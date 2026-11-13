from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserStatusEvent(Base):
    __tablename__ = "user_status_events"

    __table_args__ = (
        CheckConstraint(
            "old_is_blocked <> new_is_blocked",
            name="ck_user_status_events_changed",
        ),
        CheckConstraint(
            "length(btrim(reason)) > 0",
            name="ck_user_status_events_reason",
        ),
        CheckConstraint(
            "revoked_sessions >= 0",
            name="ck_user_status_events_sessions",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    actor_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )

    old_is_blocked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    new_is_blocked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    revoked_sessions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )