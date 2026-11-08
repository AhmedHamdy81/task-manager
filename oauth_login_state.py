"""Server-side, single-use OAuth sign-in attempts bound to the initiating browser.

`state` is random; the database keeps only its hash, the provider, the safe return
path and a hash of a per-browser binding value. The binding value, the nonce and the
PKCE verifier live in the initiating browser's session, so a callback opened in any
other browser fails before the authorization code is exchanged. Claiming an attempt
is an atomic UPDATE … WHERE used_at IS NULL, so a state works exactly once even with
several workers. Several tabs of the same browser may sign in in parallel.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Callable

from oauth_login_support import OAuthLoginError, new_pkce

TABLE = "oauth_login_attempts"
STATE_TTL = timedelta(minutes=10)
SESSION_BIND = "oauth_bind"
SESSION_PENDING = "oauth_pending"
MAX_PENDING = 5
# Apple answers with a cross-site form POST, which never carries the SameSite=Lax session
# cookie; its binding travels in this SameSite=None; Secure cookie instead.
APPLE_BIND_COOKIE = "bb_apple_bind"
APPLE_BIND_PATH = "/login/apple/callback"

MSG_OTHER_BROWSER = "This sign-in was started in another browser or has expired. Start again from this browser."
MSG_INVALID = "Sign-in could not be verified. Try again."
MSG_REPLAY = "This sign-in link was already used. Start again."
MSG_EXPIRED = "Sign-in took too long. Try again."

_models: dict[str, Any] = {}


def register_models(db, now_local) -> SimpleNamespace:
    if _models:
        return SimpleNamespace(**_models)

    class OAuthLoginAttempt(db.Model):
        __tablename__ = TABLE

        id = db.Column(db.Integer, primary_key=True)
        state_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
        provider = db.Column(db.String(16), nullable=False)
        binding_hash = db.Column(db.String(64), nullable=False)
        nonce_hash = db.Column(db.String(64), nullable=False, default="")
        next_url = db.Column(db.String(512), nullable=False, default="/")
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)
        expires_at = db.Column(db.DateTime, nullable=False, default=now_local)
        used_at = db.Column(db.DateTime, nullable=True)
        result = db.Column(db.String(32), nullable=False, default="")

    _models["Attempt"] = OAuthLoginAttempt
    return SimpleNamespace(**_models)


def ensure_tables(db, now_local) -> SimpleNamespace:
    m = register_models(db, now_local)
    m.Attempt.__table__.create(bind=db.engine, checkfirst=True)
    return m


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LoginStateStore:
    def __init__(self, db, *, now: Callable[[], datetime], session_getter: Callable[[], Any]):
        self.db = db
        self.now = now
        self._session = session_getter
        self.Attempt = register_models(db, now).Attempt

    def begin(self, provider: str, next_url: str) -> dict[str, str]:
        """Record a new attempt; returns state, nonce and PKCE values for the authorize URL."""
        sess = self._session()
        bind = sess.get(SESSION_BIND)
        if not isinstance(bind, str) or len(bind) < 32:
            bind = secrets.token_urlsafe(32)
            sess[SESSION_BIND] = bind
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(24)
        verifier, challenge = new_pkce()
        now_ts = time.time()
        pending = {
            k: v for k, v in (sess.get(SESSION_PENDING) or {}).items()
            if isinstance(v, dict) and now_ts - float(v.get("t") or 0) < STATE_TTL.total_seconds()
        }
        pending[_sha(state)] = {"p": provider, "n": nonce, "v": verifier, "t": now_ts}
        sess[SESSION_PENDING] = dict(sorted(pending.items(), key=lambda kv: kv[1]["t"])[-MAX_PENDING:])
        sess.modified = True
        now = self.now()
        self.Attempt.query.filter(self.Attempt.expires_at < now - timedelta(days=1)).delete(synchronize_session=False)
        self.db.session.add(self.Attempt(
            state_hash=_sha(state), provider=provider, binding_hash=_sha(bind), nonce_hash=_sha(nonce),
            next_url=(next_url or "/")[:512], created_at=now, expires_at=now + STATE_TTL,
        ))
        self.db.session.commit()
        return {"state": state, "nonce": nonce, "verifier": verifier, "challenge": challenge, "bind": bind}

    def claim(self, provider: str, state: str, *, cookie_bind: str | None = None) -> dict[str, str]:
        """Validate and consume an attempt before any code exchange. Raises OAuthLoginError.

        `cookie_bind` is only consulted for Apple's form-POST callback (see APPLE_BIND_COOKIE).
        """
        from sqlalchemy import update

        sess = self._session()
        h = _sha(state) if state else ""
        pending = dict(sess.get(SESSION_PENDING) or {})
        entry = pending.pop(h, None) if h else None
        sess[SESSION_PENDING] = pending
        sess.modified = True
        apple_cookie = provider == "apple" and isinstance(cookie_bind, str) and len(cookie_bind) >= 32
        if entry is None and not apple_cookie:
            if h:
                self._mark_unclaimed(h, "other_browser")
            raise OAuthLoginError(MSG_OTHER_BROWSER)
        if not h:
            raise OAuthLoginError(MSG_INVALID)
        row = self.Attempt.query.filter_by(state_hash=h).first()
        if row is None or row.provider != provider or (entry is not None and entry.get("p") != provider):
            raise OAuthLoginError(MSG_INVALID)
        now = self.now()
        res = self.db.session.execute(
            update(self.Attempt).where(self.Attempt.id == row.id, self.Attempt.used_at.is_(None)).values(used_at=now)
        )
        self.db.session.commit()
        if res.rowcount != 1:
            raise OAuthLoginError(MSG_REPLAY)
        self.db.session.refresh(row)
        if row.expires_at < now:
            self.finish(row.id, "expired")
            raise OAuthLoginError(MSG_EXPIRED)
        bind = sess.get(SESSION_BIND) if entry is not None else cookie_bind
        if not isinstance(bind, str) or not hmac.compare_digest(_sha(bind), row.binding_hash or ""):
            self.finish(row.id, "binding_mismatch")
            raise OAuthLoginError(MSG_OTHER_BROWSER)
        entry = entry or {}
        return {"id": str(row.id), "next": row.next_url or "/", "nonce": str(entry.get("n") or ""),
                "nonce_hash": row.nonce_hash or "", "verifier": str(entry.get("v") or "")}

    def _mark_unclaimed(self, state_hash: str, result: str) -> None:
        """A state presented by the wrong browser is burned so it can never be used later."""
        from sqlalchemy import update

        self.db.session.execute(
            update(self.Attempt).where(self.Attempt.state_hash == state_hash, self.Attempt.used_at.is_(None))
            .values(used_at=self.now(), result=result)
        )
        self.db.session.commit()

    def finish(self, attempt_id, result: str) -> None:
        row = self.db.session.get(self.Attempt, int(attempt_id))
        if row is not None:
            row.result = result[:32]
            self.db.session.commit()
