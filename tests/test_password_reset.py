"""Forgot-password and reset-token flow."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from werkzeug.security import check_password_hash, generate_password_hash

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_pwreset_unittest.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db  # noqa: E402
from itsdangerous import URLSafeTimedSerializer  # noqa: E402


class PasswordResetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        with app.app_context():
            db.create_all()

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        M = app.extensions.get("tm_test_models") or {}
        self.Account = M.get("Account")
        self.User = M.get("User")
        if self.User is not None:
            db.session.query(self.User).delete()
        if self.Account is not None:
            db.session.query(self.Account).delete()
            db.session.commit()

    def tearDown(self):
        if self.User is not None:
            db.session.query(self.User).delete()
        if self.Account is not None:
            db.session.query(self.Account).delete()
            db.session.commit()
        self.ctx.pop()

    def _make_account(self, email="resetme@example.com", password="old-password"):
        acc = self.Account(
            email=email,
            password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
            role="user",
            status="active",
            is_active=True,
        )
        db.session.add(acc)
        db.session.commit()
        return acc

    def _token_for(self, acc):
        import hashlib

        ser = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="password-reset")
        stamp = hashlib.sha256((acc.password_hash or "").encode("utf-8")).hexdigest()[:24]
        return ser.dumps({"id": int(acc.id), "ph": stamp})

    def test_login_page_has_forgot_password_link(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("/forgot-password", body)
        self.assertIn("Forgot password?", body)
        self.assertIn('id="auth-server-open"', body)
        self.assertIn('id="auth-server-dialog"', body)
        self.assertIn("Change server connection", body)
        self.assertIn("auth-server-connection.js", body)

    def test_forgot_password_unknown_login_still_succeeds(self):
        r = self.client.post(
            "/forgot-password",
            data={"login": "nobody@example.com"},
            follow_redirects=False,
        )
        self.assertIn(r.status_code, (302, 303))
        self.assertTrue((r.headers.get("Location") or "").endswith("/login"))

    @mock.patch("app.mail_service_mod.send_email", return_value=True)
    def test_forgot_password_emails_account_without_exposing_it(self, send_email):
        if self.Account is None:
            self.skipTest("Account model not registered")
        acc = self._make_account()
        r = self.client.post(
            "/forgot-password",
            data={"login": acc.email},
            follow_redirects=False,
        )
        self.assertIn(r.status_code, (302, 303))
        self.assertTrue((r.headers.get("Location") or "").endswith("/login"))
        send_email.assert_called_once()
        kwargs = send_email.call_args.kwargs
        self.assertEqual(kwargs["to_address"], acc.email)
        self.assertIn("/reset-password/", kwargs["text_body"])
        self.assertIn("Reset password", kwargs["html_body"])

    @mock.patch("app.mail_service_mod.send_email", side_effect=OSError("smtp unavailable"))
    @mock.patch("app._notify_admins_password_reset_failed", create=True)
    def test_forgot_password_does_not_expose_delivery_failure(self, _notify, _send):
        if self.Account is None:
            self.skipTest("Account model not registered")
        acc = self._make_account()
        r = self.client.post(
            "/forgot-password",
            data={"login": acc.email},
            follow_redirects=False,
        )
        self.assertIn(r.status_code, (302, 303))

    def test_reset_password_updates_hash_and_invalidates_token(self):
        if self.Account is None:
            self.skipTest("Account model not registered")
        acc = self._make_account()
        token = self._token_for(acc)
        r = self.client.post(
            f"/reset-password/{token}",
            data={"password": "new-password", "confirm": "new-password"},
            follow_redirects=False,
        )
        self.assertIn(r.status_code, (302, 303))
        db.session.refresh(acc)
        self.assertTrue(check_password_hash(acc.password_hash, "new-password"))
        r2 = self.client.get(f"/reset-password/{token}", follow_redirects=False)
        self.assertIn(r2.status_code, (302, 303))
        self.assertIn("/forgot-password", r2.headers.get("Location") or "")
