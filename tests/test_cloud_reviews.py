from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from limina_cloud.attention_service import record_checkpoint_request
from limina_cloud.auth import Principal
from limina_cloud.database import Database
from limina_cloud.errors import InvariantError
from limina_cloud.models import (
    AttentionEpisode,
    AttentionRequest,
    Challenge,
    InboxMessage,
)
from limina_cloud.review_service import ArtifactReviewService
from limina_cloud.service import ChallengeService
from limina_cloud.vault import SecretCipher


def command_id() -> str:
    return str(uuid4())


class ArtifactReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(f"sqlite:///{Path(self.temp_dir.name) / 'reviews.db'}")
        self.database.initialize()
        self.challenge = ChallengeService(self.database, SecretCipher.ephemeral())
        self.reviews = ArtifactReviewService(self.database)
        self.principal = Principal(
            subject="user_reviewer",
            display_name="Research reviewer",
            email="reviewer@example.test",
            auth_mode="dev-jwt",
            organization="org_test",
            permissions=frozenset({"limina:access"}),
        )
        self.challenge.create_challenge(
            slug="review-project",
            name="Review project",
            objective="Test evidence review.",
            success_criteria="A review is pinned without changing evidence.",
            context="",
            actor="owner",
            command_id=command_id(),
        )
        hypothesis = self.challenge.create_hypothesis(
            slug="review-project",
            title="Pinned review",
            statement="A review can target an immutable revision.",
            mechanism="Append-only persistence.",
            generalization="All H/E/F revisions use the same mechanism.",
            shortcut_risks="Reviewing the wrong version.",
            test_plan="Publish and review a finding.",
            actor="agent",
            command_id=command_id(),
        )
        experiment = self.challenge.create_experiment(
            slug="review-project",
            hypothesis_id=hypothesis["id"],
            title="Review persistence",
            objective="Create reviewable evidence.",
            procedure="Complete one controlled experiment.",
            success_criteria="Finding is published.",
            guardrails="Do not mutate the finding during review.",
            actor="agent",
            command_id=command_id(),
        )
        claimed = self.challenge.claim_experiment(
            slug="review-project",
            artifact_id=experiment["id"],
            ttl_seconds=300,
            actor="agent",
            command_id=command_id(),
        )
        completed = self.challenge.complete_experiment(
            slug="review-project",
            artifact_id=experiment["id"],
            results="The append-only write succeeded.",
            analysis="The original artifact remained stable.",
            decision="Publish the finding.",
            expected_version=claimed["artifact"]["version"],
            actor="agent",
            command_id=command_id(),
        )
        self.finding = self.challenge.publish_finding(
            slug="review-project",
            experiment_id=completed["id"],
            title="Reviews are append-only",
            finding="Human judgment can be recorded separately.",
            evidence="The artifact status and payload are unchanged.",
            improvement="Auditable human decisions.",
            remaining_debt="None for the persistence seam.",
            next_move="Expose the review in the Console.",
            impact="HIGH",
            actor="agent",
            command_id=command_id(),
        )

    def tearDown(self) -> None:
        self.database.dispose()
        self.temp_dir.cleanup()

    def test_review_is_revision_pinned_append_only_and_idempotent(self) -> None:
        before = self.challenge.get_artifact("review-project", self.finding["id"])
        key = command_id()
        first = self.reviews.create_review(
            slug="review-project",
            artifact_id=self.finding["id"],
            artifact_version=self.finding["version"],
            outcome="ACCEPT_WITH_RESERVATIONS",
            rationale="The evidence is credible, with a narrow fixture limitation.",
            guidance=None,
            supersedes_id=None,
            interaction_surface="KNOWLEDGE",
            principal=self.principal,
            command_id=key,
        )
        replay = self.reviews.create_review(
            slug="review-project",
            artifact_id=self.finding["id"],
            artifact_version=self.finding["version"],
            outcome="ACCEPT_WITH_RESERVATIONS",
            rationale="The evidence is credible, with a narrow fixture limitation.",
            guidance=None,
            supersedes_id=None,
            interaction_surface="KNOWLEDGE",
            principal=self.principal,
            command_id=key,
        )

        self.assertEqual(first, replay)
        self.assertEqual(first["review"]["artifact_version"], self.finding["version"])
        self.assertEqual(len(self.reviews.list_reviews("review-project", self.finding["id"])), 1)
        after = self.challenge.get_artifact("review-project", self.finding["id"])
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["payload"], before["payload"])
        self.assertEqual(after["version"], before["version"])

    def test_non_accept_review_requires_rationale(self) -> None:
        with self.assertRaises(InvariantError):
            self.reviews.create_review(
                slug="review-project",
                artifact_id=self.finding["id"],
                artifact_version=self.finding["version"],
                outcome="REJECT",
                rationale="",
                guidance=None,
                supersedes_id=None,
                interaction_surface="TODAY",
                principal=self.principal,
                command_id=command_id(),
            )

    def test_structured_review_resolves_matching_executor_request_and_wakes_with_decision(
        self,
    ) -> None:
        with self.database.session() as session, session.begin():
            challenge = session.scalar(select(Challenge).where(Challenge.slug == "review-project"))
            request_ids = record_checkpoint_request(
                session,
                challenge=challenge,
                checkpoint_sequence=50,
                request={
                    "kind": "REVIEW",
                    "response_mode": "ARTIFACT_REVIEW",
                    "priority": "HIGH",
                    "title": "Review the current finding",
                    "body": "Decide whether this exact finding revision is credible.",
                    "artifact_id": self.finding["id"],
                    "artifact_version": self.finding["version"],
                },
                actor="executor",
            )

        result = self.reviews.create_review(
            slug="review-project",
            artifact_id=self.finding["id"],
            artifact_version=self.finding["version"],
            outcome="NEEDS_MORE_EVIDENCE",
            rationale="The evidence lacks a failure-mode control.",
            guidance=None,
            supersedes_id=None,
            interaction_surface="KNOWLEDGE",
            principal=self.principal,
            command_id=command_id(),
        )

        self.assertIsNotNone(result["guidance"])
        self.assertIn("NEEDS_MORE_EVIDENCE", result["guidance"]["body"])
        with self.database.session() as session:
            request = session.get(AttentionRequest, request_ids["request_id"])
            episode = session.get(AttentionEpisode, request_ids["episode_id"])
            guidance = session.scalar(
                select(InboxMessage).where(InboxMessage.id == result["guidance"]["id"])
            )
            self.assertEqual(request.status, "RESOLVED")
            self.assertEqual(request.resolution["review_id"], result["review"]["id"])
            self.assertEqual(episode.status, "CLOSED")
            self.assertEqual(guidance.status, "PENDING")
