import unittest

from sqlalchemy.orm import Session

from app.authorization import has_application_access
from app.config import settings
from app.db import engine
from app.models import Application, User, UserApplicationAccess


class AuthorizationTests(unittest.TestCase):
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

        self.user = User(name="Usuario", surname="Test", is_blocked=False)
        self.tams = Application(
            code="tams", display_name="TAMS", is_enabled=True
        )
        self.mysim = Application(
            code="mysim_dashboard",
            display_name="mySim Dashboard",
            is_enabled=True,
        )
        self.db.add_all([self.user, self.tams, self.mysim])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def grant(self, application, role="viewer", status="active"):
        access = UserApplicationAccess(
            user_id=self.user.id,
            application_id=application.id,
            role=role,
            status=status,
        )
        self.db.add(access)
        self.db.flush()
        return access

    def allowed(self, code, role="viewer"):
        return has_application_access(
            self.db,
            user_id=self.user.id,
            application_code=code,
            minimum_role=role,
        )

    def test_absent_grant_denies_access(self):
        self.assertFalse(self.allowed("tams"))

    def test_role_hierarchy(self):
        self.grant(self.tams, role="editor")
        self.assertTrue(self.allowed("tams", "viewer"))
        self.assertTrue(self.allowed("tams", "editor"))
        self.assertFalse(self.allowed("tams", "admin"))

    def test_global_block_and_disabled_application(self):
        self.grant(self.tams)
        self.assertTrue(self.allowed("tams"))

        self.user.is_blocked = True
        self.db.flush()
        self.assertFalse(self.allowed("tams"))

        self.user.is_blocked = False
        self.tams.is_enabled = False
        self.db.flush()
        self.assertFalse(self.allowed("tams"))

    def test_application_block_and_revocation_are_independent(self):
        tams_access = self.grant(self.tams)
        self.grant(self.mysim)
        self.assertTrue(self.allowed("tams"))
        self.assertTrue(self.allowed("mysim_dashboard"))

        tams_access.status = "blocked"
        self.db.flush()
        self.assertFalse(self.allowed("tams"))
        self.assertTrue(self.allowed("mysim_dashboard"))

        tams_access.status = "revoked"
        self.db.flush()
        self.assertFalse(self.allowed("tams"))
        self.assertTrue(self.allowed("mysim_dashboard"))