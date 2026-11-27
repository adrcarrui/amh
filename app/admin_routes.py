from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
import httpx
from fastapi.responses import JSONResponse

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, EmailStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from starlette.concurrency import run_in_threadpool

from app.user_creation_service import create_managed_user
from app.access_service import set_application_access
from app.config import settings
from app.db import SessionLocal
from app.models import (
    Application,
    ApplicationEvent,
    User,
    UserApplicationAccess,
    UserCard,
    UserEmail,
)
from app.session_service import get_admin_session_user_id
from app.card_service import CardAlreadyRegisteredError, assign_card

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class AccessChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_code: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    role: Literal["viewer", "editor", "admin"]
    status: Literal["active", "blocked", "revoked"]
    reason: str | None = Field(default=None, max_length=500)


def _list_applications(session_token: str | None):
    if not session_token:
        return None

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            return None

        applications = db.scalars(
            select(Application).order_by(Application.code)
        ).all()

        return [
            {
                "id": application.id,
                "code": application.code,
                "display_name": application.display_name,
                "oidc_client_id": application.oidc_client_id,
                "launch_url": application.launch_url,
                "is_enabled": application.is_enabled,
            }
            for application in applications
        ]


@router.get("/applications")
async def list_applications(request: Request):
    result = await run_in_threadpool(
        _list_applications,
        request.cookies.get("amh_session"),
    )
    if result is None:
        raise HTTPException(status_code=401, detail="Sesión AMH no válida")

    return result


def _list_users(
    session_token: str | None,
    limit: int,
    offset: int,
    name: str = "",
    email: str = "",
    status: Literal["active", "blocked"] | None = None,
    no_application_access: bool = False,
    no_nfc_card: bool = False,
    secondary_email: str = "",
    nfc: Literal["linked", "not_linked"] | None = None,
):
    if not session_token:
        return None

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            return None

        application_count = (
            select(func.count())
            .select_from(UserApplicationAccess)
            .join(Application, Application.id == UserApplicationAccess.application_id)
            .where(
                UserApplicationAccess.user_id == User.id,
                UserApplicationAccess.status == "active",
                Application.is_enabled.is_(True),
                Application.code != "amh",
            )
            .correlate(User)
            .scalar_subquery()
        )
        has_nfc_card = (
            select(UserCard.id)
            .where(
                UserCard.user_id == User.id,
                UserCard.status == "active",
            )
            .correlate(User)
            .exists()
        )

        secondary = aliased(UserEmail)
        query = select(
            User.id,
            User.name,
            User.surname,
            User.is_blocked,
            UserEmail.email,
            UserEmail.verified_at,
            secondary.email,
            application_count.label("application_count"),
            has_nfc_card.label("has_nfc_card"),
        ).outerjoin(
            UserEmail,
            (UserEmail.user_id == User.id) & (UserEmail.kind == "primary"),
        ).outerjoin(
            secondary,
            (secondary.user_id == User.id) & (secondary.kind == "secondary"),
        )

        name = name.strip()
        email = email.strip()
        secondary_email = secondary_email.strip()
        if name:
            full_name = User.name + " " + func.coalesce(User.surname, "")
            query = query.where(full_name.icontains(name, autoescape=True))
        if email:
            query = query.where(UserEmail.email.icontains(email, autoescape=True))
        if secondary_email:
            query = query.where(secondary.email.icontains(secondary_email, autoescape=True))
        if status is not None:
            query = query.where(User.is_blocked.is_(status == "blocked"))
        if no_application_access:
            query = query.where(application_count == 0)
        if no_nfc_card or nfc == "not_linked":
            query = query.where(~has_nfc_card)
        elif nfc == "linked":
            query = query.where(has_nfc_card)

        rows = db.execute(
            query.order_by(User.name, User.surname, User.id)
            .offset(offset)
            .limit(limit + 1)
        ).all()

        return {
            "items": [
                {
                    "id": user_id,
                    "name": name,
                    "surname": surname,
                    "is_blocked": is_blocked,
                    "primary_email": email,
                    "secondary_email": extra_email,
                    "primary_email_verified": verified_at is not None,
                    "application_count": app_count,
                    "has_nfc_card": nfc_linked,
                }
                for (
                    user_id,
                    name,
                    surname,
                    is_blocked,
                    email,
                    verified_at,
                    extra_email,
                    app_count,
                    nfc_linked,
                ) in rows[:limit]
            ],
            "limit": limit,
            "offset": offset,
            "has_more": len(rows) > limit,
        }


@router.get("/users")
async def list_users(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    name: str = Query(default="", max_length=251),
    email: str = Query(default="", max_length=320),
    status: Literal["active", "blocked"] | None = None,
    no_application_access: bool = False,
    no_nfc_card: bool = False,
    secondary_email: str = Query(default="", max_length=320),
    nfc: Literal["linked", "not_linked"] | None = None,
):
    result = await run_in_threadpool(
        _list_users,
        request.cookies.get("amh_session"),
        limit,
        offset,
        name,
        email,
        status,
        no_application_access,
        no_nfc_card,
        secondary_email,
        nfc,
    )
    if result is None:
        raise HTTPException(status_code=401, detail="Sesión AMH no válida")

    return result


