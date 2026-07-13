"""Project-owned Codex runtime and durable supervisor.

Users operate projects. This module owns every session, turn, lease, retry,
workspace, and checkpoint needed to keep those projects running.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .errors import AuthenticationError, LeaseConflictError, LiminaError, TransportError
from .exporter import MarkdownExporter
from .service import ChallengeService

TURN_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "status": {"type": "string", "enum": ["RUNNING", "WAITING", "COMPLETE"]},
        "current_objective": {"type": "string"},
        "next_step": {"type": "string"},
        "blocker": {"type": "string"},
    },
    "required": ["summary", "status", "current_objective", "next_step", "blocker"],
}

SAFE_CODEX_ENV = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "CODEX_CI",
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
        "CODEX_PERMISSION_PROFILE",
        "CODEX_SHELL",
        "COLORTERM",
        "PATH",
        "SHELL",
        "SSL_CERT_FILE",
        "TERM",
        "TMPDIR",
        "USER",
    }
)


def _codex_environment(runtime_env: dict[str, str]) -> dict[str, str]:
    """Build a child environment without inheriting control-plane secrets."""
    # The SDK starts app-server from a copy of the parent environment and then
    # overlays CodexConfig.env. Empty every unapproved value explicitly.
    env = {name: "" for name in os.environ if name not in SAFE_CODEX_ENV}
    env.update({name: value for name, value in os.environ.items() if name in SAFE_CODEX_ENV})
    env.update(runtime_env)
    return env


@dataclass(frozen=True)
class RuntimeDecision:
    summary: str
    status: str
    current_objective: str
    next_step: str
    blocker: str


@dataclass(frozen=True)
class RuntimeTurn:
    thread_id: str
    turn_id: str
    decision: RuntimeDecision


@dataclass(frozen=True)
class RuntimeEvent:
    event_type: str
    summary: str
    detail: dict[str, Any]


def _redact_text(value: str, secret_values: tuple[str, ...]) -> str:
    redacted = value
    for secret in sorted((item for item in secret_values if item), key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _redact_value(value: Any, secret_values: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return _redact_text(value, secret_values)
    if isinstance(value, dict):
        return {key: _redact_value(item, secret_values) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, secret_values) for item in value]
    return value


def _redact_event(event: RuntimeEvent, secret_values: tuple[str, ...]) -> RuntimeEvent:
    return RuntimeEvent(
        event.event_type,
        _redact_text(event.summary, secret_values),
        _redact_value(event.detail, secret_values),
    )


def _redact_turn(turn: RuntimeTurn, secret_values: tuple[str, ...]) -> RuntimeTurn:
    decision = turn.decision
    return RuntimeTurn(
        thread_id=turn.thread_id,
        turn_id=turn.turn_id,
        decision=RuntimeDecision(
            summary=_redact_text(decision.summary, secret_values),
            status=decision.status,
            current_objective=_redact_text(decision.current_objective, secret_values),
            next_step=_redact_text(decision.next_step, secret_values),
            blocker=_redact_text(decision.blocker, secret_values),
        ),
    )


EventSink = Callable[[RuntimeEvent], None]
ThreadSink = Callable[[str], None]


class AgentSession(Protocol):
    async def run_turn(
        self,
        *,
        prompt: str,
        workspace: Path,
        thread_id: str | None,
        runtime_env: dict[str, str],
        on_event: EventSink,
        on_thread: ThreadSink,
    ) -> RuntimeTurn: ...

    async def steer(self, message: str) -> bool: ...

    async def interrupt(self) -> bool: ...

    async def close(self) -> None: ...


AgentFactory = Callable[[str], AgentSession]


class CodexAgentSession:
    """Official Codex SDK adapter hidden behind the project runtime contract."""

    def __init__(self, *, model: str = "gpt-5.4", sandbox: str = "workspace-write") -> None:
        self.model = model
        self.sandbox = sandbox
        self._handle: Any | None = None
        self._handle_lock = threading.Lock()

    async def run_turn(
        self,
        *,
        prompt: str,
        workspace: Path,
        thread_id: str | None,
        runtime_env: dict[str, str],
        on_event: EventSink,
        on_thread: ThreadSink,
    ) -> RuntimeTurn:
        return await asyncio.to_thread(
            self._run_turn_sync,
            prompt,
            workspace,
            thread_id,
            runtime_env,
            on_event,
            on_thread,
        )

    def _run_turn_sync(
        self,
        prompt: str,
        workspace: Path,
        thread_id: str | None,
        runtime_env: dict[str, str],
        on_event: EventSink,
        on_thread: ThreadSink,
    ) -> RuntimeTurn:
        try:
            from openai_codex import Codex, CodexConfig, Sandbox
            from openai_codex._run import _collect_turn_result
        except ImportError as exc:
            raise TransportError(
                "The Limina runtime image does not include the Codex SDK.",
                suggestion="Install the project with the 'codex' extra.",
            ) from exc

        sandbox_by_name = {
            "read-only": Sandbox.read_only,
            "workspace-write": Sandbox.workspace_write,
            "full-access": Sandbox.full_access,
        }
        selected_sandbox = sandbox_by_name.get(self.sandbox)
        if selected_sandbox is None:
            raise TransportError(f"Unsupported Codex sandbox '{self.sandbox}'.")

        env = _codex_environment(runtime_env)
        config_overrides = (
            ("sandbox_workspace_write.network_access=true",)
            if self.sandbox == "workspace-write"
            else ()
        )
        try:
            with Codex(
                CodexConfig(
                    cwd=str(workspace),
                    env=env,
                    config_overrides=config_overrides,
                )
            ) as codex:
                if thread_id:
                    thread = codex.thread_resume(
                        thread_id,
                        cwd=str(workspace),
                        model=self.model,
                        sandbox=selected_sandbox,
                    )
                else:
                    thread = codex.thread_start(
                        cwd=str(workspace),
                        model=self.model,
                        sandbox=selected_sandbox,
                    )
                on_thread(thread.id)
                handle = thread.turn(prompt, output_schema=TURN_OUTPUT_SCHEMA)
                with self._handle_lock:
                    self._handle = handle
                try:
                    result = _collect_turn_result(
                        self._tap_stream(handle.stream(), on_event),
                        turn_id=handle.id,
                    )
                finally:
                    with self._handle_lock:
                        self._handle = None
        except LiminaError:
            raise
        except Exception as exc:
            raise TransportError(
                "The managed Codex turn failed before Limina accepted its checkpoint.",
                reason=str(exc),
                thread_id=thread_id,
            ) from exc

        if not result.final_response:
            raise TransportError(
                "Codex completed without the required project decision.",
                thread_id=thread.id,
                turn_id=result.id,
            )
        decision = self._parse_decision(result.final_response)
        return RuntimeTurn(thread.id, result.id, decision)

    @staticmethod
    def _tap_stream(events: Iterator[Any], on_event: EventSink) -> Iterator[Any]:
        for event in events:
            mapped = _map_codex_notification(event)
            if mapped is not None:
                on_event(mapped)
            yield event

    @staticmethod
    def _parse_decision(response: str) -> RuntimeDecision:
        try:
            value = json.loads(response)
            decision = RuntimeDecision(
                summary=str(value["summary"]).strip(),
                status=str(value["status"]).upper(),
                current_objective=str(value["current_objective"]).strip(),
                next_step=str(value["next_step"]).strip(),
                blocker=str(value["blocker"]).strip() or "None",
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TransportError(
                "Codex returned an invalid project checkpoint.",
                response=response[:1000],
            ) from exc
        if decision.status not in {"RUNNING", "WAITING", "COMPLETE"}:
            raise TransportError(f"Codex returned unsupported project status '{decision.status}'.")
        if not decision.summary or not decision.current_objective or not decision.next_step:
            raise TransportError("Codex returned an incomplete project checkpoint.")
        return decision

    async def steer(self, message: str) -> bool:
        def steer_active_turn() -> bool:
            with self._handle_lock:
                handle = self._handle
            if handle is None:
                return False
            handle.steer(message)
            return True

        return await asyncio.to_thread(steer_active_turn)

    async def interrupt(self) -> bool:
        def interrupt_active_turn() -> bool:
            with self._handle_lock:
                handle = self._handle
            if handle is None:
                return False
            handle.interrupt()
            return True

        return await asyncio.to_thread(interrupt_active_turn)

    async def close(self) -> None:
        await self.interrupt()


def _map_codex_notification(notification: Any) -> RuntimeEvent | None:
    method = str(getattr(notification, "method", "codex/event"))
    if method not in {
        "turn/started",
        "turn/completed",
        "item/started",
        "item/completed",
        "error",
    }:
        return None
    payload = getattr(notification, "payload", None)
    item = getattr(payload, "item", None)
    root = getattr(item, "root", item)
    item_type = type(root).__name__ if root is not None else None
    if item_type in {"ReasoningThreadItem", "UserMessageThreadItem"}:
        return None
    if item_type == "AgentMessageThreadItem" and method == "item/started":
        return None
    text = getattr(root, "text", None)
    command = getattr(root, "command", None)
    name = getattr(root, "name", None)
    summary = text or command or name or item_type or method
    return RuntimeEvent(
        event_type="runtime.codex",
        summary=str(summary)[:1000],
        detail={"method": method, "item_type": item_type},
    )


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
    ) -> None:
        self.service = service
        self.exporter = exporter
        self.workspace_root = workspace_root
        self.internal_url = internal_url.rstrip("/")
        self.agent_factory = agent_factory or (
            lambda _slug: CodexAgentSession(
                model=os.environ.get("LIMINA_CODEX_MODEL", "gpt-5.4"),
                sandbox=os.environ.get("LIMINA_CODEX_SANDBOX", "workspace-write"),
            )
        )
        self.poll_interval = poll_interval
        self.lease_ttl_seconds = lease_ttl_seconds
        self.runtime_id = f"limina:{os.getpid()}:{uuid4().hex[:8]}"
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._sessions: dict[str, AgentSession] = {}
        self._wake: dict[str, asyncio.Event] = {}
        self._live_messages: dict[str, list[dict[str, Any]]] = {}
        self._lease_lost: dict[str, asyncio.Event] = {}
        self._capabilities: dict[str, tuple[str, str]] = {}
        self._closed = False

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
        if session is not None:
            if kind == "INTERRUPT":
                live = await session.interrupt()
            else:
                live = await session.steer(f"{actor}: {body}")
        if live:
            self._live_messages.setdefault(slug, []).append(message)
        self._wake_for(slug).set()
        return {"message": message, "delivery": "LIVE" if live else "QUEUED"}

    async def interrupt(self, slug: str, *, actor: str, reason: str) -> dict[str, Any]:
        delivery = await self.submit_message(
            slug=slug,
            body=reason,
            kind="INTERRUPT",
            actor=actor,
        )
        project = self.service.get_challenge(slug)
        if project["coordinator"]["status"] in {"RUNNING", "WAITING"}:
            self.service.change_project_state(
                slug=slug,
                action="pause",
                actor=actor,
                command_id=str(uuid4()),
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

    async def _run_project(self, slug: str) -> None:
        session = self._sessions.setdefault(slug, self.agent_factory(slug))
        while not self._closed:
            status = self.service.status(slug)
            coordinator = status["challenge"]["coordinator"]
            if coordinator["status"] not in {"RUNNING", "WAITING"}:
                return
            if coordinator["status"] == "WAITING" and status["pending_inbox"] == 0:
                wake = self._wake_for(slug)
                wake.clear()
                with suppress(TimeoutError):
                    await asyncio.wait_for(wake.wait(), timeout=self.poll_interval)
                continue
            try:
                await self._run_turn(slug, session)
            except LeaseConflictError:
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                current = self.service.get_challenge(slug)["coordinator"]
                if current["status"] in {"PAUSED", "STOPPED"}:
                    self._runtime_event(
                        slug,
                        RuntimeEvent(
                            "runtime.interrupted",
                            "The active turn was interrupted by a project lifecycle change.",
                            {"status": current["status"]},
                        ),
                    )
                    return
                error_detail = dict(exc.details) if isinstance(exc, LiminaError) else {}
                error_detail["error"] = exc.message if isinstance(exc, LiminaError) else str(exc)
                self._runtime_event(
                    slug,
                    RuntimeEvent(
                        "runtime.failed",
                        "The managed runtime failed and will wait for intervention.",
                        error_detail,
                    ),
                )
                latest = self.service.get_challenge(slug)["coordinator"]
                if latest["status"] in {"RUNNING", "WAITING"}:
                    with suppress(LiminaError):
                        self.service.checkpoint_coordinator(
                            slug=slug,
                            current_objective=latest["current_objective"],
                            next_step="Resolve the runtime failure and resume the project.",
                            blocker=str(error_detail.get("reason") or error_detail["error"]),
                            status="FAILED",
                            worker_id=None,
                            thread_id=latest["thread_id"],
                            inbox_cursor=latest["inbox_cursor"],
                            expected_version=latest["version"],
                            actor=self.runtime_id,
                            command_id=str(uuid4()),
                        )
                return

    async def _run_turn(self, slug: str, session: AgentSession) -> None:
        self.service.claim_coordinator(
            slug=slug,
            ttl_seconds=self.lease_ttl_seconds,
            actor=self.runtime_id,
            command_id=str(uuid4()),
        )
        capability = self.issue_capability(slug)
        heartbeat = asyncio.create_task(
            self._renew_coordinator_lease(slug, session),
            name=f"limina:{slug}:lease",
        )
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
            resource_environment = self.service.resource_environment(slug)
            secret_values = tuple(
                resource_environment[item["name"]] for item in resources if item["type"] == "SECRET"
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
                prompt=self._prompt(slug, files, resources, messages),
                workspace=workspace,
                thread_id=coordinator["thread_id"],
                runtime_env=self._runtime_env(slug, resource_environment, capability),
                on_event=lambda event: self._runtime_event(
                    slug, _redact_event(event, secret_values)
                ),
                on_thread=lambda thread_id: self._bind_thread(slug, thread_id),
            )
            turn = _redact_turn(turn, secret_values)
            if self._lease_lost_for(slug).is_set():
                raise LeaseConflictError(
                    "The project runtime lost ownership while the Codex turn was active.",
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
                thread_id=turn.thread_id,
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
        finally:
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
        self.service.record_runtime_event(
            slug=slug,
            event_type=event.event_type,
            payload={"summary": event.summary, **event.detail},
            actor=self.runtime_id,
            command_id=str(uuid4()),
        )

    def _bind_thread(self, slug: str, thread_id: str) -> None:
        """Persist SDK continuity before any tools run; never expose it publicly."""
        coordinator = self.service.get_challenge(slug)["coordinator"]
        if coordinator["thread_id"] == thread_id:
            return
        self.service.checkpoint_coordinator(
            slug=slug,
            current_objective=coordinator["current_objective"],
            next_step=coordinator["next_step"],
            blocker=coordinator["blocker"],
            status=coordinator["status"],
            worker_id=self.runtime_id,
            thread_id=thread_id,
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
        env.update(resource_environment)
        return env

    def _wake_for(self, slug: str) -> asyncio.Event:
        return self._wake.setdefault(slug, asyncio.Event())

    def _lease_lost_for(self, slug: str) -> asyncio.Event:
        return self._lease_lost.setdefault(slug, asyncio.Event())

    @staticmethod
    def _prompt(
        slug: str,
        files: dict[str, str],
        resources: list[dict[str, Any]],
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
        return f"""You are Limina, the autonomous research runtime for project `{slug}`.

Own the project. The user is not responsible for sessions, subagents, thread recovery, experiment
leases, or checkpoints. Advance one substantive research checkpoint toward the mission. Use
Codex subagents internally when independent work benefits from parallelism. Use the hidden
`limina _agent ...` commands for durable hypotheses, experiments, observations, and findings;
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

## New human guidance

{message_lines}
"""
