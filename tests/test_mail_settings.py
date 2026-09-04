"""System Setup email settings and password-reset mail config."""

from __future__ import annotations

import os
import smtplib
import socket
import tempfile
import unittest
from unittest import mock

from werkzeug.security import generate_password_hash

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_mail_settings_unittest.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

import mail_settings as mail_settings_mod  # noqa: E402
from app import app, db  # noqa: E402
import system_seed as sseed  # noqa: E402


class MailSettingsUnitTests(unittest.TestCase):
    def test_provider_presets(self):
        gmail = mail_settings_mod.provider_preset("gmail")
        self.assertEqual(gmail["server"], "smtp.gmail.com")
        self.assertEqual(gmail["port"], "587")
        self.assertEqual(gmail["encryption"], "starttls")
        m365 = mail_settings_mod.provider_preset("microsoft365")
        self.assertEqual(m365["server"], "smtp.office365.com")
        self.assertEqual(m365["encryption"], "starttls")

    def test_public_url_normalization(self):
        self.assertEqual(
            mail_settings_mod.normalize_public_application_url(
                "https://bigbang.example.com/",
                require_https_in_production=False,
            ),
            "https://bigbang.example.com",
        )
        self.assertIsNone(
            mail_settings_mod.normalize_public_application_url(
                "javascript:alert(1)",
                require_https_in_production=False,
            )
        )
        self.assertIsNone(
            mail_settings_mod.normalize_public_application_url(
                "https://bigbang.example.com/?x=1",
                require_https_in_production=False,
            )
        )

    def test_validate_port_and_expiry(self):
        errors = mail_settings_mod.validate_mail_settings(
            {
                "mail_enabled": "0",
                "mail_port": "99999",
                "mail_reset_expiry_minutes": "5",
                "mail_encryption": "starttls",
                "mail_provider": "custom",
            }
        )
        self.assertTrue(any("port" in e.lower() for e in errors))
        self.assertTrue(any("expiry" in e.lower() for e in errors))

    def test_sanitize_smtp_errors(self):
        self.assertIn(
            "Authentication",
            mail_settings_mod.sanitize_smtp_error(smtplib.SMTPAuthenticationError(535, b"bad")),
        )
        self.assertIn(
            "timed out",
            mail_settings_mod.sanitize_smtp_error(TimeoutError("timed out")).lower(),
        )
        msg = mail_settings_mod.sanitize_smtp_error(smtplib.SMTPAuthenticationError(535, b"secret-password"))
        self.assertNotIn("secret-password", msg)

    def test_example_reset_url_is_fake(self):
        url = mail_settings_mod.example_reset_url("https://studio.example.com")
        self.assertIn("preview-token-not-real", url)
        self.assertTrue(url.startswith("https://studio.example.com/"))


