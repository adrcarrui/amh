import unittest

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.card_service import (
    CardAlreadyRegisteredError,
    assign_card,
    revoke_card,
)
from app.card_uid import uid_hmac
from app.config import settings
from app.db import engine
from app.models import (
    Application,
    CardEvent,
    User,
    UserApplicationAccess,
    UserCard,
)


class CardServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if settings.amh_db_name != "amh_test":
            raise RuntimeError("Estas pruebas solo pueden usar amh_test")

    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        self.db = Session(
            bind=self.connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
        )

        self.actor = User(name="Admin Test", surname="AMH", is_blocked=False)
        self.user = User(name="Usuario Test", surname="AMH", is_blocked=False)
        self.amh = Application(
            code="amh",
            display_name="Access Management Hub",
            is_enabled=True,
        )

        self.db.add_all([self.actor, self.user, self.amh])
        self.db.flush()

        self.admin_access = UserApplicationAccess(
            user_id=self.actor.id,
            application_id=self.amh.id,
            status="active",
            role="admin",
        )
        self.db.add(self.admin_access)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def test_assignment_records_card_and_actor(self):
        card = assign_card(
            self.db,
            user_id=self.user.id,
            raw_uid="04:AA:BB:CC:DD",
            actor_user_id=self.actor.id,
        )

        self.assertEqual(card.status, "active")
        self.assertEqual(
            card.uid_hmac,
            uid_hmac("04AABBCCDD", settings.uid_hmac_key),
        )

        events = self.db.scalars(
            select(CardEvent).where(CardEvent.card_id == card.id)
        ).all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "assigned")
        self.assertEqual(events[0].actor_user_id, self.actor.id)

    def test_duplicate_and_revoked_uid_cannot_be_reassigned(self):
        card = assign_card(
            self.db,
            user_id=self.user.id,
            raw_uid="04AABBCCDD",
            actor_user_id=self.actor.id,
        )

        with self.assertRaises(CardAlreadyRegisteredError):
            assign_card(
                self.db,
                user_id=self.user.id,
                raw_uid="04 AA BB CC DD",
                actor_user_id=self.actor.id,
            )

        revoke_card(
            self.db,
            card_id=card.id,
            actor_user_id=self.actor.id,
            reason="Tarjeta sustituida",
        )
        self.assertEqual(card.status, "revoked")
        self.assertIsNotNone(card.revoked_at)

        with self.assertRaises(CardAlreadyRegisteredError):
            assign_card(
                self.db,
                user_id=self.user.id,
                raw_uid="04AABBCCDD",
                actor_user_id=self.actor.id,
            )

        actions = self.db.scalars(
            select(CardEvent.action)
            .where(CardEvent.card_id == card.id)
            .order_by(CardEvent.occurred_at, CardEvent.id)
        ).all()
        self.assertCountEqual(actions, ["assigned", "revoked"])

    def test_blocked_actor_cannot_assign_card(self):
        self.actor.is_blocked = True
        self.db.flush()

        with self.assertRaises(PermissionError):
            assign_card(
                self.db,
                user_id=self.user.id,
                raw_uid="04AABBCCDD",
                actor_user_id=self.actor.id,
            )

        self.assertEqual(self.db.scalars(select(UserCard)).all(), [])
        self.assertEqual(self.db.scalars(select(CardEvent)).all(), [])

    def test_revoked_amh_admin_cannot_assign_card(self):
        self.admin_access.status = "revoked"
        self.db.flush()

        with self.assertRaises(PermissionError):
            assign_card(
                self.db,
                user_id=self.user.id,
                raw_uid="04AABBCCDD",
                actor_user_id=self.actor.id,
            )

        self.assertEqual(self.db.scalars(select(UserCard)).all(), [])
        self.assertEqual(self.db.scalars(select(CardEvent)).all(), [])