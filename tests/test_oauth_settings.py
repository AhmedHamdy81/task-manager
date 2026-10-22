"""System Setup Google / Apple sign-in credentials."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from werkzeug.security import generate_password_hash

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_oauth_settings_unittest.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

import oauth_settings as oauth_settings_mod  # noqa: E402
from app import app, db  # noqa: E402
import oauth_login_support as oauth_login  # noqa: E402


class OAuthSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        with app.app_context():
            db.create_all()

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        self.Account = self.M["Account"]
        self.User = self.M["User"]
        self.SystemSetting = self.M.get("SystemSetting") or app.extensions["system_seed"][
            "system_seed_models"
        ].SystemSetting
        db.session.query(self.User).delete()
        db.session.query(self.Account).delete()
        db.session.query(self.SystemSetting).delete()
        db.session.commit()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.app_root = self._tmpdir.name
        os.makedirs(os.path.join(self.app_root, "instance"), exist_ok=True)
        self._env_pop = []
        for key in (
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        ):
            if key in os.environ:
                self._env_pop.append((key, os.environ.pop(key)))

    def tearDown(self):
        for key, value in self._env_pop:
            os.environ[key] = value
        self._tmpdir.cleanup()
        db.session.remove()
        self.ctx.pop()

    def _make_admin(self):
        acc = self.Account(
            email="oauth-admin@test.local",
            password_hash=generate_password_hash("password123", method="pbkdf2:sha256"),
            role="admin",
            status="active",
            is_active=True,
        )
        db.session.add(acc)
        db.session.flush()
        db.session.add(self.User(name="OAuth Admin", email=acc.email, account_id=acc.id))
        db.session.commit()
        return acc

    def test_saved_google_credentials_enable_sign_in(self):
        oauth_settings_mod.save_oauth_settings(
            db,
            self.SystemSetting,
            {
                "google_client_id": "123.apps.googleusercontent.com",
                "google_client_secret": "google-secret",
                "apple_client_id": "",
            },
            app_root=self.app_root,
            replace_secret=True,
        )
        cfg = oauth_settings_mod.resolve_oauth_config(
            self.SystemSetting, app_root=self.app_root, include_secret=True
        )
        self.assertTrue(cfg.google_configured)
        self.assertEqual(cfg.google_client_id, "123.apps.googleusercontent.com")
        self.assertEqual(cfg.google_client_secret, "google-secret")

    def test_signin_setup_page_for_admin(self):
        acc = self._make_admin()
        with self.client.session_transaction() as sess:
            sess["account_id"] = acc.id
        r = self.client.get("/control/system-setup/signin")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("Google client ID", body)
        self.assertIn("/login/google/callback", body)

    def test_admin_can_save_google_client_id(self):
        acc = self._make_admin()
        with self.client.session_transaction() as sess:
            sess["account_id"] = acc.id
        with mock.patch.object(oauth_settings_mod, "write_google_client_secret"):
            r = self.client.post(
                "/control/system-setup/signin",
                data={
                    "google_client_id": "web-client.apps.googleusercontent.com",
                    "google_client_secret": "from-console",
                    "apple_client_id": "",
                },
                follow_redirects=False,
            )
        self.assertIn(r.status_code, (302, 303))
        self.assertIn("/control/system-setup/signin", r.headers.get("Location") or "")
        stored = self.SystemSetting.query.filter_by(key="google_oauth_client_id").first()
        self.assertIsNotNone(stored)
        self.assertEqual(stored.value, "web-client.apps.googleusercontent.com")

    def test_login_google_message_without_credentials(self):
        with mock.patch.object(oauth_login, "google_configured", return_value=False):
            r = self.client.get("/login/google", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Google sign-in isn", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
