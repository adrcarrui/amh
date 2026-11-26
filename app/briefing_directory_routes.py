from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.db import SessionLocal
from app.models import User
from app.session_service import get_application_session_access


router = APIRouter(
    prefix="/api/v1/integrations/mysim-dashboard",
    tags=["briefing-directory"],
)


class BriefingNamesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_ids: list[UUID] = Field(max_length=500)

    @field_validator("user_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError(
                "Hay identificadores duplicados"
            )

        return value


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get(
        "authorization",
        "",
    )

    scheme, _, token = authorization.partition(" ")

    if (
        scheme.lower() != "bearer"
        or not token.strip()
    ):
        raise HTTPException(
            status_code=401,
            detail="Sesion de mySim requerida",
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    return token.strip()


def _briefing_user_names(
    token: str,
    user_ids: list[UUID],
):
    with SessionLocal.begin() as db:
        access = get_application_session_access(
            db,
            token=token,
            application_code="mysim_dashboard",
        )

        if access is None:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Sesion de mySim no valida o caducada"
                ),
            )

        _, role = access

        if role not in {"editor", "admin"}:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Se requiere el rol editor "
                    "o admin de mySim"
                ),
            )

        if not user_ids:
            return {"users": []}

        users = db.scalars(
            select(User)
            .where(User.id.in_(user_ids))
            .order_by(
                User.name,
                User.surname,
                User.id,
            )
        ).all()

        return {
            "users": [
                {
                    "amh_user_id": str(user.id),
                    "display_name": (
                        (
                            f"{user.name or ''} "
                            f"{user.surname or ''}"
                        ).strip()
                        or "Usuario sin nombre"
                    ),
                    "is_blocked": bool(user.is_blocked),
                }
                for user in users
            ]
        }


@router.post("/briefing-users")
async def briefing_user_names(
    data: BriefingNamesRequest,
    request: Request,
):
    result = await run_in_threadpool(
        _briefing_user_names,
        _bearer_token(request),
        data.user_ids,
    )

    return JSONResponse(
        result,
        headers={
            "Cache-Control": "no-store",
        },
    )