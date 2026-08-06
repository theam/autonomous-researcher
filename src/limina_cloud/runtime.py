"""Project-owned agent runtimes and durable supervisor.

Users operate projects. This module owns every session, turn, lease, retry,
workspace, and checkpoint needed to keep those projects running.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .codex_auth import CodexAuthManager
from .engines import RuntimeEngine
from .errors import LiminaError, TransportError
from .runtime_environment import (
    claude_environment,
    codex_environment,
)
from .runtime_usage import RuntimeUsage, TokenPricing, usage_from_result

TURN_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "status": {"type": "string", "enum": ["RUNNING", "WAITING", "COMPLETE"]},
        "current_objective": {"type": "string"},
        "next_step": {"type": "string"},
        "blocker": {"type": "string"},
        "attention_request": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["QUESTION", "APPROVAL", "REVIEW", "BLOCKER"],
                        },
                        "response_mode": {
                            "type": "string",
                            "enum": ["TEXT", "CHOICE", "CONFIRMATION", "ARTIFACT_REVIEW"],
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        },
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "choices": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 12,
                        },
                        "artifact_id": {"type": ["string", "null"]},
                        "artifact_version": {"type": ["integer", "null"], "minimum": 1},
                    },
                    "required": [
                        "kind",
                        "response_mode",
                        "priority",
                        "title",
                        "body",
                        "choices",
                        "artifact_id",
                        "artifact_version",
                    ],
                },
            ]
        },
    },
    "required": [
        "summary",
        "status",
        "current_objective",
        "next_step",
        "blocker",
        "attention_request",
    ],
}


def _codex_environment(
    runtime_env: dict[str, str], codex_home: Path | None = None
) -> dict[str, str]:
    """Compatibility wrapper for tests and adapters; auth state is always pinned."""
    home = codex_home or Path(".limina/codex")
    return codex_environment(runtime_env, home)


def _claude_environment(runtime_env: dict[str, str], config_dir: Path) -> dict[str, str]:
    return claude_environment(runtime_env, config_dir)


def _claude_settings_path(config_dir: Path) -> Path:
    """Keep resumable sessions well beyond Claude Code's interactive default."""
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.chmod(0o700)
    path = config_dir / "limina-settings.json"
    content = json.dumps({"cleanupPeriodDays": 3650}, sort_keys=True) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


@dataclass(frozen=True)
class RuntimeAttentionRequest:
    kind: str
    response_mode: str
    priority: str
    title: str
    body: str
    choices: tuple[str, ...] = ()
    artifact_id: str | None = None
    artifact_version: int | None = None


@dataclass(frozen=True)
class RuntimeDecision:
    summary: str
    status: str
    current_objective: str
    next_step: str
    blocker: str
    attention_request: RuntimeAttentionRequest | None = None


@dataclass(frozen=True)
class RuntimeTurn:
    continuation_id: str
    turn_id: str
    decision: RuntimeDecision
    usage: RuntimeUsage | None = None


@dataclass(frozen=True)
class RuntimeEvent:
    event_type: str
    summary: str
    detail: dict[str, Any]


