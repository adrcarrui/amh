from uuid import UUID

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import (
    AccessEvent,
    Application,
    User,
    UserApplicationAccess,
    UserEmail,
)


KEYCLOAK_SUBJECT = str(
    UUID("7359d45a-615a-4777-8ea0-0252da76ea52")
)


def main() -> None:
    if settings.amh_db_name != "amh_dev":
        raise RuntimeError(
            f"Bootstrap cancelado: la base configurada es {settings.amh_db_name!r}"
        )

    if settings.amh_oidc_client_id != "amh_admin_dev":
        raise RuntimeError("Bootstrap cancelado: cliente OIDC inesperado")

    name = input("Nombre: ").strip()
    surname = input("Apellidos: ").strip()
    email = input("Email principal: ").strip().lower()

    if not name or not surname:
        raise ValueError("Nombre y apellidos son obligatorios")
    if len(name) > 100 or len(surname) > 150:
        raise ValueError("Nombre o apellidos demasiado largos")
    if not email or "@" not in email or any(c.isspace() for c in email):
        raise ValueError("Email no válido")
    if len(email) > 320:
        raise ValueError("Email demasiado largo")

    with SessionLocal.begin() as db:
        application = db.scalar(
            select(Application).where(Application.code == "amh")
        )

        if application is None:
            application = Application(
                code="amh",
                display_name="Access Management Hub",
                oidc_client_id=settings.amh_oidc_client_id,
                is_enabled=True,
            )
            db.add(application)
            db.flush()
        elif application.oidc_client_id not in (
            None,
            settings.amh_oidc_client_id,
        ):
            raise RuntimeError(
                "La aplicación amh tiene otro oidc_client_id"
            )
        elif application.oidc_client_id is None:
            application.oidc_client_id = settings.amh_oidc_client_id
            db.flush()

        existing_access = db.scalar(
            select(UserApplicationAccess.id)
            .where(UserApplicationAccess.application_id == application.id)
            .limit(1)
        )
        if existing_access is not None:
            raise RuntimeError(
                "Ya existen concesiones para amh; no ejecutar el bootstrap"
            )

        existing_user = db.scalar(
            select(User.id)
            .where(User.keycloak_subject == KEYCLOAK_SUBJECT)
        )
        if existing_user is not None:
            raise RuntimeError(
                "Ya existe un usuario asociado a este subject de Keycloak"
            )

        existing_email = db.scalar(
            select(UserEmail.id)
            .where(UserEmail.email_normalized == email)
        )
        if existing_email is not None:
            raise RuntimeError("Ese email ya está registrado")

        user = User(
            keycloak_subject=KEYCLOAK_SUBJECT,
            name=name,
            surname=surname,
            is_blocked=False,
        )
        db.add(user)
        db.flush()

        db.add(
            UserEmail(
                user_id=user.id,
                kind="primary",
                email=email,
                email_normalized=email,
                verified_at=None,
            )
        )

        access = UserApplicationAccess(
            user_id=user.id,
            application_id=application.id,
            status="active",
            role="admin",
        )
        db.add(access)
        db.flush()

        db.add(
            AccessEvent(
                access_id=access.id,
                actor_kind="system",
                action="granted",
                old_status=None,
                new_status="active",
                old_role=None,
                new_role="admin",
                reason="Bootstrap inicial del primer administrador de AMH",
            )
        )

        user_id = user.id

    print(f"Administrador AMH creado: {user_id}")
    print("Concesión amh/admin y evento de auditoría registrados")


if __name__ == "__main__":
    main()