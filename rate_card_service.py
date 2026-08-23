"""Studio Rate Card — editable service rates seeded from RATE_CARD_EGP_2024_V02.

The Working Hours page edits one global studio rate card (not per-project).
Defaults match the 2024 EGP PDF: hourly rates for all services, plus daily
rates for Copy/Convert/Sync, Offline, and Online.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import fitz

CURRENCY = "EGP"
CURRENCIES = ("EGP", "USD", "EUR")
UNIT_HOUR = "Hour"
UNIT_FEE = "Fee"
BILLING_UNITS = (UNIT_HOUR, UNIT_FEE)
RATE_CARD_TITLE = "RATE CARD"
RATE_CARD_YEAR = "2024"

_RATE_CARD_DIR = Path(__file__).resolve().parent / "static" / "rate_card"
_REFERENCE_PDF = _RATE_CARD_DIR / "RATE_CARD_REFERENCE.pdf"
_FONT_PATH = _RATE_CARD_DIR / "HelveticaNeue-CondensedBold.ttf"
_WATERMARK_PATH = _RATE_CARD_DIR / "watermark-bigbang.png"

# Page geometry matched to RATE_CARD_EGP_2024_V02.pdf (1024×768).
_PAGE_W = 1024.0
_PAGE_H = 768.0
_BG = (33 / 255, 33 / 255, 33 / 255)
_TITLE = (131 / 255, 134 / 255, 134 / 255)
_TEXT = (166 / 255, 170 / 255, 169 / 255)
_RATE = (131 / 255, 135 / 255, 134 / 255)
_LINE = (0.3725, 0.3961, 0.4078)
_HEADER_RULE = (0.6510, 0.6667, 0.6627)
_ZEBRA = (0.8647, 0.8703, 0.8786)
_TABLE_LEFT = 156.0
_TABLE_RIGHT = 868.27
_TABLE_MID = 461.84
_TABLE_TOP = 152.0
_TABLE_BOTTOM = 628.74
_HEADER_LINE_Y = 78.2
_WATERMARK_RECT = fitz.Rect(680.35, 610.02, 993.76, 744.49)

# Seeded from /Users/hamdy/Downloads/RATE_CARD_EGP_2024_V02.pdf
DEFAULT_RATE_CARD_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "service_key": "copy_convert_sync",
        "service_name": "Copy & Convert & Sync",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("750"),
        "rate_day": Decimal("7500"),
    },
    {
        "service_key": "offline_editing",
        "service_name": "Offline Editing",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("2500"),
        "rate_day": Decimal("25000"),
    },
    {
        "service_key": "online_editing",
        "service_name": "Online Editing",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("3000"),
        "rate_day": Decimal("30000"),
    },
    {
        "service_key": "color_grading_senior_colorist",
        "service_name": "Color Grading / Senior Colorist",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("15000"),
        "rate_day": None,
    },
    {
        "service_key": "color_grading_colorist",
        "service_name": "Color Grading / Colorist",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("10000"),
        "rate_day": None,
    },
    {
        "service_key": "color_grading_dry_rent",
        "service_name": "Color Grading / Dry Rent",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("10000"),
        "rate_day": None,
    },
    {
        "service_key": "sound_design_mix",
        "service_name": "Sound Design & Mix",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("1250"),
        "rate_day": None,
    },
    {
        "service_key": "upload_download_1g",
        "service_name": "Upload & Download / 1G",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("500"),
        "rate_day": None,
    },
)

LOCKED_DEFAULT_SERVICE_KEYS: frozenset[str] = frozenset(
    str(item["service_key"]) for item in DEFAULT_RATE_CARD_ITEMS
) | frozenset({"offline", "online"})
_DEFAULT_ITEM_BY_KEY: dict[str, dict[str, Any]] = {
    str(item["service_key"]): item for item in DEFAULT_RATE_CARD_ITEMS
}

# Daily Worksheet reference services — added only when missing (no duplicates).
WORKSHEET_DEFAULT_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "service_key": "copy_convert",
        "service_name": "Copy&Convert",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("750"),
        "rate_day": None,
        "include_in_pdf": False,
        "aliases": ("copy_convert_sync", "copy_convert", "copy_media", "convert_transcode"),
    },
    {
        "service_key": "sync",
        "service_name": "Sync",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("750"),
        "rate_day": None,
        "include_in_pdf": True,
        "aliases": ("sync",),
    },
    {
        "service_key": "selection",
        "service_name": "Selection",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("2500"),
        "rate_day": None,
        "include_in_pdf": True,
        "aliases": ("selection",),
    },
    {
        "service_key": "edit",
        "service_name": "Edit",
        "billing_unit": UNIT_HOUR,
        "rate_hour": Decimal("2500"),
        "rate_day": None,
        "include_in_pdf": False,
        "aliases": ("edit", "offline", "online", "offline_editing", "online_editing"),
    },
    {
        "service_key": "edit_fee",
        "service_name": "Edit",
        "billing_unit": UNIT_FEE,
        "rate_hour": Decimal("80000"),
        "rate_day": None,
        "include_in_pdf": False,
        "aliases": ("edit_fee",),
    },
)


def normalize_currency(raw: Any) -> str:
    """Return a supported currency code; defaults to EGP."""
    code = str(raw or "").strip().upper()
    if code in CURRENCIES:
        return code
    return CURRENCY


def normalize_billing_unit(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in ("fee", "fixed", "fixed_fee", "manual_fee"):
        return UNIT_FEE
    return UNIT_HOUR


def service_key_for(name: str, *, explicit: Any = None) -> str:
    import project_work_ledger_service as pwls

    key = str(explicit or "").strip()
    slug = (
        pwls.slugify_key(key, fallback="", max_len=64)
        if key
        else pwls.slugify_key(name, fallback="", max_len=64)
    )
    if not slug:
        return ""
    return pwls.canonical_work_type(slug)


def is_locked_default_key(key: Any, *, name: Any = None) -> bool:
    """True for studio PDF seed services — rename/remove is not allowed."""
    resolved = service_key_for(str(name or ""), explicit=key)
    raw = str(key or "").strip()
    return resolved in LOCKED_DEFAULT_SERVICE_KEYS or raw in LOCKED_DEFAULT_SERVICE_KEYS


def parse_money(raw: Any) -> Decimal | None:
    """Parse a money field; blank -> None. Rejects negatives and junk."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = re.sub(r"(?i)\b(EGP|USD|EUR)\b", "", text).replace(",", "").strip()
    text = re.sub(r"[^\d.]", "", text)
    if not text:
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if value < 0:
        return None
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_money(value: Any, *, currency: str = CURRENCY) -> str:
    if value is None or value == "":
        return "—"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "—"
    quantized = amount.quantize(Decimal("1") if amount == amount.to_integral_value() else Decimal("0.01"))
    if quantized == quantized.to_integral_value():
        rendered = f"{int(quantized):,}"
    else:
        rendered = f"{quantized:,.2f}"
    return f"{currency} {rendered}"


