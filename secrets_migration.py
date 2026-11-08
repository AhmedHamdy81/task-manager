"""Secret setup and rotation for BigBang (session key + Google Sheets token key).

Secrets are read from and written to 0600 files only: never command-line arguments,
never printed, never logged. Output is limited to counts and key fingerprints.

Commands (run with the application stopped for anything that writes):

  init-env       Create a first-run .env with fresh random secrets (never overwrites).
  generate       Write fresh SECRET_KEY + GOOGLE_SHEETS_TOKEN_KEY to a new 0600 file.
  status         Show what the database holds and whether an env file's key matches it.
  migrate-sheets Re-encrypt stored Google Sheets tokens from the old key to the new
                 dedicated key, inside one transaction, after a protected backup.
  apply-env      Atomically write the new secrets into the live .env (backup kept).
  restore-backup Put a database backup made by migrate-sheets back in place.

See SECURITY.md → "Rotating SECRET_KEY and the Google Sheets token key".
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hmac
import os
import secrets
import shutil
import socket
import sqlite3
import stat
import sys
import tempfile
from dataclasses import dataclass, field

import google_sheets_service as gss
from security_support import secret_problem

CONN = gss.CONNECTION_TABLE
STATES = gss.STATE_TABLE
KEYSTATE = gss.KEY_STATE_TABLE
SECRET_NAMES = ("SECRET_KEY", gss.TOKEN_KEY_ENV)


class MigrationError(Exception):
    """Aborted safely; nothing was changed unless the message says otherwise."""


# --- files ---------------------------------------------------------------------------


def parse_env_file(path: str) -> dict[str, str]:
    """Same rules as security_support.load_dotenv, without touching os.environ."""
    out: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            out[key.strip()] = value
    return out


def _require_private(path: str) -> None:
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise MigrationError(f"{path} is readable by other users (mode {oct(mode)}). Run: chmod 600 {path}")


def _write_private(path: str, text: str) -> None:
    """Create a new file readable only by the owner. Fails if the file already exists."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


def _private_dir(path: str) -> str:
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def new_secret() -> str:
    return secrets.token_urlsafe(48)


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


# --- key material --------------------------------------------------------------------


def legacy_token_material(env: dict[str, str]) -> str:
    """The material the old code used: GOOGLE_SHEETS_TOKEN_KEY if set, else SECRET_KEY."""
    return (env.get(gss.TOKEN_KEY_ENV) or "").strip() or (env.get("SECRET_KEY") or "").strip()


def dedicated_token_material(env: dict[str, str]) -> str:
    return (env.get(gss.TOKEN_KEY_ENV) or "").strip()


def validate_new_secrets(new_env: dict[str, str], old_env: dict[str, str]) -> None:
    for name in SECRET_NAMES:
        problem = secret_problem(new_env.get(name))
        if problem:
            raise MigrationError(f"New {name} {problem}.")
    new_session, new_token = new_env["SECRET_KEY"].strip(), new_env[gss.TOKEN_KEY_ENV].strip()
    old_values = {v.strip() for v in (old_env.get("SECRET_KEY"), old_env.get(gss.TOKEN_KEY_ENV)) if v and v.strip()}
    if hmac.compare_digest(new_session.encode(), new_token.encode()):
        raise MigrationError("The new SECRET_KEY and GOOGLE_SHEETS_TOKEN_KEY must be different values.")
    if new_session in old_values or new_token in old_values:
        raise MigrationError("A new secret is identical to an old one. Generate fresh secrets.")


# --- database ------------------------------------------------------------------------


LOCK_TIMEOUT_SEC = 30


