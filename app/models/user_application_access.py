from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserApplicationAccess(Base):
    __tablename__ = "user_application_access"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "application_id",
            name="uq_user_application_access_user_application",
        ),
        CheckConstraint(
            "status IN ('active', 'blocked', 'revoked')",
            name="ck_user_application_access_status",
        ),
        CheckConstraint(
            "role IN ('viewer', 'editor', 'admin')",
            name="ck_user_application_access_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    application_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("applications.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )