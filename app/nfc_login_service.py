import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import has_application_access
from app.card_uid import uid_hmac
from app.config import settings
from app.models import Application, NfcLoginAttempt, UserCard


CHALLENGE_LIFETIME = timedelta(seconds=90)
CHALLENGE_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def _challenge_hash(challenge: str) -> str | None:
    if not CHALLENGE_PATTERN.fullmatch(challenge):
        return None
    return hashlib.sha256(challenge.encode("ascii")).hexdigest()


def _find_attempt(
    db: Session,
    challenge: str,
) -> NfcLoginAttempt | None:
    digest = _challenge_hash(challenge)
    if digest is None:
        return None

    return db.scalar(
        select(NfcLoginAttempt)
        .where(NfcLoginAttempt.challenge_hash == digest)
        .with_for_update()
    )


def create_nfc_login_attempt(
    db: Session,
    *,
    application_code: str,
) -> str:
    """Crea un desafío. El llamador confirma la transacción."""
    application = db.scalar(
        select(Application).where(
            Application.code == application_code,
            Application.is_enabled.is_(True),
        )
    )
    if application is None:
        raise ValueError("Aplicación no disponible")

    challenge = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    db.add(
        NfcLoginAttempt(
            application_id=application.id,
            challenge_hash=_challenge_hash(challenge),
            expires_at=now + CHALLENGE_LIFETIME,
        )
    )
    db.flush()
    return challenge


def verify_nfc_login_attempt(
    db: Session,
    *,
    challenge: str,
    raw_uid: str,
) -> None:
    """El agente confirma una lectura; el llamador confirma la transacción."""
    attempt = _find_attempt(db, challenge)
    now = datetime.now(timezone.utc)

    if (
        attempt is None
        or now >= attempt.expires_at
        or attempt.verified_at is not None
        or attempt.consumed_at is not None
    ):
        raise ValueError("Intento NFC no válido")

    card = db.scalar(
        select(UserCard).where(
            UserCard.uid_hmac == uid_hmac(
                raw_uid,
                settings.uid_hmac_key,
            ),
            UserCard.status == "active",
        )
    )
    application = db.get(Application, attempt.application_id)

    if (
        card is None
        or application is None
        or not has_application_access(
            db,
            user_id=card.user_id,
            application_code=application.code,
        )
    ):
        raise ValueError("Intento NFC no válido")

    attempt.card_id = card.id
    attempt.user_id = card.user_id
    attempt.verified_at = now
    db.flush()


def consume_nfc_login_attempt(
    db: Session,
    *,
    challenge: str,
    application_code: str,
) -> UUID:
    """Devuelve el usuario autorizado. Se consume en la misma transacción
    en la que el llamador creará su sesión de aplicación.
    """
    attempt = _find_attempt(db, challenge)
    now = datetime.now(timezone.utc)

    if (
        attempt is None
        or now >= attempt.expires_at
        or attempt.verified_at is None
        or attempt.consumed_at is not None
        or attempt.user_id is None
        or attempt.card_id is None
    ):
        raise ValueError("Intento NFC no válido")

    application = db.get(Application, attempt.application_id)
    card = db.get(UserCard, attempt.card_id)

    if (
        application is None
        or application.code != application_code
        or card is None
        or card.status != "active"
        or card.user_id != attempt.user_id
        or not has_application_access(
            db,
            user_id=attempt.user_id,
            application_code=application_code,
        )
    ):
        raise ValueError("Intento NFC no válido")

    attempt.consumed_at = now
    db.flush()
    return attempt.user_id