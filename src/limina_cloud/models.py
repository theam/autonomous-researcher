"""Relational persistence model for the collaborative research runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    success_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_engine: Mapped[str] = mapped_column(String(32), nullable=False, default="codex")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ProjectResource(Base):
    __tablename__ = "project_resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("challenge_id", "name", name="uq_project_resource_name"),
        Index("ix_project_resource_challenge", "challenge_id", "status"),
    )


class ProjectMember(Base):
    __tablename__ = "project_members"

    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True
    )
    subject: Mapped[str] = mapped_column(String(300), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    created_by: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (Index("ix_project_member_subject", "subject", "role"),)


class LiveTicket(Base):
    __tablename__ = "live_tickets"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    instance_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (Index("ix_live_ticket_expiry", "expires_at", "used_at"),)


class ProjectSource(Base):
    __tablename__ = "project_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(200))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("challenge_id", "name", name="uq_project_source_name"),
        Index("ix_project_source_challenge", "challenge_id", "status"),
    )


class CoordinatorState(Base):
    __tablename__ = "coordinator_states"

    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    current_objective: Mapped[str] = mapped_column(Text, nullable=False)
    next_step: Mapped[str] = mapped_column(Text, nullable=False)
    blocker: Mapped[str] = mapped_column(Text, nullable=False, default="None")
    worker_id: Mapped[str | None] = mapped_column(String(200))
    continuation_id: Mapped[str | None] = mapped_column(String(200))
    inbox_cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IdCounter(Base):
    __tablename__ = "id_counters"

    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(4), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False)


class Artifact(Base):
    __tablename__ = "artifacts"

    uid: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(4), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    parent_hypothesis_id: Mapped[str | None] = mapped_column(String(16))
    parent_experiment_id: Mapped[str | None] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("challenge_id", "artifact_id", name="uq_artifact_challenge_display_id"),
        Index("ix_artifact_challenge_kind", "challenge_id", "kind"),
    )


class ArtifactRevision(Base):
    __tablename__ = "artifact_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_uid: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifacts.uid", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    command_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("artifact_uid", "version", name="uq_artifact_revision_version"),
    )


class AttentionRequest(Base):
    __tablename__ = "attention_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    response_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="NORMAL")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    artifact_uid: Mapped[str | None] = mapped_column(String(36))
    artifact_version: Mapped[int | None] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("runtime_runs.id", ondelete="SET NULL")
    )
    choices: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    recommended_choice_id: Mapped[str | None] = mapped_column(String(160))
    created_checkpoint_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["artifact_uid", "artifact_version"],
            ["artifact_revisions.artifact_uid", "artifact_revisions.version"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "challenge_id",
            "created_checkpoint_sequence",
            name="uq_attention_request_checkpoint",
        ),
        Index(
            "ix_attention_request_project_status",
            "challenge_id",
            "status",
            "created_at",
            "id",
        ),
    )


class AttentionEpisode(Base):
    __tablename__ = "attention_episodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    attention_request_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("attention_requests.id", ondelete="CASCADE")
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_key: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    severity_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    resolution_semantics: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "challenge_id", "item_type", "source_key", name="uq_attention_episode_source"
        ),
        UniqueConstraint("attention_request_id", name="uq_attention_episode_request"),
        Index(
            "ix_attention_episode_queue",
            "status",
            "severity_rank",
            "opened_at",
            "id",
        ),
        Index(
            "ix_attention_episode_project",
            "challenge_id",
            "status",
            "opened_at",
            "id",
        ),
    )


class AttentionDisposition(Base):
    __tablename__ = "attention_dispositions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    episode_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("attention_episodes.id", ondelete="CASCADE"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(String(320), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_subject: Mapped[str] = mapped_column(String(300), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(240), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interaction_surface: Mapped[str] = mapped_column(String(32), nullable=False)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("episode_id", "scope_key", name="uq_attention_disposition_scope"),
        Index("ix_attention_disposition_scope", "scope_key", "updated_at", "id"),
    )


class ArtifactReview(Base):
    __tablename__ = "artifact_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    artifact_uid: Mapped[str] = mapped_column(String(36), nullable=False)
    artifact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_subject: Mapped[str] = mapped_column(String(300), nullable=False)
    reviewer_name: Mapped[str] = mapped_column(String(240), nullable=False)
    interaction_surface: Mapped[str] = mapped_column(String(32), nullable=False)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("artifact_reviews.id", ondelete="RESTRICT")
    )
    guidance_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inbox_messages.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["artifact_uid", "artifact_version"],
            ["artifact_revisions.artifact_uid", "artifact_revisions.version"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_artifact_review_revision",
            "challenge_id",
            "artifact_uid",
            "artifact_version",
            "created_at",
            "id",
        ),
    )


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    channel_type: Mapped[str] = mapped_column(String(24), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    destination_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    health: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_started_delivery_id: Mapped[str | None] = mapped_column(String(36))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trust_confirmed_by: Mapped[str] = mapped_column(String(300), nullable=False)
    trust_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(300), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("challenge_id", "display_name", name="uq_notification_channel_name"),
        Index(
            "ix_notification_channel_project",
            "challenge_id",
            "enabled",
            "health",
            "id",
        ),
    )


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    attention_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    severities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(300), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("challenge_id", "display_name", name="uq_notification_rule_name"),
        Index(
            "ix_notification_rule_project",
            "challenge_id",
            "enabled",
            "updated_at",
            "id",
        ),
        Index("ix_notification_rule_channel", "channel_id", "enabled", "id"),
    )


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    delivery_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=new_uuid
    )
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("notification_rules.id", ondelete="SET NULL")
    )
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False
    )
    attention_episode_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("attention_episodes.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    claimed_by: Mapped[str | None] = mapped_column(String(200))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_class: Mapped[str | None] = mapped_column(String(80))
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("rule_id", "dedupe_key", name="uq_notification_outbox_dedupe"),
        Index(
            "ix_notification_outbox_claim",
            "status",
            "next_attempt_at",
            "created_at",
            "id",
        ),
        Index(
            "ix_notification_outbox_project",
            "challenge_id",
            "created_at",
            "id",
        ),
    )


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    outbox_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("notification_outbox.id", ondelete="CASCADE"), nullable=False
    )
    delivery_id: Mapped[str] = mapped_column(String(36), nullable=False)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    response_class: Mapped[str] = mapped_column(String(40), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    worker_id: Mapped[str] = mapped_column(String(200), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("outbox_id", "attempt_number", name="uq_notification_delivery_attempt"),
        Index(
            "ix_notification_delivery_channel",
            "channel_id",
            "completed_at",
            "id",
        ),
        Index(
            "ix_notification_delivery_project",
            "challenge_id",
            "completed_at",
            "id",
        ),
    )


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    source_artifact_id: Mapped[str] = mapped_column(String(16), nullable=False)
    target_artifact_id: Mapped[str] = mapped_column(String(16), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["challenge_id", "source_artifact_id"],
            ["artifacts.challenge_id", "artifacts.artifact_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["challenge_id", "target_artifact_id"],
            ["artifacts.challenge_id", "artifacts.artifact_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "challenge_id",
            "source_artifact_id",
            "target_artifact_id",
            "relation_type",
            name="uq_knowledge_relation",
        ),
        Index("ix_relation_source", "challenge_id", "source_artifact_id"),
        Index("ix_relation_target", "challenge_id", "target_artifact_id"),
    )


class ArtifactComment(Base):
    __tablename__ = "artifact_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(String(36), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["challenge_id", "artifact_id"],
            ["artifacts.challenge_id", "artifacts.artifact_id"],
            ondelete="CASCADE",
        ),
        Index("ix_artifact_comment", "challenge_id", "artifact_id", "created_at"),
    )


class ArtifactTag(Base):
    __tablename__ = "artifact_tags"

    challenge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    tag: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["challenge_id", "artifact_id"],
            ["artifacts.challenge_id", "artifacts.artifact_id"],
            ondelete="CASCADE",
        ),
        Index("ix_artifact_tag_lookup", "challenge_id", "tag"),
    )


class SavedKnowledgeView(Base):
    __tablename__ = "saved_knowledge_views"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    query: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("challenge_id", "name", name="uq_saved_view_name"),
        Index("ix_saved_view_challenge", "challenge_id", "updated_at"),
    )


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(String(36), nullable=False)
    experiment_id: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["challenge_id", "experiment_id"],
            ["artifacts.challenge_id", "artifacts.artifact_id"],
            ondelete="CASCADE",
        ),
        Index("ix_observation_experiment", "challenge_id", "experiment_id"),
    )


class WorkLease(Base):
    __tablename__ = "work_leases"

    challenge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    token: Mapped[str] = mapped_column(String(36), nullable=False, default=new_uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
    )


class InboxMessage(Base):
    __tablename__ = "inbox_messages"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    command_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_inbox_challenge_status", "challenge_id", "status"),)


class Event(Base):
    __tablename__ = "events"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    command_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (Index("ix_event_challenge_sequence", "challenge_id", "sequence"),)


class RuntimeRun(Base):
    __tablename__ = "runtime_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    runtime_engine: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="RUNNING")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    turn_id: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cached_input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    reasoning_output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cost_microusd: Mapped[int | None] = mapped_column(BigInteger)
    usage_source: Mapped[str | None] = mapped_column(String(40))
    cost_source: Mapped[str | None] = mapped_column(String(40))
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        Index("ix_runtime_run_challenge_started", "challenge_id", "started_at"),
        Index("ix_runtime_run_status", "challenge_id", "status"),
    )


class CommandReceipt(Base):
    __tablename__ = "command_receipts"

    command_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    command_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