def _change_application_access(
    session_token: str | None,
    user_id: UUID,
    change: AccessChange,
):
    if not session_token:
        return None

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            return None

        access = set_application_access(
            db,
            actor_user_id=admin_id,
            user_id=user_id,
            application_code=change.application_code,
            role=change.role,
            status=change.status,
            reason=change.reason,
        )

        return {
            "access_id": access.id,
            "user_id": access.user_id,
            "application_code": change.application_code,
            "role": access.role,
            "status": access.status,
        }


@router.post("/users/{user_id}/application-access")
async def change_application_access(
    user_id: UUID,
    change: AccessChange,
    request: Request,
):
    redirect_uri = urlsplit(settings.amh_oidc_redirect_uri)
    expected_origin = f"{redirect_uri.scheme}://{redirect_uri.netloc}"

    allowed_origins = {
        expected_origin,
        "http://127.0.0.1:5174",
    }

    if request.headers.get("origin") not in allowed_origins:
        raise HTTPException(
            status_code=403,
            detail="Origen no permitido",
        )

    try:
        result = await run_in_threadpool(
            _change_application_access,
            request.cookies.get("amh_session"),
            user_id,
            change,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=401, detail="Sesión AMH no válida")

    return result

class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    display_name: str = Field(min_length=1, max_length=150)
    oidc_client_id: str | None = Field(default=None, max_length=128)
    launch_url: str | None = Field(default=None, max_length=2048)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre no puede estar vacío")
        return value

    @field_validator("launch_url")
    @classmethod
    def validate_launch_url(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("La URL de entrada no es válida")

        parsed = urlsplit(value)

        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("El puerto de la URL no es válido") from exc

        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("La URL de entrada no es válida")

        if parsed.scheme == "https":
            return value

        if (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
        ):
            return value

        raise ValueError(
            "La URL debe usar HTTPS; HTTP solo se permite en localhost"
        )


class ApplicationLaunchUrlChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    launch_url: str = Field(min_length=1, max_length=2048)

    @field_validator("launch_url")
    @classmethod
    def validate_launch_url(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("La URL de entrada no es válida")

        parsed = urlsplit(value)

        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("El puerto de la URL no es válido") from exc

        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("La URL de entrada no es válida")

        if parsed.scheme == "https":
            return value

        if (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
        ):
            return value

        raise ValueError(
            "La URL debe usar HTTPS; HTTP solo se permite en localhost"
        )

def _create_application(
    session_token: str | None,
    data: ApplicationCreate,
):
    if not session_token:
        return None

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            return None

        application = Application(
            code=data.code,
            display_name=data.display_name,
            oidc_client_id=data.oidc_client_id,
            launch_url=data.launch_url,
            is_enabled=True,
        )
        db.add(application)
        db.flush()

        db.add(
            ApplicationEvent(
                application_id=application.id,
                actor_user_id=admin_id,
                action="created",
            )
        )
        db.flush()

        return {
            "id": application.id,
            "code": application.code,
            "display_name": application.display_name,
            "oidc_client_id": application.oidc_client_id,
            "is_enabled": application.is_enabled,
        }


@router.post("/applications", status_code=201)
async def create_application(
    data: ApplicationCreate,
    request: Request,
):
    redirect_uri = urlsplit(settings.amh_oidc_redirect_uri)
    expected_origin = f"{redirect_uri.scheme}://{redirect_uri.netloc}"

    if request.headers.get("origin") != expected_origin:
        raise HTTPException(status_code=403, detail="Origen no permitido")

    try:
        result = await run_in_threadpool(
            _create_application,
            request.cookies.get("amh_session"),
            data,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="El código o el cliente OIDC ya está registrado",
        ) from exc

    if result is None:
        raise HTTPException(status_code=401, detail="Sesión AMH no válida")

    return result

class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keycloak_subject: UUID
    name: str = Field(min_length=1, max_length=100)
    surname: str = Field(min_length=1, max_length=150)
    primary_email: EmailStr = Field(max_length=320)
    application_code: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    role: Literal["viewer", "editor", "admin"]

    @field_validator("name", "surname")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre o apellido no puede estar vacío")
        return value


def _create_user(
    session_token: str | None,
    data: UserCreate,
):
    if not session_token:
        return None

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            return None

        user = User(
            keycloak_subject=str(data.keycloak_subject),
            name=data.name,
            surname=data.surname,
            is_blocked=False,
        )
        db.add(user)
        db.flush()

        email = str(data.primary_email)
        db.add(
            UserEmail(
                user_id=user.id,
                kind="primary",
                email=email,
                email_normalized=email.lower(),
                verified_at=None,
            )
        )
        db.flush()

        access = set_application_access(
            db,
            actor_user_id=admin_id,
            user_id=user.id,
            application_code=data.application_code,
            role=data.role,
            status="active",
            reason="Alta administrativa de usuario",
        )

        return {
            "id": user.id,
            "keycloak_subject": user.keycloak_subject,
            "name": user.name,
            "surname": user.surname,
            "primary_email": email,
            "primary_email_verified": False,
            "application_code": data.application_code,
            "role": access.role,
        }


@router.post("/users/link-existing", status_code=201)
async def create_user(data: UserCreate, request: Request):
    redirect_uri = urlsplit(settings.amh_oidc_redirect_uri)
    expected_origin = f"{redirect_uri.scheme}://{redirect_uri.netloc}"

    if request.headers.get("origin") != expected_origin:
        raise HTTPException(status_code=403, detail="Origen no permitido")

    try:
        result = await run_in_threadpool(
            _create_user,
            request.cookies.get("amh_session"),
            data,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="El usuario o email ya está registrado en AMH",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=401, detail="Sesión AMH no válida")

    return result

class CardAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_uid: str = Field(min_length=8, max_length=64)


def _assign_user_card(
    session_token: str | None,
    user_id: UUID,
    raw_uid: str,
):
    if not session_token:
        return None

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            return None

        card = assign_card(
            db,
            user_id=user_id,
            raw_uid=raw_uid,
            actor_user_id=admin_id,
        )
        return {
            "id": card.id,
            "user_id": card.user_id,
            "status": card.status,
        }


@router.post("/users/{user_id}/cards", status_code=201)
async def assign_user_card(
    user_id: UUID,
    data: CardAssignment,
    request: Request,
):
    redirect_uri = urlsplit(settings.amh_oidc_redirect_uri)
    expected_origin = f"{redirect_uri.scheme}://{redirect_uri.netloc}"

    allowed_origins = {
        expected_origin,
        "http://127.0.0.1:5174",
    }

    if request.headers.get("origin") not in allowed_origins:
        raise HTTPException(
            status_code=403,
            detail="Origen no permitido",
        )
    try:
        result = await run_in_threadpool(
            _assign_user_card,
            request.cookies.get("amh_session"),
            user_id,
            data.raw_uid,
        )
    except CardAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=409,
            detail="La tarjeta ya está registrada",
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="La tarjeta ya está registrada",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=401, detail="Sesión AMH no válida")

    return result

def _update_application_launch_url(
    session_token: str | None,
    application_code: str,
    change: ApplicationLaunchUrlChange,
):
    if not session_token:
        return None

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            return None

        application = db.scalar(
            select(Application)
            .where(Application.code == application_code)
            .with_for_update()
        )
        if application is None:
            raise LookupError("Aplicación no encontrada")

        if application.launch_url != change.launch_url:
            application.launch_url = change.launch_url
            db.add(
                ApplicationEvent(
                    application_id=application.id,
                    actor_user_id=admin_id,
                    action="updated",
                )
            )
            db.flush()

        return {
            "id": application.id,
            "code": application.code,
            "display_name": application.display_name,
            "launch_url": application.launch_url,
            "is_enabled": application.is_enabled,
        }


@router.patch("/applications/{application_code}/launch-url")
async def update_application_launch_url(
    application_code: str,
    change: ApplicationLaunchUrlChange,
    request: Request,
):
    redirect_uri = urlsplit(settings.amh_oidc_redirect_uri)
    expected_origin = f"{redirect_uri.scheme}://{redirect_uri.netloc}"

    if request.headers.get("origin") != expected_origin:
        raise HTTPException(status_code=403, detail="Origen no permitido")

    try:
        result = await run_in_threadpool(
            _update_application_launch_url,
            request.cookies.get("amh_session"),
            application_code,
            change,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=401, detail="Sesión AMH no válida")

    return result

class ManagedUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    name: str = Field(min_length=1, max_length=100)
    surname: str = Field(min_length=1, max_length=150)
    email: str = Field(
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )

    @field_validator("name", "surname", "email")
    @classmethod
    def strip_required_field(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El campo no puede estar vacío")
        return value


def _create_managed_user(
    session_token: str | None,
    data: ManagedUserCreate,
):
    if not session_token:
        return None

    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            return None

    user_id, temporary_password = create_managed_user(
        actor_user_id=admin_id,
        username=data.username,
        name=data.name,
        surname=data.surname,
        email=data.email,
    )

    return {
        "user_id": str(user_id),
        "username": data.username,
        "temporary_password": temporary_password,
    }


@router.post("/users", status_code=201)
async def create_managed_user_route(
    data: ManagedUserCreate,
    request: Request,
):
    redirect_uri = urlsplit(settings.amh_oidc_redirect_uri)
    expected_origin = f"{redirect_uri.scheme}://{redirect_uri.netloc}"

    if request.headers.get("origin") not in {
    expected_origin,
    "http://127.0.0.1:5174",
}:
        raise HTTPException(status_code=403, detail="Origen no permitido")

    try:
        result = await run_in_threadpool(
            _create_managed_user,
            request.cookies.get("amh_session"),
            data,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="El usuario o el email ya está registrado en AMH",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="Keycloak no está disponible",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=401, detail="Sesión AMH no válida")

    return JSONResponse(
        result,
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )