from collections import Counter
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from pydantic import Field, field_validator
from sqlalchemy.exc import IntegrityError

from app.admin_routes import ManagedUserCreate
from app.user_creation_service import create_managed_user

from app.config import settings
from app.db import SessionLocal
from app.models import User,UserEmail, UserATurnosLink
from app.session_service import get_admin_session_user_id
from fastapi import Query
from sqlalchemy import func
from sqlalchemy.orm import aliased

from app.models.aturnos_sync_run import ATurnosSyncRun
from app.models.aturnos_import_event import ATurnosImportEvent
from app.aturnos_sync_service import (
    ATurnosSyncError,
    run_aturnos_sync,
)

router = APIRouter(
    prefix="/api/v1/admin/aturnos",
    tags=["aturnos"],
)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str = "15945"


def require_admin(session_token: str | None) -> None:
    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="Sesion AMH no iniciada",
        )

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)

        if admin_id is None:
            raise HTTPException(
                status_code=401,
                detail="Sesion AMH no valida o permiso admin requerido",
            )


def compare_users(users, links, emails):
    id_counts = Counter(str(user["id_user"]) for user in users)
    email_counts = Counter(
        str(user.get("email") or "").strip().lower()
        for user in users
    )

    seen = set()
    items = []

    for user in users:
        external_id = str(user["id_user"])
        seen.add(external_id)

        name = str(user.get("username") or "").strip()
        email = str(user.get("email") or "").strip().lower()
        linked = links.get(external_id)
        reasons = []

        if id_counts[external_id] > 1:
            reasons.append("ID repetido en aTurnos")

        if not name:
            reasons.append("Sin nombre")

        valid_email = (
            email.count("@") == 1
            and bool(email.split("@")[0])
            and "." in email.rsplit("@", 1)[-1]
            and len(email) <= 320
            and not any(char.isspace() for char in email)
        )

        if not valid_email:
            reasons.append("Correo ausente o no valido")
        elif email.endswith("@aturnos.com"):
            reasons.append("Revisar correo generado por aTurnos")

        if email and email_counts[email] > 1:
            reasons.append("Correo repetido en aTurnos")

        if linked is not None:
            primary_email = (
                linked["primary_email"] or ""
            ).strip().lower()

            if email != primary_email:
                reasons.append(
                    "Correo distinto al principal de AMH; "
                    "pendiente de revision"
                )

            if email in emails and emails[email] != linked["user_id"]:
                reasons.append(
                    "El correo pertenece a otro usuario AMH"
                )

        elif email in emails:
            reasons.append("Correo existente en AMH sin enlace")

        active = str(user.get("active"))

        if active == "0" and linked is not None:
            status = "review"
            reasons.insert(
                0,
                "Usuario enlazado que figura inactivo en aTurnos; "
                "revisar continuidad de acceso",
            )

        elif active == "0":
            status = "inactive"
            reasons.insert(0, "Usuario inactivo en aTurnos")

        elif active != "1":
            status = "review"
            reasons.insert(0, "Estado active desconocido en aTurnos")

        elif reasons:
            status = "review"

        elif linked is not None:
            status = "linked"
            reasons.append("Identidad enlazada con AMH")

        else:
            status = "new"
            reasons.append(
                "Candidato a alta; revisar nombre y apellidos"
            )

        items.append(
            {
                "id_user": external_id,
                "name": name,
                "email": email or None,
                "status": status,
                "reason": "; ".join(reasons),
                "amh_user_id": (
                    str(linked["user_id"])
                    if linked is not None
                    else None
                ),
                "amh_primary_email": (
                    linked["primary_email"]
                    if linked is not None
                    else None
                ),
                "source_present": True,
            }
        )

    # Se conservan los enlaces aunque el usuario no aparezca
    # en el listado actual. Solo se genera un aviso.
    for external_id, linked in links.items():
        if external_id in seen:
            continue

        items.append(
            {
                "id_user": external_id,
                "name": linked["full_name"],
                "email": linked["primary_email"],
                "status": "review",
                "reason": (
                    "No aparece en la consulta actual de aTurnos. "
                    "Puede deberse a fechas o al alcance de la consulta; "
                    "no implica una baja confirmada."
                ),
                "amh_user_id": str(linked["user_id"]),
                "amh_primary_email": linked["primary_email"],
                "source_present": False,
            }
        )

    items.sort(
        key=lambda item: (
            item["name"].casefold(),
            item["id_user"],
        )
    )

    return items

