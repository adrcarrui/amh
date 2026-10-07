from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Application, User, UserApplicationAccess
from app.session_service import create_application_session


router = APIRouter(prefix="/api/v1/access", tags=["application-access"])


async def _verified_oidc_identity(request: Request) -> tuple[str, str]:
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")

    if (
        scheme.lower() != "bearer"
        or not separator
        or not token
        or any(character.isspace() for character in token)
    ):
        raise HTTPException(
            status_code=401,
            detail="Access token requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    introspection_url = (
        f"{settings.amh_oidc_issuer.rstrip('/')}"
        "/protocol/openid-connect/token/introspect"
    )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            keycloak_response = await client.post(
                introspection_url,
                data={"token": token},
                auth=(
                    settings.amh_api_client_id,
                    settings.amh_api_client_secret.get_secret_value(),
                ),
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="Servicio de identidad no disponible",
        ) from exc

    if keycloak_response.status_code != 200:
        raise HTTPException(
            status_code=503,
            detail="No se pudo verificar el token",
        )

    try:
        claims = keycloak_response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail="Respuesta de identidad no válida",
        ) from exc

    if not isinstance(claims, dict) or claims.get("active") is not True:
        raise HTTPException(status_code=401, detail="Token no válido")

    audience = claims.get("aud")
    audiences = [audience] if isinstance(audience, str) else audience

    if (
        not isinstance(audiences, list)
        or settings.amh_api_client_id not in audiences
        or claims.get("iss") != settings.amh_oidc_issuer.rstrip("/")
        or claims.get("typ") != "Bearer"
    ):
        raise HTTPException(status_code=401, detail="Token no válido")

    subject = claims.get("sub")
    client_id = claims.get("azp")

    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(client_id, str)
        or not client_id
    ):
        raise HTTPException(status_code=401, detail="Token no válido")

    return subject, client_id


def _find_access(db: Session, subject: str, client_id: str):
    return db.execute(
        select(
            User.id,
            Application.code,
            UserApplicationAccess.role,
        )
        .join(
            UserApplicationAccess,
            UserApplicationAccess.user_id == User.id,
        )
        .join(
            Application,
            Application.id == UserApplicationAccess.application_id,
        )
        .where(
            User.keycloak_subject == subject,
            User.is_blocked.is_(False),
            Application.oidc_client_id == client_id,
            Application.is_enabled.is_(True),
            UserApplicationAccess.status == "active",
        )
    ).one_or_none()


def _read_access(subject: str, client_id: str):
    with SessionLocal() as db:
        return _find_access(db, subject, client_id)


@router.get("/me")
async def my_application_access(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"

    subject, client_id = await _verified_oidc_identity(request)
    access = await run_in_threadpool(_read_access, subject, client_id)

    if access is None:
        raise HTTPException(status_code=403, detail="Acceso no concedido")

    user_id, application_code, role = access
    return {
        "user_id": user_id,
        "application_code": application_code,
        "role": role,
    }


def _create_session(subject: str, client_id: str):
    with SessionLocal.begin() as db:
        access = _find_access(db, subject, client_id)
        if access is None:
            return None

        user_id, application_code, role = access

        # El login administrativo de AMH conserva su flujo propio.
        if application_code == "amh":
            return None

        session_token = create_application_session(
            db,
            user_id=user_id,
            application_code=application_code,
        )

        return {
            "session_token": session_token,
            "user_id": user_id,
            "application_code": application_code,
            "role": role,
        }


@router.post("/sessions", status_code=201)
async def issue_application_session(
    request: Request,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"

    subject, client_id = await _verified_oidc_identity(request)

    try:
        result = await run_in_threadpool(
            _create_session,
            subject,
            client_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail="Acceso no concedido",
        ) from exc

    if result is None:
        raise HTTPException(status_code=403, detail="Acceso no concedido")

    return result