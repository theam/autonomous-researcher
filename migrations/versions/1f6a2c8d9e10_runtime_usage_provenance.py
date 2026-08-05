"""Add per-turn token detail and cost provenance.

Revision ID: 1f6a2c8d9e10
Revises: 7e4a19b8d2c6
Create Date: 2026-07-15 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1f6a2c8d9e10"
down_revision: str | Sequence[str] | None = "7e4a19b8d2c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runtime_runs", sa.Column("reasoning_output_tokens", sa.BigInteger()))
    op.add_column("runtime_runs", sa.Column("total_tokens", sa.BigInteger()))
    op.add_column("runtime_runs", sa.Column("usage_source", sa.String(length=40)))
    op.add_column("runtime_runs", sa.Column("cost_source", sa.String(length=40)))


def downgrade() -> None:
    op.drop_column("runtime_runs", "cost_source")
    op.drop_column("runtime_runs", "usage_source")
    op.drop_column("runtime_runs", "total_tokens")
    op.drop_column("runtime_runs", "reasoning_output_tokens")