def preview_users(
    session_token: str | None,
    data: PreviewRequest,
):
    require_admin(session_token)

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)

        if admin_id is None:
            raise HTTPException(
                status_code=401,
                detail="Sesion AMH no valida o permiso admin requerido",
            )

    try:
        result = run_aturnos_sync(
            team_id=data.team_id,
            trigger_kind="manual",
            actor_user_id=admin_id,
        )
    except ATurnosSyncError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from None

    # La sesion tambien debe seguir vigente al devolver los datos.
    require_admin(session_token)

    return result

@router.post("/preview")
async def preview_aturnos_users(
    data: PreviewRequest,
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
        preview_users,
        request.cookies.get("amh_session"),
        data,
    )

    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store"},
    )

class ImportUserRequest(PreviewRequest):
    id_user: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    surname: str = Field(min_length=1, max_length=150)

    @field_validator("id_user", "name", "surname")
    @classmethod
    def strip_required_field(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El campo no puede estar vacio")
        return value


def import_user(
    session_token: str | None,
    data: ImportUserRequest,
):
    external_id = data.id_user
    team_id = data.team_id.strip()

    if (
        not external_id.isascii()
        or not external_id.isdecimal()
        or int(external_id) <= 0
    ):
        raise HTTPException(
            status_code=400,
            detail="Identificador de usuario aTurnos no valido",
        )

    # La consulta comprueba sesion, permisos y datos actuales de aTurnos.
    preview = preview_users(
        session_token,
        PreviewRequest(team_id=team_id),
    )

    matches = [
        item
        for item in preview["items"]
        if item["id_user"] == external_id
    ]

    if len(matches) != 1:
        raise HTTPException(
            status_code=409,
            detail="El usuario no aparece de forma unica en el equipo",
        )

    source = matches[0]

    if source["status"] != "new":
        raise HTTPException(
            status_code=409,
            detail=(
                "No se puede importar este usuario: "
                + source["reason"]
                + ". Actualiza la consulta."
            ),
        )

    # El correo procede de la consulta actual a aTurnos.
    # Nombre y apellidos son los revisados por el administrador.
    try:
        user_data = ManagedUserCreate(
            username=f"aturnos_{team_id}_{external_id}",
            name=data.name,
            surname=data.surname,
            email=source["email"],
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Los datos del usuario no cumplen el formato de alta",
        ) from None

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            raise HTTPException(
                status_code=401,
                detail="Sesion AMH no valida o permiso admin requerido",
            )

    try:
        user_id, temporary_password = create_managed_user(
            actor_user_id=admin_id,
            username=user_data.username,
            name=user_data.name,
            surname=user_data.surname,
            email=user_data.email,
            aturnos_team_id=team_id,
            aturnos_user_id=external_id,
        )
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail="Se requiere el permiso admin de AMH",
        ) from None
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=(
                "El usuario, correo o enlace ya existe. "
                "Actualiza la consulta antes de continuar."
            ),
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from None
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Se interrumpio la comunicacion con Keycloak. "
                "Comprueba si el usuario se creo antes de reintentar."
            ),
        ) from None
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from None

    return {
        "user_id": str(user_id),
        "id_aturno": team_id,
        "id_user": external_id,
        "username": user_data.username,
        "name": user_data.name,
        "surname": user_data.surname,
        "temporary_password": temporary_password,
    }


@router.post("/import-user", status_code=201)
async def import_aturnos_user(
    data: ImportUserRequest,
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
        import_user,
        request.cookies.get("amh_session"),
        data,
    )

    return JSONResponse(
        result,
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )

def list_import_history(
    session_token: str | None,
    limit: int,
    offset: int,
):
    require_admin(session_token)

    imported_user = aliased(User)
    actor = aliased(User)

    with SessionLocal.begin() as db:
        if get_admin_session_user_id(db, token=session_token) is None:
            raise HTTPException(
                status_code=401,
                detail="Sesion AMH no valida o permiso admin requerido",
            )

        total = db.scalar(
            select(func.count()).select_from(ATurnosImportEvent)
        )

        rows = db.execute(
            select(
                ATurnosImportEvent.id,
                ATurnosImportEvent.user_id,
                imported_user.name,
                imported_user.surname,
                ATurnosImportEvent.actor_user_id,
                actor.name,
                actor.surname,
                ATurnosImportEvent.id_aturno,
                ATurnosImportEvent.id_user,
                ATurnosImportEvent.occurred_at,
            )
            .select_from(ATurnosImportEvent)
            .join(
                imported_user,
                imported_user.id == ATurnosImportEvent.user_id,
            )
            .join(
                actor,
                actor.id == ATurnosImportEvent.actor_user_id,
            )
            .order_by(
                ATurnosImportEvent.occurred_at.desc(),
                ATurnosImportEvent.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": str(event_id),
                    "user_id": str(user_id),
                    "user_name": f"{name} {surname or ''}".strip(),
                    "actor_user_id": str(actor_id),
                    "actor_name": (
                        f"{actor_name} {actor_surname or ''}".strip()
                    ),
                    "id_aturno": team_id,
                    "id_user": external_id,
                    "occurred_at": occurred_at.isoformat(),
                }
                for (
                    event_id,
                    user_id,
                    name,
                    surname,
                    actor_id,
                    actor_name,
                    actor_surname,
                    team_id,
                    external_id,
                    occurred_at,
                ) in rows
            ],
        }


@router.get("/history")
async def aturnos_import_history(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    result = await run_in_threadpool(
        list_import_history,
        request.cookies.get("amh_session"),
        limit,
        offset,
    )

    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store"},
    )

def get_saved_sync(session_token: str | None):
    require_admin(session_token)

    team_id = settings.amh_aturnos_team_id.strip()

    def serialize_run(run):
        if run is None:
            return None

        return {
            "id": str(run.id),
            "status": run.status,
            "trigger_kind": run.trigger_kind,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat(),
            "error_code": run.error_code,
        }

    with SessionLocal.begin() as db:
        if get_admin_session_user_id(db, token=session_token) is None:
            raise HTTPException(
                status_code=401,
                detail="Sesion AMH no valida o permiso admin requerido",
            )

        # Usa el inicio para ordenar consultas que puedan solaparse.
        latest = db.scalar(
            select(ATurnosSyncRun)
            .where(ATurnosSyncRun.id_aturno == team_id)
            .order_by(
                ATurnosSyncRun.started_at.desc(),
                ATurnosSyncRun.id.desc(),
            )
            .limit(1)
        )

        if latest is None:
            return {
                "team_id": team_id,
                "latest_run": None,
                "last_success": None,
                "preview": None,
            }

        if latest.status == "ok":
            last_success = latest
        else:
            # No mezcla la ultima ejecucion seleccionada con
            # una consulta posterior que termine durante esta lectura.
            last_success = db.scalar(
                select(ATurnosSyncRun)
                .where(
                    ATurnosSyncRun.id_aturno == team_id,
                    ATurnosSyncRun.status == "ok",
                    (
                        ATurnosSyncRun.started_at < latest.started_at
                    )
                    | (
                        (ATurnosSyncRun.started_at == latest.started_at)
                        & (ATurnosSyncRun.id <= latest.id)
                    ),
                )
                .order_by(
                    ATurnosSyncRun.started_at.desc(),
                    ATurnosSyncRun.id.desc(),
                )
                .limit(1)
            )

        return {
            "team_id": team_id,
            "latest_run": serialize_run(latest),
            "last_success": serialize_run(last_success),
            "preview": (
                last_success.result
                if last_success is not None
                else None
            ),
        }


@router.get("/latest")
async def latest_aturnos_sync(request: Request):
    result = await run_in_threadpool(
        get_saved_sync,
        request.cookies.get("amh_session"),
    )

    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store"},
    )