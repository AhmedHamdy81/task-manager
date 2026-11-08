"""Column mapping and value interpretation for production imports.

Only fields the application actually stores are offered. Every parser keeps three
states apart: an empty cell (no information — never erases existing data), an explicit
value (including 0 and "No"), and an invalid value (reported with sheet/row/column).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

import shooting_items as si
from production_import_parsing import Cell

# --- Field catalogue -----------------------------------------------------------

DAY_LEVEL = "day"
ITEM_LEVEL = "item"


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    level: str
    kind: str
    aliases: tuple[str, ...]
    tv_only: bool = False
    help: str = ""


FIELDS: tuple[FieldDef, ...] = (
    FieldDef("unit_number", "Unit", DAY_LEVEL, "int",
             ("unit", "unit no", "unit number", "unit #", "وحده", "الوحده", "رقم الوحده", "يونت")),
    FieldDef("day_name", "Shooting day", DAY_LEVEL, "day",
             ("day", "shooting day", "shoot day", "day no", "day number", "day name", "day #",
              "يوم", "اليوم", "يوم التصوير", "رقم اليوم")),
    FieldDef("shooting_date", "Shooting date", DAY_LEVEL, "date",
             ("date", "shooting date", "shoot date", "تاريخ", "التاريخ", "تاريخ التصوير")),
    FieldDef("location", "Location", DAY_LEVEL, "text",
             ("location", "loc", "set", "موقع", "الموقع", "مكان التصوير", "لوكيشن", "اللوكيشن")),
    FieldDef("record_id", "BigBang record ID", ITEM_LEVEL, "int",
             ("bigbang id", "record id", "row id", "item id"),
             help="Optional. Must be an existing row of this project."),
    FieldDef("episode", "Episode", ITEM_LEVEL, "episode",
             ("episode", "ep", "eps", "episode no", "episode number", "episode #",
              "حلقه", "الحلقه", "رقم الحلقه"), tv_only=True),
    FieldDef("scene_label", "Scene / description", ITEM_LEVEL, "scene",
             ("scene", "sc", "scene no", "scene number", "scene label", "scene #",
              "مشهد", "المشهد", "رقم المشهد")),
    FieldDef("item_type", "Item type", ITEM_LEVEL, "item_type",
             ("type", "item type", "shooting item type", "category", "نوع", "النوع", "نوع اللقطه")),
    FieldDef("reel_number", "Reel", ITEM_LEVEL, "int",
             ("reel", "reel no", "reel number", "بكره", "ريل")),
    FieldDef("duration", "Duration", ITEM_LEVEL, "duration",
             ("duration", "dur", "length", "time", "runtime", "مده", "المده", "الزمن", "الوقت")),
    FieldDef("sync_done", "Sync", ITEM_LEVEL, "bool",
             ("sync", "synced", "sync done", "مزامنه", "سينك")),
    FieldDef("first_edit_done", "First Edit", ITEM_LEVEL, "bool",
             ("first edit", "1st edit", "1st", "first cut", "مونتاج اول", "المونتاج الاول", "اول مونتاج")),
    FieldDef("needs_vfx", "Needs VFX", ITEM_LEVEL, "bool",
             ("vfx", "needs vfx", "مؤثرات", "مؤثرات بصريه")),
    FieldDef("is_critical", "Critical", ITEM_LEVEL, "bool", ("critical", "urgent", "حرج", "عاجل")),
    FieldDef("notes", "Notes", ITEM_LEVEL, "text",
             ("notes", "note", "comments", "comment", "remarks", "ملاحظات", "ملاحظه")),
)
FIELD_BY_KEY: dict[str, FieldDef] = {f.key: f for f in FIELDS}
DAY_FIELD_KEYS = tuple(f.key for f in FIELDS if f.level == DAY_LEVEL)
ITEM_FIELD_KEYS = tuple(f.key for f in FIELDS if f.level == ITEM_LEVEL)
# Item fields that can be compared/updated on an existing row (identity fields included).
COMPARE_ITEM_FIELDS = (
    "episode", "scene_label", "item_type", "reel_number", "duration",
    "sync_done", "first_edit_done", "needs_vfx", "is_critical", "notes",
)
IDENTITY_FIELDS = frozenset({"episode", "scene_label", "item_type"})

DEFAULT_TRUE_TOKENS = ("yes", "y", "true", "1", "done", "x", "✓", "✔", "نعم", "تم", "منتهي", "ok")
DEFAULT_FALSE_TOKENS = ("no", "n", "false", "0", "not done", "pending", "لا", "لم يتم", "-")

ITEM_TYPE_ALIASES: dict[str, str] = {
    "scene": "Scene", "مشهد": "Scene",
    "reshoot": "Reshoot", "re-shoot": "Reshoot", "re shoot": "Reshoot", "retake": "Reshoot",
    "اعاده": "Reshoot", "اعاده تصوير": "Reshoot",
    "pickup": "Pickup Shot", "pick up": "Pickup Shot", "pickup shot": "Pickup Shot", "pick-up": "Pickup Shot",
    "vfx": "VFX Slate", "vfx slate": "VFX Slate", "slate": "VFX Slate", "مؤثرات": "VFX Slate",
    "establishing": "Establishing Shot", "establishing shot": "Establishing Shot",
    "تاسيسي": "Establishing Shot", "لقطه تاسيسيه": "Establishing Shot",
    "promo": "Promo Shot", "promo shot": "Promo Shot", "برومو": "Promo Shot",
    "other": "Other", "اخري": "Other", "اخرى": "Other",
}

DATE_ORDERS = (("dmy", "Day / Month / Year"), ("mdy", "Month / Day / Year"), ("ymd", "Year / Month / Day"))
DURATION_FORMATS = (
    ("auto", "Automatic (same as the shooting-day form: M:SS, H:MM:SS, minutes, or MMSS)"),
    ("mss", "Minutes:Seconds (M:SS)"),
    ("hmmss", "Hours:Minutes:Seconds (H:MM:SS)"),
    ("seconds", "Total seconds"),
    ("minutes", "Total minutes"),
)
EXCEL_TIME_MODES = (
    ("hmm", "As shown in Excel — hours:minutes:seconds (0:02:50 = 2 min 50 s)"),
    ("mss", "Shifted — Excel shows 03:15:00 but it means 3 min 15 s"),
)

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ARABIC_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ـ": None})


def ascii_digits(text: str) -> str:
    return (text or "").translate(_ARABIC_DIGITS)


def fold_text(text: Any) -> str:
    """Matching key: digits to ASCII, Arabic letter variants folded, diacritics and case removed."""
    s = ascii_digits(str(text or ""))
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = s.translate(_ARABIC_FOLD).casefold()
    s = re.sub(r"[\s_\-\.:#/\\]+", " ", s)
    return s.strip()


# --- Mapping suggestions --------------------------------------------------------


SUMMARY_HEADER_WORDS = frozenset({
    "all", "total", "totals", "subtotal", "sum", "grand", "overall", "cumulative",
    "اجمالي", "الاجمالي", "مجموع", "المجموع", "الكل",
})


def is_summary_header(header: str) -> bool:
    """Headers such as "Duration All" or "Total duration" hold totals, never per-row values."""
    return any(word in SUMMARY_HEADER_WORDS for word in fold_text(header).split())


def suggest_mapping(headers: list[str], *, is_tv: bool) -> dict[int, str]:
    """Column index -> field key. Suggestions only; the user confirms every mapping."""
    out: dict[int, str] = {}
    taken: set[str] = set()
    folded = [fold_text(h) for h in headers]
    for pass_exact in (True, False):
        for idx, head in enumerate(folded):
            if idx in out or not head or is_summary_header(headers[idx]):
                continue
            for f in FIELDS:
                if f.key in taken or (f.tv_only and not is_tv):
                    continue
                aliases = [fold_text(a) for a in f.aliases] + [fold_text(f.label)]
                hit = head in aliases if pass_exact else any(
                    len(a) >= 4 and (a in head) for a in aliases
                )
                if hit:
                    out[idx] = f.key
                    taken.add(f.key)
                    break
    return out


# --- Parsed values --------------------------------------------------------------

EMPTY = "empty"
VALUE = "value"
INVALID = "invalid"


@dataclass
class ParsedValue:
    state: str
    value: Any = None
    display: str = ""
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        v = self.value
        if isinstance(v, date):
            v = v.isoformat()
        return {"state": self.state, "value": v, "display": self.display, "error": self.error}

    @classmethod
    def from_json(cls, data: dict) -> "ParsedValue":
        return cls(data.get("state", EMPTY), data.get("value"), data.get("display", ""), data.get("error", ""))


DEFAULT_BLANK_TOKENS = ("--", "—", "–", "n/a")
TOKEN_YES = "yes"
TOKEN_NO = "no"
TOKEN_IGNORE = "ignore"
TOKEN_CHOICES = (
    (TOKEN_YES, "Yes / completed"),
    (TOKEN_NO, "No / not completed"),
    (TOKEN_IGNORE, "Ignore / no information"),
)


def token_key(text: Any) -> str:
    """Normalized status token; punctuation-only tokens such as "-" keep their characters."""
    folded = fold_text(text)
    return folded or ascii_digits(str(text or "")).strip().casefold()


def blank_key(text: Any) -> str:
    return ascii_digits(str(text or "")).strip().casefold()


@dataclass
class ParseOptions:
    date_order: str = ""
    duration_format: str = "auto"
    excel_time_mode: str = ""
    true_tokens: tuple[str, ...] = DEFAULT_TRUE_TOKENS
    false_tokens: tuple[str, ...] = DEFAULT_FALSE_TOKENS
    field_tokens: dict[str, dict[str, str]] = field(default_factory=dict)
    blank_tokens: tuple[str, ...] = DEFAULT_BLANK_TOKENS
    is_tv: bool = False
    max_episode: int = 1

    @classmethod
    def from_dict(cls, data: dict, *, is_tv: bool, max_episode: int) -> "ParseOptions":
        def tokens(raw, default, key=token_key):
            if raw is None:
                return tuple(key(t) for t in default)
            items = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
            cleaned = tuple(key(t) for t in items if key(t))
            return cleaned or tuple(key(t) for t in default)

        field_tokens: dict[str, dict[str, str]] = {}
        for fkey, mapping in (data.get("field_tokens") or {}).items():
            if fkey in FIELD_BY_KEY and FIELD_BY_KEY[fkey].kind == "bool" and isinstance(mapping, dict):
                field_tokens[fkey] = {
                    token_key(t): v for t, v in mapping.items()
                    if token_key(t) and v in (TOKEN_YES, TOKEN_NO, TOKEN_IGNORE)
                }
        blank_raw = data.get("blank_tokens")
        return cls(
            date_order=str(data.get("date_order") or ""),
            duration_format=str(data.get("duration_format") or "auto"),
            excel_time_mode=str(data.get("excel_time_mode") or ""),
            true_tokens=tokens(data.get("true_tokens"), DEFAULT_TRUE_TOKENS),
            false_tokens=tokens(data.get("false_tokens"), DEFAULT_FALSE_TOKENS),
            field_tokens=field_tokens,
            blank_tokens=tuple(blank_key(t) for t in (blank_raw if isinstance(blank_raw, list) else DEFAULT_BLANK_TOKENS)
                               if blank_key(t)),
            is_tv=is_tv,
            max_episode=max_episode,
        )

    def token_meaning(self, field_key: str, token: str) -> str:
        """yes / no / ignore / "" (unknown). Field-specific definitions win over the shared lists."""
        scoped = self.field_tokens.get(field_key, {})
        if token in scoped:
            return scoped[token]
        if token in self.true_tokens:
            return TOKEN_YES
        if token in self.false_tokens:
            return TOKEN_NO
        return ""


def _empty(cell: Cell) -> bool:
    return cell.kind == "empty" or (cell.kind == "text" and not str(cell.value or "").strip())


def _text(cell: Cell) -> str:
    if cell.kind == "number":
        v = cell.value
        return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
    return str(cell.value if cell.value is not None else "").strip()


def _label_text(cell: Cell) -> str:
    """Identifier-like text: keeps the spreadsheet's formatting (e.g. "001") when known."""
    if cell.kind == "number" and cell.shown.strip():
        return cell.shown.strip()
    return _text(cell)


