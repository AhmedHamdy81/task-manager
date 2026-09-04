"""Small SMTP mailer used by account-security flows.

Configuration is supplied by Flask's ``app.config`` so production secrets stay
in the environment and tests can replace delivery without contacting a server.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any, Mapping


class MailConfigurationError(RuntimeError):
    """Raised when mail delivery is enabled but required settings are absent."""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def send_email(
    config: Mapping[str, Any],
    *,
    to_address: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> bool:
    """Deliver one email. Return ``False`` when mail is intentionally disabled."""
    if not _as_bool(config.get("MAIL_ENABLED")):
        return False

    host = str(config.get("MAIL_SERVER") or "").strip()
    sender = str(config.get("MAIL_DEFAULT_SENDER") or "").strip()
    recipient = (to_address or "").strip()
    if not host or not sender or not recipient:
        raise MailConfigurationError(
            "MAIL_SERVER, MAIL_DEFAULT_SENDER, and a recipient are required"
        )

    port = int(config.get("MAIL_PORT") or 587)
    username = str(config.get("MAIL_USERNAME") or "").strip()
    password = str(config.get("MAIL_PASSWORD") or "")
    use_ssl = _as_bool(config.get("MAIL_USE_SSL"))
    use_tls = _as_bool(config.get("MAIL_USE_TLS"))
    timeout = float(config.get("MAIL_TIMEOUT_SEC") or 15)
    if use_ssl and use_tls:
        raise MailConfigurationError("MAIL_USE_SSL and MAIL_USE_TLS cannot both be enabled")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(host, port, timeout=timeout) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
    return True
