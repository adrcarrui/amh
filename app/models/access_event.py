from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AccessEvent(Base):
    __tablename__ = "access_events"

    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('user', 'service', 'system')",
            name="ck_access_events_actor_kind",
        ),
        CheckConstraint(
            "actor_kind <> 'user' OR actor_user_id IS NOT NULL",
            name="ck_access_events_user_actor",
        ),
        CheckConstraint(
            "actor_kind <> 'service' OR actor_client_id IS NOT NULL",
            name="ck_access_events_service_actor",
        ),
        CheckConstraint(
            "old_status IS NULL OR old_status IN ('active', 'blocked', 'revoked')",
            name="ck_access_events_old_status",
        ),
        CheckConstraint(
            "new_status IN ('active', 'blocked', 'revoked')",
            name="ck_access_events_new_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    access_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user_application_access.id"),
        nullable=False,
        index=True,
    )
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    actor_client_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    old_role: Mapped[str | None] = mapped_column(String(20))
    new_role: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )