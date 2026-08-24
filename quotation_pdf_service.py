"""Studio quotation PDF — grouped Working Hours + Rate Card, modelled on BB_ORANGE_QUOTATION_2026."""

from __future__ import annotations

import html
import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import daily_worksheet_pdf_service as dws
import project_work_ledger_service as pwls
import rate_card_service as rcs
from project_settings import PROJECT_TYPE_LABELS, normalize_project_type_slug, project_type_is_commercial

ASSET_DIR = Path(__file__).resolve().parent / "static" / "quotation"
LOGO_PATH = ASSET_DIR / "logo.png"
WATERMARK_PATH = ASSET_DIR / "watermark.png"
BANK_QR_PATH = ASSET_DIR / "bank-qr.png"

# BB_ORANGE_QUOTATION_2026.pdf — same wordmark, header ~70% / watermark ~5.5%.
SIZE_TITLE = 36
SIZE_ADDR = 9
SIZE_META = 10
SIZE_TABLE_HEAD = 8
SIZE_TABLE = 10
SIZE_TERMS_TITLE = 8
SIZE_TERMS = 8
SIZE_FOOTER = 8
SIZE_SCAN = 7
HEADER_LOGO_X = 57.32
HEADER_LOGO_Y = 723.74
HEADER_LOGO_W = 141.37
HEADER_LOGO_H = 55.98
WATERMARK_X = 89.18
WATERMARK_Y = 410.23
WATERMARK_W = 375.91
WATERMARK_H = 211.45
WATERMARK_OPACITY = 0.0548
HEADER_LOGO_OPACITY = 0.6941

_HELVETICA_NEUE_TTC = Path("/System/Library/Fonts/HelveticaNeue.ttc")
_DIN_CONDENSED = Path("/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf")
_COURIER_NEW = Path("/System/Library/Fonts/Supplemental/Courier New.ttf")
_COURIER_NEW_BOLD = Path("/System/Library/Fonts/Supplemental/Courier New Bold.ttf")
_CONDENSED_FALLBACK = Path(__file__).resolve().parent / "static" / "rate_card" / "HelveticaNeue-CondensedBold.ttf"

_FONTS: dict[str, str] | None = None

STUDIO_NAME = "BIGBANG STUDIOS"
STUDIO_ADDRESS = (
    "5 SAYED ABDEL WAHED STREET,",
    "MOHANDESEIN",
    "GIZA, EGYPT. 12411",
)
INQUIRY_EMAIL = "yasmine@bbgstudio.com"
TERMS = (
    "Any changes to the brief may result in quotation re-evaluation.",
    "Prices do not include taxes.",
    f"For further inquiries kindly contact us on {INQUIRY_EMAIL}",
)


def _register_ttfont(name: str, path: Path, subfont_index: int | None = None) -> bool:
    if not path.is_file():
        return False
    if name in pdfmetrics.getRegisteredFontNames():
        return True
    try:
        if subfont_index is None:
            pdfmetrics.registerFont(TTFont(name, str(path)))
        else:
            pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=subfont_index))
        return True
    except Exception:
        return False


def quotation_fonts() -> dict[str, str]:
    """Helvetica Neue + DIN Condensed + Courier New, matching the Numbers invoice."""
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    fonts = {
        "title": "Helvetica-Bold",
        "light": "Helvetica",
        "regular": "Helvetica",
        "bold": "Helvetica-Bold",
        "mono": "Courier",
        "mono_bold": "Courier-Bold",
    }
    if _register_ttfont("HelveticaNeue", _HELVETICA_NEUE_TTC, 0):
        fonts["regular"] = "HelveticaNeue"
    if _register_ttfont("HelveticaNeue-Bold", _HELVETICA_NEUE_TTC, 1):
        fonts["bold"] = "HelveticaNeue-Bold"
    if _register_ttfont("HelveticaNeue-Light", _HELVETICA_NEUE_TTC, 7):
        fonts["light"] = "HelveticaNeue-Light"
    if _register_ttfont("DINCondensed-Bold", _DIN_CONDENSED):
        fonts["title"] = "DINCondensed-Bold"
    elif _register_ttfont("HelveticaNeue-CondensedBold", _HELVETICA_NEUE_TTC, 4):
        fonts["title"] = "HelveticaNeue-CondensedBold"
    elif _register_ttfont("HelveticaNeue-CondensedBold", _CONDENSED_FALLBACK):
        fonts["title"] = "HelveticaNeue-CondensedBold"
    if _register_ttfont("CourierNew", _COURIER_NEW):
        fonts["mono"] = "CourierNew"
    if _register_ttfont("CourierNew-Bold", _COURIER_NEW_BOLD):
        fonts["mono_bold"] = "CourierNew-Bold"
    _FONTS = fonts
    return fonts


