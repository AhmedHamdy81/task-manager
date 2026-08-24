"""Daily Worksheet PDF — billing sheet built from ProjectWorkLedger + Rate Card.

Grouping (Copy&Convert) and Fee handling are export-only; ledger rows are unchanged.
"""

from __future__ import annotations

import html
import io
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import project_work_ledger_service as pwls
import rate_card_service as rcs

UNIT_HOUR = "Hour"
UNIT_FEE = "Fee"
DEFAULT_TAX_NOTE = "PRICES DO NOT INCLUDE 14% TAX."
TAX_RATE = Decimal("0.14")


def safe_header_value(value: Any) -> str:
    text = str(value or "").strip()
    return text


def format_worksheet_date(value: date | datetime | None) -> str:
    if value is None:
        return ""
    day = value.date() if isinstance(value, datetime) else value
    return f"{day.strftime('%A')}, {day.strftime('%B')} {day.day}, {day.year}"


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "project").strip()).strip("._")
    return cleaned or "project"


def _money(value: Decimal | float | int | None) -> Decimal:
    try:
        amount = Decimal(str(value if value is not None else 0))
    except Exception:
        amount = Decimal("0")
    if amount < 0:
        amount = Decimal("0")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _hours_from_minutes(minutes: Any) -> Decimal:
    total = max(0, int(minutes or 0))
    return (Decimal(total) / Decimal(60)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _qty_for_row(row: Any, unit: str) -> Decimal:
    if unit == UNIT_FEE:
        return Decimal("1.00")
    billable = int(getattr(row, "billable_minutes", 0) or 0)
    actual = int(getattr(row, "actual_minutes", 0) or 0)
    if billable > 0:
        return _hours_from_minutes(billable)
    return _hours_from_minutes(actual)


def _artist_label(row: Any) -> str:
    source = str(getattr(row, "source_type", "") or "")
    user = getattr(row, "user", None)
    name = ""
    if user is not None:
        name = str(getattr(user, "name", "") or "").strip()
    if name:
        return name
    if source in (pwls.SOURCE_MEDIA_COPY, pwls.SOURCE_MEDIA_CONVERT):
        return "Machine"
    if str(getattr(row, "department_key", "") or "") == pwls.DEPT_MACHINE_ROOM:
        return "Machine"
    return "—"


def _rate_lookup(rate_index: dict[str, dict[str, Any]], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        slug = pwls.slugify_key(key, fallback="", max_len=64)
        if slug and slug in rate_index:
            return rate_index[slug]
    return None


def build_rate_index(rate_items: list[Any] | None) -> dict[str, dict[str, Any]]:
    """Map service_key / service_name slug → rate card payload for worksheet."""
    index: dict[str, dict[str, Any]] = {}
    for item in rate_items or []:
        if isinstance(item, dict):
            name = str(item.get("service_name") or "").strip()
            key = str(item.get("service_key") or "").strip() or pwls.slugify_key(name, fallback="", max_len=64)
            unit = rcs.normalize_billing_unit(item.get("billing_unit"))
            rate_hour = item.get("rate_hour")
            rate_day = item.get("rate_day")
            active = bool(item.get("include_in_pdf", True))
        else:
            name = str(getattr(item, "service_name", "") or "").strip()
            key = str(getattr(item, "service_key", "") or "").strip() or pwls.slugify_key(
                name, fallback="", max_len=64
            )
            unit = rcs.normalize_billing_unit(getattr(item, "billing_unit", None))
            rate_hour = getattr(item, "rate_hour", None)
            rate_day = getattr(item, "rate_day", None)
            active = bool(getattr(item, "include_in_pdf", True))
        if not key or not active:
            continue
        rate_value = rate_hour if rate_hour is not None else rate_day
        payload = {
            "key": key,
            "label": name or key,
            "unit": unit,
            "rate": _money(rate_value),
        }
        index[key] = payload
        name_slug = pwls.slugify_key(name, fallback="", max_len=64)
        if name_slug and name_slug not in index:
            index[name_slug] = payload
    return index


def _service_for_row(row: Any, rate_index: dict[str, dict[str, Any]]) -> tuple[str, str, Decimal]:
    """Return (service_label, unit, rate)."""
    work_type = pwls.normalize_work_type(getattr(row, "work_type", None))
    source = str(getattr(row, "source_type", "") or "")

    aliases = [work_type]
    if work_type in ("offline_editing", "online_editing", "offline", "online"):
        aliases.extend(["edit", "offline", "online"])
    if work_type == "copy_media":
        aliases.extend(["copy_convert", "copy_convert_sync", "copy_media"])
    if work_type == "convert_transcode":
        aliases.extend(["copy_convert", "copy_convert_sync", "convert_transcode"])
    if source in (pwls.SOURCE_MEDIA_COPY, pwls.SOURCE_MEDIA_CONVERT):
        aliases.extend(["copy_convert", "copy_convert_sync"])

    match = _rate_lookup(rate_index, *aliases)
    if match:
        return match["label"], match["unit"], match["rate"]

    label = pwls.work_type_label(work_type)
    return label, UNIT_HOUR, Decimal("0.00")


def build_daily_worksheet_rows(
    ledger_rows: list[Any],
    *,
    rate_items: list[Any] | None = None,
    combine_copy_convert: bool = True,
) -> list[dict[str, Any]]:
    """Map ledger rows into worksheet table rows (export-only grouping)."""
    rate_index = build_rate_index(rate_items)
    pwls.set_extra_work_type_labels(rcs.work_type_label_map(rate_items))

    pending_media: dict[date, list[Any]] = {}
    plain_rows: list[tuple[date, Any]] = []

    for row in ledger_rows or []:
        status = str(getattr(row, "status", "") or "")
        work_date = getattr(row, "work_date", None)
        if not isinstance(work_date, date):
            continue
        source = str(getattr(row, "source_type", "") or "")
        if combine_copy_convert and source in (pwls.SOURCE_MEDIA_COPY, pwls.SOURCE_MEDIA_CONVERT):
            pending_media.setdefault(work_date, []).append(row)
            continue
        plain_rows.append((work_date, row))

    built: list[dict[str, Any]] = []

    for work_date, group in sorted(pending_media.items(), key=lambda item: item[0]):
        minutes = 0
        for row in group:
            billable = int(getattr(row, "billable_minutes", 0) or 0)
            actual = int(getattr(row, "actual_minutes", 0) or 0)
            minutes += billable if billable > 0 else actual
        match = _rate_lookup(
            rate_index,
            "copy_convert",
            "copy_convert_sync",
            "copy_media",
            "Copy&Convert",
            "Copy & Convert & Sync",
        )
        unit = match["unit"] if match else UNIT_HOUR
        rate = match["rate"] if match else Decimal("0.00")
        label = match["label"] if match else "Copy&Convert"
        qty = Decimal("1.00") if unit == UNIT_FEE else _hours_from_minutes(minutes)
        amount = rate if unit == UNIT_FEE else _money(qty * rate)
        built.append(
            {
                "work_date": work_date,
                "date_label": format_worksheet_date(work_date),
                "artist": "Machine",
                "service": label if label != "Copy & Convert & Sync" else "Copy&Convert",
                "unit": unit,
                "qty": qty,
                "rate": rate,
                "amount": amount,
                "source": "media_combined",
            }
        )

    for work_date, row in plain_rows:
        service, unit, rate = _service_for_row(row, rate_index)
        qty = _qty_for_row(row, unit)
        amount = rate if unit == UNIT_FEE else _money(qty * rate)
        built.append(
            {
                "work_date": work_date,
                "date_label": format_worksheet_date(work_date),
                "artist": _artist_label(row),
                "service": service,
                "unit": unit,
                "qty": qty,
                "rate": rate,
                "amount": amount,
                "source": str(getattr(row, "source_type", "") or ""),
                "ledger_id": getattr(row, "id", None),
            }
        )

    built.sort(key=lambda item: (item["work_date"], item.get("artist") or "", item.get("service") or ""))

    # Show date label only on the first row of each date group.
    last_date: date | None = None
    for item in built:
        if item["work_date"] == last_date:
            item["date_display"] = ""
        else:
            item["date_display"] = item["date_label"]
            last_date = item["work_date"]
    return built


def build_worksheet_header(
    project: Any,
    *,
    prepared_by: str = "",
    contact: str = "",
    worksheet_date: date | None = None,
) -> dict[str, str]:
    client = safe_header_value(
        getattr(project, "production_house", None) or getattr(project, "client_name", None)
    )
    return {
        "client": client,
        "contact": safe_header_value(contact),
        "prepared_by": safe_header_value(prepared_by),
        "project": safe_header_value(getattr(project, "name", None)),
        "date": format_worksheet_date(worksheet_date or date.today()),
        "director": safe_header_value(getattr(project, "director", None)),
    }


def _fmt_qty(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _fmt_money(value: Decimal) -> str:
    quantized = _money(value)
    if quantized == quantized.to_integral_value():
        return f"{int(quantized):,}"
    return f"{quantized:,.2f}"


def render_daily_worksheet_pdf(
    *,
    header: dict[str, str],
    rows: list[dict[str, Any]],
    tax_note: str = DEFAULT_TAX_NOTE,
    include_tax: bool = False,
) -> bytes:
    """Render a landscape Daily Worksheet PDF in memory."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    cell = ParagraphStyle(
        "ws_cell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#111111"),
    )
    cell_left = ParagraphStyle("ws_cell_left", parent=cell, alignment=TA_LEFT)
    cell_right = ParagraphStyle("ws_cell_right", parent=cell, alignment=TA_RIGHT)
    label = ParagraphStyle(
        "ws_label",
        parent=cell_left,
        fontName="Helvetica-Bold",
        fontSize=9,
    )
    note_style = ParagraphStyle(
        "ws_note",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#222222"),
    )

    def P(text: str, style: ParagraphStyle = cell) -> Paragraph:
        return Paragraph(html.escape(str(text or ""), quote=False), style)

    header_data = [
        [P("Client", label), P(header.get("client", ""), cell_left), P("Contact", label), P(header.get("contact", ""), cell_left)],
        [P("Prepared By", label), P(header.get("prepared_by", ""), cell_left), P("Project", label), P(header.get("project", ""), cell_left)],
        [P("Date", label), P(header.get("date", ""), cell_left), P("Director", label), P(header.get("director", ""), cell_left)],
    ]
    header_table = Table(header_data, colWidths=[32 * mm, 95 * mm, 32 * mm, 95 * mm])
    header_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#333333")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f3f3")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f3f3f3")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    body: list[list[Any]] = [
        [
            P("Date", label),
            P("Artist", label),
            P("Service", label),
            P("Unit", label),
            P("QTY", label),
            P("Rate", label),
            P("Amount", label),
        ]
    ]
    total = Decimal("0.00")
    for row in rows:
        amount = _money(row.get("amount"))
        total += amount
        body.append(
            [
                P(str(row.get("date_display") or ""), cell_left),
                P(str(row.get("artist") or ""), cell_left),
                P(str(row.get("service") or ""), cell_left),
                P(str(row.get("unit") or UNIT_HOUR), cell),
                P(_fmt_qty(_money(row.get("qty"))), cell),
                P(_fmt_money(_money(row.get("rate"))), cell_right),
                P(_fmt_money(amount), cell_right),
            ]
        )

    if include_tax:
        tax = _money(total * TAX_RATE)
        grand = _money(total + tax)
        body.append(["", "", "", "", "", P("Subtotal", label), P(_fmt_money(total), cell_right)])
        body.append(["", "", "", "", "", P("Tax 14%", label), P(_fmt_money(tax), cell_right)])
        body.append(["", "", "", "", "", P("Total", label), P(_fmt_money(grand), cell_right)])
        footer_total = grand
    else:
        body.append(["", "", "", "", "", P("Total", label), P(_fmt_money(total), cell_right)])
        footer_total = total

    body_table = Table(
        body,
        colWidths=[55 * mm, 40 * mm, 55 * mm, 20 * mm, 20 * mm, 28 * mm, 32 * mm],
        repeatRows=1,
    )
    style_cmds = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#444444")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efefef")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (5, -1), (-1, -1), colors.HexColor("#f7f7f7")),
    ]
    if include_tax:
        style_cmds.append(("BACKGROUND", (5, -3), (-1, -1), colors.HexColor("#f7f7f7")))
    body_table.setStyle(TableStyle(style_cmds))

    note = Table(
        [[P(safe_header_value(tax_note) or DEFAULT_TAX_NOTE, note_style)]],
        colWidths=[250 * mm],
    )
    note.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#d0d0d0")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#888888")),
            ]
        )
    )

    story = [header_table, Spacer(1, 8 * mm), body_table, Spacer(1, 6 * mm), note]
    doc.build(story)
    return buffer.getvalue()


def render_daily_worksheet_preview_html(pdf_bytes: bytes) -> str:
    """Rasterize PDF pages to HTML images so browsers without a PDF viewer can preview."""
    import base64

    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        images: list[str] = []
        zoom = fitz.Matrix(1.6, 1.6)
        for page in doc:
            pix = page.get_pixmap(matrix=zoom, alpha=False)
            encoded = base64.b64encode(pix.tobytes("png")).decode("ascii")
            images.append(
                '<img class="page" src="data:image/png;base64,'
                + encoded
                + '" alt="Daily Worksheet page" />'
            )
    finally:
        doc.close()

    body = "\n".join(images) if images else '<p class="empty">No pages to preview.</p>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Daily Worksheet Preview</title>
  <style>
    html, body {{ margin: 0; padding: 0; background: #ececec; }}
    body {{ padding: 16px; box-sizing: border-box; }}
    .page {{
      display: block;
      width: 100%;
      max-width: 1100px;
      height: auto;
      margin: 0 auto 16px;
      background: #fff;
      box-shadow: 0 1px 4px rgba(0,0,0,0.18);
    }}
    .empty {{
      margin: 2rem auto;
      text-align: center;
      color: #444;
      font: 14px/1.4 Helvetica, Arial, sans-serif;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def render_daily_worksheet_preview_error_html(message: str) -> str:
    text = html.escape(safe_header_value(message) or "Could not build worksheet.")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Daily Worksheet Preview</title>
  <style>
    html, body {{ margin: 0; background: #1a1a1a; color: #f0a8a8; }}
    body {{
      font: 14px/1.5 Helvetica, Arial, sans-serif;
      padding: 1.5rem;
    }}
  </style>
</head>
<body><p>{text}</p></body>
</html>
"""