class MailSettingsRouteTests(unittest.TestCase):
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
        mail_settings_mod.clear_test_email_rate_limits()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.app_root = self._tmpdir.name
        os.makedirs(os.path.join(self.app_root, "instance"), exist_ok=True)
        self._env_pop = []
        for key in ("MAIL_PASSWORD", "MAIL_ENABLED", "MAIL_SERVER"):
            if key in os.environ:
                self._env_pop.append((key, os.environ.pop(key)))

    def tearDown(self):
        for key, value in self._env_pop:
            os.environ[key] = value
        path = mail_settings_mod.mail_password_file_path(self.app_root)
        if os.path.isfile(path):
            os.remove(path)
        self._tmpdir.cleanup()
        db.session.remove()
        self.ctx.pop()

    def _make_account(self, *, role="admin", email="mail-admin@test.local"):
        acc = self.Account(
            email=email,
            password_hash=generate_password_hash("password123", method="pbkdf2:sha256"),
            role=role,
            status="active",
            is_active=True,
        )
        db.session.add(acc)
        db.session.flush()
        db.session.add(self.User(name="Mail Admin", email=email, account_id=acc.id))
        db.session.commit()
        return acc

    def _login(self, acc):
        with self.client.session_transaction() as sess:
            sess["account_id"] = acc.id

    def _valid_payload(self, **overrides):
        data = {
            "mail_enabled": "1",
            "mail_provider": "custom",
            "mail_server": "smtp.example.com",
            "mail_port": "587",
            "mail_encryption": "starttls",
            "mail_username": "mailer@example.com",
            "mail_password": "",
            "mail_sender_name": "Studio",
            "mail_sender_email": "noreply@example.com",
            "public_application_url": "https://bigbang.example.com",
            "mail_reset_expiry_minutes": "60",
            "mail_admin_fallback": "1",
            "replace_password": "0",
        }
        data.update(overrides)
        return data

    def test_access_denied_for_non_admin(self):
        user = self._make_account(role="user", email="user@test.local")
        self._login(user)
        r = self.client.get("/control/system-setup?section=email", follow_redirects=False)
        self.assertIn(r.status_code, (302, 303, 403))
        if r.status_code in (302, 303):
            self.assertTrue((r.headers.get("Location") or "").endswith("/"))
        r2 = self.client.post(
            "/control/system-setup/email",
            data=self._valid_payload(),
            follow_redirects=False,
        )
        self.assertIn(r2.status_code, (302, 303, 403))

    def test_section_renders_for_admin(self):
        admin = self._make_account()
        self._login(admin)
        r = self.client.get("/control/system-setup?section=email")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("system-setup-email", body)
        self.assertIn("Email &amp; Password Reset", body)
        self.assertNotIn("secret-smtp-password", body)
        self.assertNotIn('name="mail_password" value="', body)

    def test_existing_password_never_returned(self):
        admin = self._make_account()
        self._login(admin)
        secret_path = os.path.join(self.app_root, "instance", ".mail_smtp_password")
        mail_settings_mod.write_mail_password_secret("super-secret-pw", app_root=self.app_root)
        with mock.patch(
            "system_seed_routes.app_root", self.app_root, create=True
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.mail_password_file_path",
            return_value=secret_path,
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.read_mail_password_secret",
            return_value="super-secret-pw",
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.mail_password_configured",
            return_value=True,
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.mail_password_source",
            return_value="secret_file",
        ):
            sseed.set_system_setting(db, self.SystemSetting, "mail_server", "smtp.example.com")
            db.session.commit()
            r = self.client.get("/control/system-setup?section=email")
        body = r.get_data(as_text=True)
        self.assertNotIn("super-secret-pw", body)
        self.assertNotIn("value=\"super-secret-pw\"", body)

    def test_empty_password_preserves_secret(self):
        admin = self._make_account()
        self._login(admin)
        secret_path = os.path.join(self.app_root, "instance", ".mail_smtp_password")
        mail_settings_mod.write_mail_password_secret("keep-me", app_root=self.app_root)
        with mock.patch(
            "system_seed_routes.mail_settings_mod.mail_password_file_path",
            return_value=secret_path,
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.mail_password_configured",
            return_value=True,
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.read_mail_password_secret",
            return_value="keep-me",
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.write_mail_password_secret"
        ) as write_pw:
            payload = self._valid_payload(mail_password="", replace_password="0")
            r = self.client.post(
                "/control/system-setup/email",
                data=payload,
                headers={"Accept": "application/json"},
            )
        self.assertEqual(r.status_code, 200)
        write_pw.assert_not_called()
        self.assertEqual(
            mail_settings_mod.read_mail_password_secret(app_root=self.app_root),
            "keep-me",
        )

    def test_save_starttls_and_ssl_config(self):
        admin = self._make_account()
        self._login(admin)
        mail_settings_mod.write_mail_password_secret("pw", app_root=self.app_root)
        with mock.patch(
            "system_seed_routes.mail_settings_mod.mail_password_configured",
            return_value=True,
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.read_mail_password_secret",
            return_value="pw",
        ):
            r = self.client.post(
                "/control/system-setup/email",
                data=self._valid_payload(mail_encryption="starttls", mail_port="587"),
                headers={"Accept": "application/json"},
            )
            self.assertEqual(r.status_code, 200)
            self.assertEqual(app.config.get("MAIL_USE_TLS"), "1")
            self.assertEqual(app.config.get("MAIL_USE_SSL"), "0")

            r2 = self.client.post(
                "/control/system-setup/email",
                data=self._valid_payload(mail_encryption="ssl", mail_port="465"),
                headers={"Accept": "application/json"},
            )
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(app.config.get("MAIL_USE_SSL"), "1")
            self.assertEqual(app.config.get("MAIL_USE_TLS"), "0")

    def test_validation_rejects_incomplete_enabled_config(self):
        admin = self._make_account()
        self._login(admin)
        r = self.client.post(
            "/control/system-setup/email",
            data=self._valid_payload(mail_server="", mail_password="x", replace_password="1"),
            headers={"Accept": "application/json"},
        )
        self.assertEqual(r.status_code, 400)
        payload = r.get_json()
        self.assertFalse(payload.get("ok"))

    @mock.patch("system_seed_routes.mail_service_mod.send_email", return_value=True)
    def test_successful_test_email(self, send_email):
        admin = self._make_account()
        self._login(admin)
        mail_settings_mod.clear_test_email_rate_limits()
        with mock.patch(
            "system_seed_routes.mail_settings_mod.read_mail_password_secret",
            return_value="pw",
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.mail_password_configured",
            return_value=True,
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.check_test_email_rate_limit",
            return_value=(True, 0),
        ):
            r = self.client.post(
                "/control/system-setup/email/test",
                data=self._valid_payload(test_recipient="admin@example.com"),
                headers={"Accept": "application/json"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json().get("ok"))
        send_email.assert_called_once()
        kwargs = send_email.call_args.kwargs
        self.assertEqual(kwargs["to_address"], "admin@example.com")
        self.assertIn("SMTP configuration is working", kwargs["text_body"])

    @mock.patch(
        "system_seed_routes.mail_service_mod.send_email",
        side_effect=smtplib.SMTPAuthenticationError(535, b"bad"),
    )
    def test_test_email_auth_failure_sanitized(self, _send):
        admin = self._make_account()
        self._login(admin)
        mail_settings_mod.clear_test_email_rate_limits()
        with mock.patch(
            "system_seed_routes.mail_settings_mod.read_mail_password_secret",
            return_value="pw",
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.mail_password_configured",
            return_value=True,
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.check_test_email_rate_limit",
            return_value=(True, 0),
        ):
            r = self.client.post(
                "/control/system-setup/email/test",
                data=self._valid_payload(test_recipient="admin@example.com"),
                headers={"Accept": "application/json"},
            )
        self.assertEqual(r.status_code, 502)
        err = r.get_json().get("error") or ""
        self.assertIn("Authentication", err)
        self.assertNotIn("pw", err)

    @mock.patch(
        "system_seed_routes.mail_service_mod.send_email",
        side_effect=socket.timeout("timed out"),
    )
    def test_test_email_timeout_sanitized(self, _send):
        admin = self._make_account()
        self._login(admin)
        mail_settings_mod.clear_test_email_rate_limits()
        with mock.patch(
            "system_seed_routes.mail_settings_mod.read_mail_password_secret",
            return_value="pw",
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.mail_password_configured",
            return_value=True,
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.check_test_email_rate_limit",
            return_value=(True, 0),
        ):
            r = self.client.post(
                "/control/system-setup/email/test",
                data=self._valid_payload(test_recipient="admin@example.com"),
                headers={"Accept": "application/json"},
            )
        self.assertEqual(r.status_code, 502)
        self.assertIn("timed out", (r.get_json().get("error") or "").lower())

    @mock.patch("system_seed_routes.mail_service_mod.send_email", return_value=True)
    def test_test_email_rate_limit(self, send_email):
        admin = self._make_account()
        self._login(admin)
        mail_settings_mod.clear_test_email_rate_limits()
        with mock.patch(
            "system_seed_routes.mail_settings_mod.read_mail_password_secret",
            return_value="pw",
        ), mock.patch(
            "system_seed_routes.mail_settings_mod.mail_password_configured",
            return_value=True,
        ):
            r1 = self.client.post(
                "/control/system-setup/email/test",
                data=self._valid_payload(test_recipient="admin@example.com"),
                headers={"Accept": "application/json"},
            )
            r2 = self.client.post(
                "/control/system-setup/email/test",
                data=self._valid_payload(test_recipient="admin@example.com"),
                headers={"Accept": "application/json"},
            )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 429)
        self.assertEqual(send_email.call_count, 1)

    def test_arabic_rtl_rendering(self):
        admin = self._make_account()
        self._login(admin)
        with self.client.session_transaction() as sess:
            sess["lang"] = "ar"
        r = self.client.get("/control/system-setup?section=email")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn('lang="ar"', body)
        self.assertIn('dir="rtl"', body)
        self.assertIn("system-setup-email", body)
        self.assertTrue(
            "البريد الإلكتروني وإعادة تعيين كلمة المرور" in body
            or "Email &amp; Password Reset" in body
        )


