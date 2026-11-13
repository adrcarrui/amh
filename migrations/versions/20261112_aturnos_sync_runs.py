"""Add persisted aTurnos query results.

Revision ID: 20261112_aturnos_sync_runs
Revises: 20261112_aturnos_audit
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261112_aturnos_sync_runs"
down_revision = "20261112_aturnos_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aturnos_sync_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "id_aturno",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "trigger_kind",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "result",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "error_code",
            sa.String(length=64),
            nullable=True,
        ),
        sa.CheckConstraint(
            "trigger_kind IN ('manual', 'system')",
            name="ck_aturnos_sync_runs_trigger",
        ),
        sa.CheckConstraint(
            "trigger_kind <> 'manual' OR actor_user_id IS NOT NULL",
            name="ck_aturnos_sync_runs_actor",
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'error')",
            name="ck_aturnos_sync_runs_status",
        ),
        sa.CheckConstraint(
            "finished_at >= started_at",
            name="ck_aturnos_sync_runs_dates",
        ),
        sa.CheckConstraint(
            "(status = 'ok' AND result IS NOT NULL "
            "AND error_code IS NULL) OR "
            "(status = 'error' AND result IS NULL "
            "AND error_code IS NOT NULL)",
            name="ck_aturnos_sync_runs_result",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_aturnos_sync_runs_team_started",
        "aturnos_sync_runs",
        ["id_aturno", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_aturnos_sync_runs_team_started",
        table_name="aturnos_sync_runs",
    )
    op.drop_table("aturnos_sync_runs")