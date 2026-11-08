"""Google Sheets access for Import & Compare: link parsing, OAuth requests, read-only API.

Only fixed Google endpoints are ever requested. User-supplied links are parsed into a
validated spreadsheet ID (and optional worksheet gid); request URLs are then built from
those IDs, so a pasted link can never make the server fetch an arbitrary address.
Nothing here writes to Google or changes sharing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import requests

import production_import_parsing as pip

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
SCOPES = ("openid", "email", SHEETS_SCOPE)

HTTP_TIMEOUT = 20
MAX_RESPONSE_BYTES = 40 * 1024 * 1024
GOOGLE_LIMITS = {"max_cells": 150_000}

_SERIAL_EPOCH = datetime(1899, 12, 30)


class GoogleSheetsError(Exception):
    """User-facing failure. ``code`` lets the UI pick the right state."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# --- Links ------------------------------------------------------------------------

_ID_RE = re.compile(r"[A-Za-z0-9_-]{25,100}")
_PATH_RE = re.compile(r"^/spreadsheets(?:/u/\d{1,2})?/d/([A-Za-z0-9_-]{25,100})(?:/(?:edit|view|htmlview)?)?/?$")
_OTHER_DOCS_RE = re.compile(r"^/(document|presentation|forms|drawings)(?:/u/\d{1,2})?/d/")


@dataclass(frozen=True)
class SheetsLink:
    spreadsheet_id: str
    gid: int | None

    @property
    def canonical_url(self) -> str:
        base = f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/edit"
        return base + (f"#gid={self.gid}" if self.gid is not None else "")


def _gid_from(params: dict[str, list[str]]) -> int | None:
    raw = (params.get("gid") or [""])[0]
    if raw == "":
        return None
    if not re.fullmatch(r"\d{1,10}", raw):
        raise GoogleSheetsError("invalid_link", "The worksheet part of the link (gid) is not valid.")
    return int(raw)


def parse_sheets_link(raw: str) -> SheetsLink:
    """Accept only https://docs.google.com/spreadsheets/d/<id>[/edit|/view][?…][#gid=…]."""
    text = (raw or "").strip()
    if not text:
        raise GoogleSheetsError("invalid_link", "Paste a Google Sheets link.")
    if len(text) > 2048 or any(ch.isspace() for ch in text):
        raise GoogleSheetsError("invalid_link", "That does not look like a Google Sheets link.")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise GoogleSheetsError("invalid_link", "That does not look like a Google Sheets link.") from exc
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host != "docs.google.com" or parts.username or parts.password or port not in (None, 443):
        if host == "drive.google.com":
            raise GoogleSheetsError(
                "unsupported_document",
                "This is a Google Drive file link. Open the file in Google Sheets and copy the link from the address bar.",
            )
        raise GoogleSheetsError("invalid_link", "Only links that start with https://docs.google.com/spreadsheets/ are supported.")
    path = parts.path
    if path.startswith("/spreadsheets/d/e/"):
        raise GoogleSheetsError(
            "unsupported_document",
            "Published-to-web links are not supported. Use the normal link from the spreadsheet's address bar.",
        )
    if _OTHER_DOCS_RE.match(path):
        raise GoogleSheetsError("unsupported_document", "This link is not a Google Sheets spreadsheet.")
    m = _PATH_RE.match(path)
    if not m:
        raise GoogleSheetsError("invalid_link", "That does not look like a Google Sheets spreadsheet link.")
    gid = _gid_from(parse_qs(parts.query))
    frag_gid = _gid_from(parse_qs(parts.fragment))
    return SheetsLink(spreadsheet_id=m.group(1), gid=frag_gid if frag_gid is not None else gid)


def valid_spreadsheet_id(value: str) -> bool:
    return bool(_ID_RE.fullmatch(value or ""))


# --- HTTP -------------------------------------------------------------------------


@dataclass
class HttpResult:
    status: int
    body: Any


Transport = Callable[..., HttpResult]


def default_transport(method: str, url: str, *, params=None, data=None, headers=None, max_bytes: int = MAX_RESPONSE_BYTES) -> HttpResult:
    """Fixed-endpoint HTTP with a response-size cap. Never follows redirects to other hosts."""
    if not url.startswith(("https://oauth2.googleapis.com/", "https://sheets.googleapis.com/", "https://openidconnect.googleapis.com/")):
        raise GoogleSheetsError("network", "Refused to contact an unexpected address.")
    try:
        resp = requests.request(method, url, params=params, data=data, headers=headers, timeout=HTTP_TIMEOUT,
                                stream=True, allow_redirects=False)
        chunks, size = [], 0
        for chunk in resp.iter_content(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                resp.close()
                raise GoogleSheetsError("too_large", "The spreadsheet is too large to import. Select fewer worksheets.")
            chunks.append(chunk)
    except requests.Timeout as exc:
        raise GoogleSheetsError("timeout", "Google Sheets did not respond in time. Try again.") from exc
    except requests.RequestException as exc:
        raise GoogleSheetsError("network", "Could not reach Google. Check the server's internet connection.") from exc
    raw = b"".join(chunks)
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        body = {"_raw": raw[:200].decode("utf-8", "replace")}
    return HttpResult(resp.status_code, body)


def _error_detail(body: Any) -> tuple[str, str, str]:
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, str):
        return err, str(body.get("error_description") or ""), ""
    if isinstance(err, dict):
        reason = ""
        for d in err.get("details") or []:
            if isinstance(d, dict) and d.get("reason"):
                reason = str(d["reason"])
        return str(err.get("status") or ""), str(err.get("message") or ""), reason
    return "", "", ""


def api_error(result: HttpResult) -> GoogleSheetsError:
    status, message, reason = _error_detail(result.body)
    code = result.status
    low = message.lower()
    if code == 401:
        return GoogleSheetsError("reauth", "Google access expired. Reconnect Google Sheets.")
    if code == 403:
        if reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT" or "insufficient authentication scopes" in low:
            return GoogleSheetsError("insufficient_scope", "Google Sheets read access was not granted. Reconnect and allow viewing your spreadsheets.")
        if reason in ("SERVICE_DISABLED", "API_DISABLED") or "has not been used in project" in low or "is disabled" in low:
            return GoogleSheetsError("api_disabled", "The Google Sheets API is not enabled for this server. Ask an administrator to enable it.")
        if reason in ("RATE_LIMIT_EXCEEDED", "RATE_LIMIT_EXCEEDED_PER_USER") or status == "RESOURCE_EXHAUSTED":
            return GoogleSheetsError("quota", "Google Sheets usage limit reached. Wait a minute and try again.")
        return GoogleSheetsError("forbidden", "Your Google account cannot open this spreadsheet. Ask the owner to share it with you.")
    if code == 404:
        return GoogleSheetsError("not_found", "Spreadsheet not found. Check the link and that it is shared with your Google account.")
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return GoogleSheetsError("quota", "Google Sheets usage limit reached. Wait a minute and try again.")
    if code == 400 and "not supported for this document" in low:
        return GoogleSheetsError(
            "unsupported_document",
            "This is an Excel file stored in Drive, not a Google Sheets spreadsheet. Save it as Google Sheets, or download it and upload the .xlsx.",
        )
    if code >= 500:
        return GoogleSheetsError("unavailable", "Google Sheets is temporarily unavailable. Try again shortly.")
    return GoogleSheetsError("bad_response", "Google Sheets returned an unexpected error.")


# --- OAuth ------------------------------------------------------------------------


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_url(*, client_id: str, redirect_uri: str, state: str, code_challenge: str, login_hint: str = "") -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent select_account",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(http: Transport, data: dict[str, str]) -> dict:
    result = http("POST", TOKEN_URL, data=data, max_bytes=256 * 1024)
    if result.status != 200 or not isinstance(result.body, dict):
        err, _desc, _ = _error_detail(result.body)
        if err == "invalid_grant":
            raise GoogleSheetsError("revoked", "Google access was revoked or expired. Reconnect Google Sheets.")
        raise GoogleSheetsError("oauth_failed", "Google did not accept the connection request. Try connecting again.")
    return result.body


def exchange_code(http: Transport, *, client_id: str, client_secret: str, code: str, verifier: str, redirect_uri: str) -> dict:
    token = _token_request(http, {
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
    })
    granted = set(str(token.get("scope") or "").split())
    if SHEETS_SCOPE not in granted:
        raise GoogleSheetsError(
            "insufficient_scope",
            "Google Sheets read access was not granted. Connect again and tick “See all your Google Sheets spreadsheets”.",
        )
    if not token.get("access_token"):
        raise GoogleSheetsError("oauth_failed", "Google did not return an access token.")
    return token


