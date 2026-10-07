from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.db import SessionLocal
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


def _check_session(token: str, application_code: str):
    with SessionLocal.begin() as db:
        return get_application_session_access(
            db,
            token=token,
            application_code=application_code,
        )


@router.get("/{application_code}")
async def check_application_session(
    application_code: str,
    request: Request,
):
    token = _bearer_token(request)
    result = await run_in_threadpool(
        _check_session,
        token,
        application_code,
    )

    if result is None:
        raise HTTPException(status_code=401, detail="Sesión no válida")

    user_id, role = result
    return {
        "user_id": user_id,
        "application_code": application_code,
        "role": role,
    }


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