"""Google and Apple account sign-in (OAuth 2.0 / OpenID Connect).

Login state is not a signed token any more: each attempt is a random, single-use,
server-side record bound to the browser session that started it (oauth_login_state.py).
Google identity comes from the ID token, verified for signature, issuer, audience,
expiry and nonce; the authorization code is exchanged with PKCE.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from typing import Any, Callable
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

PROVIDER_GOOGLE = "google"
PROVIDER_APPLE = "apple"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
# Google is the mail provider for these, so a verified claim proves ownership of the address.
GOOGLE_AUTHORITATIVE_DOMAINS = frozenset({"gmail.com", "googlemail.com"})

APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
APPLE_AUTHORITATIVE_DOMAINS = frozenset({"privaterelay.appleid.com", "icloud.com", "me.com", "mac.com"})

_HTTP_TIMEOUT = 20
ID_TOKEN_LEEWAY_SEC = 60


class OAuthLoginError(Exception):
    """User-facing OAuth failure (safe to flash)."""


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _claim_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


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


def google_authorize_url(*, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
    # Sign-in only: no include_granted_scopes, so earlier Google Sheets grants never ride along.
    params = {
        "client_id": google_client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
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


_google_jwk_client = None


def _google_signing_key(id_token: str):
    global _google_jwk_client
    from jwt import PyJWKClient

    if _google_jwk_client is None:
        _google_jwk_client = PyJWKClient(GOOGLE_CERTS_URL, cache_keys=True, timeout=_HTTP_TIMEOUT)
    return _google_jwk_client.get_signing_key_from_jwt(id_token).key


def verify_google_id_token(
    id_token: str,
    *,
    nonce: str,
    client_id: str,
    signing_key: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Verified claims of a Google ID token, or OAuthLoginError (fail closed)."""
    raw = (id_token or "").strip()
    if not raw:
        raise OAuthLoginError("Google did not return an identity token.")
    if not nonce:
        raise OAuthLoginError("Sign-in could not be verified. Try again.")
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - PyJWT is in requirements.txt
        raise OAuthLoginError("Google sign-in is unavailable on this server.") from exc
    try:
        key = (signing_key or _google_signing_key)(raw)
        claims = jwt.decode(
            raw,
            key,
            algorithms=["RS256"],
            audience=client_id,
            leeway=ID_TOKEN_LEEWAY_SEC,
            options={"require": ["iss", "aud", "exp", "iat", "sub"]},
        )
    except OAuthLoginError:
        raise
    except Exception as exc:
        logger.warning("Google ID token rejected: %s", type(exc).__name__)
        raise OAuthLoginError("Could not verify the Google account.") from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise OAuthLoginError("Could not verify the Google account.")
    azp = claims.get("azp")
    if azp and azp != client_id:
        raise OAuthLoginError("Could not verify the Google account.")
    if not hmac.compare_digest(str(claims.get("nonce") or "").encode(), nonce.encode()):
        raise OAuthLoginError("Sign-in could not be verified. Try again.")
    return claims


def google_profile_from_claims(claims: dict[str, Any]) -> dict[str, Any]:
    email = str(claims.get("email") or "").strip().lower()
    sub = str(claims.get("sub") or "").strip()
    if not sub:
        raise OAuthLoginError("Google did not provide an account id.")
    if not email or "@" not in email:
        raise OAuthLoginError("Google did not provide an email address.")
    if not _claim_true(claims.get("email_verified")):
        raise OAuthLoginError("Google has not verified this email address.")
    domain = _email_domain(email)
    hosted = str(claims.get("hd") or "").strip().lower()
    name = str(claims.get("name") or claims.get("given_name") or "").strip()
    return {
        "provider": PROVIDER_GOOGLE,
        "sub": sub,
        "email": email,
        "name": name,
        # Google is authoritative for Gmail and for Workspace domains it hosts (hd claim).
        "email_authoritative": domain in GOOGLE_AUTHORITATIVE_DOMAINS or (bool(hosted) and hosted == domain),
    }


def exchange_google_code(
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    nonce: str,
    post_form: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
    signing_key: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Exchange a code (PKCE) and return the verified Google profile."""
    if not google_configured():
        raise OAuthLoginError("Google sign-in is not configured.")
    if not (code or "").strip():
        raise OAuthLoginError("Google sign-in was cancelled.")
    if not code_verifier:
        raise OAuthLoginError("Sign-in could not be verified. Try again.")
    poster = post_form or _http_post_form
    client_id = google_client_id()
    try:
        token = poster(
            GOOGLE_TOKEN_URL,
            {
                "code": code.strip(),
                "client_id": client_id,
                "client_secret": google_client_secret(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
    except requests.RequestException as exc:
        logger.warning("Google token exchange failed: %s", type(exc).__name__)
        raise OAuthLoginError("Could not complete Google sign-in.") from exc
    claims = verify_google_id_token(
        str(token.get("id_token") or ""), nonce=nonce, client_id=client_id, signing_key=signing_key
    )
    return google_profile_from_claims(claims)


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
    nonce_hash: str | None = None,
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
                options={"require": ["iss", "aud", "exp", "iat", "sub"]},
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
                options={"require": ["iss", "aud", "exp", "iat", "sub"]},
            )
    except OAuthLoginError:
        raise
    except Exception as exc:
        logger.warning("Apple id_token verify failed: %s", exc)
        raise OAuthLoginError("Could not verify the Apple account.") from exc

    sub = str(claims.get("sub") or "").strip()
    email = (claims.get("email") or "").strip().lower()
    token_nonce = str(claims.get("nonce") or "").strip()
    # The nonce is mandatory: an ID token minted for another sign-in must never be accepted.
    if nonce:
        nonce_ok = hmac.compare_digest(token_nonce.encode(), str(nonce).encode())
    elif nonce_hash:
        nonce_ok = bool(token_nonce) and hmac.compare_digest(
            hashlib.sha256(token_nonce.encode("utf-8")).hexdigest(), nonce_hash
        )
    else:
        nonce_ok = False
    if not token_nonce or not nonce_ok:
        raise OAuthLoginError("Apple sign-in could not be verified.")
    if not _claim_true(claims.get("email_verified")):
        raise OAuthLoginError("Apple email is not verified.")
    if not sub:
        raise OAuthLoginError("Apple did not provide an account id.")
    if not email or "@" not in email:
        raise OAuthLoginError(
            "Apple did not share an email. Use an Apple ID that allows email, or sign in with Google."
        )
    return {
        "provider": PROVIDER_APPLE,
        "sub": sub,
        "email": email,
        "name": "",
        "email_authoritative": _email_domain(email) in APPLE_AUTHORITATIVE_DOMAINS,
    }


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

