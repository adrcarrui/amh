from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, User, UserApplicationAccess


ROLE_LEVEL = {
    "viewer": 1,
    "editor": 2,
    "admin": 3,
}


def has_application_access(
    db: Session,
    *,
    user_id: UUID,
    application_code: str,
    minimum_role: str = "viewer",
) -> bool:
    if minimum_role not in ROLE_LEVEL:
        raise ValueError("Rol requerido no válido")

    role = db.scalar(
        select(UserApplicationAccess.role)
        .join(User, User.id == UserApplicationAccess.user_id)
        .join(
            Application,
            Application.id == UserApplicationAccess.application_id,
        )
        .where(
            User.id == user_id,
            User.is_blocked.is_(False),
            Application.code == application_code,
            Application.is_enabled.is_(True),
            UserApplicationAccess.status == "active",
        )
    )

    return role is not None and ROLE_LEVEL[role] >= ROLE_LEVEL[minimum_role]