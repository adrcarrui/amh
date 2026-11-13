"""Register user blocking and unblocking events."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261113_user_status"
down_revision = "20261113_user_mysim_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_status_events",
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
            "old_is_blocked",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "new_is_blocked",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.String(length=500),
            nullable=False,
        ),
        sa.Column(
            "revoked_sessions",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
        ),
        sa.CheckConstraint(
            "old_is_blocked <> new_is_blocked",
            name="ck_user_status_events_changed",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0",
            name="ck_user_status_events_reason",
        ),
        sa.CheckConstraint(
            "revoked_sessions >= 0",
            name="ck_user_status_events_sessions",
        ),
    )

    op.create_index(
        "ix_user_status_events_user_id",
        "user_status_events",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_status_events_user_id",
        table_name="user_status_events",
    )
    op.drop_table("user_status_events")