def parse_int(cell: Cell, label: str, *, minimum: int = 1) -> ParsedValue:
    if _empty(cell):
        return ParsedValue(EMPTY)
    disp = cell.display
    if cell.kind == "number":
        v = cell.value
        if isinstance(v, float) and not v.is_integer():
            return ParsedValue(INVALID, display=disp, error=f"{label} must be a whole number.")
        n = int(v)
    else:
        nums = re.findall(r"\d+", ascii_digits(_text(cell)))
        if len(nums) != 1:
            return ParsedValue(INVALID, display=disp, error=f"{label} must contain one whole number.")
        n = int(nums[0])
    if n < minimum:
        return ParsedValue(INVALID, display=disp, error=f"{label} must be at least {minimum}.")
    return ParsedValue(VALUE, n, disp)


_DAY_PREFIXES = ("shooting day", "shoot day", "day", "d", "يوم التصوير", "اليوم", "يوم")


def day_key(raw: Any) -> str:
    """Identity key for a day name: "Day 05", "D5", "5", "اليوم ٥" all give "5"."""
    s = fold_text(raw)
    for pfx in _DAY_PREFIXES:
        p = fold_text(pfx)
        if s == p:
            return ""
        if s.startswith(p + " ") or (s.startswith(p) and s[len(p):].strip().isdigit()):
            s = s[len(p):].strip()
            break
    if s.isdigit():
        return str(int(s))
    return s


