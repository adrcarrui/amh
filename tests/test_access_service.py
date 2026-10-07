import unittest

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access_service import set_application_access
from app.authorization import has_application_access
from app.config import settings
from app.db import engine
from app.models import (
    AccessEvent,
    Application,
    User,
    UserApplicationAccess,
)


class AccessServiceTests(unittest.TestCase):
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

        self.actor = User(name="Admin", surname="Test", is_blocked=False)
        self.user = User(name="Usuario", surname="Test", is_blocked=False)
        self.amh = Application(
            code="amh", display_name="Access Management Hub", is_enabled=True
        )
        self.tams = Application(
            code="tams", display_name="TAMS", is_enabled=True
        )
        self.db.add_all([self.actor, self.user, self.amh, self.tams])
        self.db.flush()

        self.db.add(
            UserApplicationAccess(
                user_id=self.actor.id,
                application_id=self.amh.id,
                role="admin",
                status="active",
            )
        )
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def change(self, *, role="viewer", status="active", actor_id=None):
        return set_application_access(
            self.db,
            actor_user_id=actor_id or self.actor.id,
            user_id=self.user.id,
            application_code="tams",
            role=role,
            status=status,
            reason="Prueba",
        )

    def allowed(self):
        return has_application_access(
            self.db,
            user_id=self.user.id,
            application_code="tams",
        )

    def test_grant_role_block_and_revoke_are_audited(self):
        access = self.change()
        self.assertTrue(self.allowed())

        self.change(role="editor")
        self.assertTrue(self.allowed())

        self.change(role="editor", status="blocked")
        self.assertFalse(self.allowed())

        self.change(role="editor", status="revoked")
        self.assertFalse(self.allowed())

        events = self.db.scalars(
            select(AccessEvent).where(AccessEvent.access_id == access.id)
        ).all()
        self.assertCountEqual(
            [event.action for event in events],
            ["granted", "role_changed", "blocked", "revoked"],
        )
        self.assertTrue(
            all(event.actor_user_id == self.actor.id for event in events)
        )

        grant_event = next(e for e in events if e.action == "granted")
        self.assertIsNone(grant_event.old_status)
        self.assertEqual(grant_event.new_role, "viewer")

        revoke_event = next(e for e in events if e.action == "revoked")
        self.assertEqual(revoke_event.old_status, "blocked")
        self.assertEqual(revoke_event.new_status, "revoked")

    def test_absent_grant_cannot_be_blocked(self):
        with self.assertRaises(ValueError):
            self.change(status="blocked")

        self.assertFalse(self.allowed())
        self.assertEqual(self.db.scalars(select(AccessEvent)).all(), [])

    def test_non_admin_cannot_grant_access(self):
        with self.assertRaises(PermissionError):
            self.change(actor_id=self.user.id)

        self.assertFalse(self.allowed())
        self.assertEqual(self.db.scalars(select(AccessEvent)).all(), [])

    def test_admin_cannot_change_own_amh_access(self):
        with self.assertRaises(ValueError):
            set_application_access(
                self.db,
                actor_user_id=self.actor.id,
                user_id=self.actor.id,
                application_code="amh",
                role="viewer",
                status="active",
            )

        self.assertTrue(
            has_application_access(
                self.db,
                user_id=self.actor.id,
                application_code="amh",
                minimum_role="admin",
            )
        )