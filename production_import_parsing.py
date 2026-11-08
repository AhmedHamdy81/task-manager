"""Safe reading of production spreadsheets (.xlsx / .csv / Google Sheets snapshots).

File contents are untrusted: nothing is executed. XLSX is read with openpyxl in
read-only mode (no macros, no external links); formulas contribute only their cached
values, and formulas without a cached value are flagged for review instead of being
treated as empty. CSV is decoded with an explicit encoding and delimiter, and the
caller is told when either detection is ambiguous so the user can confirm it.
Google Sheets data arrives as an immutable snapshot of already-typed cells
(see google_sheets_client) and is decoded into the same Workbook structure.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

XLSX = "xlsx"
CSV = "csv"
GSHEET = "gsheet"
SUPPORTED_EXTENSIONS = {".xlsx": XLSX, ".csv": CSV}

DEFAULT_LIMITS: dict[str, int | float] = {
    "max_bytes": 10 * 1024 * 1024,
    "max_uncompressed_bytes": 150 * 1024 * 1024,
    "max_compression_ratio": 200,
    "max_sheets": 30,
    "max_rows_per_sheet": 5000,
    "max_total_rows": 20000,
    "max_columns": 60,
    "max_cells": 300_000,
    "max_seconds": 25.0,
}

CSV_ENCODINGS: tuple[tuple[str, str], ...] = (
    ("utf-8-sig", "UTF-8"),
    ("utf-16", "UTF-16"),
    ("cp1256", "Windows Arabic (cp1256)"),
    ("latin-1", "Western (Latin-1)"),
)
CSV_DELIMITERS: tuple[tuple[str, str], ...] = (
    (",", "Comma ,"),
    (";", "Semicolon ;"),
    ("\t", "Tab"),
    ("|", "Pipe |"),
)


class ImportFileError(ValueError):
    """The upload is not a readable, safe spreadsheet within the configured limits."""


@dataclass
class Cell:
    value: Any
    kind: str  # empty | text | number | bool | date | datetime | time | duration | formula_missing | error
    shown: str = ""  # the source's own formatted text (Google Sheets), e.g. "001" for the number 1
    fmt: str = ""  # source number format, e.g. "[h]:mm:ss" (Excel) or "TIME" (Google Sheets)

    @property
    def display(self) -> str:
        v = self.value
        if self.kind == "empty":
            return ""
        if self.kind == "formula_missing":
            return "(formula — no cached value)"
        if self.kind == "error":
            return str(v or "#ERROR")
        if self.shown and self.kind == "number":
            return self.shown
        if isinstance(v, datetime):
            return v.isoformat(sep=" ", timespec="minutes") if (v.hour or v.minute) else v.date().isoformat()
        if isinstance(v, (date, dtime)):
            return v.isoformat()
        if isinstance(v, timedelta):
            total = int(v.total_seconds())
            return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "display": self.display}


@dataclass
class Sheet:
    name: str
    rows: list[list[Cell]]
    truncated: bool = False
    formula_missing: int = 0
    errors: int = 0
    merges: list[tuple[int, int, int, int]] = field(default_factory=list)  # 1-based (min_row, min_col, max_row, max_col)

    @property
    def width(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def merge_anchors(self) -> dict[tuple[int, int], tuple[int, int]]:
        """Vertical single-column merges: (row, col) of a covered cell → (row, col) of its anchor."""
        out: dict[tuple[int, int], tuple[int, int]] = {}
        for r1, c1, r2, c2 in self.merges:
            if c1 != c2 or r2 <= r1:
                continue
            for r in range(r1 + 1, r2 + 1):
                out[(r, c1)] = (r1, c1)
        return out


@dataclass
class Workbook:
    kind: str
    sheets: list[Sheet]
    warnings: list[str] = field(default_factory=list)
    csv_encoding: str = ""
    csv_delimiter: str = ""
    csv_encoding_ambiguous: bool = False
    csv_delimiter_ambiguous: bool = False

    def sheet(self, name: str) -> Sheet | None:
        return next((s for s in self.sheets if s.name == name), None)


def file_kind(filename: str) -> str:
    name = (filename or "").strip().lower()
    for ext, kind in SUPPORTED_EXTENSIONS.items():
        if name.endswith(ext):
            return kind
    raise ImportFileError("Only .xlsx and .csv files can be imported.")


def _limits(overrides: dict | None) -> dict[str, Any]:
    out = dict(DEFAULT_LIMITS)
    out.update({k: v for k, v in (overrides or {}).items() if k in DEFAULT_LIMITS and v})
    return out


def read_workbook(
    data: bytes,
    kind: str,
    *,
    limits: dict | None = None,
    csv_encoding: str | None = None,
    csv_delimiter: str | None = None,
) -> Workbook:
    lim = _limits(limits)
    if not data:
        raise ImportFileError("The file is empty.")
    if len(data) > int(lim["max_bytes"]):
        raise ImportFileError(f"The file is larger than {int(lim['max_bytes']) // (1024 * 1024)} MB.")
    if kind == XLSX:
        return _read_xlsx(data, lim)
    if kind == CSV:
        return _read_csv(data, lim, encoding=csv_encoding, delimiter=csv_delimiter)
    if kind == GSHEET:
        return decode_snapshot(data)[1]
    raise ImportFileError("Unsupported file type.")


# --- XLSX -----------------------------------------------------------------------


def _check_xlsx_container(data: bytes, lim: dict) -> None:
    """Reject non-workbooks and zip bombs before handing the bytes to openpyxl."""
    if not data.startswith(b"PK\x03\x04"):
        raise ImportFileError("This is not a valid .xlsx workbook (wrong file contents).")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportFileError("The workbook is damaged and cannot be read.") from exc
    with zf:
        names = set(zf.namelist())
        if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
            raise ImportFileError("This is not a valid .xlsx workbook.")
        total = 0
        for info in zf.infolist():
            total += info.file_size
            if info.compress_size and info.file_size / info.compress_size > float(lim["max_compression_ratio"]) and info.file_size > 5 * 1024 * 1024:
                raise ImportFileError("The workbook is unusually compressed and was rejected for safety.")
        if total > int(lim["max_uncompressed_bytes"]):
            raise ImportFileError("The workbook is too large to process.")


_ELAPSED_FMT = ("[h]", "[hh]", "[m]", "[mm]", "[s]", "[ss]")


def is_elapsed_format(fmt: str) -> bool:
    """Excel elapsed-time formats ([h]:mm:ss…) never wrap at 24 hours."""
    low = (fmt or "").lower()
    return any(tok in low for tok in _ELAPSED_FMT)


def _xlsx_cell(value: Any, formula: Any, fmt: str = "") -> Cell:
    is_formula = isinstance(formula, str) and formula.startswith("=") or (
        formula is not None and type(formula).__name__ in ("ArrayFormula", "DataTableFormula")
    )
    fmt = "" if not fmt or fmt == "General" else str(fmt)
    if value is None or (isinstance(value, str) and not value.strip()):
        return Cell(None, "formula_missing" if is_formula else "empty")
    if isinstance(value, bool):
        return Cell(value, "bool", fmt=fmt)
    if isinstance(value, datetime):
        return Cell(value, "datetime", fmt=fmt)
    if isinstance(value, date):
        return Cell(value, "date", fmt=fmt)
    if isinstance(value, dtime):
        if is_elapsed_format(fmt):
            return Cell(timedelta(hours=value.hour, minutes=value.minute, seconds=value.second,
                                  microseconds=value.microsecond), "duration", fmt=fmt)
        return Cell(value, "time", fmt=fmt)
    if isinstance(value, timedelta):
        return Cell(value, "duration", fmt=fmt)
    if isinstance(value, (int, float)):
        return Cell(value, "number", fmt=fmt)
    text = str(value)
    if text.startswith("#") and text.upper() in ("#N/A", "#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!"):
        return Cell(text, "formula_missing" if is_formula else "text", fmt=fmt)
    return Cell(text, "text", fmt=fmt)


def _xlsx_merges(data: bytes) -> dict[str, list[tuple[int, int, int, int]]]:
    """Merged ranges per worksheet name, read from the sheet XML (read-only mode cannot expose them)."""
    from defusedxml import ElementTree as DET
    from openpyxl.utils.cell import range_boundaries

    ns_main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    ns_rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    out: dict[str, list[tuple[int, int, int, int]]] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            book = DET.fromstring(zf.read("xl/workbook.xml"))
            rels = DET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            targets = {r.get("Id"): r.get("Target") for r in rels}
            for sh in book.iter(f"{ns_main}sheet"):
                target = targets.get(sh.get(f"{ns_rel}id")) or ""
                path = target.lstrip("/") if target.startswith("/") else "xl/" + target
                if path not in zf.namelist():
                    continue
                ranges = []
                with zf.open(path) as fh:
                    for _ev, el in DET.iterparse(fh):
                        if el.tag == f"{ns_main}mergeCell" and el.get("ref"):
                            try:
                                c1, r1, c2, r2 = range_boundaries(el.get("ref"))
                                ranges.append((r1, c1, r2, c2))
                            except (TypeError, ValueError):
                                pass
                        el.clear()
                out[sh.get("name") or ""] = ranges
    except Exception:  # noqa: BLE001 - merges are optional evidence; reading cells still works
        return {}
    return out


def _read_xlsx(data: bytes, lim: dict) -> Workbook:
    _check_xlsx_container(data, lim)
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - dependency declared in requirements
        raise ImportFileError("XLSX support is not installed on the server.") from exc
    started = time.monotonic()
    try:
        values_wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
        formula_wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except Exception as exc:  # noqa: BLE001 - malformed workbook content
        raise ImportFileError("The workbook could not be read. Save it again as .xlsx and retry.") from exc
    warnings: list[str] = []
    sheets: list[Sheet] = []
    total_rows = 0
    total_cells = 0
    merges = _xlsx_merges(data)
    try:
        names = [ws.title for ws in values_wb.worksheets]
        if len(names) > int(lim["max_sheets"]):
            raise ImportFileError(f"The workbook has more than {int(lim['max_sheets'])} worksheets.")
        for name in names:
            ws_v, ws_f = values_wb[name], formula_wb[name]
            max_cols = int(lim["max_columns"])
            rows: list[list[Cell]] = []
            truncated = False
            missing = 0
            for vcells, forms in zip(
                ws_v.iter_rows(max_col=max_cols),
                ws_f.iter_rows(max_col=max_cols, values_only=True),
            ):
                if time.monotonic() - started > float(lim["max_seconds"]):
                    raise ImportFileError("The workbook took too long to read and was stopped.")
                if len(rows) >= int(lim["max_rows_per_sheet"]):
                    truncated = True
                    break
                cells = [_xlsx_cell(getattr(vc, "value", None), f, getattr(vc, "number_format", "") or "")
                         for vc, f in zip(vcells, forms)]
                missing += sum(1 for c in cells if c.kind == "formula_missing")
                rows.append(cells)
            rows = _trim(rows)
            total_rows += len(rows)
            total_cells += sum(len(r) for r in rows)
            if total_rows > int(lim["max_total_rows"]):
                raise ImportFileError(f"The workbook has more than {int(lim['max_total_rows'])} rows in total.")
            if total_cells > int(lim["max_cells"]):
                raise ImportFileError(f"The workbook has more than {int(lim['max_cells']):,} cells in total.")
            if (ws_v.max_column or 0) > max_cols:
                warnings.append(f"“{name}”: only the first {max_cols} columns are read.")
            if truncated:
                warnings.append(f"“{name}”: only the first {int(lim['max_rows_per_sheet'])} rows are read.")
            if missing:
                warnings.append(
                    f"“{name}”: {missing} formula cell(s) have no saved result. Open the file in Excel, "
                    "save it, and re-upload, or review those cells."
                )
            sheets.append(Sheet(name=name, rows=rows, truncated=truncated, formula_missing=missing,
                                merges=merges.get(name, [])))
    finally:
        values_wb.close()
        formula_wb.close()
    if not sheets:
        raise ImportFileError("The workbook has no worksheets.")
    return Workbook(kind=XLSX, sheets=sheets, warnings=warnings)


def _trim(rows: list[list[Cell]]) -> list[list[Cell]]:
    while rows and all(c.kind == "empty" for c in rows[-1]):
        rows.pop()
    width = 0
    for r in rows:
        for i in range(len(r) - 1, -1, -1):
            if r[i].kind != "empty":
                width = max(width, i + 1)
                break
    return [r[:width] + [Cell(None, "empty")] * max(0, width - len(r)) for r in rows]


# --- CSV ------------------------------------------------------------------------


def detect_csv_encoding(data: bytes) -> tuple[str, bool]:
    """(encoding, ambiguous). UTF-8 with or without BOM and UTF-16 BOMs are certain."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", False
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16", False
    try:
        data.decode("utf-8")
        return "utf-8-sig", False
    except UnicodeDecodeError:
        pass
    # Legacy 8-bit text: cp1256 and latin-1 both decode anything, so the user must confirm.
    return "cp1256", True


