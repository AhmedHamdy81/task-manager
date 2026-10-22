"""Google and Apple account sign-in (OAuth 2.0 / OpenID Connect)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable
from urllib.parse import urlencode

import requests
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

logger = logging.getLogger(__name__)

PROVIDER_GOOGLE = "google"
PROVIDER_APPLE = "apple"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"

_HTTP_TIMEOUT = 20
OAUTH_STATE_SALT = "oauth-login-state"
OAUTH_STATE_MAX_AGE_SEC = 600


def dump_oauth_state(secret_key: str, payload: dict[str, str]) -> str:
    return URLSafeTimedSerializer(secret_key, salt=OAUTH_STATE_SALT).dumps(payload)


def load_oauth_state(secret_key: str, token: str | None) -> dict[str, str]:
    raw = (token or "").strip()
    if not raw:
        raise OAuthLoginError("Sign-in could not be verified. Try again.")
    try:
        data = URLSafeTimedSerializer(secret_key, salt=OAUTH_STATE_SALT).loads(
            raw, max_age=OAUTH_STATE_MAX_AGE_SEC
        )
    except SignatureExpired as exc:
        raise OAuthLoginError("Sign-in expired. Try again.") from exc
    except BadSignature as exc:
        raise OAuthLoginError("Sign-in could not be verified. Try again.") from exc
    if not isinstance(data, dict):
        raise OAuthLoginError("Sign-in could not be verified. Try again.")
    return {str(k): str(v) if v is not None else "" for k, v in data.items()}


class OAuthLoginError(Exception):
    """User-facing OAuth failure (safe to flash)."""


_oauth_config_loader: Callable[[], Any] | None = None


def set_oauth_config_loader(fn: Callable[[], Any] | None) -> None:
    """Install a loader that returns oauth_settings.OAuthConfig (app context)."""
    global _oauth_config_loader
    _oauth_config_loader = fn


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _oauth_cfg() -> Any | None:
    if _oauth_config_loader is None:
        return None
    try:
        return _oauth_config_loader()
    except Exception:
        logger.debug("OAuth settings loader failed", exc_info=True)
        return None


def google_client_id() -> str:
    cfg = _oauth_cfg()
    if cfg is not None:
        return str(getattr(cfg, "google_client_id", "") or "").strip()
    return _env("GOOGLE_OAUTH_CLIENT_ID") or _env("GOOGLE_CLIENT_ID")


def google_client_secret() -> str:
    cfg = _oauth_cfg()
    if cfg is not None:
        return str(getattr(cfg, "google_client_secret", "") or "").strip()
    return _env("GOOGLE_OAUTH_CLIENT_SECRET") or _env("GOOGLE_CLIENT_SECRET")


def apple_client_id() -> str:
    cfg = _oauth_cfg()
    if cfg is not None:
        return str(getattr(cfg, "apple_client_id", "") or "").strip()
    return _env("APPLE_OAUTH_CLIENT_ID") or _env("APPLE_CLIENT_ID") or _env("APPLE_SERVICE_ID")


def google_configured() -> bool:
    cfg = _oauth_cfg()
    if cfg is not None:
        return bool(getattr(cfg, "google_configured", False))
    return bool(google_client_id() and google_client_secret())


def apple_configured() -> bool:
    cfg = _oauth_cfg()
    if cfg is not None:
        return bool(getattr(cfg, "apple_configured", False))
    return bool(apple_client_id())


def google_authorize_url(*, redirect_uri: str, state: str, nonce: str) -> str:
    params = {
        "client_id": google_client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "access_type": "online",
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def apple_authorize_url(*, redirect_uri: str, state: str, nonce: str) -> str:
    params = {
        "client_id": apple_client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code id_token",
        "response_mode": "form_post",
        "scope": "name email",
        "state": state,
        "nonce": nonce,
    }
    return f"{APPLE_AUTH_URL}?{urlencode(params)}"


def _http_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
    resp = requests.get(url, timeout=_HTTP_TIMEOUT, **kwargs)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise OAuthLoginError("Unexpected response from the identity provider.")
    return data


def _http_post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    resp = requests.post(url, data=data, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise OAuthLoginError("Unexpected response from the identity provider.")
    return payload


def exchange_google_code(
    *,
    code: str,
    redirect_uri: str,
    post_form: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
    get_json: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Return {sub, email, name} for a Google authorization code."""
    if not google_configured():
        raise OAuthLoginError("Google sign-in is not configured.")
    if not (code or "").strip():
        raise OAuthLoginError("Google sign-in was cancelled.")
    poster = post_form or _http_post_form
    getter = get_json or _http_get_json
    try:
        token = poster(
            GOOGLE_TOKEN_URL,
            {
                "code": code.strip(),
                "client_id": google_client_id(),
                "client_secret": google_client_secret(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    except requests.RequestException as exc:
        logger.warning("Google token exchange failed: %s", exc)
        raise OAuthLoginError("Could not complete Google sign-in.") from exc
    access = (token.get("access_token") or "").strip()
    if not access:
        raise OAuthLoginError("Google did not return an access token.")
    try:
        info = getter(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access}"},
        )
    except requests.RequestException as exc:
        logger.warning("Google userinfo failed: %s", exc)
        raise OAuthLoginError("Could not read the Google account.") from exc
    email = (info.get("email") or "").strip().lower()
    sub = str(info.get("sub") or "").strip()
    verified = info.get("email_verified")
    if verified in (False, "false", "False", 0, "0"):
        raise OAuthLoginError("Google email is not verified.")
    if not sub or not email or "@" not in email:
        raise OAuthLoginError("Google did not provide a verified email.")
    name = (info.get("name") or info.get("given_name") or "").strip()
    return {"provider": PROVIDER_GOOGLE, "sub": sub, "email": email, "name": name}


def _apple_jwks(get_json: Callable[..., dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    getter = get_json or _http_get_json
    try:
        data = getter(APPLE_KEYS_URL)
    except requests.RequestException as exc:
        logger.warning("Apple JWKS fetch failed: %s", exc)
        raise OAuthLoginError("Could not verify the Apple account.") from exc
    keys = data.get("keys")
    if not isinstance(keys, list) or not keys:
        raise OAuthLoginError("Could not verify the Apple account.")
    return [k for k in keys if isinstance(k, dict)]


def verify_apple_id_token(
    id_token: str,
    *,
    nonce: str | None = None,
    get_json: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Return {sub, email, name} from a Sign in with Apple id_token."""
    if not apple_configured():
        raise OAuthLoginError("Apple sign-in is not configured.")
    raw = (id_token or "").strip()
    if not raw:
        raise OAuthLoginError("Apple sign-in was cancelled.")
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as exc:  # pragma: no cover
        raise OAuthLoginError("Apple sign-in is unavailable on this server.") from exc

    audience = apple_client_id()
    try:
        # PyJWKClient fetches JWKS; fallback to a one-shot fetch if needed.
        try:
            jwk_client = PyJWKClient(APPLE_KEYS_URL, cache_keys=True)
            signing_key = jwk_client.get_signing_key_from_jwt(raw)
            claims = jwt.decode(
                raw,
                signing_key.key,
                algorithms=["RS256"],
                audience=audience,
                issuer=APPLE_ISSUER,
            )
        except Exception:
            keys = _apple_jwks(get_json)
            header = jwt.get_unverified_header(raw)
            kid = header.get("kid")
            match = next((k for k in keys if k.get("kid") == kid), None)
            if match is None:
                raise OAuthLoginError("Could not verify the Apple account.")
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(match))
            claims = jwt.decode(
                raw,
                public_key,
                algorithms=["RS256"],
                audience=audience,
                issuer=APPLE_ISSUER,
            )
    except OAuthLoginError:
        raise
    except Exception as exc:
        logger.warning("Apple id_token verify failed: %s", exc)
        raise OAuthLoginError("Could not verify the Apple account.") from exc

    sub = str(claims.get("sub") or "").strip()
    email = (claims.get("email") or "").strip().lower()
    token_nonce = str(claims.get("nonce") or "").strip()
    if nonce and token_nonce and token_nonce != nonce:
        raise OAuthLoginError("Apple sign-in could not be verified.")
    if claims.get("email_verified") in (False, "false", "False", 0, "0"):
        raise OAuthLoginError("Apple email is not verified.")
    if not sub:
        raise OAuthLoginError("Apple did not provide an account id.")
    if not email or "@" not in email:
        raise OAuthLoginError(
            "Apple did not share an email. Use an Apple ID that allows email, or sign in with Google."
        )
    return {"provider": PROVIDER_APPLE, "sub": sub, "email": email, "name": ""}


def parse_apple_user_name(user_json: str | None) -> str:
    raw = (user_json or "").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    name = data.get("name")
    if isinstance(name, dict):
        parts = [str(name.get("firstName") or "").strip(), str(name.get("lastName") or "").strip()]
        return " ".join(p for p in parts if p)
    return str(name or "").strip()

