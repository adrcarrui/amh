from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import select

from app.aturnos_comparison import compare_users
from app.authorization import has_application_access
from app.config import settings
from app.db import SessionLocal
from app.models import User, UserEmail, UserATurnosLink
from app.models.aturnos_sync_run import ATurnosSyncRun


class ATurnosSyncError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 502,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def check_actor(db, actor_user_id: UUID) -> None:
    actor = db.get(User, actor_user_id)

    if (
        actor is None
        or actor.is_blocked
        or not has_application_access(
            db,
            user_id=actor_user_id,
            application_code="amh",
            minimum_role="admin",
        )
    ):
        raise ATurnosSyncError(
            "ADMIN_REQUIRED",
            "Se requiere el permiso admin de AMH",
            403,
        )


def fetch_users(team_id: str) -> list[dict]:
    if settings.amh_aturnos_token is None:
        raise ATurnosSyncError(
            "TOKEN_NOT_CONFIGURED",
            "La conexion con aTurnos no tiene un token configurado",
            503,
        )

    token = settings.amh_aturnos_token.get_secret_value().strip()

    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if (
        not token
        or len(token) > 16384
        or any(ord(char) < 33 or ord(char) > 126 for char in token)
    ):
        raise ATurnosSyncError(
            "INVALID_TOKEN_FORMAT",
            "El token configurado no tiene un formato valido",
            503,
        )

    try:
        with httpx.Client(
            timeout=60.0,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = client.get(
                f"https://www.aturnos.com/apirest/{team_id}/users",
                params={"not_limit": "1"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
    except httpx.RequestError:
        raise ATurnosSyncError(
            "CONNECTION_FAILED",
            "No se ha podido conectar con aTurnos",
        ) from None
    finally:
        token = None

    if response.status_code in (401, 403):
        raise ATurnosSyncError(
            "ATURNOS_ACCESS_DENIED",
            "aTurnos rechazo el token o el acceso al equipo",
            400,
        )

    if response.status_code != 200:
        raise ATurnosSyncError(
            "ATURNOS_HTTP_ERROR",
            f"aTurnos respondio HTTP {response.status_code}",
        )

    try:
        payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError()

        if payload.get("status") is not True:
            raise ValueError()

        page = payload["data"]
        users = page["data"]
        raw_total = page["total"]

        if (
            isinstance(raw_total, bool)
            or not isinstance(raw_total, (int, str))
            or not str(raw_total).isascii()
            or not str(raw_total).isdecimal()
        ):
            raise ValueError()

        total = int(raw_total)

        if not isinstance(users, list):
            raise ValueError()

    except (ValueError, TypeError, KeyError):
        raise ATurnosSyncError(
            "INVALID_RESPONSE",
            "aTurnos no devolvio un listado valido",
        ) from None

    if len(users) != total:
        raise ATurnosSyncError(
            "INCOMPLETE_RESPONSE",
            "aTurnos devolvio un listado incompleto. "
            "No se realiza la comparacion.",
        )

    for user in users:
        if not isinstance(user, dict):
            raise ATurnosSyncError(
                "INVALID_USER",
                "aTurnos devolvio un registro de usuario no valido",
            )

        external_id = str(user.get("id_user") or "")

        if (
            str(user.get("id_aturno")) != team_id
            or not external_id.isascii()
            or not external_id.isdecimal()
            or len(external_id) > 64
            or int(external_id) <= 0
        ):
            raise ATurnosSyncError(
                "INVALID_USER",
                "aTurnos devolvio identificadores incompletos "
                "o registros de otro equipo",
            )

    return users


def build_comparison(db, team_id: str, users: list[dict]) -> dict:
    linked_rows = db.execute(
        select(
            UserATurnosLink.id_user,
            User.id,
            User.name,
            User.surname,
            UserEmail.email,
        )
        .select_from(UserATurnosLink)
        .join(
            User,
            User.id == UserATurnosLink.user_id,
        )
        .outerjoin(
            UserEmail,
            (UserEmail.user_id == User.id)
            & (UserEmail.kind == "primary"),
        )
        .where(UserATurnosLink.id_aturno == team_id)
    ).all()

    links = {
        external_id: {
            "user_id": amh_id,
            "full_name": f"{name} {surname or ''}".strip(),
            "primary_email": primary_email,
        }
        for (
            external_id,
            amh_id,
            name,
            surname,
            primary_email,
        ) in linked_rows
    }

    emails = {
        email: amh_id
        for email, amh_id in db.execute(
            select(
                UserEmail.email_normalized,
                UserEmail.user_id,
            )
        ).all()
    }

    items = compare_users(users, links, emails)

    return {
        "team_id": team_id,
        "total": len(items),
        "source_total": len(users),
        "missing_total": sum(
            not item["source_present"] for item in items
        ),
        "items": items,
    }


def record_failure(
    *,
    team_id: str,
    trigger_kind: str,
    actor_user_id: UUID | None,
    started_at: datetime,
    error_code: str,
) -> None:
    finished_at = max(datetime.now(timezone.utc), started_at)

    with SessionLocal.begin() as db:
        db.add(
            ATurnosSyncRun(
                id_aturno=team_id,
                trigger_kind=trigger_kind,
                actor_user_id=actor_user_id,
                status="error",
                started_at=started_at,
                finished_at=finished_at,
                result=None,
                error_code=error_code,
            )
        )


def run_aturnos_sync(
    *,
    team_id: str | None = None,
    trigger_kind: str,
    actor_user_id: UUID | None = None,
) -> dict:
    configured_team = settings.amh_aturnos_team_id.strip()
    team_id = configured_team if team_id is None else team_id.strip()

    if (
        not team_id.isascii()
        or not team_id.isdecimal()
        or len(team_id) > 64
        or int(team_id) <= 0
    ):
        raise ATurnosSyncError(
            "INVALID_TEAM",
            "Identificador de equipo no valido",
            400,
        )

    if team_id != configured_team:
        raise ATurnosSyncError(
            "TEAM_NOT_ALLOWED",
            "El equipo no coincide con la integracion configurada",
            403,
        )

    if trigger_kind not in {"manual", "system"}:
        raise ValueError("Origen de ejecucion no valido")

    if trigger_kind == "manual":
        if actor_user_id is None:
            raise ValueError("La consulta manual requiere un administrador")

        with SessionLocal.begin() as db:
            check_actor(db, actor_user_id)

    elif actor_user_id is not None:
        raise ValueError("La consulta de sistema no debe indicar un usuario")

    started_at = datetime.now(timezone.utc)

    try:
        users = fetch_users(team_id)

        with SessionLocal.begin() as db:
            if trigger_kind == "manual":
                check_actor(db, actor_user_id)

            result = build_comparison(db, team_id, users)
            finished_at = max(
                datetime.now(timezone.utc),
                started_at,
            )

            run = ATurnosSyncRun(
                id_aturno=team_id,
                trigger_kind=trigger_kind,
                actor_user_id=actor_user_id,
                status="ok",
                started_at=started_at,
                finished_at=finished_at,
                result=result,
                error_code=None,
            )
            db.add(run)
            db.flush()
            run_id = str(run.id)

    except ATurnosSyncError as exc:
        try:
            record_failure(
                team_id=team_id,
                trigger_kind=trigger_kind,
                actor_user_id=actor_user_id,
                started_at=started_at,
                error_code=exc.code,
            )
        except Exception:
            raise ATurnosSyncError(
                "AUDIT_WRITE_FAILED",
                "La consulta fallo y tampoco pudo registrarse el error",
                503,
            ) from None

        raise

    except Exception:
        # No guarda mensajes arbitrarios, respuestas ni credenciales.
        try:
            record_failure(
                team_id=team_id,
                trigger_kind=trigger_kind,
                actor_user_id=actor_user_id,
                started_at=started_at,
                error_code="INTERNAL_ERROR",
            )
        except Exception:
            raise ATurnosSyncError(
                "AUDIT_WRITE_FAILED",
                "No se pudo confirmar ni registrar la consulta",
                503,
            ) from None

        raise ATurnosSyncError(
            "INTERNAL_ERROR",
            "No se pudo completar y confirmar la consulta",
            503,
        ) from None

    return {
        **result,
        "run_id": run_id,
        "finished_at": finished_at.isoformat(),
    }