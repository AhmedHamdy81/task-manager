"""Sign-in / reset / OAuth-start throttling over real HTTP requests (isolated test database).

Throttling is off by default under TESTING; every test here turns it on explicitly.
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import threading
import unittest
from datetime import timedelta
from unittest import mock

from werkzeug.security import generate_password_hash

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_login_throttle.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from sqlalchemy import text  # noqa: E402

from app import app, db  # noqa: E402
import login_throttle as lt  # noqa: E402
import oauth_login_support as oauth  # noqa: E402
from time_utils import now_local  # noqa: E402


class LoginThrottleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()
            lt.ensure_table(db)

    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        app.config["AUTH_THROTTLE_ENABLED"] = True
        self.throttle = app.extensions["auth_throttle"]
        self.M = app.extensions["tm_test_models"]
        self._wipe()
        self.acc = self.M["Account"](email="editor@studio.example", username="editor",
                                     password_hash=generate_password_hash("right-password", method="pbkdf2:sha256"),
                                     role="user", status="active", is_active=True)
        db.session.add(self.acc)
        db.session.commit()
        self.clock = [now_local()]
        self.now_patch = mock.patch.object(self.throttle, "now", side_effect=lambda: self.clock[0])
        self.now_patch.start()

    def tearDown(self):
        self.now_patch.stop()
        app.config["AUTH_THROTTLE_ENABLED"] = False
        self._wipe()
        self.ctx.pop()

    def _wipe(self):
        db.session.execute(text(f"DELETE FROM {lt.TABLE}"))
        for model in ("User", "Account"):
            db.session.query(self.M[model]).delete()
        db.session.commit()

    def _login(self, login, password, ip="10.0.0.5", headers=None, client=None):
        return (client or app.test_client()).post(
            "/login", data={"login": login, "password": password},
            environ_base={"REMOTE_ADDR": ip}, headers=headers or {},
        )

    def test_account_limit_blocks_even_the_right_password_with_a_generic_answer(self):
        for _ in range(5):
            self.assertEqual(self._login("editor@studio.example", "wrong").status_code, 200)
        blocked = self._login("editor@studio.example", "right-password")
        self.assertEqual(blocked.status_code, 429)
        self.assertIn(lt.GENERIC_MESSAGE, blocked.get_data(as_text=True))
        for _ in range(5):
            self._login("nobody@studio.example", "wrong", ip="10.0.0.9")
        unknown = self._login("nobody@studio.example", "wrong", ip="10.0.0.9")
        self.assertEqual(unknown.status_code, 429, "unknown accounts are limited identically (no enumeration)")
        self.assertIn(lt.GENERIC_MESSAGE, unknown.get_data(as_text=True))

    def test_cooldown_expires_and_grows_without_permanent_lockout(self):
        for _ in range(6):
            self._login("editor", "wrong")
        self.clock[0] += timedelta(seconds=30)
        self.assertEqual(self._login("editor", "right-password").status_code, 429, "still cooling down")
        self.clock[0] += timedelta(minutes=20)
        ok = self._login("editor", "right-password")
        self.assertEqual(ok.status_code, 302, "cooldowns always end")

    def test_success_clears_the_account_bucket(self):
        for _ in range(4):
            self._login("editor", "wrong")
        self.assertEqual(self._login("EDITOR ", "right-password").status_code, 302, "identifier is normalized")
        for _ in range(5):
            self.assertEqual(self._login("editor", "wrong").status_code, 200)

    def test_client_limit_and_forwarded_for_spoofing(self):
        for i in range(20):
            self._login(f"user{i}@studio.example", "wrong", headers={"X-Forwarded-For": f"198.51.100.{i}"})
        r = self._login("fresh@studio.example", "wrong", headers={"X-Forwarded-For": "203.0.113.77"})
        self.assertEqual(r.status_code, 429, "X-Forwarded-For does not create a fresh client bucket")
        self.assertEqual(self._login("editor", "right-password", ip="10.0.0.6").status_code, 302,
                         "a different real client address is unaffected")

    def test_successful_sign_ins_do_not_fill_the_client_bucket(self):
        for _ in range(30):
            self.assertEqual(self._login("editor", "right-password").status_code, 302)

    def test_concurrent_attempts_cannot_exceed_the_limit(self):
        results: list[bool] = []
        lock = threading.Lock()

        def attempt():
            with app.app_context():
                d = self.throttle.reserve([("login_account", "race@studio.example")])
                with lock:
                    results.append(d.allowed)
                db.session.remove()

        threads = [threading.Thread(target=attempt) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 12)
        self.assertEqual(sum(results), lt.RULES["login_account"].limit)

    def test_nothing_identifying_is_stored(self):
        self._login("editor@studio.example", "wrong-secret-pw", ip="10.0.0.5")
        rows = db.session.execute(text(f"SELECT * FROM {lt.TABLE}")).fetchall()
        dump = repr(rows)
        for value in ("editor", "studio.example", "10.0.0.5", "wrong-secret-pw"):
            self.assertNotIn(value, dump)
        self.assertEqual(len(rows), 2)

    def test_password_reset_requests_are_limited_silently(self):
        client = app.test_client()
        with mock.patch("mail_service.send_email", return_value=True) as send:
            for _ in range(5):
                r = client.post("/forgot-password", data={"login": "editor@studio.example"},
                                environ_base={"REMOTE_ADDR": "10.0.0.7"})
                self.assertEqual(r.status_code, 302)
        self.assertEqual(send.call_count, lt.RULES["reset_account"].limit, "same answer, no more emails")

    def test_oauth_start_is_limited_per_client(self):
        with mock.patch.object(oauth, "google_configured", return_value=True), \
                mock.patch.object(oauth, "google_client_id", return_value="cid"):
            client = app.test_client()
            for _ in range(30):
                r = client.get("/login/google", environ_base={"REMOTE_ADDR": "10.0.0.8"})
                self.assertIn("accounts.google.com", r.headers["Location"])
            r = client.get("/login/google", environ_base={"REMOTE_ADDR": "10.0.0.8"})
            self.assertNotIn("accounts.google.com", r.headers["Location"])

    def test_admin_cli_clears_a_login(self):
        for _ in range(6):
            self._login("editor", "wrong")
        env = os.path.join(tempfile.mkdtemp(), "env")
        with open(env, "w") as fh:
            fh.write(f"SECRET_KEY={app.config['SECRET_KEY']}\n")
        db.session.commit()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(lt.main(["--db", _TEST_DB_PATH if os.path.exists(_TEST_DB_PATH) and
                                      app.config["SQLALCHEMY_DATABASE_URI"].endswith(_TEST_DB_PATH)
                                      else app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""),
                                      "--env", env, "--clear-login", "Editor"]), 0)
        self.assertNotIn(app.config["SECRET_KEY"], out.getvalue())
        db.session.expire_all()
        self.assertEqual(self._login("editor", "right-password").status_code, 302)


if __name__ == "__main__":
    unittest.main()