def _connect(db_path: str) -> sqlite3.Connection:
    if not os.path.isfile(db_path):
        raise MigrationError(f"Database not found: {db_path}")
    con = sqlite3.connect(db_path, timeout=LOCK_TIMEOUT_SEC, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _ensure_keystate_table(con) -> None:
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {KEYSTATE} (id INTEGER PRIMARY KEY, key_check VARCHAR(64) NOT NULL DEFAULT '', "
        "state VARCHAR(16) NOT NULL DEFAULT 'ready', migration_id VARCHAR(64) NOT NULL DEFAULT '', "
        "updated_at DATETIME NOT NULL)"
    )


def _keystate(con):
    if KEYSTATE not in _tables(con):
        return None
    return con.execute(f"SELECT key_check, state, migration_id FROM {KEYSTATE} WHERE id=1").fetchone()


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


@dataclass
class Report:
    connections: int = 0
    tokens: int = 0
    pending_states: int = 0
    unused_handoffs: int = 0
    failures: list[str] = field(default_factory=list)
    already_migrated: bool = False
    backup: str = ""

    def lines(self) -> list[str]:
        out = [
            f"connections: {self.connections}",
            f"encrypted token fields: {self.tokens}",
            f"pending OAuth attempts (to invalidate): {self.pending_states}",
            f"unused Desktop handoff links (to invalidate): {self.unused_handoffs}",
        ]
        if self.backup:
            out.append(f"backup: {self.backup}")
        if self.already_migrated:
            out.append("already migrated to this key; verified, nothing changed")
        return out


def _decrypt_all(con, cipher: gss.TokenCipher) -> tuple[dict[int, dict[str, str]], list[str]]:
    plain: dict[int, dict[str, str]] = {}
    failures: list[str] = []
    if CONN not in _tables(con):
        return plain, failures
    for row in con.execute(f"SELECT id, access_token_enc, refresh_token_enc FROM {CONN} ORDER BY id"):
        values = {}
        for col in ("access_token_enc", "refresh_token_enc"):
            try:
                values[col] = cipher.decrypt(row[col] or "")
            except gss.TokenKeyError:
                failures.append(f"connection {row['id']} {col}")
        plain[int(row["id"])] = values
    return plain, failures


def _pending(con) -> tuple[list[int], list[int]]:
    if STATES not in _tables(con):
        return [], []
    pending = [r[0] for r in con.execute(f"SELECT id FROM {STATES} WHERE used_at IS NULL AND (verifier_enc != '' OR state_hash IS NOT NULL)")]
    handoffs = [r[0] for r in con.execute(f"SELECT id FROM {STATES} WHERE handoff_hash IS NOT NULL AND handoff_used_at IS NULL")]
    return pending, handoffs


def _identity_snapshot(con) -> list[tuple]:
    if CONN not in _tables(con):
        return []
    return [tuple(r) for r in con.execute(
        f"SELECT id, account_id, google_sub, google_email, scopes, access_expires_at, created_at FROM {CONN} ORDER BY id")]


def backup_database(db_path: str, backup_dir: str) -> str:
    """Consistent online copy (sqlite backup API), owner-only permissions, integrity-checked."""
    _private_dir(backup_dir)
    dest = os.path.join(backup_dir, f"app-{_stamp()}-{secrets.token_hex(3)}.db")
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    src = sqlite3.connect(db_path, timeout=30)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(dest, 0o600)
    check = sqlite3.connect(dest)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("The backup failed its integrity check; nothing was changed.")
    finally:
        check.close()
    return dest


def app_is_listening(env: dict[str, str]) -> bool:
    host = (env.get("HOST") or "127.0.0.1").strip()
    host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    try:
        port = int((env.get("PORT") or "5001").strip())
    except ValueError:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def migrate_sheets(db_path: str, old_env: dict[str, str], new_env: dict[str, str], *, backup_dir: str,
                   dry_run: bool = False) -> Report:
    validate_new_secrets(new_env, old_env)
    old_material = legacy_token_material(old_env)
    if not old_material:
        raise MigrationError("The old env file has neither GOOGLE_SHEETS_TOKEN_KEY nor SECRET_KEY.")
    new_material = dedicated_token_material(new_env)
    old_cipher, new_cipher = gss.TokenCipher(old_material), gss.TokenCipher(new_material)
    con = _connect(db_path)
    report = Report()
    try:
        ks = _keystate(con)
        if ks is not None and ks["key_check"] and ks["state"] == gss.KEY_READY:
            if hmac.compare_digest(ks["key_check"], new_cipher.fingerprint):
                plain, failures = _decrypt_all(con, new_cipher)
                if failures:
                    raise MigrationError("Key state says migrated, but these fields do not decrypt with the new key: "
                                         + ", ".join(failures) + ". Nothing was changed.")
                report.connections = len(plain)
                report.tokens = sum(1 for v in plain.values() for t in v.values() if t)
                report.already_migrated = True
                return report
            if not hmac.compare_digest(ks["key_check"], old_cipher.fingerprint):
                raise MigrationError("The database is marked as using a key that is neither the old nor the new one. "
                                     "Check that the right env files were given. Nothing was changed.")
        plain, failures = _decrypt_all(con, old_cipher)
        report.connections = len(plain)
        report.tokens = sum(1 for v in plain.values() for t in v.values() if t)
        pending, handoffs = _pending(con)
        report.pending_states, report.unused_handoffs = len(pending), len(handoffs)
        if failures:
            report.failures = failures
            raise MigrationError("These fields do not decrypt with the old key: " + ", ".join(failures)
                                 + ". Nothing was changed; no connection was deleted.")
        if dry_run:
            return report

        report.backup = backup_database(db_path, backup_dir)
        identities_before = _identity_snapshot(con)
        migration_id = secrets.token_hex(8)
        previous = (ks["key_check"], ks["state"]) if ks is not None else None

        # 1) Maintenance flag, committed on its own so every running instance pauses Sheets.
        con.execute("BEGIN IMMEDIATE")
        _ensure_keystate_table(con)
        con.execute(
            f"INSERT INTO {KEYSTATE} (id, key_check, state, migration_id, updated_at) VALUES (1, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state=excluded.state, migration_id=excluded.migration_id, updated_at=excluded.updated_at",
            (old_cipher.fingerprint, gss.KEY_MIGRATING, migration_id, _now()),
        )
        con.execute("COMMIT")
        try:
            # 2) One write transaction: no other writer can change tokens until it ends.
            con.execute("BEGIN IMMEDIATE")
            plain, failures = _decrypt_all(con, old_cipher)
            if failures:
                raise MigrationError("Tokens changed while starting the migration: " + ", ".join(failures))
            for cid, values in plain.items():
                enc = {col: new_cipher.encrypt(val) for col, val in values.items()}
                for col, val in values.items():
                    if new_cipher.decrypt(enc[col]) != val:
                        raise MigrationError(f"Verification failed for connection {cid} {col}.")
                con.execute(f"UPDATE {CONN} SET access_token_enc=?, refresh_token_enc=? WHERE id=?",
                            (enc["access_token_enc"], enc["refresh_token_enc"], cid))
            now = _now()
            if STATES in _tables(con):
                con.execute(
                    f"UPDATE {STATES} SET verifier_enc='', used_at=COALESCE(used_at, ?), "
                    "handoff_used_at=CASE WHEN handoff_hash IS NOT NULL THEN COALESCE(handoff_used_at, ?) ELSE handoff_used_at END, "
                    "result=CASE WHEN result='' THEN 'key_rotated' ELSE result END "
                    "WHERE used_at IS NULL OR verifier_enc != '' OR (handoff_hash IS NOT NULL AND handoff_used_at IS NULL)",
                    (now, now),
                )
            after, failures = _decrypt_all(con, new_cipher)
            if failures or after != plain:
                raise MigrationError("Post-migration verification failed; rolled back.")
            if _identity_snapshot(con) != identities_before:
                raise MigrationError("Account association changed during migration; rolled back.")
            con.execute(f"UPDATE {KEYSTATE} SET key_check=?, state=?, updated_at=? WHERE id=1 AND migration_id=?",
                        (new_cipher.fingerprint, gss.KEY_READY, now, migration_id))
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            con.execute("BEGIN IMMEDIATE")
            if previous is None:
                con.execute(f"DELETE FROM {KEYSTATE} WHERE id=1 AND migration_id=?", (migration_id,))
            else:
                con.execute(f"UPDATE {KEYSTATE} SET key_check=?, state=?, updated_at=? WHERE id=1 AND migration_id=?",
                            (previous[0], previous[1], _now(), migration_id))
            con.execute("COMMIT")
            raise
        return report
    finally:
        con.close()


def status(db_path: str, env: dict[str, str] | None) -> list[str]:
    con = _connect(db_path)
    try:
        tables = _tables(con)
        n_conn = con.execute(f"SELECT COUNT(*) FROM {CONN}").fetchone()[0] if CONN in tables else 0
        pending, handoffs = _pending(con)
        ks = _keystate(con)
        lines = [
            f"connections: {n_conn}",
            f"pending OAuth attempts: {len(pending)}",
            f"unused Desktop handoff links: {len(handoffs)}",
            "key state: " + ("none (legacy: tokens use the key derived from the old SECRET_KEY)" if ks is None
                             else f"{ks['state']}, key fingerprint {ks['key_check'][:8]}…"),
        ]
        if env is not None:
            dedicated = dedicated_token_material(env)
            if not dedicated:
                lines.append("env file: no GOOGLE_SHEETS_TOKEN_KEY (Google Sheets will stay off with the new code)")
            else:
                fp = gss.key_fingerprint(dedicated)
                lines.append(f"env file GOOGLE_SHEETS_TOKEN_KEY fingerprint {fp[:8]}…: "
                             + ("matches the database" if ks is not None and hmac.compare_digest(ks["key_check"], fp)
                                else "does NOT match the database"))
            for name in SECRET_NAMES:
                problem = secret_problem(env.get(name))
                lines.append(f"env file {name}: " + ("ok" if not problem else problem))
        return lines
    finally:
        con.close()


def apply_env(env_path: str, new_env_path: str, *, backup_dir: str, extra: dict[str, str] | None = None) -> str:
    """Replace the secret lines of env_path atomically; returns the backup path."""
    new_env = parse_env_file(new_env_path)
    for name in SECRET_NAMES:
        problem = secret_problem(new_env.get(name))
        if problem:
            raise MigrationError(f"New {name} {problem}.")
    for key in extra or {}:
        if key in SECRET_NAMES:
            raise MigrationError(f"{key} can only come from the new secrets file.")
    updates = {name: new_env[name].strip() for name in SECRET_NAMES}
    updates.update(extra or {})
    with open(env_path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    _private_dir(backup_dir)
    backup = os.path.join(backup_dir, f"env-{_stamp()}-{secrets.token_hex(3)}.bak")
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as dst, open(env_path, "rb") as src:
        shutil.copyfileobj(src, dst)
    directory = os.path.dirname(os.path.abspath(env_path))
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, env_path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return backup


def restore_backup(db_path: str, backup_path: str, *, backup_dir: str) -> str:
    """Swap a verified backup in; the current database is kept as a safety copy first."""
    check = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("That backup failed its integrity check; nothing was changed.")
    finally:
        check.close()
    safety = backup_database(db_path, backup_dir)
    src = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    dst = sqlite3.connect(db_path, timeout=30)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return safety


def init_env(env_path: str, template_path: str | None) -> None:
    if os.path.exists(env_path):
        raise MigrationError(f"{env_path} already exists; it was not changed.")
    lines: list[str] = []
    if template_path and os.path.isfile(template_path):
        with open(template_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    values = {"SECRET_KEY": new_secret(), gss.TOKEN_KEY_ENV: new_secret(), "FLASK_DEBUG": "0",
              "ALLOW_PUBLIC_REGISTER": "0", "HOST": "127.0.0.1"}
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        elif key in ("SOCKETIO_CORS_ORIGINS",) and line.split("=", 1)[1].strip() == "*":
            out.append("# SOCKETIO_CORS_ORIGINS=   (unset = this server's loopback origins)")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in seen]
    _write_private(env_path, "\n".join(out) + "\n")


def generate(out_path: str) -> None:
    _write_private(out_path, "# New secrets for rotation. Delete this file after apply-env.\n"
                             f"SECRET_KEY={new_secret()}\n{gss.TOKEN_KEY_ENV}={new_secret()}\n")


# --- CLI -----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init-env")
    s.add_argument("--env", default=os.path.join(here, ".env"))
    s.add_argument("--template", default=os.path.join(here, ".env.example"))
    s = sub.add_parser("generate")
    s.add_argument("--out", required=True)
    s = sub.add_parser("status")
    s.add_argument("--db", required=True)
    s.add_argument("--env")
    s = sub.add_parser("migrate-sheets")
    s.add_argument("--db", required=True)
    s.add_argument("--old-env", required=True)
    s.add_argument("--new-env", required=True)
    s.add_argument("--backup-dir", required=True)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--confirm-app-stopped", action="store_true")
    s = sub.add_parser("apply-env")
    s.add_argument("--env", required=True)
    s.add_argument("--new-env", required=True)
    s.add_argument("--backup-dir", required=True)
    s.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="Also set a non-secret setting, e.g. --set FLASK_DEBUG=0")
    s.add_argument("--confirm-app-stopped", action="store_true")
    s = sub.add_parser("restore-backup")
    s.add_argument("--db", required=True)
    s.add_argument("--backup", required=True)
    s.add_argument("--backup-dir", required=True)
    s.add_argument("--confirm-app-stopped", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.cmd == "init-env":
            init_env(a.env, a.template)
            print(f"Created {a.env} (mode 600) with fresh random secrets.")
        elif a.cmd == "generate":
            generate(a.out)
            print(f"Wrote new secrets to {a.out} (mode 600). They are not shown here.")
        elif a.cmd == "status":
            env = None
            if a.env:
                _require_private(a.env)
                env = parse_env_file(a.env)
            print("\n".join(status(a.db, env)))
        elif a.cmd == "migrate-sheets":
            for path in (a.old_env, a.new_env):
                _require_private(path)
            old_env, new_env = parse_env_file(a.old_env), parse_env_file(a.new_env)
            if not a.dry_run:
                if not a.confirm_app_stopped:
                    raise MigrationError("Stop the application, then add --confirm-app-stopped.")
                if app_is_listening(old_env):
                    raise MigrationError("The application still answers on its port. Stop it first.")
            r = migrate_sheets(a.db, old_env, new_env, backup_dir=a.backup_dir, dry_run=a.dry_run)
            head = ("Dry run — nothing written." if a.dry_run else
                    "Nothing to do." if r.already_migrated else "Migration committed.")
            print(head + "\n" + "\n".join(r.lines()))
        elif a.cmd == "apply-env":
            _require_private(a.new_env)
            if not a.confirm_app_stopped:
                raise MigrationError("Stop the application, then add --confirm-app-stopped.")
            extra = {}
            for item in a.set:
                key, sep, value = item.partition("=")
                if not sep:
                    raise MigrationError(f"--set expects KEY=VALUE, got {item!r}")
                extra[key.strip()] = value.strip()
            backup = apply_env(a.env, a.new_env, backup_dir=a.backup_dir, extra=extra)
            print(f"Updated {a.env} (mode 600). Previous version saved to {backup}.")
        elif a.cmd == "restore-backup":
            if not a.confirm_app_stopped:
                raise MigrationError("Stop the application, then add --confirm-app-stopped.")
            safety = restore_backup(a.db, a.backup, backup_dir=a.backup_dir)
            print(f"Restored {a.backup} into {a.db}. The replaced database was saved to {safety}.")
    except MigrationError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ABORTED: {exc.filename} already exists; it was not changed.", file=sys.stderr)
        return 2
    except sqlite3.OperationalError as exc:
        print(f"ABORTED: database error ({exc}); the transaction was rolled back.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