def format_money_pdf(value: Any, *, currency: str = CURRENCY) -> str:
    """Reference PDF uses a non-breaking space between currency and amount."""
    label = format_money(value, currency=currency)
    if label == "—":
        return "-"
    return label.replace(" ", "\u00a0", 1)


def _money_input_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if amount == amount.to_integral_value():
        return str(int(amount))
    return format(amount.normalize(), "f")


def serialize_item(row: Any) -> dict[str, Any]:
    currency = normalize_currency(getattr(row, "currency", None))
    name = (row.service_name or "").strip()
    unit = normalize_billing_unit(getattr(row, "billing_unit", None))
    key = service_key_for(name, explicit=getattr(row, "service_key", None))
    locked = is_locked_default_key(key, name=name)
    catalog = _DEFAULT_ITEM_BY_KEY.get(key)
    if locked and catalog:
        name = str(catalog["service_name"])
        unit = normalize_billing_unit(catalog.get("billing_unit"))
        key = str(catalog["service_key"])
    return {
        "id": int(row.id) if getattr(row, "id", None) is not None else None,
        "service_name": name,
        "service_key": key,
        "billing_unit": unit,
        "is_default": locked,
        "rate_hour": float(row.rate_hour) if row.rate_hour is not None else None,
        "rate_day": float(row.rate_day) if row.rate_day is not None else None,
        "rate_hour_input": _money_input_value(row.rate_hour),
        "rate_day_input": _money_input_value(row.rate_day),
        "rate_hour_label": format_money(row.rate_hour, currency=currency),
        "rate_day_label": format_money(row.rate_day, currency=currency),
        "include_in_pdf": bool(getattr(row, "include_in_pdf", True)),
        "sort_order": int(row.sort_order or 0),
        "currency": currency,
    }


