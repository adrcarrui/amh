from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ATurnosSyncRun(Base):
    __tablename__ = "aturnos_sync_runs"

    __table_args__ = (
        CheckConstraint(
            "trigger_kind IN ('manual', 'system')",
            name="ck_aturnos_sync_runs_trigger",
        ),
        CheckConstraint(
            "trigger_kind <> 'manual' OR actor_user_id IS NOT NULL",
            name="ck_aturnos_sync_runs_actor",
        ),
        CheckConstraint(
            "status IN ('ok', 'error')",
            name="ck_aturnos_sync_runs_status",
        ),
        CheckConstraint(
            "finished_at >= started_at",
            name="ck_aturnos_sync_runs_dates",
        ),
        CheckConstraint(
            "(status = 'ok' AND result IS NOT NULL "
            "AND error_code IS NULL) OR "
            "(status = 'error' AND result IS NULL "
            "AND error_code IS NOT NULL)",
            name="ck_aturnos_sync_runs_result",
        ),
        Index(
            "ix_aturnos_sync_runs_team_started",
            "id_aturno",
            "started_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    id_aturno: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    trigger_kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    result: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )
    
    error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )