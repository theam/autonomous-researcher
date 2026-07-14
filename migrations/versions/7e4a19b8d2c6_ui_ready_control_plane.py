"""UI-ready collaboration, knowledge graph, and runtime observability.

Revision ID: 7e4a19b8d2c6
Revises: c0d3c1a2b7e9
Create Date: 2026-07-14 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7e4a19b8d2c6"
down_revision: str | Sequence[str] | None = "c0d3c1a2b7e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_members",
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("created_by", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("challenge_id", "subject"),
    )
    op.create_index("ix_project_member_subject", "project_members", ["subject", "role"])
    op.create_table(
        "live_tickets",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("instance_admin", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_live_ticket_expiry", "live_tickets", ["expires_at", "used_at"])
    op.create_table(
        "project_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=200), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_id", "name", name="uq_project_source_name"),
    )
    op.create_index("ix_project_source_challenge", "project_sources", ["challenge_id", "status"])
    op.create_table(
        "knowledge_relations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("source_artifact_id", sa.String(length=16), nullable=False),
        sa.Column("target_artifact_id", sa.String(length=16), nullable=False),
        sa.Column("relation_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["challenge_id", "source_artifact_id"],
            ["artifacts.challenge_id", "artifacts.artifact_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id", "target_artifact_id"],
            ["artifacts.challenge_id", "artifacts.artifact_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "challenge_id",
            "source_artifact_id",
            "target_artifact_id",
            "relation_type",
            name="uq_knowledge_relation",
        ),
    )
    op.create_index(
        "ix_relation_source", "knowledge_relations", ["challenge_id", "source_artifact_id"]
    )
    op.create_index(
        "ix_relation_target", "knowledge_relations", ["challenge_id", "target_artifact_id"]
    )
    op.create_table(
        "artifact_comments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_id", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["challenge_id", "artifact_id"],
            ["artifacts.challenge_id", "artifacts.artifact_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("command_id"),
    )
    op.create_index(
        "ix_artifact_comment",
        "artifact_comments",
        ["challenge_id", "artifact_id", "created_at"],
    )
    op.create_table(
        "artifact_tags",
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_id", sa.String(length=16), nullable=False),
        sa.Column("tag", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["challenge_id", "artifact_id"],
            ["artifacts.challenge_id", "artifacts.artifact_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("challenge_id", "artifact_id", "tag"),
    )
    op.create_index("ix_artifact_tag_lookup", "artifact_tags", ["challenge_id", "tag"])
    op.create_table(
        "saved_knowledge_views",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("query", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_id", "name", name="uq_saved_view_name"),
    )
    op.create_index(
        "ix_saved_view_challenge", "saved_knowledge_views", ["challenge_id", "updated_at"]
    )
    op.create_table(
        "runtime_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("runtime_engine", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("turn_id", sa.String(length=200), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_run_challenge_started", "runtime_runs", ["challenge_id", "started_at"]
    )
    op.create_index("ix_runtime_run_status", "runtime_runs", ["challenge_id", "status"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE INDEX ix_artifact_search_fts ON artifacts USING GIN (
                to_tsvector(
                    'simple',
                    coalesce(title, '') || ' ' || coalesce(payload::text, '')
                )
            )
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_artifact_search_fts")
    op.drop_index("ix_runtime_run_status", table_name="runtime_runs")
    op.drop_index("ix_runtime_run_challenge_started", table_name="runtime_runs")
    op.drop_table("runtime_runs")
    op.drop_index("ix_saved_view_challenge", table_name="saved_knowledge_views")
    op.drop_table("saved_knowledge_views")
    op.drop_index("ix_artifact_tag_lookup", table_name="artifact_tags")
    op.drop_table("artifact_tags")
    op.drop_index("ix_artifact_comment", table_name="artifact_comments")
    op.drop_table("artifact_comments")
    op.drop_index("ix_relation_target", table_name="knowledge_relations")
    op.drop_index("ix_relation_source", table_name="knowledge_relations")
    op.drop_table("knowledge_relations")
    op.drop_index("ix_project_source_challenge", table_name="project_sources")
    op.drop_table("project_sources")
    op.drop_index("ix_live_ticket_expiry", table_name="live_tickets")
    op.drop_table("live_tickets")
    op.drop_index("ix_project_member_subject", table_name="project_members")
    op.drop_table("project_members")
