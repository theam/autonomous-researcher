"""add selectable runtime engines

Revision ID: c0d3c1a2b7e9
Revises: 9a62d4f771c1
Create Date: 2026-07-14 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0d3c1a2b7e9"
down_revision: str | Sequence[str] | None = "9a62d4f771c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist each project's immutable engine and neutralize continuation state."""
    op.add_column(
        "challenges",
        sa.Column(
            "runtime_engine",
            sa.String(length=32),
            nullable=False,
            server_default="codex",
        ),
    )
    with op.batch_alter_table("coordinator_states") as batch:
        batch.alter_column(
            "thread_id",
            new_column_name="continuation_id",
            existing_type=sa.String(length=200),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Return to the original Codex-only schema."""
    with op.batch_alter_table("coordinator_states") as batch:
        batch.alter_column(
            "continuation_id",
            new_column_name="thread_id",
            existing_type=sa.String(length=200),
            existing_nullable=True,
        )
    op.drop_column("challenges", "runtime_engine")
