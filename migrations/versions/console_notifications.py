"""Add project notification channels, rules, outbox, and delivery history.

Revision ID: console_notifications
Revises: console_attention_and_review
Create Date: 2026-08-06 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "console_notifications"
down_revision: str | Sequence[str] | None = "console_attention_and_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_channels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("channel_type", sa.String(length=24), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("destination_metadata", sa.JSON(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("health", sa.String(length=24), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("failure_started_delivery_id", sa.String(length=36), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trust_confirmed_by", sa.String(length=300), nullable=False),
        sa.Column("trust_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=300), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_id", "display_name", name="uq_notification_channel_name"),
    )
    op.create_index(
        "ix_notification_channel_project",
        "notification_channels",
        ["challenge_id", "enabled", "health", "id"],
    )

    op.create_table(
        "notification_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("attention_types", sa.JSON(), nullable=False),
        sa.Column("severities", sa.JSON(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=300), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["notification_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_id", "display_name", name="uq_notification_rule_name"),
    )
    op.create_index(
        "ix_notification_rule_project",
        "notification_rules",
        ["challenge_id", "enabled", "updated_at", "id"],
    )
    op.create_index(
        "ix_notification_rule_channel",
        "notification_rules",
        ["channel_id", "enabled", "id"],
    )

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("delivery_id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=True),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("attention_episode_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(length=200), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_class", sa.String(length=80), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["attention_episode_id"], ["attention_episodes.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["notification_channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["notification_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id"),
        sa.UniqueConstraint("rule_id", "dedupe_key", name="uq_notification_outbox_dedupe"),
    )
    op.create_index(
        "ix_notification_outbox_claim",
        "notification_outbox",
        ["status", "next_attempt_at", "created_at", "id"],
    )
    op.create_index(
        "ix_notification_outbox_project",
        "notification_outbox",
        ["challenge_id", "created_at", "id"],
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("outbox_id", sa.String(length=36), nullable=False),
        sa.Column("delivery_id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("response_class", sa.String(length=40), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("worker_id", sa.String(length=200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["notification_channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outbox_id"], ["notification_outbox.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbox_id", "attempt_number", name="uq_notification_delivery_attempt"),
    )
    op.create_index(
        "ix_notification_delivery_channel",
        "notification_deliveries",
        ["channel_id", "completed_at", "id"],
    )
    op.create_index(
        "ix_notification_delivery_project",
        "notification_deliveries",
        ["challenge_id", "completed_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_delivery_project", table_name="notification_deliveries")
    op.drop_index("ix_notification_delivery_channel", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index("ix_notification_outbox_project", table_name="notification_outbox")
    op.drop_index("ix_notification_outbox_claim", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_index("ix_notification_rule_channel", table_name="notification_rules")
    op.drop_index("ix_notification_rule_project", table_name="notification_rules")
    op.drop_table("notification_rules")
    op.drop_index("ix_notification_channel_project", table_name="notification_channels")
    op.drop_table("notification_channels")