def refresh_access_token(http: Transport, *, client_id: str, client_secret: str, refresh_token: str) -> dict:
    token = _token_request(http, {
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    })
    if not token.get("access_token"):
        raise GoogleSheetsError("revoked", "Google access was revoked or expired. Reconnect Google Sheets.")
    return token


def revoke_token(http: Transport, token: str) -> None:
    try:
        http("POST", REVOKE_URL, data={"token": token}, max_bytes=64 * 1024)
    except GoogleSheetsError:
        pass


def fetch_identity(http: Transport, access_token: str) -> dict:
    result = http("GET", USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, max_bytes=64 * 1024)
    if result.status != 200 or not isinstance(result.body, dict):
        raise GoogleSheetsError("oauth_failed", "Could not read the connected Google account.")
    sub = str(result.body.get("sub") or "").strip()
    email = str(result.body.get("email") or "").strip().lower()
    if not sub:
        raise GoogleSheetsError("oauth_failed", "Could not read the connected Google account.")
    return {"sub": sub, "email": email}


# --- Sheets API -------------------------------------------------------------------

_META_FIELDS = (
    "spreadsheetId,properties(title,locale,timeZone),"
    "sheets(properties(sheetId,title,index,sheetType,hidden,gridProperties(rowCount,columnCount)),"
    "merges(startRowIndex,endRowIndex,startColumnIndex,endColumnIndex))"
)
_GRID_FIELDS = (
    "sheets(properties(sheetId,title),data(startRow,startColumn,"
    "rowData(values(effectiveValue,formattedValue,effectiveFormat/numberFormat))))"
)


class SheetsApi:
    """Read-only Sheets API calls. ``token(force_refresh)`` supplies a valid access token."""

    def __init__(self, token: Callable[[bool], str], http: Transport = default_transport):
        self._token = token
        self._http = http

    def _get(self, spreadsheet_id: str, params: list[tuple[str, str]]) -> dict:
        if not valid_spreadsheet_id(spreadsheet_id):
            raise GoogleSheetsError("invalid_link", "That does not look like a Google Sheets spreadsheet link.")
        url = f"{SHEETS_API}/{quote(spreadsheet_id, safe='')}"
        for attempt in (0, 1):
            result = self._http("GET", url, params=params, headers={"Authorization": f"Bearer {self._token(attempt == 1)}"})
            if result.status == 200 and isinstance(result.body, dict):
                return result.body
            if result.status == 401 and attempt == 0:
                continue
            raise api_error(result)
        raise GoogleSheetsError("reauth", "Google access expired. Reconnect Google Sheets.")

    def metadata(self, spreadsheet_id: str) -> dict:
        return self._get(spreadsheet_id, [("fields", _META_FIELDS)])

    def grid(self, spreadsheet_id: str, ranges: list[str]) -> dict:
        params = [("includeGridData", "true"), ("fields", _GRID_FIELDS)] + [("ranges", r) for r in ranges]
        return self._get(spreadsheet_id, params)


def a1_range(title: str, rows: int, cols: int) -> str:
    quoted = "'" + title.replace("'", "''") + "'"
    return f"{quoted}!A1:{_col_letter(max(1, cols))}{max(1, rows)}"


def _col_letter(n: int) -> str:
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


# --- Cells ------------------------------------------------------------------------