# Export-only buckets. Ledger rows stay unchanged.
COPY_CONVERT_TYPES = frozenset({"copy_media", "convert_transcode", "copy_convert", "copy_convert_sync"})
OFFLINE_TYPES = frozenset({"offline_editing", "offline", "selection"})

BUCKET_ORDER = (
    "copy_convert",
    "sync",
    "offline_editing",
    "online_editing",
    "online",
    "color_grading_senior_colorist",
    "color_grading_colorist",
    "color_grading_dry_rent",
    "color_grading",
    "sound_design_mix",
    "sound_edit",
    "sound_mix",
    "upload_download_1g",
    "conform",
    "vfx_work",
    "assembly",
    "review",
    "meeting",
    "supervision",
    "delivery_prep",
    "admin",
    "other",
    "edit_fee",
)

BUCKET_LABELS = {
    "copy_convert": "Copy & Convert",
    "offline_editing": "Offline Editing",
}

COPY_CONVERT_RATE_KEYS = (
    "copy_convert",
    "copy_convert_sync",
    "copy_media",
    "convert_transcode",
    "Copy & Convert",
    "Copy&Convert",
)
OFFLINE_RATE_KEYS = (
    "offline_editing",
    "offline",
    "edit",
    "selection",
    "Offline Editing",
)


def format_quote_date(value: date | datetime | None) -> str:
    if value is None:
        return ""
    day = value.date() if isinstance(value, datetime) else value
    return day.strftime("%d-%m-%Y")


def quotation_type_label(project_type: str | None) -> str:
    if project_type_is_commercial(project_type):
        return "TVC"
    slug = normalize_project_type_slug(project_type)
    label = PROJECT_TYPE_LABELS.get(slug) or str(project_type or "").strip()
    return label.upper() if label else ""


def _minutes_for_row(row: Any) -> int:
    billable = int(getattr(row, "billable_minutes", 0) or 0)
    actual = int(getattr(row, "actual_minutes", 0) or 0)
    return billable if billable > 0 else max(0, actual)


def _bucket_for_row(row: Any) -> str:
    work_type = pwls.normalize_work_type(getattr(row, "work_type", None))
    source = str(getattr(row, "source_type", "") or "")
    if source in (pwls.SOURCE_MEDIA_COPY, pwls.SOURCE_MEDIA_CONVERT) or work_type in COPY_CONVERT_TYPES:
        return "copy_convert"
    if work_type in OFFLINE_TYPES:
        return "offline_editing"
    return work_type or "other"


def _rate_for_bucket(
    bucket: str,
    sample_row: Any,
    rate_index: dict[str, dict[str, Any]],
) -> tuple[str, str, Decimal]:
    if bucket == "copy_convert":
        match = dws._rate_lookup(rate_index, *COPY_CONVERT_RATE_KEYS)
        if match:
            return "Copy & Convert", match["unit"], match["rate"]
        return "Copy & Convert", dws.UNIT_HOUR, Decimal("0.00")
    if bucket == "offline_editing":
        match = dws._rate_lookup(rate_index, *OFFLINE_RATE_KEYS)
        if match:
            return "Offline Editing", match["unit"], match["rate"]
        return "Offline Editing", dws.UNIT_HOUR, Decimal("0.00")
    label, unit, rate = dws._service_for_row(sample_row, rate_index)
    return BUCKET_LABELS.get(bucket, label), unit, rate


