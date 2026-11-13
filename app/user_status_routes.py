import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db import SessionLocal
from app.models import (
    Application,
    User,
    UserApplicationAccess,
    UserSession,
)
from app.models.user_status_event import UserStatusEvent
from app.session_service import get_admin_session_user_id


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/users",
    tags=["user-status"],
)


class UserStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_blocked: StrictBool
    expected_is_blocked: StrictBool
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value


def change_user_status(
    session_token: str | None,
    user_id: UUID,
    data: UserStatusChange,
):
    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="Sesion AMH no iniciada",
        )

    with SessionLocal.begin() as db:
        # Serializa los bloqueos y desbloqueos.
        # Se adquiere antes de bloquear la sesion del administrador.
        db.execute(
            text(
                "SELECT pg_advisory_xact_lock(109558381, 1)"
            )
        )

        actor_id = get_admin_session_user_id(
            db,
            token=session_token,
        )

        if actor_id is None:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Sesion AMH no valida "
                    "o permiso admin requerido"
                ),
            )

        user = db.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="Usuario no encontrado",
            )

        if data.is_blocked and user_id == actor_id:
            raise HTTPException(
                status_code=400,
                detail="No puedes bloquearte a ti mismo.",
            )

        if user.is_blocked != data.expected_is_blocked:
            raise HTTPException(
                status_code=409,
                detail=(
                    "El estado del usuario ha cambiado. "
                    "Recarga la ficha antes de continuar."
                ),
            )

        if user.is_blocked == data.is_blocked:
            raise HTTPException(
                status_code=409,
                detail="El usuario ya tiene ese estado.",
            )

        if data.is_blocked:
            target_is_admin = db.scalar(
                select(UserApplicationAccess.id)
                .join(
                    Application,
                    Application.id
                    == UserApplicationAccess.application_id,
                )
                .where(
                    UserApplicationAccess.user_id == user_id,
                    UserApplicationAccess.role == "admin",
                    UserApplicationAccess.status == "active",
                    Application.code == "amh",
                    Application.is_enabled.is_(True),
                )
            )

            if target_is_admin is not None:
                other_admins = db.scalar(
                    select(func.count())
                    .select_from(UserApplicationAccess)
                    .join(
                        User,
                        User.id
                        == UserApplicationAccess.user_id,
                    )
                    .join(
                        Application,
                        Application.id
                        == UserApplicationAccess.application_id,
                    )
                    .where(
                        User.id != user_id,
                        User.is_blocked.is_(False),
                        UserApplicationAccess.role == "admin",
                        UserApplicationAccess.status == "active",
                        Application.code == "amh",
                        Application.is_enabled.is_(True),
                    )
                )

                if not other_admins:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "No se puede bloquear al ultimo "
                            "administrador disponible de AMH."
                        ),
                    )

        now = datetime.now(timezone.utc)
        old_is_blocked = user.is_blocked
        revoked_sessions = 0

        user.is_blocked = data.is_blocked
        user.updated_at = now

        if data.is_blocked:
            # Revoca todas las sesiones emitidas por AMH:
            # portal y sesiones de aplicaciones.
            result = db.execute(
                update(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
                .execution_options(synchronize_session=False)
            )

            revoked_sessions = result.rowcount

        db.add(
            UserStatusEvent(
                user_id=user_id,
                actor_user_id=actor_id,
                old_is_blocked=old_is_blocked,
                new_is_blocked=data.is_blocked,
                reason=data.reason,
                revoked_sessions=revoked_sessions,
            )
        )

        db.flush()

        result_data = {
            "saved": True,
            "user_id": str(user_id),
            "is_blocked": data.is_blocked,
            "revoked_sessions": revoked_sessions,
        }

    # Solo devuelve exito despues del commit.
    return result_data


@router.patch("/{user_id}/status")
async def patch_user_status(
    user_id: UUID,
    data: UserStatusChange,
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

    try:
        result = await run_in_threadpool(
            change_user_status,
            request.cookies.get("amh_session"),
            user_id,
            data,
        )
    except SQLAlchemyError:
        logger.exception(
            "No se pudo confirmar el estado del usuario %s",
            user_id,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "No se pudo confirmar el cambio de estado. "
                "Recarga la ficha para comprobarlo "
                "antes de volver a intentarlo."
            ),
        ) from None

    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store"},
    )