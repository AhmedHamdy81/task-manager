"""Project Working Hours — normalization layer over the ProjectWorkLedger table.

Sources of worked time (dashboard work sessions, machine-room copy/convert,
manual entries) each keep their own system of record. This module turns them
into uniform ledger rows so reporting, approval, billable hours, and exports
have one shape to read. Route code stays thin: it validates the request, calls
one function here, and renders.

Duplicate protection is the core invariant. A row is identified by
``(source_type, source_id)`` when a source id exists, otherwise by
``operation_id``. Every upsert looks the row up first, so replaying an event
(ending a session twice, a retried copy callback) updates instead of inserting.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Iterable

# --- Source types -----------------------------------------------------------

SOURCE_MANUAL = "manual"
SOURCE_WORK_SESSION = "work_session"
SOURCE_BOOKING = "booking"
SOURCE_MEDIA_COPY = "media_copy"
SOURCE_MEDIA_CONVERT = "media_convert"
SOURCE_SYNC = "sync"
SOURCE_CONFORM = "conform"
SOURCE_COLOR = "color"
SOURCE_VFX = "vfx"
SOURCE_SOUND = "sound"
SOURCE_PRODUCER = "producer"
SOURCE_OTHER = "other"

SOURCE_TYPES: tuple[str, ...] = (
    SOURCE_MANUAL,
    SOURCE_WORK_SESSION,
    SOURCE_BOOKING,
    SOURCE_MEDIA_COPY,
    SOURCE_MEDIA_CONVERT,
    SOURCE_SYNC,
    SOURCE_CONFORM,
    SOURCE_COLOR,
    SOURCE_VFX,
    SOURCE_SOUND,
    SOURCE_PRODUCER,
    SOURCE_OTHER,
)

SOURCE_TYPE_LABELS: dict[str, str] = {
    SOURCE_MANUAL: "Manual Hours",
    SOURCE_WORK_SESSION: "Work Session",
    SOURCE_BOOKING: "Booking",
    SOURCE_MEDIA_COPY: "Copy Media",
    SOURCE_MEDIA_CONVERT: "Convert / Transcode",
    SOURCE_SYNC: "Sync",
    SOURCE_CONFORM: "Conform",
    SOURCE_COLOR: "Color",
    SOURCE_VFX: "VFX",
    SOURCE_SOUND: "Sound",
    SOURCE_PRODUCER: "Producer",
    SOURCE_OTHER: "Other",
}

# --- Statuses ---------------------------------------------------------------

STATUS_DRAFT = "draft"
STATUS_STARTED = "started"
STATUS_SUBMITTED = "submitted"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_AUTO_APPROVED = "auto_approved"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"

STATUSES: tuple[str, ...] = (
    STATUS_DRAFT,
    STATUS_STARTED,
    STATUS_SUBMITTED,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_AUTO_APPROVED,
    STATUS_CANCELLED,
    STATUS_FAILED,
)

STATUS_LABELS: dict[str, str] = {
    STATUS_DRAFT: "Draft",
    STATUS_STARTED: "In Progress",
    STATUS_SUBMITTED: "Pending Approval",
    STATUS_APPROVED: "Approved",
    STATUS_REJECTED: "Rejected",
    STATUS_AUTO_APPROVED: "Auto Approved",
    STATUS_CANCELLED: "Cancelled",
    STATUS_FAILED: "Failed",
}

#: Statuses whose minutes count toward reported totals.
COUNTED_STATUSES: frozenset[str] = frozenset(
    {STATUS_SUBMITTED, STATUS_APPROVED, STATUS_AUTO_APPROVED}
)
#: Statuses that an approver has already signed off.
APPROVED_STATUSES: frozenset[str] = frozenset({STATUS_APPROVED, STATUS_AUTO_APPROVED})
#: Statuses that still need a decision from an approver.
PENDING_STATUSES: frozenset[str] = frozenset({STATUS_SUBMITTED})
#: Statuses an owner may still edit or delete without admin rights.
OWNER_EDITABLE_STATUSES: frozenset[str] = frozenset(
    {STATUS_DRAFT, STATUS_SUBMITTED, STATUS_REJECTED}
)
#: Statuses that lock a row against everyone except an admin.
LOCKED_STATUSES: frozenset[str] = APPROVED_STATUSES

# --- Departments ------------------------------------------------------------

DEPT_PRODUCTION = "production"
DEPT_POST_PRODUCTION = "post_production"
DEPT_EDITORIAL = "editorial"
DEPT_MACHINE_ROOM = "machine_room"
DEPT_CONFORM = "conform"
DEPT_VFX = "vfx"
DEPT_COLOR = "color"
DEPT_SOUND = "sound"
DEPT_DELIVERY = "delivery"
DEPT_OTHER = "other"

DEPARTMENT_KEYS: tuple[str, ...] = (
    DEPT_PRODUCTION,
    DEPT_POST_PRODUCTION,
    DEPT_EDITORIAL,
    DEPT_MACHINE_ROOM,
    DEPT_CONFORM,
    DEPT_VFX,
    DEPT_COLOR,
    DEPT_SOUND,
    DEPT_DELIVERY,
    DEPT_OTHER,
)

DEPARTMENT_LABELS: dict[str, str] = {
    DEPT_PRODUCTION: "Production",
    DEPT_POST_PRODUCTION: "Post Production",
    DEPT_EDITORIAL: "Editorial",
    DEPT_MACHINE_ROOM: "Machine Room",
    DEPT_CONFORM: "Conform",
    DEPT_VFX: "VFX",
    DEPT_COLOR: "Color",
    DEPT_SOUND: "Sound",
    DEPT_DELIVERY: "Delivery",
    DEPT_OTHER: "Other",
}

#: Directory ``department_code`` values mapped onto ledger department keys.
_DEPARTMENT_CODE_MAP: dict[str, str] = {
    "editing": DEPT_EDITORIAL,
    "editorial": DEPT_EDITORIAL,
    "offline_editing": DEPT_EDITORIAL,
    "online_editing": DEPT_EDITORIAL,
    "color_grading": DEPT_COLOR,
    "color": DEPT_COLOR,
    "conform": DEPT_CONFORM,
    "vfx": DEPT_VFX,
    "sound": DEPT_SOUND,
    "sound_post": DEPT_SOUND,
    "delivery": DEPT_DELIVERY,
    "delivery_qc": DEPT_DELIVERY,
    "machine_room": DEPT_MACHINE_ROOM,
    "machine_room_media_management": DEPT_MACHINE_ROOM,
    "media_management": DEPT_MACHINE_ROOM,
    "post_production": DEPT_POST_PRODUCTION,
    "post_production_management": DEPT_POST_PRODUCTION,
    "post": DEPT_POST_PRODUCTION,
    "production": DEPT_PRODUCTION,
}

# --- Work types -------------------------------------------------------------

WORK_TYPE_LABELS: dict[str, str] = {
    "sync": "Sync",
    "selection": "Selection",
    "assembly": "Assembly",
    "offline_editing": "Offline Editing",
    "online_editing": "Online Editing",
    "color_grading": "Color Grading",
    "conform": "Conform",
    "vfx_work": "VFX Work",
    "sound_edit": "Sound Edit",
    "sound_mix": "Sound Mix",
    "copy_media": "Copy Media",
    "convert_transcode": "Convert / Transcode",
    "review": "Review",
    "meeting": "Meeting",
    "supervision": "Supervision",
    "delivery_prep": "Delivery Prep",
    "admin": "Admin",
    "other": "Other",
}

#: Work types offered in the manual-entry form, in display order.
MANUAL_WORK_TYPES: tuple[str, ...] = (
    "offline_editing",
    "online_editing",
    "conform",
    "color_grading",
    "vfx_work",
    "sound_edit",
    "sound_mix",
    "sync",
    "selection",
    "assembly",
    "copy_media",
    "convert_transcode",
    "review",
    "meeting",
    "supervision",
    "delivery_prep",
    "admin",
    "other",
)

WORK_TYPE_DEFAULT_DEPARTMENT: dict[str, str] = {
    "sync": DEPT_MACHINE_ROOM,
    "selection": DEPT_EDITORIAL,
    "assembly": DEPT_EDITORIAL,
    "offline_editing": DEPT_EDITORIAL,
    "online_editing": DEPT_EDITORIAL,
    "offline": DEPT_EDITORIAL,
    "online": DEPT_EDITORIAL,
    "edit": DEPT_EDITORIAL,
    "edit_fee": DEPT_EDITORIAL,
    "color_grading": DEPT_COLOR,
    "color_grading_senior_colorist": DEPT_COLOR,
    "color_grading_colorist": DEPT_COLOR,
    "color_grading_dry_rent": DEPT_COLOR,
    "conform": DEPT_CONFORM,
    "vfx_work": DEPT_VFX,
    "sound_edit": DEPT_SOUND,
    "sound_mix": DEPT_SOUND,
    "sound_design_mix": DEPT_SOUND,
    "copy_media": DEPT_MACHINE_ROOM,
    "convert_transcode": DEPT_MACHINE_ROOM,
    "copy_convert_sync": DEPT_MACHINE_ROOM,
    "copy_convert": DEPT_MACHINE_ROOM,
    "upload_download_1g": DEPT_MACHINE_ROOM,
    "delivery_prep": DEPT_DELIVERY,
    "supervision": DEPT_POST_PRODUCTION,
}

# --- Limits -----------------------------------------------------------------

MAX_MANUAL_MINUTES = 24 * 60
MAX_ADMIN_MINUTES = 7 * 24 * 60
#: How far ahead a work_date may be dated (a night shift can roll past midnight).
MAX_FUTURE_DAYS = 1
MAX_ADMIN_FUTURE_DAYS = 31
TITLE_MAX = 200
DESCRIPTION_MAX = 4000

PAGE_SIZES: tuple[int, ...] = (25, 50, 100, 250)
DEFAULT_PAGE_SIZE = 50


# ---------------------------------------------------------------------------
# Extension plumbing
# ---------------------------------------------------------------------------


def _extension() -> dict[str, Any]:
    try:
        from flask import current_app

        return current_app.extensions.get("project_work_ledger") or {}
    except Exception:
        return {}


def resolve_model(model: Any = None) -> Any:
    """The ProjectWorkLedger class, from the caller or the app extension."""
    if model is not None:
        return model
    return _extension().get("Model")


def resolve_db(db: Any = None) -> Any:
    if db is not None:
        return db
    return _extension().get("db")


# ---------------------------------------------------------------------------
# Formatting and normalization
# ---------------------------------------------------------------------------


def format_minutes_label(minutes: int | float | None) -> str:
    """``195`` -> ``"3h 15m"``. Always returns something renderable."""
    total = int(minutes or 0)
    sign = "-" if total < 0 else ""
    total = abs(total)
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{sign}{hours}h {mins:02d}m"
    if hours:
        return f"{sign}{hours}h"
    return f"{sign}{mins}m"


def format_hours_value(minutes: int | float | None) -> str:
    """Decimal hours for exports and summary cards, e.g. ``"3.25"``."""
    return f"{(int(minutes or 0) / 60.0):.2f}"


def minutes_between(start: datetime | None, end: datetime | None) -> int:
    """Whole minutes between two instants, rounded up. Never negative."""
    if start is None or end is None:
        return 0
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 60.0))


def slugify_key(value: Any, *, fallback: str = "other", max_len: int = 64) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return (text or fallback)[:max_len]


def normalize_source_type(value: Any) -> str:
    key = slugify_key(value, fallback=SOURCE_OTHER, max_len=32)
    return key if key in SOURCE_TYPES else SOURCE_OTHER


def normalize_status(value: Any, *, fallback: str = STATUS_SUBMITTED) -> str:
    key = slugify_key(value, fallback=fallback, max_len=32)
    return key if key in STATUSES else fallback


def normalize_department_key(value: Any, *, fallback: str = DEPT_OTHER) -> str:
    key = slugify_key(value, fallback=fallback, max_len=40)
    if key in DEPARTMENT_KEYS:
        return key
    return _DEPARTMENT_CODE_MAP.get(key, fallback)


def normalize_work_type(value: Any, *, fallback: str = "other") -> str:
    """Slugify a job type. Unknown slugs are kept so nothing is silently lost."""
    return slugify_key(value, fallback=fallback, max_len=64)


# Rate-card / session aliases that should match the ledger work types shown
# in the Working Hours log (e.g. "Offline" -> "Offline Editing").
WORK_TYPE_CANONICAL: dict[str, str] = {
    "offline": "offline_editing",
    "edit": "offline_editing",
    "online": "online_editing",
}


def canonical_work_type(value: Any, *, fallback: str = "other") -> str:
    slug = normalize_work_type(value, fallback=fallback)
    return WORK_TYPE_CANONICAL.get(slug, slug)


def work_type_equivalent_keys(value: Any) -> tuple[str, ...]:
    """All stored slugs that should match a filter/form work-type choice."""
    slug = normalize_work_type(value, fallback="")
    if not slug:
        return ()
    canon = canonical_work_type(slug)
    keys = {slug, canon}
    for alias, target in WORK_TYPE_CANONICAL.items():
        if target == canon:
            keys.add(alias)
    return tuple(sorted(keys))


def department_label(key: Any) -> str:
    slug = slugify_key(key, fallback=DEPT_OTHER, max_len=40)
    return DEPARTMENT_LABELS.get(slug) or slug.replace("_", " ").title()


_extra_work_type_labels: dict[str, str] = {}


def set_extra_work_type_labels(labels: dict[str, str] | None) -> None:
    """Register dynamic work-type labels (e.g. Rate Card service names) for this process."""
    global _extra_work_type_labels
    mapped: dict[str, str] = {}
    for key, value in (labels or {}).items():
        slug = slugify_key(key, fallback="", max_len=64)
        name = str(value).strip()
        if not slug or not name:
            continue
        mapped[slug] = name
        mapped[canonical_work_type(slug)] = name
        for alias, target in WORK_TYPE_CANONICAL.items():
            if target == canonical_work_type(slug):
                mapped[alias] = name
    _extra_work_type_labels = mapped


def work_type_label(key: Any) -> str:
    slug = slugify_key(key, fallback="other", max_len=64)
    canon = canonical_work_type(slug)
    return (
        _extra_work_type_labels.get(slug)
        or _extra_work_type_labels.get(canon)
        or WORK_TYPE_LABELS.get(canon)
        or WORK_TYPE_LABELS.get(slug)
        or slug.replace("_", " ").title()
    )


def source_type_label(key: Any) -> str:
    slug = slugify_key(key, fallback=SOURCE_OTHER, max_len=32)
    return SOURCE_TYPE_LABELS.get(slug) or slug.replace("_", " ").title()


def status_label(key: Any) -> str:
    slug = slugify_key(key, fallback=STATUS_SUBMITTED, max_len=32)
    return STATUS_LABELS.get(slug) or slug.replace("_", " ").title()


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_int(value: Any, default: int | None = None) -> int | None:
    raw = str(value if value is not None else "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def parse_hours_minutes(hours: Any, minutes: Any) -> int:
    """Combine an hours field and a minutes field into total minutes."""
    return (parse_int(hours, 0) or 0) * 60 + (parse_int(minutes, 0) or 0)


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def infer_department_from_user(user: Any = None, *, account: Any = None, fallback: str = DEPT_EDITORIAL) -> str:
    """Best-effort department for a directory user, from job titles then categories.

    Falls back to ``editorial`` because the dashboard session widget is an
    editorial tool: a session with no resolvable job title is editorial time.
    """
    if user is None and account is not None:
        user = getattr(account, "directory_user", None)
    if user is None:
        return fallback

    direct = normalize_department_key(getattr(user, "department_code", None), fallback="")
    if direct:
        return direct

    titles: Iterable[Any] = ()
    getter = getattr(user, "assigned_job_titles", None)
    if callable(getter):
        try:
            titles = getter() or ()
        except Exception:
            titles = ()
    if not titles:
        single = getattr(user, "job_title", None)
        titles = (single,) if single is not None else ()

    for title in titles:
        if title is None:
            continue
        key = normalize_department_key(getattr(title, "department_code", None), fallback="")
        if key:
            return key
        category = getattr(title, "category", None)
        if category is not None:
            key = normalize_department_key(getattr(category, "department_code", None), fallback="")
            if key:
                return key
            key = normalize_department_key(getattr(category, "code", None), fallback="")
            if key:
                return key
    return fallback


def infer_department_for_work_type(work_type: Any, *, fallback: str = DEPT_OTHER) -> str:
    slug = canonical_work_type(work_type)
    raw = normalize_work_type(work_type)
    return WORK_TYPE_DEFAULT_DEPARTMENT.get(slug) or WORK_TYPE_DEFAULT_DEPARTMENT.get(raw, fallback)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_work_duration(
    minutes: Any,
    *,
    is_admin: bool = False,
    field_label: str = "Duration",
    allow_zero: bool = False,
) -> tuple[int, str | None]:
    """Return ``(minutes, error)``. ``error`` is a user-facing message or None."""
    value = parse_int(minutes, None)
    if value is None:
        return 0, f"{field_label} is not a number."
    if value < 0:
        return 0, f"{field_label} cannot be negative."
    if value == 0:
        if allow_zero:
            return 0, None
        return 0, f"{field_label} must be more than zero."
    limit = MAX_ADMIN_MINUTES if is_admin else MAX_MANUAL_MINUTES
    if value > limit:
        return 0, f"{field_label} cannot exceed {limit // 60} hours."
    return value, None


def validate_work_date(
    value: Any,
    *,
    today: date,
    is_admin: bool = False,
) -> tuple[date | None, str | None]:
    parsed = parse_date(value)
    if parsed is None:
        return None, "Pick a valid work date."
    horizon = MAX_ADMIN_FUTURE_DAYS if is_admin else MAX_FUTURE_DAYS
    if parsed > today + timedelta(days=horizon):
        return None, "Work date is too far in the future."
    return parsed, None


# ---------------------------------------------------------------------------
# Lookup and upsert
# ---------------------------------------------------------------------------


def find_ledger_row(
    *,
    model: Any = None,
    source_type: str | None = None,
    source_id: int | None = None,
    operation_id: str | None = None,
) -> Any | None:
    """The existing row for a source, if any. This is what makes upserts safe."""
    Model = resolve_model(model)
    if Model is None:
        return None
    if source_type and source_id is not None:
        row = Model.query.filter_by(
            source_type=normalize_source_type(source_type), source_id=int(source_id)
        ).first()
        if row is not None:
            return row
    op = (operation_id or "").strip()
    if op:
        return Model.query.filter_by(operation_id=op).first()
    return None


def _apply_fields(row: Any, values: dict[str, Any], *, overwrite: bool = True) -> bool:
    """Set attributes on a ledger row. Returns True when anything changed."""
    changed = False
    for key, value in values.items():
        if value is None and not overwrite:
            continue
        if getattr(row, key, None) != value:
            setattr(row, key, value)
            changed = True
    return changed


def upsert_work_ledger_from_session(
    *,
    db: Any = None,
    session: Any,
    account: Any = None,
    now: datetime | None = None,
    model: Any = None,
    auto_approve: bool = False,
    directory_user: Any = None,
) -> Any | None:
    """Create or refresh the ledger row for an ended dashboard work session.

    Called from the session-end route. Re-ending the same session updates the
    existing row rather than adding a second one.
    """
    Model = resolve_model(model)
    database = resolve_db(db)
    if Model is None or database is None or session is None:
        return None
    if getattr(session, "project_id", None) is None:
        return None

    started_at = getattr(session, "started_at", None)
    ended_at = getattr(session, "ended_at", None)
    now = now or ended_at or started_at or datetime.now()

    actual = minutes_between(started_at, ended_at)
    booking = getattr(session, "booking", None)
    estimated = 0
    if booking is not None:
        estimated = booking_planned_minutes(booking)

    work_date = (started_at or now).date()
    work_type = canonical_work_type(getattr(session, "job_type", None))
    department = infer_department_from_user(
        directory_user or getattr(session, "user", None), fallback=DEPT_EDITORIAL
    )
    if department == DEPT_OTHER:
        department = infer_department_for_work_type(work_type, fallback=DEPT_EDITORIAL)

    row = find_ledger_row(
        model=Model, source_type=SOURCE_WORK_SESSION, source_id=int(session.id)
    )
    created = row is None
    if created:
        row = Model(
            project_id=int(session.project_id),
            source_type=SOURCE_WORK_SESSION,
            source_id=int(session.id),
            work_date=work_date,
            created_at=now,
            created_by_account_id=int(account.id) if account is not None else None,
        )
        database.session.add(row)

    if ended_at is None:
        status = STATUS_STARTED
    else:
        status = STATUS_AUTO_APPROVED if auto_approve else STATUS_SUBMITTED
    # An approver's decision outranks a replayed source event.
    if not created and row.status in (LOCKED_STATUSES | {STATUS_REJECTED}):
        status = row.status

    _apply_fields(
        row,
        {
            "project_id": int(session.project_id),
            "user_id": int(session.user_id) if getattr(session, "user_id", None) else None,
            "account_id": int(account.id) if account is not None else row.account_id,
            "department_key": department,
            "work_type": work_type,
            "work_date": work_date,
            "started_at": started_at,
            "ended_at": ended_at,
            "estimated_minutes": int(estimated),
            "actual_minutes": int(actual),
            "booking_id": (
                int(session.booking_id) if getattr(session, "booking_id", None) else None
            ),
            "work_session_id": int(session.id),
            "title": "Work session",
            "status": status,
            "updated_at": now,
        },
    )
    # Billable tracks actual until somebody overrides it by hand.
    if created or row.billable_minutes in (0, None) or row.status not in LOCKED_STATUSES:
        row.billable_minutes = int(actual)
    return row


def booking_planned_minutes(booking: Any) -> int:
    """Planned minutes for a Booking row (date + start/end wall-clock times)."""
    if booking is None:
        return 0
    booking_date = getattr(booking, "booking_date", None)
    start_time = getattr(booking, "start_time", None)
    end_time = getattr(booking, "end_time", None)
    if booking_date is None or start_time is None or end_time is None:
        return 0
    start = datetime.combine(booking_date, start_time)
    end = datetime.combine(booking_date, end_time)
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 60)


def upsert_work_ledger_from_media_event(
    *,
    db: Any = None,
    model: Any = None,
    project_id: int,
    kind: str,
    task_id: int,
    operation_id: str | None = None,
    phase: str = "started",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    estimated_minutes: int | None = None,
    day_label: str = "",
    shooting_day_id: int | None = None,
    user_id: int | None = None,
    account: Any = None,
    now: datetime | None = None,
    auto_approve: bool = True,
) -> Any | None:
    """Create or update the Machine Room ledger row behind a copy/convert task.

    ``phase`` is one of ``started``, ``completed``, ``failed``, ``cancelled``.
    The row is keyed by ``(source_type, task_id)`` so the start event and the
    terminal event land on the same row.
    """
    Model = resolve_model(model)
    database = resolve_db(db)
    if Model is None or database is None or project_id is None:
        return None

    is_convert = str(kind or "").strip().lower() == "convert"
    source_type = SOURCE_MEDIA_CONVERT if is_convert else SOURCE_MEDIA_COPY
    work_type = "convert_transcode" if is_convert else "copy_media"
    title = "Convert / Transcode" if is_convert else "Copy media"
    now = now or completed_at or started_at or datetime.now()

    row = find_ledger_row(
        model=Model,
        source_type=source_type,
        source_id=int(task_id),
        operation_id=operation_id,
    )
    created = row is None
    if created:
        row = Model(
            project_id=int(project_id),
            source_type=source_type,
            source_id=int(task_id),
            work_date=(started_at or now).date(),
            created_at=now,
            created_by_account_id=int(account.id) if account is not None else None,
        )
        database.session.add(row)

    phase_key = str(phase or "started").strip().lower()
    if phase_key == "failed":
        status = STATUS_FAILED
    elif phase_key == "cancelled":
        status = STATUS_CANCELLED
    elif phase_key == "completed":
        status = STATUS_AUTO_APPROVED if auto_approve else STATUS_SUBMITTED
    else:
        status = STATUS_STARTED
    if not created and phase_key == "started" and row.status != STATUS_STARTED:
        # A replayed start event must not reopen a row that already finished.
        status = row.status
    elif not created and row.status in LOCKED_STATUSES and phase_key == "completed":
        status = row.status

    effective_start = started_at or row.started_at
    effective_end = completed_at if phase_key != "started" else row.ended_at
    actual = minutes_between(effective_start, effective_end)
    if phase_key in ("failed", "cancelled"):
        # Aborted machine time is recorded but never billed.
        billable = 0
    else:
        billable = actual

    values: dict[str, Any] = {
        "project_id": int(project_id),
        "department_key": DEPT_MACHINE_ROOM,
        "work_type": work_type,
        "title": title,
        "media_task_id": int(task_id),
        "operation_id": (operation_id or "").strip() or None,
        "started_at": effective_start,
        "ended_at": effective_end,
        "actual_minutes": int(actual),
        "billable_minutes": int(billable),
        "status": status,
        "updated_at": now,
    }
    if effective_start is not None:
        values["work_date"] = effective_start.date()
    if estimated_minutes is not None:
        values["estimated_minutes"] = max(0, int(estimated_minutes))
    if shooting_day_id is not None:
        values["shooting_day_id"] = int(shooting_day_id)
    if user_id is not None:
        values["user_id"] = int(user_id)
    if day_label and not (row.description or ""):
        values["description"] = str(day_label)[:DESCRIPTION_MAX]

    _apply_fields(row, values)
    return row


def create_manual_work_log(
    *,
    db: Any = None,
    model: Any = None,
    project_id: int,
    user_id: int | None,
    account: Any = None,
    created_by_account: Any = None,
    work_date: date,
    department_key: str,
    work_type: str,
    actual_minutes: int,
    billable_minutes: int | None = None,
    estimated_minutes: int = 0,
    title: str = "",
    description: str = "",
    episode_id: int | None = None,
    shooting_day_id: int | None = None,
    scene_id: int | None = None,
    vfx_shot_id: int | None = None,
    status: str = STATUS_SUBMITTED,
    now: datetime | None = None,
) -> Any | None:
    """Insert a manual hours row. Callers validate first; this only writes."""
    Model = resolve_model(model)
    database = resolve_db(db)
    if Model is None or database is None:
        return None
    now = now or datetime.now()
    actual = max(0, int(actual_minutes or 0))
    billable = actual if billable_minutes is None else max(0, int(billable_minutes))
    row = Model(
        project_id=int(project_id),
        user_id=int(user_id) if user_id else None,
        account_id=int(account.id) if account is not None else None,
        department_key=normalize_department_key(department_key, fallback=DEPT_OTHER),
        work_type=canonical_work_type(work_type),
        source_type=SOURCE_MANUAL,
        source_id=None,
        operation_id=None,
        title=(title or "Manual hours")[:TITLE_MAX],
        description=(description or "")[:DESCRIPTION_MAX],
        work_date=work_date,
        started_at=datetime.combine(work_date, time(0, 0)),
        ended_at=None,
        estimated_minutes=max(0, int(estimated_minutes or 0)),
        actual_minutes=actual,
        billable_minutes=billable,
        episode_id=int(episode_id) if episode_id else None,
        shooting_day_id=int(shooting_day_id) if shooting_day_id else None,
        scene_id=int(scene_id) if scene_id else None,
        vfx_shot_id=int(vfx_shot_id) if vfx_shot_id else None,
        status=normalize_status(status),
        created_by_account_id=(
            int(created_by_account.id) if created_by_account is not None else None
        ),
        created_at=now,
        updated_at=now,
    )
    database.session.add(row)
    return row


# ---------------------------------------------------------------------------
# Filters and queries
# ---------------------------------------------------------------------------


def clamp_page_size(raw: Any) -> int:
    value = parse_int(raw, DEFAULT_PAGE_SIZE) or DEFAULT_PAGE_SIZE
    return value if value in PAGE_SIZES else DEFAULT_PAGE_SIZE


# Work log table: clickable sort columns + optional group-by.
SORT_KEYS: tuple[str, ...] = ("date", "user", "department", "work_type", "billable", "status")
GROUP_KEYS: tuple[str, ...] = ("user", "department", "work_type", "billable", "status")
GROUP_LABELS: dict[str, str] = {
    "user": "User",
    "department": "Department",
    "work_type": "Work type",
    "billable": "Billable",
    "status": "Status",
}
DEFAULT_SORT = "date"
DEFAULT_DIR = "desc"


def parse_filters(args: Any) -> dict[str, Any]:
    """Query string -> normalized filter dict. Invalid values fall back silently."""
    def _text(name: str) -> str | None:
        return (args.get(name) or "").strip() or None

    date_from = _text("date_from")
    date_to = _text("date_to")
    if date_from and parse_date(date_from) is None:
        date_from = None
    if date_to and parse_date(date_to) is None:
        date_to = None

    status = _text("status")
    if status and status not in STATUSES:
        status = None
    source_type = _text("source_type")
    if source_type and source_type not in SOURCE_TYPES:
        source_type = None
    department = _text("department_key")
    if department and department not in DEPARTMENT_KEYS:
        department = None

    sort = (_text("sort") or DEFAULT_SORT).lower()
    if sort not in SORT_KEYS:
        sort = DEFAULT_SORT
    direction = (_text("dir") or DEFAULT_DIR).lower()
    if direction not in ("asc", "desc"):
        direction = DEFAULT_DIR
    group_by = (_text("group_by") or "").lower() or None
    if group_by and group_by not in GROUP_KEYS:
        group_by = None

    page = max(1, parse_int(args.get("page"), 1) or 1)
    return {
        "page": page,
        "per_page": clamp_page_size(args.get("per_page")),
        "date_from": date_from,
        "date_to": date_to,
        "user_id": parse_int(args.get("user_id"), None),
        "department_key": department,
        "work_type": _text("work_type"),
        "status": status,
        "source_type": source_type,
        "q": _text("q"),
        "sort": sort,
        "dir": direction,
        "group_by": group_by,
    }


FILTER_KEYS: tuple[str, ...] = (
    "date_from",
    "date_to",
    "user_id",
    "department_key",
    "work_type",
    "status",
    "source_type",
    "q",
    "per_page",
    "sort",
    "dir",
    "group_by",
)


def next_sort_dir(filters: dict[str, Any], column: str) -> str:
    """Toggle direction when re-clicking the active column; else pick a sensible default."""
    if filters.get("sort") == column:
        return "asc" if filters.get("dir") == "desc" else "desc"
    return "desc" if column in ("date", "billable") else "asc"


def sort_aria(filters: dict[str, Any], column: str) -> str | None:
    if filters.get("sort") != column:
        return None
    return "ascending" if filters.get("dir") == "asc" else "descending"


def order_ledger_query(query: Any, Model: Any, filters: dict[str, Any], *, User: Any = None) -> Any:
    """Apply sort + optional group-by ordering. Group key always leads when set."""
    sort = filters.get("sort") or DEFAULT_SORT
    direction = filters.get("dir") or DEFAULT_DIR
    group_by = filters.get("group_by")
    ascending = direction == "asc"

    def _col(column: Any):
        return column.asc() if ascending else column.desc()

    # Outer-join users when sorting or grouping by name so unassigned rows still appear.
    needs_user = sort == "user" or group_by == "user"
    if needs_user and User is not None:
        query = query.outerjoin(User, Model.user_id == User.id)

    clauses: list[Any] = []

    def _append_key(key: str, *, use_sort_dir: bool) -> None:
        nonlocal clauses
        apply = _col if use_sort_dir else (lambda c: c.asc())
        if key == "user":
            if User is not None:
                clauses.append(apply(User.name))
            clauses.append(apply(Model.user_id))
        elif key == "department":
            clauses.append(apply(Model.department_key))
        elif key == "work_type":
            clauses.append(apply(Model.work_type))
        elif key == "billable":
            # Group by billable vs not; sort by minutes within that.
            if not use_sort_dir:
                clauses.append((Model.billable_minutes > 0).desc())
            clauses.append(apply(Model.billable_minutes))
        elif key == "status":
            clauses.append(apply(Model.status))
        elif key == "date":
            clauses.append(apply(Model.work_date))

    if group_by:
        _append_key(group_by, use_sort_dir=False)
        if sort and sort != group_by:
            _append_key(sort, use_sort_dir=True)
        if sort != "date" and group_by != "date":
            clauses.append(Model.work_date.desc())
    else:
        _append_key(sort, use_sort_dir=True)
        if sort != "date":
            clauses.append(Model.work_date.desc())

    clauses.append(Model.id.desc())
    return query.order_by(*clauses)


def display_group_by(filters: dict[str, Any]) -> tuple[str | None, bool]:
    """Group key for the work-log table, plus whether to render group headers.

    Explicit Group by keeps the labeled header rows. Sorting by User /
    Department / Work type / Billable / Status clusters the same way, so we
    still emit Actual + Billable subtotal rows without repeating the header.
    """
    explicit = filters.get("group_by")
    if explicit:
        return str(explicit), True
    sort = str(filters.get("sort") or "")
    if sort in GROUP_KEYS:
        return sort, False
    return None, False


def row_group_meta(row: dict[str, Any], group_by: str | None) -> dict[str, Any] | None:
    """Stable group identity + label for one serialized work-log row."""
    if not group_by:
        return None
    if group_by == "user":
        return {
            "key": f"user:{row.get('user_id') or 0}",
            "label": row.get("user_name") or "Unassigned",
        }
    if group_by == "department":
        return {
            "key": f"department:{row.get('department_key') or 'other'}",
            "label": row.get("department_label") or "Other",
        }
    if group_by == "work_type":
        return {
            "key": f"work_type:{row.get('work_type') or 'other'}",
            "label": row.get("work_type_label") or "Other",
        }
    if group_by == "billable":
        is_billable = int(row.get("billable_minutes") or 0) > 0
        return {
            "key": f"billable:{1 if is_billable else 0}",
            "label": "Billable" if is_billable else "Not billable",
        }
    if group_by == "status":
        return {
            "key": f"status:{row.get('status') or 'submitted'}",
            "label": row.get("status_label") or "Unknown",
        }
    return None


def build_log_display_rows(
    rows: list[dict[str, Any]],
    group_by: str | None,
    *,
    include_headers: bool = True,
) -> list[dict[str, Any]]:
    """Interleave group header + footer summary rows when ``group_by`` is set."""
    if not group_by:
        return [{"kind": "entry", "row": row} for row in rows]

    display: list[dict[str, Any]] = []
    current_key: str | None = None
    pending_meta: dict[str, Any] | None = None
    pending_entries: list[dict[str, Any]] = []

    def _emit() -> None:
        if not pending_meta or not pending_entries:
            return
        actual = sum(int(e["row"].get("actual_minutes") or 0) for e in pending_entries)
        billable = sum(int(e["row"].get("billable_minutes") or 0) for e in pending_entries)
        summary = {
            "key": pending_meta["key"],
            "label": pending_meta["label"],
            "count": len(pending_entries),
            "actual_minutes": actual,
            "billable_minutes": billable,
            "actual_label": format_minutes_label(actual),
            "billable_label": format_minutes_label(billable),
        }
        if include_headers:
            display.append({"kind": "group", **summary})
        display.extend(pending_entries)
        display.append({"kind": "group_summary", **summary})

    for row in rows:
        meta = row_group_meta(row, group_by) or {"key": "other", "label": "Other"}
        entry = {"kind": "entry", "row": row}
        if meta["key"] != current_key:
            _emit()
            current_key = meta["key"]
            pending_meta = meta
            pending_entries = [entry]
        else:
            pending_entries.append(entry)

    _emit()
    return display


def apply_filters(query: Any, Model: Any, filters: dict[str, Any]) -> Any:
    q = query
    date_from = parse_date(filters.get("date_from"))
    if date_from is not None:
        q = q.filter(Model.work_date >= date_from)
    date_to = parse_date(filters.get("date_to"))
    if date_to is not None:
        q = q.filter(Model.work_date <= date_to)
    if filters.get("user_id"):
        q = q.filter(Model.user_id == int(filters["user_id"]))
    if filters.get("department_key"):
        q = q.filter(Model.department_key == filters["department_key"])
    if filters.get("work_type"):
        keys = work_type_equivalent_keys(filters["work_type"])
        if keys:
            q = q.filter(Model.work_type.in_(keys))
        else:
            q = q.filter(Model.work_type == filters["work_type"])
    if filters.get("status"):
        q = q.filter(Model.status == filters["status"])
    if filters.get("source_type"):
        q = q.filter(Model.source_type == filters["source_type"])
    search = filters.get("q")
    if search:
        like = f"%{search}%"
        q = q.filter(Model.title.ilike(like) | Model.description.ilike(like))
    return q


def page_url(
    endpoint: str,
    filters: dict[str, Any],
    *,
    url_for: Callable[..., str],
    project_id: int,
    page: int | None = None,
    **extra: Any,
) -> str:
    params: dict[str, Any] = {"project_id": project_id}
    for key in FILTER_KEYS:
        value = filters.get(key)
        if value not in (None, "", 0):
            params[key] = value
    if page is not None:
        params["page"] = page
    params.update(extra)
    return url_for(endpoint, **params)


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def week_start(day: date) -> date:
    """Saturday-start week, matching the local production week."""
    return day - timedelta(days=(day.weekday() + 2) % 7)


def _bucket_add(bucket: dict[str, dict[str, Any]], key: str, label: str, row: Any) -> None:
    entry = bucket.setdefault(
        key,
        {"key": key, "label": label, "actual_minutes": 0, "billable_minutes": 0, "entries": 0},
    )
    entry["actual_minutes"] += int(row.actual_minutes or 0)
    entry["billable_minutes"] += int(row.billable_minutes or 0)
    entry["entries"] += 1


def summarize_rows(rows: Iterable[Any], *, today: date | None = None) -> dict[str, Any]:
    """Totals and breakdowns over an already-filtered set of ledger rows.

    Only ``COUNTED_STATUSES`` contribute hours; failed, cancelled, rejected and
    in-progress rows are visible in the table but never inflate a total.
    """
    today = today or date.today()
    this_week_start = week_start(today)

    totals = {
        "actual_minutes": 0,
        "billable_minutes": 0,
        "estimated_minutes": 0,
        "this_week_minutes": 0,
        "pending_minutes": 0,
        "pending_count": 0,
        "entries": 0,
        "counted_entries": 0,
    }
    by_department: dict[str, dict[str, Any]] = {}
    by_user: dict[str, dict[str, Any]] = {}
    by_work_type: dict[str, dict[str, Any]] = {}
    by_source_type: dict[str, dict[str, Any]] = {}
    by_week: dict[str, dict[str, Any]] = {}
    by_month: dict[str, dict[str, Any]] = {}

    for row in rows:
        totals["entries"] += 1
        if row.status in PENDING_STATUSES:
            totals["pending_count"] += 1
            totals["pending_minutes"] += int(row.actual_minutes or 0)
        if row.status not in COUNTED_STATUSES:
            continue
        totals["counted_entries"] += 1
        totals["actual_minutes"] += int(row.actual_minutes or 0)
        totals["billable_minutes"] += int(row.billable_minutes or 0)
        totals["estimated_minutes"] += int(row.estimated_minutes or 0)
        if row.work_date and row.work_date >= this_week_start and row.work_date <= today:
            totals["this_week_minutes"] += int(row.actual_minutes or 0)

        _bucket_add(
            by_department, row.department_key or DEPT_OTHER, department_label(row.department_key), row
        )
        user_key = str(row.user_id or 0)
        user_name = _row_user_name(row)
        _bucket_add(by_user, user_key, user_name, row)
        _bucket_add(by_work_type, row.work_type or "other", work_type_label(row.work_type), row)
        _bucket_add(
            by_source_type, row.source_type or SOURCE_OTHER, source_type_label(row.source_type), row
        )
        if row.work_date:
            wk = week_start(row.work_date)
            _bucket_add(by_week, wk.isoformat(), f"Week of {wk.isoformat()}", row)
            month_key = row.work_date.strftime("%Y-%m")
            _bucket_add(by_month, month_key, row.work_date.strftime("%B %Y"), row)

    def _sorted(bucket: dict[str, dict[str, Any]], *, by_key: bool = False) -> list[dict[str, Any]]:
        values = list(bucket.values())
        if by_key:
            return sorted(values, key=lambda e: e["key"])
        return sorted(values, key=lambda e: (-e["actual_minutes"], e["label"]))

    return {
        **totals,
        "by_department": _sorted(by_department),
        "by_user": _sorted(by_user),
        "by_work_type": _sorted(by_work_type),
        "by_source_type": _sorted(by_source_type),
        "by_week": _sorted(by_week, by_key=True),
        "by_month": _sorted(by_month, by_key=True),
    }


def _row_user_name(row: Any) -> str:
    user = getattr(row, "user", None)
    if user is not None:
        name = (getattr(user, "name", "") or "").strip()
        if name:
            return name
        email = (getattr(user, "email", "") or "").strip()
        if email:
            return email
    return "Unassigned"


def summarize_project_work_hours(
    project_id: int,
    filters: dict[str, Any] | None = None,
    *,
    model: Any = None,
    today: date | None = None,
    restrict_user_id: int | None = None,
) -> dict[str, Any]:
    """Summary cards and breakdowns for one project under the current filters."""
    Model = resolve_model(model)
    if Model is None:
        return summarize_rows([], today=today)
    q = Model.query.filter(Model.project_id == int(project_id))
    if restrict_user_id is not None:
        q = q.filter(Model.user_id == int(restrict_user_id))
    if filters:
        q = apply_filters(q, Model, filters)
    return summarize_rows(q.all(), today=today)


def summarize_booked_minutes(
    project_id: int,
    *,
    Booking: Any,
    date_from: Any = None,
    date_to: Any = None,
    user_id: int | None = None,
) -> int:
    """Planned minutes from Booking rows. Booked time is not worked time."""
    if Booking is None:
        return 0
    q = Booking.query.filter(Booking.project_id == int(project_id))
    if hasattr(Booking, "is_active"):
        q = q.filter(Booking.is_active.is_(True))
    start = parse_date(date_from)
    if start is not None:
        q = q.filter(Booking.booking_date >= start)
    end = parse_date(date_to)
    if end is not None:
        q = q.filter(Booking.booking_date <= end)
    if user_id is not None:
        q = q.filter(Booking.booked_for_id == int(user_id))
    return sum(booking_planned_minutes(b) for b in q.all())


def summarize_user_today(
    *,
    model: Any = None,
    user_id: int | None,
    today: date,
    project_id: int | None = None,
) -> dict[str, Any]:
    """Today's actual/billable minutes for one person, for the dashboard widget."""
    empty = {
        "actual_minutes": 0,
        "billable_minutes": 0,
        "entries": 0,
        "pending_count": 0,
        "actual_label": format_minutes_label(0),
        "billable_label": format_minutes_label(0),
    }
    Model = resolve_model(model)
    if Model is None or not user_id:
        return empty
    q = Model.query.filter(Model.user_id == int(user_id), Model.work_date == today)
    if project_id is not None:
        q = q.filter(Model.project_id == int(project_id))
    rows = q.all()
    actual = sum(int(r.actual_minutes or 0) for r in rows if r.status in COUNTED_STATUSES)
    billable = sum(int(r.billable_minutes or 0) for r in rows if r.status in COUNTED_STATUSES)
    return {
        "actual_minutes": actual,
        "billable_minutes": billable,
        "entries": len(rows),
        "pending_count": sum(1 for r in rows if r.status in PENDING_STATUSES),
        "actual_label": format_minutes_label(actual),
        "billable_label": format_minutes_label(billable),
    }


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def linked_entity_label(row: Any) -> str:
    parts: list[str] = []
    if getattr(row, "episode_id", None):
        parts.append(f"Episode #{row.episode_id}")
    if getattr(row, "shooting_day_id", None):
        parts.append(f"Shooting day #{row.shooting_day_id}")
    if getattr(row, "scene_id", None):
        parts.append(f"Scene #{row.scene_id}")
    if getattr(row, "vfx_shot_id", None):
        parts.append(f"VFX shot #{row.vfx_shot_id}")
    if getattr(row, "booking_id", None):
        parts.append(f"Booking #{row.booking_id}")
    if getattr(row, "media_task_id", None):
        parts.append(f"Media task #{row.media_task_id}")
    return " · ".join(parts)


def serialize_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "project_id": int(row.project_id),
        "user_id": row.user_id,
        "user_name": _row_user_name(row),
        "department_key": row.department_key or DEPT_OTHER,
        "department_label": department_label(row.department_key),
        "work_type": row.work_type or "other",
        "work_type_label": work_type_label(row.work_type),
        "source_type": row.source_type or SOURCE_OTHER,
        "source_type_label": source_type_label(row.source_type),
        "title": row.title or "",
        "description": row.description or "",
        "work_date": row.work_date.isoformat() if row.work_date else "",
        "started_at": row.started_at.isoformat(timespec="seconds") if row.started_at else "",
        "ended_at": row.ended_at.isoformat(timespec="seconds") if row.ended_at else "",
        "estimated_minutes": int(row.estimated_minutes or 0),
        "actual_minutes": int(row.actual_minutes or 0),
        "billable_minutes": int(row.billable_minutes or 0),
        "estimated_label": format_minutes_label(row.estimated_minutes),
        "actual_label": format_minutes_label(row.actual_minutes),
        "billable_label": format_minutes_label(row.billable_minutes),
        "status": row.status or STATUS_SUBMITTED,
        "status_label": status_label(row.status),
        "linked_entity": linked_entity_label(row),
        "operation_id": row.operation_id or "",
        "source_id": row.source_id,
        "is_manual": (row.source_type or "") == SOURCE_MANUAL,
        "is_locked": (row.status or "") in LOCKED_STATUSES,
        "is_pending": (row.status or "") in PENDING_STATUSES,
    }


