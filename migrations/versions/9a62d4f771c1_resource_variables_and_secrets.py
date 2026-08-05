"""resource variables and encrypted secrets

Revision ID: 9a62d4f771c1
Revises: 474c29565487
Create Date: 2026-07-13 16:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a62d4f771c1"
down_revision: str | Sequence[str] | None = "474c29565487"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace resource references with runtime variables and encrypted secrets."""
    op.add_column(
        "project_resources",
        sa.Column("resource_type", sa.String(length=16), nullable=True),
    )
    op.add_column("project_resources", sa.Column("value", sa.Text(), nullable=True))
    op.add_column(
        "project_resources",
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
    )
    op.add_column(
        "project_resources",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE project_resources
            SET name = upper(replace(name, '-', '_')),
                resource_type = 'VARIABLE',
                value = uri,
                updated_at = created_at
            """
        )
    )
    with op.batch_alter_table("project_resources") as batch:
        batch.alter_column("resource_type", existing_type=sa.String(length=16), nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.drop_column("credential_env")
        batch.drop_column("kind")
        batch.drop_column("uri")


def downgrade() -> None:
    """Restore the old reference shape without attempting to reveal secrets."""
    op.add_column("project_resources", sa.Column("uri", sa.Text(), nullable=True))
    op.add_column(
        "project_resources",
        sa.Column("kind", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "project_resources",
        sa.Column("credential_env", sa.String(length=160), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE project_resources
            SET uri = CASE
                    WHEN resource_type = 'VARIABLE' THEN value
                    ELSE 'secret://redacted'
                END,
                kind = 'OTHER'
            """
        )
    )
    with op.batch_alter_table("project_resources") as batch:
        batch.alter_column("uri", existing_type=sa.Text(), nullable=False)
        batch.alter_column("kind", existing_type=sa.String(length=40), nullable=False)
        batch.drop_column("updated_at")
        batch.drop_column("secret_ciphertext")
        batch.drop_column("value")
        batch.drop_column("resource_type")
