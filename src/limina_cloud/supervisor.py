"""Durable project lifecycle supervisor, independent of provider adapters."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import secrets
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .codex_auth import CodexAuthManager
from .collaboration import CollaborationService
from .engines import RuntimeEngine
from .errors import AuthenticationError, LeaseConflictError, LiminaError, TransportError
from .exporter import MarkdownExporter
from .retry import RetryPolicy
from .runtime import (
    AgentFactory,
    AgentSession,
    ClaudeCodeAgentSession,
    CodexAgentSession,
    RuntimeEvent,
    RuntimeUsage,
    _redact_event,
    _redact_text,
    _redact_turn,
)
from .runtime_environment import sanitize_project_environment
from .runtime_usage import TokenPricing
from .service import ChallengeService


class _RuntimeRefreshRequested(Exception):
    """Abort a turn so changed project resources can be materialized safely."""


class ProjectSupervisor:
    """Owns every active project's autonomous lifecycle."""

    def __init__(
        self,
        service: ChallengeService,
        exporter: MarkdownExporter,
        *,
        workspace_root: Path,
        internal_url: str,
        agent_factory: AgentFactory | None = None,
        poll_interval: float = 1.0,
        lease_ttl_seconds: int = 3600,
        codex_auth: CodexAuthManager | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.service = service
        self.collaboration = CollaborationService(service.database)
        self.exporter = exporter
        self.workspace_root = workspace_root
        self.internal_url = internal_url.rstrip("/")
        self._custom_agent_factory = agent_factory is not None
        self.agent_factory = agent_factory or self._default_agent_factory
        self.poll_interval = poll_interval
        self.lease_ttl_seconds = lease_ttl_seconds
        self.codex_auth = codex_auth or CodexAuthManager.from_environment(
            Path(
                os.environ.get(
                    "CODEX_HOME",
                    str(self.workspace_root.parent / "codex"),
                )
            )
        )
        self.codex_pricing = TokenPricing.from_environment("LIMINA_CODEX")
        self.retry_policy = retry_policy or RetryPolicy.from_environment()
        self.runtime_id = f"limina:{os.getpid()}:{uuid4().hex[:8]}"
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._sessions: dict[str, AgentSession] = {}
        self._wake: dict[str, asyncio.Event] = {}
        self._live_messages: dict[str, list[dict[str, Any]]] = {}
        self._lease_lost: dict[str, asyncio.Event] = {}
        self._resource_refresh: dict[str, asyncio.Event] = {}
        self._capabilities: dict[str, tuple[str, str]] = {}
        self._active_run_ids: dict[str, str] = {}
        self._closed = False

    def configured_engines(self) -> set[str]:
        if self._custom_agent_factory:
            return {"codex", "claude-code"}
        available: set[str] = set()
        if importlib.util.find_spec("openai_codex") is not None:
            available.add("codex")
        if importlib.util.find_spec("claude_agent_sdk") is not None:
            available.add("claude-code")
        return available

    def _default_agent_factory(self, slug: str, engine: RuntimeEngine) -> AgentSession:
        if engine == "codex":
            return CodexAgentSession(
                model=os.environ.get("LIMINA_CODEX_MODEL", "gpt-5.4"),
                sandbox=os.environ.get("LIMINA_CODEX_SANDBOX", "workspace-write"),
                auth_manager=self.codex_auth,
                pricing=self.codex_pricing,
            )
        if engine != "claude-code":
            raise TransportError(f"Unsupported managed runtime engine '{engine}'.")
        config_root = Path(
            os.environ.get(
                "LIMINA_CLAUDE_CONFIG_DIR",
                str(self.workspace_root.parent / "claude"),
            )
        )
        return ClaudeCodeAgentSession(
            config_dir=config_root / slug,
            state_root=self.workspace_root.parent,
            model=os.environ.get("LIMINA_CLAUDE_MODEL") or None,
            weaker_nested_sandbox=os.environ.get("LIMINA_CLAUDE_WEAKER_NESTED_SANDBOX", "").lower()
            in {"1", "true", "yes"},
        )

    async def recover(self) -> None:
        for project in self.service.list_projects():
            if project["coordinator"]["status"] in {"RUNNING", "WAITING"}:
                await self.ensure_running(project["slug"])

    async def ensure_running(self, slug: str) -> None:
        if self._closed:
            raise RuntimeError("Project supervisor is closed.")
        task = self._tasks.get(slug)
        if task is not None and not task.done():
            self._wake_for(slug).set()
            return
        self._tasks[slug] = asyncio.create_task(self._run_project(slug), name=f"limina:{slug}")

    async def submit_message(
        self,
        *,
        slug: str,
        body: str,
        kind: str,
        actor: str,
        command_id: str | None = None,
        live_delivery: bool = True,
    ) -> dict[str, Any]:
        message = self.service.send_message(
            slug=slug,
            kind=kind,
            body=body,
            actor=actor,
            command_id=command_id or str(uuid4()),
        )
        session = self._sessions.get(slug)
        live = False
        if live_delivery and session is not None:
            if kind == "INTERRUPT":
                live = await session.interrupt()
            else:
                live = await session.steer(f"{actor}: {body}")
        if live:
            self._live_messages.setdefault(slug, []).append(message)
        self._wake_for(slug).set()
        return {"message": message, "delivery": "LIVE" if live else "QUEUED"}

    async def refresh_resources(self, slug: str) -> bool:
        """Restart active work so its child environment reflects resource changes."""
        session = self._sessions.get(slug)
        if session is None:
            self._wake_for(slug).set()
            return False
        refresh = self._resource_refresh_for(slug)
        refresh.set()
        try:
            interrupted = await session.interrupt()
        except Exception:
            interrupted = True
        if not interrupted:
            refresh.clear()
        self._wake_for(slug).set()
        return interrupted

    async def interrupt(
        self,
        slug: str,
        *,
        actor: str,
        reason: str,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        delivery = await self.submit_message(
            slug=slug,
            body=reason,
            kind="INTERRUPT",
            actor=actor,
            command_id=command_id,
        )
        project = self.service.get_challenge(slug)
        if project["coordinator"]["status"] in {"RUNNING", "WAITING"}:
            self.service.change_project_state(
                slug=slug,
                action="pause",
                actor=actor,
                command_id=f"{command_id}:pause" if command_id else str(uuid4()),
            )
        return delivery

    async def stop_runtime(self, slug: str) -> None:
        session = self._sessions.get(slug)
        if session is not None:
            await session.interrupt()
        self._wake_for(slug).set()

    async def shutdown(self) -> None:
        self._closed = True
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        for session in self._sessions.values():
            with suppress(Exception):
                await session.close()
        self._tasks.clear()
        self._sessions.clear()
        self._resource_refresh.clear()
        self.codex_auth.close()

    async def _run_project(self, slug: str) -> None:
        project = self.service.get_challenge(slug)
        session = self._sessions.setdefault(
            slug,
            self.agent_factory(slug, project["runtime_engine"]),
        )
        while not self._closed:
            status = self.service.status(slug)
            coordinator = status["challenge"]["coordinator"]
            if coordinator["status"] not in {"RUNNING", "WAITING"}:
                return
            wake_due = False
            if coordinator["wake_at"]:
                wake_at = datetime.fromisoformat(coordinator["wake_at"])
                delay = max(0.0, (wake_at - datetime.now(UTC)).total_seconds())
                if delay > 0:
                    wake = self._wake_for(slug)
                    wake.clear()
                    with suppress(TimeoutError):
                        await asyncio.wait_for(wake.wait(), timeout=delay)
                    continue
                wake_due = True
            if coordinator["status"] == "WAITING" and status["pending_inbox"] == 0 and not wake_due:
                wake = self._wake_for(slug)
                wake.clear()
                with suppress(TimeoutError):
                    await asyncio.wait_for(wake.wait(), timeout=self.poll_interval)
                continue
            try:
                retry_count = (
                    self.collaboration.next_retry_count(slug) if coordinator["wake_at"] else 0
                )
                await self._run_turn(slug, session, retry_count=retry_count)
            except _RuntimeRefreshRequested:
                self._complete_resource_refresh(slug)
                continue
            except LeaseConflictError:
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                current = self.service.get_challenge(slug)["coordinator"]
                if current["status"] in {"PAUSED", "STOPPED"}:
                    self._resource_refresh.pop(slug, None)
                    self._runtime_event(
                        slug,
                        RuntimeEvent(
                            "runtime.interrupted",
                            "The active turn was interrupted by a project lifecycle change.",
                            {"status": current["status"]},
                        ),
                    )
                    return
                if self._resource_refresh_for(slug).is_set():
                    self._complete_resource_refresh(slug)
                    continue
                retry_count = self.collaboration.next_retry_count(slug)
                retry_delay = (
                    self.retry_policy.delay_after(retry_count - 1)
                    if self.retry_policy.is_retryable(exc)
                    else None
                )
                error_detail = dict(exc.details) if isinstance(exc, LiminaError) else {}
                error_detail["error"] = (
                    exc.message
                    if isinstance(exc, LiminaError)
                    else "The managed runtime raised an unexpected internal error."
                )
                latest = self.service.get_challenge(slug)["coordinator"]
                if retry_delay is not None and latest["status"] in {"RUNNING", "WAITING"}:
                    wake_at = datetime.now(UTC) + timedelta(seconds=retry_delay)
                    self._runtime_event(
                        slug,
                        RuntimeEvent(
                            "runtime.retry_scheduled",
                            "The managed runtime hit a transient failure; "
                            "Limina scheduled a retry.",
                            {
                                **error_detail,
                                "retry_count": retry_count,
                                "wake_at": wake_at.isoformat(),
                            },
                        ),
                    )
                    self.service.checkpoint_coordinator(
                        slug=slug,
                        current_objective=latest["current_objective"],
                        next_step="Retry the managed turn after the transient provider failure.",
                        blocker=str(error_detail.get("reason") or error_detail["error"]),
                        status="WAITING",
                        worker_id=None,
                        continuation_id=latest["continuation_id"],
                        inbox_cursor=latest["inbox_cursor"],
                        expected_version=latest["version"],
                        actor=self.runtime_id,
                        command_id=str(uuid4()),
                        wake_at=wake_at,
                    )
                    continue
                self._runtime_event(
                    slug,
                    RuntimeEvent(
                        "runtime.failed",
                        "The managed runtime failed and will wait for intervention.",
                        error_detail,
                    ),
                )
                if latest["status"] in {"RUNNING", "WAITING"}:
                    with suppress(LiminaError):
                        self.service.checkpoint_coordinator(
                            slug=slug,
                            current_objective=latest["current_objective"],
                            next_step="Resolve the runtime failure and resume the project.",
                            blocker=str(error_detail.get("reason") or error_detail["error"]),
                            status="FAILED",
                            worker_id=None,
                            continuation_id=latest["continuation_id"],
                            inbox_cursor=latest["inbox_cursor"],
                            expected_version=latest["version"],
                            actor=self.runtime_id,
                            command_id=str(uuid4()),
                        )
                return

    async def _run_turn(self, slug: str, session: AgentSession, *, retry_count: int = 0) -> None:
        self.service.claim_coordinator(
            slug=slug,
            ttl_seconds=self.lease_ttl_seconds,
            actor=self.runtime_id,
            command_id=str(uuid4()),
        )
        capability = self.issue_capability(slug)
        try:
            project = self.service.get_challenge(slug)
            run_id = self.collaboration.start_run(
                slug,
                runtime_engine=project["runtime_engine"],
                model=str(getattr(session, "model", "")) or None,
                retry_count=retry_count,
            )
        except Exception:
            self._capabilities.pop(capability, None)
            with suppress(LiminaError):
                self.service.release_coordinator(
                    slug=slug,
                    actor=self.runtime_id,
                    command_id=str(uuid4()),
                )
            raise
        heartbeat = asyncio.create_task(
            self._renew_coordinator_lease(slug, session),
            name=f"limina:{slug}:lease",
        )
        self._active_run_ids[slug] = run_id
        secret_values: tuple[str, ...] = ()
        try:
            status = self.service.status(slug)
            coordinator = status["challenge"]["coordinator"]
            messages = self.service.inbox(
                slug,
                after=coordinator["inbox_cursor"],
                pending_only=True,
            )
            files = self.exporter.snapshot(slug)
            resources = self.service.list_resources(slug)
            sources = self.collaboration.sources(slug)
            resource_environment = self.service.resource_environment(slug)
            resource_environment, blocked_names = sanitize_project_environment(resource_environment)
            if blocked_names:
                self._runtime_event(
                    slug,
                    RuntimeEvent(
                        "runtime.resources_blocked",
                        "Limina ignored unsafe legacy project environment resources.",
                        {"names": blocked_names},
                    ),
                )
            secret_values = tuple(
                resource_environment[item["name"]]
                for item in resources
                if item["type"] == "SECRET" and item["name"] in resource_environment
            )
            workspace = self.workspace_root / slug
            workspace.mkdir(parents=True, exist_ok=True)
            self._runtime_event(
                slug,
                RuntimeEvent(
                    "runtime.turn_started",
                    coordinator["next_step"],
                    {"pending_messages": len(messages)},
                ),
            )
            turn = await session.run_turn(
                prompt=self._prompt(slug, files, resources, sources, messages),
                workspace=workspace,
                continuation_id=coordinator["continuation_id"],
                runtime_env=self._runtime_env(slug, resource_environment, capability),
                on_event=lambda event: self._runtime_event(
                    slug, _redact_event(event, secret_values)
                ),
                on_continuation=lambda continuation_id: self._bind_continuation(
                    slug, continuation_id
                ),
            )
            turn = _redact_turn(turn, secret_values)
            if self._resource_refresh_for(slug).is_set():
                raise _RuntimeRefreshRequested
            if self._lease_lost_for(slug).is_set():
                raise LeaseConflictError(
                    "The project runtime lost ownership while the managed turn was active.",
                    project=slug,
                )

            latest = self.service.get_challenge(slug)["coordinator"]
            live_messages = self._live_messages.pop(slug, [])
            accepted_messages = {item["id"]: item for item in [*messages, *live_messages]}
            cursor = max(
                [
                    latest["inbox_cursor"],
                    *(item["sequence"] for item in accepted_messages.values()),
                ]
            )
            if latest["status"] in {"RUNNING", "WAITING"}:
                checkpoint_status = turn.decision.status
                objective = turn.decision.current_objective
                next_step = turn.decision.next_step
                blocker = turn.decision.blocker
            else:
                checkpoint_status = latest["status"]
                objective = latest["current_objective"]
                next_step = latest["next_step"]
                blocker = latest["blocker"]
            self.service.checkpoint_coordinator(
                slug=slug,
                current_objective=objective,
                next_step=next_step,
                blocker=blocker,
                status=checkpoint_status,
                worker_id=self.runtime_id,
                continuation_id=turn.continuation_id,
                inbox_cursor=cursor,
                expected_version=latest["version"],
                acknowledge_message_ids=list(accepted_messages),
                actor=self.runtime_id,
                command_id=str(uuid4()),
            )
            self._runtime_event(
                slug,
                RuntimeEvent(
                    "runtime.turn_completed",
                    turn.decision.summary,
                    {"status": checkpoint_status},
                ),
            )
            usage = turn.usage or RuntimeUsage()
            self.collaboration.finish_run(
                run_id,
                status="COMPLETED",
                summary=turn.decision.summary,
                turn_id=turn.turn_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                reasoning_output_tokens=usage.reasoning_output_tokens,
                total_tokens=usage.total_tokens,
                cost_microusd=usage.cost_microusd,
                usage_source=usage.usage_source,
                cost_source=usage.cost_source,
            )
        except asyncio.CancelledError:
            self.collaboration.finish_run(
                run_id, status="INTERRUPTED", summary="Runtime task was cancelled."
            )
            raise
        except _RuntimeRefreshRequested:
            self.collaboration.finish_run(
                run_id,
                status="INTERRUPTED",
                summary="Project resources changed during the turn.",
            )
            raise
        except Exception as exc:
            latest_status = self.service.get_challenge(slug)["coordinator"]["status"]
            interrupted = latest_status in {"PAUSED", "STOPPED"}
            error_text = _redact_text(
                exc.message if isinstance(exc, LiminaError) else str(exc), secret_values
            )
            summary = (
                "The managed turn was interrupted by a lifecycle change."
                if interrupted
                else "The managed turn failed before checkpointing."
            )
            self._runtime_event(
                slug,
                RuntimeEvent(
                    "runtime.turn_interrupted" if interrupted else "runtime.turn_failed",
                    summary,
                    {"error": error_text},
                ),
            )
            self.collaboration.finish_run(
                run_id,
                status="INTERRUPTED" if interrupted else "FAILED",
                summary=summary,
                error_code=None
                if interrupted
                else exc.code
                if isinstance(exc, LiminaError)
                else "runtime_error",
                error_message=None if interrupted else error_text,
            )
            if interrupted:
                raise
            raise
        finally:
            self._active_run_ids.pop(slug, None)
            self._capabilities.pop(capability, None)
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            self._lease_lost.pop(slug, None)
            with suppress(LiminaError):
                self.service.release_coordinator(
                    slug=slug,
                    actor=self.runtime_id,
                    command_id=str(uuid4()),
                )

    async def _renew_coordinator_lease(self, slug: str, session: AgentSession) -> None:
        interval = max(10.0, self.lease_ttl_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                await asyncio.to_thread(
                    self.service.claim_coordinator,
                    slug=slug,
                    ttl_seconds=self.lease_ttl_seconds,
                    actor=self.runtime_id,
                    command_id=str(uuid4()),
                )
            except Exception as exc:
                self._lease_lost_for(slug).set()
                self._runtime_event(
                    slug,
                    RuntimeEvent(
                        "runtime.lease_lost",
                        "The runtime lost exclusive ownership of the project turn.",
                        {"error": str(exc)},
                    ),
                )
                with suppress(Exception):
                    await session.interrupt()
                return

    def _runtime_event(self, slug: str, event: RuntimeEvent) -> None:
        run_id = self._active_run_ids.get(slug)
        payload = {"summary": event.summary, **event.detail}
        if run_id:
            payload["run_id"] = run_id
            method = str(event.detail.get("method", ""))
            item_type = str(event.detail.get("item_type", ""))
            self.collaboration.note_run_event(
                run_id,
                tool_call=method == "tool/use"
                or (method == "item/started" and "command" in item_type.lower()),
            )
        self.service.record_runtime_event(
            slug=slug,
            event_type=event.event_type,
            payload=payload,
            actor=self.runtime_id,
            command_id=str(uuid4()),
        )

    def _bind_continuation(self, slug: str, continuation_id: str) -> None:
        """Persist SDK continuity before any tools run; never expose it publicly."""
        coordinator = self.service.get_challenge(slug)["coordinator"]
        if coordinator["continuation_id"] == continuation_id:
            return
        self.service.checkpoint_coordinator(
            slug=slug,
            current_objective=coordinator["current_objective"],
            next_step=coordinator["next_step"],
            blocker=coordinator["blocker"],
            status=coordinator["status"],
            worker_id=self.runtime_id,
            continuation_id=continuation_id,
            inbox_cursor=coordinator["inbox_cursor"],
            expected_version=coordinator["version"],
            actor=self.runtime_id,
            command_id=str(uuid4()),
        )

    def issue_capability(self, slug: str) -> str:
        token = secrets.token_urlsafe(32)
        self._capabilities[token] = (slug, self.runtime_id)
        return token

    def capability_actor(self, token: str, slug: str, lane: str | None = None) -> str:
        capability = self._capabilities.get(token)
        if capability is None or capability[0] != slug:
            raise AuthenticationError("The internal project capability is invalid or expired.")
        actor = capability[1]
        if lane:
            normalized = "".join(
                character for character in lane if character.isalnum() or character in "-_"
            )
            if not normalized or normalized != lane or len(lane) > 64:
                raise AuthenticationError("The internal agent lane is invalid.")
            actor = f"{actor}:{lane}"
        return actor

    def _runtime_env(
        self,
        slug: str,
        resource_environment: dict[str, str],
        capability: str,
    ) -> dict[str, str]:
        env = {
            "LIMINA_INTERNAL_URL": self.internal_url,
            "LIMINA_INTERNAL_TOKEN": capability,
            "LIMINA_PROJECT": slug,
            "LIMINA_CHALLENGE": slug,
            "LIMINA_ACTOR": self.runtime_id,
        }
        safe_resources, _blocked = sanitize_project_environment(resource_environment)
        env.update(safe_resources)
        return env

    def _wake_for(self, slug: str) -> asyncio.Event:
        return self._wake.setdefault(slug, asyncio.Event())

    def _lease_lost_for(self, slug: str) -> asyncio.Event:
        return self._lease_lost.setdefault(slug, asyncio.Event())

    def _resource_refresh_for(self, slug: str) -> asyncio.Event:
        return self._resource_refresh.setdefault(slug, asyncio.Event())

    def _complete_resource_refresh(self, slug: str) -> None:
        self._resource_refresh.pop(slug, None)
        self._runtime_event(
            slug,
            RuntimeEvent(
                "runtime.resources_refreshed",
                "Restarting the managed turn with updated project resources.",
                {},
            ),
        )

    @staticmethod
    def _prompt(
        slug: str,
        files: dict[str, str],
        resources: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> str:
        resource_lines = (
            "\n".join(
                (
                    f"- VARIABLE {item['name']}={json.dumps(item['value'], ensure_ascii=False)}"
                    if item["type"] == "VARIABLE"
                    else f"- SECRET {item['name']} (configured; value hidden)"
                )
                for item in resources
            )
            or "- No project resources have been provided."
        )
        message_lines = (
            "\n".join(
                f"- #{item['sequence']} [{item['kind']}] {item['actor']}: {item['body']}"
                for item in messages
            )
            or "- No new human guidance."
        )
        source_lines = (
            "\n".join(
                f"- {item['type']} {item['name']}: {item['uri']}"
                + (f" ({item['media_type']})" if item["media_type"] else "")
                for item in sources
            )
            or "- No project sources have been registered."
        )
        return f"""You are Limina, the autonomous research runtime for project `{slug}`.

Own the project. The user is not responsible for sessions, subagents, thread recovery, experiment
leases, or checkpoints. Advance one substantive research checkpoint toward the mission. Use the
selected engine's subagents internally when independent work benefits from parallelism. Use the
hidden `limina _agent ...` commands for durable hypotheses, experiments, observations, and findings;
start with `limina _agent status` and inspect help only for the specific command you need. Do not
invoke or inspect a Limina bootstrap/setup skill: this project is already managed by the runtime.
Never ask the user to operate internal commands. Persist decisive knowledge before ending the turn.

Human steering may arrive during this turn. Incorporate it immediately unless safety requires an
explicit interruption. Ask the user only for mission decisions, feedback, approvals, or missing
resource access. Your final response must satisfy the provided structured checkpoint schema.
Treat SECRET resources as sensitive: never print them, include their values in command arguments,
persist them to files or knowledge, or repeat them in messages. Reference secret environment
variables by name and disclose their values only to the intended authenticated service.

## Mission

{files["mission/CHALLENGE.md"]}

## Active state

{files["ACTIVE.md"]}

## Resources

{resource_lines}

## Sources

{source_lines}

## New human guidance

{message_lines}
"""
