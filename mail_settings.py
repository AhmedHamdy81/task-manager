"""Unified email / SMTP settings for System Setup and password-reset mail.

Precedence for credentials:
  1. ``MAIL_PASSWORD`` environment variable (never overwritten by the UI)
  2. Instance secret file ``instance/.mail_smtp_password`` (0600), written only
     when an administrator replaces the password in System Setup
  3. Empty (not configured)

Precedence for non-secret options:
  1. Saved ``SystemSetting`` values when non-empty
  2. Environment / Flask ``app.config`` values
  3. Safe defaults

The SMTP password is never returned to templates, APIs, logs, or audit details.
"""

from __future__ import annotations

import os
import re
import smtplib
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parseaddr
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse

from flask import Flask

import security_support as security_support_mod

MAIL_ENABLED_KEY = "mail_enabled"
MAIL_PROVIDER_KEY = "mail_provider"
MAIL_SERVER_KEY = "mail_server"
MAIL_PORT_KEY = "mail_port"
MAIL_ENCRYPTION_KEY = "mail_encryption"
MAIL_USERNAME_KEY = "mail_username"
MAIL_SENDER_NAME_KEY = "mail_sender_name"
MAIL_SENDER_EMAIL_KEY = "mail_sender_email"
MAIL_RESET_EXPIRY_MINUTES_KEY = "mail_reset_expiry_minutes"
MAIL_ADMIN_FALLBACK_KEY = "mail_admin_fallback_on_failure"

MAIL_SETTING_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    (MAIL_ENABLED_KEY, "false", "Enable outbound SMTP email delivery"),
    (MAIL_PROVIDER_KEY, "custom", "SMTP provider preset (custom, gmail, microsoft365)"),
    (MAIL_SERVER_KEY, "", "SMTP server hostname"),
    (MAIL_PORT_KEY, "587", "SMTP port"),
    (MAIL_ENCRYPTION_KEY, "starttls", "SMTP encryption: starttls, ssl, or none"),
    (MAIL_USERNAME_KEY, "", "SMTP username"),
    (MAIL_SENDER_NAME_KEY, "", "Default sender display name"),
    (MAIL_SENDER_EMAIL_KEY, "", "Default sender email address"),
    (MAIL_RESET_EXPIRY_MINUTES_KEY, "60", "Password-reset link expiry in minutes"),
    (
        MAIL_ADMIN_FALLBACK_KEY,
        "true",
        "Notify administrators when password-reset email delivery fails",
    ),
)

MAIL_PASSWORD_ENV = "MAIL_PASSWORD"
MAIL_PASSWORD_FILE_NAME = ".mail_smtp_password"
MAIL_PASSWORD_PLACEHOLDER = "••••••••"

PROVIDERS: dict[str, dict[str, str]] = {
    "custom": {"label": "Custom SMTP", "server": "", "port": "587", "encryption": "starttls"},
    "gmail": {
        "label": "Gmail",
        "server": "smtp.gmail.com",
        "port": "587",
        "encryption": "starttls",
        "help": "Use a Google App Password, not your normal Gmail password.",
    },
    "microsoft365": {
        "label": "Microsoft 365 / Outlook",
        "server": "smtp.office365.com",
        "port": "587",
        "encryption": "starttls",
    },
}

ENCRYPTION_OPTIONS: tuple[tuple[str, str], ...] = (
    ("starttls", "STARTTLS"),
    ("ssl", "SSL/TLS"),
    ("none", "None"),
)

RESET_EXPIRY_MIN = 15
RESET_EXPIRY_MAX = 1440
DEFAULT_RESET_EXPIRY_MINUTES = 60
_TEST_EMAIL_RATE_LIMIT_SEC = 60
_test_email_last_by_account: dict[int, float] = {}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _truthy_setting(value: Any) -> str:
    return "true" if _as_bool(value) else "false"


def is_valid_email(raw: str | None) -> bool:
    text = (raw or "").strip()
    if not text or len(text) > 254:
        return False
    _name, addr = parseaddr(text)
    candidate = (addr or text).strip()
    return bool(_EMAIL_RE.match(candidate))


