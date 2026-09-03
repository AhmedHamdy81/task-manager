"""Work request (internal Request) catalog, transitions, and query helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from markupsafe import escape
from sqlalchemy import or_

STATUS_PENDING = "pending"
STATUS_STARTED = "started"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"

STATUSES: tuple[str, ...] = (STATUS_PENDING, STATUS_STARTED, STATUS_FINISHED, STATUS_FAILED)

STATUS_LABELS: dict[str, str] = {
    STATUS_PENDING: "Pending",
    STATUS_STARTED: "Started",
    STATUS_FINISHED: "Finished",
    STATUS_FAILED: "Failed",
}

PRIORITIES: tuple[str, ...] = ("low", "medium", "high")

# Stable keys only — never numeric IDs.
REQUEST_TYPES: tuple[tuple[str, str], ...] = (
    ("general", "General"),
    ("machine_room", "Machine Room"),
    ("editorial", "Editorial"),
    ("color", "Color"),
    ("vfx", "VFX"),
    ("sound", "Sound"),
    ("other", "Other"),
)

REQUEST_TYPE_LABELS: dict[str, str] = {key: label for key, label in REQUEST_TYPES}

EVENT_CREATED = "created"
EVENT_STARTED = "started"
EVENT_FINISHED = "finished"
EVENT_FAILED = "failed"
EVENT_REOPENED = "reopened"
EVENT_COMMENTED = "commented"
EVENT_EDITED = "edited"

OPEN_STATUSES: tuple[str, ...] = (STATUS_PENDING, STATUS_STARTED)

# pending→started, pending→failed, started→finished, started→failed
# Reopen is explicit and permission-gated: failed/finished → pending
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_PENDING: frozenset({STATUS_STARTED, STATUS_FAILED}),
    STATUS_STARTED: frozenset({STATUS_FINISHED, STATUS_FAILED}),
    STATUS_FAILED: frozenset({STATUS_PENDING}),
    STATUS_FINISHED: frozenset({STATUS_PENDING}),
}

REOPEN_TARGETS: frozenset[str] = frozenset({STATUS_PENDING})

SORT_KEYS: dict[str, str] = {
    "created": "created_at",
    "updated": "updated_at",
    "title": "title",
    "priority": "priority",
    "status": "status",
}


def request_type_key_set() -> set[str]:
    return {key for key, _ in REQUEST_TYPES}


def normalize_status(raw: str | None) -> str | None:
    key = (raw or "").strip().lower()
    return key if key in STATUSES else None


def normalize_priority(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    return key if key in PRIORITIES else "medium"


def normalize_request_type(raw: str | None) -> str | None:
    key = (raw or "").strip().lower()
    return key if key in request_type_key_set() else None


def parse_optional_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def parse_optional_minutes(raw: Any) -> int | None | str:
    """Return minutes, None if blank, or 'invalid'."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = int(text)
    except (TypeError, ValueError):
        return "invalid"
    if value < 0 or value > 60 * 24 * 14:
        return "invalid"
    return value


