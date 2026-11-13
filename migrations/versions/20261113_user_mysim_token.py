"""Prepare encrypted mySim token storage.

Revision ID: 20261113_user_mysim_token
Revises: 20261112_aturnos_sync_runs
"""

from alembic import op
import sqlalchemy as sa


revision = "20261113_user_mysim_token"
down_revision = "20261112_aturnos_sync_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "mysim_token_encrypted",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "mysim_token_encrypted")