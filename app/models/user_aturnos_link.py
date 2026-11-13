from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserATurnosLink(Base):
    __tablename__ = "user_aturnos_links"

    __table_args__ = (
        UniqueConstraint(
            "id_aturno",
            "id_user",
            name="uq_aturnos_links_external_identity",
        ),
        UniqueConstraint(
            "user_id",
            "id_aturno",
            name="uq_aturnos_links_user_team",
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
    id_aturno: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    id_user: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )