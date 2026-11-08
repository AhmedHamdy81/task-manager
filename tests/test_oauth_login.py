"""Google and Apple sign-in: browser-bound single-use state, PKCE, verified ID tokens, safe linking.

Google is mocked at the HTTP boundary (token endpoint) and the ID token is a real RS256
JWT signed by a test key, so the production verification code runs unchanged.
CSRF is disabled in TESTING; the callbacks are GET (Google) or provider-initiated POST
(Apple, CSRF-exempt by design), so CSRF does not affect what is tested here.
"""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import time
import unittest
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from werkzeug.security import generate_password_hash

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_oauth_login_unittest.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db  # noqa: E402
import oauth_login_state as ols  # noqa: E402
import oauth_login_support as oauth  # noqa: E402

CLIENT_ID = "test-google-client.apps.googleusercontent.com"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def id_token(nonce: str, *, sub="google-sub-1", email="colorist@gmail.com", key=_KEY, **over) -> str:
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "azp": CLIENT_ID, "sub": sub,
              "email": email, "email_verified": True, "name": "Colorist", "iat": now, "exp": now + 600,
              "nonce": nonce}
    claims.update(over)
    for k in [k for k, v in claims.items() if v is None]:
        claims.pop(k)
    return jwt.encode(claims, _pem(key), algorithm="RS256", headers={"kid": "test"})


class _Google:
    """Fake token endpoint: returns whatever ID token the test prepared, records calls."""

    def __init__(self):
        self.token = ""
        self.calls: list[dict] = []

    def post(self, url, data):
        self.calls.append(dict(data))
        return {"access_token": "at", "id_token": self.token, "token_type": "Bearer"}


class OAuthLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        M = app.extensions["tm_test_models"]
        self.Account, self.Identity, self.User = M["Account"], M["AccountOAuthIdentity"], M["User"]
        self.Attempt = ols.register_models(db, None).Attempt
        self._wipe()
        self.google = _Google()
        self.patches = [
            mock.patch.object(oauth, "google_configured", return_value=True),
            mock.patch.object(oauth, "google_client_id", return_value=CLIENT_ID),
            mock.patch.object(oauth, "google_client_secret", return_value="client-secret"),
            mock.patch.object(oauth, "_http_post_form", side_effect=self.google.post),
            mock.patch.object(oauth, "_google_signing_key", side_effect=lambda _t: _KEY.public_key()),
        ]
        for p in self.patches:
            p.start()
        self._old_register = app.config.get("ALLOW_PUBLIC_REGISTER")
        app.config["ALLOW_PUBLIC_REGISTER"] = False

    def tearDown(self):
        for p in self.patches:
            p.stop()
        app.config["ALLOW_PUBLIC_REGISTER"] = self._old_register
        self._wipe()
        self.ctx.pop()

    def _wipe(self):
        for model in (self.Attempt, self.Identity, self.User, self.Account):
            db.session.query(model).delete()
        db.session.commit()

    def _account(self, email="colorist@gmail.com", status="active", role="user"):
        acc = self.Account(email=email, password_hash=generate_password_hash("secret-pass", method="pbkdf2:sha256"),
                           role=role, status=status, is_active=status == "active")
        db.session.add(acc)
        db.session.commit()
        return acc

    def _start(self, client=None, next_url=None):
        url = "/login/google" + (f"?next={next_url}" if next_url else "")
        r = (client or self.client).get(url)
        self.assertIn(r.status_code, (302, 303))
        q = parse_qs(urlparse(r.headers["Location"]).query)
        return {k: v[0] for k, v in q.items()}

    def _callback(self, params, client=None, *, token=None, code="auth-code"):
        self.google.token = token if token is not None else id_token(params["nonce"])
        return (client or self.client).get(f"/login/google/callback?state={params['state']}&code={code}")

    def _signed_in(self, client=None):
        with (client or self.client).session_transaction() as s:
            return s.get("account_id")

    # -- start --

    def test_start_uses_random_state_nonce_and_pkce(self):
        p = self._start()
        self.assertTrue(p["state"] and p["nonce"])
        self.assertEqual(p["code_challenge_method"], "S256")
        self.assertNotIn("include_granted_scopes", p, "sign-in must not inherit Google Sheets grants")
        self.assertEqual(p["scope"], "openid email profile")
        row = self.Attempt.query.one()
        self.assertEqual(row.state_hash, hashlib.sha256(p["state"].encode()).hexdigest())
        self.assertNotEqual(self._start()["state"], p["state"])

    def test_start_without_config_returns_to_login(self):
        with mock.patch.object(oauth, "google_configured", return_value=False):
            r = self.client.get("/login/google")
        self.assertIn("/login", r.headers["Location"])
        self.assertNotIn("accounts.google.com", r.headers["Location"])

    def test_login_page_buttons_follow_configuration(self):
        with mock.patch.object(oauth, "google_configured", return_value=False), \
                mock.patch.object(oauth, "apple_configured", return_value=False):
            body = self.client.get("/login").get_data(as_text=True)
        self.assertNotIn("/login/google", body)
        with mock.patch.object(oauth, "apple_configured", return_value=True):
            body = self.client.get("/login").get_data(as_text=True)
        self.assertIn("Continue with Google", body)
        self.assertIn("Continue with Apple", body)

    # -- success and binding --

    def test_same_browser_signs_in_with_pkce_and_links_identity(self):
        acc = self._account()
        p = self._start(next_url="/projects")
        r = self._callback(p)
        self.assertEqual(r.headers["Location"].rstrip("/").rsplit("/", 1)[-1], "projects")
        self.assertEqual(self._signed_in(), acc.id)
        sent = self.google.calls[0]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, p["code_challenge"])
        self.assertEqual(self.Identity.query.filter_by(provider="google", subject="google-sub-1").one().account_id, acc.id)
        with self.client.session_transaction() as s:
            self.assertNotIn(ols.SESSION_PENDING, s, "login regenerates the session contents")

    def test_state_from_browser_a_cannot_authenticate_browser_b(self):
        """Regression: a valid state started in browser A, completed in browser B with a valid Google profile."""
        self._account()
        browser_a, browser_b = app.test_client(), app.test_client()
        p = self._start(browser_a)
        r = self._callback(p, browser_b)
        self.assertIn("/login", r.headers["Location"])
        self.assertIsNone(self._signed_in(browser_b))
        self.assertEqual(self.google.calls, [], "the code must not be exchanged for another browser")
        self.assertEqual(self.Identity.query.count(), 0)
        r = self._callback(p, browser_a)
        self.assertIsNone(self._signed_in(browser_a), "a state shown to another browser is burned")

    def test_replayed_state_is_rejected(self):
        acc = self._account()
        p = self._start()
        self._callback(p)
        self.assertEqual(self._signed_in(), acc.id)
        self.client.get("/logout")
        self._callback(p)
        self.assertIsNone(self._signed_in())
        self.assertEqual(len(self.google.calls), 1)

    def test_concurrent_claims_succeed_only_once(self):
        self._account()
        p = self._start()
        with self.client.session_transaction() as s:
            saved = dict(s)
        self._callback(p)
        twin = app.test_client()
        with twin.session_transaction() as s:
            s.update(saved)
        self._callback(p, twin)
        self.assertIsNone(self._signed_in(twin), "a copied session cannot reuse a claimed state")
        self.assertEqual(len(self.google.calls), 1)

    def test_expired_missing_and_unknown_state_are_rejected(self):
        self._account()
        p = self._start()
        row = self.Attempt.query.one()
        row.expires_at = row.created_at - timedelta(seconds=1)
        db.session.commit()
        self._callback(p)
        self.assertIsNone(self._signed_in())
        self.client.get("/login/google/callback?code=x")
        self.client.get("/login/google/callback?state=not-a-real-state&code=x")
        self.assertIsNone(self._signed_in())
        self.assertEqual(self.google.calls, [])

    def test_multiple_tabs_in_one_browser(self):
        acc = self._account()
        first, second = self._start(), self._start()
        self._callback(second)
        self.assertEqual(self._signed_in(), acc.id)
        r = self._callback(first)
        self.assertEqual(self._signed_in(), acc.id, "the other tab never swaps the signed-in account")
        self.assertNotIn("/login", r.headers["Location"])
        self.assertEqual(len(self.google.calls), 1)

    def test_callback_never_replaces_a_signed_in_account(self):
        self._account()
        other = self._account(email="producer@gmail.com")
        p = self._start()
        with self.client.session_transaction() as s:
            s["account_id"] = other.id
        self._callback(p, token=id_token(p["nonce"]))
        self.assertEqual(self._signed_in(), other.id)
        self.assertEqual(self.google.calls, [])

    def test_state_for_google_is_rejected_on_apple_callback(self):
        self._account()
        p = self._start()
        with mock.patch.object(oauth, "verify_apple_id_token") as verify:
            self.client.post("/login/apple/callback", data={"state": p["state"], "id_token": "x"})
        verify.assert_not_called()
        self.assertIsNone(self._signed_in())

    def test_unsafe_next_is_dropped(self):
        self._account()
        p = self._start(next_url="//evil.example/steal")
        r = self._callback(p)
        self.assertEqual(urlparse(r.headers["Location"]).netloc in ("", "localhost"), True)
        self.assertNotIn("evil.example", r.headers["Location"])

    # -- ID token validation (fail closed) --

    def test_invalid_id_tokens_are_rejected(self):
        self._account()
        cases = {
            "nonce": lambda n: id_token("someone-elses-nonce"),
            "audience": lambda n: id_token(n, aud="other-client"),
            "issuer": lambda n: id_token(n, iss="https://evil.example"),
            "expired": lambda n: id_token(n, exp=int(time.time()) - 3600, iat=int(time.time()) - 7200),
            "signature": lambda n: id_token(n, key=_OTHER_KEY),
            "unverified": lambda n: id_token(n, email_verified=False),
            "verified-missing": lambda n: id_token(n, email_verified=None),
            "no-email": lambda n: id_token(n, email=None),
            "no-sub": lambda n: id_token(n, sub=None),
            "azp": lambda n: id_token(n, azp="other-client"),
            "missing": lambda n: "",
        }
        for label, make in cases.items():
            with self.subTest(label):
                p = self._start()
                self._callback(p, token=make(p["nonce"]))
                self.assertIsNone(self._signed_in(), label)
        self.assertEqual(self.Identity.query.count(), 0)

    # -- identity linking --

    def test_email_link_requires_google_to_own_the_mailbox(self):
        acc = self._account(email="editor@studio.example")
        p = self._start()
        self._callback(p, token=id_token(p["nonce"], email="editor@studio.example"))
        self.assertIsNone(self._signed_in(), "a non-Google-hosted address is not linked automatically")
        self.assertEqual(self.Identity.query.count(), 0)
        p = self._start()
        self._callback(p, token=id_token(p["nonce"], email="editor@studio.example", hd="studio.example"))
        self.assertEqual(self._signed_in(), acc.id, "Workspace domain hosted by Google (hd claim)")

    def test_existing_link_wins_and_a_second_google_account_cannot_attach(self):
        acc = self._account()
        db.session.add(self.Identity(account_id=acc.id, provider="google", subject="original-sub", email=acc.email))
        db.session.commit()
        p = self._start()
        self._callback(p, token=id_token(p["nonce"], sub="different-sub"))
        self.assertIsNone(self._signed_in())
        p = self._start()
        self._callback(p, token=id_token(p["nonce"], sub="original-sub", email="renamed@gmail.com"))
        self.assertEqual(self._signed_in(), acc.id, "linked subject signs in even after an email change")

    def test_pending_and_suspended_accounts_stay_restricted(self):
        for status in ("pending_approval", "suspended"):
            with self.subTest(status):
                self._wipe()
                acc = self._account(status=status)
                client = app.test_client()
                p = self._start(client)
                r = self._callback(p, client)
                self.assertIn("/account/pending", r.headers["Location"])
                with client.session_transaction() as s:
                    self.assertEqual(s.get("account_id"), acc.id)
                self.assertEqual(client.get("/projects").status_code, 302)

    def test_unknown_email_without_public_register_is_refused(self):
        p = self._start()
        self._callback(p, token=id_token(p["nonce"], email="nobody@gmail.com"))
        self.assertIsNone(self._signed_in())
        self.assertEqual(self.Account.query.count(), 0)

    # -- Apple (not enabled; helpers must not regress) --

    def test_apple_state_and_nonce(self):
        acc = self._account(email="apple.user@icloud.com")
        with mock.patch.object(oauth, "apple_configured", return_value=True), \
                mock.patch.object(oauth, "apple_client_id", return_value="com.bigbang.signin"):
            r = self.client.get("/login/apple")
            q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["Location"]).query).items()}
            self.assertEqual(q["response_mode"], "form_post")
            profile = {"provider": "apple", "sub": "apple-sub-1", "email": acc.email, "name": "",
                       "email_authoritative": True}
            with mock.patch.object(oauth, "verify_apple_id_token", return_value=profile) as verify:
                other = app.test_client()
                other.post("/login/apple/callback", data={"state": q["state"], "id_token": "x"})
                verify.assert_not_called()
            r = self.client.get("/login/apple")
            q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["Location"]).query).items()}
            with mock.patch.object(oauth, "verify_apple_id_token", return_value=profile) as verify:
                self.client.post("/login/apple/callback", data={"state": q["state"], "id_token": "x"})
            self.assertEqual(verify.call_args.kwargs["nonce"], q["nonce"])
        self.assertEqual(self._signed_in(), acc.id)

    def test_apple_id_token_requires_matching_nonce(self):
        now = int(time.time())
        base = {"iss": oauth.APPLE_ISSUER, "aud": "com.bigbang.signin", "sub": "s", "email": "a@icloud.com",
                "email_verified": "true", "iat": now, "exp": now + 600}
        fake_client = mock.Mock()
        fake_client.return_value.get_signing_key_from_jwt.return_value = mock.Mock(key=_KEY.public_key())
        with mock.patch.object(oauth, "apple_configured", return_value=True), \
                mock.patch.object(oauth, "apple_client_id", return_value="com.bigbang.signin"), \
                mock.patch("jwt.PyJWKClient", fake_client):
            ok = jwt.encode({**base, "nonce": "n1"}, _pem(_KEY), algorithm="RS256")
            self.assertEqual(oauth.verify_apple_id_token(ok, nonce="n1")["sub"], "s")
            nonce_hash = hashlib.sha256(b"n1").hexdigest()
            self.assertEqual(oauth.verify_apple_id_token(ok, nonce_hash=nonce_hash)["sub"], "s")
            for token, kwargs in ((jwt.encode(base, _pem(_KEY), algorithm="RS256"), {"nonce": "n1"}),
                                  (ok, {"nonce": "other"}), (ok, {})):
                with self.assertRaises(oauth.OAuthLoginError):
                    oauth.verify_apple_id_token(token, **kwargs)


if __name__ == "__main__":
    unittest.main()
