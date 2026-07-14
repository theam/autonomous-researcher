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


class CloudApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_url = f"sqlite:///{Path(self.temp_dir.name) / 'api.db'}"
        self.session = FakeAgentSession()
        self.app = create_app(
            database_url=database_url,
            token="secret",
            workspace_root=Path(self.temp_dir.name) / "workspaces",
            agent_factory=lambda _slug, _engine: self.session,
            poll_interval=0.01,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.auth = {"Authorization": "Bearer secret"}

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
            "/v1/projects",
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
        self.assertEqual(self.client.get("/healthz").status_code, 401)
        response = self.client.get("/healthz", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["runtime_owner"], "limina")
        self.assertEqual(response.json()["runtimes"], ["codex", "claude-code"])

        schema = self.client.get("/openapi.json", headers=self.auth).json()
        self.assertIn("HTTPBearer", schema["components"]["securitySchemes"])
        paths = " ".join(schema["paths"])
        for forbidden in ("worker", "thread", "session", "coordinator", "lease"):
            self.assertNotIn(forbidden, paths)

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
            "/v1/projects", json=payload, headers=self.command_headers(replay_key)
        )
        second = self.client.post(
            "/v1/projects", json=payload, headers=self.command_headers(replay_key)
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["status"], "CREATED")
        self.assertEqual(first.json()["runtime"], "codex")
        created_events = self.client.get(
            "/v1/projects/cloud-test/events", headers=self.auth
        ).json()["events"]
        self.assertEqual(created_events[0]["detail"]["runtime"], "codex")
        self.assertNotIn("runtime_engine", created_events[0]["detail"])

        variable = self.client.put(
            "/v1/projects/cloud-test/resources/variables/SOURCE_URL",
            json={"value": "https://example.invalid/repository"},
            headers=self.command_headers(),
        )
        self.assertEqual(variable.status_code, 200, variable.text)
        self.assertEqual(variable.json()["type"], "VARIABLE")
        self.assertEqual(variable.json()["value"], "https://example.invalid/repository")

        secret_value = "super-sensitive-token-123"
        secret = self.client.put(
            "/v1/projects/cloud-test/resources/secrets/SOURCE_TOKEN",
            json={"value": secret_value},
            headers=self.command_headers(),
        )
        self.assertEqual(secret.status_code, 200, secret.text)
        self.assertEqual(secret.json()["type"], "SECRET")
        self.assertTrue(secret.json()["configured"])
        self.assertNotIn("value", secret.json())
        self.assertNotIn(secret_value, secret.text)

        resources = self.client.get("/v1/projects/cloud-test/resources", headers=self.auth)
        self.assertEqual(resources.status_code, 200, resources.text)
        self.assertNotIn(secret_value, resources.text)
        review = self.client.get("/v1/projects/cloud-test/review", headers=self.auth)
        events = self.client.get("/v1/projects/cloud-test/events", headers=self.auth)
        self.assertNotIn(secret_value, review.text)
        self.assertNotIn(secret_value, events.text)

        started = self.client.post(
            "/v1/projects/cloud-test/actions/start", headers=self.command_headers()
        )
        self.assertEqual(started.status_code, 200, started.text)
        self.assertTrue(self.session.started.wait(timeout=2))

        status = self.client.get("/v1/projects/cloud-test/status", headers=self.auth)
        self.assertEqual(status.status_code, 200, status.text)
        serialized = status.text.lower()
        for forbidden in (
            "thread_id",
            "continuation_id",
            "worker_id",
            "inbox_cursor",
            "version",
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
        created = self.client.post("/v1/projects", json=payload, headers=self.command_headers())
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["runtime"], "claude-code")

        payload["slug"] = "invalid-project"
        payload["runtime"] = "other"
        rejected = self.client.post("/v1/projects", json=payload, headers=self.command_headers())
        self.assertEqual(rejected.status_code, 422, rejected.text)

    def test_live_attach_can_steer_the_active_managed_turn(self) -> None:
        self.assertEqual(self.create_project().status_code, 201)
        self.client.post("/v1/projects/cloud-test/actions/start", headers=self.command_headers())
        self.assertTrue(self.session.started.wait(timeout=2))

        with self.client.websocket_connect(
            "/v1/projects/cloud-test/live",
            headers={**self.auth, "X-Limina-Actor": "reviewer"},
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
            "/v1/projects/cloud-test/steering",
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
        first = self.client.get("/v1/projects/cloud-test/events?after=0", headers=self.auth).json()
        self.assertEqual([item["type"] for item in first["events"]], ["project.created"])

        self.client.put(
            "/v1/projects/cloud-test/resources/variables/BRIEF_URI",
            json={"value": "s3://brief"},
            headers=self.command_headers(),
        )
        second = self.client.get(
            f"/v1/projects/cloud-test/events?after={first['cursor']}", headers=self.auth
        ).json()
        self.assertEqual(
            [item["type"] for item in second["events"]],
            ["resource.variable_set", "guidance.received"],
        )
        self.assertGreater(second["cursor"], first["cursor"])

    def test_domain_errors_have_stable_machine_readable_shape(self) -> None:
        response = self.client.get("/v1/projects/missing/status", headers=self.auth)
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
        review = self.client.get("/v1/projects/cloud-test/review", headers=self.auth)
        self.assertEqual(review.status_code, 200, review.text)
        recent = review.json()["recent_activity"]
        self.assertEqual(len(recent), 50)
        self.assertEqual(recent[-1]["detail"]["marker"], 1004)


if __name__ == "__main__":
    unittest.main()