def storage_day_name(raw: str) -> str:
    """Name for a new day, following the app convention ("5" is stored as "Day 5")."""
    text = ascii_digits(raw.strip())
    key = day_key(text)
    if key.isdigit():
        return f"Day {int(key)}"
    return text[:50]


def parse_day(cell: Cell) -> ParsedValue:
    if _empty(cell):
        return ParsedValue(EMPTY)
    text = _label_text(cell)
    key = day_key(text)
    if not key:
        return ParsedValue(INVALID, display=cell.display, error="Shooting day has no number or name.")
    if not any(ch.isdigit() for ch in key):
        return ParsedValue(INVALID, display=cell.display, error=f"Shooting day “{text[:40]}” has no day number.")
    if len(text) > 50:
        return ParsedValue(INVALID, display=cell.display, error="Shooting day name is longer than 50 characters.")
    return ParsedValue(VALUE, text, cell.display)


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _year(y: int) -> int:
    return 2000 + y if y < 100 else y


def date_is_ambiguous(cell: Cell) -> bool:
    if cell.kind != "text":
        return False
    m = re.fullmatch(r"(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{2,4})", ascii_digits(_text(cell)))
    return bool(m and int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and m.group(1) != m.group(2))


def parse_date(cell: Cell, opts: ParseOptions) -> ParsedValue:
    if _empty(cell):
        return ParsedValue(EMPTY)
    disp = cell.display
    if cell.kind == "datetime":
        return ParsedValue(VALUE, cell.value.date(), disp)
    if cell.kind == "date":
        return ParsedValue(VALUE, cell.value, disp)
    if cell.kind == "number":
        v = float(cell.value)
        if 20000 <= v <= 80000:
            return ParsedValue(VALUE, date(1899, 12, 30) + timedelta(days=int(v)), disp)
        return ParsedValue(INVALID, display=disp, error="Not a recognisable date.")
    text = ascii_digits(_text(cell)).strip()
    m = re.fullmatch(r"(\d{4})[/\.\-](\d{1,2})[/\.\-](\d{1,2})", text)
    try:
        if m:
            return ParsedValue(VALUE, date(int(m.group(1)), int(m.group(2)), int(m.group(3))), disp)
        m = re.fullmatch(r"(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{2,4})", text)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), _year(int(m.group(3)))
            if a > 12 and b <= 12:
                return ParsedValue(VALUE, date(y, b, a), disp)
            if b > 12 and a <= 12:
                return ParsedValue(VALUE, date(y, a, b), disp)
            if a == b:
                return ParsedValue(VALUE, date(y, a, b), disp)
            if opts.date_order == "dmy":
                return ParsedValue(VALUE, date(y, b, a), disp)
            if opts.date_order == "mdy":
                return ParsedValue(VALUE, date(y, a, b), disp)
            return ParsedValue(INVALID, display=disp, error="Ambiguous date — choose the date order.")
        m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,})\.?,?\s+(\d{2,4})", text)
        if m and m.group(2)[:3].lower() in _MONTHS:
            return ParsedValue(VALUE, date(_year(int(m.group(3))), _MONTHS[m.group(2)[:3].lower()], int(m.group(1))), disp)
        m = re.fullmatch(r"([A-Za-z]{3,})\.?\s+(\d{1,2}),?\s+(\d{2,4})", text)
        if m and m.group(1)[:3].lower() in _MONTHS:
            return ParsedValue(VALUE, date(_year(int(m.group(3))), _MONTHS[m.group(1)[:3].lower()], int(m.group(2))), disp)
    except ValueError:
        return ParsedValue(INVALID, display=disp, error="Not a valid calendar date.")
    return ParsedValue(INVALID, display=disp, error="Not a recognisable date.")


