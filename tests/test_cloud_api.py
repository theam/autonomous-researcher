from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
import warnings
from pathlib import Path
from uuid import uuid4

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*"
)

from starlette.testclient import TestClient  # noqa: E402

from limina_cloud.api import create_app  # noqa: E402
from limina_cloud.models import Event  # noqa: E402
from limina_cloud.notification_service import TransportResult  # noqa: E402
from limina_cloud.runtime import RuntimeDecision, RuntimeTurn  # noqa: E402


class FakeAgentSession:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.steering: list[str] = []
        self._finish: asyncio.Event | None = None

    async def run_turn(self, **_values):
        self._finish = asyncio.Event()
        self.started.set()
        await self._finish.wait()
        return RuntimeTurn(
            "private-thread",
            "private-turn",
            RuntimeDecision(
                "Human guidance incorporated.",
                "COMPLETE",
                "Synthesize the result.",
                "Present accepted knowledge.",
                "None",
            ),
        )

    async def steer(self, message: str) -> bool:
        self.steering.append(message)
        if self._finish is not None:
            self._finish.set()
            return True
        return False

    async def interrupt(self) -> bool:
        if self._finish is not None:
            self._finish.set()
            return True
        return False

    async def close(self) -> None:
        await self.interrupt()


class FakeCodexAuth:
    def __init__(self) -> None:
        self.logged_out = False

    @staticmethod
    def status():
        return {
            "engine": "codex",
            "configured_mode": "auto",
            "configured": False,
            "active_method": None,
            "account_email": None,
            "account_plan": None,
            "source": "none",
            "error": None,
            "single_runtime_node": True,
        }

    def logout(self):
        self.logged_out = True
        return self.status()

    def close(self) -> None:
        return None


class CloudApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_url = f"sqlite:///{Path(self.temp_dir.name) / 'api.db'}"
        self.session = FakeAgentSession()
        self.app = create_app(
            database_url=database_url,
            token="secret",
            admin_token="admin-secret",
            workspace_root=Path(self.temp_dir.name) / "workspaces",
            agent_factory=lambda _slug, _engine: self.session,
            poll_interval=0.01,
        )
        self.app.state.runtime.supervisor.codex_auth.close()
        self.app.state.runtime.supervisor.codex_auth = FakeCodexAuth()
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.auth = {"Authorization": "Bearer secret"}
        self.admin_auth = {"Authorization": "Bearer admin-secret"}

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.app.state.runtime.database.dispose()
        self.temp_dir.cleanup()

    def command_headers(self, command_id: str | None = None) -> dict[str, str]:
        return {
            **self.auth,
            "X-Limina-Actor": "api-user",
            "Idempotency-Key": command_id or str(uuid4()),
        }

    def create_project(self, slug: str = "cloud-test"):
        return self.client.post(
            "/v2/projects",
            json={
                "slug": slug,
                "name": "Cloud test",
                "objective": "Prove that Limina owns execution.",
                "context": "API integration test.",
                "success_criteria": "A teammate can steer the managed live turn.",
                "runtime": "codex",
            },
            headers=self.command_headers(),
        )

    def test_authentication_and_public_surface(self) -> None:
        self.assertEqual(self.client.get("/livez").status_code, 200)
        self.assertEqual(self.client.get("/readyz").status_code, 200)
        self.assertEqual(self.client.get("/healthz").status_code, 401)
        response = self.client.get("/healthz", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["runtime_owner"], "limina")
        self.assertEqual(response.json()["runtimes"], ["codex", "claude-code"])
        self.assertEqual(response.json()["interfaces"]["rest"], "/v2")

        schema = self.client.get("/v2/openapi.json", headers=self.auth).json()
        self.assertIn("HTTPBearer", schema["components"]["securitySchemes"])
        paths = " ".join(schema["paths"])
        self.assertFalse(any(path.startswith("/v1") for path in schema["paths"]))
        self.assertFalse(any(path.startswith("/internal/") for path in schema["paths"]))
        for forbidden in ("worker", "thread", "session", "coordinator", "lease"):
            self.assertNotIn(forbidden, paths)

    def test_legacy_public_v1_routes_are_not_mounted(self) -> None:
        for path in ("/v1/projects", "/v1/runtime/engines/codex/auth"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, headers=self.auth).status_code, 404)

    def test_failed_authentication_is_rate_limited(self) -> None:
        invalid = {"Authorization": "Bearer wrong"}
        for _ in range(10):
            self.assertEqual(self.client.get("/healthz", headers=invalid).status_code, 401)
        limited = self.client.get("/healthz", headers=invalid)
        self.assertEqual(limited.status_code, 429)
        self.assertGreaterEqual(limited.json()["error"]["details"]["retry_after_seconds"], 1)

    def test_runtime_authentication_requires_the_distinct_admin_token(self) -> None:
        path = "/v2/runtime/engines/codex/auth"
        self.assertEqual(self.client.get(path, headers=self.auth).status_code, 403)
        status = self.client.get(path, headers=self.admin_auth)
        self.assertEqual(status.status_code, 200, status.text)
        self.assertFalse(status.json()["configured"])

    def test_project_lifecycle_resources_and_sanitized_status(self) -> None:
        replay_key = str(uuid4())
        payload = {
            "slug": "cloud-test",
            "name": "Cloud test",
            "objective": "Prove the shared transport.",
            "context": "API integration test.",
            "success_criteria": "Round-trip state through HTTP.",
        }
        first = self.client.post(
            "/v2/projects", json=payload, headers=self.command_headers(replay_key)
        )
        second = self.client.post(
            "/v2/projects", json=payload, headers=self.command_headers(replay_key)
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["status"], "CREATED")
        self.assertEqual(first.json()["runtime"], "codex")
        created_events = self.client.get(
            "/v2/projects/cloud-test/events", headers=self.auth
        ).json()["events"]
        self.assertEqual(created_events[0]["detail"]["runtime"], "codex")
        self.assertNotIn("runtime_engine", created_events[0]["detail"])

        variable = self.client.put(
            "/v2/projects/cloud-test/resources/variables/SOURCE_URL",
            json={"value": "https://example.invalid/repository"},
            headers=self.command_headers(),
        )
        self.assertEqual(variable.status_code, 200, variable.text)
        self.assertEqual(variable.json()["type"], "VARIABLE")
        self.assertEqual(variable.json()["value"], "https://example.invalid/repository")

        secret_value = "super-sensitive-token-123"
        secret = self.client.put(
            "/v2/projects/cloud-test/resources/secrets/SOURCE_TOKEN",
            json={"value": secret_value},
            headers=self.command_headers(),
        )
        self.assertEqual(secret.status_code, 200, secret.text)
        self.assertEqual(secret.json()["type"], "SECRET")
        self.assertTrue(secret.json()["configured"])
        self.assertNotIn("value", secret.json())
        self.assertNotIn(secret_value, secret.text)

        resources = self.client.get("/v2/projects/cloud-test/resources", headers=self.auth)
        self.assertEqual(resources.status_code, 200, resources.text)
        self.assertNotIn(secret_value, resources.text)
        review = self.client.get("/v2/projects/cloud-test/review", headers=self.auth)
        events = self.client.get("/v2/projects/cloud-test/events", headers=self.auth)
        self.assertNotIn(secret_value, review.text)
        self.assertNotIn(secret_value, events.text)

        started = self.client.post(
            "/v2/projects/cloud-test/actions/start", headers=self.command_headers()
        )
        self.assertEqual(started.status_code, 200, started.text)
        self.assertTrue(self.session.started.wait(timeout=2))

        status = self.client.get("/v2/projects/cloud-test/status", headers=self.auth)
        self.assertEqual(status.status_code, 200, status.text)
        serialized = status.text.lower()
        for forbidden in (
            "thread_id",
            "continuation_id",
            "worker_id",
            "inbox_cursor",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_project_creation_selects_a_supported_runtime_engine(self) -> None:
        payload = {
            "slug": "claude-project",
            "name": "Claude project",
            "objective": "Use the Claude Code engine.",
            "context": "API selection test.",
            "success_criteria": "The engine is persisted.",
            "runtime": "claude-code",
        }
        created = self.client.post("/v2/projects", json=payload, headers=self.command_headers())
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["runtime"], "claude-code")

        payload["slug"] = "invalid-project"
        payload["runtime"] = "other"
        rejected = self.client.post("/v2/projects", json=payload, headers=self.command_headers())
        self.assertEqual(rejected.status_code, 422, rejected.text)

    def test_project_draft_updates_are_revision_checked_and_clone_omits_inputs(self) -> None:
        created = self.create_project()
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["version"], 1)
        update_key = str(uuid4())
        update_payload = {
            "expected_version": 1,
            "name": "Reframed project",
            "mission": "Prove safe optimistic draft updates.",
        }
        updated = self.client.patch(
            "/v2/projects/cloud-test",
            json=update_payload,
            headers=self.command_headers(update_key),
        )
        replay = self.client.patch(
            "/v2/projects/cloud-test",
            json=update_payload,
            headers=self.command_headers(update_key),
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json(), replay.json())
        self.assertEqual(updated.json()["version"], 2)

        stale = self.client.patch(
            "/v2/projects/cloud-test",
            json={"expected_version": 1, "name": "Stale overwrite"},
            headers=self.command_headers(),
        )
        self.assertEqual(stale.status_code, 409, stale.text)

        self.client.put(
            "/v2/projects/cloud-test/resources/variables/PRIVATE_INPUT",
            json={"value": "must-not-copy"},
            headers=self.command_headers(),
        )
        self.client.put(
            "/v2/projects/cloud-test/sources",
            json={
                "name": "Private source",
                "type": "URL",
                "uri": "https://example.test/source",
                "media_type": None,
                "metadata": {},
            },
            headers=self.command_headers(),
        )
        clone_key = str(uuid4())
        clone_payload = {"slug": "cloud-copy", "name": "Cloud copy"}
        cloned = self.client.post(
            "/v2/projects/cloud-test/clone",
            json=clone_payload,
            headers=self.command_headers(clone_key),
        )
        clone_replay = self.client.post(
            "/v2/projects/cloud-test/clone",
            json=clone_payload,
            headers=self.command_headers(clone_key),
        )
        self.assertEqual(cloned.status_code, 201, cloned.text)
        self.assertEqual(cloned.json(), clone_replay.json())
        self.assertEqual(cloned.json()["mission"], updated.json()["mission"])
        self.assertEqual(
            self.client.get("/v2/projects/cloud-copy/resources", headers=self.auth).json(), []
        )
        self.assertEqual(
            self.client.get("/v2/projects/cloud-copy/sources", headers=self.auth).json(), []
        )
        members = self.client.get("/v2/projects/cloud-copy/members", headers=self.auth).json()
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]["role"], "OWNER")

    def test_notification_configuration_is_write_only_and_idempotent(self) -> None:
        self.assertEqual(self.create_project().status_code, 201)
        self.app.state.runtime.notifications.resolver = lambda _host, _port: ["93.184.216.34"]
        self.app.state.runtime.notifications.sender = lambda _url, _headers, _body: TransportResult(
            204
        )
        channel_key = str(uuid4())
        channel_payload = {
            "type": "GENERIC_WEBHOOK",
            "display_name": "Operator webhook",
            "destination": "https://notify.example.test/limina",
            "signing_secret": "write-only-signing-secret",
            "trust_delegation_confirmed": True,
        }
        channel = self.client.post(
            "/v2/projects/cloud-test/notifications/channels",
            json=channel_payload,
            headers=self.command_headers(channel_key),
        )
        replay = self.client.post(
            "/v2/projects/cloud-test/notifications/channels",
            json=channel_payload,
            headers=self.command_headers(channel_key),
        )
        self.assertEqual(channel.status_code, 201, channel.text)
        self.assertEqual(replay.json(), channel.json())
        self.assertNotIn("write-only-signing-secret", channel.text)
        self.assertNotIn("notify.example.test/limina", channel.text)

        rule_key = str(uuid4())
        rule_payload = {
            "channel_id": channel.json()["id"],
            "display_name": "High-priority questions",
            "attention_types": ["agent_request"],
            "severities": ["CRITICAL", "HIGH"],
            "cooldown_seconds": 300,
        }
        rule = self.client.post(
            "/v2/projects/cloud-test/notifications/rules",
            json=rule_payload,
            headers=self.command_headers(rule_key),
        )
        rule_replay = self.client.post(
            "/v2/projects/cloud-test/notifications/rules",
            json=rule_payload,
            headers=self.command_headers(rule_key),
        )
        self.assertEqual(rule.status_code, 201, rule.text)
        self.assertEqual(rule_replay.json(), rule.json())
        self.assertEqual(
            len(
                self.client.get(
                    "/v2/projects/cloud-test/notifications/channels", headers=self.auth
                ).json()
            ),
            1,
        )
        self.assertEqual(
            len(
                self.client.get(
                    "/v2/projects/cloud-test/notifications/rules", headers=self.auth
                ).json()
            ),
            1,
        )

    def test_live_attach_can_steer_the_active_managed_turn(self) -> None:
        self.assertEqual(self.create_project().status_code, 201)
        self.client.post("/v2/projects/cloud-test/actions/start", headers=self.command_headers())
        self.assertTrue(self.session.started.wait(timeout=2))

        with self.client.websocket_connect(
            "/v2/projects/cloud-test/live",
            headers={**self.auth, "X-Limina-Actor": "reviewer"},
            subprotocols=["limina.v2"],
        ) as socket:
            snapshot = socket.receive_json()
            self.assertEqual(snapshot["type"], "snapshot")
            socket.send_json({"type": "steer", "body": "Prioritize generalization."})
            deadline = time.monotonic() + 2
            delivery = None
            while time.monotonic() < deadline:
                message = socket.receive_json()
                if message["type"] == "delivery":
                    delivery = message["value"]
                    break
            self.assertEqual(delivery, "LIVE")

        self.assertEqual(self.session.steering, ["reviewer: Prioritize generalization."])

        response = self.client.post(
            "/v2/projects/cloud-test/steering",
            json={"body": "Now test the strongest baseline.", "kind": "STEER"},
            headers=self.command_headers(),
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(set(response.json()), {"id", "delivery", "kind", "accepted_at", "status"})
        self.assertNotIn("message", response.json())

    def test_private_agent_commands_require_a_project_scoped_capability(self) -> None:
        self.assertEqual(self.create_project().status_code, 201)
        capability = self.app.state.runtime.supervisor.issue_capability("cloud-test")
        internal_headers = {
            "Authorization": f"Bearer {capability}",
            "Idempotency-Key": str(uuid4()),
        }
        created = self.client.post(
            "/internal/v1/projects/cloud-test/hypotheses",
            json={
                "title": "Scoped write",
                "statement": "The capability permits only its managed project.",
            },
            headers=internal_headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["id"], "H001")

        denied = self.client.get(
            "/internal/v1/projects/cloud-test/status",
            headers={"Authorization": "Bearer wrong"},
        )
        self.assertEqual(denied.status_code, 401, denied.text)

    def test_activity_cursor_replays_only_new_durable_events(self) -> None:
        self.assertEqual(self.create_project().status_code, 201)
        first = self.client.get("/v2/projects/cloud-test/events?after=0", headers=self.auth).json()
        self.assertEqual([item["type"] for item in first["events"]], ["project.created"])

        self.client.put(
            "/v2/projects/cloud-test/resources/variables/BRIEF_URI",
            json={"value": "s3://brief"},
            headers=self.command_headers(),
        )
        second = self.client.get(
            f"/v2/projects/cloud-test/events?after={first['cursor']}", headers=self.auth
        ).json()
        self.assertEqual(
            [item["type"] for item in second["events"]],
            ["resource.variable_set", "guidance.received"],
        )
        self.assertGreater(second["cursor"], first["cursor"])

    def test_domain_errors_have_stable_machine_readable_shape(self) -> None:
        response = self.client.get("/v2/projects/missing/status", headers=self.auth)
        self.assertEqual(response.status_code, 404)
        error = response.json()["error"]
        self.assertEqual(error["code"], "not_found")
        self.assertIn("does not exist", error["message"])

    def test_review_recent_activity_uses_the_newest_events_after_large_histories(self) -> None:
        self.assertEqual(self.create_project().status_code, 201)
        challenge_id = self.app.state.runtime.service.get_challenge("cloud-test")["id"]
        with self.app.state.runtime.database.session() as session, session.begin():
            session.add_all(
                Event(
                    challenge_id=challenge_id,
                    event_type="test.marker",
                    actor="tester",
                    payload={"marker": marker},
                    command_id=f"marker-{marker}",
                )
                for marker in range(1005)
            )
        review = self.client.get("/v2/projects/cloud-test/review", headers=self.auth)
        self.assertEqual(review.status_code, 200, review.text)
        recent = review.json()["recent_activity"]
        self.assertEqual(len(recent), 50)
        self.assertEqual(recent[-1]["detail"]["marker"], 1004)


if __name__ == "__main__":
    unittest.main()
