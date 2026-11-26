import hashlib
import hmac
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db import SessionLocal
from app.nfc_login_service import (
    consume_nfc_login_attempt,
    create_nfc_login_attempt,
)
from app.session_service import create_portal_session


FLOW_COOKIE = "amh_portal_nfc_flow"
FLOW_PATH = "/auth/nfc"

SESSION_COOKIE = "amh_session"
SESSION_MAX_AGE = 8 * 60 * 60
FLOW_MAX_AGE = 90

issuer = urlsplit(settings.amh_oidc_issuer)

KEYCLOAK_ORIGIN = (
    f"{issuer.scheme}://{issuer.netloc}"
)

ALLOWED_ORIGINS = {
    KEYCLOAK_ORIGIN,
    "http://127.0.0.1:5174",
}

COOKIE_SECURE = (
    urlsplit(settings.amh_oidc_redirect_uri).scheme
    == "https"
)


portal_nfc_app = FastAPI(
    title="AMH portal NFC",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

portal_nfc_app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
    allow_credentials=True,
)


class FinishPortalNfc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge: str = Field(
        min_length=43,
        max_length=43,
        pattern=r"^[A-Za-z0-9_-]{43}$",
    )


def _require_origin(request: Request) -> None:
    if request.headers.get("origin") not in ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail="Origen no permitido",
        )


def _browser_proof(challenge: str) -> str:
    secret = (
        settings.amh_oidc_state_secret.get_secret_value()
    )

    return hmac.new(
        secret.encode("utf-8"),
        (
            "amh-portal-nfc:" + challenge
        ).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _start() -> str:
    with SessionLocal.begin() as db:
        return create_nfc_login_attempt(
            db,
            application_code="amh",
        )


def _finish(challenge: str):
    with SessionLocal.begin() as db:
        user_id = consume_nfc_login_attempt(
            db,
            challenge=challenge,
            application_code="amh",
        )

        session_token = create_portal_session(
            db,
            user_id=user_id,
            auth_method="nfc",
        )

    return user_id, session_token


@portal_nfc_app.post("/start")
async def start_portal_nfc(request: Request):
    _require_origin(request)

    try:
        challenge = await run_in_threadpool(_start)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "El acceso NFC de AMH no esta disponible"
            ),
        ) from exc

    response = JSONResponse(
        {
            "challenge": challenge,
            "expires_in_seconds": FLOW_MAX_AGE,
        },
        headers={"Cache-Control": "no-store"},
    )

    response.set_cookie(
        key=FLOW_COOKIE,
        value=_browser_proof(challenge),
        max_age=FLOW_MAX_AGE,
        path=FLOW_PATH,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )

    return response


@portal_nfc_app.post("/finish")
async def finish_portal_nfc(
    data: FinishPortalNfc,
    request: Request,
):
    _require_origin(request)

    proof = request.cookies.get(FLOW_COOKIE)

    if (
        proof is None
        or len(proof) != 64
        or not proof.isascii()
        or not hmac.compare_digest(
            proof,
            _browser_proof(data.challenge),
        )
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "El intento NFC no pertenece "
                "a este navegador. Reintenta."
            ),
        )

    try:
        user_id, session_token = await run_in_threadpool(
            _finish,
            data.challenge,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Tarjeta no autorizada, usuario bloqueado "
                "o intento NFC caducado."
            ),
        ) from exc

    response = JSONResponse(
        {
            "authenticated": True,
            "user_id": str(user_id),
        },
        headers={"Cache-Control": "no-store"},
    )

    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        max_age=SESSION_MAX_AGE,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )

    response.delete_cookie(
        key=FLOW_COOKIE,
        path=FLOW_PATH,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )

    return response