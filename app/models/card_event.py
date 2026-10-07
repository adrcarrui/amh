from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CardEvent(Base):
    __tablename__ = "card_events"

    __table_args__ = (
        CheckConstraint(
            "action IN ('assigned', 'revoked')",
            name="ck_card_events_action",
        ),
        CheckConstraint(
            "(actor_kind = 'user' AND actor_user_id IS NOT NULL) OR "
            "(actor_kind = 'system' AND actor_user_id IS NULL)",
            name="ck_card_events_actor",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    card_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user_cards.id"),
        nullable=False,
        index=True,
    )
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )