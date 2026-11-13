"""Add user links to aTurnos.

Revision ID: 20261112_aturnos_links
Revises: e5ab0ae2e228
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261112_aturnos_links"
down_revision = "e5ab0ae2e228"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_aturnos_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "id_aturno",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "id_user",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id_aturno",
            "id_user",
            name="uq_aturnos_links_external_identity",
        ),
        sa.UniqueConstraint(
            "user_id",
            "id_aturno",
            name="uq_aturnos_links_user_team",
        ),
    )

    op.create_index(
        "ix_user_aturnos_links_user_id",
        "user_aturnos_links",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_aturnos_links_user_id",
        table_name="user_aturnos_links",
    )
    op.drop_table("user_aturnos_links")