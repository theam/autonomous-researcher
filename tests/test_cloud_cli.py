from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

from typer.testing import CliRunner

from limina_cloud.cli import app
from limina_cloud.database import Database
from limina_cloud.service import ChallengeService


class FakePublicClient:
    last_secret: str | None = None

    def __init__(self, _url: str, _token: str | None) -> None:
        pass

    def create_project(self, payload, *, actor, command_id):
        return {
            "slug": payload["slug"],
            "name": payload["name"],
            "mission": payload["objective"],
            "success_criteria": payload["success_criteria"],
            "context": payload["context"],
            "status": "CREATED",
            "current_objective": payload["objective"],
            "next_step": "Frame the first falsifiable hypothesis.",
            "blocker": "None",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    def set_variable(self, _project, name, value, *, actor, command_id):
        return {
            "name": name,
            "type": "VARIABLE",
            "value": value,
            "configured": None,
            "status": "ACTIVE",
        }

    def set_secret(self, _project, name, value, *, actor, command_id):
        type(self).last_secret = value
        return {
            "name": name,
            "type": "SECRET",
            "configured": True,
            "status": "ACTIVE",
        }

    def close(self) -> None:
        pass


class CloudCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp_dir.name) / "cli.db")
        self.runner = CliRunner()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_public_help_exposes_only_project_level_concepts(self) -> None:
        result = self.runner.invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        for command in ("project", "review", "steer", "attach", "resource", "status"):
            self.assertIn(command, result.output)
        for internal in ("_agent", "worker", "coordinator", "thread", "lease"):
            self.assertNotIn(internal, result.output.lower())

    def test_project_create_has_stable_json_output(self) -> None:
        with mock.patch("limina_cloud.cli.HttpRuntimeClient", FakePublicClient):
            result = self.runner.invoke(
                app,
                [
                    "--json",
                    "project",
                    "create",
                    "cli-test",
                    "--mission",
                    "Prove CLI composition.",
                    "--success",
                    "Project state is returned.",
                ],
            )
        self.assertEqual(result.exit_code, 0, result.output)
        value = json.loads(result.output)
        self.assertEqual(value["slug"], "cli-test")
        self.assertEqual(value["status"], "CREATED")
        self.assertNotIn("thread_id", value)

    def test_resource_commands_make_secrets_write_only(self) -> None:
        secret_value = "cli-super-secret"
        FakePublicClient.last_secret = None
        with mock.patch("limina_cloud.cli.HttpRuntimeClient", FakePublicClient):
            help_result = self.runner.invoke(app, ["resource", "--help"])
            variable = self.runner.invoke(
                app,
                ["--json", "resource", "variable", "cli-test", "SOURCE_URL", "s3://data"],
            )
            secret = self.runner.invoke(
                app,
                [
                    "--json",
                    "resource",
                    "secret",
                    "cli-test",
                    "SOURCE_TOKEN",
                    "--from-env",
                    "TEST_SOURCE_TOKEN",
                ],
                env={"TEST_SOURCE_TOKEN": secret_value},
            )

        self.assertEqual(help_result.exit_code, 0, help_result.output)
        self.assertIn("variable", help_result.output)
        self.assertIn("secret", help_result.output)
        self.assertEqual(variable.exit_code, 0, variable.output)
        self.assertEqual(json.loads(variable.output)["value"], "s3://data")
        self.assertEqual(secret.exit_code, 0, secret.output)
        self.assertNotIn(secret_value, secret.output)
        self.assertNotIn("value", json.loads(secret.output))
        self.assertEqual(FakePublicClient.last_secret, secret_value)

    def test_hidden_agent_protocol_can_write_the_research_graph(self) -> None:
        database_url = f"sqlite:///{self.database}"
        database = Database(database_url)
        database.initialize()
        service = ChallengeService(database)
        service.create_challenge(
            slug="agent-test",
            name="Agent test",
            objective="Validate the private protocol.",
            context="",
            success_criteria="Create a hypothesis.",
            actor="owner",
            command_id=str(uuid4()),
        )
        database.dispose()

        result = self.runner.invoke(
            app,
            [
                "--database",
                database_url,
                "--actor",
                "limina-runtime",
                "_agent",
                "hypothesis",
                "add",
                "Typed internal command",
                "--statement",
                "Typed commands preserve the H to E to F contract.",
            ],
            env={"LIMINA_PROJECT": "agent-test"},
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.output)["id"], "H001")


if __name__ == "__main__":
    unittest.main()
