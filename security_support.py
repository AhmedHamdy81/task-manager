"""App-wide security helpers: headers, CSRF wiring, audit logging helpers."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import secrets
from datetime import datetime
from typing import Any, Callable

from flask import Flask, Request, request

logger = logging.getLogger(__name__)


def load_dotenv(path: str | None = None, *, override: bool = False) -> bool:
    """Load KEY=VALUE pairs from a .env file into os.environ (no extra dependency)."""
    env_path = path or os.path.join(os.getcwd(), ".env")
    if not os.path.isfile(env_path):
        # Fall back to package/app directory when started from elsewhere.
        here = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(here, ".env")
    if not os.path.isfile(env_path):
        return False
    loaded = False
    with open(env_path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if override or key not in os.environ:
                os.environ[key] = value
                loaded = True
    return loaded


# Endpoints that host public share UIs — keep camera/mic locked down there.
PUBLIC_SHARE_ENDPOINT_PREFIXES = ("client_review_", "color_gallery_")

# Conference pages that explicitly need live A/V (kept for clarity / tests).
CONFERENCE_MEDIA_ENDPOINTS = frozenset(
    {
        "chat_conference_room",
        "chat_conference_join",
    }
)


def is_production_env() -> bool:
    env = (
        os.environ.get("APP_ENV")
        or os.environ.get("FLASK_ENV")
        or os.environ.get("ENV")
        or ""
    ).strip().lower()
    return env in {"production", "prod"}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


# Values that shipped in examples, docs or old code. Anything here is public knowledge.
KNOWN_INSECURE_SECRETS = frozenset({
    "dev-change-in-production",
    "replace-with-a-long-random-string",
    "replace-me",
    "change-me",
    "changeme",
    "secret",
    "dev",
    "development",
    "test",
    "password",
})
MIN_SECRET_LENGTH = 32
FIRST_RUN_HINT = (
    "Run `python secrets_migration.py init-env` to create a local .env with fresh random secrets "
    "(it never overwrites an existing file), or set the value yourself with "
    "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
)


class InsecureConfigError(RuntimeError):
    """Startup refused because a security-relevant setting is missing or unsafe."""


def secret_problem(value: str | None) -> str:
    """Why a secret is unacceptable, or "" when it is usable."""
    v = (value or "").strip()
    if not v:
        return "is not set"
    if v.lower() in KNOWN_INSECURE_SECRETS or v.lower().startswith(("replace", "changeme", "change-me", "dev-change")):
        return "is a known placeholder/default value"
    if len(v) < MIN_SECRET_LENGTH:
        return f"is shorter than {MIN_SECRET_LENGTH} characters"
    if len(set(v)) < 8:
        return "has too little variety to be random"
    return ""


WEAK_PASSWORDS = frozenset({"password", "replace-me", "admin", "changeme", "change-me", "guest", "12345678",
                            "password1", "letmein", "welcome"})
MIN_BOOTSTRAP_PASSWORD_LENGTH = 12


def weak_password_problem(value: str | None) -> str:
    v = (value or "").strip()
    if v.lower() in WEAK_PASSWORDS:
        return "a known default"
    if len(v) < MIN_BOOTSTRAP_PASSWORD_LENGTH:
        return f"shorter than {MIN_BOOTSTRAP_PASSWORD_LENGTH} characters"
    return ""


def is_testing_env() -> bool:
    """Automated tests opt in with an isolated database URI; never valid in production."""
    return bool((os.environ.get("TASK_MANAGER_TEST_DATABASE") or "").strip())


def resolve_secret_key(*, testing: bool = False) -> str:
    """SECRET_KEY must be a strong, non-placeholder value outside automated tests.

    Tests without an explicit key get a fresh random one per process, never a constant.
    """
    key = (os.environ.get("SECRET_KEY") or "").strip()
    if testing:
        return key or secrets.token_urlsafe(48)
    problem = secret_problem(key)
    if problem:
        raise InsecureConfigError(f"SECRET_KEY {problem}. {FIRST_RUN_HINT}")
    return key


def resolve_allow_public_register() -> bool:
    """
    Public self-registration. Off unless ALLOW_PUBLIC_REGISTER=1.

    Production also requires ALLOW_PUBLIC_REGISTER_CONFIRMED=1.
    """
    want = _env_truthy("ALLOW_PUBLIC_REGISTER")
    if not is_production_env():
        return want
    if not want:
        return False
    if not _env_truthy("ALLOW_PUBLIC_REGISTER_CONFIRMED"):
        raise InsecureConfigError(
            "ALLOW_PUBLIC_REGISTER=1 in production also requires "
            "ALLOW_PUBLIC_REGISTER_CONFIRMED=1 to confirm open signup is intentional."
        )
    return True


def parse_allowed_storage_roots() -> tuple[str, ...] | None:
    """
    Return configured storage root prefixes, or None to use built-in defaults.

    Env: ALLOWED_STORAGE_ROOTS=/Volumes/A,/Volumes/B
    """
    raw = (os.environ.get("ALLOWED_STORAGE_ROOTS") or "").strip()
    if not raw:
        return None
    parts: list[str] = []
    for item in raw.split(","):
        p = item.strip()
        if not p:
            continue
        # Normalize to a prefix form suitable for startswith checks.
        slash = p.replace("\\", "/").rstrip("/")
        if not slash.startswith("/"):
            continue
        parts.append(slash + "/")
    return tuple(parts) if parts else None


def enforce_production_config() -> None:
    """Fail fast on unsafe production configuration."""
    if not is_production_env():
        return

    app_env = (os.environ.get("APP_ENV") or "").strip().lower()
    if app_env not in {"production", "prod"}:
        raise InsecureConfigError(
            "Production mode requires APP_ENV=production (do not rely on FLASK_ENV alone)."
        )
    if is_testing_env():
        raise InsecureConfigError("TASK_MANAGER_TEST_DATABASE must never be set in production.")
    if _env_truthy("FLASK_DEBUG") or _env_truthy("DEBUG"):
        raise InsecureConfigError("FLASK_DEBUG must be off in production (the debugger allows code execution).")

    resolve_secret_key()

    if not _env_truthy("SESSION_COOKIE_SECURE"):
        raise InsecureConfigError(
            "SESSION_COOKIE_SECURE=1 is required in production (HTTPS-only session cookies)."
        )

    origins = socketio_cors_origins()
    insecure = [o for o in origins if not o.startswith("https://")]
    if insecure:
        raise InsecureConfigError("SOCKETIO_CORS_ORIGINS must list https:// origins in production: " + ", ".join(insecure))

    hosts = allowed_hosts()
    if not (os.environ.get("ALLOWED_HOSTS") or "").strip():
        raise InsecureConfigError(
            "ALLOWED_HOSTS is required in production (comma-separated host names this server answers to)."
        )
    if "*" in hosts:
        raise InsecureConfigError("ALLOWED_HOSTS=* is not allowed in production.")

    roots = parse_allowed_storage_roots()
    if not roots:
        raise InsecureConfigError(
            "ALLOWED_STORAGE_ROOTS is required in production "
            "(comma-separated absolute prefixes, e.g. /Volumes/BigBang_Projects,/Volumes/BigBang_Backup)."
        )

    trusted_proxy_count()
    sheets_key = os.environ.get("GOOGLE_SHEETS_TOKEN_KEY")
    if sheets_key is not None and sheets_key.strip():
        problem = secret_problem(sheets_key)
        if problem:
            raise InsecureConfigError(f"GOOGLE_SHEETS_TOKEN_KEY {problem}.")

    # Validates confirmed open-registration flag if enabled.
    resolve_allow_public_register()


def configure_secure_session(app: Flask) -> None:
    """HttpOnly + SameSite=Lax always; Secure in production or when explicitly enabled.

    Plain-HTTP loopback development keeps non-Secure cookies, otherwise browsers drop
    the session on http://127.0.0.1 and nobody can sign in.
    """
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    # Flask ships SESSION_COOKIE_SAMESITE=None, so setdefault() would never apply Lax.
    if app.config.get("SESSION_COOKIE_SAMESITE") not in ("Lax", "Strict"):
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    secure = _env_truthy("SESSION_COOKIE_SECURE")
    if is_production_env() or secure:
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["PREFERRED_URL_SCHEME"] = "https"
    else:
        app.config.setdefault("SESSION_COOKIE_SECURE", False)


# --- Network: loopback binding, debug, hosts, proxies -------------------------------

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def is_loopback_host(host: str | None) -> bool:
    h = (host or "").strip().strip("[]").lower()
    if h in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def resolve_bind_host() -> str:
    """Development binds to loopback unless ALLOW_NON_LOOPBACK_DEV=1 is set explicitly."""
    host = (os.environ.get("HOST") or "127.0.0.1").strip()
    if not is_production_env() and not is_loopback_host(host) and not _env_truthy("ALLOW_NON_LOOPBACK_DEV"):
        raise InsecureConfigError(
            f"HOST={host} exposes the development server to the network. Use HOST=127.0.0.1, "
            "or set ALLOW_NON_LOOPBACK_DEV=1 to confirm that this is intentional."
        )
    return host


def resolve_debug(host: str) -> bool:
    """The Werkzeug debugger allows code execution: explicit opt-in, loopback, never production."""
    want = _env_truthy("FLASK_DEBUG") or _env_truthy("DEBUG")
    if not want:
        return False
    if is_production_env():
        raise InsecureConfigError("FLASK_DEBUG must be off in production.")
    if not is_loopback_host(host):
        raise InsecureConfigError("FLASK_DEBUG=1 is only allowed when HOST is a loopback address.")
    return True


def _port() -> str:
    return (os.environ.get("PORT") or "5001").strip()


def allowed_hosts() -> list[str]:
    """Host names this server answers to (Host header allowlist; protects generated links)."""
    raw = (os.environ.get("ALLOWED_HOSTS") or "").strip()
    if raw:
        return [h.strip().lower() for h in raw.split(",") if h.strip()]
    hosts = list(LOOPBACK_HOSTS)
    bind = (os.environ.get("HOST") or "").strip().lower()
    if bind and bind not in hosts and bind not in ("0.0.0.0", "::"):
        hosts.append(bind)
    return hosts


def host_allowed(host_header: str | None, hosts: list[str]) -> bool:
    raw = (host_header or "").strip().lower()
    if not raw:
        return False
    if raw.startswith("["):
        name = raw[1:raw.find("]")] if "]" in raw else raw
    else:
        name = raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw
    for allowed in hosts:
        if allowed == "*" or name == allowed:
            return True
        if allowed.startswith(".") and (name.endswith(allowed) or name == allowed[1:]):
            return True
    return False


def register_host_check(app: Flask) -> None:
    hosts = allowed_hosts()
    app.config["ALLOWED_HOSTS"] = hosts

    @app.before_request
    def _reject_unknown_host():
        if not host_allowed(request.host, app.config.get("ALLOWED_HOSTS") or hosts):
            from flask import abort

            abort(400)


def trusted_proxy_count() -> int:
    """Number of reverse proxies in front of the app whose X-Forwarded-* headers are trusted.

    0 (default) means forwarded headers are ignored entirely.
    """
    raw = (os.environ.get("TRUSTED_PROXY_COUNT") or "0").strip()
    try:
        n = int(raw)
    except ValueError as exc:
        raise InsecureConfigError("TRUSTED_PROXY_COUNT must be a whole number (0 when there is no proxy).") from exc
    if n < 0 or n > 5:
        raise InsecureConfigError("TRUSTED_PROXY_COUNT must be between 0 and 5.")
    return n


def configure_proxy(app: Flask) -> None:
    n = trusted_proxy_count()
    app.config["TRUSTED_PROXY_COUNT"] = n
    if n:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n, x_port=n)


def configure_csrf(app: Flask) -> Any:
    """Initialize Flask-WTF CSRFProtect. Disabled automatically when TESTING=True."""
    from flask_wtf.csrf import CSRFProtect

    app.config.setdefault("WTF_CSRF_ENABLED", not app.config.get("TESTING", False))
    app.config.setdefault("WTF_CSRF_TIME_LIMIT", None)
    app.config.setdefault("WTF_CSRF_HEADERS", ["X-CSRFToken", "X-CSRF-Token"])
    app.config.setdefault("WTF_CSRF_METHODS", ["POST", "PUT", "PATCH", "DELETE"])
    csrf = CSRFProtect()
    csrf.init_app(app)
    return csrf


def exempt_public_token_views(app: Flask, csrf: Any) -> None:
    """Token-gated share links authenticate via URL secret, not session cookies."""
    if csrf is None:
        return
    for endpoint, view in list(app.view_functions.items()):
        if not endpoint:
            continue
        if endpoint in {"login_apple_callback"}:
            try:
                csrf.exempt(view)
            except Exception:  # noqa: BLE001 — Apple posts id_token without our CSRF token
                logger.debug("Could not CSRF-exempt %s", endpoint, exc_info=True)
            continue
        if endpoint.startswith("client_review_") or endpoint.startswith("color_gallery_"):
            try:
                csrf.exempt(view)
            except Exception:  # noqa: BLE001 — best-effort exemption
                logger.debug("Could not CSRF-exempt %s", endpoint, exc_info=True)


def permissions_policy_for_endpoint(endpoint: str | None) -> str:
    """
    Default: lock camera / mic / geolocation.

    Allow microphone on chat pages (voice notes) and camera+mic on conference rooms.
    Public token share pages stay fully locked down. Browser still prompts the user.
    """
    if endpoint and any(endpoint.startswith(p) for p in PUBLIC_SHARE_ENDPOINT_PREFIXES):
        return "camera=(), microphone=(), geolocation=()"
    if endpoint in CONFERENCE_MEDIA_ENDPOINTS:
        return "camera=(self), microphone=(self), geolocation=()"
    # Voice-note capture in global / project chat UIs.
    if endpoint and (
        endpoint == "chat"
        or endpoint.startswith("chat_")
        or endpoint.startswith("project_chat_")
    ):
        return "camera=(), microphone=(self), geolocation=()"
    return "camera=(), microphone=(), geolocation=()"


def build_content_security_policy() -> str:
    """
    Baseline CSP.

    'unsafe-eval' is omitted. 'unsafe-inline' remains until inline <script> blocks
    in templates (see TODOs below) are moved to external files.
    """
    # TODO(security): migrate remaining inline scripts off 'unsafe-inline':
    # - templates/base.html (sidebar collapse, task status wiring, fragment URLs)
    # - templates/project_team.html (scope manage modal)
    # - templates/partials/project_team_panel.html (user picker)
    # - VFX progress sheet: move config into JSON <script type="application/json">
    #   or data-* attributes, then load static/js without inline.
    return (
        "default-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'self'; "
        "object-src 'none'; "
        # TODO(security): remove 'unsafe-inline' after migrating inline scripts.
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.socket.io https://meet.jit.si; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https:; "
        "media-src 'self' blob: data:; "
        "connect-src 'self' ws: wss: https:; "
        "frame-src 'self' https://meet.jit.si https://*.jit.si;"
    )


def apply_security_headers(response, endpoint: str | None = None):
    """Attach baseline security headers without breaking existing inline scripts."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers["Permissions-Policy"] = permissions_policy_for_endpoint(endpoint)
    response.headers.setdefault("Content-Security-Policy", build_content_security_policy())
    if is_production_env():
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def register_security_headers(app: Flask) -> None:
    @app.after_request
    def _security_headers(response):
        return apply_security_headers(response, endpoint=request.endpoint)


