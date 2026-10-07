from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.card_uid import uid_hmac
from app.config import settings
from app.models import CardEvent, User, UserCard
from app.authorization import has_application_access


class CardAlreadyRegisteredError(Exception):
    pass


class CardNotFoundError(Exception):
    pass


class CardAlreadyRevokedError(Exception):
    pass


def _require_actor(db: Session, actor_user_id: UUID) -> None:
    if not has_application_access(
        db,
        user_id=actor_user_id,
        application_code="amh",
        minimum_role="admin",
    ):
        raise PermissionError("Permiso de administración de AMH requerido")


def assign_card(
    db: Session,
    *,
    user_id: UUID,
    raw_uid: str,
    actor_user_id: UUID,
) -> UserCard:
    _require_actor(db, actor_user_id)

    if db.get(User, user_id) is None:
        raise ValueError("Usuario no encontrado")

    digest = uid_hmac(raw_uid, settings.uid_hmac_key)

    existing = db.scalar(
        select(UserCard).where(UserCard.uid_hmac == digest)
    )
    if existing is not None:
        # También impide reasignar el UID de una tarjeta revocada.
        raise CardAlreadyRegisteredError("Tarjeta ya registrada")

    card = UserCard(
        user_id=user_id,
        uid_hmac=digest,
        status="active",
    )
    db.add(card)
    db.flush()

    db.add(CardEvent(
        card_id=card.id,
        actor_kind="user",
        actor_user_id=actor_user_id,
        action="assigned",
    ))
    db.flush()
    return card


def revoke_card(
    db: Session,
    *,
    card_id: UUID,
    actor_user_id: UUID,
    reason: str,
) -> UserCard:
    _require_actor(db, actor_user_id)

    card = db.get(UserCard, card_id)
    if card is None:
        raise CardNotFoundError("Tarjeta no encontrada")
    if card.status == "revoked":
        raise CardAlreadyRevokedError("Tarjeta ya revocada")

    reason = reason.strip()
    if not reason or len(reason) > 500:
        raise ValueError("Indica un motivo de hasta 500 caracteres")

    card.status = "revoked"
    card.revoked_at = datetime.now(timezone.utc)
    card.revoked_by_user_id = actor_user_id
    card.revocation_reason = reason

    db.add(CardEvent(
        card_id=card.id,
        actor_kind="user",
        actor_user_id=actor_user_id,
        action="revoked",
        reason=reason,
    ))
    db.flush()
    return card