DURATION_ELAPSED = "elapsed"
DURATION_TIME_OF_DAY = "time_of_day"
DURATION_NUMBER = "number"
DURATION_TEXT = "text"
DURATION_KIND_LABELS = {
    DURATION_ELAPSED: "Elapsed duration",
    DURATION_TIME_OF_DAY: "Time of day",
    DURATION_NUMBER: "Number",
    DURATION_TEXT: "Text",
}
_SERIAL_EPOCH = datetime(1899, 12, 30)


def duration_cell_is_time(cell: Cell) -> bool:
    return cell.kind in ("time", "duration") or (cell.kind == "datetime" and cell.value.date() <= date(1900, 1, 1))


def duration_cell_kind(cell: Cell) -> str:
    """Elapsed ([h]:mm:ss or ≥ 24 h), time-of-day (h:mm:ss under 24 h), plain number, or text."""
    if cell.kind == "duration":
        return DURATION_ELAPSED
    if cell.kind == "time" or (cell.kind == "datetime" and cell.value.date() <= date(1900, 1, 1)):
        return DURATION_TIME_OF_DAY
    if cell.kind == "number":
        return DURATION_NUMBER
    return DURATION_TEXT


def round_half_up(seconds: float) -> int:
    """Durations are whole seconds: fractions round to the nearest second, exactly .5 rounds up."""
    return int((seconds + 0.5) // 1) if seconds >= 0 else -int((-seconds + 0.5) // 1)


def excel_time_seconds(cell: Cell, mode: str) -> int:
    """Seconds for an Excel time/duration cell. "hmm" = as shown; "mss" = shifted (h→min, min→s)."""
    if cell.kind == "duration":
        total = cell.value.total_seconds()
    elif cell.kind == "datetime":
        # Serials below 60 (before 1900-03-01) count from 1899-12-31 because of Excel's 1900 leap-year quirk.
        base = datetime(1899, 12, 31) if cell.value < datetime(1900, 3, 1) else _SERIAL_EPOCH
        total = (cell.value - base).total_seconds()
    else:
        t = cell.value
        total = t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1_000_000
    secs = round_half_up(total)
    if mode == "mss":
        return (secs // 3600) * 60 + (secs % 3600) // 60
    return secs


def _auto_duration(text: str) -> int | None:
    """Same rules as the shooting-day form (parse_shooting_day_duration_seconds)."""
    s = text.strip()
    if not s:
        return 0
    while "::" in s:
        s = s.replace("::", ":")
    if ":" in s:
        parts = [p for p in s.split(":") if p != ""]
        if not all(p.isdigit() for p in parts):
            return None
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return None
    if s.isdigit():
        if len(s) <= 3:
            return int(s) * 60
        return int(s[:-2]) * 60 + min(59, int(s[-2:]))
    return None


def parse_duration(cell: Cell, opts: ParseOptions) -> ParsedValue:
    if _empty(cell):
        return ParsedValue(EMPTY)
    disp = cell.display
    fmt = opts.duration_format or "auto"
    if duration_cell_is_time(cell):
        mode = opts.excel_time_mode
        if not mode and duration_cell_kind(cell) == DURATION_TIME_OF_DAY:
            return ParsedValue(INVALID, display=disp, error="Time-of-day cell — choose how to read Excel time cells.")
        return ParsedValue(VALUE, excel_time_seconds(cell, mode or "hmm"), disp)
    text = ascii_digits(_text(cell))
    try:
        if fmt == "seconds":
            secs = round_half_up(float(text))
        elif fmt == "minutes":
            secs = round_half_up(float(text) * 60)
        elif fmt == "mss":
            m = re.fullmatch(r"(\d+):(\d{1,2})", text)
            if not m or int(m.group(2)) > 59:
                raise ValueError
            secs = int(m.group(1)) * 60 + int(m.group(2))
        elif fmt == "hmmss":
            m = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", text)
            if not m:
                raise ValueError
            secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3) or 0)
        else:
            if cell.kind == "number":
                v = float(cell.value)
                if not v.is_integer():
                    raise ValueError
                text = str(int(v))
            secs = _auto_duration(text)
            if secs is None:
                raise ValueError
    except (TypeError, ValueError):
        return ParsedValue(INVALID, display=disp, error="Duration does not match the chosen format.")
    if secs < 0:
        return ParsedValue(INVALID, display=disp, error="Duration cannot be negative.")
    return ParsedValue(VALUE, int(secs), disp)


