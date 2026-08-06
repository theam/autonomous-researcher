from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*"
)

from starlette.testclient import TestClient  # noqa: E402

from limina_cloud.api import create_app  # noqa: E402


class CloudMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.app = create_app(
            database_url=f"sqlite:///{root / 'mcp.db'}",
            token="secret",
            workspace_root=root / "workspaces",
            secret_key_path=root / "secret.key",
        )
        self.client_context = TestClient(self.app, base_url="http://localhost:7433")
        self.client = self.client_context.__enter__()
        self.headers = {
            "Authorization": "Bearer secret",
            "X-Limina-Actor": "maya",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        initialized = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "limina-tests", "version": "1"},
            },
        )
        self.assertEqual(initialized.status_code, 200, initialized.text)

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.app.state.runtime.database.dispose()
        self.temp_dir.cleanup()

    def request(self, method: str, params: dict, *, request_id: int = 1):
        return self.client.post(
            "/mcp/",
            headers=self.headers,
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )

    def call_tool(self, name: str, arguments: dict, *, request_id: int = 2) -> dict:
        response = self.request(
            "tools/call", {"name": name, "arguments": arguments}, request_id=request_id
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertFalse(result.get("isError", False), result)
        return result["structuredContent"]

    def test_mcp_uses_the_same_authenticated_public_boundary(self) -> None:
        unauthorized = self.client.post(
            "/mcp/",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.json()["error"]["code"], "authentication_required")

        with self.assertLogs("mcp.server.transport_security", level="WARNING"):
            rebinding = self.client.post(
                "/mcp/",
                headers={**self.headers, "Host": "attacker.invalid"},
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
        self.assertEqual(rebinding.status_code, 421)

        health = self.client.get("/healthz", headers={"Authorization": "Bearer secret"})
        self.assertEqual(health.json()["interfaces"]["mcp"], "/mcp/")

        listed = self.request("tools/list", {}, request_id=3).json()["result"]["tools"]
        names = {tool["name"] for tool in listed}
        self.assertIn("limina_create_project", names)
        self.assertIn("limina_steer_project", names)
        self.assertIn("limina_review_project", names)
        self.assertNotIn("limina_set_project_secret", names)
        create_tool = next(tool for tool in listed if tool["name"] == "limina_create_project")
        properties = create_tool["inputSchema"]["properties"]
        self.assertEqual(properties["actor"]["maxLength"], 200)
        self.assertEqual(properties["idempotency_key"]["maxLength"], 55)
        serialized = str(listed).lower()
        for forbidden in ("thread_id", "session_id", "worker_id", "subagent"):
            self.assertNotIn(forbidden, serialized)

    def test_mcp_and_rest_share_projects_resources_and_audit_history(self) -> None:
        arguments = {
            "slug": "mcp-project",
            "name": "MCP project",
            "mission": "Prove the shared application contract.",
            "success_criteria": "MCP and REST observe one durable project.",
            "runtime": "claude-code",
            "idempotency_key": "create-mcp-project",
        }
        first = self.call_tool("limina_create_project", arguments, request_id=4)
        replay = self.call_tool("limina_create_project", arguments, request_id=5)
        self.assertEqual(first, replay)
        self.assertEqual(first["runtime"], "claude-code")

        project = self.client.get(
            "/v2/projects/mcp-project",
            headers={"Authorization": "Bearer secret"},
        )
        self.assertEqual(project.status_code, 200, project.text)
        self.assertEqual(project.json(), first)

        interrupt_arguments = {
            "project": "mcp-project",
            "message": "Pause before execution and wait for the revised benchmark.",
            "kind": "INTERRUPT",
            "idempotency_key": "interrupt-before-start",
        }
        interrupted = self.call_tool("limina_steer_project", interrupt_arguments, request_id=6)
        interrupt_replay = self.call_tool("limina_steer_project", interrupt_arguments, request_id=7)
        self.assertEqual(interrupted, interrupt_replay)

        variable = self.call_tool(
            "limina_set_project_variable",
            {
                "project": "mcp-project",
                "name": "EVAL_SET_URI",
                "value": "s3://research/eval-v3.parquet",
                "idempotency_key": "set-eval-uri",
            },
            request_id=8,
        )
        self.assertEqual(variable["type"], "VARIABLE")

        resources = self.client.get(
            "/v2/projects/mcp-project/resources",
            headers={"Authorization": "Bearer secret"},
        ).json()
        self.assertEqual(resources, [variable])
        events = self.client.get(
            "/v2/projects/mcp-project/events",
            headers={"Authorization": "Bearer secret"},
        ).json()["events"]
        self.assertEqual(events[0]["actor"], "maya")
        self.assertEqual([event["type"] for event in events].count("project.created"), 1)
        self.assertEqual([event["type"] for event in events].count("guidance.received"), 2)

    def test_mcp_resources_expose_read_only_project_knowledge(self) -> None:
        self.call_tool(
            "limina_create_project",
            {
                "slug": "reviewable",
                "name": "Reviewable",
                "mission": "Make durable work reviewable.",
                "success_criteria": "The MCP resource returns the project review.",
                "actor": "reviewer",
            },
            request_id=9,
        )
        response = self.request(
            "resources/read",
            {"uri": "limina://projects/reviewable/review"},
            request_id=10,
        )
        self.assertEqual(response.status_code, 200, response.text)
        content = response.json()["result"]["contents"][0]
        self.assertEqual(content["mimeType"], "application/json")
        self.assertIn('"mission": "Make durable work reviewable."', content["text"])

        status = self.call_tool(
            "limina_get_project_status", {"project": "reviewable"}, request_id=11
        )
        self.assertEqual(status["project"]["slug"], "reviewable")
        self.assertEqual(status["knowledge"], {})


if __name__ == "__main__":
    unittest.main()