def _parse_runtime_decision(response: str | dict[str, Any], *, provider: str) -> RuntimeDecision:
    try:
        value = json.loads(response) if isinstance(response, str) else response
        request_value = value.get("attention_request")
        attention_request = None
        if request_value is not None:
            attention_request = RuntimeAttentionRequest(
                kind=str(request_value["kind"]).upper(),
                response_mode=str(request_value["response_mode"]).upper(),
                priority=str(request_value["priority"]).upper(),
                title=str(request_value["title"]).strip(),
                body=str(request_value["body"]).strip(),
                choices=tuple(str(item).strip() for item in request_value.get("choices", [])),
                artifact_id=(
                    str(request_value["artifact_id"]).strip().upper()
                    if request_value.get("artifact_id")
                    else None
                ),
                artifact_version=(
                    int(request_value["artifact_version"])
                    if request_value.get("artifact_version") is not None
                    else None
                ),
            )
        decision = RuntimeDecision(
            summary=str(value["summary"]).strip(),
            status=str(value["status"]).upper(),
            current_objective=str(value["current_objective"]).strip(),
            next_step=str(value["next_step"]).strip(),
            blocker=str(value["blocker"]).strip() or "None",
            attention_request=attention_request,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TransportError(f"{provider} returned an invalid project checkpoint.") from exc
    if decision.status not in {"RUNNING", "WAITING", "COMPLETE"}:
        raise TransportError(f"{provider} returned unsupported project status '{decision.status}'.")
    if not decision.summary or not decision.current_objective or not decision.next_step:
        raise TransportError(f"{provider} returned an incomplete project checkpoint.")
    request = decision.attention_request
    if request is not None:
        if decision.status != "WAITING":
            raise TransportError(
                f"{provider} returned an attention request without waiting for its resolution."
            )
        if request.kind not in {"QUESTION", "APPROVAL", "REVIEW", "BLOCKER"}:
            raise TransportError(f"{provider} returned an unsupported attention request kind.")
        if request.response_mode not in {"TEXT", "CHOICE", "CONFIRMATION", "ARTIFACT_REVIEW"}:
            raise TransportError(f"{provider} returned an unsupported attention response mode.")
        if request.priority not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
            raise TransportError(f"{provider} returned an unsupported attention priority.")
        if not request.title or not request.body:
            raise TransportError(f"{provider} returned an incomplete attention request.")
        if request.response_mode == "CHOICE" and not request.choices:
            raise TransportError(f"{provider} returned a choice request without choices.")
        if request.response_mode != "CHOICE" and request.choices:
            raise TransportError(f"{provider} returned choices for a non-choice request.")
        if (request.artifact_id is None) != (request.artifact_version is None):
            raise TransportError(
                f"{provider} must provide both artifact ID and version for a pinned request."
            )
    return decision


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
    request = decision.attention_request
    return RuntimeTurn(
        continuation_id=turn.continuation_id,
        turn_id=turn.turn_id,
        decision=RuntimeDecision(
            summary=_redact_text(decision.summary, secret_values),
            status=decision.status,
            current_objective=_redact_text(decision.current_objective, secret_values),
            next_step=_redact_text(decision.next_step, secret_values),
            blocker=_redact_text(decision.blocker, secret_values),
            attention_request=(
                RuntimeAttentionRequest(
                    kind=request.kind,
                    response_mode=request.response_mode,
                    priority=request.priority,
                    title=_redact_text(request.title, secret_values),
                    body=_redact_text(request.body, secret_values),
                    choices=tuple(_redact_text(item, secret_values) for item in request.choices),
                    artifact_id=request.artifact_id,
                    artifact_version=request.artifact_version,
                )
                if request is not None
                else None
            ),
        ),
        usage=turn.usage,
    )


def _usage_from_result(result: Any, *, pricing: TokenPricing | None = None) -> RuntimeUsage | None:
    """Compatibility alias for the focused usage normalizer."""
    return usage_from_result(result, pricing=pricing)


EventSink = Callable[[RuntimeEvent], None]
ContinuationSink = Callable[[str], None]


class AgentSession(Protocol):
    async def run_turn(
        self,
        *,
        prompt: str,
        workspace: Path,
        continuation_id: str | None,
        runtime_env: dict[str, str],
        on_event: EventSink,
        on_continuation: ContinuationSink,
    ) -> RuntimeTurn: ...

    async def steer(self, message: str) -> bool: ...

    async def interrupt(self) -> bool: ...

    async def close(self) -> None: ...


AgentFactory = Callable[[str, RuntimeEngine], AgentSession]


class CodexAgentSession:
    """Official Codex SDK adapter hidden behind the project runtime contract."""

    def __init__(
        self,
        *,
        model: str = "gpt-5.4",
        sandbox: str = "workspace-write",
        auth_manager: CodexAuthManager | None = None,
        pricing: TokenPricing | None = None,
    ) -> None:
        self.model = model
        self.sandbox = sandbox
        self.auth_manager = auth_manager or CodexAuthManager.from_environment(
            Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        )
        self.pricing = pricing
        self._handle: Any | None = None
        self._handle_lock = threading.Lock()

    async def run_turn(
        self,
        *,
        prompt: str,
        workspace: Path,
        continuation_id: str | None,
        runtime_env: dict[str, str],
        on_event: EventSink,
        on_continuation: ContinuationSink,
    ) -> RuntimeTurn:
        return await asyncio.to_thread(
            self._run_turn_sync,
            prompt,
            workspace,
            continuation_id,
            runtime_env,
            on_event,
            on_continuation,
        )

    def _run_turn_sync(
        self,
        prompt: str,
        workspace: Path,
        continuation_id: str | None,
        runtime_env: dict[str, str],
        on_event: EventSink,
        on_continuation: ContinuationSink,
    ) -> RuntimeTurn:
        try:
            from openai_codex import Codex, CodexConfig, Sandbox, is_retryable_error
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

        env = _codex_environment(runtime_env, self.auth_manager.home)
        config_overrides = (
            ("sandbox_workspace_write.network_access=true",)
            if self.sandbox == "workspace-write"
            else ()
        )
        try:
            with (
                self.auth_manager.turn(),
                Codex(
                    CodexConfig(
                        cwd=str(workspace),
                        env=env,
                        config_overrides=config_overrides,
                    )
                ) as codex,
            ):
                if continuation_id:
                    thread = codex.thread_resume(
                        continuation_id,
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
                on_continuation(thread.id)
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
                reason=_redact_text(str(exc), tuple(runtime_env.values())),
                continuation_id=continuation_id,
                retryable=bool(is_retryable_error(exc)),
            ) from exc

        if not result.final_response:
            raise TransportError(
                "Codex completed without the required project decision.",
                continuation_id=thread.id,
                turn_id=result.id,
            )
        decision = _parse_runtime_decision(result.final_response, provider="Codex")
        return RuntimeTurn(
            thread.id,
            result.id,
            decision,
            _usage_from_result(result, pricing=self.pricing),
        )

    @staticmethod
    def _tap_stream(events: Iterator[Any], on_event: EventSink) -> Iterator[Any]:
        for event in events:
            mapped = _map_codex_notification(event)
            if mapped is not None:
                on_event(mapped)
            yield event

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


class ClaudeCodeAgentSession:
    """Claude Agent SDK adapter with resumable, Limina-owned session state."""

    def __init__(
        self,
        *,
        config_dir: Path,
        state_root: Path,
        model: str | None = None,
        weaker_nested_sandbox: bool = False,
    ) -> None:
        self.config_dir = config_dir
        self.state_root = state_root
        self.model = model or None
        self.weaker_nested_sandbox = weaker_nested_sandbox
        self._client: Any | None = None
        self._active = False
        self._query_active = False
        self._stop_requested = False
        self._steering: asyncio.Queue[str] = asyncio.Queue()

    async def run_turn(
        self,
        *,
        prompt: str,
        workspace: Path,
        continuation_id: str | None,
        runtime_env: dict[str, str],
        on_event: EventSink,
        on_continuation: ContinuationSink,
    ) -> RuntimeTurn:
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ClaudeSDKClient,
                PermissionResultAllow,
                PermissionResultDeny,
                ResultMessage,
            )
        except ImportError as exc:
            raise TransportError(
                "The Limina runtime image does not include the Claude Agent SDK.",
                suggestion="Install the project with the 'claude' extra.",
            ) from exc

        settings_path = _claude_settings_path(self.config_dir)
        workspace_root = workspace.resolve()
        protected_roots = sorted(
            {
                str(self.state_root.resolve()),
                str(self.config_dir.parent.resolve()),
            }
        )

        async def can_use_tool(tool_name: str, input_data: dict[str, Any], _context: Any) -> Any:
            if tool_name == "Bash" and input_data.get("dangerouslyDisableSandbox"):
                return PermissionResultDeny(
                    message="Limina does not permit commands outside the project sandbox.",
                    interrupt=False,
                )
            path_key = {
                "Read": "file_path",
                "Write": "file_path",
                "Edit": "file_path",
                "NotebookEdit": "notebook_path",
                "Glob": "path",
                "Grep": "path",
            }.get(tool_name)
            if path_key and (raw_path := input_data.get(path_key)):
                candidate = Path(str(raw_path))
                if not candidate.is_absolute():
                    candidate = workspace_root / candidate
                try:
                    candidate.resolve().relative_to(workspace_root)
                except (OSError, RuntimeError, ValueError):
                    return PermissionResultDeny(
                        message="Limina restricts file access to this project's workspace.",
                        interrupt=False,
                    )
            return PermissionResultAllow(updated_input=input_data)

        options = ClaudeAgentOptions(
            tools={"type": "preset", "preset": "claude_code"},
            system_prompt={"type": "preset", "preset": "claude_code"},
            permission_mode="default",
            can_use_tool=can_use_tool,
            sandbox={
                "enabled": True,
                "failIfUnavailable": True,
                "autoAllowBashIfSandboxed": True,
                "allowUnsandboxedCommands": False,
                "enableWeakerNestedSandbox": self.weaker_nested_sandbox,
                "filesystem": {
                    "denyRead": protected_roots,
                    "allowRead": [str(workspace_root)],
                },
            },
            setting_sources=[],
            cwd=workspace,
            settings=str(settings_path),
            env=_claude_environment(runtime_env, self.config_dir),
            resume=continuation_id,
            model=self.model,
            output_format={"type": "json_schema", "schema": TURN_OUTPUT_SCHEMA},
        )
        client = ClaudeSDKClient(options=options)
        self._client = client
        self._active = True
        self._stop_requested = False
        try:
            await client.connect()
            next_prompt = prompt
            while True:
                self._query_active = True
                try:
                    await client.query(next_prompt)
                    result: Any | None = None
                    turn_id: str | None = None
                    async for message in client.receive_response():
                        session_id = _claude_session_id(message)
                        if session_id:
                            on_continuation(session_id)
                        if isinstance(message, AssistantMessage) and message.message_id:
                            turn_id = message.message_id
                        if isinstance(message, ResultMessage):
                            result = message
                        mapped = _map_claude_message(message)
                        if mapped is not None:
                            on_event(mapped)
                finally:
                    self._query_active = False

                steering = self._drain_steering()
                if steering and not self._stop_requested:
                    next_prompt = (
                        "Human steering arrived while you were working. Incorporate it now and "
                        "continue the same Limina checkpoint:\n\n- " + "\n- ".join(steering)
                    )
                    continue
                if self._stop_requested:
                    raise TransportError(
                        "The managed Claude Code turn was interrupted before checkpointing."
                    )
                if result is None:
                    raise TransportError(
                        "Claude Code completed without returning a terminal result."
                    )
                if result.is_error:
                    raise TransportError(
                        "The managed Claude Code turn failed before Limina accepted "
                        "its checkpoint.",
                        stop_reason=result.stop_reason,
                    )
                response = result.structured_output or result.result
                if response is None:
                    raise TransportError(
                        "Claude Code completed without the required project decision."
                    )
                decision = _parse_runtime_decision(response, provider="Claude Code")
                return RuntimeTurn(
                    continuation_id=result.session_id,
                    turn_id=turn_id or str(uuid4()),
                    decision=decision,
                    usage=_usage_from_result(result),
                )
        except LiminaError:
            raise
        except Exception as exc:
            raise TransportError(
                "The managed Claude Code turn failed before Limina accepted its checkpoint.",
                reason=_redact_text(str(exc), tuple(runtime_env.values())),
                continuation_id=continuation_id,
            ) from exc
        finally:
            self._active = False
            self._query_active = False
            self._client = None
            with suppress(Exception):
                await client.disconnect()

    async def steer(self, message: str) -> bool:
        client = self._client
        if client is None or not self._query_active or self._stop_requested:
            return False
        await self._steering.put(message)
        with suppress(Exception):
            await client.interrupt()
        return True

    async def interrupt(self) -> bool:
        client = self._client
        if client is None or not self._active:
            return False
        self._stop_requested = True
        await client.interrupt()
        return True

    async def close(self) -> None:
        client = self._client
        if client is None:
            return
        with suppress(Exception):
            await self.interrupt()
        with suppress(Exception):
            await client.disconnect()

    def _drain_steering(self) -> list[str]:
        messages: list[str] = []
        while True:
            try:
                messages.append(self._steering.get_nowait())
            except asyncio.QueueEmpty:
                return messages


