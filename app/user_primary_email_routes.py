import logging
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db import SessionLocal
from app.keycloak_admin import _service_token, _users_url
from app.models import UserEmail
from app.user_contact_routes import get_authorized_user


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/users",
    tags=["user-contact"],
)


class PrimaryEmailChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_email: EmailStr = Field(max_length=320)

    # El correo que estaba viendo el administrador.
    # Evita sobrescribir un cambio guardado desde otra ventana.
    expected_primary_email: EmailStr | None = Field(
        max_length=320,
    )

    @field_validator(
        "primary_email",
        "expected_primary_email",
        mode="before",
    )
    @classmethod
    def clean_email(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value


def normalized_email(value: str | None) -> str:
    return (value or "").strip().lower()


def uncertain_result() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "No se pudo confirmar el resultado completo del cambio. "
            "Keycloak podria haber actualizado el correo. "
            "Revisa el correo en AMH y Keycloak antes de reintentar."
        ),
    )


def synchronize_keycloak_email(
    *,
    subject: str,
    previous_email: str | None,
    new_email: str,
) -> None:
    user_url = (
        f"{_users_url()}/"
        f"{quote(subject, safe='')}"
    )

    with httpx.Client(
        timeout=10.0,
        trust_env=False,
    ) as client:
        # Estas operaciones solo consultan datos.
        try:
            token = _service_token(client)

            headers = {
                "Authorization": f"Bearer {token}",
            }

            response = client.get(
                user_url,
                headers=headers,
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "No se pudo consultar Keycloak. "
                    "El correo no se ha cambiado en AMH."
                ),
            ) from exc

        if response.status_code == 404:
            raise HTTPException(
                status_code=409,
                detail=(
                    "La identidad enlazada no existe en Keycloak. "
                    "Revisa el enlace antes de cambiar el correo."
                ),
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=(
                    "No se pudo consultar el usuario en Keycloak: "
                    f"HTTP {response.status_code}. "
                    "El correo no se ha cambiado en AMH."
                ),
            )

        try:
            representation = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Keycloak devolvio una respuesta no valida.",
            ) from exc

        if not isinstance(representation, dict):
            raise HTTPException(
                status_code=502,
                detail="Keycloak devolvio una respuesta no valida.",
            )

        remote_email = representation.get("email")

        if remote_email is not None and not isinstance(
            remote_email,
            str,
        ):
            raise HTTPException(
                status_code=502,
                detail="Keycloak devolvio un correo no valido.",
            )

        remote_normalized = normalized_email(remote_email)
        previous_normalized = normalized_email(previous_email)
        new_normalized = normalized_email(new_email)

        # Permite completar un cambio cuyo resultado anterior
        # quedo incierto, si Keycloak ya tiene el correo solicitado.
        if remote_email == new_email:
            return

        if remote_normalized not in {
            previous_normalized,
            new_normalized,
        }:
            raise HTTPException(
                status_code=409,
                detail=(
                    "El correo principal de Keycloak no coincide "
                    "con el registrado en AMH. "
                    "Revisa ambos sistemas antes de continuar."
                ),
            )

        # Conserva los datos de perfil existentes.
        payload = {
            key: representation[key]
            for key in (
                "username",
                "firstName",
                "lastName",
                "attributes",
            )
            if key in representation
        }

        payload["email"] = new_email
        payload["emailVerified"] = False

        try:
            response = client.put(
                user_url,
                headers=headers,
                json=payload,
            )
        except httpx.RequestError as exc:
            # Una desconexion no permite saber si Keycloak
            # llego a aplicar el cambio.
            logger.warning(
                "Resultado incierto al actualizar correo en Keycloak: %s",
                subject,
            )
            raise uncertain_result() from exc

        if response.status_code == 204:
            return

        if response.status_code == 409:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Keycloak ha rechazado el cambio por un conflicto. "
                    "Comprueba si el correo pertenece a otra cuenta."
                ),
            )

        if response.status_code == 400:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Keycloak ha rechazado los datos del correo. "
                    "Revisa las reglas del perfil del usuario."
                ),
            )

        if response.status_code in {401, 403}:
            raise HTTPException(
                status_code=502,
                detail=(
                    "La cuenta de servicio de AMH no puede "
                    "modificar este usuario en Keycloak."
                ),
            )

        if response.status_code == 404:
            raise HTTPException(
                status_code=409,
                detail="El usuario ya no existe en Keycloak.",
            )

        # Un error del servidor puede producirse despues
        # de aplicar la escritura. No se presupone un rollback.
        logger.warning(
            "Respuesta inesperada al actualizar Keycloak: %s HTTP %s",
            subject,
            response.status_code,
        )
        raise uncertain_result()