def card_currency(items: list[Any] | None) -> str:
    """Currency for the whole card (first row wins; default EGP)."""
    if not items:
        return CURRENCY
    first = items[0]
    if isinstance(first, dict):
        return normalize_currency(first.get("currency"))
    return normalize_currency(getattr(first, "currency", None))


# Worksheet-only rows that should not appear as separate Work Type options.
_WORK_TYPE_UI_SKIP_KEYS = frozenset({"edit", "copy_convert"})


def work_type_choices(items: list[Any] | None) -> list[dict[str, str]]:
    """Manual-entry and filter Work Type options from Rate Card services.

    Aliases such as Offline / Edit collapse to the ledger work type
    (``offline_editing`` → "Offline Editing").
    """
    import project_work_ledger_service as pwls

    choices: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items or []:
        if isinstance(item, dict):
            name = str(item.get("service_name") or "").strip()
            key = service_key_for(name, explicit=item.get("service_key"))
            unit = normalize_billing_unit(item.get("billing_unit"))
        else:
            name = str(getattr(item, "service_name", "") or "").strip()
            key = service_key_for(name, explicit=getattr(item, "service_key", None))
            unit = normalize_billing_unit(getattr(item, "billing_unit", None))
        if not name or not key or key in _WORK_TYPE_UI_SKIP_KEYS:
            continue
        canon = pwls.canonical_work_type(key)
        if canon in seen or key in seen:
            continue
        seen.add(canon)
        seen.update(pwls.work_type_equivalent_keys(canon))
        generic = name.lower() in ("offline", "online", "edit") or key in (
            "offline",
            "online",
            "edit",
        )
        label = pwls.WORK_TYPE_LABELS[canon] if generic and canon in pwls.WORK_TYPE_LABELS else name
        choices.append({"key": canon, "label": label, "billing_unit": unit})
    return choices


def billing_unit_for_work_type(items: list[Any] | None, work_type: str) -> str:
    """Resolve Hour/Fee for a work_type key from the rate card."""
    import project_work_ledger_service as pwls

    wanted = set(pwls.work_type_equivalent_keys(work_type))
    for choice in work_type_choices(items):
        if choice["key"] in wanted:
            return normalize_billing_unit(choice.get("billing_unit"))
    return UNIT_HOUR


def work_type_label_map(items: list[Any] | None) -> dict[str, str]:
    import project_work_ledger_service as pwls

    mapping: dict[str, str] = {}
    for row in work_type_choices(items):
        mapping[row["key"]] = row["label"]
        for alias in pwls.work_type_equivalent_keys(row["key"]):
            mapping[alias] = row["label"]
    return mapping


def list_items(model: Any) -> list[Any]:
    return (
        model.query.order_by(model.sort_order.asc(), model.id.asc()).all()
    )


def delete_item(db: Any, model: Any, item_id: int) -> tuple[Any | None, str | None]:
    """Delete one custom rate-card row.

    Returns ``(row, None)`` on success, ``(None, "not_found")`` if missing,
    or ``(None, "locked_default")`` for studio PDF seed services.
    """
    row = model.query.filter_by(id=int(item_id)).first()
    if row is None:
        return None, "not_found"
    name = str(getattr(row, "service_name", "") or "").strip()
    key = service_key_for(name, explicit=getattr(row, "service_key", None))
    if is_locked_default_key(key, name=name):
        return None, "locked_default"
    db.session.delete(row)
    return row, None


def list_pdf_items(model: Any) -> list[Any]:
    return [
        row
        for row in list_items(model)
        if bool(getattr(row, "include_in_pdf", True))
    ]


def _existing_keys(model: Any) -> set[str]:
    keys: set[str] = set()
    for row in list_items(model):
        name = str(getattr(row, "service_name", "") or "").strip()
        key = service_key_for(name, explicit=getattr(row, "service_key", None))
        if key:
            keys.add(key)
            import project_work_ledger_service as pwls

            keys.update(pwls.work_type_equivalent_keys(key))
        name_slug = service_key_for(name)
        if name_slug:
            keys.add(name_slug)
        unit = normalize_billing_unit(getattr(row, "billing_unit", None))
        if name_slug and unit == UNIT_FEE:
            keys.add(f"{name_slug}__fee")
    return keys


