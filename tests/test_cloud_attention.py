from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from pydantic import TypeAdapter
from sqlalchemy import func, select

from limina_cloud.api import create_app
from limina_cloud.attention_service import (
    AttentionService,
    record_checkpoint_request,
    record_notification_failure,
)
from limina_cloud.auth import Principal
from limina_cloud.console_schemas import AttentionItem, AttentionPage
from limina_cloud.database import Database
from limina_cloud.errors import (
    AuthenticationError,
    ConflictError,
    InvariantError,
    NotFoundError,
    TransportError,
)
from limina_cloud.exporter import MarkdownExporter
from limina_cloud.models import (
    Artifact,
    ArtifactReview,
    ArtifactRevision,
    AttentionDisposition,
    AttentionEpisode,
    AttentionRequest,
    Challenge,
    CommandReceipt,
    CoordinatorState,
    Event,
    InboxMessage,
    RuntimeRun,
    new_uuid,
)
from limina_cloud.runtime import (
    RuntimeAttentionRequest,
    RuntimeDecision,
    RuntimeTurn,
    _parse_runtime_decision,
)
from limina_cloud.service import ChallengeService
from limina_cloud.supervisor import ProjectSupervisor

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*"
)

from starlette.testclient import TestClient  # noqa: E402

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


class AttentionTokenAuthenticator:
    mode = "oidc"

    def __init__(self) -> None:
        self.principals = {
            "owner-token": Principal("owner", "Owner", auth_mode="oidc"),
            "editor-token": Principal("editor", "Editor", auth_mode="oidc"),
            "viewer-token": Principal("viewer", "Viewer", auth_mode="oidc"),
            "outsider-token": Principal("outsider", "Outsider", auth_mode="oidc"),
        }

    def authenticate(
        self,
        bearer_token: str | None,
        *,
        actor_hint: str | None = None,
    ) -> Principal:
        del actor_hint
        try:
            return self.principals[bearer_token or ""]
        except KeyError as exc:
            raise AuthenticationError() from exc


