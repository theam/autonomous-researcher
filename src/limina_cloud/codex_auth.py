"""Instance-owned Codex authentication with durable state and turn-safe mutation."""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .errors import AuthenticationError, ConflictError, InvariantError, TransportError
from .runtime_environment import codex_environment, ensure_private_directory

AUTH_MODES = {"auto", "chatgpt", "api-key", "access-token"}


class _CodexClient(Protocol):
    def __enter__(self) -> _CodexClient: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def account(self, *, refresh_token: bool = False) -> Any: ...

    def login_api_key(self, api_key: str) -> None: ...

    def login_chatgpt_device_code(self) -> Any: ...

    def logout(self) -> None: ...

    def close(self) -> None: ...


CodexFactory = Callable[[dict[str, str]], _CodexClient]


class _ReadWriteGate:
    """Writer-preferring gate: turns share reads; auth mutation owns the writer."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._readers = 0
        self._writer = False
        self._writers_waiting = 0

    @property
    def readers(self) -> int:
        with self._condition:
            return self._readers

    @contextmanager
    def read(self) -> Iterator[None]:
        with self._condition:
            while self._writer or self._writers_waiting:
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                self._condition.notify_all()

    @contextmanager
    def write(self) -> Iterator[None]:
        self._begin_write(wait=True)
        try:
            yield
        finally:
            self.end_write()

    def try_begin_write(self) -> bool:
        return self._begin_write(wait=False)

    def _begin_write(self, *, wait: bool) -> bool:
        with self._condition:
            self._writers_waiting += 1
            try:
                if not wait and (self._writer or self._readers):
                    return False
                while self._writer or self._readers:
                    self._condition.wait()
                self._writer = True
                return True
            finally:
                self._writers_waiting -= 1

    def end_write(self) -> None:
        with self._condition:
            if not self._writer:
                return
            self._writer = False
            self._condition.notify_all()


@dataclass
class DeviceLoginAttempt:
    login_id: str
    verification_url: str
    user_code: str
    command_id: str
    status: str = "PENDING"
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    _codex: _CodexClient | None = field(default=None, repr=False)
    _handle: Any = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "login_id": self.login_id,
            "status": self.status,
            "verification_url": self.verification_url,
            "user_code": self.user_code if self.status == "PENDING" else None,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class CodexAuthManager:
    """Owns one node's shared Codex credential state.

    `auth.json` is intentionally readable by Codex itself. The manager removes raw provider
    credentials from the child environment, but does not claim to hide the credential store from
    the provider process that must use it.
    """

    def __init__(
        self,
        home: Path,
        *,
        mode: str = "auto",
        api_key: str | None = None,
        access_token: str | None = None,
        codex_factory: CodexFactory | None = None,
        login_command: tuple[str, ...] = ("codex", "login", "--with-access-token"),
    ) -> None:
        normalized_mode = mode.strip().lower()
        if normalized_mode not in AUTH_MODES:
            raise RuntimeError(f"LIMINA_CODEX_AUTH_MODE must be one of {sorted(AUTH_MODES)}.")
        if api_key and access_token and normalized_mode == "auto":
            raise RuntimeError(
                "OPENAI_API_KEY and CODEX_ACCESS_TOKEN cannot both be set in auto auth mode."
            )
        self.home = ensure_private_directory(home)
        self.mode = normalized_mode
        self.api_key = api_key or None
        self.access_token = access_token or None
        self.codex_factory = codex_factory or self._default_codex_factory
        self.login_command = login_command
        self._gate = _ReadWriteGate()
        self._chatgpt_turn = threading.Lock()
        self._materialized_process_credential = False
        self._attempts: dict[str, DeviceLoginAttempt] = {}
        self._attempt_by_command: dict[str, str] = {}
        self._attempt_lock = threading.Lock()

    @classmethod
    def from_environment(cls, home: Path) -> CodexAuthManager:
        return cls(
            home,
            mode=os.environ.get("LIMINA_CODEX_AUTH_MODE", "auto"),
            api_key=os.environ.get("OPENAI_API_KEY") or None,
            access_token=os.environ.get("CODEX_ACCESS_TOKEN") or None,
        )

    @property
    def active_turns(self) -> int:
        return self._gate.readers

    def status(self) -> dict[str, Any]:
        with self._gate.read():
            return self._account_status_unlocked()

    def ensure_ready(self) -> dict[str, Any]:
        # Established credentials are read-only for the duration of a turn. Keep the common path
        # under a shared lock so independent API-key projects can actually run in parallel.
        with self._gate.read():
            status = self._account_status_unlocked()
            if self._ready_without_mutation(status):
                return status
        # Materialization is rare and must exclude turns. Re-check under the writer because another
        # caller may have completed login between the shared and exclusive sections.
        with self._gate.write():
            return self._ensure_ready_unlocked()

    @contextmanager
    def turn(self) -> Iterator[dict[str, Any]]:
        self.ensure_ready()
        with self._gate.read():
            status = self._account_status_unlocked()
            if not status["configured"]:
                raise self._missing_auth_error()
            if status["active_method"] == "chatgpt":
                with self._chatgpt_turn:
                    yield status
            else:
                yield status

    def login_from_environment(self, method: str) -> dict[str, Any]:
        normalized = method.strip().lower()
        if normalized not in {"api-key", "access-token"}:
            raise InvariantError("Runtime login method must be api-key or access-token.")
        if not self._gate.try_begin_write():
            raise ConflictError(
                "Codex authentication cannot change while a managed turn is active.",
                active_turns=self.active_turns,
            )
        try:
            if normalized == "api-key":
                self._login_api_key_unlocked()
            else:
                self._login_access_token_unlocked()
            return self._account_status_unlocked()
        finally:
            self._gate.end_write()

    def start_device_login(self, command_id: str) -> dict[str, Any]:
        if self.mode in {"api-key", "access-token"}:
            raise InvariantError(
                "ChatGPT login is disabled by LIMINA_CODEX_AUTH_MODE.",
                configured_mode=self.mode,
                suggestion="Use auto/chatgpt mode or log in with the configured server credential.",
            )
        with self._attempt_lock:
            existing_id = self._attempt_by_command.get(command_id)
            if existing_id:
                return self._attempts[existing_id].public()
        if not self._gate.try_begin_write():
            raise ConflictError(
                "Codex authentication cannot change while a managed turn is active.",
                active_turns=self.active_turns,
            )
        codex: _CodexClient | None = None
        try:
            codex = self.codex_factory(self._auth_environment())
            codex.__enter__()
            handle = codex.login_chatgpt_device_code()
            attempt = DeviceLoginAttempt(
                login_id=str(handle.login_id),
                verification_url=str(handle.verification_url),
                user_code=str(handle.user_code),
                command_id=command_id,
                _codex=codex,
                _handle=handle,
            )
            with self._attempt_lock:
                self._prune_attempts()
                self._attempts[attempt.login_id] = attempt
                self._attempt_by_command[command_id] = attempt.login_id
            threading.Thread(
                target=self._wait_for_device_login,
                args=(attempt.login_id,),
                name=f"limina:codex-login:{attempt.login_id[:8]}",
                daemon=True,
            ).start()
            return attempt.public()
        except Exception:
            try:
                if codex is not None:
                    codex.close()
            finally:
                self._gate.end_write()
            raise

    def login_attempt(self, login_id: str) -> dict[str, Any]:
        with self._attempt_lock:
            attempt = self._attempts.get(login_id)
            if attempt is None:
                raise InvariantError("The Codex login attempt does not exist.", login_id=login_id)
            return attempt.public()

    def cancel_device_login(self, login_id: str) -> dict[str, Any]:
        with self._attempt_lock:
            attempt = self._attempts.get(login_id)
            if attempt is None:
                raise InvariantError("The Codex login attempt does not exist.", login_id=login_id)
            if attempt.status != "PENDING":
                return attempt.public()
            handle = attempt._handle
        try:
            handle.cancel()
        finally:
            # `_finish_attempt` owns the attempt lock. Keep provider cancellation outside it so a
            # synchronous callback or the waiter thread cannot deadlock this control request.
            self._finish_attempt(attempt, status="CANCELLED")
        return self.login_attempt(login_id)

    def logout(self) -> dict[str, Any]:
        if not self._gate.try_begin_write():
            raise ConflictError(
                "Codex authentication cannot change while a managed turn is active.",
                active_turns=self.active_turns,
            )
        try:
            with self.codex_factory(self._auth_environment()) as codex:
                codex.logout()
            self._materialized_process_credential = False
            self._secure_state_files()
            return self._account_status_unlocked()
        finally:
            self._gate.end_write()

    def close(self) -> None:
        with self._attempt_lock:
            pending = [
                item.login_id for item in self._attempts.values() if item.status == "PENDING"
            ]
        for login_id in pending:
            self.cancel_device_login(login_id)

    def _ensure_ready_unlocked(self) -> dict[str, Any]:
        status = self._account_status_unlocked()
        if self.mode == "chatgpt":
            if status["active_method"] != "chatgpt":
                raise self._missing_auth_error()
            return status
        if self.mode == "api-key":
            if not self._materialized_process_credential:
                self._login_api_key_unlocked()
            return self._account_status_unlocked()
        if self.mode == "access-token":
            if not self._materialized_process_credential:
                self._login_access_token_unlocked()
            return self._account_status_unlocked()

        # Auto preserves a human ChatGPT session. Machine credentials are re-materialized once per
        # server process so rotation replaces stale cached API-key/access-token state.
        if status["active_method"] == "chatgpt" and status["source"] == "cached_chatgpt":
            return status
        if self.access_token:
            if not self._materialized_process_credential:
                self._login_access_token_unlocked()
            return self._account_status_unlocked()
        if self.api_key:
            if not self._materialized_process_credential:
                self._login_api_key_unlocked()
            return self._account_status_unlocked()
        if status["configured"]:
            return status
        raise self._missing_auth_error()

    def _ready_without_mutation(self, status: dict[str, Any]) -> bool:
        if self.mode == "chatgpt":
            return status["active_method"] == "chatgpt"
        if self.mode in {"api-key", "access-token"}:
            return self._materialized_process_credential and bool(status["configured"])
        if status["active_method"] == "chatgpt" and status["source"] == "cached_chatgpt":
            return True
        if self._materialized_process_credential and status["configured"]:
            return True
        return not self.api_key and not self.access_token and bool(status["configured"])

    def _login_api_key_unlocked(self) -> None:
        if not self.api_key:
            raise AuthenticationError(
                "Codex API-key auth requires OPENAI_API_KEY on the Limina server."
            )
        try:
            with self.codex_factory(self._auth_environment()) as codex:
                codex.login_api_key(self.api_key)
        except Exception as exc:
            raise TransportError(
                "Limina could not materialize Codex API-key authentication.",
                reason="The Codex SDK rejected or could not persist the server credential.",
            ) from exc
        self._materialized_process_credential = True
        self._secure_state_files()

    def _login_access_token_unlocked(self) -> None:
        if not self.access_token:
            raise AuthenticationError(
                "Codex access-token auth requires CODEX_ACCESS_TOKEN on the Limina server."
            )
        try:
            result = subprocess.run(
                self.login_command,
                input=self.access_token,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self._auth_environment(),
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise TransportError("Limina could not start Codex access-token login.") from exc
        if result.returncode != 0:
            raise TransportError(
                "Limina could not materialize Codex access-token authentication.",
                reason="Codex login rejected the configured access token.",
            )
        self._materialized_process_credential = True
        self._secure_state_files()

    def _account_status_unlocked(self) -> dict[str, Any]:
        try:
            with self.codex_factory(self._auth_environment()) as codex:
                response = codex.account()
        except Exception:
            return {
                "engine": "codex",
                "configured_mode": self.mode,
                "configured": False,
                "active_method": None,
                "account_email": None,
                "account_plan": None,
                "source": "unavailable",
                "error": "Codex account status is unavailable.",
                "single_runtime_node": True,
            }
        account = getattr(response, "account", None)
        root = getattr(account, "root", account) if account is not None else None
        raw_type = str(getattr(root, "type", "")) if root is not None else ""
        active_method = (
            "chatgpt" if raw_type == "chatgpt" else "api-key" if raw_type == "apiKey" else None
        )
        source = (
            "cached_chatgpt"
            if active_method == "chatgpt" and not self._materialized_process_credential
            else "server_access_token"
            if active_method == "chatgpt" and self.access_token
            else "server_api_key"
            if active_method == "api-key" and self.api_key
            else "cached_api_key"
            if active_method == "api-key"
            else "none"
        )
        plan = getattr(root, "plan_type", None)
        return {
            "engine": "codex",
            "configured_mode": self.mode,
            "configured": bool(active_method),
            "active_method": active_method,
            "account_email": getattr(root, "email", None),
            "account_plan": str(getattr(plan, "value", plan)) if plan is not None else None,
            "source": source,
            "error": None,
            "single_runtime_node": True,
        }

    def _wait_for_device_login(self, login_id: str) -> None:
        with self._attempt_lock:
            attempt = self._attempts[login_id]
        try:
            completed = attempt._handle.wait()
            if bool(getattr(completed, "success", False)):
                self._secure_state_files()
                self._finish_attempt(attempt, status="SUCCEEDED")
            else:
                self._finish_attempt(
                    attempt,
                    status="FAILED",
                    error="ChatGPT login failed or expired.",
                )
        except Exception:
            self._finish_attempt(
                attempt,
                status="FAILED",
                error="ChatGPT login failed or expired.",
            )

    def _finish_attempt(
        self, attempt: DeviceLoginAttempt, *, status: str, error: str | None = None
    ) -> None:
        with self._attempt_lock:
            if attempt.status != "PENDING":
                return
            attempt.status = status
            attempt.error = error
            attempt.completed_at = datetime.now(UTC)
            codex = attempt._codex
            attempt._codex = None
            attempt._handle = None
        try:
            if codex is not None:
                codex.close()
        finally:
            # A provider cleanup error must never strand the instance-wide auth writer.
            self._gate.end_write()

    def _auth_environment(self) -> dict[str, str]:
        return codex_environment({}, self.home)

    def _secure_state_files(self) -> None:
        ensure_private_directory(self.home)
        auth_file = self.home / "auth.json"
        if auth_file.exists():
            auth_file.chmod(0o600)

    def _missing_auth_error(self) -> AuthenticationError:
        return AuthenticationError(
            "Codex is not authenticated. Configure OPENAI_API_KEY/CODEX_ACCESS_TOKEN on the "
            "server or run `limina runtime codex login`."
        )

    def _prune_attempts(self) -> None:
        completed = sorted(
            (item for item in self._attempts.values() if item.status != "PENDING"),
            key=lambda item: item.completed_at or item.created_at,
        )
        while len(self._attempts) >= 32 and completed:
            item = completed.pop(0)
            self._attempts.pop(item.login_id, None)
            self._attempt_by_command.pop(item.command_id, None)

    @staticmethod
    def _default_codex_factory(environment: dict[str, str]) -> _CodexClient:
        try:
            from openai_codex import Codex, CodexConfig
        except ImportError as exc:
            raise TransportError(
                "The Limina runtime image does not include the Codex SDK.",
                suggestion="Install the project with the 'codex' extra.",
            ) from exc
        return Codex(
            CodexConfig(
                env=environment,
                config_overrides=('cli_auth_credentials_store="file"',),
            )
        )
