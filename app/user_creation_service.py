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
from app.models import User, UserEmail


def create_managed_user(
    *,
    actor_user_id: UUID,
    username: str,
    name: str,
    surname: str,
    email: str,
) -> tuple[UUID, str]:
    """Crea la identidad y devuelve (ID AMH, contraseña temporal)."""
    username = username.strip()
    name = name.strip()
    surname = surname.strip()
    email = email.strip()
    normalized_email = email.lower()

    if not all((username, name, surname, email)):
        raise ValueError("Todos los campos son obligatorios")

    # Comprobación previa: evita llamar a Keycloak cuando AMH ya
    # conoce ese email. La restricción UNIQUE sigue protegiendo carreras.
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

    # No se guarda en AMH. Se mostrará al administrador una sola vez.
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
            # El permiso puede haber cambiado mientras Keycloak respondía.
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
            db.flush()
            amh_user_id = user.id

    except (IntegrityError, PermissionError):
        # En estos casos sabemos que la transacción AMH no se confirmó.
        delete_newly_created_keycloak_user(keycloak_user_id)
        raise

    except Exception as exc:
        # Un error de conexión durante commit podría ocurrir después
        # de que PostgreSQL haya confirmado. No borramos a ciegas.
        raise RuntimeError(
            "No se pudo confirmar el alta en AMH. Revisa el usuario "
            f"de Keycloak {keycloak_user_id} antes de reintentar."
        ) from exc

    return amh_user_id, temporary_password