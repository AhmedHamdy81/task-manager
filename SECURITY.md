# Security notes for BIGbang Task Manager

## Production checklist

Use `.env.production.example` as a template. Startup refuses to run when any of these is
missing or unsafe (`security_support.enforce_production_config`):

1. `APP_ENV=production`; `FLASK_DEBUG` off; `TASK_MANAGER_TEST_DATABASE` unset
2. Strong `SECRET_KEY` (32+ random characters; known placeholders are refused everywhere)
3. `SESSION_COOKIE_SECURE=1` (HTTPS only); `HttpOnly` and `SameSite=Lax` are always set
4. `ALLOWED_HOSTS=your-host` (Host-header allowlist; protects password-reset/OAuth links)
5. `SOCKETIO_CORS_ORIGINS=https://your-host` (explicit `https://` origins, **never** `*`)
6. `TRUSTED_PROXY_COUNT` = number of reverse proxies in front (forwarded headers are ignored otherwise)
7. `ALLOWED_STORAGE_ROOTS=/Volumes/…,/Volumes/…` (explicit prefixes)
8. `ALLOW_PUBLIC_REGISTER=0` (or `=1` **and** `ALLOW_PUBLIC_REGISTER_CONFIRMED=1`)
9. `GOOGLE_SHEETS_TOKEN_KEY` (dedicated, different from `SECRET_KEY`) if Google Sheets is used
10. `BOOTSTRAP_ADMIN_PASSWORD` only for the very first admin (12+ characters; never a default)
11. Keep uploads under `instance/uploads/` (outside `/static`)
12. Rotate any credentials that were ever committed, shared or left at a default

## Local development

- First run: `python secrets_migration.py init-env` creates `.env` (mode 600) with random
  secrets; it never overwrites an existing file. There is no built-in fallback key.
- The server binds to `127.0.0.1` by default. Another `HOST` needs `ALLOW_NON_LOOPBACK_DEV=1`.
- `FLASK_DEBUG=1` is opt-in and only accepted with a loopback `HOST`.
- Plain-HTTP loopback keeps `SESSION_COOKIE_SECURE=0`, otherwise browsers drop the session.
- Automated tests set `TASK_MANAGER_TEST_DATABASE`; they get random per-process secrets,
  CSRF off (tests that check CSRF turn it back on) and throttling off (throttle tests turn it on).

## What uses which secret

| Secret | Used for | Rotating it invalidates |
|---|---|---|
| `SECRET_KEY` | Flask session cookie, CSRF tokens, Socket.IO auth tokens, password-reset links, import-plan signatures, throttle bucket hashing | every signed-in session (users sign in again), open forms (reload the page), live Socket.IO connections (reconnect on reload), unused password-reset links, the comparison step of unfinished imports (press "Compare again"), all sign-in throttle counters |
| `GOOGLE_SHEETS_TOKEN_KEY` | Fernet encryption of stored Google Sheets access/refresh tokens and PKCE verifiers | nothing, when rotated with `migrate-sheets` (tokens are re-encrypted); without the migration Google Sheets pauses (it never deletes connections) |

Sign-in state, Google Sheets consent state and Desktop handoff links are random server-side
records, not signed with either key. Flask 3.0 has no `SECRET_KEY_FALLBACKS`, and none is
configured: cookies signed with an old key are rejected.

## Rotating SECRET_KEY and the Google Sheets token key

Older code derived the Google Sheets token key from `SECRET_KEY` when
`GOOGLE_SHEETS_TOKEN_KEY` was unset, so stored tokens must be re-encrypted **before**
`SECRET_KEY` changes. `secrets_migration.py` reads secrets only from 0600 files, prints only
counts and key fingerprints, and refuses to write while the app answers on its port.

```bash
# 0. Stop the application. Install requirements (PyJWT is needed for Google sign-in).
python secrets_migration.py status --db instance/app.db --env .env
python secrets_migration.py generate --out instance/secrets.new.env        # mode 600, never printed
python secrets_migration.py migrate-sheets --db instance/app.db --old-env .env \
    --new-env instance/secrets.new.env --backup-dir instance/secret-backups --dry-run
python secrets_migration.py migrate-sheets --db instance/app.db --old-env .env \
    --new-env instance/secrets.new.env --backup-dir instance/secret-backups --confirm-app-stopped
python secrets_migration.py apply-env --env .env --new-env instance/secrets.new.env \
    --backup-dir instance/secret-backups --confirm-app-stopped
python secrets_migration.py status --db instance/app.db --env .env        # must say "matches"
# Start the application, sign in, check Google Sheets, then delete instance/secrets.new.env.
```

What `migrate-sheets` does: verifies every encrypted field decrypts with the old key (any
failure aborts with nothing changed, and no connection is ever deleted); writes an
integrity-checked backup (directory 0700, file 0600); sets a maintenance flag so new-code
instances pause Google Sheets; then, in one `BEGIN IMMEDIATE` transaction, re-encrypts every
token, verifies it against the new key, confirms account/Google identity/scopes/expiry are
unchanged, invalidates pending consent attempts and unused Desktop handoff links (users
simply click "Connect" again), and records the new key's fingerprint. Re-running is a
verified no-op; a database marked with an unknown key is refused.

Rollback:
- Failure during `migrate-sheets`: the transaction is rolled back automatically.
- Database migrated but `.env` not yet updated: run `apply-env`, or put the backup back with
  `restore-backup --db instance/app.db --backup <file> --backup-dir instance/secret-backups --confirm-app-stopped`.
- `.env` updated but the app misbehaves: stop it, copy the `env-*.bak` file from the backup
  directory back over `.env`, run `restore-backup`, and restore the previous code version
  (current code refuses the old development `SECRET_KEY` by design).

Backups contain encrypted tokens and the old `.env` contains the old secrets: keep the backup
directory private and delete it once the new configuration is confirmed.

## Sign-in protections

- Google/Apple sign-in: each attempt is a random, single-use, 10-minute server record bound
  to the browser session that started it (multiple tabs of that browser are fine). Browser
  binding, single use and expiry are checked before the authorization code is exchanged.
  Google uses PKCE, and its ID token is verified (signature, issuer, audience, expiry, nonce,
  `email_verified`). A callback never replaces an account that is already signed in.
- An existing BigBang account is linked by email only when the provider owns the mailbox
  (Gmail, a Google-hosted Workspace domain via `hd`, Apple-issued addresses) and the account
  has no other identity at that provider. Pending/suspended accounts stay restricted.
- "Connect Google Sheets" is a separate authorization that never changes the BigBang login.
- Throttling (`login_throttle.py`, stored in the database, shared across workers): password
  sign-in per account and per client address, password-reset requests and submissions,
  OAuth starts and registrations. Answers are generic; cooldowns grow and always expire.
  Administrator recovery: `python login_throttle.py --db instance/app.db --env .env
  --clear-login someone@example.com` (or `--clear-ip ADDRESS`, `--purge`).

## Project roles (decided policy)

- **Leads**: a project member (not Guest / Machine Room) whose job titles include one marked
  *Supervisor* may create project notes, and may add or remove team members **within their
  own scopes** (their assigned scope on the project plus their job-title scopes). Adding
  requires choosing one of those scopes; eligibility checks still apply and admin overrides
  are ignored. Removing or re-scoping someone requires all of that member's scopes to be the
  Lead's. Enforced in the routes; covered by `tests/test_route_authorization.py`.
- **Super Users** keep administrator access. Their sidebar hides Projects, Tasks, Booking,
  VFX and Color to keep it focused; direct URLs still work (hidden, not blocked).

## Desktop shell (macOS Electron)

The `desktop/` package at the repository root is a **thin HTTPS client** (`BigBang.app`).
It must load the **same** production origin as the browser. There is no `PUBLIC_BASE_URL`
env var in Flask today — set `PRODUCTION_APP_URL` in `desktop/main.cjs` and keep
`SOCKETIO_CORS_ORIGINS` identical.

- Do not grant Electron clients extra server permissions.
- Do not treat the Electron user-agent as authentication.
- Do not add Electron-specific CORS when loading the real HTTPS URL.
- Session cookies (`Secure` + `HttpOnly` + `SameSite=Lax`), CSRF, and Socket.IO/WSS
  continue to enforce access on the Flask server.
- Legacy `task-manager/electron-desktop/` (local Flask + filesystem IPC) is deprecated.

## What is protected

- Session login gate on most HTTP routes
- Flask-WTF CSRF on POST/PUT/PATCH/DELETE (token-gated review/share links exempt; tokens are `secrets.token_urlsafe(32)`)
- Permission service checks for modules and project membership
- Path allowlists via `ALLOWED_STORAGE_ROOTS` / `path_security.py`
- Upload extension + magic-byte (+ Pillow image) validation
- Chat attachment routes check thread/project membership
- Security headers (nosniff, frame options, referrer, CSP without `unsafe-eval`)
- Camera/microphone Permissions-Policy allowed for in-app UI (chat, profile, conferences); denied on public share pages
- `SecurityAuditLog` for auth, role/permission changes, storage, mounts, volumes, uploads/deletes, token share access

## Reporting issues

Report suspected vulnerabilities privately to the studio administrators. Do not open public issues with exploit details.
