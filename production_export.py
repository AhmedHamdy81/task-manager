"""Export shooting days and their rows as a worksheet (.xlsx or .csv).

Headers are the Import & Compare field labels, so an exported file maps back
automatically and its "BigBang record ID" column updates the same rows on re-import.
Read-only: nothing here writes to the database.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

import episode_detail as ed
import production_import_matching as pim
import production_import_normalize as pin
import shooting_items as si

FORMATS = ("xlsx", "csv")
SHEET_TITLE = "Shooting days"
_BOOL_FIELDS = ("sync_done", "first_edit_done", "needs_vfx", "is_critical")
_COLUMN_WIDTHS = {
    "record_id": 18, "unit_number": 7, "day_name": 14, "shooting_date": 13, "location": 26,
    "episode": 10, "scene_label": 14, "item_type": 18, "reel_number": 7, "duration": 10,
    "sync_done": 8, "first_edit_done": 10, "needs_vfx": 11, "is_critical": 9, "notes": 48,
}
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def export_fields(*, is_tv: bool) -> list[pin.FieldDef]:
    """Every importable field, record ID first; Episode only for TV series."""
    fields = [f for f in pin.FIELDS if is_tv or not f.tv_only]
    return sorted(fields, key=lambda f: f.key != "record_id")


def _episode_cell(row: dict) -> Any:
    if row.get("is_establishing_shots_pool") or si.is_establishing_shot_type(row.get("shooting_item_type")):
        return "Establishing"
    if row.get("is_episode_unassigned"):
        return "X"
    n = int(row.get("episode_number") or 0)
    return n if n > 0 else ""


class _SortProxy:
    def __init__(self, row: dict):
        self.id = row["id"]
        self.scene_label = row.get("scene_label")
        self.scene_number = 0
        self.episode_number = row.get("episode_number")
        self.is_episode_unassigned = row.get("is_episode_unassigned")
        self.is_establishing_shots_pool = row.get("is_establishing_shots_pool")


def export_rows(days: list[dict], rows: list[dict], *, is_tv: bool, day_id: int | None = None) -> list[dict[str, Any]]:
    """One dict per shooting row (field key → cell value), days in unit/date order."""
    by_day: dict[int, list[dict]] = {}
    for r in rows:
        by_day.setdefault(int(r["day_id"]), []).append(r)
    ordered = sorted(days, key=lambda d: (int(d["unit_number"] or 1), d["shooting_date"] or date.min, int(d["id"])))
    out: list[dict[str, Any]] = []
    for d in ordered:
        if day_id is not None and int(d["id"]) != int(day_id):
            continue
        day_rows = sorted(by_day.get(int(d["id"]), []), key=lambda r: ed.shooting_day_pipeline_sort_key(_SortProxy(r)))
        for r in day_rows:
            item = {
                "record_id": r["id"],
                "unit_number": int(d["unit_number"] or 1),
                "day_name": d["day_name"] or "",
                "shooting_date": d["shooting_date"],
                "location": d["location"] or "",
                "scene_label": r.get("scene_label") or "",
                "item_type": si.normalize_shooting_item_type(r.get("shooting_item_type")),
                "reel_number": r.get("reel_number") or "",
                "duration": pim.format_duration(r.get("duration_seconds") or 0) if r.get("duration_seconds") else "",
                "notes": r.get("notes") or "",
            }
            for key in _BOOL_FIELDS:
                item[key] = "Yes" if r.get(key) else "No"
            if is_tv:
                item["episode"] = _episode_cell(r)
            out.append(item)
    return out


def _text(value: Any) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(_FORMULA_PREFIXES) else s


def to_csv(items: list[dict], fields: list[pin.FieldDef]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f.label for f in fields])
    for item in items:
        cells = []
        for f in fields:
            v = item.get(f.key, "")
            cells.append(v.isoformat() if isinstance(v, date) else (v if isinstance(v, int) else _text(v)))
        w.writerow(cells)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def to_xlsx(items: list[dict], fields: list[pin.FieldDef], *, title: str = SHEET_TITLE) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append([f.label for f in fields])
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="2B3442")
    for cell in ws[1]:
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center")
    for item in items:
        ws.append([item.get(f.key, "") for f in fields])
        for cell in ws[ws.max_row]:
            if isinstance(cell.value, str):
                # Stored as text, so "=…" in a note is never evaluated as a formula.
                cell.data_type = "s"
    last = ws.max_row
    for idx, f in enumerate(fields, start=1):
        letter = get_column_letter(idx)
        ws.column_dimensions[letter].width = _COLUMN_WIDTHS.get(f.key, 12)
        for (cell,) in ws.iter_rows(min_row=2, max_row=last, min_col=idx, max_col=idx):
            if f.key == "shooting_date":
                cell.number_format = "yyyy-mm-dd"
            elif f.kind in ("scene", "duration", "day", "text"):
                # Text format stops Excel turning scene "3-1" into a date or "3:00" into a time when edited.
                cell.number_format = "@"
        if f.key in _BOOL_FIELDS and last > 1:
            dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
            dv.add(f"{letter}2:{letter}{last}")
            ws.add_data_validation(dv)
        if f.key == "item_type" and last > 1:
            dv = DataValidation(type="list", formula1='"' + ",".join(si.SHOOTING_ITEM_TYPES) + '"', allow_blank=True)
            dv.add(f"{letter}2:{letter}{last}")
            ws.add_data_validation(dv)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(fields))}{max(last, 1)}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def download_name(project_name: str, *, day: dict | None, fmt: str) -> str:
    base = " ".join(str(project_name or "Project").split())
    for ch in '\\/:*?"<>|':
        base = base.replace(ch, "-")
    if day:
        base += f" - Unit {int(day['unit_number'] or 1)} {day['day_name'] or 'Day'}"
    return f"{base[:120]} - shooting days.{fmt}"