def build_quotation_rows(
    ledger_rows: list[Any],
    *,
    rate_items: list[Any] | None = None,
    currency: str | None = None,
) -> list[dict[str, Any]]:
    """Group approved hours into quotation lines (export-only)."""
    rate_index = dws.build_rate_index(rate_items)
    pwls.set_extra_work_type_labels(rcs.work_type_label_map(rate_items))
    money_code = rcs.normalize_currency(currency or rcs.card_currency(rate_items))

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in ledger_rows or []:
        work_date = getattr(row, "work_date", None)
        if not isinstance(work_date, date):
            continue
        bucket = _bucket_for_row(row)
        sample_label, unit, rate = _rate_for_bucket(bucket, row, rate_index)
        key = (bucket, unit)
        slot = groups.get(key)
        if slot is None:
            slot = {
                "bucket": bucket,
                "description": sample_label,
                "unit": unit,
                "rate": rate,
                "minutes": 0,
                "fee_count": 0,
                "amount": Decimal("0.00"),
            }
            groups[key] = slot
        if unit == dws.UNIT_FEE:
            slot["fee_count"] += 1
            slot["amount"] += rate
        else:
            slot["minutes"] += _minutes_for_row(row)

    order_index = {key: idx for idx, key in enumerate(BUCKET_ORDER)}
    built: list[dict[str, Any]] = []
    for (_bucket, unit), slot in groups.items():
        if unit == dws.UNIT_FEE:
            qty = Decimal(slot["fee_count"] or 1)
            amount = dws._money(slot["amount"])
        else:
            qty = dws._hours_from_minutes(slot["minutes"])
            if qty <= 0:
                continue
            amount = dws._money(qty * slot["rate"])
        built.append(
            {
                "bucket": slot["bucket"],
                "description": slot["description"],
                "qty": qty,
                "unit": unit,
                "unit_price": dws._money(slot["rate"]),
                "cost": amount,
                "currency": money_code,
            }
        )
    built.sort(
        key=lambda item: (
            order_index.get(item["bucket"], 80),
            item["description"].lower(),
            item["unit"],
        )
    )
    return built


def build_quotation_header(
    project: Any,
    *,
    attention: str = "",
    quote_date: date | None = None,
) -> dict[str, str]:
    attention_value = (attention or "").strip() or getattr(project, "producer_name", None) or ""
    return {
        "production": dws.safe_header_value(getattr(project, "production_house", None)),
        "attention": dws.safe_header_value(attention_value),
        "date": format_quote_date(quote_date or date.today()),
        "project": dws.safe_header_value(getattr(project, "name", None)),
        "director": dws.safe_header_value(getattr(project, "director", None)),
        "type": quotation_type_label(getattr(project, "project_type", None)),
        "year": str((quote_date or date.today()).year),
    }


def _fmt_qty(value: Decimal) -> str:
    quantized = dws._money(value)
    if quantized == quantized.to_integral_value():
        return str(int(quantized))
    text = f"{quantized:.2f}".rstrip("0").rstrip(".")
    return text


def _fmt_money(value: Decimal, currency: str) -> str:
    quantized = dws._money(value)
    if quantized == quantized.to_integral_value():
        number = f"{int(quantized):,}"
    else:
        number = f"{quantized:,.2f}"
    return f"{currency} {number}"


