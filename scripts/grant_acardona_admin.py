from sqlalchemy import select

from app.authorization import has_application_access
from app.config import settings
from app.db import SessionLocal
from app.models import (
    AccessEvent,
    Application,
    User,
    UserApplicationAccess,
    UserEmail,
)


CURRENT_SUBJECT = "7359d45a-615a-4777-8ea0-0252da76ea52"
ACARDONA_SUBJECT = "6222abaf-b35a-4584-be2b-4514762f79dc"


def main() -> None:
    if settings.amh_db_name != "amh_dev":
        raise RuntimeError("Esta operación solo puede ejecutarse en amh_dev")

    with SessionLocal.begin() as db:
        current_admin = db.scalar(
            select(User).where(User.keycloak_subject == CURRENT_SUBJECT)
        )
        if current_admin is None or not has_application_access(
            db,
            user_id=current_admin.id,
            application_code="amh",
            minimum_role="admin",
        ):
            raise RuntimeError("No se encuentra el administrador actual")

        application = db.scalar(
            select(Application).where(Application.code == "amh")
        )
        if application is None:
            raise RuntimeError("No se encuentra la aplicación amh")

        target = db.scalar(
            select(User).where(
                User.keycloak_subject == ACARDONA_SUBJECT
            )
        )

        if target is None:
            print("acardona todavía no tiene registro en AMH.")
            name = input("Nombre de acardona: ").strip()
            surname = input("Apellidos de acardona: ").strip()
            email = input("Email principal de acardona: ").strip().lower()

            if not name or not surname:
                raise ValueError("Nombre y apellidos son obligatorios")
            if len(name) > 100 or len(surname) > 150:
                raise ValueError("Nombre o apellidos demasiado largos")
            if (
                not email
                or "@" not in email
                or any(c.isspace() for c in email)
                or len(email) > 320
            ):
                raise ValueError("Email no válido")

            if db.scalar(
                select(UserEmail.id).where(
                    UserEmail.email_normalized == email
                )
            ) is not None:
                raise RuntimeError(
                    "El email ya está asociado a otro usuario de AMH. "
                    "No se ha cambiado ninguna concesión."
                )

            target = User(
                keycloak_subject=ACARDONA_SUBJECT,
                name=name,
                surname=surname,
                is_blocked=False,
            )
            db.add(target)
            db.flush()

            db.add(
                UserEmail(
                    user_id=target.id,
                    kind="primary",
                    email=email,
                    email_normalized=email,
                    verified_at=None,
                )
            )

        if target.is_blocked:
            raise RuntimeError("La cuenta de acardona está bloqueada")

        access = db.scalar(
            select(UserApplicationAccess)
            .where(
                UserApplicationAccess.user_id == target.id,
                UserApplicationAccess.application_id == application.id,
            )
            .with_for_update()
        )

        if access is None:
            old_status = None
            old_role = None
            access = UserApplicationAccess(
                user_id=target.id,
                application_id=application.id,
                status="active",
                role="admin",
            )
            db.add(access)
            action = "granted"
        elif access.status == "active" and access.role == "admin":
            raise RuntimeError("acardona ya tiene amh/admin activo")
        else:
            old_status = access.status
            old_role = access.role
            access.status = "active"
            access.role = "admin"
            action = "restored" if old_status != "active" else "role_changed"

        db.flush()

        db.add(
            AccessEvent(
                access_id=access.id,
                actor_kind="system",
                action=action,
                old_status=old_status,
                new_status="active",
                old_role=old_role,
                new_role="admin",
                reason="Transferencia inicial de administración a acardona",
            )
        )
        target_id = target.id

    print(f"Acceso amh/admin concedido a acardona: {target_id}")
    print("El acceso de inaranjo sigue activo por ahora")


if __name__ == "__main__":
    main()