def detect_csv_delimiter(text: str) -> tuple[str, bool]:
    """(delimiter, ambiguous) from the column counts each candidate produces."""
    lines = [ln for ln in text.splitlines()[:50] if ln.strip()]
    if not lines:
        return ",", False
    scores: list[tuple[int, str]] = []
    for delim, _label in CSV_DELIMITERS:
        counts = [len(r) for r in csv.reader(lines, delimiter=delim)]
        widest = max(counts)
        if widest < 2:
            continue
        consistent = sum(1 for c in counts if c == widest)
        scores.append((consistent, delim))
    if not scores:
        return ",", False
    scores.sort(reverse=True)
    best = scores[0]
    ambiguous = len(scores) > 1 and scores[1][0] == best[0]
    return best[1], ambiguous


_CSV_GUARDED = ("=", "+", "-", "@", "\t", "\r")


def _csv_text(value: str) -> str:
    """Undo the apostrophe that spreadsheet-safe CSV exports put before formula-like text."""
    if len(value) > 1 and value[0] == "'" and value[1] in _CSV_GUARDED:
        return value[1:]
    return value


def _read_csv(data: bytes, lim: dict, *, encoding: str | None, delimiter: str | None) -> Workbook:
    if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ImportFileError("This file is not a text CSV.")
    lowered = data[:512].lstrip().lower()
    if lowered.startswith((b"<!doctype", b"<html", b"<svg", b"<?xml")) or data.startswith(b"PK\x03\x04"):
        raise ImportFileError("This file is not a CSV (wrong file contents).")
    detected_enc, enc_ambiguous = detect_csv_encoding(data)
    enc = encoding or detected_enc
    if enc not in {e for e, _ in CSV_ENCODINGS} and enc != "utf-8":
        raise ImportFileError("Unsupported text encoding.")
    try:
        text = data.decode(enc)
    except UnicodeDecodeError as exc:
        raise ImportFileError(f"The file is not valid {enc} text. Choose another encoding.") from exc
    detected_delim, delim_ambiguous = detect_csv_delimiter(text)
    delim = delimiter or detected_delim
    if delim not in {d for d, _ in CSV_DELIMITERS}:
        raise ImportFileError("Unsupported delimiter.")
    rows: list[list[Cell]] = []
    truncated = False
    max_cols = int(lim["max_columns"])
    try:
        for record in csv.reader(io.StringIO(text, newline=""), delimiter=delim):
            if len(rows) >= int(lim["max_rows_per_sheet"]):
                truncated = True
                break
            rows.append([Cell(_csv_text(v), "text") if v.strip() else Cell(None, "empty") for v in record[:max_cols]])
    except csv.Error as exc:
        raise ImportFileError(f"The CSV could not be parsed: {exc}") from exc
    rows = _trim(rows)
    warnings = []
    if truncated:
        warnings.append(f"Only the first {int(lim['max_rows_per_sheet'])} rows are read.")
    return Workbook(
        kind=CSV,
        sheets=[Sheet(name="CSV", rows=rows, truncated=truncated)],
        warnings=warnings,
        csv_encoding=enc,
        csv_delimiter=delim,
        csv_encoding_ambiguous=enc_ambiguous and not encoding,
        csv_delimiter_ambiguous=delim_ambiguous and not delimiter,
    )


