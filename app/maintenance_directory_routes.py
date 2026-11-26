from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.db import SessionLocal
from app.models import User, UserEmail
from app.models.user_aturnos_link import UserATurnosLink
from app.session_service import get_application_session_access
from app.aturnos_sync_service import ATurnosSyncError, fetch_users
from app.config import settings
from app.aturnos_sync_service import build_comparison


router = APIRouter(
    prefix="/api/v1/integrations/mysim-dashboard",
    tags=["maintenance-directory"],
)


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


def _directory_users(token: str) -> list[dict]:
    with SessionLocal.begin() as db:
        access = get_application_session_access(
            db,
            token=token,
            application_code="mysim_dashboard",
        )

        if access is None:
            raise HTTPException(
                status_code=401,
                detail="Sesión no válida",
            )

        _, role = access

        if role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Se requiere el rol admin de mySim Dashboard",
            )

        users = db.scalars(
            select(User).order_by(
                User.name,
                User.surname,
                User.id,
            )
        ).all()

        primary_emails = dict(
            db.execute(
                select(
                    UserEmail.user_id,
                    UserEmail.email,
                ).where(UserEmail.kind == "primary")
            ).all()
        )

        links_by_user: dict = {}

        links = db.scalars(
            select(UserATurnosLink).order_by(
                UserATurnosLink.user_id,
                UserATurnosLink.id_aturno,
                UserATurnosLink.id_user,
            )
        ).all()

        for link in links:
            links_by_user.setdefault(link.user_id, []).append(
                {
                    "id_aturno": link.id_aturno,
                    "id_user": link.id_user,
                }
            )

        return [
            {
                "amh_user_id": str(user.id),
                "display_name": " ".join(
                    part
                    for part in (
                        (user.name or "").strip(),
                        (user.surname or "").strip(),
                    )
                    if part
                ),
                "email": primary_emails.get(user.id),
                "is_blocked": user.is_blocked,
                "aturnos_links": links_by_user.get(user.id, []),
            }
            for user in users
        ]

def _current_aturnos_users() -> tuple[str, dict[str, bool | None]]:
    team_id = settings.amh_aturnos_team_id.strip()

    if (
        not team_id.isascii()
        or not team_id.isdecimal()
        or len(team_id) > 64
        or int(team_id) <= 0
    ):
        raise HTTPException(
            status_code=503,
            detail="El equipo de aTurnos no está configurado correctamente",
        )

    try:
        users = fetch_users(team_id)
    except ATurnosSyncError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"No se pudo comprobar aTurnos: {exc}",
        ) from exc

    states: dict[str, bool | None] = {}

    for user in users:
        external_id = str(user["id_user"])

        if external_id in states:
            raise HTTPException(
                status_code=503,
                detail="aTurnos devolvió identificadores duplicados",
            )

        active = str(user.get("active"))

        states[external_id] = (
            True if active == "1"
            else False if active == "0"
            else None
        )

    return team_id, states

@router.get("/users")
async def list_directory_users(request: Request):
    token = _bearer_token(request)

    users = await run_in_threadpool(
        _directory_users,
        token,
    )

    team_id, current_states = await run_in_threadpool(
        _current_aturnos_users,
    )

    for user in users:
        linked_states = [
            current_states[str(link["id_user"])]
            for link in user["aturnos_links"]
            if str(link["id_aturno"]) == team_id
            and str(link["id_user"]) in current_states
        ]

        user["aturnos_present"] = bool(linked_states)

        if any(state is True for state in linked_states):
            user["aturnos_active"] = True
        elif not linked_states or any(
            state is None for state in linked_states
        ):
            user["aturnos_active"] = None
        else:
            user["aturnos_active"] = False

    return JSONResponse(
        {
            "users": users,
            "complete": True,
        },
        headers={"Cache-Control": "no-store"},
    )

def _pending_aturnos_users(token: str) -> dict:
    def check_access(db):
        access = get_application_session_access(
            db,
            token=token,
            application_code="mysim_dashboard",
        )

        if access is None:
            raise HTTPException(
                status_code=401,
                detail="Sesión no válida",
            )

        _, role = access

        if role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Se requiere el rol admin de mySim Dashboard",
            )

    # Comprobamos los permisos antes de consultar aTurnos.
    with SessionLocal.begin() as db:
        check_access(db)

    team_id = settings.amh_aturnos_team_id.strip()

    if (
        not team_id.isascii()
        or not team_id.isdecimal()
        or len(team_id) > 64
        or int(team_id) <= 0
    ):
        raise HTTPException(
            status_code=503,
            detail="El equipo de aTurnos no está configurado correctamente",
        )

    try:
        source_users = fetch_users(team_id)
    except ATurnosSyncError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"No se pudo consultar aTurnos: {exc}",
        ) from exc

    identifiers = [
        str(user["id_user"])
        for user in source_users
    ]

    if len(identifiers) != len(set(identifiers)):
        raise HTTPException(
            status_code=503,
            detail="aTurnos devolvió identificadores duplicados",
        )

    with SessionLocal.begin() as db:
        # La sesión debe seguir vigente después de la consulta.
        check_access(db)

        comparison = build_comparison(
            db,
            team_id,
            source_users,
        )

    candidates = []
    review_required = []

    for item in comparison["items"]:
        if (
            not item["source_present"]
            or item["amh_user_id"] is not None
        ):
            continue

        if item["status"] == "new":
            candidates.append(item)

        elif item["status"] == "review":
            review_required.append(item)

    return {
        "team_id": team_id,
        "users": candidates,
        "review_required": review_required,
        "complete": True,
    }


@router.get("/aturnos-candidates")
async def list_pending_aturnos_users(request: Request):
    token = _bearer_token(request)

    result = await run_in_threadpool(
        _pending_aturnos_users,
        token,
    )

    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store"},
    )