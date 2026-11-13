import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import has_application_access
from app.models import Application, UserApplicationAccess, UserSession, User


IDLE_TIMEOUT = timedelta(minutes=15)
ABSOLUTE_TIMEOUT = timedelta(hours=8)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")

def _require_unblocked_user(
    db: Session,
    *,
    user_id: UUID,
) -> User:
    user = db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    if user is None or user.is_blocked:
        raise PermissionError(
            "Usuario inexistente o bloqueado"
        )

    return user

def _session_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _find_session(db: Session, token: str) -> UserSession | None:
    if not TOKEN_PATTERN.fullmatch(token):
        return None

    return db.scalar(
        select(UserSession)
        .where(UserSession.session_hash == _session_hash(token))
        .with_for_update()
    )


def create_admin_session(db: Session, *, user_id: UUID) -> str:
    """Crea una sesión AMH; el llamador debe confirmar la transacción."""
    _require_unblocked_user(db, user_id=user_id)
    if not has_application_access(
        db,
        user_id=user_id,
        application_code="amh",
        minimum_role="admin",
    ):
        raise PermissionError("Acceso de administrador a AMH requerido")

    application = db.scalar(
        select(Application).where(Application.code == "amh")
    )
    if application is None:
        raise RuntimeError("La aplicación amh no existe")

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    db.add(
        UserSession(
            user_id=user_id,
            application_id=application.id,
            session_hash=_session_hash(token),
            auth_method="oidc",
            last_seen_at=now,
            expires_at=now + ABSOLUTE_TIMEOUT,
        )
    )
    db.flush()
    return token


def get_admin_session_user_id(
    db: Session, *, token: str
) -> UUID | None:
    """Valida la sesión AMH y exige permiso admin para esta operación."""
    user_id = get_portal_session_user_id(db, token=token)
    if user_id is None:
        return None

    if not has_application_access(
        db,
        user_id=user_id,
        application_code="amh",
        minimum_role="admin",
    ):
        return None

    return user_id


def revoke_admin_session(db: Session, *, token: str) -> None:
    """Revoca la sesión, si existe, sin revelar si el token era válido."""
    session = _find_session(db, token)
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.flush()


def create_application_session(
    db: Session,
    *,
    user_id: UUID,
    application_code: str,
    auth_method: str = "oidc",
) -> str:
    """Crea una sesión de aplicación; el llamador confirma la transacción."""
    if auth_method not in {"oidc", "nfc"}:
        raise ValueError("Método de autenticación no válido")

    if application_code == "amh":
        raise ValueError("Las sesiones administrativas usan su propio flujo")

    if not has_application_access(
        db,
        user_id=user_id,
        application_code=application_code,
    ):
        raise PermissionError("Acceso a la aplicación no concedido")

    application = db.scalar(
        select(Application).where(Application.code == application_code)
    )
    if application is None:
        raise ValueError("Aplicación no encontrada")

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    db.add(
        UserSession(
            user_id=user_id,
            application_id=application.id,
            session_hash=_session_hash(token),
            auth_method=auth_method,
            last_seen_at=now,
            expires_at=now + ABSOLUTE_TIMEOUT,
        )
    )
    db.flush()
    return token


def get_application_session_access(
    db: Session,
    *,
    token: str,
    application_code: str,
) -> tuple[UUID, str] | None:
    """Comprueba sesión y concesión actual; devuelve (usuario, rol)."""
    session = _find_session(db, token)
    if session is None or session.revoked_at is not None:
        return None

    application = db.get(Application, session.application_id)

    # Una cookie de otra aplicación no sirve aquí. No revocamos por
    # este motivo la sesión legítima de aquella aplicación.
    if application is None or application.code != application_code:
        return None

    now = datetime.now(timezone.utc)

    role = db.scalar(
        select(UserApplicationAccess.role)
        .where(
            UserApplicationAccess.user_id == session.user_id,
            UserApplicationAccess.application_id == application.id,
            UserApplicationAccess.status == "active",
        )
        .with_for_update()
    )

    valid = (
        now < session.expires_at
        and now - session.last_seen_at < IDLE_TIMEOUT
        and role in {"viewer", "editor", "admin"}
        and has_application_access(
            db,
            user_id=session.user_id,
            application_code=application_code,
        )
    )

    if not valid:
        session.revoked_at = now
        db.flush()
        return None

    session.last_seen_at = now
    db.flush()
    return session.user_id, role


def revoke_application_session(
    db: Session,
    *,
    token: str,
    application_code: str,
) -> None:
    """Cierra una sesión de esta aplicación sin afectar a otras."""
    session = _find_session(db, token)
    if session is None or session.revoked_at is not None:
        return

    application = db.get(Application, session.application_id)
    if application is None or application.code != application_code:
        return

    session.revoked_at = datetime.now(timezone.utc)
    db.flush()

def create_portal_session(db: Session, *, user_id: UUID) -> str:
    """Crea una sesión para entrar al portal AMH, sin exigir rol admin."""
    user = db.get(User, user_id)
    if user is None or user.is_blocked:
        raise PermissionError("Usuario inexistente o bloqueado")

    application = db.scalar(
        select(Application).where(
            Application.code == "amh",
            Application.is_enabled.is_(True),
        )
    )
    if application is None:
        raise RuntimeError("La aplicación AMH no está disponible")

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    db.add(
        UserSession(
            user_id=user_id,
            application_id=application.id,
            session_hash=_session_hash(token),
            auth_method="oidc",
            last_seen_at=now,
            expires_at=now + ABSOLUTE_TIMEOUT,
        )
    )
    db.flush()
    return token


def get_portal_session_user_id(
    db: Session, *, token: str
) -> UUID | None:
    """Valida una sesión AMH para usuarios normales y administradores."""
    session = _find_session(db, token)
    if session is None or session.revoked_at is not None:
        return None

    application = db.get(Application, session.application_id)
    if application is None or application.code != "amh":
        return None

    user = db.get(User, session.user_id)
    now = datetime.now(timezone.utc)

    if (
        user is None
        or user.is_blocked
        or not application.is_enabled
        or now >= session.expires_at
        or now - session.last_seen_at >= IDLE_TIMEOUT
    ):
        session.revoked_at = now
        db.flush()
        return None

    session.last_seen_at = now
    db.flush()
    return session.user_id