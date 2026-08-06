"""Add attention episodes, dispositions, and revision-pinned reviews.

Revision ID: console_attention_and_review
Revises: 1f6a2c8d9e10
Create Date: 2026-08-06 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "console_attention_and_review"
down_revision: str | Sequence[str] | None = "1f6a2c8d9e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attention_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("response_mode", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("artifact_uid", sa.String(length=36), nullable=True),
        sa.Column("artifact_version", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("choices", sa.JSON(), nullable=False),
        sa.Column("recommended_choice_id", sa.String(length=160), nullable=True),
        sa.Column("created_checkpoint_sequence", sa.BigInteger(), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("resolution", sa.JSON(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=300), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_uid", "artifact_version"],
            ["artifact_revisions.artifact_uid", "artifact_revisions.version"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runtime_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "challenge_id",
            "created_checkpoint_sequence",
            name="uq_attention_request_checkpoint",
        ),
    )
    op.create_index(
        "ix_attention_request_project_status",
        "attention_requests",
        ["challenge_id", "status", "created_at", "id"],
    )

    op.create_table(
        "attention_episodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("attention_request_id", sa.String(length=36), nullable=True),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("source_key", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("severity_rank", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.JSON(), nullable=False),
        sa.Column("allowed_actions", sa.JSON(), nullable=False),
        sa.Column("resolution_semantics", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["attention_request_id"], ["attention_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attention_request_id", name="uq_attention_episode_request"),
        sa.UniqueConstraint(
            "challenge_id", "item_type", "source_key", name="uq_attention_episode_source"
        ),
    )
    op.create_index(
        "ix_attention_episode_queue",
        "attention_episodes",
        ["status", "severity_rank", "opened_at", "id"],
    )
    op.create_index(
        "ix_attention_episode_project",
        "attention_episodes",
        ["challenge_id", "status", "opened_at", "id"],
    )

    op.create_table(
        "attention_dispositions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("episode_id", sa.String(length=36), nullable=False),
        sa.Column("scope_key", sa.String(length=320), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("actor_subject", sa.String(length=300), nullable=False),
        sa.Column("actor_name", sa.String(length=240), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interaction_surface", sa.String(length=32), nullable=False),
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["episode_id"], ["attention_episodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("command_id"),
        sa.UniqueConstraint("episode_id", "scope_key", name="uq_attention_disposition_scope"),
    )
    op.create_index(
        "ix_attention_disposition_scope",
        "attention_dispositions",
        ["scope_key", "updated_at", "id"],
    )

    op.create_table(
        "artifact_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_uid", sa.String(length=36), nullable=False),
        sa.Column("artifact_version", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("reviewer_subject", sa.String(length=300), nullable=False),
        sa.Column("reviewer_name", sa.String(length=240), nullable=False),
        sa.Column("interaction_surface", sa.String(length=32), nullable=False),
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column("guidance_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_uid", "artifact_version"],
            ["artifact_revisions.artifact_uid", "artifact_revisions.version"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["guidance_id"], ["inbox_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["artifact_reviews.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("command_id"),
    )
    op.create_index(
        "ix_artifact_review_revision",
        "artifact_reviews",
        ["challenge_id", "artifact_uid", "artifact_version", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_artifact_review_revision", table_name="artifact_reviews")
    op.drop_table("artifact_reviews")
    op.drop_index("ix_attention_disposition_scope", table_name="attention_dispositions")
    op.drop_table("attention_dispositions")
    op.drop_index("ix_attention_episode_project", table_name="attention_episodes")
    op.drop_index("ix_attention_episode_queue", table_name="attention_episodes")
    op.drop_table("attention_episodes")
    op.drop_index("ix_attention_request_project_status", table_name="attention_requests")
    op.drop_table("attention_requests")