def parse_bool(cell: Cell, opts: ParseOptions, label: str, field_key: str = "") -> ParsedValue:
    if _empty(cell):
        return ParsedValue(EMPTY)
    if cell.kind == "bool":
        return ParsedValue(VALUE, bool(cell.value), cell.display)
    meaning = opts.token_meaning(field_key, token_key(_text(cell)))
    if meaning == TOKEN_YES:
        return ParsedValue(VALUE, True, cell.display)
    if meaning == TOKEN_NO:
        return ParsedValue(VALUE, False, cell.display)
    if meaning == TOKEN_IGNORE:
        return ParsedValue(EMPTY, display=f"{cell.display} (ignored)")
    return ParsedValue(
        INVALID, display=cell.display,
        error=f"{label}: “{cell.display}” is not defined. Choose Yes, No or Ignore for it under “Status values”.",
    )


def parse_item_type(cell: Cell) -> ParsedValue:
    if _empty(cell):
        return ParsedValue(EMPTY)
    raw = _text(cell)
    folded = fold_text(raw)
    for choice in si.SHOOTING_ITEM_TYPE_CHOICES:
        if fold_text(choice) == folded:
            return ParsedValue(VALUE, choice, cell.display)
    if folded in {fold_text(k): v for k, v in ITEM_TYPE_ALIASES.items()}:
        return ParsedValue(VALUE, {fold_text(k): v for k, v in ITEM_TYPE_ALIASES.items()}[folded], cell.display)
    for legacy in si.LEGACY_SHOOTING_ITEM_TYPES:
        if fold_text(legacy) == folded:
            return ParsedValue(VALUE, legacy, cell.display)
    return ParsedValue(INVALID, display=cell.display, error=f"Unknown item type “{raw}”.")