CSV_HEADERS: tuple[str, ...] = (
    "date",
    "project",
    "user",
    "department",
    "work_type",
    "source_type",
    "title",
    "estimated_minutes",
    "actual_minutes",
    "billable_minutes",
    "estimated_hours",
    "actual_hours",
    "billable_hours",
    "status",
    "linked_entity",
    "source_id",
    "operation_id",
)


def csv_row_values(row: Any, *, project_name: str) -> list[Any]:
    return [
        row.work_date.isoformat() if row.work_date else "",
        project_name,
        _row_user_name(row),
        department_label(row.department_key),
        work_type_label(row.work_type),
        source_type_label(row.source_type),
        row.title or "",
        int(row.estimated_minutes or 0),
        int(row.actual_minutes or 0),
        int(row.billable_minutes or 0),
        format_hours_value(row.estimated_minutes),
        format_hours_value(row.actual_minutes),
        format_hours_value(row.billable_minutes),
        status_label(row.status),
        linked_entity_label(row),
        row.source_id if row.source_id is not None else "",
        row.operation_id or "",
    ]


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


def backfill_from_sessions(
    *,
    db: Any,
    model: Any = None,
    WorkSession: Any,
    now: datetime | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Create ledger rows for ended sessions that predate the ledger."""
    Model = resolve_model(model)
    report = {"sessions_scanned": 0, "session_rows_created": 0, "skipped_duplicates": 0, "errors": 0}
    if Model is None or WorkSession is None:
        return report
    q = WorkSession.query.filter(WorkSession.ended_at.isnot(None)).order_by(WorkSession.id.asc())
    if limit:
        q = q.limit(int(limit))
    for sess in q.all():
        report["sessions_scanned"] += 1
        try:
            existing = find_ledger_row(
                model=Model, source_type=SOURCE_WORK_SESSION, source_id=int(sess.id)
            )
            if existing is not None:
                report["skipped_duplicates"] += 1
                continue
            created = upsert_work_ledger_from_session(
                db=db, session=sess, now=now or sess.ended_at, model=Model
            )
            if created is not None:
                report["session_rows_created"] += 1
        except Exception:
            report["errors"] += 1
            db.session.rollback()
    return report


_MEDIA_EVENT_KIND = {
    "media.copy.completed": ("copy", "completed"),
    "media.copy.failed": ("copy", "failed"),
    "media.copy.cancelled": ("copy", "cancelled"),
    "media.convert.completed": ("convert", "completed"),
    "media.convert.failed": ("convert", "failed"),
    "media.convert.cancelled": ("convert", "cancelled"),
}


def backfill_from_activity_log(
    *,
    db: Any,
    model: Any = None,
    ProjectActivityLog: Any,
    loads_json: Callable[[Any, Any], Any],
    now: datetime | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Create Machine Room ledger rows from historic media log events."""
    Model = resolve_model(model)
    report = {"media_events_scanned": 0, "media_rows_created": 0, "skipped_duplicates": 0, "errors": 0}
    if Model is None or ProjectActivityLog is None:
        return report
    q = (
        ProjectActivityLog.query.filter(
            ProjectActivityLog.event_type.in_(tuple(_MEDIA_EVENT_KIND.keys()))
        )
        .order_by(ProjectActivityLog.id.asc())
    )
    if limit:
        q = q.limit(int(limit))
    for log_row in q.all():
        report["media_events_scanned"] += 1
        try:
            kind, phase = _MEDIA_EVENT_KIND[log_row.event_type]
            task_id = log_row.entity_id
            if not task_id:
                continue
            existing = find_ledger_row(
                model=Model,
                source_type=SOURCE_MEDIA_CONVERT if kind == "convert" else SOURCE_MEDIA_COPY,
                source_id=int(task_id),
                operation_id=log_row.operation_id or None,
            )
            if existing is not None:
                report["skipped_duplicates"] += 1
                continue
            meta = loads_json(getattr(log_row, "metadata_json", None), {}) or {}
            created = upsert_work_ledger_from_media_event(
                db=db,
                model=Model,
                project_id=int(log_row.project_id),
                kind=kind,
                task_id=int(task_id),
                operation_id=log_row.operation_id or None,
                phase=phase,
                started_at=log_row.started_at,
                completed_at=log_row.completed_at or log_row.occurred_at,
                estimated_minutes=parse_int(meta.get("estimated_minutes"), None),
                day_label=str(meta.get("shooting_day_label") or ""),
                shooting_day_id=parse_int(meta.get("shooting_day_id"), None),
                user_id=log_row.user_id,
                now=now,
            )
            if created is not None:
                report["media_rows_created"] += 1
        except Exception:
            report["errors"] += 1
            db.session.rollback()
    return report


def ensure_project_media_ledger(
    *,
    db: Any,
    project_id: int,
    model: Any = None,
    ProjectActivityLog: Any,
    loads_json: Callable[[Any, Any], Any],
    now: datetime | None = None,
) -> dict[str, int]:
    """Create missing Copy/Convert ledger rows for one project from its activity log."""
    Model = resolve_model(model)
    report = {
        "media_events_scanned": 0,
        "media_rows_created": 0,
        "skipped_duplicates": 0,
        "errors": 0,
    }
    if Model is None or ProjectActivityLog is None or project_id is None:
        return report
    q = (
        ProjectActivityLog.query.filter(
            ProjectActivityLog.project_id == int(project_id),
            ProjectActivityLog.event_type.in_(tuple(_MEDIA_EVENT_KIND.keys())),
        ).order_by(ProjectActivityLog.id.asc())
    )
    for log_row in q.all():
        report["media_events_scanned"] += 1
        try:
            kind, phase = _MEDIA_EVENT_KIND[log_row.event_type]
            task_id = log_row.entity_id
            if not task_id:
                continue
            existing = find_ledger_row(
                model=Model,
                source_type=SOURCE_MEDIA_CONVERT if kind == "convert" else SOURCE_MEDIA_COPY,
                source_id=int(task_id),
                operation_id=log_row.operation_id or None,
            )
            if existing is not None:
                report["skipped_duplicates"] += 1
                continue
            meta = loads_json(getattr(log_row, "metadata_json", None), {}) or {}
            created = upsert_work_ledger_from_media_event(
                db=db,
                model=Model,
                project_id=int(log_row.project_id),
                kind=kind,
                task_id=int(task_id),
                operation_id=log_row.operation_id or None,
                phase=phase,
                started_at=log_row.started_at,
                completed_at=log_row.completed_at or log_row.occurred_at,
                estimated_minutes=parse_int(meta.get("estimated_minutes"), None),
                day_label=str(meta.get("shooting_day_label") or ""),
                shooting_day_id=parse_int(meta.get("shooting_day_id"), None),
                user_id=log_row.user_id,
                now=now,
            )
            if created is not None:
                report["media_rows_created"] += 1
        except Exception:
            report["errors"] += 1
            db.session.rollback()
    return report


def list_media_hours(
    *,
    project_id: int,
    model: Any = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Return Copy / Convert ledger rows and totals for the Machine Room strip."""
    Model = resolve_model(model)
    empty = {
        "rows": [],
        "copy_minutes": 0,
        "convert_minutes": 0,
        "total_minutes": 0,
        "copy_label": format_minutes_label(0),
        "convert_label": format_minutes_label(0),
        "total_label": format_minutes_label(0),
    }
    if Model is None or project_id is None:
        return empty
    q = Model.query.filter(
        Model.project_id == int(project_id),
        Model.source_type.in_((SOURCE_MEDIA_COPY, SOURCE_MEDIA_CONVERT)),
        Model.status.in_(
            tuple(COUNTED_STATUSES | APPROVED_STATUSES | {STATUS_STARTED})
        ),
    )
    if date_from is not None:
        q = q.filter(Model.work_date >= date_from)
    if date_to is not None:
        q = q.filter(Model.work_date <= date_to)
    rows = q.order_by(Model.work_date.asc(), Model.id.asc()).limit(100).all()
    copy_minutes = 0
    convert_minutes = 0
    serialized = []
    for row in rows:
        payload = serialize_row(row)
        serialized.append(payload)
        mins = int(row.actual_minutes or 0)
        if row.source_type == SOURCE_MEDIA_CONVERT:
            convert_minutes += mins
        else:
            copy_minutes += mins
    total = copy_minutes + convert_minutes
    return {
        "rows": serialized,
        "copy_minutes": copy_minutes,
        "convert_minutes": convert_minutes,
        "total_minutes": total,
        "copy_label": format_minutes_label(copy_minutes),
        "convert_label": format_minutes_label(convert_minutes),
        "total_label": format_minutes_label(total),
    }