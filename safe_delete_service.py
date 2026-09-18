"""Safe Delete: reusable, secure confirmation for destructive delete actions.

A "Safe Delete" replaces a plain ``confirm()`` dialog. The user must type a
short numeric code that the server generated for *this* user and *this* exact
entity. The code is never stored in plain text, expires quickly, is single-use
and cannot be reused or replayed against a different entity or user.

This module is storage-agnostic: it receives the SQLAlchemy ``db`` handle and a
``SafeDeleteChallenge`` model (defined inside the Flask app factory) so the
model can live next to the other application models while the logic stays here,
independently testable.

Security model
--------------
* The 4-digit code is generated with :func:`secrets.randbelow` (never
  ``random`` / ``Math.random`` / timestamps).
* Only a salted SHA-256 hash of the code is stored (salted with the per-row
  token, so identical codes never share a hash).
* Client-side matching is UX only; :meth:`SafeDeleteService.verify` is the sole
  authority and always runs server-side.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

CODE_LENGTH = 4
CODE_MODULO = 10**CODE_LENGTH  # 10000 -> "0000".."9999", leading zeroes allowed
DEFAULT_TTL_SECONDS = 120
MAX_ATTEMPTS = 5

# Deliberately generic so an attacker cannot learn whether the code was partly
# correct, already used, or simply unknown.
GENERIC_ERROR = "The Safe Delete code is incorrect or expired."
EXPIRED_ERROR = "This Safe Delete code has expired."


def generate_code() -> str:
    """Return a cryptographically-random 4-digit code, e.g. ``"0047"``."""
    return f"{secrets.randbelow(CODE_MODULO):0{CODE_LENGTH}d}"


def generate_token() -> str:
    """Return an unguessable challenge token."""
    return secrets.token_urlsafe(24)


def normalize_code(raw: Any) -> str:
    """Trim spaces; keep only what the user typed (digits validated later)."""
    return ("" if raw is None else str(raw)).strip()


def is_well_formed_code(code: str) -> bool:
    return len(code) == CODE_LENGTH and code.isdigit()


def hash_code(token: str, code: str) -> str:
    """Salted hash of the code (salt = per-challenge token). Never reversible."""
    return hashlib.sha256(f"{token}:{code}".encode("utf-8")).hexdigest()


@dataclass
class SafeDeleteResult:
    """Outcome of a :meth:`SafeDeleteService.verify` call."""

    ok: bool
    challenge: Any | None = None
    error: str = ""
    # Machine-readable reason so the frontend can react (regenerate, close, ...).
    code: str = ""  # "invalid" | "expired" | "consumed" | "forbidden" | "gone"
    regenerate: bool = False
    http_status: int = 200


class SafeDeleteService:
    """Create / verify / consume one-time Safe Delete challenges."""

    def __init__(
        self,
        db: Any,
        model: Any,
        *,
        now_fn: Callable[[], datetime],
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.db = db
        self.model = model
        self.now_fn = now_fn
        self.ttl_seconds = int(ttl_seconds)
        self.max_attempts = int(max_attempts)

    # ------------------------------------------------------------------ create
    def invalidate_existing(
        self,
        *,
        account_id: int,
        entity_type: str,
        entity_id: int,
        project_id: int | None = None,
    ) -> int:
        """Consume any still-live challenge for the same user+entity.

        Generating a new code must invalidate the previous one. Returns the
        number of challenges invalidated. Does not commit (caller commits).
        """
        now = self.now_fn()
        q = self.model.query.filter(
            self.model.account_id == int(account_id),
            self.model.entity_type == str(entity_type),
            self.model.entity_id == int(entity_id),
            self.model.is_consumed.is_(False),
        )
        count = 0
        for row in q.all():
            row.is_consumed = True
            row.consumed_at = now
            count += 1
        return count

    def create_challenge(
        self,
        *,
        account_id: int,
        entity_type: str,
        entity_id: int,
        project_id: int | None = None,
    ) -> tuple[Any, str, int]:
        """Create a fresh challenge; return ``(challenge, display_code, ttl)``.

        The display code is returned exactly once (only here). Any previous
        live challenge for this user+entity is invalidated first.
        """
        self.invalidate_existing(
            account_id=account_id,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
        )
        code = generate_code()
        token = generate_token()
        now = self.now_fn()
        row = self.model(
            token=token,
            account_id=int(account_id),
            project_id=(int(project_id) if project_id is not None else None),
            entity_type=str(entity_type),
            entity_id=int(entity_id),
            code_hash=hash_code(token, code),
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
            attempt_count=0,
            is_consumed=False,
        )
        self.db.session.add(row)
        self.db.session.commit()
        return row, code, self.ttl_seconds

    # ------------------------------------------------------------------ verify
    def verify(
        self,
        *,
        token: str,
        entered_code: str,
        account_id: int,
        entity_type: str,
        entity_id: int,
        project_id: int | None = None,
    ) -> SafeDeleteResult:
        """Validate a challenge without deleting anything.

        On a wrong code the attempt counter is incremented and the challenge is
        invalidated after :attr:`max_attempts`. Attempt/​invalidations are
        committed here (they are independent of the caller's delete
        transaction). The caller performs the delete and then calls
        :meth:`consume` inside its own transaction so the two commit together.
        """
        code = normalize_code(entered_code)
        row = self.model.query.filter(self.model.token == (token or "")).first()

        # Unknown token / wrong owner / wrong entity all fail identically so the
        # response never leaks which check failed.
        if row is None:
            return SafeDeleteResult(
                ok=False, error=GENERIC_ERROR, code="invalid",
                regenerate=True, http_status=400,
            )
        if int(row.account_id) != int(account_id):
            return SafeDeleteResult(
                ok=False, error=GENERIC_ERROR, code="forbidden",
                regenerate=False, http_status=403,
            )
        if str(row.entity_type) != str(entity_type) or int(row.entity_id) != int(entity_id):
            return SafeDeleteResult(
                ok=False, error=GENERIC_ERROR, code="invalid",
                regenerate=True, http_status=400,
            )
        if project_id is not None and row.project_id is not None and int(row.project_id) != int(project_id):
            return SafeDeleteResult(
                ok=False, error=GENERIC_ERROR, code="invalid",
                regenerate=True, http_status=400,
            )
        if row.is_consumed:
            return SafeDeleteResult(
                ok=False, error=GENERIC_ERROR, code="consumed",
                regenerate=True, http_status=409,
            )
        if self.now_fn() > row.expires_at:
            return SafeDeleteResult(
                ok=False, error=EXPIRED_ERROR, code="expired",
                regenerate=True, http_status=410,
            )

        if not is_well_formed_code(code) or not hmac.compare_digest(
            row.code_hash, hash_code(row.token, code)
        ):
            row.attempt_count = int(row.attempt_count or 0) + 1
            regenerate = False
            if row.attempt_count >= self.max_attempts:
                # Too many wrong tries: burn the challenge, force a new code.
                row.is_consumed = True
                row.consumed_at = self.now_fn()
                regenerate = True
            self.db.session.commit()
            return SafeDeleteResult(
                ok=False, error=GENERIC_ERROR, code="invalid",
                regenerate=regenerate, http_status=400,
            )

        return SafeDeleteResult(ok=True, challenge=row, http_status=200)

    # ----------------------------------------------------------------- consume
    def consume(self, challenge: Any) -> None:
        """Mark the challenge used. Does NOT commit — caller commits atomically
        with the actual delete so a rollback also un-consumes the challenge."""
        challenge.is_consumed = True
        challenge.consumed_at = self.now_fn()

    def purge_expired(self, *, older_than_seconds: int = 3600) -> int:
        """Best-effort cleanup of stale rows. Returns rows deleted."""
        cutoff = self.now_fn() - timedelta(seconds=int(older_than_seconds))
        deleted = self.model.query.filter(self.model.expires_at < cutoff).delete(
            synchronize_session=False
        )
        self.db.session.commit()
        return int(deleted or 0)