def parse_episode(cell: Cell, opts: ParseOptions) -> ParsedValue:
    """Returns the raw form parse_shooting_row_identity expects: "5", "X" or "establishing"."""
    if _empty(cell):
        return ParsedValue(EMPTY)
    raw = _text(cell)
    folded = fold_text(raw)
    if folded in si.EPISODE_UNASSIGNED_INPUT_VALUES or folded in ("حلقه x", "غير محدد"):
        return ParsedValue(VALUE, "X", cell.display)
    if folded in si.EPISODE_ESTABLISHING_SHOTS_INPUT_VALUES:
        return ParsedValue(VALUE, "establishing", cell.display)
    nums = re.findall(r"\d+", ascii_digits(raw))
    if len(nums) != 1:
        return ParsedValue(INVALID, display=cell.display, error="Episode must be a number, X, or Establishing.")
    n = int(nums[0])
    if opts.is_tv and opts.max_episode < 1:
        return ParsedValue(INVALID, display=cell.display,
                           error="The project has no number of episodes set. Set it in the project settings first.")
    if n < 1 or (opts.is_tv and n > opts.max_episode):
        return ParsedValue(INVALID, display=cell.display, error=f"Episode must be between 1 and {opts.max_episode}.")
    return ParsedValue(VALUE, str(n), cell.display)


_SCENE_PREFIX = re.compile(r"^(?:scene|sc\.?|مشهد)\s+", re.IGNORECASE)


def parse_scene(cell: Cell) -> ParsedValue:
    if _empty(cell):
        return ParsedValue(EMPTY)
    if cell.kind in ("date", "datetime"):
        return ParsedValue(
            INVALID, display=cell.display,
            error="Excel turned this scene label into a date (format "
                  f"{cell.fmt or 'date'}). Re-type the scene as text in the source.",
        )
    label = _SCENE_PREFIX.sub("", ascii_digits(_label_text(cell))).strip()
    if len(label) > 120:
        return ParsedValue(INVALID, display=cell.display, error="Scene is longer than 120 characters.")
    return ParsedValue(VALUE, label, cell.display)


def parse_text(cell: Cell, *, max_len: int, label: str) -> ParsedValue:
    if _empty(cell):
        return ParsedValue(EMPTY)
    text = _label_text(cell)
    if len(text) > max_len:
        return ParsedValue(INVALID, display=cell.display[:80], error=f"{label} is longer than {max_len} characters.")
    return ParsedValue(VALUE, text, cell.display)


