from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import has_application_access
from app.models import (
    AccessEvent,
    Application,
    User,
    UserApplicationAccess,
)


VALID_ROLES = {"viewer", "editor", "admin"}
VALID_STATUSES = {"active", "blocked", "revoked"}


def set_application_access(
    db: Session,
    *,
    actor_user_id: UUID,
    user_id: UUID,
    application_code: str,
    role: str,
    status: str,
    reason: str | None = None,
) -> UserApplicationAccess:
    """Create or change one application grant and record the change.

    The caller owns the transaction; this function does not commit.
    """
    if not has_application_access(
        db,
        user_id=actor_user_id,
        application_code="amh",
        minimum_role="admin",
    ):
        raise PermissionError("Permiso de administración de AMH requerido")

    if role not in VALID_ROLES or status not in VALID_STATUSES:
        raise ValueError("Rol o estado no válido")

    if db.get(User, user_id) is None:
        raise ValueError("Usuario no encontrado")

    application = db.scalar(
        select(Application).where(Application.code == application_code)
    )
    if application is None:
        raise ValueError("Aplicación no encontrada")

    if application_code == "amh" and user_id == actor_user_id:
        raise ValueError("No puedes cambiar tu propio acceso a AMH")

    if reason is not None:
        reason = reason.strip()
        if len(reason) > 500:
            raise ValueError("Motivo demasiado largo")

    access = db.scalar(
        select(UserApplicationAccess)
        .where(
            UserApplicationAccess.user_id == user_id,
            UserApplicationAccess.application_id == application.id,
        )
        .with_for_update()
    )

    if access is None:
        if status != "active":
            raise ValueError("Para bloquear o revocar debe existir una concesión")

        old_status = None
        old_role = None
        action = "granted"

        access = UserApplicationAccess(
            user_id=user_id,
            application_id=application.id,
            status=status,
            role=role,
        )
        db.add(access)
        db.flush()
    else:
        old_status = access.status
        old_role = access.role

        if old_status == status and old_role == role:
            raise ValueError("El acceso ya tiene ese estado y rol")

        if status == "revoked":
            action = "revoked"
        elif status == "blocked":
            action = "blocked"
        elif old_status in {"blocked", "revoked"} and status == "active":
            action = "restored"
        else:
            action = "role_changed"

        access.status = status
        access.role = role
        db.flush()

    db.add(
        AccessEvent(
            access_id=access.id,
            actor_kind="user",
            actor_user_id=actor_user_id,
            action=action,
            old_status=old_status,
            new_status=status,
            old_role=old_role,
            new_role=role,
            reason=reason,
        )
    )
    db.flush()
    return access