class IdleAgent:
    model = "test-model"

    async def run_turn(self, **_values):
        return RuntimeTurn(
            "continuation",
            "turn",
            RuntimeDecision("Complete.", "COMPLETE", "Done.", "Report.", "None"),
        )

    async def steer(self, _message: str) -> bool:
        return False

    async def interrupt(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class RequestingAgent(IdleAgent):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def run_turn(self, **values):
        self.prompts.append(values["prompt"])
        return RuntimeTurn(
            "continuation",
            "turn",
            RuntimeDecision(
                "A product decision is required.",
                "WAITING",
                "Choose the release boundary.",
                "Continue after the decision.",
                "Two credible options remain.",
                RuntimeAttentionRequest(
                    kind="QUESTION",
                    response_mode="TEXT",
                    priority="HIGH",
                    title="Choose the release boundary",
                    body="Which release boundary should the executor use?",
                ),
            ),
        )


class AttentionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "attention.db"
        self.database = Database(f"sqlite:///{database_path}")
        self.database.initialize()
        self.service = AttentionService(self.database, unattended_after=timedelta(hours=2))

    def tearDown(self) -> None:
        self.database.dispose()
        self.temp_dir.cleanup()

    @staticmethod
    def _project(
        session,
        slug: str,
        *,
        coordinator_status: str = "CREATED",
        runtime_engine: str = "codex",
        updated_at: datetime = NOW,
    ) -> tuple[Challenge, CoordinatorState]:
        challenge = Challenge(
            id=new_uuid(),
            slug=slug,
            name=slug.replace("-", " ").title(),
            objective=f"Complete {slug} research.",
            context="",
            success_criteria="Produce a decision.",
            runtime_engine=runtime_engine,
            status="ACTIVE",
            version=1,
            created_at=updated_at,
            updated_at=updated_at,
        )
        coordinator = CoordinatorState(
            challenge_id=challenge.id,
            status=coordinator_status,
            current_objective=f"Investigate {slug}.",
            next_step="Run the next decisive check.",
            blocker="Waiting for evidence.",
            version=1,
            updated_at=updated_at,
        )
        session.add_all([challenge, coordinator])
        session.flush()
        return challenge, coordinator

    @staticmethod
    def _finding(session, challenge: Challenge, artifact_id: str = "F001") -> Artifact:
        artifact = Artifact(
            uid=new_uuid(),
            challenge_id=challenge.id,
            artifact_id=artifact_id,
            kind="F",
            title="Material finding",
            status="CONFIRMED",
            payload={"summary": "Evidence changed the decision.", "impact": "HIGH"},
            version=1,
            created_by="agent",
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(artifact)
        session.flush()
        session.add(
            ArtifactRevision(
                artifact_uid=artifact.uid,
                version=1,
                status=artifact.status,
                title=artifact.title,
                payload=artifact.payload,
                actor="agent",
                command_id=f"revision-{challenge.slug}",
                created_at=NOW,
            )
        )
        session.flush()
        return artifact

    @staticmethod
    def _episode(
        session,
        challenge: Challenge,
        *,
        item_type: str,
        severity: str,
        rank: int,
        opened_at: datetime,
        status: str = "OPEN",
        allowed_actions: list[str] | None = None,
        attention_request_id: str | None = None,
        source_ref: dict | None = None,
        source_key: str | None = None,
        resolution_semantics: str = "test",
    ) -> AttentionEpisode:
        episode = AttentionEpisode(
            id=new_uuid(),
            challenge_id=challenge.id,
            attention_request_id=attention_request_id,
            item_type=item_type,
            source_key=source_key or f"{item_type}:{new_uuid()}",
            status=status,
            severity=severity,
            severity_rank=rank,
            title=f"{item_type} title",
            body=f"{item_type} summary",
            source_ref=source_ref or {},
            allowed_actions=allowed_actions or [],
            resolution_semantics=resolution_semantics,
            version=1,
            opened_at=opened_at,
            updated_at=opened_at,
            closed_at=opened_at if status == "CLOSED" else None,
        )
        session.add(episode)
        session.flush()
        return episode

    @classmethod
    def _agent_request(
        cls,
        session,
        challenge: Challenge,
        *,
        sequence: int,
        response_mode: str,
        choices: list[dict[str, str]] | None = None,
    ) -> tuple[AttentionRequest, AttentionEpisode]:
        actions = {
            "TEXT": ["ANSWER"],
            "CHOICE": ["SELECT"],
            "CONFIRMATION": ["CONFIRM", "REJECT"],
            "ARTIFACT_REVIEW": ["REVIEW"],
        }[response_mode]
        request = AttentionRequest(
            id=new_uuid(),
            challenge_id=challenge.id,
            kind="REVIEW" if response_mode == "ARTIFACT_REVIEW" else "QUESTION",
            title=f"Request {sequence}",
            body=f"Resolve request {sequence}.",
            response_mode=response_mode,
            priority="HIGH",
            status="OPEN",
            choices=choices or [],
            created_checkpoint_sequence=sequence,
            content_fingerprint=f"fingerprint-{sequence}",
            version=1,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(request)
        session.flush()
        episode = cls._episode(
            session,
            challenge,
            item_type="agent_request",
            severity="HIGH",
            rank=1,
            opened_at=NOW + timedelta(minutes=sequence),
            allowed_actions=actions,
            attention_request_id=request.id,
            source_ref={"request_id": request.id},
        )
        episode.source_key = f"request:{request.id}"
        episode.title = request.title
        episode.body = request.body
        episode.source_ref = {
            "request_id": request.id,
            "artifact_id": None,
            "artifact_version": None,
            "run_id": None,
        }
        episode.resolution_semantics = "resolve_request"
        return request, episode

    def test_checkpoint_request_pins_revision_and_deduplicates(self) -> None:
        with self.database.session() as session, session.begin():
            challenge, _ = self._project(session, "checkpoint")
            artifact = self._finding(session, challenge)
            artifact.version = 2
            artifact.payload = {"summary": "Current revision"}
            artifact.updated_at = NOW + timedelta(minutes=1)
            session.add(
                ArtifactRevision(
                    artifact_uid=artifact.uid,
                    version=2,
                    status=artifact.status,
                    title=artifact.title,
                    payload=artifact.payload,
                    actor="agent",
                    command_id="revision-checkpoint-v2",
                    created_at=NOW + timedelta(minutes=1),
                )
            )
            payload = {
                "kind": "review",
                "response_mode": "artifact_review",
                "priority": "critical",
                "title": "Review current finding",
                "body": "Does the current evidence support the decision?",
                "artifact_id": "F001",
                "artifact_version": 2,
            }
            first = record_checkpoint_request(
                session,
                challenge=challenge,
                checkpoint_sequence=7,
                request=payload,
                actor="Limina",
            )
            replay = record_checkpoint_request(
                session,
                challenge=challenge,
                checkpoint_sequence=7,
                request=payload,
                actor="Limina",
            )
            later_checkpoint = record_checkpoint_request(
                session,
                challenge=challenge,
                checkpoint_sequence=8,
                request=payload,
                actor="Limina",
            )
            self.assertEqual(first, replay)
            self.assertNotEqual(first, later_checkpoint)

        with self.database.session() as session:
            request = session.get(AttentionRequest, first["request_id"])
            episode = session.get(AttentionEpisode, first["episode_id"])
            self.assertEqual(request.artifact_uid, artifact.uid)
            self.assertEqual(request.artifact_version, 2)
            self.assertEqual(request.priority, "CRITICAL")
            self.assertEqual(episode.allowed_actions, ["REVIEW"])
            self.assertEqual(session.scalar(select(func.count()).select_from(AttentionRequest)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(Event)), 2)

        with self.assertRaises(ConflictError), self.database.session() as session, session.begin():
            challenge = session.get(Challenge, challenge.id)
            record_checkpoint_request(
                session,
                challenge=challenge,
                checkpoint_sequence=7,
                request={**payload, "body": "A different question."},
                actor="Limina",
            )

    def test_checkpoint_request_redacts_secret_shaped_operator_text(self) -> None:
        with self.database.session() as session, session.begin():
            challenge, _ = self._project(session, "redacted-request")
            result = record_checkpoint_request(
                session,
                challenge=challenge,
                checkpoint_sequence=1,
                request={
                    "kind": "question",
                    "response_mode": "text",
                    "priority": "high",
                    "title": "Token ghp_1234567890abcdef needs review",
                    "body": "Use Bearer abcdefghijklmnop and api_key=super-secret-value?",
                },
                actor="Limina",
            )

        item = self.service.get_item(
            result["episode_id"],
            allowed_challenge_ids={challenge.id},
        )
        self.assertNotIn("ghp_1234567890abcdef", item["title"])
        self.assertNotIn("abcdefghijklmnop", item["summary"])
        self.assertNotIn("super-secret-value", item["summary"])
        self.assertIn("[redacted]", item["summary"])

    def test_coordinator_checkpoint_persists_request_and_state_atomically(self) -> None:
        challenge_service = ChallengeService(self.database)
        with self.database.session() as session, session.begin():
            challenge, _ = self._project(session, "runtime-checkpoint")
            run = RuntimeRun(
                id=new_uuid(),
                challenge_id=challenge.id,
                runtime_engine="codex",
                status="RUNNING",
                summary="Running a managed checkpoint.",
                started_at=NOW,
            )
            session.add(run)

        request_payload = {
            "kind": "QUESTION",
            "response_mode": "TEXT",
            "priority": "HIGH",
            "title": "Choose the release boundary",
            "body": "Which deployment boundary should govern this release?",
            "choices": [],
            "artifact_id": None,
            "artifact_version": None,
        }
        result = challenge_service.checkpoint_coordinator(
            slug=challenge.slug,
            current_objective="Resolve the release boundary.",
            next_step="Continue after the operator chooses.",
            blocker="A product decision is required.",
            status="WAITING",
            worker_id="limina:runtime",
            continuation_id="turn-1",
            inbox_cursor=0,
            expected_version=1,
            actor="limina:runtime",
            command_id="checkpoint-with-attention",
            attention_request=request_payload,
            run_id=run.id,
        )
        replay = challenge_service.checkpoint_coordinator(
            slug=challenge.slug,
            current_objective="Resolve the release boundary.",
            next_step="Continue after the operator chooses.",
            blocker="A product decision is required.",
            status="WAITING",
            worker_id="limina:runtime",
            continuation_id="turn-1",
            inbox_cursor=0,
            expected_version=1,
            actor="limina:runtime",
            command_id="checkpoint-with-attention",
            attention_request=request_payload,
            run_id=run.id,
        )
        self.assertEqual(result, replay)
        self.assertEqual(result["status"], "WAITING")
        self.assertEqual(result["version"], 2)

        with self.database.session() as session:
            request = session.scalar(
                select(AttentionRequest).where(AttentionRequest.challenge_id == challenge.id)
            )
            checkpoint_event = session.scalar(
                select(Event).where(
                    Event.challenge_id == challenge.id,
                    Event.event_type == "coordinator.checkpointed",
                )
            )
            self.assertEqual(request.run_id, run.id)
            self.assertEqual(
                request.created_checkpoint_sequence,
                checkpoint_event.sequence,
            )
            self.assertEqual(checkpoint_event.payload["attention_request_id"], request.id)
            self.assertEqual(session.scalar(select(func.count()).select_from(AttentionEpisode)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(CommandReceipt)), 1)

        with self.assertRaises(InvariantError):
            challenge_service.checkpoint_coordinator(
                slug=challenge.slug,
                current_objective="Invalid checkpoint.",
                next_step="This update must roll back.",
                blocker="None",
                status="WAITING",
                worker_id="limina:runtime",
                continuation_id="turn-1",
                inbox_cursor=0,
                expected_version=2,
                actor="limina:runtime",
                command_id="checkpoint-invalid-attention",
                attention_request={**request_payload, "choices": ["invalid"]},
                run_id=run.id,
            )
        self.assertEqual(
            challenge_service.get_challenge(challenge.slug)["coordinator"]["version"],
            2,
        )

    def test_runtime_rejects_attention_without_waiting(self) -> None:
        with self.assertRaises(TransportError):
            _parse_runtime_decision(
                {
                    "summary": "Asking while continuing.",
                    "status": "RUNNING",
                    "current_objective": "Continue independently.",
                    "next_step": "Keep working.",
                    "blocker": "None",
                    "attention_request": {
                        "kind": "QUESTION",
                        "response_mode": "TEXT",
                        "priority": "MEDIUM",
                        "title": "Optional preference",
                        "body": "Which optional style is preferred?",
                        "choices": [],
                        "artifact_id": None,
                        "artifact_version": None,
                    },
                },
                provider="test runtime",
            )

    def test_supervisor_materializes_runtime_decision_with_owning_run(self) -> None:
        challenge_service = ChallengeService(self.database)
        with self.database.session() as session, session.begin():
            challenge, _ = self._project(
                session,
                "supervised-request",
                coordinator_status="RUNNING",
            )
        agent = RequestingAgent()
        supervisor = ProjectSupervisor(
            challenge_service,
            MarkdownExporter(challenge_service),
            workspace_root=Path(self.temp_dir.name) / "workspaces",
            internal_url="http://127.0.0.1:7433",
            agent_factory=lambda _slug, _engine: agent,
            poll_interval=0.01,
        )
        try:
            asyncio.run(supervisor._run_turn(challenge.slug, agent))
        finally:
            asyncio.run(supervisor.shutdown())

        with self.database.session() as session:
            request = session.scalar(
                select(AttentionRequest).where(AttentionRequest.challenge_id == challenge.id)
            )
            run = session.get(RuntimeRun, request.run_id)
            episode = session.scalar(
                select(AttentionEpisode).where(AttentionEpisode.attention_request_id == request.id)
            )
            coordinator = session.get(CoordinatorState, challenge.id)
            self.assertEqual(run.status, "COMPLETED")
            self.assertEqual(coordinator.status, "WAITING")
            self.assertEqual(episode.status, "OPEN")
            self.assertEqual(episode.source_ref["run_id"], run.id)
        self.assertIn("Set `attention_request` to null by default", agent.prompts[0])

    def test_reconcile_materializes_sources_and_closes_only_auto_clear_items(self) -> None:
        old = NOW - timedelta(hours=3)
        with self.database.session() as session, session.begin():
            request_project, request_coordinator = self._project(
                session, "request", coordinator_status="WAITING"
            )
            request_ids = record_checkpoint_request(
                session,
                challenge=request_project,
                checkpoint_sequence=1,
                request={
                    "kind": "QUESTION",
                    "response_mode": "TEXT",
                    "priority": "HIGH",
                    "title": "Need a decision",
                    "body": "Which direction should the executor take?",
                },
                actor="Limina",
            )

            failed_project, failed_coordinator = self._project(
                session, "failed", coordinator_status="WAITING"
            )
            failed_run = RuntimeRun(
                id=new_uuid(),
                challenge_id=failed_project.id,
                runtime_engine="codex",
                status="FAILED",
                summary="Provider stopped.",
                error_code="provider_error",
                error_message="The provider stopped before a checkpoint.",
                started_at=NOW - timedelta(minutes=20),
                completed_at=NOW - timedelta(minutes=19),
            )
            session.add(failed_run)

            finding_project, _ = self._project(session, "finding")
            finding = self._finding(session, finding_project)
            complete_project, complete = self._project(
                session, "complete", coordinator_status="COMPLETE"
            )
            stalled_project, stalled = self._project(
                session, "stalled", coordinator_status="WAITING"
            )
            preflight_project, _ = self._project(
                session,
                "preflight",
                coordinator_status="CREATED",
                runtime_engine="claude-code",
            )
            unattended_project, unattended = self._project(
                session, "unattended", coordinator_status="RUNNING", updated_at=old
            )
            running = RuntimeRun(
                id=new_uuid(),
                challenge_id=unattended_project.id,
                runtime_engine="codex",
                status="RUNNING",
                summary="Still running.",
                started_at=old,
            )
            session.add(running)
            notification_project, _ = self._project(session, "notification")
            notification_episode = record_notification_failure(
                session,
                challenge=notification_project,
                source_key="channel:alerts:delivery:17",
                title="Notification delivery failed",
                body="The configured alerts channel rejected delivery.",
                source_ref={"event_sequence": 17},
            )
            project_ids = {
                request_project.id,
                failed_project.id,
                finding_project.id,
                complete_project.id,
                stalled_project.id,
                preflight_project.id,
                unattended_project.id,
                notification_project.id,
            }

        self.service.reconcile(
            allowed_challenge_ids=project_ids,
            configured_engines={"codex"},
            now=NOW,
        )
        with self.database.session() as session:
            open_types = set(
                session.scalars(
                    select(AttentionEpisode.item_type).where(
                        AttentionEpisode.challenge_id.in_(project_ids),
                        AttentionEpisode.status == "OPEN",
                    )
                ).all()
            )
            self.assertEqual(
                open_types,
                {
                    "agent_request",
                    "run_failure",
                    "finding_review",
                    "project_complete",
                    "stalled_project",
                    "preflight_issue",
                    "unattended_run",
                    "notification_failure",
                },
            )
            failed_stalls = session.scalars(
                select(AttentionEpisode).where(
                    AttentionEpisode.challenge_id == failed_project.id,
                    AttentionEpisode.item_type == "stalled_project",
                )
            ).all()
            self.assertEqual(failed_stalls, [])
            request_episode = session.get(AttentionEpisode, request_ids["episode_id"])
            self.assertEqual(request_episode.source_ref["request_id"], request_ids["request_id"])
            unattended_episode = session.scalar(
                select(AttentionEpisode).where(
                    AttentionEpisode.challenge_id == unattended_project.id,
                    AttentionEpisode.item_type == "unattended_run",
                )
            )
            self.assertEqual(unattended_episode.source_ref["run_id"], running.id)

        with self.database.session() as session, session.begin():
            request = session.get(AttentionRequest, request_ids["request_id"])
            request.status = "RESOLVED"
            session.add(
                RuntimeRun(
                    id=new_uuid(),
                    challenge_id=failed_project.id,
                    runtime_engine="codex",
                    status="COMPLETED",
                    summary="A later run recovered.",
                    started_at=NOW + timedelta(seconds=1),
                    completed_at=NOW + timedelta(seconds=30),
                )
            )
            session.add(
                ArtifactReview(
                    challenge_id=finding_project.id,
                    artifact_uid=finding.uid,
                    artifact_version=1,
                    outcome="ACCEPT",
                    rationale="",
                    reviewer_subject="user:reviewer",
                    reviewer_name="Reviewer",
                    interaction_surface="KNOWLEDGE",
                    command_id="review-finding",
                    created_at=NOW,
                )
            )
            for coordinator in (
                request_coordinator,
                failed_coordinator,
                complete,
                stalled,
                unattended,
            ):
                persisted = session.get(CoordinatorState, coordinator.challenge_id)
                persisted.status = "RUNNING"
                persisted.updated_at = NOW
                persisted.heartbeat_at = NOW

        self.service.reconcile(
            allowed_challenge_ids=project_ids,
            configured_engines={"codex", "claude-code"},
            now=NOW + timedelta(minutes=1),
        )
        with self.database.session() as session:
            episodes = session.scalars(
                select(AttentionEpisode).where(AttentionEpisode.challenge_id.in_(project_ids))
            ).all()
            status_by_type = {item.item_type: item.status for item in episodes}
            self.assertEqual(status_by_type["run_failure"], "CLOSED")
            self.assertEqual(status_by_type["notification_failure"], "OPEN")
            self.assertEqual(session.get(AttentionEpisode, notification_episode.id).status, "OPEN")
            for item_type in {
                "agent_request",
                "finding_review",
                "project_complete",
                "run_failure",
                "stalled_project",
                "preflight_issue",
                "unattended_run",
            }:
                self.assertEqual(status_by_type[item_type], "CLOSED", item_type)

    def test_open_requests_expire_when_a_project_archives_or_reaches_terminal_state(self) -> None:
        with self.database.session() as session, session.begin():
            archived, _ = self._project(session, "archive-request")
            archived_ids = record_checkpoint_request(
                session,
                challenge=archived,
                checkpoint_sequence=11,
                request={
                    "kind": "QUESTION",
                    "response_mode": "TEXT",
                    "priority": "HIGH",
                    "title": "Stale archive question",
                    "body": "This must not survive project archival.",
                },
                actor="executor",
            )
            terminal, _ = self._project(session, "terminal-request", coordinator_status="RUNNING")
            terminal_ids = record_checkpoint_request(
                session,
                challenge=terminal,
                checkpoint_sequence=12,
                request={
                    "kind": "QUESTION",
                    "response_mode": "TEXT",
                    "priority": "HIGH",
                    "title": "Stale terminal question",
                    "body": "This must not survive terminal completion.",
                },
                actor="executor",
            )

        challenge_service = ChallengeService(self.database)
        challenge_service.change_project_state(
            slug="archive-request",
            action="archive",
            actor="owner",
            command_id="archive-request-project",
        )
        challenge_service.checkpoint_coordinator(
            slug="terminal-request",
            current_objective="Finish the run.",
            next_step="Report the result.",
            blocker="None",
            status="COMPLETE",
            worker_id=None,
            continuation_id=None,
            inbox_cursor=0,
            expected_version=1,
            actor="executor",
            command_id="complete-request-project",
        )

        with self.database.session() as session:
            archived_request = session.get(AttentionRequest, archived_ids["request_id"])
            terminal_request = session.get(AttentionRequest, terminal_ids["request_id"])
            self.assertEqual(archived_request.status, "EXPIRED")
            self.assertEqual(archived_request.resolution["reason"], "project_archived")
            self.assertEqual(terminal_request.status, "EXPIRED")
            self.assertEqual(terminal_request.resolution["reason"], "coordinator_complete")
            self.assertEqual(
                session.get(AttentionEpisode, archived_ids["episode_id"]).status,
                "CLOSED",
            )
            self.assertEqual(
                session.get(AttentionEpisode, terminal_ids["episode_id"]).status,
                "CLOSED",
            )

    def test_listing_is_authorized_user_scoped_and_keyset_paginated(self) -> None:
        with self.database.session() as session, session.begin():
            alpha, _ = self._project(session, "alpha")
            beta, _ = self._project(session, "beta")
            forbidden, _ = self._project(session, "forbidden")
            acknowledged = self._episode(
                session,
                alpha,
                item_type="run_failure",
                severity="CRITICAL",
                rank=0,
                opened_at=NOW,
                allowed_actions=["ACKNOWLEDGE"],
            )
            snoozed = self._episode(
                session,
                alpha,
                item_type="stalled_project",
                severity="HIGH",
                rank=1,
                opened_at=NOW + timedelta(minutes=1),
                allowed_actions=["SNOOZE"],
            )
            expired = self._episode(
                session,
                alpha,
                item_type="unattended_run",
                severity="MEDIUM",
                rank=2,
                opened_at=NOW + timedelta(minutes=2),
                allowed_actions=["SNOOZE"],
            )
            critical = self._episode(
                session,
                beta,
                item_type="preflight_issue",
                severity="CRITICAL",
                rank=0,
                opened_at=NOW + timedelta(minutes=3),
            )
            low = self._episode(
                session,
                alpha,
                item_type="project_complete",
                severity="LOW",
                rank=3,
                opened_at=NOW + timedelta(minutes=4),
                allowed_actions=["ACKNOWLEDGE"],
            )
            closed = self._episode(
                session,
                beta,
                item_type="finding_review",
                severity="HIGH",
                rank=1,
                opened_at=NOW - timedelta(minutes=1),
                status="CLOSED",
            )
            self._episode(
                session,
                forbidden,
                item_type="run_failure",
                severity="CRITICAL",
                rank=0,
                opened_at=NOW - timedelta(minutes=5),
            )
            session.add_all(
                [
                    AttentionDisposition(
                        episode_id=acknowledged.id,
                        scope_key="user:user-1",
                        action="ACKNOWLEDGED",
                        actor_subject="user-1",
                        actor_name="User One",
                        details={},
                        interaction_surface="TODAY",
                        command_id="ack-list",
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                    AttentionDisposition(
                        episode_id=snoozed.id,
                        scope_key="user:user-1",
                        action="SNOOZE",
                        actor_subject="user-1",
                        actor_name="User One",
                        details={},
                        snoozed_until=NOW + timedelta(hours=1),
                        interaction_surface="TODAY",
                        command_id="snooze-list",
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                    AttentionDisposition(
                        episode_id=expired.id,
                        scope_key="user:user-1",
                        action="SNOOZE",
                        actor_subject="user-1",
                        actor_name="User One",
                        details={},
                        snoozed_until=NOW - timedelta(seconds=1),
                        interaction_surface="TODAY",
                        command_id="expired-list",
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                ]
            )
            allowed = {alpha.id, beta.id}

        ids: list[str] = []
        cursor = None
        while True:
            page = self.service.list_items(
                allowed_challenge_ids=allowed,
                subject="user-1",
                cursor=cursor,
                limit=1,
                now=NOW,
            )
            AttentionPage.model_validate(page)
            ids.extend(item["id"] for item in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(ids, [critical.id, expired.id, low.id])
        self.assertEqual(len(ids), len(set(ids)))

        detail = self.service.get_item(closed.id, allowed_challenge_ids=allowed)
        TypeAdapter(AttentionItem).validate_python(detail)
        self.assertEqual(detail["status"], "CLOSED")
        history = self.service.list_items(
            allowed_challenge_ids=allowed,
            subject="user-1",
            include_closed=True,
            now=NOW,
        )
        self.assertEqual(history["items"][-1]["id"], closed.id)
        with self.assertRaises(NotFoundError):
            self.service.get_item(acknowledged.id, allowed_challenge_ids={forbidden.id})

    def test_agent_request_resolutions_are_validated_atomic_and_replayable(self) -> None:
        with self.database.session() as session, session.begin():
            challenge, _ = self._project(session, "resolutions")
            requests = [
                self._agent_request(session, challenge, sequence=1, response_mode="TEXT"),
                self._agent_request(
                    session,
                    challenge,
                    sequence=2,
                    response_mode="CHOICE",
                    choices=[
                        {"id": "alpha", "label": "Alpha"},
                        {"id": "beta", "label": "Beta"},
                    ],
                ),
                self._agent_request(session, challenge, sequence=3, response_mode="CONFIRMATION"),
                self._agent_request(
                    session, challenge, sequence=4, response_mode="ARTIFACT_REVIEW"
                ),
                self._agent_request(session, challenge, sequence=6, response_mode="CONFIRMATION"),
            ]
            invalid_request, invalid_episode = self._agent_request(
                session,
                challenge,
                sequence=5,
                response_mode="CHOICE",
                choices=[{"id": "yes", "label": "Yes"}],
            )
            allowed = {challenge.id}

        resolutions = [
            {"action": "ANSWER", "response": "Use the stronger baseline."},
            {"action": "SELECT", "choice": "beta"},
            {"action": "CONFIRM", "response": "APPROVE"},
            {"action": "REVIEW", "response": "Collect one more ablation."},
            {"action": "REJECT", "response": "The rollback guard is missing."},
        ]
        results = []
        for index, ((_request, episode), values) in enumerate(
            zip(requests, resolutions, strict=True), start=1
        ):
            result = self.service.resolve(
                episode.id,
                allowed_challenge_ids=allowed,
                expected_version=1,
                actor_subject="user-1",
                actor_name="User One",
                command_id=f"resolve-{index}",
                interaction_surface="TODAY",
                now=NOW + timedelta(hours=1),
                **values,
            )
            results.append(result)
            self.assertEqual(result["item"]["status"], "CLOSED")
            self.assertEqual(result["delivery"], "QUEUED")
            self.assertTrue(result["guidance_id"])
            self.assertTrue(result["guidance_body"])

        replay = self.service.resolve(
            requests[0][1].id,
            allowed_challenge_ids=allowed,
            action="ANSWER",
            response="Use the stronger baseline.",
            expected_version=1,
            actor_subject="user-1",
            actor_name="User One",
            command_id="resolve-1",
            now=NOW + timedelta(hours=2),
        )
        self.assertEqual(replay, results[0])

        with self.assertRaises(ConflictError):
            self.service.resolve(
                requests[0][1].id,
                allowed_challenge_ids=allowed,
                action="ANSWER",
                response="Try again.",
                expected_version=1,
                actor_subject="user-1",
                actor_name="User One",
                command_id="resolve-stale",
                now=NOW + timedelta(hours=2),
            )
        with self.assertRaises(InvariantError):
            self.service.resolve(
                invalid_episode.id,
                allowed_challenge_ids=allowed,
                action="SELECT",
                choice="no",
                expected_version=1,
                actor_subject="user-1",
                actor_name="User One",
                command_id="resolve-invalid-choice",
                now=NOW + timedelta(hours=1),
            )

        with self.database.session() as session:
            self.assertEqual(session.get(AttentionRequest, invalid_request.id).status, "OPEN")
            self.assertIsNone(session.get(CommandReceipt, "resolve-invalid-choice"))
            self.assertEqual(session.scalar(select(func.count()).select_from(InboxMessage)), 5)
            self.assertEqual(session.scalar(select(func.count()).select_from(Event)), 5)
            self.assertEqual(session.scalar(select(func.count()).select_from(CommandReceipt)), 5)
            for request, episode in requests:
                self.assertEqual(session.get(AttentionRequest, request.id).status, "RESOLVED")
                self.assertEqual(session.get(AttentionEpisode, episode.id).status, "CLOSED")

    def test_run_failure_acknowledgement_is_project_wide_while_snooze_is_personal(self) -> None:
        with self.database.session() as session, session.begin():
            challenge, _ = self._project(session, "dispositions")
            failure = self._episode(
                session,
                challenge,
                item_type="run_failure",
                severity="HIGH",
                rank=1,
                opened_at=NOW,
                allowed_actions=["ACKNOWLEDGE"],
                resolution_semantics="project_wide_acknowledge",
            )
            stalled = self._episode(
                session,
                challenge,
                item_type="stalled_project",
                severity="MEDIUM",
                rank=2,
                opened_at=NOW + timedelta(minutes=1),
                allowed_actions=["SNOOZE"],
            )
            too_long = self._episode(
                session,
                challenge,
                item_type="unattended_run",
                severity="LOW",
                rank=3,
                opened_at=NOW + timedelta(minutes=2),
                allowed_actions=["SNOOZE"],
            )
            allowed = {challenge.id}

        acknowledged = self.service.resolve(
            failure.id,
            allowed_challenge_ids=allowed,
            action="ACKNOWLEDGE",
            expected_version=1,
            actor_subject="user-1",
            actor_name="User One",
            command_id="ack-failure",
            now=NOW,
        )
        snoozed = self.service.resolve(
            stalled.id,
            allowed_challenge_ids=allowed,
            action="SNOOZE",
            snooze_until=NOW + timedelta(hours=1),
            expected_version=1,
            actor_subject="user-1",
            actor_name="User One",
            command_id="snooze-stalled",
            now=NOW,
        )
        self.assertEqual(acknowledged["item"]["status"], "CLOSED")
        self.assertEqual(snoozed["item"]["status"], "OPEN")
        user_one = self.service.list_items(allowed_challenge_ids=allowed, subject="user-1", now=NOW)
        self.assertEqual([item["id"] for item in user_one["items"]], [too_long.id])
        user_two = self.service.list_items(allowed_challenge_ids=allowed, subject="user-2", now=NOW)
        self.assertEqual(
            {item["id"] for item in user_two["items"]},
            {stalled.id, too_long.id},
        )
        after_snooze = self.service.list_items(
            allowed_challenge_ids=allowed,
            subject="user-1",
            now=NOW + timedelta(hours=2),
        )
        self.assertEqual(
            {item["id"] for item in after_snooze["items"]},
            {stalled.id, too_long.id},
        )

        with self.assertRaises(InvariantError):
            self.service.resolve(
                too_long.id,
                allowed_challenge_ids=allowed,
                action="SNOOZE",
                snooze_until=NOW + timedelta(hours=25),
                expected_version=1,
                actor_subject="user-1",
                actor_name="User One",
                command_id="snooze-too-long",
                now=NOW,
            )
        with self.database.session() as session:
            self.assertEqual(session.get(AttentionEpisode, failure.id).status, "CLOSED")
            self.assertIsNone(session.get(CommandReceipt, "snooze-too-long"))


class AttentionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.app = create_app(
            database_url=f"sqlite:///{root / 'attention-api.db'}",
            authenticator=AttentionTokenAuthenticator(),
            workspace_root=root / "workspaces",
            secret_key_path=root / "secret.key",
            agent_factory=lambda _slug, _engine: IdleAgent(),
            poll_interval=0.01,
            attention_reconcile_interval=0.05,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.wake = AsyncMock()
        self.app.state.runtime.supervisor.ensure_running = self.wake

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.app.state.runtime.database.dispose()
        self.temp_dir.cleanup()

    def test_background_worker_materializes_failed_run_without_a_queue_read(self) -> None:
        self._create_project("owner-token", "background-failure")
        database = self.app.state.runtime.database
        with database.session() as session, session.begin():
            project = session.scalar(
                select(Challenge).where(Challenge.slug == "background-failure")
            )
            failed_run = RuntimeRun(
                id=new_uuid(),
                challenge_id=project.id,
                runtime_engine="codex",
                status="FAILED",
                summary="The provider exited before a checkpoint.",
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=1),
            )
            session.add(failed_run)
            project_id = project.id
            failed_run_id = failed_run.id

        deadline = time.monotonic() + 2
        episode = None
        while time.monotonic() < deadline and episode is None:
            with database.session() as session:
                episode = session.scalar(
                    select(AttentionEpisode).where(
                        AttentionEpisode.challenge_id == project_id,
                        AttentionEpisode.item_type == "run_failure",
                        AttentionEpisode.source_key == f"run:{failed_run_id}",
                    )
                )
            if episode is None:
                time.sleep(0.02)
        self.assertIsNotNone(episode)
        self.assertEqual(episode.status, "OPEN")

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @classmethod
    def _command(cls, token: str, command_id: str) -> dict[str, str]:
        return {**cls._auth(token), "Idempotency-Key": command_id}

    def _create_project(self, token: str, slug: str) -> None:
        response = self.client.post(
            "/v2/projects",
            headers=self._command(token, f"create-{slug}"),
            json={
                "slug": slug,
                "name": slug.title(),
                "objective": f"Complete {slug}.",
                "success_criteria": "Produce a durable decision.",
                "runtime": "codex",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

    def test_attention_routes_filter_membership_resolve_and_preserve_deep_links(self) -> None:
        self._create_project("owner-token", "owned")
        self._create_project("outsider-token", "outside")
        member = self.client.put(
            "/v2/projects/owned/members",
            headers=self._auth("owner-token"),
            json={
                "subject": "viewer",
                "display_name": "Viewer",
                "role": "VIEWER",
            },
        )
        self.assertEqual(member.status_code, 200, member.text)

        database = self.app.state.runtime.database
        with database.session() as session, session.begin():
            owned = session.scalar(select(Challenge).where(Challenge.slug == "owned"))
            outside = session.scalar(select(Challenge).where(Challenge.slug == "outside"))
            owned_run = RuntimeRun(
                id=new_uuid(),
                challenge_id=owned.id,
                runtime_engine="codex",
                status="FAILED",
                summary="Owned runtime failed.",
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=1),
            )
            outside_run = RuntimeRun(
                id=new_uuid(),
                challenge_id=outside.id,
                runtime_engine="codex",
                status="FAILED",
                summary="Outside runtime failed.",
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=1),
            )
            session.add_all([owned_run, outside_run])
            session.flush()
            failure = AttentionServiceTests._episode(
                session,
                owned,
                item_type="run_failure",
                severity="CRITICAL",
                rank=0,
                opened_at=NOW,
                allowed_actions=["ACKNOWLEDGE"],
                source_ref={"run_id": owned_run.id},
                source_key=f"run:{owned_run.id}",
                resolution_semantics="project_wide_acknowledge",
            )
            _outside_failure = AttentionServiceTests._episode(
                session,
                outside,
                item_type="run_failure",
                severity="HIGH",
                rank=1,
                opened_at=NOW,
                allowed_actions=["ACKNOWLEDGE"],
                source_ref={"run_id": outside_run.id},
                source_key=f"run:{outside_run.id}",
                resolution_semantics="project_wide_acknowledge",
            )
            request, request_episode = AttentionServiceTests._agent_request(
                session,
                owned,
                sequence=1,
                response_mode="TEXT",
            )

        owner_queue = self.client.get("/v2/attention", headers=self._auth("owner-token"))
        self.assertEqual(owner_queue.status_code, 200, owner_queue.text)
        self.assertEqual(
            {item["id"] for item in owner_queue.json()["items"]},
            {failure.id, request_episode.id},
        )
        viewer_detail = self.client.get(
            f"/v2/attention/{request_episode.id}",
            headers=self._auth("viewer-token"),
        )
        self.assertEqual(viewer_detail.status_code, 200, viewer_detail.text)

        unknown = self.client.get(
            f"/v2/attention/{new_uuid()}", headers=self._auth("outsider-token")
        )
        inaccessible = self.client.get(
            f"/v2/attention/{request_episode.id}",
            headers=self._auth("outsider-token"),
        )
        self.assertEqual(unknown.status_code, 404, unknown.text)
        self.assertEqual(inaccessible.status_code, 404, inaccessible.text)
        self.assertEqual(unknown.json(), inaccessible.json())

        viewer_denied = self.client.post(
            f"/v2/attention/{request_episode.id}/resolve",
            headers=self._command("viewer-token", "viewer-cannot-resolve"),
            json={
                "action": "ANSWER",
                "expected_version": 1,
                "response": "A viewer must not resolve this.",
            },
        )
        self.assertEqual(viewer_denied.status_code, 403, viewer_denied.text)
        outsider_hidden = self.client.post(
            f"/v2/attention/{request_episode.id}/resolve",
            headers=self._command("outsider-token", "outsider-cannot-resolve"),
            json={
                "action": "ANSWER",
                "expected_version": 1,
                "response": "An outsider must not see this.",
            },
        )
        self.assertEqual(outsider_hidden.status_code, 404, outsider_hidden.text)

        resolution_body = {
            "action": "ANSWER",
            "expected_version": 1,
            "response": "Use private ingress for the release.",
            "interaction_surface": "TODAY",
        }
        resolved = self.client.post(
            f"/v2/attention/{request_episode.id}/resolve",
            headers=self._command("owner-token", "resolve-request"),
            json=resolution_body,
        )
        replay = self.client.post(
            f"/v2/attention/{request_episode.id}/resolve",
            headers=self._command("owner-token", "resolve-request"),
            json=resolution_body,
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(resolved.json(), replay.json())
        self.assertEqual(resolved.json()["item"]["status"], "CLOSED")
        self.assertEqual(resolved.json()["delivery"], "QUEUED")
        self.assertTrue(resolved.json()["guidance_id"])
        self.assertEqual(self.wake.await_count, 2)
        self.wake.assert_awaited_with("owned")

        open_queue = self.client.get("/v2/attention", headers=self._auth("owner-token")).json()
        self.assertEqual([item["id"] for item in open_queue["items"]], [failure.id])
        history = self.client.get(
            "/v2/projects/owned/attention",
            headers=self._auth("viewer-token"),
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(
            {item["id"] for item in history.json()["items"]},
            {failure.id, request_episode.id},
        )
        closed_detail = self.client.get(
            f"/v2/attention/{request_episode.id}",
            headers=self._auth("owner-token"),
        )
        self.assertEqual(closed_detail.status_code, 200, closed_detail.text)
        self.assertEqual(closed_detail.json()["status"], "CLOSED")

        with database.session() as session:
            self.assertEqual(session.get(AttentionRequest, request.id).status, "RESOLVED")
            guidance = session.scalars(
                select(InboxMessage).where(InboxMessage.challenge_id == owned.id)
            ).all()
            self.assertEqual(len(guidance), 1)
            self.assertEqual(guidance[0].body, resolution_body["response"])

    def test_attention_action_projection_and_resolution_roles(self) -> None:
        self._create_project("owner-token", "action-policy")
        for subject, display_name, role in (
            ("editor", "Editor", "EDITOR"),
            ("viewer", "Viewer", "VIEWER"),
        ):
            member = self.client.put(
                "/v2/projects/action-policy/members",
                headers=self._auth("owner-token"),
                json={"subject": subject, "display_name": display_name, "role": role},
            )
            self.assertEqual(member.status_code, 200, member.text)

        database = self.app.state.runtime.database
        with database.session() as session, session.begin():
            project = session.scalar(select(Challenge).where(Challenge.slug == "action-policy"))
            coordinator = session.get(CoordinatorState, project.id)
            coordinator.status = "COMPLETE"
            notification = AttentionServiceTests._episode(
                session,
                project,
                item_type="notification_failure",
                severity="HIGH",
                rank=1,
                opened_at=NOW,
                allowed_actions=["ACKNOWLEDGE"],
            )
            failed_run = RuntimeRun(
                id=new_uuid(),
                challenge_id=project.id,
                runtime_engine="codex",
                status="FAILED",
                summary="The runtime failed.",
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=1),
            )
            session.add(failed_run)
            session.flush()
            failure = AttentionServiceTests._episode(
                session,
                project,
                item_type="run_failure",
                severity="HIGH",
                rank=1,
                opened_at=NOW,
                allowed_actions=["ACKNOWLEDGE"],
                source_ref={"run_id": failed_run.id},
                source_key=f"run:{failed_run.id}",
                resolution_semantics="project_wide_acknowledge",
            )

        viewer_items = {
            item["kind"]: item
            for item in self.client.get("/v2/attention", headers=self._auth("viewer-token")).json()[
                "items"
            ]
        }
        self.assertEqual(viewer_items["project_complete"]["allowed_actions"], ["ACKNOWLEDGE"])
        self.assertEqual(viewer_items["notification_failure"]["allowed_actions"], [])
        self.assertEqual(viewer_items["run_failure"]["allowed_actions"], [])

        viewer_ack = self.client.post(
            f"/v2/attention/{viewer_items['project_complete']['id']}/resolve",
            headers=self._command("viewer-token", "viewer-ack-complete"),
            json={"action": "ACKNOWLEDGE", "expected_version": 1},
        )
        self.assertEqual(viewer_ack.status_code, 200, viewer_ack.text)

        editor_notification = self.client.post(
            f"/v2/attention/{notification.id}/resolve",
            headers=self._command("editor-token", "editor-ack-notification"),
            json={"action": "ACKNOWLEDGE", "expected_version": 1},
        )
        self.assertEqual(editor_notification.status_code, 403, editor_notification.text)

        owner_notification = self.client.post(
            f"/v2/attention/{notification.id}/resolve",
            headers=self._command("owner-token", "owner-ack-notification"),
            json={"action": "ACKNOWLEDGE", "expected_version": 1},
        )
        self.assertEqual(owner_notification.status_code, 200, owner_notification.text)

        invalid_action = self.client.post(
            f"/v2/attention/{failure.id}/resolve",
            headers=self._command("owner-token", "invalid-failure-action"),
            json={
                "action": "SNOOZE",
                "expected_version": viewer_items["run_failure"]["version"],
                "snooze_until": (NOW + timedelta(hours=1)).isoformat(),
            },
        )
        self.assertEqual(invalid_action.status_code, 409, invalid_action.text)
        self.assertEqual(
            invalid_action.json()["error"],
            {
                "code": "ATTENTION_ACTION_NOT_ALLOWED",
                "message": "The action is not available for this attention item.",
                "details": {
                    "action": "SNOOZE",
                    "allowed_actions": ["ACKNOWLEDGE"],
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