def client_ip(req: Request | None = None) -> str | None:
    """Peer address. X-Forwarded-For is honoured only through ProxyFix (TRUSTED_PROXY_COUNT)."""
    req = req or request
    return req.remote_addr or None


def build_audit_logger(
    db: Any,
    model: Any,
    *,
    now_fn: Callable[[], datetime],
) -> Callable[..., None]:
    """
    Return log_security_event(action, ...) that writes SecurityAuditLog rows.

    Failures are logged but never raised — audit must not break primary flows.
    """

    def log_security_event(
        action: str,
        *,
        account_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        project_id: int | None = None,
        details: dict[str, Any] | None = None,
        req: Request | None = None,
    ) -> None:
        try:
            req = req or request
            row = model(
                account_id=account_id,
                action=(action or "")[:120],
                entity_type=(entity_type or "")[:64] or None,
                entity_id=entity_id,
                project_id=project_id,
                ip_address=(client_ip(req) or "")[:64] or None,
                user_agent=((req.headers.get("User-Agent") or "")[:512] or None) if req else None,
                details_json=json.dumps(details, default=str)[:8000] if details else None,
                created_at=now_fn(),
            )
            db.session.add(row)
            db.session.commit()
        except Exception:  # noqa: BLE001
            try:
                db.session.rollback()
            except Exception:  # noqa: BLE001
                pass
            logger.exception("Failed to write security audit log for %s", action)

    return log_security_event


def socketio_cors_origins() -> list[str]:
    """Explicit Socket.IO origins. Wildcards are rejected everywhere.

    Unset in development: the loopback origins of this server's port.
    """
    raw = (os.environ.get("SOCKETIO_CORS_ORIGINS") or "").strip()
    parts = [p.strip().rstrip("/") for p in raw.split(",") if p.strip()]
    if any(p == "*" or "*" in p for p in parts):
        raise InsecureConfigError(
            "SOCKETIO_CORS_ORIGINS=* is not allowed. List the exact origins (e.g. http://127.0.0.1:5001), "
            "or leave it unset in local development."
        )
    if is_production_env():
        if not parts:
            raise InsecureConfigError("SOCKETIO_CORS_ORIGINS is required in production.")
        return parts
    if parts:
        return parts
    port = _port()
    return [f"http://127.0.0.1:{port}", f"http://localhost:{port}", f"http://[::1]:{port}"]