def ensure_defaults(db: Any, model: Any) -> int:
    """Insert PDF defaults when the rate card table is empty. Returns rows created."""
    if model.query.count() > 0:
        return 0
    created = 0
    for idx, item in enumerate(DEFAULT_RATE_CARD_ITEMS):
        db.session.add(
            model(
                service_name=item["service_name"],
                service_key=item.get("service_key") or service_key_for(item["service_name"]),
                billing_unit=normalize_billing_unit(item.get("billing_unit")),
                rate_hour=item["rate_hour"],
                rate_day=item["rate_day"],
                currency=CURRENCY,
                include_in_pdf=True,
                sort_order=idx,
            )
        )
        created += 1
    return created


def ensure_worksheet_defaults(db: Any, model: Any) -> int:
    """Add Daily Worksheet services when equivalent keys are missing."""
    existing = _existing_keys(model)
    created = 0
    next_order = model.query.count()
    for item in WORKSHEET_DEFAULT_ITEMS:
        key = str(item["service_key"])
        aliases = set(item.get("aliases") or ()) | {key}
        # Fee Edit must not be skipped just because hourly Edit/Offline exists.
        if item.get("billing_unit") == UNIT_FEE:
            if key in existing or f"{service_key_for(item['service_name'])}__fee" in existing:
                continue
        elif aliases & existing:
            continue
        db.session.add(
            model(
                service_name=item["service_name"],
                service_key=key,
                billing_unit=normalize_billing_unit(item.get("billing_unit")),
                rate_hour=item.get("rate_hour"),
                rate_day=item.get("rate_day"),
                currency=CURRENCY,
                include_in_pdf=bool(item.get("include_in_pdf", True)),
                sort_order=next_order + created,
            )
        )
        created += 1
        existing.add(key)
    return created


_CANONICAL_SERVICE_KEYS = {
    "offline": ("offline_editing", "Offline Editing"),
    "online": ("online_editing", "Online Editing"),
}


def align_canonical_service_keys(db: Any, model: Any) -> int:
    """Point legacy Offline/Online rows at the ledger work types used in the log."""
    changed = 0
    for row in list_items(model):
        key = str(getattr(row, "service_key", "") or "").strip()
        mapped = _CANONICAL_SERVICE_KEYS.get(key)
        if not mapped:
            continue
        new_key, default_name = mapped
        name = str(getattr(row, "service_name", "") or "").strip()
        row.service_key = new_key
        if name.lower() in ("", "offline", "online"):
            row.service_name = default_name
        changed += 1
    return changed


