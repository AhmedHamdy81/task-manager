"""Session-key / Google Sheets token-key separation and the rotation tool, on disposable data.

Every database here is a throwaway SQLite file in a temporary directory; fake tokens are
encrypted exactly the way the previous code did (key derived from SECRET_KEY).
"""

from __future__ import annotations

import contextlib
import io
import os
import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import google_sheets_service as gss
import secrets_migration as sm

OLD_SESSION = "dev-change-in-production"          # the known development key
NEW_SESSION = "N3w-session-key-0123456789-abcdefghijklmnopqrstuvwxyz"
NEW_TOKEN = "N3w-token-key-ZYXWVUTSRQPONMLKJIHGFEDCBA-9876543210_x"
TOKENS = {1: ("ya29.access-one", "1//refresh-one"), 2: ("ya29.access-two", "")}


def _schema(con):
    con.executescript(f"""
        CREATE TABLE {gss.CONNECTION_TABLE} (
            id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL UNIQUE, google_sub VARCHAR(64) NOT NULL DEFAULT '',
            google_email VARCHAR(255) NOT NULL DEFAULT '', scopes TEXT NOT NULL DEFAULT '',
            access_token_enc TEXT NOT NULL DEFAULT '', access_expires_at DATETIME, refresh_token_enc TEXT NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, last_used_at DATETIME);
        CREATE TABLE {gss.STATE_TABLE} (
            id INTEGER PRIMARY KEY, state_hash VARCHAR(64), handoff_hash VARCHAR(64), binding_hash VARCHAR(64) NOT NULL DEFAULT '',
            verifier_enc TEXT NOT NULL DEFAULT '', account_id INTEGER NOT NULL, mode VARCHAR(16) NOT NULL DEFAULT 'web',
            project_id INTEGER, day_id INTEGER, link VARCHAR(2048) NOT NULL DEFAULT '', created_at DATETIME NOT NULL,
            expires_at DATETIME NOT NULL, handoff_used_at DATETIME, used_at DATETIME, result VARCHAR(32) NOT NULL DEFAULT '');
    """)


def _legacy_db(path: str, material: str = OLD_SESSION) -> None:
    c = gss.TokenCipher(material)
    now = datetime(2026, 11, 8, 12, 0, 0)
    con = sqlite3.connect(path)
    _schema(con)
    for cid, (access, refresh) in TOKENS.items():
        con.execute(
            f"INSERT INTO {gss.CONNECTION_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (cid, 100 + cid, f"sub-{cid}", f"user{cid}@gmail.com", "openid email spreadsheets.readonly",
             c.encrypt(access), str(now + timedelta(hours=1)), c.encrypt(refresh), str(now), str(now)),
        )
    con.execute(f"INSERT INTO {gss.STATE_TABLE} (id, state_hash, binding_hash, verifier_enc, account_id, mode, created_at, expires_at) "
                "VALUES (1, 'sh', 'bh', ?, 101, 'web', ?, ?)", (c.encrypt("pkce-verifier"), str(now), str(now + timedelta(minutes=10))))
    con.execute(f"INSERT INTO {gss.STATE_TABLE} (id, handoff_hash, account_id, mode, created_at, expires_at) "
                "VALUES (2, 'hh', 102, 'desktop', ?, ?)", (str(now), str(now + timedelta(minutes=5))))
    con.commit()
    con.close()


def _rows(path: str) -> list[tuple]:
    con = sqlite3.connect(path)
    try:
        return con.execute(f"SELECT * FROM {gss.CONNECTION_TABLE} ORDER BY id").fetchall()
    finally:
        con.close()


def _keystate(path: str):
    con = sqlite3.connect(path)
    try:
        if gss.KEY_STATE_TABLE not in {r[0] for r in con.execute("SELECT name FROM sqlite_master")}:
            return None
        return con.execute(f"SELECT key_check, state FROM {gss.KEY_STATE_TABLE} WHERE id=1").fetchone()
    finally:
        con.close()


class MigrationToolTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="bb_rotation_")
        self.db = os.path.join(self.dir, "app.db")
        self.backups = os.path.join(self.dir, "backups")
        _legacy_db(self.db)
        self.old = {"SECRET_KEY": OLD_SESSION}
        self.new = {"SECRET_KEY": NEW_SESSION, gss.TOKEN_KEY_ENV: NEW_TOKEN}

    def _decrypted(self, material: str) -> dict[int, tuple[str, str]]:
        c = gss.TokenCipher(material)
        return {r[0]: (c.decrypt(r[5]), c.decrypt(r[7])) for r in _rows(self.db)}

    def test_tokens_survive_migration_and_pending_oauth_is_invalidated(self):
        before = _rows(self.db)
        report = sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups)
        self.assertEqual((report.connections, report.tokens, report.pending_states, report.unused_handoffs), (2, 3, 1, 1))
        self.assertEqual(self._decrypted(NEW_TOKEN), TOKENS)
        with self.assertRaises(gss.TokenKeyError):
            self._decrypted(OLD_SESSION)
        after = _rows(self.db)
        for b, a in zip(before, after):
            self.assertEqual((b[0], b[1], b[2], b[3], b[4], b[6], b[8]), (a[0], a[1], a[2], a[3], a[4], a[6], a[8]),
                             "account, Google identity, scopes, expiry and created_at are preserved")
        con = sqlite3.connect(self.db)
        states = con.execute(f"SELECT id, verifier_enc, used_at, handoff_used_at, result FROM {gss.STATE_TABLE} ORDER BY id").fetchall()
        con.close()
        self.assertEqual(states[0][1], "")
        self.assertTrue(states[0][2] and states[1][3])
        self.assertEqual({s[4] for s in states}, {"key_rotated"})
        self.assertEqual(_keystate(self.db), (gss.key_fingerprint(NEW_TOKEN), gss.KEY_READY))

    def test_backup_is_private_and_holds_the_old_data(self):
        report = sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups)
        self.assertEqual(stat.S_IMODE(os.stat(self.backups).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(report.backup).st_mode), 0o600)
        con = sqlite3.connect(report.backup)
        enc = con.execute(f"SELECT access_token_enc FROM {gss.CONNECTION_TABLE} WHERE id=1").fetchone()[0]
        con.close()
        self.assertEqual(gss.TokenCipher(OLD_SESSION).decrypt(enc), TOKENS[1][0])

    def test_rerun_is_a_verified_no_op(self):
        sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups)
        rows = _rows(self.db)
        report = sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups)
        self.assertTrue(report.already_migrated)
        self.assertEqual(_rows(self.db), rows)
        self.assertEqual(len(os.listdir(self.backups)), 1, "no second backup on a no-op rerun")

    def test_wrong_old_key_aborts_without_any_write(self):
        before = _rows(self.db)
        with self.assertRaises(sm.MigrationError):
            sm.migrate_sheets(self.db, {"SECRET_KEY": "some-other-session-key-1234567890-abcdef"}, self.new,
                              backup_dir=self.backups)
        self.assertEqual(_rows(self.db), before)
        self.assertIsNone(_keystate(self.db))
        self.assertFalse(os.path.exists(self.backups))

    def test_damaged_ciphertext_aborts_and_deletes_nothing(self):
        con = sqlite3.connect(self.db)
        con.execute(f"UPDATE {gss.CONNECTION_TABLE} SET refresh_token_enc='gAAAAAB-damaged' WHERE id=1")
        con.commit()
        con.close()
        before = _rows(self.db)
        with self.assertRaises(sm.MigrationError) as ctx:
            sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups)
        self.assertIn("connection 1 refresh_token_enc", str(ctx.exception))
        self.assertNotIn("1//refresh", str(ctx.exception))
        self.assertEqual(_rows(self.db), before)
        self.assertEqual(len(before), 2)

    def test_failure_inside_the_transaction_rolls_everything_back(self):
        before = _rows(self.db)
        real = gss.TokenCipher.encrypt
        calls = {"n": 0}

        def flaky(self_, value):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("disk full")
            return real(self_, value)

        with mock.patch.object(gss.TokenCipher, "encrypt", flaky), self.assertRaises(RuntimeError):
            sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups)
        self.assertEqual(_rows(self.db), before)
        self.assertIsNone(_keystate(self.db), "maintenance flag is removed again")
        self.assertEqual(self._decrypted(OLD_SESSION), TOKENS)

    def test_another_writer_holding_the_lock_makes_migration_give_up_cleanly(self):
        before = _rows(self.db)
        holder = sqlite3.connect(self.db, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        try:
            with mock.patch.object(sm, "LOCK_TIMEOUT_SEC", 0.2), self.assertRaises(sqlite3.OperationalError):
                sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups)
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        self.assertEqual(_rows(self.db), before)
        self.assertIsNone(_keystate(self.db))
        report = sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups)
        self.assertEqual(report.tokens, 3, "a later run succeeds")

    def test_unexpected_key_state_is_refused(self):
        con = sqlite3.connect(self.db)
        sm._ensure_keystate_table(con)
        con.execute(f"INSERT INTO {gss.KEY_STATE_TABLE} VALUES (1, ?, 'ready', '', ?)",
                    (gss.key_fingerprint("a-third-key-nobody-expects-0123456789abcdef"), "2026-11-08"))
        con.commit()
        con.close()
        with self.assertRaises(sm.MigrationError):
            sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups)

    def test_weak_or_reused_new_keys_are_refused(self):
        bad = [
            {"SECRET_KEY": NEW_SESSION, gss.TOKEN_KEY_ENV: OLD_SESSION},
            {"SECRET_KEY": OLD_SESSION, gss.TOKEN_KEY_ENV: NEW_TOKEN},
            {"SECRET_KEY": NEW_SESSION, gss.TOKEN_KEY_ENV: NEW_SESSION},
            {"SECRET_KEY": NEW_SESSION},
            {"SECRET_KEY": NEW_SESSION, gss.TOKEN_KEY_ENV: "short"},
        ]
        for new in bad:
            with self.subTest(new=sorted(new)), self.assertRaises(sm.MigrationError):
                sm.migrate_sheets(self.db, self.old, new, backup_dir=self.backups)
        self.assertIsNone(_keystate(self.db))

    def test_dry_run_reads_only(self):
        before = _rows(self.db)
        report = sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups, dry_run=True)
        self.assertEqual(report.tokens, 3)
        self.assertEqual(_rows(self.db), before)
        self.assertFalse(os.path.exists(self.backups))

    def test_restore_backup_rolls_back_a_completed_migration(self):
        report = sm.migrate_sheets(self.db, self.old, self.new, backup_dir=self.backups)
        safety = sm.restore_backup(self.db, report.backup, backup_dir=self.backups)
        self.assertEqual(self._decrypted(OLD_SESSION), TOKENS)
        self.assertIsNone(_keystate(self.db))
        con = sqlite3.connect(safety)
        enc = con.execute(f"SELECT access_token_enc FROM {gss.CONNECTION_TABLE} WHERE id=1").fetchone()[0]
        con.close()
        self.assertEqual(gss.TokenCipher(NEW_TOKEN).decrypt(enc), TOKENS[1][0], "migrated state kept as safety copy")

    def test_migration_from_an_existing_dedicated_key(self):
        """GOOGLE_SHEETS_TOKEN_KEY was already set: that, not SECRET_KEY, is the source."""
        old_dedicated = "an-older-dedicated-token-key-0123456789-abcdef"
        os.unlink(self.db)
        _legacy_db(self.db, material=old_dedicated)
        old = {"SECRET_KEY": OLD_SESSION, gss.TOKEN_KEY_ENV: old_dedicated}
        sm.migrate_sheets(self.db, old, self.new, backup_dir=self.backups)
        self.assertEqual(self._decrypted(NEW_TOKEN), TOKENS)


class EnvFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="bb_env_")

    def _path(self, name):
        return os.path.join(self.dir, name)

    def test_generate_and_cli_never_print_secrets(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(sm.main(["generate", "--out", self._path("new.env")]), 0)
        values = sm.parse_env_file(self._path("new.env"))
        self.assertEqual(stat.S_IMODE(os.stat(self._path("new.env")).st_mode), 0o600)
        for name in sm.SECRET_NAMES:
            self.assertFalse(sm.secret_problem(values[name]))
            self.assertNotIn(values[name], out.getvalue())
        self.assertNotEqual(values["SECRET_KEY"], values[gss.TOKEN_KEY_ENV])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sm.main(["generate", "--out", self._path("new.env")]), 2, "never overwrites")

    def test_apply_env_is_atomic_keeps_other_settings_and_backs_up(self):
        live = self._path(".env")
        with open(live, "w") as fh:
            fh.write("# local\nAPP_ENV=development\nSECRET_KEY=dev-change-in-production\nFLASK_DEBUG=1\nPORT=5001\n")
        os.chmod(live, 0o600)
        sm.generate(self._path("new.env"))
        new = sm.parse_env_file(self._path("new.env"))
        backup = sm.apply_env(live, self._path("new.env"), backup_dir=self._path("bk"),
                              extra={"FLASK_DEBUG": "0", "ALLOW_PUBLIC_REGISTER": "0"})
        result = sm.parse_env_file(live)
        self.assertEqual(result["SECRET_KEY"], new["SECRET_KEY"])
        self.assertEqual(result[gss.TOKEN_KEY_ENV], new[gss.TOKEN_KEY_ENV])
        self.assertEqual((result["APP_ENV"], result["PORT"], result["FLASK_DEBUG"], result["ALLOW_PUBLIC_REGISTER"]),
                         ("development", "5001", "0", "0"))
        self.assertEqual(stat.S_IMODE(os.stat(live).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(backup).st_mode), 0o600)
        self.assertEqual(sm.parse_env_file(backup)["SECRET_KEY"], "dev-change-in-production")
        with self.assertRaises(sm.MigrationError):
            sm.apply_env(live, self._path("new.env"), backup_dir=self._path("bk"), extra={"SECRET_KEY": "x"})

    def test_world_readable_secret_files_are_refused(self):
        p = self._path("loose.env")
        with open(p, "w") as fh:
            fh.write("SECRET_KEY=x\n")
        os.chmod(p, 0o644)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sm.main(["status", "--db", self._path("none.db"), "--env", p]), 2)

    def test_migrate_cli_requires_stopped_app(self):
        db = self._path("app.db")
        _legacy_db(db)
        sm.generate(self._path("new.env"))
        old = self._path("old.env")
        with open(old, "w") as fh:
            fh.write(f"SECRET_KEY={OLD_SESSION}\nHOST=127.0.0.1\nPORT=1\n")
        os.chmod(old, 0o600)
        err = io.StringIO()
        args = ["migrate-sheets", "--db", db, "--old-env", old, "--new-env", self._path("new.env"),
                "--backup-dir", self._path("bk")]
        with contextlib.redirect_stderr(err):
            self.assertEqual(sm.main(args), 2)
        self.assertIn("--confirm-app-stopped", err.getvalue())
        with mock.patch.object(sm, "app_is_listening", return_value=True), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sm.main(args + ["--confirm-app-stopped"]), 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(sm.main(args + ["--confirm-app-stopped"]), 0)
        new = sm.parse_env_file(self._path("new.env"))
        for value in (*new.values(), OLD_SESSION, *[t for pair in TOKENS.values() for t in pair if t]):
            self.assertNotIn(value, out.getvalue())

    def test_init_env_creates_strong_private_file_once(self):
        template = self._path("example")
        with open(template, "w") as fh:
            fh.write("SECRET_KEY=replace-with-a-long-random-string\nFLASK_DEBUG=1\nSOCKETIO_CORS_ORIGINS=*\nHOST=127.0.0.1\n")
        target = self._path(".env")
        sm.init_env(target, template)
        values = sm.parse_env_file(target)
        self.assertFalse(sm.secret_problem(values["SECRET_KEY"]))
        self.assertFalse(sm.secret_problem(values[gss.TOKEN_KEY_ENV]))
        self.assertEqual(values["FLASK_DEBUG"], "0")
        self.assertNotIn("SOCKETIO_CORS_ORIGINS", values)
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600)
        with self.assertRaises(sm.MigrationError):
            sm.init_env(target, template)


