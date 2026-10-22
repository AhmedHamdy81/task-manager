"""Google and Apple sign-in on /login."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from werkzeug.security import generate_password_hash

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_oauth_login_unittest.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db  # noqa: E402
import oauth_login_support as oauth  # noqa: E402


class OAuthLoginTests(unittest.TestCase):
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
        self.Identity = M.get("AccountOAuthIdentity")
        self.User = M.get("User")
        if self.Identity is not None:
            db.session.query(self.Identity).delete()
        if self.User is not None:
            db.session.query(self.User).delete()
        if self.Account is not None:
            db.session.query(self.Account).delete()
        db.session.commit()

    def tearDown(self):
        if self.Identity is not None:
            db.session.query(self.Identity).delete()
        if self.User is not None:
            db.session.query(self.User).delete()
        if self.Account is not None:
            db.session.query(self.Account).delete()
        db.session.commit()
        self.ctx.pop()

    def _account(self, email="colorist@example.com", password="secret-pass"):
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

    def test_login_page_hides_oauth_when_not_configured(self):
        with mock.patch.object(oauth, "google_configured", return_value=False), mock.patch.object(
            oauth, "apple_configured", return_value=False
        ):
            r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertNotIn("Continue with Google", body)
        self.assertNotIn("Continue with Apple", body)
        self.assertNotIn("/login/google", body)
        self.assertNotIn("/login/apple", body)

    def test_login_page_has_google_and_apple_buttons(self):
        with mock.patch.object(oauth, "google_configured", return_value=True), mock.patch.object(
            oauth, "apple_configured", return_value=True
        ):
            r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("Continue with Google", body)
        self.assertIn("Continue with Apple", body)
        self.assertIn("/login/google", body)
        self.assertIn("/login/apple", body)

    def test_google_start_without_config_returns_to_login(self):
        with mock.patch.object(oauth, "google_configured", return_value=False):
            r = self.client.get("/login/google", follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        loc = r.headers.get("Location") or ""
        self.assertIn("/login", loc)
        self.assertNotIn("accounts.google.com", loc)

    def test_google_start_redirects_to_google(self):
        with mock.patch.object(oauth, "google_configured", return_value=True), mock.patch.object(
            oauth, "google_client_id", return_value="test-google-client"
        ):
            r = self.client.get("/login/google", follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        loc = r.headers.get("Location") or ""
        self.assertTrue(loc.startswith("https://accounts.google.com/o/oauth2/v2/auth"))
        qs = parse_qs(urlparse(loc).query)
        self.assertEqual(qs.get("client_id"), ["test-google-client"])
        self.assertTrue(qs.get("state"))

    def test_google_callback_logs_in_existing_email(self):
        if self.Account is None:
            self.skipTest("Account model not registered")
        acc = self._account()
        state = oauth.dump_oauth_state(app.config["SECRET_KEY"], {"p": "google", "n": "n1", "next": "/"})
        profile = {
            "provider": "google",
            "sub": "google-sub-1",
            "email": acc.email,
            "name": "Colorist",
        }
        with mock.patch.object(oauth, "exchange_google_code", return_value=profile):
            r = self.client.get(
                f"/login/google/callback?state={state}&code=fake",
                follow_redirects=False,
            )
        self.assertIn(r.status_code, (302, 303))
        loc = r.headers.get("Location") or ""
        self.assertFalse(loc.endswith("/login"))
        ident = self.Identity.query.filter_by(provider="google", subject="google-sub-1").first()
        self.assertIsNotNone(ident)
        self.assertEqual(ident.account_id, acc.id)
        r2 = self.client.get("/login", follow_redirects=False)
        self.assertIn(r2.status_code, (302, 303))

    def test_google_callback_unknown_email_without_public_register(self):
        state = oauth.dump_oauth_state(app.config["SECRET_KEY"], {"p": "google", "n": "n1", "next": "/"})
        profile = {
            "provider": "google",
            "sub": "google-sub-new",
            "email": "nobody-oauth@example.com",
            "name": "New Person",
        }
        old = app.config.get("ALLOW_PUBLIC_REGISTER")
        app.config["ALLOW_PUBLIC_REGISTER"] = False
        try:
            with mock.patch.object(oauth, "exchange_google_code", return_value=profile):
                r = self.client.get(
                    f"/login/google/callback?state={state}&code=fake",
                    follow_redirects=False,
                )
        finally:
            app.config["ALLOW_PUBLIC_REGISTER"] = old
        self.assertIn(r.status_code, (302, 303))
        loc = r.headers.get("Location") or ""
        self.assertIn("/login", loc)
        self.assertNotIn("accounts.google.com", loc)

    def test_apple_start_redirects_when_configured(self):
        with mock.patch.object(oauth, "apple_configured", return_value=True), mock.patch.object(
            oauth, "apple_client_id", return_value="com.bigbang.signin"
        ):
            r = self.client.get("/login/apple", follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        loc = r.headers.get("Location") or ""
        self.assertTrue(loc.startswith("https://appleid.apple.com/auth/authorize"))
        qs = parse_qs(urlparse(loc).query)
        self.assertEqual(qs.get("response_mode"), ["form_post"])

    def test_apple_callback_logs_in_existing_email(self):
        if self.Account is None:
            self.skipTest("Account model not registered")
        acc = self._account(email="apple.user@example.com")
        state = oauth.dump_oauth_state(app.config["SECRET_KEY"], {"p": "apple", "n": "n2", "next": "/"})
        profile = {
            "provider": "apple",
            "sub": "apple-sub-1",
            "email": acc.email,
            "name": "",
        }
        with mock.patch.object(oauth, "verify_apple_id_token", return_value=profile):
            r = self.client.post(
                "/login/apple/callback",
                data={"state": state, "id_token": "fake.jwt"},
                follow_redirects=False,
            )
        self.assertIn(r.status_code, (302, 303))
        ident = self.Identity.query.filter_by(provider="apple", subject="apple-sub-1").first()
        self.assertIsNotNone(ident)
        self.assertEqual(ident.account_id, acc.id)


if __name__ == "__main__":
    unittest.main()
