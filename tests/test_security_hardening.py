"""Security hardening tests — production config, paths, uploads, CSRF, storage perms."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from unittest import mock

# Isolate from instance DB before importing app-dependent modules.
_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_security_pass2.db")
os.close(_fd)
os.environ["TASK_MANAGER_TEST_DATABASE"] = f"sqlite:///{_TEST_DB_PATH}"
# Ensure production guards are not active during import.
os.environ.pop("APP_ENV", None)
os.environ.pop("FLASK_ENV", None)


STRONG = "Zq3v9mJx2LkP8sT4wYb7Nc1Rf6Hd0Ge5Ua_strong-test-secret"
PROD = {
    "APP_ENV": "production",
    "SECRET_KEY": STRONG,
    "SESSION_COOKIE_SECURE": "1",
    "SOCKETIO_CORS_ORIGINS": "https://app.example.com",
    "ALLOWED_HOSTS": "app.example.com",
    "ALLOWED_STORAGE_ROOTS": "/Volumes/BigBang_Projects,/Volumes/BigBang_Backup",
    "ALLOW_PUBLIC_REGISTER": "0",
}


def _env(base: dict | None = None, **over):
    """Replace the whole environment (pytest's TASK_MANAGER_TEST_DATABASE must not leak in)."""
    values = dict(base or {})
    values.update({k: v for k, v in over.items() if v is not None})
    for k in [k for k, v in over.items() if v is None]:
        values.pop(k, None)
    return mock.patch.dict(os.environ, values, clear=True)


class ProductionConfigTests(unittest.TestCase):
    def test_valid_production_config_passes(self):
        import security_support as ss

        with _env(PROD):
            ss.enforce_production_config()
            self.assertEqual(ss.socketio_cors_origins(), ["https://app.example.com"])

    def test_each_missing_or_unsafe_production_setting_is_refused(self):
        import security_support as ss

        cases = {
            "wildcard cors": {"SOCKETIO_CORS_ORIGINS": "*"},
            "http cors": {"SOCKETIO_CORS_ORIGINS": "http://app.example.com"},
            "no cors": {"SOCKETIO_CORS_ORIGINS": None},
            "insecure cookie": {"SESSION_COOKIE_SECURE": "0"},
            "no hosts": {"ALLOWED_HOSTS": None},
            "wildcard hosts": {"ALLOWED_HOSTS": "*"},
            "no storage roots": {"ALLOWED_STORAGE_ROOTS": None},
            "debug": {"FLASK_DEBUG": "1"},
            "test database": {"TASK_MANAGER_TEST_DATABASE": "sqlite:///x.db"},
            "dev secret": {"SECRET_KEY": "dev-change-in-production"},
            "example secret": {"SECRET_KEY": "replace-with-a-long-random-string"},
            "short secret": {"SECRET_KEY": "short-but-random-xyz"},
            "no secret": {"SECRET_KEY": None},
            "weak sheets key": {"GOOGLE_SHEETS_TOKEN_KEY": "changeme"},
            "bad proxy count": {"TRUSTED_PROXY_COUNT": "lots"},
            "open signup unconfirmed": {"ALLOW_PUBLIC_REGISTER": "1"},
        }
        for label, over in cases.items():
            with self.subTest(label), _env(PROD, **over):
                with self.assertRaises(ss.InsecureConfigError):
                    ss.enforce_production_config()

    def test_public_register_requires_confirmation_in_production(self):
        import security_support as ss

        with _env(PROD, ALLOW_PUBLIC_REGISTER="1"):
            with self.assertRaises(RuntimeError):
                ss.resolve_allow_public_register()
        with _env(PROD, ALLOW_PUBLIC_REGISTER="1", ALLOW_PUBLIC_REGISTER_CONFIRMED="1"):
            self.assertTrue(ss.resolve_allow_public_register())


class SecretAndLocalConfigTests(unittest.TestCase):
    def test_placeholder_and_weak_secret_keys_are_rejected_outside_tests(self):
        import security_support as ss

        for value in ("dev-change-in-production", "replace-with-a-long-random-string", "changeme", "",
                      "a" * 64, "short"):
            with self.subTest(value=value), _env({"SECRET_KEY": value} if value else {}):
                with self.assertRaises(ss.InsecureConfigError):
                    ss.resolve_secret_key()
        with _env({"SECRET_KEY": STRONG}):
            self.assertEqual(ss.resolve_secret_key(), STRONG)

    def test_tests_get_a_random_key_never_a_constant(self):
        import security_support as ss

        with _env({}):
            a, b = ss.resolve_secret_key(testing=True), ss.resolve_secret_key(testing=True)
        self.assertNotEqual(a, b)
        self.assertFalse(ss.secret_problem(a))
        self.assertNotEqual(a, "dev-change-in-production")

    def test_loopback_development_defaults(self):
        import security_support as ss

        with _env({"SECRET_KEY": STRONG}):
            self.assertEqual(ss.resolve_bind_host(), "127.0.0.1")
            self.assertFalse(ss.resolve_debug("127.0.0.1"), "debug is opt-in")
            self.assertFalse(ss.resolve_allow_public_register(), "signup is opt-in")
            self.assertEqual(ss.socketio_cors_origins(),
                             ["http://127.0.0.1:5001", "http://localhost:5001", "http://[::1]:5001"])
            self.assertEqual(ss.trusted_proxy_count(), 0)
        with _env({"SECRET_KEY": STRONG, "FLASK_DEBUG": "1"}):
            self.assertTrue(ss.resolve_debug("127.0.0.1"))
            with self.assertRaises(ss.InsecureConfigError):
                ss.resolve_debug("0.0.0.0")
        with _env({"SECRET_KEY": STRONG, "HOST": "0.0.0.0"}):
            with self.assertRaises(ss.InsecureConfigError):
                ss.resolve_bind_host()
        with _env({"SECRET_KEY": STRONG, "HOST": "0.0.0.0", "ALLOW_NON_LOOPBACK_DEV": "1"}):
            self.assertEqual(ss.resolve_bind_host(), "0.0.0.0")
        with _env({"SECRET_KEY": STRONG, "SOCKETIO_CORS_ORIGINS": "*"}):
            with self.assertRaises(ss.InsecureConfigError):
                ss.socketio_cors_origins()

    def test_local_http_keeps_non_secure_but_httponly_lax_cookies(self):
        from flask import Flask

        import security_support as ss

        with _env({"SECRET_KEY": STRONG}):
            local = Flask("local")
            ss.configure_secure_session(local)
        self.assertFalse(local.config["SESSION_COOKIE_SECURE"])
        self.assertTrue(local.config["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual(local.config["SESSION_COOKIE_SAMESITE"], "Lax")
        with _env(PROD):
            prod = Flask("prod")
            ss.configure_secure_session(prod)
        self.assertTrue(prod.config["SESSION_COOKIE_SECURE"])
        self.assertEqual(prod.config["PREFERRED_URL_SCHEME"], "https")

    def test_host_allowlist_matching(self):
        import security_support as ss

        hosts = ["127.0.0.1", "localhost", "::1", ".studio.example"]
        for ok in ("127.0.0.1:5001", "localhost", "[::1]:5001", "app.studio.example", "studio.example"):
            self.assertTrue(ss.host_allowed(ok, hosts), ok)
        for bad in ("evil.example", "127.0.0.1.evil.example", "", "studio.example.evil.com"):
            self.assertFalse(ss.host_allowed(bad, hosts), bad)


class RequestHardeningTests(unittest.TestCase):
    """Real HTTP requests through the app (TESTING app, CSRF off unless a test enables it)."""

    @classmethod
    def setUpClass(cls):
        from app import app, db

        cls.app, cls.db = app, db
        with app.app_context():
            db.create_all()

    def test_unknown_host_header_is_rejected(self):
        client = self.app.test_client()
        self.assertEqual(client.get("/login", headers={"Host": "evil.example"}).status_code, 400)
        self.assertEqual(client.get("/login", headers={"Host": "127.0.0.1:5001"}).status_code, 200)

    def test_session_cookie_header_flags_on_local_http(self):
        client = self.app.test_client()
        res = client.post("/login", data={"login": "nobody@example.invalid", "password": "x"})
        header = next(h for h in res.headers.getlist("Set-Cookie") if h.startswith("session="))
        flags = {p.strip().split("=")[0].lower(): p.strip() for p in header.split(";")[1:]}
        self.assertIn("httponly", flags)
        self.assertEqual(flags.get("samesite"), "SameSite=Lax")
        self.assertNotIn("secure", flags, "plain-HTTP loopback must keep a non-Secure cookie")

    def test_forwarded_for_is_ignored_without_trusted_proxy(self):
        import security_support as ss

        with self.app.test_request_context("/", headers={"X-Forwarded-For": "203.0.113.9"},
                                           environ_base={"REMOTE_ADDR": "10.1.2.3"}):
            from flask import request

            self.assertEqual(ss.client_ip(request), "10.1.2.3")

    def test_session_signed_with_old_key_is_not_accepted(self):
        from flask.sessions import SecureCookieSessionInterface

        old = self.app.config["SECRET_KEY"]
        client = self.app.test_client()
        with client.session_transaction() as s:
            s["account_id"] = 999
        cookie = client.get_cookie(self.app.config.get("SESSION_COOKIE_NAME", "session"))
        self.assertIsNotNone(cookie)
        try:
            self.app.config["SECRET_KEY"] = STRONG
            serializer = SecureCookieSessionInterface().get_signing_serializer(self.app)
            self.assertIsNone(_loads_or_none(serializer, cookie.value), "old-key cookie must not verify")
            with client.session_transaction() as s:
                self.assertNotIn("account_id", s)
            self.assertNotIn("SECRET_KEY_FALLBACKS", self.app.config)
        finally:
            self.app.config["SECRET_KEY"] = old


def _loads_or_none(serializer, value):
    from itsdangerous import BadSignature

    try:
        return serializer.loads(value)
    except BadSignature:
        return None


class PathSecurityPass2Tests(unittest.TestCase):
    def test_unsafe_and_traversal_rejected(self):
        from path_security import reject_unsafe_system_path, validate_storage_root

        ok, _ = reject_unsafe_system_path("/etc/passwd")
        self.assertFalse(ok)
        ok, _ = reject_unsafe_system_path("/Volumes/Proj/../etc/passwd")
        self.assertFalse(ok)
        ok, _ = validate_storage_root("/Users/shared/media")
        self.assertFalse(ok)

    def test_configured_roots_preferred(self):
        from path_security import validate_storage_root

        with mock.patch.dict(
            os.environ,
            {"ALLOWED_STORAGE_ROOTS": "/Volumes/BigBang_Projects,/Volumes/BigBang_Backup"},
            clear=False,
        ):
            ok, err = validate_storage_root("/Volumes/BigBang_Projects/ShowA")
            self.assertTrue(ok, err)
            ok, _ = validate_storage_root("/Volumes/OtherDrive/ShowA")
            self.assertFalse(ok)

    def test_safe_join_cannot_escape(self):
        from path_security import safe_join

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                safe_join(tmp, "..", "etc", "passwd")
            out = safe_join(tmp, "a", "b.txt")
            self.assertTrue(out.startswith(os.path.normpath(tmp)))


class UploadSecurityTests(unittest.TestCase):
    def test_extension_rejected(self):
        from upload_security import IMAGE_EXTENSIONS, UploadRejected, assert_allowed_extension

        with self.assertRaises(UploadRejected):
            assert_allowed_extension("evil.svg", IMAGE_EXTENSIONS)
        with self.assertRaises(UploadRejected):
            assert_allowed_extension("page.html", IMAGE_EXTENSIONS)

    def test_large_upload_rejected(self):
        from werkzeug.datastructures import FileStorage

        from upload_security import UploadRejected, sniff_size

        data = io.BytesIO(b"x" * 100)
        fs = FileStorage(stream=data, filename="tiny.png")
        with self.assertRaises(UploadRejected):
            sniff_size(fs, max_bytes=50)

    def test_signature_mismatch_rejected(self):
        from werkzeug.datastructures import FileStorage

        from upload_security import IMAGE_EXTENSIONS, UploadRejected, validate_upload

        # HTML pretending to be PNG
        data = io.BytesIO(b"<!DOCTYPE html><html></html>")
        fs = FileStorage(stream=data, filename="fake.png", content_type="image/png")
        with self.assertRaises(UploadRejected):
            validate_upload(fs, allowed_extensions=IMAGE_EXTENSIONS, max_bytes=1024)


class CsrfAndStoragePermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import app, db

        cls.app = app
        cls.db = db
        with app.app_context():
            db.create_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        self.M = self.app.extensions.get("tm_test_models") or {}

    def tearDown(self):
        self.ctx.pop()

    def test_csrf_required_for_post_when_enabled(self):
        # TESTING disables CSRF by default; this test turns the real enforcement back on.
        self.app.config["WTF_CSRF_ENABLED"] = True
        try:
            r = self.client.post("/login", data={"login": "nobody", "password": "x"})
            self.assertIn(r.status_code, (400, 403))
            page = self.client.get("/login").get_data(as_text=True)
            import re

            token = re.search(r'name="csrf_token" value="([^"]+)"', page)
            self.assertIsNotNone(token, "login form renders a CSRF token")
            ok = self.client.post("/login", data={"login": "nobody", "password": "x", "csrf_token": token.group(1)})
            self.assertEqual(ok.status_code, 200, "a valid token is accepted (generic failure page)")
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = False

    def test_storage_folder_creation_requires_permission(self):
        # Unauthenticated create-folders must not succeed.
        r = self.client.post(
            "/projects/1/settings/storage/create-folders",
            json={"project_root_path": "/Volumes/BigBang_Projects/Show"},
            headers={"Accept": "application/json"},
        )
        self.assertIn(r.status_code, (302, 401, 403, 404))

        from app import db
        from werkzeug.security import generate_password_hash

        Account = self.M.get("Account")
        Project = self.M.get("Project")
        if Account is None or Project is None:
            self.skipTest("tm_test_models not registered")
        db.session.query(Project).delete()
        db.session.query(Account).delete()
        db.session.commit()
        user = Account(
            email="storage-user@test.local",
            password_hash=generate_password_hash("password", method="pbkdf2:sha256"),
            role="user",
        )
        db.session.add(user)
        proj = Project(
            name="Sec Storage Proj",
            project_type="Feature film",
            production_house="Test House",
            director="Test",
            sort_order=1,
        )
        db.session.add(proj)
        db.session.commit()
        with self.client.session_transaction() as sess:
            sess["account_id"] = user.id
        r2 = self.client.post(
            f"/projects/{proj.id}/settings/storage/create-folders",
            json={"project_root_path": "/Volumes/BigBang_Projects/Show"},
            headers={"Accept": "application/json"},
        )
        # User is not on the project / cannot manage storage.
        self.assertIn(r2.status_code, (401, 403, 404))


class PermissionsPolicyTests(unittest.TestCase):
    def test_default_pages_deny_camera_mic(self):
        import security_support as ss

        for endpoint in ("index", "profile", "projects_list"):
            policy = ss.permissions_policy_for_endpoint(endpoint)
            self.assertIn("camera=()", policy)
            self.assertIn("microphone=()", policy)
            self.assertIn("geolocation=()", policy)

    def test_chat_allows_microphone_only(self):
        import security_support as ss

        for endpoint in ("chat", "chat_threads", "project_chat_messages"):
            policy = ss.permissions_policy_for_endpoint(endpoint)
            self.assertIn("camera=()", policy)
            self.assertIn("microphone=(self)", policy)

    def test_conference_allows_camera_and_mic(self):
        import security_support as ss

        policy = ss.permissions_policy_for_endpoint("chat_conference_room")
        self.assertIn("camera=(self)", policy)
        self.assertIn("microphone=(self)", policy)

    def test_public_share_pages_deny_camera_mic(self):
        import security_support as ss

        for endpoint in ("client_review_home", "color_gallery_share"):
            policy = ss.permissions_policy_for_endpoint(endpoint)
            self.assertIn("camera=()", policy)
            self.assertIn("microphone=()", policy)

    def test_csp_omits_unsafe_eval(self):
        import security_support as ss

        csp = ss.build_content_security_policy()
        self.assertNotIn("unsafe-eval", csp)
        self.assertIn("unsafe-inline", csp)


if __name__ == "__main__":
    unittest.main()
