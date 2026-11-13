"""Add audit events for successful aTurnos imports.

Revision ID: 20261112_aturnos_audit
Revises: 20261112_aturnos_links
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261112_aturnos_audit"
down_revision = "20261112_aturnos_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aturnos_import_events",
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
            "actor_user_id",
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
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_aturnos_import_events_user_id",
        "aturnos_import_events",
        ["user_id"],
    )

    op.create_index(
        "ix_aturnos_import_events_actor_user_id",
        "aturnos_import_events",
        ["actor_user_id"],
    )

    op.create_index(
        "ix_aturnos_import_events_occurred_at",
        "aturnos_import_events",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_aturnos_import_events_occurred_at",
        table_name="aturnos_import_events",
    )
    op.drop_index(
        "ix_aturnos_import_events_actor_user_id",
        table_name="aturnos_import_events",
    )
    op.drop_index(
        "ix_aturnos_import_events_user_id",
        table_name="aturnos_import_events",
    )
    op.drop_table("aturnos_import_events")