class ConnectionServiceKeyTests(unittest.TestCase):
    """The running service pauses (never deletes) when the key is missing, wrong or mid-migration."""

    @classmethod
    def setUpClass(cls):
        from app import app, db

        cls.app, cls.db = app, db
        with app.app_context():
            db.create_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        m = gss.register_models(self.db, datetime.now)
        self.Connection, self.KeyState, self.OAuthState = m.Connection, m.KeyState, m.OAuthState
        for model in (self.Connection, self.KeyState, self.OAuthState):
            self.db.session.query(model).delete()
        self.db.session.commit()

    def tearDown(self):
        for model in (self.Connection, self.KeyState, self.OAuthState):
            self.db.session.query(model).delete()
        self.db.session.commit()
        self.ctx.pop()

    def _svc(self, key):
        return gss.ConnectionService(db=self.db, now_local=datetime.now, token_key=key,
                                     client_config=lambda: ("cid", "csecret"))

    def _connection(self, material):
        c = gss.TokenCipher(material)
        row = self.Connection(account_id=4242, google_sub="s", google_email="e@gmail.com", scopes=gss.gsc.SHEETS_SCOPE,
                              access_token_enc=c.encrypt("at"), refresh_token_enc=c.encrypt("rt"),
                              access_expires_at=datetime.now() + timedelta(hours=1),
                              created_at=datetime.now(), updated_at=datetime.now())
        self.db.session.add(row)
        self.db.session.commit()

    def test_no_secret_key_fallback(self):
        svc = self._svc(None)
        self.assertIsNone(svc.cipher)
        self.assertFalse(svc.configured())
        self.assertEqual(svc.availability(), "key_missing")
        self.assertIsNone(self._svc("dev-change-in-production").cipher, "the known dev key is never a token key")

    def test_fresh_install_records_the_key_and_works(self):
        svc = self._svc(NEW_TOKEN)
        self.assertEqual(svc.availability(), "")
        self.assertEqual(self.db.session.get(self.KeyState, 1).key_check, gss.key_fingerprint(NEW_TOKEN))
        self._connection(NEW_TOKEN)
        self.assertEqual(svc.access_token(4242), "at")

    def test_legacy_data_wrong_key_and_maintenance_pause_without_dropping(self):
        self._connection(OLD_SESSION)
        svc = self._svc(NEW_TOKEN)
        self.assertEqual(svc.availability(), "legacy")
        with self.assertRaises(gss.gsc.GoogleSheetsError) as ctx:
            svc.access_token(4242)
        self.assertEqual(ctx.exception.code, "unavailable")
        self.db.session.add(self.KeyState(id=1, key_check=gss.key_fingerprint(OLD_SESSION), state=gss.KEY_READY,
                                          updated_at=datetime.now()))
        self.db.session.commit()
        self.assertEqual(svc.availability(), "key_mismatch")
        with self.assertRaises(gss.ConnectError):
            svc.disconnect(4242)
        state = self.db.session.get(self.KeyState, 1)
        state.key_check, state.state = gss.key_fingerprint(NEW_TOKEN), gss.KEY_MIGRATING
        self.db.session.commit()
        self.assertEqual(svc.availability(), "maintenance")
        with self.assertRaises(gss.gsc.GoogleSheetsError):
            svc.access_token(4242)
        self.assertEqual(self.Connection.query.count(), 1, "a key problem never deletes a connection")

    def test_undecryptable_token_is_an_error_not_an_empty_token(self):
        self._connection("yet-another-key-that-was-never-configured-123456")
        svc = self._svc(NEW_TOKEN)
        self.db.session.add(self.KeyState(id=1, key_check=gss.key_fingerprint(NEW_TOKEN), state=gss.KEY_READY,
                                          updated_at=datetime.now()))
        self.db.session.commit()
        with self.assertRaises(gss.gsc.GoogleSheetsError):
            svc.access_token(4242)
        self.assertEqual(self.Connection.query.count(), 1)


if __name__ == "__main__":
    unittest.main()
