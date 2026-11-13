import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.authorization import has_application_access
from app.db import SessionLocal
from app.keycloak_admin import (
    create_keycloak_user,
    delete_newly_created_keycloak_user,
)
from app.models import User, UserEmail, UserATurnosLink
from app.models.aturnos_import_event import ATurnosImportEvent

def create_managed_user(
    *,
    actor_user_id: UUID,
    username: str,
    name: str,
    surname: str,
    email: str,
    aturnos_team_id: str | None = None,
    aturnos_user_id: str | None = None,
) -> tuple[UUID, str]:
    """Crea la identidad y devuelve (ID AMH, contraseña temporal)."""
    username = username.strip()
    name = name.strip()
    surname = surname.strip()
    email = email.strip()
    normalized_email = email.lower()

    if not all((username, name, surname, email)):
        raise ValueError("Todos los campos son obligatorios")

    if len(name) > 100 or len(surname) > 150 or len(email) > 320:
        raise ValueError("Nombre, apellidos o email demasiado largos")

    # Los identificadores externos se proporcionan juntos.
    if (aturnos_team_id is None) != (aturnos_user_id is None):
        raise ValueError(
            "Deben indicarse tanto el equipo como el usuario de aTurnos"
        )

    has_aturnos_link = aturnos_team_id is not None

    if has_aturnos_link:
        aturnos_team_id = str(aturnos_team_id).strip()
        aturnos_user_id = str(aturnos_user_id).strip()

        if not all(
            value.isascii()
            and value.isdecimal()
            and len(value) <= 64
            and int(value) > 0
            for value in (aturnos_team_id, aturnos_user_id)
        ):
            raise ValueError("Identificadores de aTurnos no válidos")

    with SessionLocal.begin() as db:
        if not has_application_access(
            db,
            user_id=actor_user_id,
            application_code="amh",
            minimum_role="admin",
        ):
            raise PermissionError("Se requiere el rol admin de AMH")

        existing = db.scalar(
            select(UserEmail.id).where(
                UserEmail.email_normalized == normalized_email
            )
        )
        if existing is not None:
            raise ValueError("El email ya está registrado en AMH")

        if has_aturnos_link:
            existing_link = db.scalar(
                select(UserATurnosLink.id).where(
                    UserATurnosLink.id_aturno == aturnos_team_id,
                    UserATurnosLink.id_user == aturnos_user_id,
                )
            )
            if existing_link is not None:
                raise ValueError(
                    "El usuario de aTurnos ya está enlazado en AMH"
                )

    # No se guarda en AMH.
    temporary_password = "Aa1!" + secrets.token_urlsafe(24)

    keycloak_user_id = create_keycloak_user(
        username=username,
        name=name,
        surname=surname,
        email=email,
        temporary_password=temporary_password,
    )

    try:
        with SessionLocal.begin() as db:
            if not has_application_access(
                db,
                user_id=actor_user_id,
                application_code="amh",
                minimum_role="admin",
            ):
                raise PermissionError("Se revocó el permiso admin de AMH")

            user = User(
                keycloak_subject=str(keycloak_user_id),
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
                    email_normalized=normalized_email,
                )
            )

            if has_aturnos_link:
                db.add(
                    UserATurnosLink(
                        user_id=user.id,
                        id_aturno=aturnos_team_id,
                        id_user=aturnos_user_id,
                    )
                )

                db.add(
                    ATurnosImportEvent(
                        user_id=user.id,
                        actor_user_id=actor_user_id,
                        id_aturno=aturnos_team_id,
                        id_user=aturnos_user_id,
                    )
                )

            db.flush()
            amh_user_id = user.id

    except (IntegrityError, PermissionError):
        # La transacción AMH no se confirmó.
        delete_newly_created_keycloak_user(keycloak_user_id)
        raise

    except Exception as exc:
        # Si el resultado del commit es incierto, no borramos
        # la identidad de Keycloak sin comprobar PostgreSQL.
        raise RuntimeError(
            "No se pudo confirmar el alta en AMH. Revisa el usuario "
            f"de Keycloak {keycloak_user_id} antes de reintentar."
        ) from exc

    return amh_user_id, temporary_password