def update_primary_email(
    session_token: str | None,
    user_id: UUID,
    data: PrimaryEmailChange,
):
    keycloak_ready = False

    try:
        with SessionLocal.begin() as db:
            user = get_authorized_user(
                db,
                session_token,
                user_id,
                lock=True,
            )

            primary = db.scalar(
                select(UserEmail)
                .where(
                    UserEmail.user_id == user_id,
                    UserEmail.kind == "primary",
                )
                .with_for_update()
            )

            current_email = (
                primary.email
                if primary is not None
                else None
            )

            expected_email = (
                str(data.expected_primary_email)
                if data.expected_primary_email is not None
                else None
            )

            if normalized_email(current_email) != normalized_email(
                expected_email
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "El correo principal ha cambiado desde que "
                        "abriste la ficha. Recarga la pagina "
                        "antes de volver a editarlo."
                    ),
                )

            new_email = str(data.primary_email).strip()
            new_normalized = new_email.lower()

            collision_id = db.scalar(
                select(UserEmail.id).where(
                    UserEmail.email_normalized == new_normalized
                )
            )

            if collision_id is not None and (
                primary is None or collision_id != primary.id
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Ese correo ya esta registrado como principal "
                        "o alternativo en AMH. "
                        "Utiliza un correo diferente."
                    ),
                )

            if not user.keycloak_subject:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "El usuario no tiene una identidad de Keycloak "
                        "enlazada. Revisa su identidad antes de "
                        "cambiar el correo principal."
                    ),
                )

            changed = current_email != new_email

            if primary is None:
                primary = UserEmail(
                    user_id=user_id,
                    kind="primary",
                    email=new_email,
                    email_normalized=new_normalized,
                    verified_at=None,
                )
                db.add(primary)

            elif changed:
                primary.email = new_email
                primary.email_normalized = new_normalized
                primary.verified_at = None

            if changed:
                user.updated_at = datetime.now(timezone.utc)

            # Comprueba las restricciones locales antes
            # de solicitar una escritura en Keycloak.
            db.flush()

            synchronize_keycloak_email(
                subject=user.keycloak_subject,
                previous_email=current_email,
                new_email=new_email,
            )

            keycloak_ready = True

        # Solo se devuelve exito tras confirmar la transaccion.
        return {
            "saved": True,
            "primary_email": new_email,
        }

    except SQLAlchemyError as exc:
        if keycloak_ready:
            # La conexion podria fallar durante commit incluso
            # despues de que PostgreSQL haya confirmado.
            # No se restaura Keycloak a ciegas.
            logger.exception(
                "No se pudo confirmar el correo principal en AMH: %s",
                user_id,
            )
            raise uncertain_result() from exc

        if isinstance(exc, IntegrityError):
            raise HTTPException(
                status_code=409,
                detail="Ese correo ya esta registrado en AMH.",
            ) from None

        logger.exception(
            "Error de base de datos al preparar cambio de correo: %s",
            user_id,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "No se pudo preparar el cambio en AMH. "
                "No se ha solicitado el cambio a Keycloak."
            ),
        ) from exc


@router.patch("/{user_id}/contact/primary")
async def patch_primary_email(
    user_id: UUID,
    data: PrimaryEmailChange,
    request: Request,
):
    redirect = urlsplit(settings.amh_oidc_redirect_uri)

    allowed_origins = {
        f"{redirect.scheme}://{redirect.netloc}",
        "http://127.0.0.1:5174",
    }

    if request.headers.get("origin") not in allowed_origins:
        raise HTTPException(
            status_code=403,
            detail="Origen no permitido",
        )

    result = await run_in_threadpool(
        update_primary_email,
        request.cookies.get("amh_session"),
        user_id,
        data,
    )

    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store"},
    )