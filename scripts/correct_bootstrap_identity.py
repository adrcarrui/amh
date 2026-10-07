from datetime import datetime, timezone
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
    UserSession,
)


AMH_USER_ID = UUID("24307b6d-e337-49dd-986e-79e0fa775a7a")
OLD_SUBJECT = "7359d45a-615a-4777-8ea0-0252da76ea52"
NEW_SUBJECT = "6222abaf-b35a-4584-be2b-4514762f79dc"


def main() -> None:
    if settings.amh_db_name != "amh_dev":
        raise RuntimeError("Solo se permite corregir amh_dev")

    expected_email = input(
        "Email principal de Adrián para comprobar el registro: "
    ).strip().lower()

    if not expected_email:
        raise ValueError("El email es obligatorio")

    with SessionLocal.begin() as db:
        user = db.scalar(
            select(User)
            .where(User.id == AMH_USER_ID)
            .with_for_update()
        )
        if user is None or user.keycloak_subject != OLD_SUBJECT:
            raise RuntimeError(
                "El usuario o el vínculo antiguo no coinciden"
            )

        if (
            user.name.strip().casefold() != "adrián".casefold()
            or user.surname.strip().casefold()
            != "cardona ruiz".casefold()
        ):
            raise RuntimeError(
                "El nombre del registro no coincide con Adrián Cardona Ruiz"
            )

        email = db.scalar(
            select(UserEmail).where(
                UserEmail.user_id == user.id,
                UserEmail.kind == "primary",
            )
        )
        if (
            email is None
            or email.email_normalized != expected_email
        ):
            raise RuntimeError(
                "El email principal no pertenece a este registro"
            )

        if db.scalar(
            select(User.id).where(
                User.keycloak_subject == NEW_SUBJECT
            )
        ) is not None:
            raise RuntimeError(
                "El subject de acardona ya está vinculado a otro usuario"
            )

        application = db.scalar(
            select(Application).where(Application.code == "amh")
        )
        if application is None:
            raise RuntimeError("No existe la aplicación amh")

        access = db.scalar(
            select(UserApplicationAccess).where(
                UserApplicationAccess.user_id == user.id,
                UserApplicationAccess.application_id == application.id,
            )
        )
        if (
            access is None
            or access.status != "active"
            or access.role != "admin"
        ):
            raise RuntimeError(
                "No se encuentra la concesión amh/admin esperada"
            )

        now = datetime.now(timezone.utc)

        sessions = db.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
            )
            .with_for_update()
        ).all()
        for session in sessions:
            session.revoked_at = now

        user.keycloak_subject = NEW_SUBJECT

        db.add(
            AccessEvent(
                access_id=access.id,
                actor_kind="system",
                action="identity_link_corrected",
                old_status="active",
                new_status="active",
                old_role="admin",
                new_role="admin",
                reason=(
                    "Corrección del vínculo Keycloak del alta inicial: "
                    f"{OLD_SUBJECT} -> {NEW_SUBJECT}"
                ),
            )
        )

    print(f"Vínculo corregido para el usuario AMH {AMH_USER_ID}")
    print(f"Sesiones anteriores revocadas: {len(sessions)}")


if __name__ == "__main__":
    main()