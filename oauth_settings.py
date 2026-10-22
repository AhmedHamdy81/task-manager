"""Google / Apple sign-in credentials for System Setup.

Client IDs live in ``SystemSetting``. The Google client secret is never stored
in the database:

  1. ``GOOGLE_OAUTH_CLIENT_SECRET`` / ``GOOGLE_CLIENT_SECRET`` env (wins)
  2. ``instance/.google_oauth_client_secret`` (0600), written from System Setup
  3. Empty
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

GOOGLE_CLIENT_ID_KEY = "google_oauth_client_id"
APPLE_CLIENT_ID_KEY = "apple_oauth_client_id"

GOOGLE_CLIENT_ID_ENVS = ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET_ENVS = ("GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_CLIENT_SECRET")
APPLE_CLIENT_ID_ENVS = ("APPLE_OAUTH_CLIENT_ID", "APPLE_CLIENT_ID", "APPLE_SERVICE_ID")

GOOGLE_SECRET_FILE_NAME = ".google_oauth_client_secret"
SECRET_PLACEHOLDER = "••••••••"

OAUTH_SETTING_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    (GOOGLE_CLIENT_ID_KEY, "", "Google OAuth web client ID for Sign in with Google"),
    (APPLE_CLIENT_ID_KEY, "", "Apple Services ID for Sign in with Apple"),
)


def _env_first(names: tuple[str, ...]) -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _app_root(app_root: str | None = None) -> str:
    return app_root or os.path.dirname(os.path.abspath(__file__))


def google_secret_file_path(*, app_root: str | None = None) -> str:
    return os.path.join(_app_root(app_root), "instance", GOOGLE_SECRET_FILE_NAME)


def read_google_client_secret(*, app_root: str | None = None) -> str:
    env_pw = _env_first(GOOGLE_CLIENT_SECRET_ENVS)
    if env_pw:
        return env_pw
    path = google_secret_file_path(app_root=app_root)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().rstrip("\n")
    except OSError:
        return ""


def write_google_client_secret(secret: str, *, app_root: str | None = None) -> None:
    path = google_secret_file_path(app_root=app_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def google_secret_source(*, app_root: str | None = None) -> str:
    if _env_first(GOOGLE_CLIENT_SECRET_ENVS):
        return "environment"
    path = google_secret_file_path(app_root=app_root)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                if fh.read().rstrip("\n"):
                    return "file"
        except OSError:
            return "none"
    return "none"


def google_secret_env_locked() -> bool:
    return bool(_env_first(GOOGLE_CLIENT_SECRET_ENVS))


@dataclass
class OAuthConfig:
    google_client_id: str = ""
    google_client_secret: str = ""
    google_secret_configured: bool = False
    google_secret_source: str = "none"
    google_secret_env_locked: bool = False
    apple_client_id: str = ""

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_secret_configured)

    @property
    def apple_configured(self) -> bool:
        return bool(self.apple_client_id)

    def public_dict(self) -> dict[str, Any]:
        return {
            "google_client_id": self.google_client_id,
            "google_secret_configured": self.google_secret_configured,
            "google_secret_env_locked": self.google_secret_env_locked,
            "google_configured": self.google_configured,
            "apple_client_id": self.apple_client_id,
            "apple_configured": self.apple_configured,
        }


def resolve_oauth_config(
    SystemSetting,
    *,
    app_root: str | None = None,
    form: Mapping[str, Any] | None = None,
    include_secret: bool = False,
) -> OAuthConfig:
    from system_seed import get_system_setting

    form = form or {}
    stored_google_id = get_system_setting(SystemSetting, GOOGLE_CLIENT_ID_KEY, "")
    stored_apple_id = get_system_setting(SystemSetting, APPLE_CLIENT_ID_KEY, "")
    google_id = (str(form.get("google_client_id") or "").strip() or _env_first(GOOGLE_CLIENT_ID_ENVS) or stored_google_id)
    apple_id = (str(form.get("apple_client_id") or "").strip() or _env_first(APPLE_CLIENT_ID_ENVS) or stored_apple_id)

    env_locked = google_secret_env_locked()
    source = google_secret_source(app_root=app_root)
    secret = ""
    if include_secret:
        submitted = str(form.get("google_client_secret") or "")
        if submitted and submitted != SECRET_PLACEHOLDER:
            secret = submitted.strip()
        else:
            secret = read_google_client_secret(app_root=app_root)
    configured = bool(secret) or source != "none"
    return OAuthConfig(
        google_client_id=google_id,
        google_client_secret=secret if include_secret else "",
        google_secret_configured=configured,
        google_secret_source=source,
        google_secret_env_locked=env_locked,
        apple_client_id=apple_id,
    )


def save_oauth_settings(
    db,
    SystemSetting,
    payload: Mapping[str, Any],
    *,
    app_root: str | None = None,
    replace_secret: bool = False,
) -> OAuthConfig:
    from system_seed import set_system_setting

    google_id = str(payload.get("google_client_id") or "").strip()
    apple_id = str(payload.get("apple_client_id") or "").strip()
    set_system_setting(
        db,
        SystemSetting,
        GOOGLE_CLIENT_ID_KEY,
        google_id,
        description="Google OAuth web client ID for Sign in with Google",
    )
    set_system_setting(
        db,
        SystemSetting,
        APPLE_CLIENT_ID_KEY,
        apple_id,
        description="Apple Services ID for Sign in with Apple",
    )
    submitted = str(payload.get("google_client_secret") or "").strip()
    if (
        replace_secret
        and submitted
        and submitted != SECRET_PLACEHOLDER
        and not google_secret_env_locked()
    ):
        write_google_client_secret(submitted, app_root=app_root)
    db.session.commit()
    return resolve_oauth_config(SystemSetting, app_root=app_root, include_secret=False)


def ensure_oauth_setting_defaults(db, SystemSetting) -> None:
    from system_seed import set_system_setting

    created = False
    for key, value, description in OAUTH_SETTING_DEFAULTS:
        row = SystemSetting.query.filter_by(key=key).first()
        if row is None:
            set_system_setting(db, SystemSetting, key, value, description=description)
            created = True
    if created:
        db.session.commit()