def _claude_session_id(message: Any) -> str | None:
    session_id = getattr(message, "session_id", None)
    if session_id:
        return str(session_id)
    data = getattr(message, "data", None)
    if isinstance(data, dict) and data.get("session_id"):
        return str(data["session_id"])
    return None


def _map_claude_message(message: Any) -> RuntimeEvent | None:
    message_type = type(message).__name__
    if message_type == "AssistantMessage":
        blocks = getattr(message, "content", [])
        for block in blocks:
            block_type = type(block).__name__
            if block_type == "ToolUseBlock":
                tool_name = str(getattr(block, "name", "tool"))
                return RuntimeEvent(
                    event_type="runtime.claude-code",
                    summary=f"Using {tool_name}",
                    detail={"method": "tool/use", "item_type": tool_name},
                )
            if block_type == "TextBlock" and (text := str(getattr(block, "text", "")).strip()):
                return RuntimeEvent(
                    event_type="runtime.claude-code",
                    summary=text[:1000],
                    detail={"method": "assistant/message", "item_type": "text"},
                )
    if message_type in {"TaskStartedMessage", "TaskProgressMessage", "TaskNotificationMessage"}:
        description = str(getattr(message, "description", message_type))
        return RuntimeEvent(
            event_type="runtime.claude-code",
            summary=description[:1000],
            detail={"method": "task/progress", "item_type": message_type},
        )
    return None


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


from .supervisor import ProjectSupervisor  # noqa: E402, F401
