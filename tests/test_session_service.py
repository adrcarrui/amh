import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.models import Application, User, UserApplicationAccess, UserSession
from app.session_service import (
    create_admin_session,
    get_admin_session_user_id,
    revoke_admin_session,
)


class SessionServiceTests(unittest.TestCase):
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

        self.user = User(name="Admin", surname="Sesiones", is_blocked=False)
        self.application = Application(
            code="amh",
            display_name="Access Management Hub",
            is_enabled=True,
        )
        self.db.add_all([self.user, self.application])
        self.db.flush()

        self.access = UserApplicationAccess(
            user_id=self.user.id,
            application_id=self.application.id,
            role="admin",
            status="active",
        )
        self.db.add(self.access)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def test_create_and_validate_session(self):
        token = create_admin_session(self.db, user_id=self.user.id)
        stored = self.db.scalar(select(UserSession))

        self.assertIsNotNone(stored)
        self.assertNotEqual(stored.session_hash, token)
        self.assertEqual(stored.auth_method, "oidc")
        self.assertEqual(
            get_admin_session_user_id(self.db, token=token),
            self.user.id,
        )

    def test_idle_session_expires(self):
        token = create_admin_session(self.db, user_id=self.user.id)
        stored = self.db.scalar(select(UserSession))
        stored.last_seen_at = datetime.now(timezone.utc) - timedelta(
            minutes=16
        )
        self.db.flush()

        self.assertIsNone(
            get_admin_session_user_id(self.db, token=token)
        )
        self.assertIsNotNone(stored.revoked_at)

    def test_blocked_user_loses_open_session(self):
        token = create_admin_session(self.db, user_id=self.user.id)
        self.user.is_blocked = True
        self.db.flush()

        self.assertIsNone(
            get_admin_session_user_id(self.db, token=token)
        )

    def test_logout_revokes_session(self):
        token = create_admin_session(self.db, user_id=self.user.id)

        revoke_admin_session(self.db, token=token)

        self.assertIsNone(
            get_admin_session_user_id(self.db, token=token)
        )

    def test_revoked_amh_access_invalidates_open_session(self):
        token = create_admin_session(self.db, user_id=self.user.id)
        self.access.status = "revoked"
        self.db.flush()

        self.assertIsNone(
            get_admin_session_user_id(self.db, token=token)
        )
        stored = self.db.scalar(select(UserSession))
        self.assertIsNotNone(stored.revoked_at)

    def test_role_downgrade_invalidates_open_session(self):
        token = create_admin_session(self.db, user_id=self.user.id)
        self.access.role = "viewer"
        self.db.flush()

        self.assertIsNone(
            get_admin_session_user_id(self.db, token=token)
        )

    def test_disabled_application_invalidates_open_session(self):
        token = create_admin_session(self.db, user_id=self.user.id)
        self.application.is_enabled = False
        self.db.flush()

        self.assertIsNone(
            get_admin_session_user_id(self.db, token=token)
        )

    def test_absolute_expiry_invalidates_open_session(self):
        token = create_admin_session(self.db, user_id=self.user.id)
        stored = self.db.scalar(select(UserSession))
        stored.expires_at = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
        self.db.flush()

        self.assertIsNone(
            get_admin_session_user_id(self.db, token=token)
        )