def parse_items_from_form(form: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Parse parallel form arrays into validated item payloads."""
    names = form.getlist("service_name") if hasattr(form, "getlist") else []
    hours = form.getlist("rate_hour") if hasattr(form, "getlist") else []
    days = form.getlist("rate_day") if hasattr(form, "getlist") else []
    includes = form.getlist("include_in_pdf") if hasattr(form, "getlist") else []
    units = form.getlist("billing_unit") if hasattr(form, "getlist") else []
    keys = form.getlist("service_key") if hasattr(form, "getlist") else []
    currency = normalize_currency(form.get("currency") if hasattr(form, "get") else None)
    if not names:
        return None, "Add at least one rate card service."

    items: list[dict[str, Any]] = []
    for idx, raw_name in enumerate(names):
        name = (raw_name or "").strip()
        hour_raw = hours[idx] if idx < len(hours) else ""
        day_raw = days[idx] if idx < len(days) else ""
        include_raw = includes[idx] if idx < len(includes) else "1"
        unit_raw = units[idx] if idx < len(units) else UNIT_HOUR
        key_raw = keys[idx] if idx < len(keys) else ""
        if not name and not str(hour_raw).strip() and not str(day_raw).strip():
            continue
        if not name:
            return None, f"Service name is required on row {idx + 1}."
        if len(name) > 160:
            return None, f"Service name is too long on row {idx + 1}."
        rate_hour = parse_money(hour_raw)
        rate_day = parse_money(day_raw)
        if str(hour_raw).strip() and not re.fullmatch(r"\d+", str(hour_raw).strip().replace(",", "")):
            return None, f"Hourly rate must be numbers only on row {idx + 1}."
        if str(day_raw).strip() and not re.fullmatch(r"\d+", str(day_raw).strip().replace(",", "")):
            return None, f"Daily rate must be numbers only on row {idx + 1}."
        if rate_hour is None and str(hour_raw).strip():
            return None, f"Invalid hourly rate on row {idx + 1}."
        if rate_day is None and str(day_raw).strip():
            return None, f"Invalid daily rate on row {idx + 1}."
        if rate_hour is None and rate_day is None:
            return None, f"Enter an hourly or daily rate for {name}."
        unit = normalize_billing_unit(unit_raw)
        items.append(
            {
                "service_name": name,
                "service_key": service_key_for(name, explicit=key_raw),
                "billing_unit": unit,
                "rate_hour": rate_hour,
                "rate_day": rate_day,
                "include_in_pdf": str(include_raw).strip() in ("1", "true", "on", "yes"),
                "currency": currency,
                "sort_order": len(items),
            }
        )

    if not items:
        return None, "Add at least one rate card service."
    return items, None


def _lock_item_identity(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    key = service_key_for(
        str(payload.get("service_name") or ""),
        explicit=payload.get("service_key"),
    )
    catalog = _DEFAULT_ITEM_BY_KEY.get(key)
    if not catalog:
        payload["service_key"] = key
        return payload
    payload["service_key"] = str(catalog["service_key"])
    payload["service_name"] = str(catalog["service_name"])
    payload["billing_unit"] = normalize_billing_unit(catalog.get("billing_unit"))
    return payload


def apply_locked_defaults(
    parsed: list[dict[str, Any]] | None,
    *,
    existing_rows: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Keep PDF seed services; restore name/unit; fill any omitted defaults."""
    items = [_lock_item_identity(item) for item in (parsed or [])]
    currency = CURRENCY
    if items:
        currency = normalize_currency(items[0].get("currency"))

    by_key: dict[str, dict[str, Any]] = {}
    extras: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("service_key") or "")
        if is_locked_default_key(key, name=item.get("service_name")):
            by_key[key] = item
        else:
            extras.append(item)

    existing_by_key: dict[str, Any] = {}
    for row in existing_rows or []:
        name = str(getattr(row, "service_name", "") or "").strip()
        key = service_key_for(name, explicit=getattr(row, "service_key", None))
        if is_locked_default_key(key, name=name):
            existing_by_key[key] = row

    merged: list[dict[str, Any]] = []
    for catalog in DEFAULT_RATE_CARD_ITEMS:
        key = str(catalog["service_key"])
        if key in by_key:
            payload = dict(by_key[key])
        elif key in existing_by_key:
            row = existing_by_key[key]
            payload = {
                "service_name": catalog["service_name"],
                "service_key": key,
                "billing_unit": normalize_billing_unit(catalog.get("billing_unit")),
                "rate_hour": getattr(row, "rate_hour", None),
                "rate_day": getattr(row, "rate_day", None),
                "include_in_pdf": bool(getattr(row, "include_in_pdf", True)),
                "currency": currency,
            }
        else:
            payload = {
                "service_name": catalog["service_name"],
                "service_key": key,
                "billing_unit": normalize_billing_unit(catalog.get("billing_unit")),
                "rate_hour": catalog.get("rate_hour"),
                "rate_day": catalog.get("rate_day"),
                "include_in_pdf": True,
                "currency": currency,
            }
        payload["sort_order"] = len(merged)
        merged.append(payload)

    for extra in extras:
        payload = dict(extra)
        payload["currency"] = currency
        payload["sort_order"] = len(merged)
        merged.append(payload)
    return merged


def replace_items(db: Any, model: Any, items: list[dict[str, Any]]) -> list[Any]:
    """Full replace of the studio rate card."""
    model.query.delete()
    rows = []
    for item in items:
        name = item["service_name"]
        row = model(
            service_name=name,
            service_key=item.get("service_key") or service_key_for(name),
            billing_unit=normalize_billing_unit(item.get("billing_unit")),
            rate_hour=item.get("rate_hour"),
            rate_day=item.get("rate_day"),
            currency=item.get("currency") or CURRENCY,
            include_in_pdf=bool(item.get("include_in_pdf", True)),
            sort_order=int(item.get("sort_order") or 0),
        )
        db.session.add(row)
        rows.append(row)
    db.session.flush()
    return rows


