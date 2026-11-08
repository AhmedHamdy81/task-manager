"""Per-account Google Sheets connections (separate from BigBang sign-in).

Tokens are encrypted at rest in the database and never leave the server: they are
not put in URLs, templates, the Flask session cookie or logs. Each OAuth attempt is a
one-time, expiring server-side record bound to the initiating BigBang account, to a
random cookie in the browser that performs the consent, and to the import context.
Connecting never changes who is signed in to BigBang.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Callable

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import google_sheets_client as gsc

CONNECTION_TABLE = "google_sheets_connections"
STATE_TABLE = "google_sheets_oauth_states"
KEY_STATE_TABLE = "google_sheets_key_state"
TOKEN_KEY_ENV = "GOOGLE_SHEETS_TOKEN_KEY"
KEY_READY = "ready"
KEY_MIGRATING = "migrating"

STATE_TTL = timedelta(minutes=10)
HANDOFF_TTL = timedelta(minutes=5)
MODE_WEB = "web"
MODE_DESKTOP = "desktop"
BINDING_COOKIE = "bb_gsheets_bind"

_models: dict[str, Any] = {}


def register_models(db, now_local) -> SimpleNamespace:
    if _models:
        return SimpleNamespace(**_models)

    class GoogleSheetsConnection(db.Model):
        __tablename__ = CONNECTION_TABLE

        id = db.Column(db.Integer, primary_key=True)
        account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, unique=True, index=True)
        google_sub = db.Column(db.String(64), nullable=False, default="")
        google_email = db.Column(db.String(255), nullable=False, default="")
        scopes = db.Column(db.Text, nullable=False, default="")
        access_token_enc = db.Column(db.Text, nullable=False, default="")
        access_expires_at = db.Column(db.DateTime, nullable=True)
        refresh_token_enc = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)
        updated_at = db.Column(db.DateTime, nullable=False, default=now_local)
        last_used_at = db.Column(db.DateTime, nullable=True)

    class GoogleSheetsOAuthState(db.Model):
        __tablename__ = STATE_TABLE

        id = db.Column(db.Integer, primary_key=True)
        state_hash = db.Column(db.String(64), nullable=True, unique=True, index=True)
        handoff_hash = db.Column(db.String(64), nullable=True, unique=True, index=True)
        binding_hash = db.Column(db.String(64), nullable=False, default="")
        verifier_enc = db.Column(db.Text, nullable=False, default="")
        account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
        mode = db.Column(db.String(16), nullable=False, default=MODE_WEB)
        project_id = db.Column(db.Integer, nullable=True)
        day_id = db.Column(db.Integer, nullable=True)
        link = db.Column(db.String(2048), nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)
        expires_at = db.Column(db.DateTime, nullable=False, default=now_local)
        handoff_used_at = db.Column(db.DateTime, nullable=True)
        used_at = db.Column(db.DateTime, nullable=True)
        result = db.Column(db.String(32), nullable=False, default="")

    class GoogleSheetsKeyState(db.Model):
        """Single row: fingerprint of the token key in use, and a maintenance flag.

        Every process compares its key to `key_check` before touching tokens, so a wrong
        key or a running migration pauses Google Sheets instead of corrupting or dropping data.
        """

        __tablename__ = KEY_STATE_TABLE

        id = db.Column(db.Integer, primary_key=True)
        key_check = db.Column(db.String(64), nullable=False, default="")
        state = db.Column(db.String(16), nullable=False, default=KEY_READY)
        migration_id = db.Column(db.String(64), nullable=False, default="")
        updated_at = db.Column(db.DateTime, nullable=False, default=now_local)

    _models.update(Connection=GoogleSheetsConnection, OAuthState=GoogleSheetsOAuthState, KeyState=GoogleSheetsKeyState)
    return SimpleNamespace(**_models)


def ensure_tables(db, now_local) -> SimpleNamespace:
    m = register_models(db, now_local)
    m.Connection.__table__.create(bind=db.engine, checkfirst=True)
    m.OAuthState.__table__.create(bind=db.engine, checkfirst=True)
    m.KeyState.__table__.create(bind=db.engine, checkfirst=True)
    return m


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class TokenKeyError(Exception):
    """Stored ciphertext does not decrypt with the configured key. Never treated as "no token"."""


def derive_fernet_key(material: str) -> bytes:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"bigbang-google-sheets-tokens", info=b"v1").derive(
        material.encode("utf-8")
    )
    return base64.urlsafe_b64encode(key)


def key_fingerprint(material: str) -> str:
    """Non-reversible identifier of a key, safe to store and compare (not the key itself)."""
    return hmac.new(base64.urlsafe_b64decode(derive_fernet_key(material)), b"bigbang-gsheets-key-check-v1",
                    hashlib.sha256).hexdigest()[:32]


class TokenCipher:
    """Fernet encryption under one explicit key. No fallback key, no silent failures."""

    def __init__(self, material: str):
        material = (material or "").strip()
        if not material:
            raise TokenKeyError("No Google Sheets token key is configured.")
        self._f = Fernet(derive_fernet_key(material))
        self.fingerprint = key_fingerprint(material)

    def encrypt(self, value: str) -> str:
        return self._f.encrypt(value.encode("utf-8")).decode("ascii") if value else ""

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self._f.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise TokenKeyError("A stored Google token could not be decrypted with the configured key.") from exc


def token_key_problem(material: str | None) -> str:
    from security_support import secret_problem

    return secret_problem(material)


UNAVAILABLE_MESSAGES = {
    "key_missing": "Google Sheets is turned off on this server until an administrator sets GOOGLE_SHEETS_TOKEN_KEY.",
    "key_mismatch": "Google Sheets is paused: the stored connections use a different token key. An administrator must finish the key migration.",
    "legacy": "Google Sheets is paused: stored connections were encrypted with the old key. An administrator must run the key migration.",
    "maintenance": "Google Sheets is paused for maintenance. Try again in a few minutes.",
}


class ConnectError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ConnectionService:
    def __init__(self, *, db, now_local: Callable[[], datetime], token_key: str | None,
                 client_config: Callable[[], tuple[str, str]], http: gsc.Transport | None = None):
        self.db = db
        self.now = now_local
        self.cipher = TokenCipher(token_key) if not token_key_problem(token_key) else None
        self.client_config = client_config
        self.http = http or gsc.default_transport
        m = register_models(db, now_local)
        self.Connection = m.Connection
        self.OAuthState = m.OAuthState
        self.KeyState = m.KeyState

    # -- configuration --

    def configured(self) -> bool:
        cid, secret = self.client_config()
        return bool(cid and secret) and self.cipher is not None

    def availability(self) -> str:
        """"" when tokens may be used, else a code from UNAVAILABLE_MESSAGES."""
        if self.cipher is None:
            return "key_missing"
        state = self.db.session.get(self.KeyState, 1)
        if state is None:
            if self._has_encrypted_data():
                return "legacy"
            self.db.session.add(self.KeyState(id=1, key_check=self.cipher.fingerprint, state=KEY_READY,
                                              updated_at=self.now()))
            self.db.session.commit()
            return ""
        if state.state != KEY_READY:
            return "maintenance"
        if not hmac.compare_digest(state.key_check or "", self.cipher.fingerprint):
            return "key_mismatch"
        return ""

    def _has_encrypted_data(self) -> bool:
        C, S = self.Connection, self.OAuthState
        if C.query.filter((C.access_token_enc != "") | (C.refresh_token_enc != "")).first() is not None:
            return True
        return S.query.filter(S.verifier_enc != "").first() is not None

    def _ready(self) -> None:
        code = self.availability()
        if code:
            raise ConnectError(code, UNAVAILABLE_MESSAGES[code])

    def _ready_for_api(self) -> None:
        code = self.availability()
        if code:
            raise gsc.GoogleSheetsError("unavailable", UNAVAILABLE_MESSAGES[code])

    def _client(self) -> tuple[str, str]:
        cid, secret = self.client_config()
        if not (cid and secret):
            raise ConnectError("not_configured", "Google is not configured on this server. Ask an administrator to set up Google sign-in credentials.")
        self._ready()
        return cid, secret

    # -- status --

    def connection(self, account_id: int):
        return self.Connection.query.filter_by(account_id=int(account_id)).first()

    def status(self, account_id: int) -> dict:
        c = self.connection(account_id)
        if c is None:
            return {"connected": False, "email": "", "connected_at": None}
        return {"connected": True, "email": c.google_email, "connected_at": c.created_at}

    # -- authorization --

    def _purge_states(self) -> None:
        cutoff = self.now() - timedelta(days=1)
        self.OAuthState.query.filter(self.OAuthState.expires_at < cutoff).delete(synchronize_session=False)

    def create_handoff(self, *, account_id: int, project_id: int | None, day_id: int | None, link: str) -> str:
        """Desktop: a single-use token the external browser exchanges to start consent."""
        self._client()
        self._purge_states()
        token = secrets.token_urlsafe(32)
        self.db.session.add(self.OAuthState(
            handoff_hash=_sha(token), account_id=int(account_id), mode=MODE_DESKTOP,
            project_id=project_id, day_id=day_id, link=(link or "")[:2048],
            created_at=self.now(), expires_at=self.now() + HANDOFF_TTL,
        ))
        self.db.session.commit()
        return token

    def _start(self, row, redirect_uri: str, login_hint: str = "") -> tuple[str, str]:
        cid, _secret = self._client()
        state = secrets.token_urlsafe(32)
        binding = secrets.token_urlsafe(32)
        verifier, challenge = gsc.new_pkce()
        row.state_hash = _sha(state)
        row.binding_hash = _sha(binding)
        row.verifier_enc = self.cipher.encrypt(verifier)
        row.expires_at = self.now() + STATE_TTL
        self.db.session.commit()
        url = gsc.authorize_url(client_id=cid, redirect_uri=redirect_uri, state=state, code_challenge=challenge, login_hint=login_hint)
        return url, binding

    def begin_web(self, *, account_id: int, project_id: int | None, day_id: int | None, link: str,
                  redirect_uri: str) -> tuple[str, str]:
        """Returns (Google consent URL, binding cookie value)."""
        self._client()
        self._purge_states()
        row = self.OAuthState(account_id=int(account_id), mode=MODE_WEB, project_id=project_id, day_id=day_id,
                              link=(link or "")[:2048], created_at=self.now(), expires_at=self.now() + STATE_TTL)
        self.db.session.add(row)
        self.db.session.flush()
        existing = self.connection(account_id)
        return self._start(row, redirect_uri, existing.google_email if existing else "")

    def consume_handoff(self, token: str, *, redirect_uri: str) -> tuple[str, str]:
        row = self.OAuthState.query.filter_by(handoff_hash=_sha(token or "")).first() if token else None
        if row is None or row.mode != MODE_DESKTOP:
            raise ConnectError("invalid", "This connection link is not valid. Start again from BigBang Desktop.")
        if row.handoff_used_at is not None:
            raise ConnectError("replay", "This connection link was already used. Start again from BigBang Desktop.")
        if row.expires_at < self.now():
            raise ConnectError("expired", "This connection link expired. Start again from BigBang Desktop.")
        row.handoff_used_at = self.now()
        existing = self.connection(row.account_id)
        return self._start(row, redirect_uri, existing.google_email if existing else "")

    def complete(self, *, state: str, code: str, error: str, binding: str, session_account_id: int | None,
                 redirect_uri: str):
        """Validate the callback and store tokens. Returns the state row (for its return context)."""
        row = self.OAuthState.query.filter_by(state_hash=_sha(state)).first() if state else None
        if row is None:
            raise ConnectError("invalid", "The Google connection could not be verified. Start again.")
        if row.used_at is not None:
            raise ConnectError("replay", "This Google connection response was already used. Start again.")
        row.used_at = self.now()
        self.db.session.commit()
        if row.expires_at < self.now():
            self._finish(row, "expired")
            raise ConnectError("expired", "The Google connection took too long. Start again.")
        if not binding or not hmac.compare_digest(_sha(binding), row.binding_hash or ""):
            self._finish(row, "binding_mismatch")
            raise ConnectError("invalid", "The Google connection was finished in a different browser. Start again.")
        if row.mode == MODE_WEB and (session_account_id is None or int(session_account_id) != int(row.account_id)):
            self._finish(row, "account_mismatch")
            raise ConnectError("account", "You are signed in to BigBang as a different user than the one who started this connection.")
        if error:
            self._finish(row, "cancelled")
            raise ConnectError("cancelled" if error == "access_denied" else "denied",
                               "Google Sheets connection was cancelled." if error == "access_denied"
                               else "Google did not allow the connection.")
        cid, secret = self._client()
        try:
            verifier = self.cipher.decrypt(row.verifier_enc)
        except TokenKeyError as exc:
            self._finish(row, "key_mismatch")
            raise ConnectError("expired", "The Google connection has to be started again.") from exc
        if not verifier:
            self._finish(row, "invalid")
            raise ConnectError("expired", "The Google connection has to be started again.")
        try:
            token = gsc.exchange_code(self.http, client_id=cid, client_secret=secret, code=code,
                                      verifier=verifier, redirect_uri=redirect_uri)
            identity = gsc.fetch_identity(self.http, token["access_token"])
        except gsc.GoogleSheetsError as exc:
            self._finish(row, exc.code)
            raise ConnectError(exc.code, str(exc)) from exc
        self._store(row.account_id, token, identity)
        self._finish(row, "connected")
        return row

    def _finish(self, row, result: str) -> None:
        row.result = result[:32]
        row.verifier_enc = ""
        self.db.session.commit()

    def _store(self, account_id: int, token: dict, identity: dict) -> None:
        c = self.connection(account_id)
        if c is None:
            c = self.Connection(account_id=int(account_id), created_at=self.now())
            self.db.session.add(c)
        new_refresh = str(token.get("refresh_token") or "")
        if new_refresh or c.google_sub != identity["sub"]:
            c.refresh_token_enc = self.cipher.encrypt(new_refresh)
        if c.google_sub and c.google_sub != identity["sub"]:
            c.created_at = self.now()
        c.google_sub = identity["sub"]
        c.google_email = identity["email"]
        c.scopes = str(token.get("scope") or "")[:2000]
        c.access_token_enc = self.cipher.encrypt(str(token["access_token"]))
        c.access_expires_at = self.now() + timedelta(seconds=max(60, int(token.get("expires_in") or 3600)) - 60)
        c.updated_at = self.now()

    # -- use --

    def access_token(self, account_id: int, force_refresh: bool = False) -> str:
        self._ready_for_api()
        c = self.connection(account_id)
        if c is None:
            raise gsc.GoogleSheetsError("not_connected", "Connect Google Sheets first.")
        try:
            access = self.cipher.decrypt(c.access_token_enc)
            refresh = self.cipher.decrypt(c.refresh_token_enc)
        except TokenKeyError as exc:
            # Never drop a connection because of a key problem: the data is recoverable.
            raise gsc.GoogleSheetsError("unavailable", UNAVAILABLE_MESSAGES["key_mismatch"]) from exc
        if access and not force_refresh and c.access_expires_at and c.access_expires_at > self.now():
            c.last_used_at = self.now()
            return access
        if not refresh:
            self._drop(c)
            raise gsc.GoogleSheetsError("revoked", "Google access expired. Reconnect Google Sheets.")
        cid, secret = self.client_config()
        try:
            token = gsc.refresh_access_token(self.http, client_id=cid, client_secret=secret, refresh_token=refresh)
        except gsc.GoogleSheetsError as exc:
            if exc.code == "revoked":
                self._drop(c)
            raise
        if token.get("scope") and gsc.SHEETS_SCOPE not in str(token["scope"]).split():
            self._drop(c)
            raise gsc.GoogleSheetsError("insufficient_scope", "Google Sheets read access was removed. Reconnect Google Sheets.")
        c.access_token_enc = self.cipher.encrypt(str(token["access_token"]))
        c.access_expires_at = self.now() + timedelta(seconds=max(60, int(token.get("expires_in") or 3600)) - 60)
        if token.get("refresh_token"):
            c.refresh_token_enc = self.cipher.encrypt(str(token["refresh_token"]))
        c.updated_at = c.last_used_at = self.now()
        self.db.session.commit()
        return str(token["access_token"])

    def api(self, account_id: int) -> gsc.SheetsApi:
        return gsc.SheetsApi(lambda force: self.access_token(account_id, force), self.http)

    def _drop(self, c) -> None:
        self.db.session.delete(c)
        self.db.session.commit()

    def disconnect(self, account_id: int) -> bool:
        self._ready()
        c = self.connection(account_id)
        if c is None:
            return False
        token = self.cipher.decrypt(c.refresh_token_enc) or self.cipher.decrypt(c.access_token_enc)
        if token:
            gsc.revoke_token(self.http, token)
        self._drop(c)
        return True
