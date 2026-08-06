"""Append-only human reviews pinned to exact research artifact revisions."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import Principal
from .database import Database
from .errors import ConflictError, InvariantError, NotFoundError
from .models import (
    Artifact,
    ArtifactReview,
    ArtifactRevision,
    AttentionEpisode,
    AttentionRequest,
    Challenge,
    CommandReceipt,
    Event,
    InboxMessage,
    new_uuid,
    utcnow,
)

REVIEW_OUTCOMES = {
    "ACCEPT",
    "ACCEPT_WITH_RESERVATIONS",
    "NEEDS_MORE_EVIDENCE",
    "REJECT",
}
INTERACTION_SURFACES = {"TODAY", "PROJECT_DETAIL", "KNOWLEDGE"}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


class ArtifactReviewService:
    """Persist and query human judgment without mutating agent-owned artifacts."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def list_reviews(self, slug: str, artifact_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            challenge, artifact = self._artifact(session, slug, artifact_id)
            reviews = session.scalars(
                select(ArtifactReview)
                .where(
                    ArtifactReview.challenge_id == challenge.id,
                    ArtifactReview.artifact_uid == artifact.uid,
                )
                .order_by(ArtifactReview.created_at.desc(), ArtifactReview.id.desc())
            ).all()
            return [self._public_review(item, artifact.artifact_id) for item in reviews]

    def create_review(
        self,
        *,
        slug: str,
        artifact_id: str,
        artifact_version: int,
        outcome: str,
        rationale: str,
        guidance: str | None,
        supersedes_id: str | None,
        interaction_surface: str,
        principal: Principal,
        command_id: str,
    ) -> dict[str, Any]:
        outcome = outcome.strip().upper()
        interaction_surface = interaction_surface.strip().upper()
        rationale = rationale.strip()
        guidance = guidance.strip() if guidance and guidance.strip() else None
        if outcome not in REVIEW_OUTCOMES:
            raise InvariantError("The review outcome is not supported.", outcome=outcome)
        if outcome != "ACCEPT" and not rationale:
            raise InvariantError("A rationale is required unless the review accepts the evidence.")
        if interaction_surface not in INTERACTION_SURFACES:
            raise InvariantError("The review interaction surface is not supported.")
        if artifact_version < 1:
            raise InvariantError("Artifact version must be positive.")

        with self.database.session() as session:
            try:
                with session.begin():
                    receipt = session.get(CommandReceipt, command_id)
                    if receipt is not None:
                        if (
                            receipt.actor != principal.actor
                            or receipt.command_type != "artifact.review"
                        ):
                            raise ConflictError("The idempotency key was already used.")
                        return receipt.result

                    challenge, artifact = self._artifact(session, slug, artifact_id)
                    revision = session.scalar(
                        select(ArtifactRevision).where(
                            ArtifactRevision.artifact_uid == artifact.uid,
                            ArtifactRevision.version == artifact_version,
                        )
                    )
                    if revision is None:
                        raise NotFoundError(
                            f"Revision v{artifact_version} of '{artifact_id}' does not exist.",
                            artifact_id=artifact_id,
                            artifact_version=artifact_version,
                        )

                    superseded = None
                    if supersedes_id:
                        superseded = session.get(ArtifactReview, supersedes_id)
                        if superseded is None or superseded.artifact_uid != artifact.uid:
                            raise NotFoundError("The review to supersede does not exist.")

                    matching_requests = list(
                        session.scalars(
                            select(AttentionRequest)
                            .where(
                                AttentionRequest.challenge_id == challenge.id,
                                AttentionRequest.status == "OPEN",
                                AttentionRequest.response_mode == "ARTIFACT_REVIEW",
                                AttentionRequest.artifact_uid == artifact.uid,
                                AttentionRequest.artifact_version == artifact_version,
                            )
                            .with_for_update()
                        ).all()
                    )
                    guidance_body = guidance
                    if matching_requests:
                        decision = [
                            f"Review outcome for {artifact.artifact_id} v{artifact_version}: "
                            f"{outcome}."
                        ]
                        if rationale:
                            decision.append(f"Rationale: {rationale}")
                        if guidance:
                            decision.append(f"Guidance: {guidance}")
                        guidance_body = " ".join(decision)

                    guidance_message = None
                    if guidance_body:
                        guidance_message = InboxMessage(
                            id=new_uuid(),
                            challenge_id=challenge.id,
                            kind="REVIEW",
                            body=guidance_body,
                            actor=principal.actor,
                            command_id=self._child_command_id(command_id, "guidance"),
                        )
                        session.add(guidance_message)
                        session.flush()

                    review = ArtifactReview(
                        challenge_id=challenge.id,
                        artifact_uid=artifact.uid,
                        artifact_version=artifact_version,
                        outcome=outcome,
                        rationale=rationale,
                        reviewer_subject=principal.subject,
                        reviewer_name=principal.display_name,
                        interaction_surface=interaction_surface,
                        command_id=command_id,
                        supersedes_id=superseded.id if superseded else None,
                        guidance_id=guidance_message.id if guidance_message else None,
                    )
                    session.add(review)
                    session.flush()

                    changed_at = utcnow()
                    finding_episodes = list(
                        session.scalars(
                            select(AttentionEpisode).where(
                                AttentionEpisode.challenge_id == challenge.id,
                                AttentionEpisode.item_type == "finding_review",
                                AttentionEpisode.source_key
                                == f"artifact:{artifact.uid}:v{artifact_version}",
                                AttentionEpisode.status == "OPEN",
                            )
                        ).all()
                    )
                    request_ids = {item.id for item in matching_requests}
                    request_episodes = (
                        list(
                            session.scalars(
                                select(AttentionEpisode).where(
                                    AttentionEpisode.attention_request_id.in_(request_ids),
                                    AttentionEpisode.status == "OPEN",
                                )
                            ).all()
                        )
                        if request_ids
                        else []
                    )
                    for request in matching_requests:
                        request.status = "RESOLVED"
                        request.resolution = {
                            "action": "REVIEW",
                            "review_id": review.id,
                            "outcome": outcome,
                        }
                        request.resolved_at = changed_at
                        request.resolved_by = principal.subject
                        request.updated_at = changed_at
                        request.version += 1
                    for episode in [*finding_episodes, *request_episodes]:
                        episode.status = "CLOSED"
                        episode.closed_at = changed_at
                        episode.updated_at = changed_at
                        episode.version += 1

                    event = Event(
                        challenge_id=challenge.id,
                        event_type="artifact.reviewed",
                        actor=principal.actor,
                        artifact_id=artifact.artifact_id,
                        payload={
                            "review_id": review.id,
                            "artifact_version": artifact_version,
                            "outcome": outcome,
                            "guidance_id": guidance_message.id if guidance_message else None,
                            "attention_request_ids": sorted(request_ids),
                            "interaction_surface": interaction_surface,
                        },
                        command_id=command_id,
                    )
                    session.add(event)
                    session.flush()
                    result = {
                        "review": self._public_review(review, artifact.artifact_id),
                        "guidance": (
                            {
                                "id": guidance_message.id,
                                "body": guidance_message.body,
                                "kind": guidance_message.kind,
                                "sequence": guidance_message.sequence,
                            }
                            if guidance_message
                            else None
                        ),
                    }
                    session.add(
                        CommandReceipt(
                            command_id=command_id,
                            command_type="artifact.review",
                            actor=principal.actor,
                            result=result,
                        )
                    )
                return result
            except IntegrityError as exc:
                session.rollback()
                with self.database.session() as retry:
                    receipt = retry.get(CommandReceipt, command_id)
                    if (
                        receipt is not None
                        and receipt.command_type == "artifact.review"
                        and receipt.actor == principal.actor
                    ):
                        return receipt.result
                raise ConflictError("The review conflicted with another write.") from exc

    @staticmethod
    def _child_command_id(command_id: str, suffix: str) -> str:
        digest = hashlib.sha256(f"{command_id}:{suffix}".encode()).hexdigest()
        return f"review:{digest[:48]}"

    @staticmethod
    def _artifact(session: Session, slug: str, artifact_id: str) -> tuple[Challenge, Artifact]:
        challenge = session.scalar(select(Challenge).where(Challenge.slug == slug.lower()))
        if challenge is None:
            raise NotFoundError(f"Project '{slug}' does not exist.")
        artifact = session.scalar(
            select(Artifact).where(
                Artifact.challenge_id == challenge.id,
                Artifact.artifact_id == artifact_id.upper(),
            )
        )
        if artifact is None:
            raise NotFoundError(f"Artifact '{artifact_id}' does not exist.")
        return challenge, artifact

    @staticmethod
    def _public_review(review: ArtifactReview, artifact_id: str) -> dict[str, Any]:
        return {
            "id": review.id,
            "artifact_id": artifact_id,
            "artifact_version": review.artifact_version,
            "outcome": review.outcome,
            "rationale": review.rationale,
            "reviewer_subject": review.reviewer_subject,
            "reviewer_name": review.reviewer_name,
            "supersedes_id": review.supersedes_id,
            "guidance_id": review.guidance_id,
            "interaction_surface": review.interaction_surface,
            "created_at": _iso(review.created_at),
        }