def extract_email_address(raw: str | None) -> str:
    text = (raw or "").strip()
    _name, addr = parseaddr(text)
    return (addr or text).strip()


def mail_password_file_path(app_root: str | None = None) -> str:
    root = app_root or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(root, "instance", MAIL_PASSWORD_FILE_NAME)


def read_mail_password_secret(*, app_root: str | None = None) -> str:
    env_pw = os.environ.get(MAIL_PASSWORD_ENV)
    if env_pw is not None and str(env_pw) != "":
        return str(env_pw)
    path = mail_password_file_path(app_root)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().rstrip("\n")
    except OSError:
        return ""


def write_mail_password_secret(password: str, *, app_root: str | None = None) -> None:
    path = mail_password_file_path(app_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(password)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def mail_password_source(*, app_root: str | None = None) -> str:
    if (os.environ.get(MAIL_PASSWORD_ENV) or "").strip():
        return "environment"
    path = mail_password_file_path(app_root)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                if fh.read().rstrip("\n"):
                    return "secret_file"
        except OSError:
            pass
    return "none"


def mail_password_configured(*, app_root: str | None = None) -> bool:
    return mail_password_source(app_root=app_root) != "none"


def normalize_public_application_url(
    raw: str | None,
    *,
    require_https_in_production: bool = True,
) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    if not parsed.hostname:
        return None
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"} and security_support_mod.is_production_env():
        return None
    if (
        require_https_in_production
        and security_support_mod.is_production_env()
        and parsed.scheme != "https"
    ):
        return None
    path = (parsed.path or "").rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")).rstrip("/")


def provider_preset(provider: str) -> dict[str, str]:
    key = (provider or "custom").strip().lower()
    return dict(PROVIDERS.get(key) or PROVIDERS["custom"])


@dataclass
class MailConfig:
    enabled: bool = False
    provider: str = "custom"
    server: str = ""
    port: int = 587
    encryption: str = "starttls"
    username: str = ""
    password: str = field(default="", repr=False)
    password_configured: bool = False
    password_source: str = "none"
    password_env_locked: bool = False
    sender_name: str = ""
    sender_email: str = ""
    public_base_url: str = ""
    reset_expiry_minutes: int = DEFAULT_RESET_EXPIRY_MINUTES
    admin_fallback_on_failure: bool = True
    timeout_sec: float = 15.0

    @property
    def use_tls(self) -> bool:
        return self.encryption == "starttls"

    @property
    def use_ssl(self) -> bool:
        return self.encryption == "ssl"

    @property
    def sender_header(self) -> str:
        email = extract_email_address(self.sender_email)
        name = (self.sender_name or "").strip()
        if name and email:
            return f"{name} <{email}>"
        return email or name

    @property
    def can_send_test(self) -> bool:
        return bool(
            self.server
            and self.sender_header
            and self.password_configured
            and 1 <= self.port <= 65535
            and self.encryption in {"starttls", "ssl", "none"}
            and not (self.use_tls and self.use_ssl)
        )

    @property
    def is_ready(self) -> bool:
        return bool(self.enabled and self.can_send_test)

    def flask_mail_mapping(self) -> dict[str, Any]:
        return {
            "MAIL_ENABLED": "1" if self.enabled else "0",
            "MAIL_SERVER": self.server,
            "MAIL_PORT": str(self.port),
            "MAIL_USERNAME": self.username,
            "MAIL_PASSWORD": self.password,
            "MAIL_USE_TLS": "1" if self.use_tls else "0",
            "MAIL_USE_SSL": "1" if self.use_ssl else "0",
            "MAIL_DEFAULT_SENDER": self.sender_header,
            "MAIL_TIMEOUT_SEC": str(self.timeout_sec),
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "server": self.server,
            "port": self.port,
            "encryption": self.encryption,
            "username": self.username,
            "password_configured": self.password_configured,
            "password_source": self.password_source,
            "password_env_locked": self.password_env_locked,
            "password_placeholder": MAIL_PASSWORD_PLACEHOLDER if self.password_configured else "",
            "sender_name": self.sender_name,
            "sender_email": self.sender_email,
            "sender_header": self.sender_header,
            "public_base_url": self.public_base_url,
            "reset_expiry_minutes": self.reset_expiry_minutes,
            "admin_fallback_on_failure": self.admin_fallback_on_failure,
            "can_send_test": self.can_send_test,
            "is_ready": self.is_ready,
            "status": "configured" if self.is_ready else "not_configured",
        }


def _setting(SystemSetting, key: str, default: str = "") -> str:
    from system_seed import get_system_setting

    return get_system_setting(SystemSetting, key, default)


def _nonempty(stored: str, fallback: str) -> str:
    text = (stored or "").strip()
    return text if text else (fallback or "").strip()


def resolve_mail_config(
    SystemSetting,
    *,
    app: Flask | None = None,
    app_root: str | None = None,
    form: Mapping[str, Any] | None = None,
    include_password: bool = True,
) -> MailConfig:
    cfg = (app.config if app is not None else {}) or {}
    form = form or {}

    def form_or(key: str, setting_key: str, env_key: str, default: str = "") -> str:
        if key in form and form.get(key) is not None:
            return str(form.get(key) or "").strip()
        stored = _setting(SystemSetting, setting_key, "")
        env_val = str(cfg.get(env_key) or os.environ.get(env_key) or "").strip()
        return _nonempty(stored, env_val) or default

    if "mail_enabled" in form:
        enabled = _as_bool(form.get("mail_enabled"))
    else:
        stored = _setting(SystemSetting, MAIL_ENABLED_KEY, "")
        if stored.strip():
            enabled = _as_bool(stored)
        else:
            enabled = _as_bool(cfg.get("MAIL_ENABLED") or os.environ.get("MAIL_ENABLED"))

    provider = form_or("mail_provider", MAIL_PROVIDER_KEY, "", "custom").lower() or "custom"
    if provider not in PROVIDERS:
        provider = "custom"

    server = form_or("mail_server", MAIL_SERVER_KEY, "MAIL_SERVER", "")
    port_raw = form_or("mail_port", MAIL_PORT_KEY, "MAIL_PORT", "587")
    try:
        port = int(str(port_raw).strip() or "587")
    except (TypeError, ValueError):
        port = 587

    encryption = form_or("mail_encryption", MAIL_ENCRYPTION_KEY, "", "starttls").lower()
    if encryption not in {"starttls", "ssl", "none"}:
        if _as_bool(cfg.get("MAIL_USE_SSL")):
            encryption = "ssl"
        elif _as_bool(cfg.get("MAIL_USE_TLS")):
            encryption = "starttls"
        else:
            encryption = "none"

    username = form_or("mail_username", MAIL_USERNAME_KEY, "MAIL_USERNAME", "")
    sender_name = form_or("mail_sender_name", MAIL_SENDER_NAME_KEY, "", "")
    sender_email = form_or("mail_sender_email", MAIL_SENDER_EMAIL_KEY, "MAIL_DEFAULT_SENDER", "")
    if sender_email and "<" in sender_email and not sender_name:
        name, addr = parseaddr(sender_email)
        if addr:
            sender_name = (name or "").strip()
            sender_email = addr.strip()

    public_raw = form_or("public_application_url", "public_base_url", "", "")
    public_url = normalize_public_application_url(public_raw, require_https_in_production=False) or ""

    expiry_raw = form_or(
        "mail_reset_expiry_minutes",
        MAIL_RESET_EXPIRY_MINUTES_KEY,
        "",
        str(DEFAULT_RESET_EXPIRY_MINUTES),
    )
    try:
        expiry = int(str(expiry_raw).strip() or str(DEFAULT_RESET_EXPIRY_MINUTES))
    except (TypeError, ValueError):
        expiry = DEFAULT_RESET_EXPIRY_MINUTES
    expiry = max(RESET_EXPIRY_MIN, min(RESET_EXPIRY_MAX, expiry))

    if "mail_admin_fallback" in form:
        admin_fallback = _as_bool(form.get("mail_admin_fallback"))
    else:
        stored_fb = _setting(SystemSetting, MAIL_ADMIN_FALLBACK_KEY, "")
        admin_fallback = _as_bool(stored_fb) if stored_fb.strip() else True

    env_locked = bool((os.environ.get(MAIL_PASSWORD_ENV) or "").strip())
    password = ""
    if include_password:
        replace = str(form.get("mail_password") or "")
        if replace and replace != MAIL_PASSWORD_PLACEHOLDER:
            password = replace
        else:
            password = read_mail_password_secret(app_root=app_root)
            if not password:
                password = str(cfg.get("MAIL_PASSWORD") or "")

    pw_source = mail_password_source(app_root=app_root)
    pw_configured = bool(password) or pw_source != "none"

    try:
        timeout = float(cfg.get("MAIL_TIMEOUT_SEC") or os.environ.get("MAIL_TIMEOUT_SEC") or 15)
    except (TypeError, ValueError):
        timeout = 15.0

    return MailConfig(
        enabled=enabled,
        provider=provider,
        server=server,
        port=port,
        encryption=encryption,
        username=username,
        password=password if include_password else "",
        password_configured=pw_configured,
        password_source=pw_source,
        password_env_locked=env_locked,
        sender_name=sender_name,
        sender_email=extract_email_address(sender_email) or sender_email,
        public_base_url=public_url,
        reset_expiry_minutes=expiry,
        admin_fallback_on_failure=admin_fallback,
        timeout_sec=timeout,
    )


def validate_mail_settings(
    data: Mapping[str, Any],
    *,
    require_complete_when_enabled: bool = True,
    password_configured: bool = False,
) -> list[str]:
    errors: list[str] = []
    enabled = _as_bool(data.get("mail_enabled"))
    server = str(data.get("mail_server") or "").strip()
    port_raw = str(data.get("mail_port") or "").strip()
    encryption = str(data.get("mail_encryption") or "").strip().lower()
    username = str(data.get("mail_username") or "").strip()
    sender_email = str(data.get("mail_sender_email") or "").strip()
    public_url = str(data.get("public_application_url") or "").strip()
    expiry_raw = str(data.get("mail_reset_expiry_minutes") or "").strip()
    provider = str(data.get("mail_provider") or "custom").strip().lower()
    replace_pw = str(data.get("mail_password") or "").strip()
    if replace_pw == MAIL_PASSWORD_PLACEHOLDER:
        replace_pw = ""

    if provider not in PROVIDERS:
        errors.append("Choose a valid SMTP provider preset.")
    if encryption and encryption not in {"starttls", "ssl", "none"}:
        errors.append("Choose a valid encryption mode.")
    if encryption == "starttls" and _as_bool(data.get("mail_use_ssl")):
        errors.append("STARTTLS and SSL/TLS cannot both be enabled.")
    if encryption == "ssl" and _as_bool(data.get("mail_use_tls")):
        errors.append("STARTTLS and SSL/TLS cannot both be enabled.")

    if port_raw:
        try:
            port = int(port_raw)
            if not (1 <= port <= 65535):
                errors.append("SMTP port must be between 1 and 65535.")
        except (TypeError, ValueError):
            errors.append("SMTP port must be a number between 1 and 65535.")

    if enabled and require_complete_when_enabled:
        if not server:
            errors.append("SMTP server is required when email delivery is enabled.")
        if not sender_email or not is_valid_email(sender_email):
            errors.append("Enter a valid default sender email.")
        if provider in {"gmail", "microsoft365"} and not username:
            errors.append("SMTP username is required for this provider.")
        if not password_configured and not replace_pw:
            errors.append(
                "SMTP password is required when email delivery is enabled "
                f"(set {MAIL_PASSWORD_ENV} or use Replace password)."
            )
        if security_support_mod.is_production_env():
            if not public_url:
                errors.append("Public application URL is required in production.")
            elif not normalize_public_application_url(public_url):
                errors.append(
                    "Public application URL must be a safe https:// address in production."
                )

    if public_url and not normalize_public_application_url(
        public_url,
        require_https_in_production=security_support_mod.is_production_env(),
    ):
        errors.append(
            "Enter a valid http:// or https:// public application URL "
            "(no query string or fragment; https required in production)."
        )

    if sender_email and not is_valid_email(sender_email):
        errors.append("Default sender email is not valid.")

    if expiry_raw:
        try:
            expiry = int(expiry_raw)
            if expiry < RESET_EXPIRY_MIN or expiry > RESET_EXPIRY_MAX:
                errors.append(
                    f"Password-reset expiry must be between {RESET_EXPIRY_MIN} and {RESET_EXPIRY_MAX} minutes."
                )
        except (TypeError, ValueError):
            errors.append("Password-reset expiry must be a whole number of minutes.")

    return errors


def save_mail_settings(
    db,
    SystemSetting,
    data: Mapping[str, Any],
    *,
    app_root: str | None = None,
    replace_password: bool = False,
) -> tuple[MailConfig, list[str]]:
    from system_seed import (
        CONNECTION_HTTP_ADDRESS_DESCRIPTION,
        CONNECTION_HTTP_ADDRESS_KEY,
        set_system_setting,
    )

    errors = validate_mail_settings(
        data,
        password_configured=mail_password_configured(app_root=app_root),
    )
    if errors:
        return resolve_mail_config(SystemSetting, app_root=app_root, form=data), errors

    enabled = _as_bool(data.get("mail_enabled"))
    provider = str(data.get("mail_provider") or "custom").strip().lower() or "custom"
    server = str(data.get("mail_server") or "").strip()
    port = str(data.get("mail_port") or "587").strip()
    encryption = str(data.get("mail_encryption") or "starttls").strip().lower()
    username = str(data.get("mail_username") or "").strip()
    sender_name = str(data.get("mail_sender_name") or "").strip()
    sender_email = extract_email_address(data.get("mail_sender_email"))
    public_url = normalize_public_application_url(
        data.get("public_application_url"),
        require_https_in_production=False,
    ) or ""
    expiry = str(data.get("mail_reset_expiry_minutes") or DEFAULT_RESET_EXPIRY_MINUTES).strip()
    admin_fallback = _truthy_setting(data.get("mail_admin_fallback"))

    pairs = {
        MAIL_ENABLED_KEY: (_truthy_setting(enabled), "Enable outbound SMTP email delivery"),
        MAIL_PROVIDER_KEY: (provider, "SMTP provider preset"),
        MAIL_SERVER_KEY: (server, "SMTP server hostname"),
        MAIL_PORT_KEY: (port, "SMTP port"),
        MAIL_ENCRYPTION_KEY: (encryption, "SMTP encryption"),
        MAIL_USERNAME_KEY: (username, "SMTP username"),
        MAIL_SENDER_NAME_KEY: (sender_name, "Default sender display name"),
        MAIL_SENDER_EMAIL_KEY: (sender_email, "Default sender email address"),
        MAIL_RESET_EXPIRY_MINUTES_KEY: (expiry, "Password-reset link expiry in minutes"),
        MAIL_ADMIN_FALLBACK_KEY: (
            admin_fallback,
            "Notify administrators when password-reset email fails",
        ),
    }
    for key, (value, desc) in pairs.items():
        set_system_setting(db, SystemSetting, key, value, description=desc)

    if public_url:
        set_system_setting(
            db,
            SystemSetting,
            CONNECTION_HTTP_ADDRESS_KEY,
            public_url,
            description=CONNECTION_HTTP_ADDRESS_DESCRIPTION,
        )

    if replace_password and not (os.environ.get(MAIL_PASSWORD_ENV) or "").strip():
        new_pw = str(data.get("mail_password") or "")
        if new_pw and new_pw != MAIL_PASSWORD_PLACEHOLDER:
            write_mail_password_secret(new_pw, app_root=app_root)

    db.session.commit()
    return resolve_mail_config(SystemSetting, app_root=app_root), []


def changed_mail_setting_keys(
    before: MailConfig, after: MailConfig, *, password_replaced: bool
) -> list[str]:
    keys: list[str] = []
    mapping = [
        ("enabled", before.enabled, after.enabled),
        ("provider", before.provider, after.provider),
        ("server", before.server, after.server),
        ("port", before.port, after.port),
        ("encryption", before.encryption, after.encryption),
        ("username", before.username, after.username),
        ("sender_name", before.sender_name, after.sender_name),
        ("sender_email", before.sender_email, after.sender_email),
        ("public_base_url", before.public_base_url, after.public_base_url),
        ("reset_expiry_minutes", before.reset_expiry_minutes, after.reset_expiry_minutes),
        (
            "admin_fallback_on_failure",
            before.admin_fallback_on_failure,
            after.admin_fallback_on_failure,
        ),
    ]
    for name, a, b in mapping:
        if a != b:
            keys.append(name)
    if password_replaced:
        keys.append("password_replaced")
    return keys


def apply_mail_config_to_app(app: Flask, mail: MailConfig) -> None:
    mapping = mail.flask_mail_mapping()
    if not mapping.get("MAIL_PASSWORD") and (os.environ.get(MAIL_PASSWORD_ENV) or "").strip():
        mapping["MAIL_PASSWORD"] = os.environ.get(MAIL_PASSWORD_ENV) or ""
    app.config.update(mapping)
    app.config["MAIL_RESET_EXPIRY_MINUTES"] = int(mail.reset_expiry_minutes)
    app.config["MAIL_ADMIN_FALLBACK_ON_FAILURE"] = bool(mail.admin_fallback_on_failure)


def sanitize_smtp_error(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (
            "Authentication rejected. Check the SMTP username and password "
            "(use an App Password for Gmail)."
        )
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "Sender rejected by the mail server. Check the default sender email."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "Recipient rejected by the mail server."
    if isinstance(exc, smtplib.SMTPDataError):
        return "The mail server rejected the message content."
    if isinstance(exc, smtplib.SMTPConnectError):
        return "Server unavailable. Could not connect to the SMTP host."
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return "Server unavailable. The SMTP connection closed unexpectedly."
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "Connection timed out while contacting the SMTP server."
    if isinstance(exc, ssl.SSLError):
        return "TLS negotiation failed. Check encryption mode and port."
    if isinstance(exc, OSError):
        msg = str(exc).lower()
        if "timed out" in msg or "timeout" in msg:
            return "Connection timed out while contacting the SMTP server."
        if "ssl" in msg or "tls" in msg or "certificate" in msg:
            return "TLS negotiation failed. Check encryption mode and port."
        return "Server unavailable. Could not reach the SMTP host."
    return "Email delivery failed. Check SMTP settings and try again."


def check_test_email_rate_limit(account_id: int) -> tuple[bool, int]:
    now = time.monotonic()
    last = _test_email_last_by_account.get(int(account_id))
    if last is None:
        return True, 0
    elapsed = now - last
    if elapsed < _TEST_EMAIL_RATE_LIMIT_SEC:
        return False, int(_TEST_EMAIL_RATE_LIMIT_SEC - elapsed) + 1
    return True, 0


def mark_test_email_sent(account_id: int) -> None:
    _test_email_last_by_account[int(account_id)] = time.monotonic()


def clear_test_email_rate_limits() -> None:
    _test_email_last_by_account.clear()


def build_test_email_bodies(*, app_name: str, sender: str) -> tuple[str, str]:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = (
        f"This is a test message from {app_name}.\n\n"
        f"Sender: {sender}\n"
        f"Sent at: {stamp}\n\n"
        "If you received this email, SMTP configuration is working."
    )
    html = (
        f"<p>This is a test message from <strong>{app_name}</strong>.</p>"
        f"<p>Sender: {sender}<br>Sent at: {stamp}</p>"
        "<p>If you received this email, SMTP configuration is working.</p>"
    )
    return text, html


def example_reset_url(public_base_url: str) -> str:
    base = (public_base_url or "").rstrip("/") or "https://your-server.example.com"
    return f"{base}/reset-password/preview-token-not-real"


def ensure_mail_setting_defaults(db, SystemSetting) -> None:
    from system_seed import set_system_setting

    created = False
    for key, value, description in MAIL_SETTING_DEFAULTS:
        row = SystemSetting.query.filter_by(key=key).first()
        if row is None:
            set_system_setting(db, SystemSetting, key, value, description=description)
            created = True
    if created:
        db.session.commit()