def transition_allowed(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def is_reopen(current: str, target: str) -> bool:
    return current in (STATUS_FAILED, STATUS_FINISHED) and target == STATUS_PENDING


def apply_status_transition(
    row: Any,
    *,
    target: str,
    actor_user_id: int | None,
    now: datetime,
    estimated_minutes: int | None = None,
    comment: str = "",
    expected_version: int | None = None,
) -> str | None:
    """Mutate row in-place. Returns an error message, or None on success."""
    current = normalize_status(getattr(row, "status", None)) or ""
    target_n = normalize_status(target)
    if not target_n:
        return "Invalid status."
    if expected_version is not None and int(getattr(row, "version", 0) or 0) != int(expected_version):
        return "This request was updated by someone else. Reload and try again."
    if current == target_n:
        return "That status is already set."
    if not transition_allowed(current, target_n):
        return (
            f"Cannot change a {STATUS_LABELS.get(current, current)} request "
            f"to {STATUS_LABELS.get(target_n, target_n)}."
        )
    comment = (comment or "").strip()
    if target_n == STATUS_FAILED and not comment:
        return "A failure reason is required."

    row.status = target_n
    row.updated_at = now
    row.version = int(getattr(row, "version", 0) or 0) + 1
    row.last_transition_by_id = actor_user_id

    if target_n == STATUS_STARTED:
        row.started_at = now
        row.started_by_id = actor_user_id
        if estimated_minutes is not None:
            row.estimated_duration_minutes = estimated_minutes
        row.finished_at = None
        row.failed_at = None
        row.finished_by_id = None
        row.failed_by_id = None
    elif target_n == STATUS_FINISHED:
        row.finished_at = now
        row.finished_by_id = actor_user_id
        row.failed_at = None
        row.failed_by_id = None
    elif target_n == STATUS_FAILED:
        row.failed_at = now
        row.failed_by_id = actor_user_id
        row.finished_at = None
        row.finished_by_id = None
    elif target_n == STATUS_PENDING:
        row.started_at = None
        row.finished_at = None
        row.failed_at = None
        row.started_by_id = None
        row.finished_by_id = None
        row.failed_by_id = None
        row.estimated_duration_minutes = None
    return None


def event_type_for_status(target: str) -> str:
    return {
        STATUS_STARTED: EVENT_STARTED,
        STATUS_FINISHED: EVENT_FINISHED,
        STATUS_FAILED: EVENT_FAILED,
        STATUS_PENDING: EVENT_REOPENED,
    }.get(target, EVENT_EDITED)


def escaped_plain(text: str | None) -> str:
    return str(escape((text or "").strip()))


def visible_request_query(
    WorkRequest: Any,
    *,
    vis: set[int] | list[int] | None,
    uid: int | None,
    view_all: bool,
):
    q = WorkRequest.query.filter(WorkRequest.archived.is_(False))
    if vis is not None:
        if not vis:
            return q.filter(WorkRequest.id == -1)
        q = q.filter(
            or_(
                WorkRequest.project_id.in_(list(vis)),
                WorkRequest.project_id.is_(None),
            )
        )
    if view_all or uid is None:
        return q
    return q.filter(
        or_(
            WorkRequest.requested_by_id == int(uid),
            WorkRequest.assigned_to_id == int(uid),
        )
    )


def apply_list_filters(
    q,
    WorkRequest: Any,
    *,
    status: str | None,
    project_id: int | None,
    requester_id: int | None,
    assignee_id: int | None,
    priority: str | None,
    search: str,
    request_type: str | None,
):
    if status:
        q = q.filter(WorkRequest.status == status)
    if project_id is not None:
        q = q.filter(WorkRequest.project_id == int(project_id))
    if requester_id is not None:
        q = q.filter(WorkRequest.requested_by_id == int(requester_id))
    if assignee_id is not None:
        q = q.filter(WorkRequest.assigned_to_id == int(assignee_id))
    if priority:
        q = q.filter(WorkRequest.priority == priority)
    if request_type:
        q = q.filter(WorkRequest.request_type == request_type)
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        q = q.filter(
            or_(
                WorkRequest.title.ilike(like),
                WorkRequest.description.ilike(like),
            )
        )
    return q


def sort_clause(WorkRequest: Any, sort: str, direction: str):
    col_name = SORT_KEYS.get(sort, "updated_at")
    col = getattr(WorkRequest, col_name)
    if direction == "asc":
        return col.asc()
    return col.desc()


def count_open_for_dashboard(WorkRequest: Any, vis, uid: int) -> tuple[int, int]:
    base = WorkRequest.query.filter(
        WorkRequest.archived.is_(False),
        WorkRequest.status.in_(OPEN_STATUSES),
    )
    if vis is not None:
        if not vis:
            return 0, 0
        base = base.filter(
            or_(
                WorkRequest.project_id.in_(list(vis)),
                WorkRequest.project_id.is_(None),
            )
        )
    requested = base.filter(WorkRequest.requested_by_id == int(uid)).count()
    to_complete = base.filter(WorkRequest.assigned_to_id == int(uid)).count()
    return int(requested), int(to_complete)


def recipient_user_ids(row: Any, actor_uid: int | None) -> list[int]:
    ids: list[int] = []
    for uid in (getattr(row, "requested_by_id", None), getattr(row, "assigned_to_id", None)):
        if uid is None:
            continue
        i = int(uid)
        if actor_uid is not None and i == int(actor_uid):
            continue
        if i not in ids:
            ids.append(i)
    return ids


def next_actions(status: str) -> list[str]:
    return sorted(ALLOWED_TRANSITIONS.get(status, frozenset()))