# --- Source snapshots (Google Sheets) ---------------------------------------------

SNAPSHOT_VERSION = 1
MAX_SNAPSHOT_JSON_BYTES = 80 * 1024 * 1024


def _encode_cell(c: Cell) -> list:
    v = c.value
    if isinstance(v, datetime):
        v = v.isoformat()
    elif isinstance(v, date):
        v = v.isoformat()
    elif isinstance(v, dtime):
        v = v.isoformat()
    elif isinstance(v, timedelta):
        v = v.total_seconds()
    if c.fmt:
        return [c.kind, v, c.shown, c.fmt]
    return [c.kind, v, c.shown] if c.shown else [c.kind, v]


def _decode_cell(raw: list) -> Cell:
    kind = str(raw[0])
    v = raw[1] if len(raw) > 1 else None
    shown = str(raw[2] or "") if len(raw) > 2 else ""
    fmt = str(raw[3] or "") if len(raw) > 3 else ""
    if kind == "datetime":
        v = datetime.fromisoformat(v)
    elif kind == "date":
        v = date.fromisoformat(v)
    elif kind == "time":
        v = dtime.fromisoformat(v)
    elif kind == "duration":
        v = timedelta(seconds=float(v))
    elif kind not in ("empty", "text", "number", "bool", "formula_missing", "error"):
        raise ImportFileError("The source snapshot is damaged.")
    return Cell(v, kind, shown, fmt)


