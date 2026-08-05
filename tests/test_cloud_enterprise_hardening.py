from __future__ import annotations

import asyncio
import os
import stat
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from limina_cloud.codex_auth import CodexAuthManager
from limina_cloud.collaboration import CollaborationService
from limina_cloud.database import Database
from limina_cloud.errors import ConflictError, RateLimitError, TransportError
from limina_cloud.exporter import MarkdownExporter
from limina_cloud.rate_limit import FailureRateLimiter
from limina_cloud.retry import RetryPolicy
from limina_cloud.runtime import ProjectSupervisor, RuntimeDecision, RuntimeTurn
from limina_cloud.runtime_usage import TokenPricing, usage_from_result
from limina_cloud.service import ChallengeService
from limina_cloud.vault import SecretCipher


class FakeDeviceHandle:
    login_id = "device-login"
    verification_url = "https://example.invalid/device"
    user_code = "ABCD-EFGH"

    def __init__(self) -> None:
        self.cancelled = False
        self.closed = threading.Event()

    def wait(self):
        self.closed.wait(timeout=2)
        return SimpleNamespace(success=False)

    def cancel(self) -> None:
        self.cancelled = True


class FakeCodex:
    def __init__(self, state: dict[str, object], environment: dict[str, str]) -> None:
        self.state = state
        self.environment = environment

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def account(self, *, refresh_token: bool = False):
        del refresh_token
        account_type = self.state.get("type")
        root = (
            SimpleNamespace(type=account_type, email=None, plan_type=None) if account_type else None
        )
        return SimpleNamespace(account=SimpleNamespace(root=root) if root else None)

    def login_api_key(self, api_key: str) -> None:
        self.state["received_key"] = api_key
        self.state["type"] = "apiKey"
        auth_file = Path(self.environment["CODEX_HOME"]) / "auth.json"
        auth_file.write_text("{}\n", encoding="utf-8")

    def login_chatgpt_device_code(self) -> FakeDeviceHandle:
        handle = FakeDeviceHandle()
        self.state["device_handle"] = handle
        return handle

    def logout(self) -> None:
        self.state["type"] = None

    def close(self) -> None:
        handle = self.state.get("device_handle")
        if isinstance(handle, FakeDeviceHandle):
            handle.closed.set()


class EnterpriseHardeningTests(unittest.TestCase):
    def test_api_key_auth_is_materialized_without_child_environment_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state: dict[str, object] = {}
            environments: list[dict[str, str]] = []

            def factory(environment: dict[str, str]) -> FakeCodex:
                environments.append(environment)
                return FakeCodex(state, environment)

            home = Path(temporary) / "fresh" / "codex"
            with patch.dict(
                os.environ,
                {
                    "ANTHROPIC_API_KEY": "unrelated-provider-secret",
                    "LIMINA_API_TOKEN": "control-plane-secret",
                    "LIMINA_ADMIN_API_TOKEN": "instance-admin-secret",
                    "LIMINA_DATABASE_URL": "postgresql://private-control-plane",
                },
            ):
                manager = CodexAuthManager(
                    home,
                    mode="api-key",
                    api_key="server-only-key",
                    codex_factory=factory,
                )
                status = manager.ensure_ready()

            self.assertTrue(status["configured"])
            self.assertEqual(status["active_method"], "api-key")
            self.assertEqual(state["received_key"], "server-only-key")
            self.assertTrue(environments)
            self.assertTrue(all(item["OPENAI_API_KEY"] == "" for item in environments))
            for name in (
                "ANTHROPIC_API_KEY",
                "LIMINA_API_TOKEN",
                "LIMINA_ADMIN_API_TOKEN",
                "LIMINA_DATABASE_URL",
            ):
                self.assertTrue(all(item.get(name, "") == "" for item in environments))
            self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((home / "auth.json").stat().st_mode), 0o600)

    def test_auth_mutation_is_rejected_while_a_turn_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state: dict[str, object] = {"type": "chatgpt"}
            manager = CodexAuthManager(
                Path(temporary) / "codex",
                mode="chatgpt",
                codex_factory=lambda environment: FakeCodex(state, environment),
            )
            entered = threading.Event()
            release = threading.Event()

            def hold_turn() -> None:
                with manager.turn():
                    entered.set()
                    release.wait(timeout=2)

            thread = threading.Thread(target=hold_turn)
            thread.start()
            self.assertTrue(entered.wait(timeout=1))
            with self.assertRaises(ConflictError):
                manager.logout()
            release.set()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def test_materialized_api_key_turns_share_the_auth_read_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state: dict[str, object] = {}
            manager = CodexAuthManager(
                Path(temporary) / "codex",
                mode="api-key",
                api_key="server-only-key",
                codex_factory=lambda environment: FakeCodex(state, environment),
            )
            manager.ensure_ready()
            first_entered = threading.Event()
            second_entered = threading.Event()
            release = threading.Event()

            def hold_turn(entered: threading.Event) -> None:
                with manager.turn():
                    entered.set()
                    release.wait(timeout=2)

            first = threading.Thread(target=hold_turn, args=(first_entered,))
            second = threading.Thread(target=hold_turn, args=(second_entered,))
            first.start()
            self.assertTrue(first_entered.wait(timeout=1))
            second.start()
            self.assertTrue(second_entered.wait(timeout=1))
            self.assertTrue(manager.status()["configured"])
            release.set()
            first.join(timeout=2)
            second.join(timeout=2)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())

    def test_device_login_cancellation_releases_the_auth_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state: dict[str, object] = {}
            manager = CodexAuthManager(
                Path(temporary) / "codex",
                mode="chatgpt",
                codex_factory=lambda environment: FakeCodex(state, environment),
            )
            started = manager.start_device_login("command-1")

            cancelled = manager.cancel_device_login(started["login_id"])

            self.assertEqual(cancelled["status"], "CANCELLED")
            handle = state["device_handle"]
            self.assertIsInstance(handle, FakeDeviceHandle)
            self.assertTrue(handle.cancelled)
            manager.logout()  # proves cancellation released the exclusive auth gate

    def test_usage_uses_current_turn_and_operator_rate_provenance(self) -> None:
        current = SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=40,
            reasoning_output_tokens=8,
            total_tokens=120,
        )
        cumulative = SimpleNamespace(input_tokens=9_999, output_tokens=9_999)
        result = SimpleNamespace(usage=SimpleNamespace(last=current, total=cumulative))
        pricing = TokenPricing(Decimal("2"), Decimal("1"), Decimal("4"))

        usage = usage_from_result(result, pricing=pricing)

        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage.input_tokens, 100)
        self.assertEqual(usage.reasoning_output_tokens, 8)
        self.assertEqual(usage.total_tokens, 120)
        self.assertEqual(usage.cost_microusd, 240)
        self.assertEqual(usage.usage_source, "provider")
        self.assertEqual(usage.cost_source, "operator_rate")

    def test_failure_limiter_is_bounded_and_recovers_after_the_window(self) -> None:
        now = [0.0]
        limiter = FailureRateLimiter(
            limit=2,
            window_seconds=10,
            max_keys=2,
            clock=lambda: now[0],
        )
        limiter.failure("client")
        limiter.failure("client")
        with self.assertRaises(RateLimitError):
            limiter.check("client")
        now[0] = 11.0
        limiter.check("client")


class DurableRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_record_start_failure_releases_capability_and_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(f"sqlite:///{root / 'startup-failure.db'}")
            database.initialize()
            service = ChallengeService(database, SecretCipher.ephemeral())
            service.create_challenge(
                slug="startup-failure",
                name="Startup failure",
                objective="Release partial runtime state.",
                context="",
                success_criteria="No heartbeat or capability survives.",
                actor="owner",
                command_id=str(uuid4()),
            )
            service.change_project_state(
                slug="startup-failure",
                action="start",
                actor="owner",
                command_id=str(uuid4()),
            )
            supervisor = ProjectSupervisor(
                service,
                MarkdownExporter(service),
                workspace_root=root / "workspaces",
                internal_url="http://127.0.0.1:7433",
                agent_factory=lambda _slug, _engine: object(),
            )
            supervisor.collaboration.start_run = Mock(
                side_effect=RuntimeError("database unavailable")
            )
            try:
                with self.assertRaises(RuntimeError):
                    await supervisor._run_turn("startup-failure", object())
                coordinator = service.get_challenge("startup-failure")["coordinator"]
                self.assertIsNone(coordinator["worker_id"])
                self.assertEqual(supervisor._capabilities, {})
                active_names = {task.get_name() for task in asyncio.all_tasks() if not task.done()}
                self.assertNotIn("limina:startup-failure:lease", active_names)
            finally:
                await supervisor.shutdown()
                database.dispose()

    async def test_retry_attempts_have_distinct_runs_and_clear_wake_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(f"sqlite:///{root / 'retry.db'}")
            database.initialize()
            service = ChallengeService(database, SecretCipher.ephemeral())
            service.create_challenge(
                slug="retry-project",
                name="Retry project",
                objective="Survive one provider overload.",
                context="",
                success_criteria="The retry succeeds.",
                actor="owner",
                command_id=str(uuid4()),
            )
            service.change_project_state(
                slug="retry-project",
                action="start",
                actor="owner",
                command_id=str(uuid4()),
            )

            class RetryOnceSession:
                model = "test"

                def __init__(self) -> None:
                    self.attempts = 0

                async def run_turn(self, **_values: object) -> RuntimeTurn:
                    self.attempts += 1
                    if self.attempts == 1:
                        raise TransportError("provider overloaded", retryable=True)
                    return RuntimeTurn(
                        "continuation",
                        "turn",
                        RuntimeDecision("Recovered.", "COMPLETE", "Done", "Review", "None"),
                    )

                async def steer(self, _message: str) -> bool:
                    return False

                async def interrupt(self) -> bool:
                    return True

                async def close(self) -> None:
                    return None

            session = RetryOnceSession()
            supervisor = ProjectSupervisor(
                service,
                MarkdownExporter(service),
                workspace_root=root / "workspaces",
                internal_url="http://127.0.0.1:7433",
                agent_factory=lambda _slug, _engine: session,
                poll_interval=0.01,
                retry_policy=RetryPolicy((0.0,)),
            )
            try:
                await supervisor.ensure_running("retry-project")
                for _ in range(200):
                    if (
                        service.get_challenge("retry-project")["coordinator"]["status"]
                        == "COMPLETE"
                    ):
                        break
                    await asyncio.sleep(0.01)
                coordinator = service.get_challenge("retry-project")["coordinator"]
                self.assertEqual(coordinator["status"], "COMPLETE")
                self.assertIsNone(coordinator["wake_at"])
                runs = CollaborationService(database).runs("retry-project")["items"]
                self.assertEqual([item["status"] for item in runs], ["COMPLETED", "FAILED"])
                self.assertEqual([item["retry_count"] for item in runs], [1, 0])
            finally:
                await supervisor.shutdown()
                database.dispose()


if __name__ == "__main__":
    unittest.main()
