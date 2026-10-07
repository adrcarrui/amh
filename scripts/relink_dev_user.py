from uuid import UUID

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import User, UserEmail, UserSession


AMH_USER_ID = UUID("55ea5fbe-bb64-4735-91d9-8584c241b180")
KEYCLOAK_SUBJECT = "19b1b845-55e9-4754-8a19-6e06c4f2c99d"


def main() -> None:
    if settings.amh_db_name != "amh_dev":
        raise RuntimeError("Este ajuste solo se permite en amh_dev")

    expected_email = input(
        "Email principal de la persona, para verificar el registro AMH: "
    ).strip().lower()

    if not expected_email:
        raise RuntimeError("Debes introducir el email esperado")

    with SessionLocal.begin() as db:
        user = db.scalar(
            select(User)
            .where(User.id == AMH_USER_ID)
            .with_for_update()
        )
        if user is None:
            raise RuntimeError("No existe ese ID de usuario AMH")

        email = db.scalar(
            select(UserEmail.email_normalized).where(
                UserEmail.user_id == AMH_USER_ID,
                UserEmail.kind == "primary",
            )
        )
        if email != expected_email:
            raise RuntimeError(
                "El email no coincide con el usuario AMH. No se ha cambiado nada."
            )

        other_user = db.scalar(
            select(User).where(
                User.keycloak_subject == KEYCLOAK_SUBJECT,
                User.id != AMH_USER_ID,
            )
        )
        if other_user is not None:
            raise RuntimeError(
                "El ID de Keycloak ya pertenece a otro usuario AMH"
            )

        session_count = db.scalar(
            select(func.count())
            .select_from(UserSession)
            .where(UserSession.user_id == AMH_USER_ID)
        )
        if session_count:
            raise RuntimeError(
                "El usuario ya tiene sesiones AMH; revisar antes de cambiarlo"
            )

        previous_subject = user.keycloak_subject
        user.keycloak_subject = KEYCLOAK_SUBJECT
        db.flush()

    print("Vínculo corregido.")
    print("Usuario AMH:", AMH_USER_ID)
    print("Keycloak anterior:", previous_subject)
    print("Keycloak nuevo:", KEYCLOAK_SUBJECT)


if __name__ == "__main__":
    main()