def sheet_content_hash(sheet: Sheet) -> str:
    """Content identity of one worksheet's values (used for source-change checks)."""
    body = json.dumps([[_encode_cell(c) for c in row] for row in sheet.rows], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def encode_snapshot(source: dict, sheets: list[Sheet], warnings: list[str]) -> bytes:
    body = {
        "version": SNAPSHOT_VERSION,
        "source": source,
        "warnings": list(warnings),
        "sheets": [
            {
                "name": s.name,
                "truncated": s.truncated,
                "formula_missing": s.formula_missing,
                "errors": s.errors,
                "merges": [list(m) for m in s.merges],
                "rows": [[_encode_cell(c) for c in row] for row in s.rows],
            }
            for s in sheets
        ],
    }
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return gzip.compress(raw, compresslevel=6, mtime=0)


def decode_snapshot(data: bytes) -> tuple[dict, Workbook]:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as fh:
            raw = fh.read(MAX_SNAPSHOT_JSON_BYTES + 1)
        if len(raw) > MAX_SNAPSHOT_JSON_BYTES:
            raise ImportFileError("The source snapshot is too large.")
        body = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ImportFileError("The source snapshot is damaged.") from exc
    if not isinstance(body, dict) or body.get("version") != SNAPSHOT_VERSION:
        raise ImportFileError("The source snapshot is from an unsupported version.")
    sheets = []
    for s in body.get("sheets") or []:
        sheets.append(Sheet(
            name=str(s["name"]),
            rows=[[_decode_cell(c) for c in row] for row in s.get("rows") or []],
            truncated=bool(s.get("truncated")),
            formula_missing=int(s.get("formula_missing") or 0),
            errors=int(s.get("errors") or 0),
            merges=[tuple(int(x) for x in m) for m in s.get("merges") or [] if len(m) == 4],
        ))
    return body.get("source") or {}, Workbook(kind=GSHEET, sheets=sheets, warnings=list(body.get("warnings") or []))