def _pdf_fontfile() -> str | None:
    if _FONT_PATH.is_file():
        return str(_FONT_PATH)
    return None


def _draw_hline(page: fitz.Page, x0: float, x1: float, y: float, *, color=_LINE, width: float = 2.0) -> None:
    page.draw_line(fitz.Point(x0, y), fitz.Point(x1, y), color=color, width=width)


def _draw_vline(page: fitz.Page, x: float, y0: float, y1: float, *, color=_LINE, width: float = 2.0) -> None:
    page.draw_line(fitz.Point(x, y0), fitz.Point(x, y1), color=color, width=width)


def _insert_left(
    page: fitz.Page,
    text: str,
    *,
    x: float,
    y_baseline: float,
    fontsize: float,
    color: tuple[float, float, float],
    fontname: str,
) -> None:
    page.insert_text(
        (x, y_baseline),
        text,
        fontname=fontname,
        fontsize=fontsize,
        color=color,
    )


def _insert_right(
    page: fitz.Page,
    text: str,
    *,
    x_right: float,
    y_baseline: float,
    fontsize: float,
    color: tuple[float, float, float],
    fontname: str,
    font: fitz.Font | None,
) -> None:
    width = font.text_length(text, fontsize=fontsize) if font is not None else fontsize * len(text) * 0.5
    page.insert_text(
        (x_right - width, y_baseline),
        text,
        fontname=fontname,
        fontsize=fontsize,
        color=color,
    )


