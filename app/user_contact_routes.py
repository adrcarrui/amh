from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID

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
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db import SessionLocal
from app.models import User, UserEmail
from app.session_service import get_admin_session_user_id


router = APIRouter(
    prefix="/api/v1/admin/users",
    tags=["user-contact"],
)


class SecondaryEmailChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secondary_email: EmailStr | None = Field(max_length=320)

    @field_validator("secondary_email", mode="before")
    @classmethod
    def clean_email(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value


def get_authorized_user(
    db,
    session_token: str | None,
    user_id: UUID,
    *,
    lock: bool = False,
):
    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="Sesion AMH no iniciada",
        )

    if get_admin_session_user_id(db, token=session_token) is None:
        raise HTTPException(
            status_code=401,
            detail="Sesion AMH no valida o permiso admin requerido",
        )

    query = select(User).where(User.id == user_id)

    if lock:
        query = query.with_for_update()

    user = db.scalar(query)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Usuario no encontrado",
        )

    return user


def read_contact(session_token: str | None, user_id: UUID):
    with SessionLocal.begin() as db:
        get_authorized_user(db, session_token, user_id)

        emails = dict(
            db.execute(
                select(UserEmail.kind, UserEmail.email).where(
                    UserEmail.user_id == user_id
                )
            ).all()
        )

        # Consulta solo si existe contenido, nunca el token.
        token_configured = db.scalar(
            select(
                User.mysim_token_encrypted.is_not(None)
            ).where(User.id == user_id)
        )

        return {
            "user_id": str(user_id),
            "primary_email": emails.get("primary"),
            "secondary_email": emails.get("secondary"),
            "mysim_token_configured": bool(token_configured),
        }


def update_secondary_email(
    session_token: str | None,
    user_id: UUID,
    data: SecondaryEmailChange,
):
    with SessionLocal.begin() as db:
        user = get_authorized_user(
            db,
            session_token,
            user_id,
            lock=True,
        )

        secondary = db.scalar(
            select(UserEmail).where(
                UserEmail.user_id == user_id,
                UserEmail.kind == "secondary",
            )
        )

        if data.secondary_email is None:
            if secondary is not None:
                db.delete(secondary)
                user.updated_at = datetime.now(timezone.utc)
                db.flush()

            return {"saved": True}

        email = str(data.secondary_email).strip()
        normalized = email.lower()

        collision_id = db.scalar(
            select(UserEmail.id).where(
                UserEmail.email_normalized == normalized
            )
        )

        if collision_id is not None and (
            secondary is None or collision_id != secondary.id
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Ese correo ya esta registrado como principal "
                    "o alternativo en AMH"
                ),
            )

        if secondary is None:
            db.add(
                UserEmail(
                    user_id=user_id,
                    kind="secondary",
                    email=email,
                    email_normalized=normalized,
                    verified_at=None,
                )
            )
            user.updated_at = datetime.now(timezone.utc)

        elif secondary.email != email:
            if secondary.email_normalized != normalized:
                secondary.verified_at = None

            secondary.email = email
            secondary.email_normalized = normalized
            user.updated_at = datetime.now(timezone.utc)

        db.flush()

        return {"saved": True}


@router.get("/{user_id}/contact")
async def get_user_contact(user_id: UUID, request: Request):
    result = await run_in_threadpool(
        read_contact,
        request.cookies.get("amh_session"),
        user_id,
    )

    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store"},
    )


@router.patch("/{user_id}/contact")
async def patch_user_contact(
    user_id: UUID,
    data: SecondaryEmailChange,
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
            update_secondary_email,
            request.cookies.get("amh_session"),
            user_id,
            data,
        )
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Ese correo ya esta registrado en AMH",
        ) from None

    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store"},
    )