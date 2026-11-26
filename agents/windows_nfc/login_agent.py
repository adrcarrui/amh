import os
import re
from threading import Lock
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from agents.windows_nfc.reader import read_uid_once


FRONTEND_ORIGIN = os.environ.get(
    "AMH_NFC_FRONTEND_ORIGIN",
    "http://127.0.0.1:5174",
)

KEYCLOAK_ORIGIN = os.environ.get(
    "AMH_NFC_KEYCLOAK_ORIGIN",
    "http://127.0.0.1:8081",
)

AMH_API_URL = os.environ.get(
    "AMH_NFC_API_URL",
    "http://127.0.0.1:8001",
).rstrip("/")

api_address = urlsplit(AMH_API_URL)

if api_address.scheme != "https" and not (
    api_address.scheme == "http"
    and api_address.hostname in {"127.0.0.1", "localhost"}
):
    raise RuntimeError(
        "AMH_NFC_API_URL requiere HTTPS fuera del equipo local"
    )

AMH_ORIGIN = (
    f"{api_address.scheme}://"
    f"{api_address.netloc}"
)

ALLOWED_ORIGINS = {
    FRONTEND_ORIGIN,
    KEYCLOAK_ORIGIN,
    AMH_ORIGIN,
    "http://127.0.0.1:5173",
    "http://localhost:5173",
}

ENROLLMENT_ORIGINS = {
    FRONTEND_ORIGIN,
    AMH_ORIGIN,
}

AGENT_TOKEN = os.environ.get("AMH_NFC_AGENT_TOKEN")

if not AGENT_TOKEN:
    raise RuntimeError("Falta AMH_NFC_AGENT_TOKEN")


app = FastAPI(title="AMH NFC Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
    allow_credentials=True,
)

_reader_lock = Lock()
_must_remove_card = False


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge: str = Field(min_length=43, max_length=43)


def require_json(request: Request) -> None:
    content_type = (
        request.headers.get("content-type", "")
        .split(";")[0]
        .strip()
        .lower()
    )

    if content_type != "application/json":
        raise HTTPException(
            status_code=415,
            detail="Se requiere JSON",
        )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/scan")
def scan(
    data: ScanRequest,
    request: Request,
    origin: str | None = Header(default=None),
):
    global _must_remove_card

    if origin not in ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail="Origen no permitido",
        )

    require_json(request)

    if re.fullmatch(
        r"[A-Za-z0-9_-]{43}",
        data.challenge,
    ) is None:
        raise HTTPException(
            status_code=400,
            detail="Desafio no valido",
        )

    with _reader_lock:
        try:
            uid = read_uid_once()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Lector no disponible",
            ) from exc

        if uid is None:
            _must_remove_card = False

            return Response(
                status_code=204,
                headers={"Cache-Control": "no-store"},
            )

        # Obliga a retirar la tarjeta despues de una lectura aceptada.
        if _must_remove_card:
            return JSONResponse(
                {"status": "remove_card"},
                headers={"Cache-Control": "no-store"},
            )

        try:
            with httpx.Client(
                timeout=5.0,
                trust_env=False,
            ) as client:
                result = client.post(
                    f"{AMH_API_URL}/api/v1/nfc/readings",
                    headers={
                        "X-AMH-NFC-Agent-Token": AGENT_TOKEN,
                    },
                    json={
                        "challenge": data.challenge,
                        "uid": uid,
                    },
                )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail="AMH no disponible",
            ) from exc

        print(
            "Respuesta de AMH a /readings: "
            f"HTTP {result.status_code}",
            flush=True,
        )

        if result.status_code != 204:
            raise HTTPException(
                status_code=502,
                detail="AMH no ha aceptado la lectura",
            )

        _must_remove_card = True

        return JSONResponse(
            {"status": "verified"},
            headers={"Cache-Control": "no-store"},
        )


@app.post("/enrollment/read")
def read_card_for_enrollment(
    request: Request,
    origin: str | None = Header(default=None),
):
    global _must_remove_card

    if origin not in ENROLLMENT_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail="Origen no permitido",
        )

    require_json(request)

    admin_session = request.cookies.get("amh_session")

    if not admin_session:
        raise HTTPException(
            status_code=401,
            detail="Sesion AMH ausente",
        )

    # Comprueba la sesion y el permiso admin contra AMH.
    try:
        with httpx.Client(
            timeout=5.0,
            trust_env=False,
        ) as client:
            authorization = client.get(
                f"{AMH_API_URL}/api/v1/admin/applications",
                cookies={
                    "amh_session": admin_session,
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="AMH no disponible",
        ) from exc

    if authorization.status_code == 401:
        raise HTTPException(
            status_code=401,
            detail="Sesion AMH no valida",
        )

    if authorization.status_code == 403:
        raise HTTPException(
            status_code=403,
            detail="Se requiere permiso admin de AMH",
        )

    if authorization.status_code != 200:
        raise HTTPException(
            status_code=503,
            detail="No se pudo comprobar el permiso en AMH",
        )

    with _reader_lock:
        try:
            uid = read_uid_once()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Lector no disponible",
            ) from exc

        if uid is None:
            _must_remove_card = False

            return Response(
                status_code=204,
                headers={"Cache-Control": "no-store"},
            )

        if _must_remove_card:
            return JSONResponse(
                {"status": "remove_card"},
                headers={"Cache-Control": "no-store"},
            )

        _must_remove_card = True

        return JSONResponse(
            {"uid": uid},
            headers={"Cache-Control": "no-store"},
        )