def to_cell(v: dict | None) -> pip.Cell:
    """Typed Sheets cell → import Cell. Formula results are used as plain values."""
    if not isinstance(v, dict):
        return pip.Cell(None, "empty")
    ev = v.get("effectiveValue")
    shown = str(v.get("formattedValue") or "")
    if not isinstance(ev, dict) or not ev:
        return pip.Cell(None, "empty")
    if "errorValue" in ev:
        err = ev.get("errorValue") or {}
        return pip.Cell(shown or f"#{err.get('type') or 'ERROR'}", "error")
    if "boolValue" in ev:
        return pip.Cell(bool(ev["boolValue"]), "bool")
    if "stringValue" in ev:
        s = str(ev["stringValue"])
        return pip.Cell(s, "text") if s.strip() else pip.Cell(None, "empty")
    if "numberValue" in ev:
        n = float(ev["numberValue"])
        nf = (v.get("effectiveFormat") or {}).get("numberFormat") or {}
        fmt = str(nf.get("type") or "")
        pattern = str(nf.get("pattern") or "")
        label = pattern or fmt
        if fmt == "DATE":
            return pip.Cell((_SERIAL_EPOCH + timedelta(days=int(n // 1))).date(), "date", fmt=label)
        if fmt == "DATE_TIME":
            return pip.Cell(_SERIAL_EPOCH + timedelta(seconds=round(n * 86400)), "datetime", fmt=label)
        if fmt == "TIME":
            secs = round(n * 86400)
            if n >= 1 or secs >= 86400 or pip.is_elapsed_format(pattern):
                return pip.Cell(timedelta(seconds=secs), "duration", fmt=label)
            return pip.Cell(dtime(secs // 3600, (secs % 3600) // 60, secs % 60), "time", fmt=label)
        value: int | float = int(n) if n.is_integer() else n
        plain = str(value)
        return pip.Cell(value, "number", shown if shown and shown != plain else "")
    return pip.Cell(shown or None, "text" if shown else "empty")


def grid_rows(sheet_json: dict, cols: int) -> list[list[pip.Cell]]:
    rows: list[list[pip.Cell]] = []
    for block in sheet_json.get("data") or []:
        for row in block.get("rowData") or []:
            cells = [to_cell(v) for v in (row.get("values") or [])[:cols]]
            rows.append(cells)
    return rows


# --- Snapshots --------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _grid_sheets(meta: dict) -> list[dict]:
    out = []
    for s in meta.get("sheets") or []:
        p = s.get("properties") or {}
        if (p.get("sheetType") or "GRID") != "GRID":
            continue
        g = p.get("gridProperties") or {}
        merges = []
        for m in s.get("merges") or []:
            try:
                merges.append((int(m.get("startRowIndex", 0)) + 1, int(m.get("startColumnIndex", 0)) + 1,
                               int(m["endRowIndex"]), int(m["endColumnIndex"])))
            except (KeyError, TypeError, ValueError):
                continue
        out.append({
            "sheet_id": int(p.get("sheetId") or 0),
            "title": str(p.get("title") or ""),
            "rows": int(g.get("rowCount") or 0),
            "cols": int(g.get("columnCount") or 0),
            "hidden": bool(p.get("hidden")),
            "merges": merges,
        })
    return out


def _bounded(sheet: dict, lim: dict) -> tuple[int, int]:
    return min(sheet["rows"], int(lim["max_rows_per_sheet"])), min(sheet["cols"], int(lim["max_columns"]))


def _limits(overrides: dict | None) -> dict:
    lim = dict(pip.DEFAULT_LIMITS)
    lim.update(GOOGLE_LIMITS)
    lim.update({k: v for k, v in (overrides or {}).items() if k in lim and v})
    return lim


def _fetch_sheets(api: SheetsApi, spreadsheet_id: str, chosen: list[dict], lim: dict) -> tuple[list[pip.Sheet], list[dict], list[str]]:
    ranges = []
    for s in chosen:
        rows, cols = _bounded(s, lim)
        ranges.append(a1_range(s["title"], rows, cols))
    body = api.grid(spreadsheet_id, ranges) if ranges else {"sheets": []}
    by_id = {int((x.get("properties") or {}).get("sheetId") or 0): x for x in body.get("sheets") or []}
    sheets, loaded, warnings = [], [], []
    for s, rng in zip(chosen, ranges):
        rows_cap, cols_cap = _bounded(s, lim)
        raw = by_id.get(s["sheet_id"]) or {}
        rows = pip._trim(grid_rows(raw, cols_cap))
        sheet = pip.Sheet(name=s["title"], rows=rows, truncated=s["rows"] > rows_cap, merges=list(s.get("merges") or []))
        sheet.errors = sum(1 for r in rows for c in r if c.kind == "error")
        if sheet.truncated:
            warnings.append(f"“{s['title']}”: only the first {rows_cap} rows are read.")
        if s["cols"] > cols_cap:
            warnings.append(f"“{s['title']}”: only the first {cols_cap} columns are read.")
        if sheet.errors:
            warnings.append(f"“{s['title']}”: {sheet.errors} cell(s) contain spreadsheet errors (for example #REF!). Their rows are marked Invalid.")
        if not rows:
            warnings.append(f"“{s['title']}” is empty.")
        sheets.append(sheet)
        loaded.append({
            "sheet_id": s["sheet_id"], "title": s["title"], "range": rng,
            "rows": len(rows), "truncated": sheet.truncated, "content_hash": pip.sheet_content_hash(sheet),
        })
    return sheets, loaded, warnings


def fetch_snapshot(api: SheetsApi, link: SheetsLink, *, sheet_ids: list[int] | None = None,
                   limits: dict | None = None) -> tuple[bytes, dict]:
    """Fetch a bounded, typed copy of the chosen worksheets. Returns (snapshot bytes, source info)."""
    lim = _limits(limits)
    meta = api.metadata(link.spreadsheet_id)
    available = _grid_sheets(meta)
    if not available:
        raise GoogleSheetsError("empty", "This spreadsheet has no worksheets with cells.")
    if len(available) > int(lim["max_sheets"]) * 4:
        raise GoogleSheetsError("too_large", "This spreadsheet has too many worksheets to import.")
    by_id = {s["sheet_id"]: s for s in available}
    if sheet_ids:
        chosen = [by_id[i] for i in sheet_ids if i in by_id]
        if not chosen:
            raise GoogleSheetsError("not_found", "The selected worksheets no longer exist in this spreadsheet.")
    else:
        visible = [s for s in available if not s["hidden"]] or available
        est_all = sum(_bounded(s, lim)[0] * _bounded(s, lim)[1] for s in visible)
        if est_all <= int(lim["max_cells"]) and len(visible) <= int(lim["max_sheets"]):
            chosen = visible
        else:
            first = by_id.get(link.gid) if link.gid is not None else None
            chosen = [first or visible[0]]
    if len(chosen) > int(lim["max_sheets"]):
        raise GoogleSheetsError("too_large", f"Select at most {int(lim['max_sheets'])} worksheets.")
    est = sum(_bounded(s, lim)[0] * _bounded(s, lim)[1] for s in chosen)
    if est > int(lim["max_cells"]):
        raise GoogleSheetsError(
            "too_large",
            f"The selected worksheets are too large ({est:,} cells; the limit is {int(lim['max_cells']):,}). Select fewer worksheets.",
        )
    sheets, loaded, warnings = _fetch_sheets(api, link.spreadsheet_id, chosen, lim)
    if all(not s.rows for s in sheets):
        raise GoogleSheetsError("empty", "The selected worksheets are empty.")
    props = meta.get("properties") or {}
    source = {
        "type": "google_sheets",
        "spreadsheet_id": link.spreadsheet_id,
        "title": str(props.get("title") or "Google Sheets spreadsheet")[:200],
        "locale": str(props.get("locale") or ""),
        "time_zone": str(props.get("timeZone") or ""),
        "gid": link.gid,
        "url": link.canonical_url,
        "fetched_at": _now_iso(),
        "available": available,
        "loaded": loaded,
    }
    return pip.encode_snapshot(source, sheets, warnings), source


def check_freshness(api: SheetsApi, source: dict, titles: list[str], *, limits: dict | None = None) -> dict:
    """Compare the selected worksheets in Google with the reviewed snapshot (never imports anything)."""
    lim = _limits(limits)
    loaded = {x["title"]: x for x in source.get("loaded") or []}
    try:
        meta = api.metadata(source["spreadsheet_id"])
        current = {s["sheet_id"]: s for s in _grid_sheets(meta)}
        chosen, changed = [], []
        for t in titles:
            snap = loaded.get(t)
            now = current.get(snap["sheet_id"]) if snap else None
            if now is None:
                changed.append(t)
            elif now["title"] != t:
                changed.append(t)
            else:
                chosen.append(now)
        _sheets, fresh, _w = _fetch_sheets(api, source["spreadsheet_id"], chosen, lim)
        for f in fresh:
            if f["content_hash"] != loaded[f["title"]]["content_hash"]:
                changed.append(f["title"])
    except GoogleSheetsError as exc:
        return {"state": "failed", "message": str(exc), "code": exc.code, "checked_at": _now_iso(), "changed": []}
    if changed:
        return {
            "state": "changed", "changed": sorted(set(changed)), "checked_at": _now_iso(),
            "message": "These worksheets changed in Google Sheets after your snapshot: " + ", ".join(sorted(set(changed))) + ".",
        }
    return {"state": "unchanged", "changed": [], "checked_at": _now_iso(),
            "message": "The selected worksheets still match your snapshot."}
