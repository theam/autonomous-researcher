from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]


class CloudMigrationTests(unittest.TestCase):
    def test_initial_migration_matches_runtime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "migration.db"
            env = os.environ.copy()
            env["LIMINA_DATABASE_URL"] = f"sqlite:///{database_path}"
            upgraded = subprocess.run(
                ["uv", "run", "alembic", "upgrade", "head"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)

            engine = create_engine(f"sqlite:///{database_path}")
            try:
                tables = set(inspect(engine).get_table_names())
                self.assertIn("challenges", tables)
                self.assertIn("artifacts", tables)
                self.assertIn("work_leases", tables)
                self.assertIn("project_resources", tables)
                self.assertIn("alembic_version", tables)
                with engine.connect() as connection:
                    revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                self.assertEqual(revision, "console_notifications")
                self.assertTrue(
                    {
                        "project_members",
                        "live_tickets",
                        "project_sources",
                        "knowledge_relations",
                        "artifact_comments",
                        "artifact_tags",
                        "saved_knowledge_views",
                        "runtime_runs",
                        "attention_requests",
                        "attention_episodes",
                        "attention_dispositions",
                        "artifact_reviews",
                        "notification_channels",
                        "notification_rules",
                        "notification_outbox",
                        "notification_deliveries",
                    }
                    <= tables
                )
                challenge_columns = {
                    item["name"] for item in inspect(engine).get_columns("challenges")
                }
                coordinator_columns = {
                    item["name"] for item in inspect(engine).get_columns("coordinator_states")
                }
                self.assertIn("runtime_engine", challenge_columns)
                self.assertIn("continuation_id", coordinator_columns)
                self.assertNotIn("thread_id", coordinator_columns)
                columns = {
                    item["name"] for item in inspect(engine).get_columns("project_resources")
                }
                self.assertTrue(
                    {"resource_type", "value", "secret_ciphertext", "updated_at"} <= columns
                )
                self.assertTrue({"uri", "kind", "credential_env"}.isdisjoint(columns))

                attention_indexes = {
                    item["name"]: tuple(item["column_names"])
                    for item in inspect(engine).get_indexes("attention_episodes")
                }
                self.assertEqual(
                    attention_indexes["ix_attention_episode_queue"],
                    ("status", "severity_rank", "opened_at", "id"),
                )
                review_foreign_keys = inspect(engine).get_foreign_keys("artifact_reviews")
                self.assertTrue(
                    any(
                        tuple(item["constrained_columns"]) == ("artifact_uid", "artifact_version")
                        and item["referred_table"] == "artifact_revisions"
                        and tuple(item["referred_columns"]) == ("artifact_uid", "version")
                        for item in review_foreign_keys
                    )
                )
                outbox_indexes = {
                    item["name"]: tuple(item["column_names"])
                    for item in inspect(engine).get_indexes("notification_outbox")
                }
                self.assertEqual(
                    outbox_indexes["ix_notification_outbox_claim"],
                    ("status", "next_attempt_at", "created_at", "id"),
                )
            finally:
                engine.dispose()

            checked = subprocess.run(
                ["uv", "run", "alembic", "check"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertIn("No new upgrade operations detected", checked.stdout + checked.stderr)

    def test_resource_migration_preserves_references_as_variables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "resource-migration.db"
            database_url = f"sqlite:///{database_path}"
            env = {**os.environ, "LIMINA_DATABASE_URL": database_url}
            initial = subprocess.run(
                ["uv", "run", "alembic", "upgrade", "474c29565487"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)

            engine = create_engine(database_url)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            """
                            INSERT INTO challenges
                                (id, slug, name, objective, context, success_criteria,
                                 status, version, created_at, updated_at)
                            VALUES
                                ('project-1', 'migration', 'Migration', 'Preserve data', '',
                                 'Reference survives', 'ACTIVE', 1,
                                 '2026-01-01 00:00:00', '2026-01-01 00:00:00')
                            """
                        )
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO project_resources
                                (id, challenge_id, name, uri, kind, credential_env,
                                 status, created_by, created_at)
                            VALUES
                                ('resource-1', 'project-1', 'eval-set', 's3://eval',
                                 'DATASET', NULL, 'ACTIVE', 'owner', '2026-01-01 00:00:00')
                            """
                        )
                    )
            finally:
                engine.dispose()

            upgraded = subprocess.run(
                ["uv", "run", "alembic", "upgrade", "head"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)

            engine = create_engine(database_url)
            try:
                with engine.connect() as connection:
                    row = connection.execute(
                        text(
                            "SELECT name, resource_type, value FROM project_resources "
                            "WHERE id = 'resource-1'"
                        )
                    ).one()
                self.assertEqual(tuple(row), ("EVAL_SET", "VARIABLE", "s3://eval"))
            finally:
                engine.dispose()

    def test_runtime_engine_migration_preserves_codex_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "runtime-engine-migration.db"
            database_url = f"sqlite:///{database_path}"
            env = {**os.environ, "LIMINA_DATABASE_URL": database_url}
            initial = subprocess.run(
                ["uv", "run", "alembic", "upgrade", "9a62d4f771c1"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)

            engine = create_engine(database_url)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            """
                            INSERT INTO challenges
                                (id, slug, name, objective, context, success_criteria,
                                 status, version, created_at, updated_at)
                            VALUES
                                ('project-1', 'existing', 'Existing', 'Continue', '',
                                 'Continuity survives', 'ACTIVE', 1,
                                 '2026-01-01 00:00:00', '2026-01-01 00:00:00')
                            """
                        )
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO coordinator_states
                                (challenge_id, status, current_objective, next_step, blocker,
                                 worker_id, thread_id, inbox_cursor, version, heartbeat_at,
                                 wake_at, updated_at)
                            VALUES
                                ('project-1', 'PAUSED', 'Continue', 'Resume', 'None', NULL,
                                 'codex-thread', 0, 1, NULL, NULL, '2026-01-01 00:00:00')
                            """
                        )
                    )
            finally:
                engine.dispose()

            upgraded = subprocess.run(
                ["uv", "run", "alembic", "upgrade", "head"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)

            engine = create_engine(database_url)
            try:
                with engine.connect() as connection:
                    engine_name = connection.scalar(
                        text("SELECT runtime_engine FROM challenges WHERE id = 'project-1'")
                    )
                    continuation = connection.scalar(
                        text(
                            "SELECT continuation_id FROM coordinator_states "
                            "WHERE challenge_id = 'project-1'"
                        )
                    )
                self.assertEqual(engine_name, "codex")
                self.assertEqual(continuation, "codex-thread")
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
