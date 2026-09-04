"""Multi-language (en/ar) helpers for Flask-Babel."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import redirect, request, session, url_for

SUPPORTED_LOCALES = ("en", "ar")
DEFAULT_LOCALE = "en"
RTL_LOCALES = frozenset({"ar"})


def normalize_lang(lang: str | None) -> str:
    key = (lang or "").strip().lower()
    if key in SUPPORTED_LOCALES:
        return key
    return DEFAULT_LOCALE


def session_lang() -> str:
    return normalize_lang(session.get("lang"))


def is_rtl_locale(lang: str | None = None) -> bool:
    return normalize_lang(lang if lang is not None else session_lang()) in RTL_LOCALES


def text_direction_for(lang: str | None = None) -> str:
    return "rtl" if is_rtl_locale(lang) else "ltr"


def safe_redirect_back(fallback_endpoint: str = "index") -> str:
    """Return a same-origin relative URL, or a fallback route."""
    candidates = (
        request.args.get("next"),
        request.form.get("next"),
        request.referrer,
    )
    for raw in candidates:
        target = (raw or "").strip()
        if not target:
            continue
        parsed = urlparse(target)
        if parsed.scheme or parsed.netloc:
            # Absolute URL — only allow same host.
            if parsed.netloc and parsed.netloc != request.host:
                continue
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            if path.startswith("/") and not path.startswith("//"):
                return path
            continue
        if target.startswith("/") and not target.startswith("//"):
            return target
    try:
        return url_for(fallback_endpoint)
    except Exception:
        return "/"


def redirect_after_language_change():
    return redirect(safe_redirect_back())
