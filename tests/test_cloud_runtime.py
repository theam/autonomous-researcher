from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
from uuid import uuid4

from limina_cloud.database import Database
from limina_cloud.errors import ConflictError, InvariantError, LeaseConflictError, NotFoundError
from limina_cloud.exporter import MarkdownExporter
from limina_cloud.runtime import (
    ProjectSupervisor,
    RuntimeDecision,
    RuntimeEvent,
    RuntimeTurn,
    _codex_environment,
    _redact_event,
    _redact_turn,
)
from limina_cloud.service import ChallengeService
from limina_cloud.vault import SecretCipher

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "kb_validate.py"


def command_id() -> str:
    return str(uuid4())


class CloudRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_url = f"sqlite:///{Path(self.temp_dir.name) / 'runtime.db'}"
        self.database = Database(self.database_url)
        self.database.initialize()
        self.secret_cipher = SecretCipher.ephemeral()
        self.service = ChallengeService(self.database, self.secret_cipher)
        self.service.create_challenge(
            slug="retrieval",
            name="Retrieval quality",
            objective="Improve retrieval quality.",
            context="Existing hybrid baseline.",
            success_criteria="Improve NDCG without a latency regression.",
            actor="owner",
            command_id=command_id(),
        )

    def tearDown(self) -> None:
        self.database.dispose()
        self.temp_dir.cleanup()

    def create_hypothesis(self, title: str = "Reranking") -> dict[str, object]:
        return self.service.create_hypothesis(
            slug="retrieval",
            title=title,
            statement="A stronger reranker improves NDCG.",
            mechanism="Pairwise relevance modeling.",
            generalization="The mechanism is query independent.",
            shortcut_risks="Overfitting the fixture.",
            test_plan="Use a frozen candidate set.",
            actor="researcher",
            command_id=command_id(),
        )

    def create_experiment(self, hypothesis_id: str, title: str = "Benchmark") -> dict[str, object]:
        return self.service.create_experiment(
            slug="retrieval",
            hypothesis_id=hypothesis_id,
            title=title,
            objective="Measure NDCG and latency.",
            procedure="Run baseline and treatment.",
            success_criteria="At least 10 percent NDCG improvement.",
            guardrails="Use identical candidates and hardware.",
            actor="researcher",
            command_id=command_id(),
        )

    def test_codex_child_environment_excludes_control_plane_secrets(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sdk-key",
                "LIMINA_DATABASE_URL": "postgresql://control-plane",
                "LIMINA_API_TOKEN": "admin-token",
                "LIMINA_SECRET_KEY": "master-key",
                "UNRELATED_SECRET": "other-secret",
            },
            clear=True,
        ):
            child = _codex_environment(
                {
                    "LIMINA_INTERNAL_URL": "http://runtime:7433",
                    "LIMINA_INTERNAL_TOKEN": "project-capability",
                }
            )

        self.assertEqual(child["OPENAI_API_KEY"], "sdk-key")
        self.assertEqual(child["LIMINA_DATABASE_URL"], "")
        self.assertEqual(child["LIMINA_API_TOKEN"], "")
        self.assertEqual(child["LIMINA_SECRET_KEY"], "")
        self.assertEqual(child["UNRELATED_SECRET"], "")
        self.assertEqual(child["LIMINA_INTERNAL_TOKEN"], "project-capability")

    def test_runtime_events_and_decisions_redact_project_secret_values(self) -> None:
        values = ("sensitive-123",)
        event = _redact_event(
            RuntimeEvent(
                "runtime.codex",
                "Used sensitive-123",
                {"nested": ["sensitive-123", {"value": "prefix-sensitive-123"}]},
            ),
            values,
        )
        turn = _redact_turn(
            RuntimeTurn(
                "thread",
                "turn",
                RuntimeDecision(
                    "Found sensitive-123",
                    "WAITING",
                    "Rotate sensitive-123",
                    "Ask for access",
                    "sensitive-123 expired",
                ),
            ),
            values,
        )
        self.assertNotIn("sensitive-123", str(event))
        self.assertNotIn("sensitive-123", str(turn))
        self.assertIn("[REDACTED]", str(event))
        self.assertIn("[REDACTED]", str(turn))

    def test_sqlite_utc_timestamps_survive_a_read_round_trip(self) -> None:
        created = self.service.create_hypothesis(
            slug="retrieval",
            title="Timestamp round trip",
            statement="UTC timestamps remain stable after persistence.",
            mechanism="Naive SQLite values are interpreted as UTC.",
            generalization="All persisted runtime timestamps use the same serializer.",
            shortcut_risks="None.",
            test_plan="Compare the write response to a fresh read.",
            actor="researcher",
            command_id=command_id(),
        )
        loaded = self.service.get_artifact("retrieval", str(created["id"]))
        self.assertEqual(created["created_at"], loaded["created_at"])
        self.assertTrue(str(loaded["created_at"]).endswith("+00:00"))

    def test_hef_invariants_are_enforced_transactionally(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.create_experiment(
                slug="retrieval",
                hypothesis_id="H999",
                title="Invalid",
                objective="Cannot run.",
                procedure="",
                success_criteria="",
                guardrails="",
                actor="researcher",
                command_id=command_id(),
            )

        hypothesis = self.create_hypothesis()
        experiment = self.create_experiment(str(hypothesis["id"]))
        with self.assertRaises(InvariantError):
            self.service.publish_finding(
                slug="retrieval",
                experiment_id=str(experiment["id"]),
                title="Premature",
                finding="Not established.",
                evidence="None.",
                improvement="",
                remaining_debt="",
                next_move="",
                impact="LOW",
                actor="researcher",
                command_id=command_id(),
            )

    def test_command_replay_is_idempotent(self) -> None:
        replay_key = command_id()
        payload = dict(
            slug="retrieval",
            title="Stable replay",
            statement="The command produces one artifact.",
            mechanism="Receipt lookup.",
            generalization="All typed commands use the same boundary.",
            shortcut_risks="None.",
            test_plan="Replay the command.",
            actor="researcher",
            command_id=replay_key,
        )
        first = self.service.create_hypothesis(**payload)
        second = self.service.create_hypothesis(**payload)
        self.assertEqual(first, second)
        self.assertEqual(len(self.service.list_artifacts("retrieval", "H")), 1)

    def test_parallel_artifact_creation_allocates_unique_ids(self) -> None:
        def create(index: int) -> str:
            result = self.service.create_hypothesis(
                slug="retrieval",
                title=f"Hypothesis {index}",
                statement=f"Claim {index}",
                mechanism="Independent mechanism.",
                generalization="Independent scope.",
                shortcut_risks="None.",
                test_plan="Test independently.",
                actor=f"worker-{index}",
                command_id=command_id(),
            )
            return str(result["id"])

        with ThreadPoolExecutor(max_workers=8) as executor:
            ids = list(executor.map(create, range(12)))

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {f"H{index:03d}" for index in range(1, 13)})

    def test_parallel_experiments_share_only_the_hypothesis_transition(self) -> None:
        hypothesis = self.create_hypothesis()

        def create(index: int) -> str:
            result = self.create_experiment(
                str(hypothesis["id"]),
                title=f"Independent lane {index}",
            )
            return str(result["id"])

        with ThreadPoolExecutor(max_workers=8) as executor:
            ids = list(executor.map(create, range(12)))

        self.assertEqual(set(ids), {f"E{index:03d}" for index in range(1, 13)})
        updated = self.service.get_artifact("retrieval", str(hypothesis["id"]))
        self.assertEqual(updated["status"], "TESTING")
        self.assertEqual(updated["version"], 2)

    def test_experiment_leases_are_scoped_not_global(self) -> None:
        hypothesis = self.create_hypothesis()
        first = self.create_experiment(str(hypothesis["id"]), "First lane")
        second = self.create_experiment(str(hypothesis["id"]), "Second lane")

        def claim(artifact_id: str, actor: str) -> dict[str, object]:
            return self.service.claim_experiment(
                slug="retrieval",
                artifact_id=artifact_id,
                ttl_seconds=300,
                actor=actor,
                command_id=command_id(),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(
                executor.map(
                    lambda args: claim(*args),
                    [(str(first["id"]), "worker-a"), (str(second["id"]), "worker-b")],
                )
            )

        self.assertEqual({item["lease"]["owner"] for item in claims}, {"worker-a", "worker-b"})
        with self.assertRaises(LeaseConflictError):
            claim(str(first["id"]), "worker-b")

    def test_coordinator_lease_prevents_duplicate_execution(self) -> None:
        self.service.claim_coordinator(
            slug="retrieval",
            ttl_seconds=300,
            actor="worker-a",
            command_id=command_id(),
        )
        with self.assertRaises(LeaseConflictError):
            self.service.claim_coordinator(
                slug="retrieval",
                ttl_seconds=300,
                actor="worker-b",
                command_id=command_id(),
            )
        self.service.release_coordinator(
            slug="retrieval",
            actor="worker-a",
            command_id=command_id(),
        )
        claimed = self.service.claim_coordinator(
            slug="retrieval",
            ttl_seconds=300,
            actor="worker-b",
            command_id=command_id(),
        )
        self.assertEqual(claimed["owner"], "worker-b")

    def test_supervisor_owns_thread_and_consumes_guidance_after_success(self) -> None:
        message = self.service.send_message(
            slug="retrieval",
            kind="STEER",
            body="Prioritize the latency guardrail.",
            actor="owner",
            command_id=command_id(),
        )

        class FakeSession:
            prompt = ""
            runtime_env: dict[str, str] = {}

            async def run_turn(self, **values):
                self.prompt = values["prompt"]
                self.runtime_env = values["runtime_env"]
                values["on_thread"]("thread-123")
                return RuntimeTurn(
                    "thread-123",
                    "turn-456",
                    RuntimeDecision(
                        "Checkpoint complete.",
                        "COMPLETE",
                        "Verify the result.",
                        "Present the finding for review.",
                        "None",
                    ),
                )

            async def steer(self, _message: str) -> bool:
                return False

            async def interrupt(self) -> bool:
                return False

            async def close(self) -> None:
                return None

        session = FakeSession()
        self.service.set_variable(
            slug="retrieval",
            name="SOURCE_URL",
            value="https://example.invalid/source",
            actor="owner",
            command_id=command_id(),
        )
        self.service.set_secret(
            slug="retrieval",
            name="SOURCE_TOKEN",
            value="scoped-secret",
            actor="owner",
            command_id=command_id(),
        )
        self.service.change_project_state(
            slug="retrieval",
            action="start",
            actor="owner",
            command_id=command_id(),
        )
        supervisor = ProjectSupervisor(
            self.service,
            MarkdownExporter(self.service),
            workspace_root=Path(self.temp_dir.name) / "workspaces",
            internal_url="http://127.0.0.1:7433",
            agent_factory=lambda _slug: session,
            lease_ttl_seconds=300,
        )

        async def run() -> None:
            await supervisor.ensure_running("retrieval")
            await supervisor._tasks["retrieval"]
            await supervisor.shutdown()

        with mock.patch.dict(os.environ, {"UNRELATED_SECRET": "never-copy"}):
            asyncio.run(run())
        status = self.service.status("retrieval")
        pending = self.service.inbox("retrieval", after=0, pending_only=True)
        events = self.service.events("retrieval", after=0, limit=200)

        self.assertEqual(status["challenge"]["coordinator"]["thread_id"], "thread-123")
        self.assertEqual(status["challenge"]["coordinator"]["inbox_cursor"], message["sequence"])
        self.assertEqual(pending, [])
        self.assertIn("Prioritize the latency guardrail", session.prompt)
        self.assertIn("SOURCE_URL", session.prompt)
        self.assertIn("SOURCE_TOKEN", session.prompt)
        self.assertNotIn("scoped-secret", session.prompt)
        self.assertEqual(session.runtime_env["SOURCE_URL"], "https://example.invalid/source")
        self.assertEqual(session.runtime_env["SOURCE_TOKEN"], "scoped-secret")
        self.assertNotIn("UNRELATED_SECRET", session.runtime_env)
        self.assertNotIn("LIMINA_DATABASE_URL", session.runtime_env)
        self.assertEqual(
            [item["sequence"] for item in events], sorted(item["sequence"] for item in events)
        )
        checkpoint_event = [item for item in events if item["type"] == "coordinator.checkpointed"][
            -1
        ]
        self.assertTrue(checkpoint_event["actor"].startswith("limina:"))
        self.assertEqual(checkpoint_event["payload"]["messages_acknowledged"], 1)

    def test_secret_resources_are_encrypted_redacted_and_project_bound(self) -> None:
        plaintext = "never-store-this-plaintext"
        resource = self.service.set_secret(
            slug="retrieval",
            name="SERVICE_TOKEN",
            value=plaintext,
            actor="owner",
            command_id=command_id(),
        )
        self.assertEqual(resource["type"], "SECRET")
        self.assertIsNone(resource["value"])
        self.assertTrue(resource["configured"])

        with self.database.engine.connect() as connection:
            ciphertext = connection.exec_driver_sql(
                "SELECT secret_ciphertext FROM project_resources WHERE name = 'SERVICE_TOKEN'"
            ).scalar_one()
            receipts = connection.exec_driver_sql("SELECT result FROM command_receipts").fetchall()
        self.assertNotEqual(ciphertext, plaintext)
        self.assertNotIn(plaintext, ciphertext)
        self.assertNotIn(plaintext, str(receipts))
        self.assertNotIn(plaintext, str(self.service.list_resources("retrieval")))
        self.assertNotIn(plaintext, str(self.service.events("retrieval", after=0, limit=200)))
        self.assertEqual(self.service.resource_environment("retrieval")["SERVICE_TOKEN"], plaintext)

        with self.assertRaises(InvariantError):
            self.secret_cipher.decrypt(
                project="other-project",
                name="SERVICE_TOKEN",
                ciphertext=ciphertext,
            )

        for reserved_name in ("PATH", "LIMINA_INTERNAL_TOKEN", "OPENAI_BASE_URL"):
            with self.assertRaises(InvariantError):
                self.service.set_variable(
                    slug="retrieval",
                    name=reserved_name,
                    value="unsafe",
                    actor="owner",
                    command_id=command_id(),
                )

        rotated = self.service.set_secret(
            slug="retrieval",
            name="SERVICE_TOKEN",
            value="rotated-value",
            actor="owner",
            command_id=command_id(),
        )
        self.assertTrue(rotated["configured"])
        self.assertEqual(
            self.service.resource_environment("retrieval")["SERVICE_TOKEN"],
            "rotated-value",
        )
        self.assertEqual(
            len(
                [
                    item
                    for item in self.service.list_resources("retrieval")
                    if item["name"] == "SERVICE_TOKEN"
                ]
            ),
            1,
        )

        removed = self.service.remove_resource(
            slug="retrieval",
            name="SERVICE_TOKEN",
            actor="owner",
            command_id=command_id(),
        )
        self.assertFalse(removed["configured"])
        self.assertNotIn("SERVICE_TOKEN", self.service.resource_environment("retrieval"))
        with self.database.engine.connect() as connection:
            wiped = connection.exec_driver_sql(
                "SELECT value, secret_ciphertext FROM project_resources "
                "WHERE name = 'SERVICE_TOKEN'"
            ).one()
        self.assertEqual(tuple(wiped), (None, None))

    def test_generated_secret_key_survives_instance_restart(self) -> None:
        key_path = Path(self.temp_dir.name) / "persistent-secret.key"
        with mock.patch.dict(os.environ, {}, clear=True):
            first = SecretCipher.load(key_path)
            ciphertext = first.encrypt(project="retrieval", name="TOKEN", value="durable")
            second = SecretCipher.load(key_path)

        self.assertEqual(
            second.decrypt(project="retrieval", name="TOKEN", ciphertext=ciphertext),
            "durable",
        )
        self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)

    def test_live_steering_reaches_the_active_managed_turn(self) -> None:
        class BlockingSession:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.finish = asyncio.Event()
                self.steering: list[str] = []

            async def run_turn(self, **_values):
                _values["on_thread"]("thread-live")
                self.started.set()
                await self.finish.wait()
                return RuntimeTurn(
                    "thread-live",
                    "turn-live",
                    RuntimeDecision("Steered.", "COMPLETE", "Done", "Review", "None"),
                )

            async def steer(self, message: str) -> bool:
                self.steering.append(message)
                self.finish.set()
                return True

            async def interrupt(self) -> bool:
                self.finish.set()
                return True

            async def close(self) -> None:
                return None

        session = BlockingSession()
        self.service.change_project_state(
            slug="retrieval", action="start", actor="owner", command_id=command_id()
        )
        supervisor = ProjectSupervisor(
            self.service,
            MarkdownExporter(self.service),
            workspace_root=Path(self.temp_dir.name) / "workspaces",
            internal_url="http://127.0.0.1:7433",
            agent_factory=lambda _slug: session,
            lease_ttl_seconds=300,
        )

        async def run() -> dict[str, object]:
            await supervisor.ensure_running("retrieval")
            await session.started.wait()
            delivery = await supervisor.submit_message(
                slug="retrieval",
                body="Change the strategy now.",
                kind="STEER",
                actor="reviewer",
            )
            await supervisor._tasks["retrieval"]
            await supervisor.shutdown()
            return delivery

        delivery = asyncio.run(run())
        self.assertEqual(delivery["delivery"], "LIVE")
        self.assertEqual(session.steering, ["reviewer: Change the strategy now."])
        self.assertEqual(self.service.inbox("retrieval", pending_only=True), [])

    def test_append_only_observations_do_not_contend_on_artifact_version(self) -> None:
        hypothesis = self.create_hypothesis()
        experiment = self.create_experiment(str(hypothesis["id"]))
        artifact_id = str(experiment["id"])
        self.service.claim_experiment(
            slug="retrieval",
            artifact_id=artifact_id,
            ttl_seconds=300,
            actor="worker",
            command_id=command_id(),
        )

        def observe(index: int) -> None:
            self.service.append_observation(
                slug="retrieval",
                artifact_id=artifact_id,
                body=f"Observation {index}",
                evidence_ref=f"s3://evidence/{index}.json",
                actor="worker",
                command_id=command_id(),
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(observe, range(20)))

        detailed = self.service.get_artifact("retrieval", artifact_id)
        self.assertEqual(detailed["version"], 2)
        self.assertEqual(len(detailed["observations"]), 20)

    def test_stale_artifact_and_coordinator_writes_are_rejected(self) -> None:
        hypothesis = self.create_hypothesis()
        with self.assertRaises(ConflictError):
            self.service.decide_hypothesis(
                slug="retrieval",
                artifact_id=str(hypothesis["id"]),
                status="CONFIRMED",
                conclusion="Stale decision.",
                expected_version=99,
                actor="reviewer",
                command_id=command_id(),
            )

        checkpoint = self.service.checkpoint_coordinator(
            slug="retrieval",
            current_objective="Run two lanes.",
            next_step="Wait for experiments.",
            blocker="None",
            status="RUNNING",
            worker_id="coordinator-a",
            thread_id="thread-a",
            inbox_cursor=0,
            expected_version=1,
            actor="coordinator-a",
            command_id=command_id(),
        )
        self.assertEqual(checkpoint["version"], 2)
        pending_message = self.service.send_message(
            slug="retrieval",
            kind="COMMENT",
            body="This must remain pending when the checkpoint conflicts.",
            actor="owner",
            command_id=command_id(),
        )
        with self.assertRaises(ConflictError):
            self.service.checkpoint_coordinator(
                slug="retrieval",
                current_objective="Overwrite state.",
                next_step="This must fail.",
                blocker="None",
                status="RUNNING",
                worker_id="coordinator-b",
                thread_id="thread-b",
                inbox_cursor=0,
                expected_version=1,
                actor="coordinator-b",
                command_id=command_id(),
                acknowledge_message_ids=[pending_message["id"]],
            )
        pending = self.service.inbox("retrieval", after=0, pending_only=True)
        self.assertEqual([item["id"] for item in pending], [pending_message["id"]])

    def test_full_chain_exports_to_a_validator_compatible_kb(self) -> None:
        hypothesis = self.create_hypothesis()
        experiment = self.create_experiment(str(hypothesis["id"]))
        artifact_id = str(experiment["id"])
        claimed = self.service.claim_experiment(
            slug="retrieval",
            artifact_id=artifact_id,
            ttl_seconds=300,
            actor="worker",
            command_id=command_id(),
        )
        self.service.append_observation(
            slug="retrieval",
            artifact_id=artifact_id,
            body="NDCG improved by twelve percent.",
            evidence_ref="s3://evidence/run.json",
            actor="worker",
            command_id=command_id(),
        )
        completed = self.service.complete_experiment(
            slug="retrieval",
            artifact_id=artifact_id,
            results="Treatment improved NDCG by twelve percent.",
            analysis="The threshold was exceeded under the fixed candidate set.",
            decision="Publish a finding and test online latency.",
            expected_version=int(claimed["artifact"]["version"]),
            actor="worker",
            command_id=command_id(),
        )
        self.assertEqual(completed["status"], "COMPLETED")
        self.service.publish_finding(
            slug="retrieval",
            experiment_id=artifact_id,
            title="Reranking improves offline NDCG",
            finding="The treatment exceeded the offline NDCG threshold.",
            evidence="A fixed-candidate comparison improved NDCG by twelve percent.",
            improvement="Relevance ordering improved on held-out queries.",
            remaining_debt="Online latency is not established.",
            next_move="Measure latency in a production-like environment.",
            impact="HIGH",
            actor="worker",
            command_id=command_id(),
        )

        kb_root = Path(self.temp_dir.name) / "kb-export"
        MarkdownExporter(self.service).write("retrieval", kb_root)
        env = os.environ.copy()
        env["LIMINA_TELEMETRY_INTERNAL"] = "1"
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), "--kb-root", str(kb_root)],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("KB validation passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
