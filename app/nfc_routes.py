import hmac

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from hashlib import sha256
from app.config import settings
from app.db import SessionLocal
from app.nfc_login_service import (
    create_nfc_login_attempt,
    verify_nfc_login_attempt,
)
from app.nfc_login_service import consume_nfc_login_attempt
from app.session_service import (
    create_application_session,
    get_application_session_access,
)

router = APIRouter(prefix="/api/v1/nfc", tags=["nfc"])


class StartNfcLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_code: str


class ConfirmNfcReading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge: str = Field(min_length=43, max_length=43)
    uid: str = Field(min_length=8, max_length=64)


def _require_token(received: str | None, expected: str) -> None:
    if received is None or not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Cliente no autorizado")


def _start(application_code: str) -> str:
    with SessionLocal.begin() as db:
        return create_nfc_login_attempt(
            db,
            application_code=application_code,
        )


@router.post("/attempts", status_code=201)
async def start_nfc_login(
    data: StartNfcLogin,
    x_amh_nfc_client_token: str | None = Header(default=None),
):
    _require_token(
        x_amh_nfc_client_token,
        settings.amh_nfc_mysim_client_token.get_secret_value(),
    )

    if data.application_code != "mysim_dashboard":
        raise HTTPException(status_code=403, detail="Aplicación no permitida")

    try:
        challenge = await run_in_threadpool(
            _start,
            data.application_code,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Aplicación no disponible",
        ) from exc

    return {"challenge": challenge, "expires_in_seconds": 90}


def _confirm(challenge: str, uid: str) -> None:
    with SessionLocal.begin() as db:
        verify_nfc_login_attempt(
            db,
            challenge=challenge,
            raw_uid=uid,
        )

def fingerprint(value: str | None) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:12] if value else "AUSENTE"


@router.post("/readings", status_code=204)
async def confirm_nfc_reading(
    data: ConfirmNfcReading,
    x_amh_nfc_agent_token: str | None = Header(default=None),
):
    print(
        "NFC token esperado:",
        fingerprint(settings.amh_nfc_agent_token.get_secret_value()),
        "recibido:",
        fingerprint(x_amh_nfc_agent_token),
        flush=True,
    )
    _require_token(
        x_amh_nfc_agent_token,
        settings.amh_nfc_agent_token.get_secret_value(),
    )

    try:
        await run_in_threadpool(
            _confirm,
            data.challenge,
            data.uid,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Intento NFC no válido",
        ) from exc

class ConsumeNfcLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge: str = Field(min_length=43, max_length=43)


def _consume(challenge: str) -> dict:
    with SessionLocal.begin() as db:
        user_id = consume_nfc_login_attempt(
            db,
            challenge=challenge,
            application_code="mysim_dashboard",
        )

        session_token = create_application_session(
            db,
            user_id=user_id,
            application_code="mysim_dashboard",
            auth_method="nfc",
        )

        access = get_application_session_access(
            db,
            token=session_token,
            application_code="mysim_dashboard",
        )
        if access is None:
            raise ValueError("No se pudo validar la nueva sesión")

        _, role = access
        return {
            "application_code": "mysim_dashboard",
            "user_id": user_id,
            "role": role,
            "session_token": session_token,
        }


@router.post("/attempts/consume", status_code=201)
async def consume_nfc_login(
    data: ConsumeNfcLogin,
    x_amh_nfc_client_token: str | None = Header(default=None),
):
    _require_token(
        x_amh_nfc_client_token,
        settings.amh_nfc_mysim_client_token.get_secret_value(),
    )

    try:
        return await run_in_threadpool(_consume, data.challenge)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Lectura NFC ausente, caducada o no autorizada",
        ) from exc