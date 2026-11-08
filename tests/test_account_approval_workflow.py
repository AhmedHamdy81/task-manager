"""Tests for user registration and role-change approval workflow."""

from __future__ import annotations

import os
import tempfile
import unittest

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_approval_unittest.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from werkzeug.security import generate_password_hash  # noqa: E402

from app import app, db  # noqa: E402
import account_approval_support as aas  # noqa: E402


def _model(name: str):
    """Models are defined inside create_app(), so they are looked up in the SQLAlchemy registry."""
    return db.Model.registry._class_registry[name]  # noqa: SLF001


class AccountApprovalWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.Account, self.User = _model("Account"), _model("User")
        self.ApprovalRequest, self.RoleChangeRequest = _model("UserApprovalRequest"), _model("RoleChangeRequest")
        # Public signup is off by default; these tests opt in explicitly.
        self._old_register = app.config.get("ALLOW_PUBLIC_REGISTER")
        app.config["ALLOW_PUBLIC_REGISTER"] = True
        self._wipe()

    def tearDown(self):
        app.config["ALLOW_PUBLIC_REGISTER"] = self._old_register
        self._wipe()
        self.ctx.pop()

    def _wipe(self):
        for model in (self.RoleChangeRequest, self.ApprovalRequest, self.User, self.Account):
            db.session.query(model).delete()
        db.session.commit()

    def test_registration_creates_pending_account(self):
        resp = self.client.post(
            "/register",
            data={
                "name": "Pending User",
                "email": "pending@example.com",
                "password": "password123",
                "confirm": "password123",
                "company": "Test Co",
                "department_code": "editing",
            },
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (302, 303))
        acc = self.Account.query.filter_by(email="pending@example.com").first()
        self.assertIsNotNone(acc)
        self.assertEqual(aas.normalized_account_status(acc.status), aas.STATUS_PENDING_APPROVAL)
        self.assertFalse(acc.is_active)
        req = self.ApprovalRequest.query.filter_by(account_id=acc.id).first()
        self.assertIsNotNone(req)
        self.assertEqual(req.status, aas.REQUEST_PENDING)

    def test_registration_is_closed_unless_enabled(self):
        app.config["ALLOW_PUBLIC_REGISTER"] = False
        resp = self.client.post("/register", data={"name": "X", "email": "closed@example.com",
                                                   "password": "password123", "confirm": "password123"})
        self.assertIn(resp.status_code, (302, 303))
        self.assertIsNone(self.Account.query.filter_by(email="closed@example.com").first())

    def test_pending_user_login_redirects_to_pending_page(self):
        acc = self.Account(
            email="wait@example.com",
            password_hash=generate_password_hash("password123", method="pbkdf2:sha256"),
            role="user",
            status=aas.STATUS_PENDING_APPROVAL,
            is_active=False,
        )
        db.session.add(acc)
        db.session.flush()
        db.session.add(self.User(name="Wait User", email="wait@example.com", account_id=acc.id))
        db.session.commit()

        resp = self.client.post(
            "/login",
            data={"login": "wait@example.com", "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/account/pending", resp.headers.get("Location", ""))
        self.assertEqual(self.client.get("/projects").status_code, 302)

    def test_sensitive_profile_change_creates_role_request(self):
        acc = self.Account(
            email="active@example.com",
            password_hash=generate_password_hash("password123", method="pbkdf2:sha256"),
            role="user",
            status=aas.STATUS_ACTIVE,
            is_active=True,
        )
        db.session.add(acc)
        db.session.flush()
        jt = _model("JobTitle").query.first()
        user = self.User(
            name="Active User",
            email="active@example.com",
            account_id=acc.id,
            job_title_id=jt.id if jt else None,
        )
        db.session.add(user)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess["account_id"] = acc.id

        resp = self.client.post(
            "/profile",
            data={
                "action": "profile",
                "name": "Active User",
                "email": "active@example.com",
                "company": "New Company Ltd",
            },
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (302, 303))
        row = self.RoleChangeRequest.query.filter_by(user_id=user.id).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.status, aas.ROLE_REQUEST_PENDING)
        self.assertEqual(row.requested_company, "New Company Ltd")
        db.session.refresh(user)
        self.assertNotEqual(user.company, "New Company Ltd")


if __name__ == "__main__":
    unittest.main()