def parse_field(key: str, cell: Cell, opts: ParseOptions) -> ParsedValue:
    if cell.kind == "formula_missing":
        return ParsedValue(INVALID, display=cell.display, error="Formula has no saved result — recalculate in Excel or correct the cell.")
    if cell.kind == "error":
        return ParsedValue(INVALID, display=cell.display, error=f"Spreadsheet error value {cell.display} — fix the cell in the source.")
    if cell.kind == "text" and opts.blank_tokens and blank_key(cell.value) in opts.blank_tokens:
        return ParsedValue(EMPTY, display=f"{cell.display} (placeholder)")
    f = FIELD_BY_KEY[key]
    if key == "unit_number":
        return parse_int(cell, f.label)
    if key == "record_id":
        return parse_int(cell, f.label)
    if key == "reel_number":
        return parse_int(cell, f.label)
    if key == "day_name":
        return parse_day(cell)
    if key == "shooting_date":
        return parse_date(cell, opts)
    if key == "duration":
        return parse_duration(cell, opts)
    if f.kind == "bool":
        return parse_bool(cell, opts, f.label, key)
    if key == "item_type":
        return parse_item_type(cell)
    if key == "episode":
        return parse_episode(cell, opts)
    if key == "scene_label":
        return parse_scene(cell)
    if key == "location":
        return parse_text(cell, max_len=255, label=f.label)
    if key == "notes":
        return parse_text(cell, max_len=20000, label=f.label)
    return ParsedValue(INVALID, display=cell.display, error="Unsupported field.")


def parse_default(key: str, raw: str, opts: ParseOptions) -> ParsedValue:
    """A typed-in default value, parsed with the same rules as a cell."""
    return parse_field(key, Cell(raw, "text") if str(raw or "").strip() else Cell(None, "empty"), opts)


# --- Source rows ----------------------------------------------------------------


@dataclass
class SourceRow:
    sheet: str
    row_number: int
    values: dict[str, ParsedValue] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    day_override: dict[str, Any] = field(default_factory=dict)
    inherited: dict[str, dict[str, str]] = field(default_factory=dict)

    def get(self, key: str) -> ParsedValue:
        return self.values.get(key) or ParsedValue(EMPTY)

    def to_json(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "row_number": self.row_number,
            "values": {k: v.to_json() for k, v in self.values.items()},
            "errors": self.errors,
        }


def column_letter(idx: int) -> str:
    out = ""
    n = idx + 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


# Day-level fields that may be filled down; Location and Date belong to one Day group.
FILL_DOWN_FIELDS = ("unit_number", "day_name", "shooting_date", "location")
DAY_SCOPED_FIELDS = ("shooting_date", "location")