def render_quotation_pdf(
    *,
    header: dict[str, str],
    rows: list[dict[str, Any]],
    currency: str = rcs.CURRENCY,
) -> bytes:
    """Render a portrait A4 quotation modelled on BB_ORANGE_QUOTATION_2026."""
    money_code = rcs.normalize_currency(currency)
    fonts = quotation_fonts()
    buffer = io.BytesIO()
    page_w, page_h = A4
    c = canvas.Canvas(buffer, pagesize=A4)
    left = 16 * mm
    right = page_w - 16 * mm
    usable = right - left
    ink = colors.HexColor("#111111")
    muted = colors.HexColor("#222222")

    def draw_watermark() -> None:
        """Same stacked wordmark as BB_ORANGE_QUOTATION_2026.pdf, ~5.5% opacity."""
        path = WATERMARK_PATH if WATERMARK_PATH.is_file() else LOGO_PATH
        if not path.is_file():
            return
        try:
            c.drawImage(
                ImageReader(str(path)),
                WATERMARK_X,
                WATERMARK_Y,
                width=WATERMARK_W,
                height=WATERMARK_H,
                mask="auto",
                preserveAspectRatio=True,
                anchor="c",
            )
        except Exception:
            return

    def draw_chrome() -> None:
        draw_watermark()
        y = page_h - 16 * mm
        if LOGO_PATH.is_file():
            try:
                c.drawImage(
                    ImageReader(str(LOGO_PATH)),
                    HEADER_LOGO_X,
                    HEADER_LOGO_Y,
                    width=HEADER_LOGO_W,
                    height=HEADER_LOGO_H,
                    mask="auto",
                    preserveAspectRatio=True,
                    anchor="sw",
                )
            except Exception:
                c.setFillColor(ink)
                c.setFont(fonts["bold"], 14)
                c.drawString(left, y - 8 * mm, STUDIO_NAME)
        c.setFillColor(ink)
        c.setFont(fonts["title"], SIZE_TITLE)
        c.drawRightString(right, y - 12 * mm, "QUOTATION")
        c.setFillColor(muted)
        c.setFont(fonts["mono"], SIZE_ADDR)
        addr_y = HEADER_LOGO_Y - 6 * mm
        c.drawString(HEADER_LOGO_X, addr_y, STUDIO_NAME)
        for line in STUDIO_ADDRESS:
            addr_y -= 3.6 * mm
            c.drawString(HEADER_LOGO_X, addr_y, line)

        meta_top = addr_y - 9 * mm
        label_w = 28 * mm
        right_col = left + usable * 0.52
        meta = (
            ("Production:", header.get("production", ""), "Project Title:", header.get("project", "")),
            ("Attention:", header.get("attention", ""), "Director:", header.get("director", "")),
            ("Date:", header.get("date", ""), "TYPE:", header.get("type", "")),
        )
        for left_label, left_val, right_label, right_val in meta:
            c.setFillColor(muted)
            c.setFont(fonts["light"], SIZE_META)
            c.drawString(HEADER_LOGO_X, meta_top, left_label)
            c.drawString(right_col, meta_top, right_label)
            c.setFillColor(ink)
            c.setFont(fonts["mono_bold"], SIZE_META)
            c.drawString(HEADER_LOGO_X + label_w, meta_top, left_val)
            c.drawString(right_col + label_w, meta_top, right_val)
            meta_top -= 5.4 * mm
        return meta_top - 6 * mm

    def draw_footer() -> None:
        c.setStrokeColor(colors.HexColor("#bbbbbb"))
        c.setLineWidth(0.4)
        c.line(left, 42 * mm, right, 42 * mm)
        c.setFillColor(ink)
        c.setFont(fonts["regular"], SIZE_TERMS_TITLE)
        c.drawString(left, 36 * mm, "Terms & Conditions:")
        title_w = c.stringWidth("Terms & Conditions:", fonts["regular"], SIZE_TERMS_TITLE)
        c.setLineWidth(0.5)
        c.line(left, 35.2 * mm, left + title_w, 35.2 * mm)
        c.setFont(fonts["mono"], SIZE_TERMS)
        ty = 31.2 * mm
        for line in TERMS:
            c.drawString(left, ty, f"- {line}")
            ty -= 3.5 * mm
        c.setFont(fonts["mono"], SIZE_FOOTER)
        c.drawString(
            left,
            14 * mm,
            f"Prepared By BigBang Finance Department {header.get('year') or date.today().year}",
        )
        qr_size = 28 * mm
        qr_x = right - qr_size
        c.setFont(fonts["bold"], SIZE_SCAN)
        c.drawCentredString(qr_x + qr_size / 2, 40 * mm, "SCAN FOR BANK DETAILS")
        if BANK_QR_PATH.is_file():
            try:
                c.drawImage(
                    ImageReader(str(BANK_QR_PATH)),
                    qr_x,
                    10 * mm,
                    width=qr_size,
                    height=qr_size,
                    mask="auto",
                    preserveAspectRatio=True,
                )
            except Exception:
                pass

    col_desc = usable * 0.46
    col_qty = usable * 0.12
    col_price = usable * 0.21
    col_cost = usable * 0.21
    row_h = 8.2 * mm
    header_h = 8.6 * mm
    table_bottom = 48 * mm

    def draw_table_header(y: float) -> float:
        c.setFillColor(colors.HexColor("#efefef"))
        c.rect(left, y - header_h, usable, header_h, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor("#b0b0b0"))
        c.setLineWidth(0.5)
        c.rect(left, y - header_h, usable, header_h, fill=0, stroke=1)
        c.setFillColor(ink)
        c.setFont(fonts["bold"], SIZE_TABLE_HEAD)
        text_y = y - header_h + 3 * mm
        c.drawString(left + 3 * mm, text_y, "DESCRIPTION")
        c.drawRightString(left + col_desc + col_qty - 2 * mm, text_y, "QTY")
        c.drawRightString(left + col_desc + col_qty + col_price - 2 * mm, text_y, "UNIT PRICE")
        c.drawRightString(right - 2 * mm, text_y, "COST")
        x = left + col_desc
        c.line(x, y, x, y - header_h)
        x += col_qty
        c.line(x, y, x, y - header_h)
        x += col_price
        c.line(x, y, x, y - header_h)
        return y - header_h

    def draw_data_row(y: float, row: dict[str, Any], zebra: bool) -> float:
        if zebra:
            c.setFillColor(colors.HexColor("#f6f6f6"))
            c.rect(left, y - row_h, usable, row_h, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor("#c8c8c8"))
        c.setLineWidth(0.4)
        c.rect(left, y - row_h, usable, row_h, fill=0, stroke=1)
        x = left + col_desc
        c.line(x, y, x, y - row_h)
        x += col_qty
        c.line(x, y, x, y - row_h)
        x += col_price
        c.line(x, y, x, y - row_h)
        c.setFillColor(ink)
        c.setFont(fonts["mono"], SIZE_TABLE)
        text_y = y - row_h + 2.8 * mm
        c.drawString(left + 3 * mm, text_y, str(row.get("description") or "").upper())
        c.drawRightString(left + col_desc + col_qty - 2 * mm, text_y, _fmt_qty(row.get("qty") or 0))
        c.drawRightString(
            left + col_desc + col_qty + col_price - 2 * mm,
            text_y,
            _fmt_money(row.get("unit_price") or 0, money_code),
        )
        c.setFont(fonts["mono_bold"], SIZE_TABLE)
        c.drawRightString(right - 2 * mm, text_y, _fmt_money(row.get("cost") or 0, money_code))
        return y - row_h

    def draw_total_row(y: float, label: str, value: Decimal) -> float:
        c.setStrokeColor(colors.HexColor("#c8c8c8"))
        c.setLineWidth(0.4)
        c.rect(left, y - row_h, usable, row_h, fill=0, stroke=1)
        x = left + col_desc + col_qty + col_price
        c.line(x, y, x, y - row_h)
        c.setFillColor(ink)
        c.setFont(fonts["light"], SIZE_TABLE)
        text_y = y - row_h + 2.8 * mm
        c.drawRightString(x - 3 * mm, text_y, label)
        c.setFont(fonts["mono_bold"], SIZE_TABLE)
        c.drawRightString(right - 2 * mm, text_y, _fmt_money(value, money_code))
        return y - row_h

    items = list(rows or [])
    total = sum((dws._money(r.get("cost")) for r in items), Decimal("0.00"))
    idx = 0
    while True:
        table_y = draw_chrome()
        table_y = draw_table_header(table_y)
        zebra = False
        while idx < len(items):
            extra = 2 * row_h if idx == len(items) - 1 else 0
            if table_y - row_h - extra < table_bottom:
                break
            table_y = draw_data_row(table_y, items[idx], zebra)
            zebra = not zebra
            idx += 1
        if idx >= len(items):
            if table_y - 2 * row_h < table_bottom:
                draw_footer()
                c.showPage()
                table_y = draw_chrome()
                table_y = draw_table_header(table_y)
            table_y = draw_total_row(table_y, "SUBTOTAL", total)
            draw_total_row(table_y, "TOTAL", total)
            draw_footer()
            c.showPage()
            break
        draw_footer()
        c.showPage()

    c.save()
    return buffer.getvalue()


def render_quotation_preview_html(pdf_bytes: bytes) -> str:
    html_doc = dws.render_daily_worksheet_preview_html(pdf_bytes)
    return (
        html_doc.replace("Daily Worksheet Preview", "Quotation Preview")
        .replace('alt="Daily Worksheet page"', 'alt="Quotation page"')
    )


def render_quotation_preview_error_html(message: str) -> str:
    text = html.escape(dws.safe_header_value(message) or "Could not build quotation.")
    return dws.render_daily_worksheet_preview_error_html(text).replace(
        "Daily Worksheet Preview", "Quotation Preview"
    )
