from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from uuid import uuid4

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*"
)

from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from limina_cloud.api import create_app  # noqa: E402
from limina_cloud.auth import Principal  # noqa: E402
from limina_cloud.errors import AuthenticationError  # noqa: E402
from limina_cloud.runtime import (  # noqa: E402
    RuntimeDecision,
    RuntimeEvent,
    RuntimeTurn,
    RuntimeUsage,
)


class TokenAuthenticator:
    mode = "oidc"

    def __init__(self) -> None:
        self.principals = {
            "owner-token": Principal("owner", "Olivia Owner", "owner@example.test"),
            "viewer-token": Principal("viewer", "Victor Viewer", "viewer@example.test"),
            "same-name-token": Principal("other-owner", "Olivia Owner", "other@example.test"),
            "admin-token": Principal(
                "instance-admin",
                "Alice Admin",
                "admin@example.test",
                instance_admin=True,
            ),
        }

    def authenticate(self, bearer_token: str | None, *, actor_hint: str | None = None) -> Principal:
        del actor_hint
        try:
            return self.principals[bearer_token or ""]
        except KeyError as exc:
            raise AuthenticationError() from exc


class CompletingAgent:
    model = "test-model"

    async def run_turn(self, **values):
        values["on_continuation"]("private-continuation")
        values["on_event"](
            RuntimeEvent(
                "runtime.codex",
                "limina _agent finding create --thread private-thread",
                {
                    "method": "item/started",
                    "item_type": "CommandExecution",
                    "thread_id": "private-thread",
                    "continuation_id": "private-continuation",
                },
            )
        )
        await asyncio.sleep(0)
        return RuntimeTurn(
            "private-continuation",
            "turn-1",
            RuntimeDecision(
                "Evidence checkpoint completed.",
                "COMPLETE",
                "Synthesize evidence.",
                "Present the decision.",
                "None",
            ),
            RuntimeUsage(
                input_tokens=120,
                output_tokens=30,
                cached_input_tokens=10,
                cost_microusd=500,
            ),
        )

    async def steer(self, _message: str) -> bool:
        return False

    async def interrupt(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class UiReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.app = create_app(
            database_url=f"sqlite:///{root / 'ui.db'}",
            authenticator=TokenAuthenticator(),
            workspace_root=root / "workspaces",
            secret_key_path=root / "secret.key",
            agent_factory=lambda _slug, _engine: CompletingAgent(),
            poll_interval=0.01,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.app.state.runtime.database.dispose()
        self.temp_dir.cleanup()

    @staticmethod
    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def command(token: str, command_id: str | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": command_id or str(uuid4()),
            "X-Limina-Actor": "spoofed actor",
        }

    def create_project(self, slug: str = "ui-ready") -> None:
        response = self.client.post(
            "/v1/projects",
            headers=self.command("owner-token"),
            json={
                "slug": slug,
                "name": "UI ready",
                "objective": "Make every project surface queryable.",
                "success_criteria": "The typed API supports a collaborative UI.",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

    def test_oidc_principals_and_project_roles_are_enforced_centrally(self) -> None:
        self.create_project()

        owner_projects = self.client.get("/v1/projects", headers=self.auth("owner-token")).json()
        viewer_projects = self.client.get("/v1/projects", headers=self.auth("viewer-token")).json()
        self.assertEqual(owner_projects["total"], 1)
        self.assertEqual(viewer_projects["total"], 0)
        self.assertEqual(
            self.client.get("/v1/projects/ui-ready", headers=self.auth("viewer-token")).status_code,
            403,
        )

        member = self.client.put(
            "/v1/projects/ui-ready/members",
            headers=self.auth("owner-token"),
            json={
                "subject": "viewer",
                "display_name": "Victor Viewer",
                "email": "viewer@example.test",
                "role": "VIEWER",
            },
        )
        self.assertEqual(member.status_code, 200, member.text)
        self.assertEqual(
            self.client.get("/v1/projects/ui-ready", headers=self.auth("viewer-token")).status_code,
            200,
        )
        denied = self.client.post(
            "/v1/projects/ui-ready/actions/start",
            headers=self.command("viewer-token"),
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertEqual(denied.json()["error"]["code"], "permission_denied")

        orphan = self.client.put(
            "/v1/projects/ui-ready/members",
            headers=self.auth("owner-token"),
            json={
                "subject": "owner",
                "display_name": "Olivia Owner",
                "role": "EDITOR",
            },
        )
        self.assertEqual(orphan.status_code, 422, orphan.text)
        self.assertIn("retain at least one owner", orphan.text)

        events = self.client.get(
            "/v1/projects/ui-ready/events", headers=self.auth("owner-token")
        ).json()["events"]
        self.assertEqual(events[0]["actor"], "Olivia Owner")
        self.assertNotIn("spoofed actor", str(events))

    def test_idempotency_keys_are_scoped_to_signed_subjects(self) -> None:
        key = "shared-client-key"
        for token, slug in (("owner-token", "first"), ("same-name-token", "second")):
            response = self.client.post(
                "/v1/projects",
                headers=self.command(token, key),
                json={
                    "slug": slug,
                    "name": slug.title(),
                    "objective": f"Run {slug} mission.",
                    "success_criteria": "Produce durable evidence.",
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["slug"], slug)

        first = self.client.get("/v1/projects", headers=self.auth("owner-token")).json()
        second = self.client.get("/v1/projects", headers=self.auth("same-name-token")).json()
        self.assertEqual([item["slug"] for item in first["items"]], ["first"])
        self.assertEqual([item["slug"] for item in second["items"]], ["second"])

    def test_browser_ticket_is_single_use_and_supports_read_only_viewers(self) -> None:
        self.create_project()
        self.client.put(
            "/v1/projects/ui-ready/members",
            headers=self.auth("owner-token"),
            json={
                "subject": "viewer",
                "display_name": "Victor Viewer",
                "role": "VIEWER",
            },
        )
        ticket = self.client.post(
            "/v1/projects/ui-ready/live-ticket", headers=self.auth("viewer-token")
        )
        self.assertEqual(ticket.status_code, 200, ticket.text)
        value = ticket.json()["ticket"]
        with self.client.websocket_connect(
            "/v1/projects/ui-ready/live",
            subprotocols=["limina.v1", f"limina.ticket.{value}"],
        ) as socket:
            self.assertEqual(socket.receive_json()["type"], "snapshot")
            socket.send_json({"type": "steer", "body": "Try to mutate."})
            error = socket.receive_json()
            while error["type"] == "event":
                error = socket.receive_json()
            self.assertEqual(error["type"], "error")
            self.assertIn("Viewers", error["value"]["message"])

        with (
            self.assertRaises(WebSocketDisconnect),
            self.client.websocket_connect(
                "/v1/projects/ui-ready/live",
                subprotocols=["limina.v1", f"limina.ticket.{value}"],
            ),
        ):
            pass

        admin_ticket = self.client.post(
            "/v1/projects/ui-ready/live-ticket", headers=self.auth("admin-token")
        ).json()["ticket"]
        with self.client.websocket_connect(
            "/v1/projects/ui-ready/live",
            subprotocols=["limina.v1", f"limina.ticket.{admin_ticket}"],
        ) as socket:
            self.assertEqual(socket.receive_json()["type"], "snapshot")
            socket.send_json({"type": "steer", "body": "Review the current strategy."})
            delivery = socket.receive_json()
            while delivery["type"] == "event":
                delivery = socket.receive_json()
            self.assertEqual(delivery["type"], "delivery")

    def test_kickoff_knowledge_sources_runs_and_analytics_are_queryable(self) -> None:
        self.create_project()
        updated = self.client.patch(
            "/v1/projects/ui-ready",
            headers=self.auth("owner-token"),
            json={"context": "A richer kickoff context."},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["context"], "A richer kickoff context.")
        self.assertEqual(
            self.client.get("/v1/project-templates", headers=self.auth("owner-token")).status_code,
            200,
        )
        preflight = self.client.get(
            "/v1/projects/ui-ready/preflight", headers=self.auth("owner-token")
        )
        self.assertTrue(preflight.json()["ready"])

        source = self.client.put(
            "/v1/projects/ui-ready/sources",
            headers=self.auth("owner-token"),
            json={
                "name": "benchmark",
                "type": "URL",
                "uri": "https://example.test/benchmark",
                "metadata": {"purpose": "evaluation"},
            },
        )
        self.assertEqual(source.status_code, 200, source.text)
        credential_source = self.client.put(
            "/v1/projects/ui-ready/sources",
            headers=self.auth("owner-token"),
            json={
                "name": "unsafe",
                "type": "URL",
                "uri": "https://example.test/data?access_token=secret",
            },
        )
        self.assertEqual(credential_source.status_code, 422, credential_source.text)
        connector_credential = self.client.put(
            "/v1/projects/ui-ready/sources",
            headers=self.auth("owner-token"),
            json={
                "name": "unsafe-connector",
                "type": "CONNECTOR",
                "uri": "github://user:token@example.test/repository",
            },
        )
        self.assertEqual(connector_credential.status_code, 422, connector_credential.text)
        upload = self.client.post(
            "/v1/projects/ui-ready/sources/upload",
            headers=self.auth("owner-token"),
            data={"name": "brief"},
            files={"file": ("brief.md", b"# Brief\nEvidence", "text/markdown")},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        self.assertEqual(upload.json()["type"], "UPLOAD")

        service = self.app.state.runtime.service
        first = service.create_hypothesis(
            slug="ui-ready",
            title="Hybrid retrieval",
            statement="Full-text retrieval narrows the graph.",
            mechanism="Lexical matching",
            generalization="Across artifacts",
            shortcut_risks="Vocabulary mismatch",
            test_plan="Query known terms",
            actor="Limina",
            command_id=str(uuid4()),
        )
        second = service.create_hypothesis(
            slug="ui-ready",
            title="Graph navigation",
            statement="Explicit links improve review.",
            mechanism="Backlinks",
            generalization="Across findings",
            shortcut_risks="Noisy links",
            test_plan="Review relation graph",
            actor="Limina",
            command_id=str(uuid4()),
        )
        search = self.client.get(
            "/v1/projects/ui-ready/knowledge?query=retrieval",
            headers=self.auth("owner-token"),
        )
        self.assertEqual(search.status_code, 200, search.text)
        self.assertEqual(search.json()["items"][0]["id"], first["id"])
        self.assertEqual(search.json()["search_backend"], "portable-substring")
        wildcard = self.client.get(
            "/v1/projects/ui-ready/knowledge?query=%25",
            headers=self.auth("owner-token"),
        )
        self.assertEqual(wildcard.json()["total"], 0)
        first_page = self.client.get(
            "/v1/projects/ui-ready/knowledge?limit=1",
            headers=self.auth("owner-token"),
        ).json()
        self.assertIsNotNone(first_page["next_cursor"])
        second_page = self.client.get(
            f"/v1/projects/ui-ready/knowledge?limit=1&cursor={first_page['next_cursor']}",
            headers=self.auth("owner-token"),
        ).json()
        self.assertNotEqual(first_page["items"][0]["id"], second_page["items"][0]["id"])
        tagged = self.client.put(
            f"/v1/projects/ui-ready/knowledge/{first['id']}/tags/retrieval",
            headers=self.auth("owner-token"),
        )
        self.assertEqual(tagged.status_code, 200, tagged.text)
        self.assertEqual(tagged.json()["tags"], ["retrieval"])
        tag_search = self.client.get(
            "/v1/projects/ui-ready/knowledge?tag=retrieval",
            headers=self.auth("owner-token"),
        )
        self.assertEqual(tag_search.json()["total"], 1)
        self.assertEqual(tag_search.json()["items"][0]["tags"], ["retrieval"])

        relation = self.client.post(
            "/v1/projects/ui-ready/knowledge/relations",
            headers=self.auth("owner-token"),
            json={"source_id": first["id"], "target_id": second["id"], "type": "SUPPORTS"},
        )
        self.assertEqual(relation.status_code, 201, relation.text)
        graph = self.client.get(
            "/v1/projects/ui-ready/knowledge/graph", headers=self.auth("owner-token")
        ).json()
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(graph["edges"][0]["type"], "SUPPORTS")

        comment = self.client.post(
            f"/v1/projects/ui-ready/knowledge/{first['id']}/comments",
            headers=self.command("owner-token"),
            json={"body": "Please test vocabulary drift."},
        )
        self.assertEqual(comment.status_code, 201, comment.text)
        self.create_project("comment-boundary")
        other = service.create_hypothesis(
            slug="comment-boundary",
            title="Separate tenant artifact",
            statement="Comments remain tenant scoped.",
            mechanism="Project-scoped foreign keys",
            generalization="Across every project",
            shortcut_risks="Reused client keys",
            test_plan="Reuse one key across two projects.",
            actor="Limina",
            command_id=str(uuid4()),
        )
        reused_key = "predictable-comment-key"
        original = self.client.post(
            f"/v1/projects/ui-ready/knowledge/{first['id']}/comments",
            headers=self.command("owner-token", reused_key),
            json={"body": "Private project comment."},
        )
        self.assertEqual(original.status_code, 201, original.text)
        collision = self.client.post(
            f"/v1/projects/comment-boundary/knowledge/{other['id']}/comments",
            headers=self.command("owner-token", reused_key),
            json={"body": "A different comment."},
        )
        self.assertEqual(collision.status_code, 409, collision.text)
        self.assertNotIn("Private project comment", collision.text)
        revisions = self.client.get(
            f"/v1/projects/ui-ready/knowledge/{first['id']}/revisions",
            headers=self.auth("owner-token"),
        )
        self.assertEqual(revisions.status_code, 200, revisions.text)
        self.assertEqual(revisions.json()[0]["version"], 1)
        view = self.client.put(
            "/v1/projects/ui-ready/knowledge/views",
            headers=self.auth("owner-token"),
            json={"name": "Open hypotheses", "query": {"kind": "H", "status": "PROPOSED"}},
        )
        self.assertEqual(view.status_code, 200, view.text)

        guidance = self.client.post(
            "/v1/projects/ui-ready/steering",
            headers=self.command("owner-token"),
            json={"body": "Prioritize the strongest evidence.", "kind": "STEER"},
        )
        self.assertEqual(guidance.status_code, 202, guidance.text)
        started = self.client.post(
            "/v1/projects/ui-ready/actions/start", headers=self.command("owner-token")
        )
        self.assertEqual(started.status_code, 200, started.text)

        deadline = time.monotonic() + 2
        runs = None
        while time.monotonic() < deadline:
            runs = self.client.get(
                "/v1/projects/ui-ready/runs", headers=self.auth("owner-token")
            ).json()
            if runs["items"] and runs["items"][0]["status"] == "COMPLETED":
                break
            time.sleep(0.02)
        self.assertIsNotNone(runs)
        run = runs["items"][0]
        self.assertEqual(run["status"], "COMPLETED")
        self.assertEqual(run["usage"]["input_tokens"], 120)
        self.assertEqual(run["tool_calls"], 1)
        detail = self.client.get(
            f"/v1/projects/ui-ready/runs/{run['id']}", headers=self.auth("owner-token")
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertGreaterEqual(len(detail.json()["events"]), 3)
        self.assertNotIn("private-thread", detail.text)
        self.assertNotIn("private-continuation", detail.text)
        self.assertIn("Updating durable project knowledge", detail.text)

        history = self.client.get(
            "/v1/projects/ui-ready/guidance", headers=self.auth("owner-token")
        ).json()
        self.assertEqual(history["items"][0]["body"], "Prioritize the strongest evidence.")
        self.assertEqual(history["items"][0]["status"], "ACKNOWLEDGED")
        analytics = self.client.get(
            "/v1/projects/ui-ready/analytics", headers=self.auth("owner-token")
        )
        self.assertEqual(analytics.status_code, 200, analytics.text)
        self.assertEqual(analytics.json()["runs"]["total"], 1)
        self.assertEqual(analytics.json()["knowledge"]["by_kind"]["H"], 2)

        schema = self.client.get("/openapi.json").json()
        knowledge_schema = schema["paths"]["/v1/projects/{slug}/knowledge"]["get"]["responses"][
            "200"
        ]["content"]["application/json"]["schema"]
        self.assertEqual(knowledge_schema, {"$ref": "#/components/schemas/KnowledgePage"})


if __name__ == "__main__":
    unittest.main()