class PasswordResetMailIntegrationTests(unittest.TestCase):
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
        self.SystemSetting = app.extensions["system_seed"]["system_seed_models"].SystemSetting
        try:
            db.session.query(self.M["User"]).delete()
        except Exception:
            db.session.rollback()
        db.session.query(self.Account).delete()
        db.session.query(self.SystemSetting).delete()
        db.session.commit()
        sseed.set_system_setting(
            db,
            self.SystemSetting,
            sseed.CONNECTION_HTTP_ADDRESS_KEY,
            "https://bigbang.example.com",
            description=sseed.CONNECTION_HTTP_ADDRESS_DESCRIPTION,
        )
        db.session.commit()
        app.config["MAIL_RESET_EXPIRY_MINUTES"] = 90
        app.config["MAIL_ADMIN_FALLBACK_ON_FAILURE"] = True

    def tearDown(self):
        app.config["MAIL_RESET_EXPIRY_MINUTES"] = 60
        try:
            db.session.query(self.M["User"]).delete()
        except Exception:
            db.session.rollback()
        db.session.query(self.Account).delete()
        db.session.query(self.SystemSetting).delete()
        db.session.commit()
        db.session.remove()
        self.ctx.pop()

    def _make_account(self):
        acc = self.Account(
            email="resetme@example.com",
            password_hash=generate_password_hash("old-password", method="pbkdf2:sha256"),
            role="user",
            status="active",
            is_active=True,
        )
        db.session.add(acc)
        db.session.commit()
        return acc

    @mock.patch("app.mail_service_mod.send_email", return_value=True)
    def test_public_reset_url_uses_configured_base(self, send_email):
        acc = self._make_account()
        r = self.client.post("/forgot-password", data={"login": acc.email})
        self.assertIn(r.status_code, (302, 303))
        body = send_email.call_args.kwargs["text_body"]
        self.assertIn("https://bigbang.example.com/reset-password/", body)
        self.assertNotIn("127.0.0.1", body)
        self.assertNotIn("localhost", body)

    @mock.patch("app.mail_service_mod.send_email", return_value=True)
    def test_configured_expiry_in_email(self, send_email):
        acc = self._make_account()
        self.client.post("/forgot-password", data={"login": acc.email})
        html = send_email.call_args.kwargs["html_body"]
        self.assertIn("90 minutes", html)

    @mock.patch("app.mail_service_mod.send_email", return_value=True)
    def test_generic_forgot_password_response(self, send_email):
        acc = self._make_account()
        known = self.client.post(
            "/forgot-password", data={"login": acc.email}, follow_redirects=False
        )
        unknown = self.client.post(
            "/forgot-password",
            data={"login": "nobody-missing@example.com"},
            follow_redirects=False,
        )
        self.assertIn(known.status_code, (302, 303))
        self.assertIn(unknown.status_code, (302, 303))
        self.assertTrue((known.headers.get("Location") or "").endswith("/login"))
        self.assertEqual(known.headers.get("Location"), unknown.headers.get("Location"))
        send_email.assert_called_once()
        # Response must not include the reset token.
        self.assertNotIn("reset-password", known.headers.get("Location") or "")

    @mock.patch("app.mail_service_mod.send_email", return_value=True)
    def test_no_token_or_password_in_logs(self, send_email):
        acc = self._make_account()
        with self.assertLogs(app.logger, level="INFO") as captured:
            app.logger.info("baseline before reset")
            self.client.post("/forgot-password", data={"login": acc.email})
        joined = "\n".join(captured.output)
        token_part = send_email.call_args.kwargs["text_body"].split("/reset-password/")[-1].split()[0]
        self.assertNotIn(token_part, joined)
        self.assertNotIn("MAIL_PASSWORD", joined)

    @mock.patch("app.mail_service_mod.send_email", side_effect=OSError("smtp down"))
    def test_admin_fallback_on_failure(self, _send):
        acc = self._make_account()
        app.config["MAIL_ADMIN_FALLBACK_ON_FAILURE"] = True
        with mock.patch("app.account_approval_support_mod.notify_users") as notify_users:
            r = self.client.post(
                "/forgot-password",
                data={"login": acc.email},
                follow_redirects=False,
            )
            self.assertIn(r.status_code, (302, 303))
            if notify_users.called:
                kwargs = notify_users.call_args.kwargs
                msg = kwargs.get("message") or ""
                self.assertNotIn("/reset-password/", msg)
                self.assertNotIn("token", msg.lower())

    def test_production_rejects_localhost_public_url(self):
        with mock.patch.object(mail_settings_mod.security_support_mod, "is_production_env", return_value=True):
            self.assertIsNone(
                mail_settings_mod.normalize_public_application_url("http://127.0.0.1:5001")
            )
            self.assertIsNone(
                mail_settings_mod.normalize_public_application_url("http://localhost:5001")
            )


if __name__ == "__main__":
    unittest.main()