def build_source_rows(
    sheet_name: str,
    rows: list[list[Cell]],
    *,
    header_row: int,
    skip_after_header: int,
    mapping: dict[int, str],
    defaults: dict[str, ParsedValue],
    sheet_day_context: dict[str, ParsedValue],
    opts: ParseOptions,
    fill_down: set[str] | frozenset[str] = frozenset(),
    location_across_days: bool = False,
    merges: dict[tuple[int, int], tuple[int, int]] | None = None,
    stats: dict | None = None,
) -> list[SourceRow]:
    """header_row is 0-based; reported row numbers are the worksheet's 1-based numbers.

    Fill-down (opt-in, per field) carries a value forward to blank cells below it within the
    worksheet. It never fills upward, never overwrites a value, resets at blank, summary and
    repeated-header rows, and a new Day clears the previous Day's Location and Date.
    """
    stats = stats if stats is not None else {}
    stats.setdefault("inherited", {})
    for key in ("merged", "resets", "summary_rows", "header_repeats", "group_headers", "data_rows"):
        stats.setdefault(key, 0)
    merges = merges or {}
    out: list[SourceRow] = []
    headers = rows[header_row] if 0 <= header_row < len(rows) else []
    active = {idx: key for idx, key in mapping.items()
              if key in FIELD_BY_KEY and not (FIELD_BY_KEY[key].tv_only and not opts.is_tv)}
    fill_cols = sorted((idx for idx, key in active.items() if key in fill_down and key in FILL_DOWN_FIELDS),
                       key=lambda i: FILL_DOWN_FIELDS.index(active[i]))
    other_cols = [idx for idx in active if idx not in fill_cols]
    header_keys = {idx: fold_text(headers[idx].display) for idx in active if idx < len(headers)}
    first_data = header_row + 1 + max(0, skip_after_header)
    context: dict[str, tuple[ParsedValue, str]] = {}

    def cell_at(cells, idx) -> Cell:
        return cells[idx] if idx < len(cells) else Cell(None, "empty")

    def reset() -> None:
        if context:
            stats["resets"] += 1
        context.clear()

    def set_context(key: str, parsed: ParsedValue, ref: str) -> None:
        if key == "day_name":
            for scoped in DAY_SCOPED_FIELDS:
                if scoped == "location" and location_across_days:
                    continue
                context.pop(scoped, None)
        context[key] = (parsed, ref)

    def column_label(idx: int) -> str:
        return f"{column_letter(idx)} · {headers[idx].display if idx < len(headers) else ''}".strip(" ·")

    for offset, cells in enumerate(rows[first_data:]):
        row_number = first_data + 1 + offset
        if all(_empty(c) for c in cells):
            reset()
            continue
        repeats = sum(
            1 for idx in active
            if header_keys.get(idx) and not _empty(cell_at(cells, idx))
            and fold_text(cell_at(cells, idx).display) == header_keys[idx]
        )
        if repeats >= 2:
            stats["header_repeats"] += 1
            reset()
            continue
        has_other = any(not _empty(cell_at(cells, idx)) for idx in other_cols)
        explicit_fill = [idx for idx in fill_cols if not _empty(cell_at(cells, idx))]
        if not has_other:
            if not explicit_fill:
                if fill_cols:
                    stats["summary_rows"] += 1
                    reset()
                continue
            # A line that only names the Day / Location starts a group but is not a scene row.
            stats["group_headers"] += 1
            for idx in explicit_fill:
                parsed = parse_field(active[idx], cell_at(cells, idx), opts)
                if parsed.state != VALUE:
                    reset()
                    break
                set_context(active[idx], parsed, f"{column_letter(idx)}{row_number}")
            continue
        stats["data_rows"] += 1
        src = SourceRow(sheet=sheet_name, row_number=row_number)
        for idx in fill_cols + other_cols:
            key = active[idx]
            cell = cell_at(cells, idx)
            ref = f"{column_letter(idx)}{row_number}"
            if idx in fill_cols and _empty(cell):
                anchor = merges.get((row_number, idx + 1))
                if anchor and anchor[0] >= first_data + 1:
                    a_row, a_col = anchor
                    a_cells = rows[a_row - 1] if a_row - 1 < len(rows) else []
                    a_cell = cell_at(a_cells, a_col - 1)
                    if not _empty(a_cell):
                        parsed = parse_field(key, a_cell, opts)
                        if parsed.state == VALUE:
                            a_ref = f"{column_letter(a_col - 1)}{a_row}"
                            if key == "day_name" and context.get(key, (None, ""))[1] != a_ref:
                                set_context(key, parsed, a_ref)
                            else:
                                context[key] = (parsed, a_ref)
                            src.values[key] = ParsedValue(VALUE, parsed.value, parsed.display)
                            src.inherited[key] = {"from": a_ref, "how": "merged", "sheet": sheet_name, "original": ""}
                            stats["merged"] += 1
                            stats["inherited"][key] = stats["inherited"].get(key, 0) + 1
                            continue
                if key in context:
                    parsed, from_ref = context[key]
                    src.values[key] = ParsedValue(VALUE, parsed.value, parsed.display)
                    src.inherited[key] = {"from": from_ref, "how": "fill", "sheet": sheet_name, "original": ""}
                    stats["inherited"][key] = stats["inherited"].get(key, 0) + 1
                    continue
            parsed = parse_field(key, cell, opts)
            src.values[key] = parsed
            if idx in fill_cols and parsed.state == VALUE:
                set_context(key, parsed, ref)
            elif idx in fill_cols and parsed.state == INVALID:
                context.pop(key, None)
            if parsed.state == INVALID:
                src.errors.append({
                    "sheet": sheet_name,
                    "row": str(row_number),
                    "column": column_label(idx),
                    "value": parsed.display,
                    "message": parsed.error,
                })
        for key, value in defaults.items():
            if value.state == VALUE and src.get(key).state == EMPTY:
                src.values[key] = ParsedValue(VALUE, value.value, f"{value.display} (default)")
        for key, value in sheet_day_context.items():
            if value.state == VALUE:
                src.values[key] = ParsedValue(VALUE, value.value, f"{value.display} (worksheet)")
                src.inherited.pop(key, None)
        out.append(src)
    return out
