from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.db import SessionLocal
from app.models.user import User
from app.session_service import (
    get_application_session_access,
    revoke_application_session,
)

router = APIRouter(prefix="/api/v1/access/sessions", tags=["sessions"])


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Sesión requerida",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token.strip()


def _check_session(token: str, application_code: str, include_profile: bool):
    with SessionLocal.begin() as db:
        access = get_application_session_access(
            db,
            token=token,
            application_code=application_code,
        )
        if access is None:
            return None

        user_id, role = access
        result = {
            "user_id": user_id,
            "application_code": application_code,
            "role": role,
        }
        if include_profile:
            profile = db.execute(
                select(User.name, User.surname).where(User.id == user_id)
            ).one_or_none()
            display_name = None
            if profile is not None:
                name, surname = profile
                display_name = f"{name.strip()} {surname.strip()}".strip() or None
            result["display_name"] = display_name

        return result


@router.get("/{application_code}")
async def check_application_session(
    application_code: str,
    request: Request,
    include_profile: bool = False,
):
    token = _bearer_token(request)
    result = await run_in_threadpool(
        _check_session,
        token,
        application_code,
        include_profile,
    )

    if result is None:
        raise HTTPException(status_code=401, detail="Sesión no válida")

    return result


def _revoke_session(token: str, application_code: str) -> None:
    with SessionLocal.begin() as db:
        revoke_application_session(
            db,
            token=token,
            application_code=application_code,
        )


@router.delete("/{application_code}", status_code=204)
async def logout_application_session(
    application_code: str,
    request: Request,
):
    token = _bearer_token(request)
    await run_in_threadpool(
        _revoke_session,
        token,
        application_code,
    )
    return Response(status_code=204)