def _build_rates_page(doc: fitz.Document, items: list[Any], *, year: str, currency: str) -> None:
    """Rebuild the middle rates page to match the reference fonts/colors/layout."""
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.draw_rect(page.rect, color=None, fill=_BG)

    fontfile = _pdf_fontfile()
    fontname = "helv"
    font: fitz.Font | None = None
    if fontfile:
        try:
            page.insert_font(fontname="HNCB", fontfile=fontfile)
            fontname = "HNCB"
            font = fitz.Font(fontfile=fontfile)
        except Exception:
            fontname = "helv"
            font = None

    # Title — "RATE CARD" + smaller year, matching reference placement.
    _insert_left(page, RATE_CARD_TITLE, x=36, y_baseline=60, fontsize=24, color=_TITLE, fontname=fontname)
    title_w = font.text_length(RATE_CARD_TITLE, fontsize=24) if font else 124
    _insert_left(
        page,
        f" {year}",
        x=36 + title_w,
        y_baseline=54,
        fontsize=16,
        color=_TITLE,
        fontname=fontname,
    )

    # Top rule under title
    _draw_hline(page, 32, 992, _HEADER_LINE_Y, color=_HEADER_RULE, width=2)

    currency = normalize_currency(currency)
    hour_rows = []
    day_rows = []
    for row in items:
        name = (getattr(row, "service_name", None) or "").strip() or "—"
        hour_val = getattr(row, "rate_hour", None)
        day_val = getattr(row, "rate_day", None)
        if hour_val is not None and str(hour_val) != "":
            hour_rows.append((name, format_money_pdf(hour_val, currency=currency)))
        if day_val is not None and str(day_val) != "":
            day_rows.append((name, format_money_pdf(day_val, currency=currency)))

    # Fallback: if nothing qualifies, still show names with em dash.
    if not hour_rows and not day_rows:
        for row in items:
            name = (getattr(row, "service_name", None) or "").strip() or "—"
            hour_rows.append((name, "-"))

    sections: list[tuple[str, list[tuple[str, str]]]] = []
    if hour_rows:
        sections.append(("RATE/HOUR", hour_rows))
    if day_rows:
        sections.append(("RATE/DAY", day_rows))

    content_row_count = sum(1 + len(rows) for _, rows in sections)
    usable = _TABLE_BOTTOM - _TABLE_TOP
    row_h = usable / max(content_row_count, 1)
    row_h = min(row_h, 36.6)
    # Re-center vertically if fewer rows than the reference card.
    table_height = row_h * content_row_count
    table_top = _TABLE_TOP + max(0.0, (_TABLE_BOTTOM - _TABLE_TOP - table_height) * 0.15)
    table_bottom = table_top + table_height

    # Outer + mid frame
    _draw_hline(page, _TABLE_LEFT, _TABLE_RIGHT, table_top, width=2)
    _draw_hline(page, _TABLE_LEFT, _TABLE_RIGHT, table_bottom, width=2)
    _draw_vline(page, _TABLE_LEFT, table_top, table_bottom, width=2)
    _draw_vline(page, _TABLE_RIGHT, table_top, table_bottom, width=2)
    _draw_vline(page, _TABLE_MID, table_top, table_bottom, width=5)

    y = table_top
    rate_right = _TABLE_RIGHT - 6.0
    service_left = 162.0
    fontsize = 22 if row_h >= 32 else max(14, row_h * 0.55)
    row_index = 0

    def _centered_in(text: str, x0: float, x1: float) -> float:
        width = font.text_length(text, fontsize=fontsize) if font is not None else fontsize * len(text) * 0.5
        return x0 + max(0.0, (x1 - x0 - width) / 2)

    for section_idx, (rate_label, rows) in enumerate(sections):
        # Section header
        y1 = y + row_h
        baseline = y + row_h * 0.72
        _insert_left(
            page,
            "SERVICE",
            x=_centered_in("SERVICE", _TABLE_LEFT, _TABLE_MID),
            y_baseline=baseline,
            fontsize=fontsize,
            color=_TEXT,
            fontname=fontname,
        )
        _insert_left(
            page,
            rate_label,
            x=_centered_in(rate_label, _TABLE_MID, _TABLE_RIGHT),
            y_baseline=baseline,
            fontsize=fontsize,
            color=_TEXT,
            fontname=fontname,
        )
        _draw_hline(page, _TABLE_LEFT, _TABLE_RIGHT, y1, width=5 if section_idx == 0 else 2)
        _draw_vline(page, _TABLE_MID, y, y1, width=2)
        y = y1
        row_index += 1

        for name, rate_text in rows:
            y1 = y + row_h
            # Alternating translucent zebra on the rate column (matches reference).
            if row_index % 2 == 1:
                rect = fitz.Rect(_TABLE_MID, y, _TABLE_RIGHT, y1)
                page.draw_rect(rect, color=None, fill=_ZEBRA, fill_opacity=0.18)
            baseline = y + row_h * 0.72
            _insert_left(
                page,
                name,
                x=service_left,
                y_baseline=baseline,
                fontsize=fontsize,
                color=_TEXT,
                fontname=fontname,
            )
            _insert_right(
                page,
                rate_text,
                x_right=rate_right,
                y_baseline=baseline,
                fontsize=fontsize,
                color=_RATE,
                fontname=fontname,
                font=font,
            )
            _draw_hline(page, _TABLE_LEFT, _TABLE_RIGHT, y1, width=2)
            y = y1
            row_index += 1

    if _WATERMARK_PATH.is_file():
        page.insert_image(_WATERMARK_RECT, filename=str(_WATERMARK_PATH), keep_proportion=True, overlay=True)


def build_rate_card_pdf(
    items: list[Any],
    *,
    year: str = RATE_CARD_YEAR,
    currency: str | None = None,
) -> bytes:
    """Export a 3-page rate card: cover + rates + back, matching the studio PDF.

    Pages 1 and 3 are taken as-is from ``RATE_CARD_REFERENCE.pdf``.
    Page 2 is redrawn with current services using the same fonts/colors/layout.
    ``currency`` overrides the card currency shown on rate amounts (EGP/USD/EUR).
    """
    resolved = normalize_currency(currency) if currency else card_currency(items)
    out = fitz.open()
    try:
        if _REFERENCE_PDF.is_file():
            ref = fitz.open(str(_REFERENCE_PDF))
            try:
                if ref.page_count >= 1:
                    out.insert_pdf(ref, from_page=0, to_page=0)
                _build_rates_page(out, items, year=year, currency=resolved)
                if ref.page_count >= 3:
                    out.insert_pdf(ref, from_page=2, to_page=2)
                elif ref.page_count >= 2:
                    out.insert_pdf(ref, from_page=ref.page_count - 1, to_page=ref.page_count - 1)
            finally:
                ref.close()
        else:
            # No reference asset — still emit a rates page so export never blank-fails.
            _build_rates_page(out, items, year=year, currency=resolved)

        return out.tobytes(deflate=True, garbage=3)
    finally:
        out.close()
