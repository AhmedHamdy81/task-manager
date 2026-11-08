"""Database-backed throttling for sign-in, password reset, OAuth start and registration.

Limits are kept in the shared database, so they apply across worker processes and
survive restarts. Buckets are keyed by an HMAC of the normalized identifier or client
address: no login names, IP addresses, passwords or tokens are stored in clear.

Every attempt is *reserved* (counted) before the password is checked, so parallel
requests cannot slip extra guesses past the limit. Cooldowns grow with repeated
failures and always expire (no permanent lockout); a successful sign-in clears the
account bucket but not the client bucket.

Administrator recovery: `python login_throttle.py --db instance/app.db --env .env
--clear-login someone@example.com` (or --clear-ip, --purge). Rotating SECRET_KEY also
resets every bucket, because the HMAC key is derived from it.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

TABLE = "auth_throttle"


@dataclass(frozen=True)
class Rule:
    limit: int                 # attempts allowed inside the window before cooldowns start
    window: timedelta
    base_cooldown: timedelta   # first cooldown; doubles with each further attempt
    max_cooldown: timedelta


RULES: dict[str, Rule] = {
    "login_account": Rule(5, timedelta(minutes=15), timedelta(minutes=1), timedelta(minutes=15)),
    "login_ip": Rule(20, timedelta(minutes=15), timedelta(minutes=1), timedelta(minutes=15)),
    "reset_account": Rule(3, timedelta(minutes=30), timedelta(minutes=5), timedelta(minutes=30)),
    "reset_ip": Rule(10, timedelta(minutes=30), timedelta(minutes=5), timedelta(minutes=30)),
    "reset_submit_ip": Rule(10, timedelta(minutes=15), timedelta(minutes=1), timedelta(minutes=15)),
    "oauth_start_ip": Rule(30, timedelta(minutes=15), timedelta(minutes=1), timedelta(minutes=15)),
    "register_ip": Rule(5, timedelta(hours=1), timedelta(minutes=10), timedelta(hours=1)),
}

GENERIC_MESSAGE = "Too many attempts. Wait a few minutes and try again."


def normalize_identifier(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def bucket_key(secret: str, scope: str, value: str) -> str:
    material = hashlib.sha256(("bigbang-auth-throttle:" + secret).encode("utf-8")).digest()
    return hmac.new(material, f"{scope}\x00{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def ensure_table(db) -> None:
    from sqlalchemy import text

    db.session.execute(text(
        f"CREATE TABLE IF NOT EXISTS {TABLE} ("
        "bucket VARCHAR(64) PRIMARY KEY, scope VARCHAR(32) NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, "
        "window_start DATETIME NOT NULL, blocked_until DATETIME, updated_at DATETIME NOT NULL)"
    ))
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_updated ON {TABLE} (updated_at)"))
    db.session.commit()


def _cooldown(rule: Rule, attempts: int) -> timedelta:
    over = max(0, attempts - rule.limit)
    seconds = rule.base_cooldown.total_seconds() * (2 ** min(over, 16))
    return timedelta(seconds=min(seconds, rule.max_cooldown.total_seconds()))


@dataclass
class Decision:
    allowed: bool
    retry_after: int = 0


class Throttle:
    def __init__(self, db, *, secret: Callable[[], str], now: Callable[[], datetime]):
        self.db = db
        self._secret = secret
        self.now = now

    def _key(self, scope: str, value: str) -> str:
        return bucket_key(self._secret(), scope, value)

    def reserve(self, buckets: list[tuple[str, str]]) -> Decision:
        """Count one attempt against every (scope, value) bucket; refuse if any is cooling down.

        A refused attempt still counts, so hammering during a cooldown extends it.
        """
        from sqlalchemy import text

        now = self.now()
        retry = 0
        try:
            for scope, value in buckets:
                if not value:
                    continue
                rule = RULES[scope]
                key = self._key(scope, value)
                # One statement does the increment (or the window reset), so concurrent
                # requests cannot both see an empty bucket; it also takes the write lock,
                # making the read-back below consistent.
                stale = "(window_start < :cut AND (blocked_until IS NULL OR blocked_until <= :n))"
                self.db.session.execute(text(
                    f"INSERT INTO {TABLE} (bucket, scope, attempts, window_start, blocked_until, updated_at) "
                    "VALUES (:k, :s, 1, :n, NULL, :n) ON CONFLICT(bucket) DO UPDATE SET "
                    f"attempts = CASE WHEN {stale} THEN 1 ELSE attempts + 1 END, "
                    f"window_start = CASE WHEN {stale} THEN :n ELSE window_start END, "
                    f"blocked_until = CASE WHEN {stale} THEN NULL ELSE blocked_until END, "
                    "updated_at = :n"), {"k": key, "s": scope, "n": now, "cut": now - rule.window})
                row = self.db.session.execute(
                    text(f"SELECT attempts, blocked_until FROM {TABLE} WHERE bucket=:k"), {"k": key}).fetchone()
                attempts = int(row[0])
                blocked_until = _as_dt(row[1]) if row[1] else None
                if blocked_until is not None and blocked_until > now:
                    until = now + _cooldown(rule, attempts)
                    self.db.session.execute(text(f"UPDATE {TABLE} SET blocked_until=:u WHERE bucket=:k"),
                                            {"k": key, "u": max(until, blocked_until)})
                    retry = max(retry, int((max(until, blocked_until) - now).total_seconds()) + 1)
                elif attempts > rule.limit:
                    until = now + _cooldown(rule, attempts)
                    self.db.session.execute(text(f"UPDATE {TABLE} SET blocked_until=:u WHERE bucket=:k"),
                                            {"k": key, "u": until})
                    retry = max(retry, int((until - now).total_seconds()) + 1)
            self.db.session.commit()
        except Exception:
            self.db.session.rollback()
            raise
        return Decision(allowed=retry == 0, retry_after=retry)

    def release(self, buckets: list[tuple[str, str]]) -> None:
        """Give back one reserved attempt (used for client buckets after a successful sign-in)."""
        from sqlalchemy import text

        for scope, value in buckets:
            if value:
                self.db.session.execute(text(
                    f"UPDATE {TABLE} SET attempts=MAX(attempts-1, 0) WHERE bucket=:k AND blocked_until IS NULL"),
                    {"k": self._key(scope, value)})
        self.db.session.commit()

    def clear(self, buckets: list[tuple[str, str]]) -> None:
        from sqlalchemy import text

        for scope, value in buckets:
            if value:
                self.db.session.execute(text(f"DELETE FROM {TABLE} WHERE bucket=:k"), {"k": self._key(scope, value)})
        self.db.session.commit()

    def purge(self, older_than: timedelta = timedelta(days=1)) -> int:
        from sqlalchemy import text

        cutoff = self.now() - older_than
        res = self.db.session.execute(text(
            f"DELETE FROM {TABLE} WHERE updated_at < :c AND (blocked_until IS NULL OR blocked_until < :n)"),
            {"c": cutoff, "n": self.now()})
        self.db.session.commit()
        return int(res.rowcount or 0)


def _as_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


# --- administrator CLI (works on the SQLite file; never prints the secret) ----------


def main(argv: list[str] | None = None) -> int:
    from secrets_migration import parse_env_file

    p = argparse.ArgumentParser(description="Clear sign-in throttling for a login or client address.")
    p.add_argument("--db", required=True)
    p.add_argument("--env", required=True, help="env file holding the current SECRET_KEY")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--clear-login")
    g.add_argument("--clear-ip")
    g.add_argument("--purge", action="store_true", help="delete expired buckets")
    a = p.parse_args(argv)
    secret = (parse_env_file(a.env).get("SECRET_KEY") or "").strip()
    if not secret:
        print("The env file has no SECRET_KEY.", file=sys.stderr)
        return 2
    from time_utils import now_local

    con = sqlite3.connect(a.db, timeout=30)
    try:
        if a.purge:
            n = con.execute(f"DELETE FROM {TABLE} WHERE blocked_until IS NULL OR blocked_until < ?",
                            (str(now_local()),)).rowcount
        elif a.clear_login:
            v = normalize_identifier(a.clear_login)
            keys = [bucket_key(secret, s, v) for s in ("login_account", "reset_account")]
            n = con.execute(f"DELETE FROM {TABLE} WHERE bucket IN (?, ?)", keys).rowcount
        else:
            v = a.clear_ip.strip()
            keys = [bucket_key(secret, s, v) for s in RULES if s.endswith("_ip")]
            n = con.execute(f"DELETE FROM {TABLE} WHERE bucket IN ({','.join('?' * len(keys))})", keys).rowcount
        con.commit()
    finally:
        con.close()
    print(f"Removed {n} throttle bucket(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
