"""Project Activity Log Book service.

Append-only operational audit trail. Logging failures must never abort the
caller’s business transaction — callers should use ``safe_log_project_activity``.

Future archive strategy (not implemented in Phase 1):
- Keep recent activity in ``project_activity_logs``.
- Periodically move rows older than N months into ``project_activity_logs_archive``
  with the same schema (or a compressed summary variant).
- Preserve searchable summaries, entity identifiers, and operation_id links.
- Never silently discard audit records.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

from flask import has_request_context, request, session

import project_activity_events as pae

logger = logging.getLogger(__name__)

SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|cookie|session|"
    r"csrf|private[_-]?key|credential)",
    re.I,
)

TEXT_MAX_LEN = 2_000
SUMMARY_MAX_LEN = 500
ACTOR_NAME_MAX = 200
ENTITY_LABEL_MAX = 255
PAGE_SIZES = (25, 50, 100)
DEFAULT_PAGE_SIZE = 50

# Settings keys that must never appear in changes/metadata.
SETTINGS_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "auth_token",
    }
)

SHOOTING_ITEM_TRACKED_FIELDS = (
    "episode_number",
    "is_episode_unassigned",
    "is_establishing_shots_pool",
    "scene_label",
    "scene_number",
    "duration_seconds",
    "notes",
    "status",
    "sync_done",
    "first_edit_done",
    "needs_vfx",
    "is_critical",
    "shooting_item_type",
    "runtime_selected",
    "reel_number",
)

SHOOTING_DAY_TRACKED_FIELDS = (
    "unit_number",
    "day_name",
    "shooting_date",
    "location",
    "day_note",
)

BOOKING_TRACKED_FIELDS = (
    "edit_suite_id",
    "suite_name",
    "project_id",
    "booked_for_id",
    "booked_for_name",
    "booking_date",
    "start_time",
    "end_time",
    "is_full_day",
    "notes",
    "job_type",
    "is_active",
    "scene_id",
)

PROJECT_SETTINGS_TRACKED_FIELDS = (
    "name",
    "project_type",
    "production_company",
    "production_house",
    "lifecycle_status",
    "priority",
    "number_of_episodes",
    "project_manager_id",
    "needs_offline_editing",
    "needs_online_editing",
    "needs_color",
    "needs_vfx",
    "needs_sound",
    "needs_mastering_delivery",
    "estimated_shooting_days",
    "delivery_frame_rate",
    "delivery_resolution",
    "delivery_color_space",
    "delivery_audio_format",
)


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return str(value)[:TEXT_MAX_LEN]
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if isinstance(value, str):
        return value[:TEXT_MAX_LEN]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="seconds")
    if isinstance(value, timedelta):
        return int(value.total_seconds())
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if SENSITIVE_KEY_RE.search(key):
                continue
            cleaned = _json_safe(v, depth=depth + 1)
            if cleaned is None or cleaned == "" or cleaned == [] or cleaned == {}:
                continue
            out[key] = cleaned
        return out
    if isinstance(value, (list, tuple, set)):
        items = [_json_safe(v, depth=depth + 1) for v in list(value)[:100]]
        return [i for i in items if i is not None and i != "" and i != {}]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)[:TEXT_MAX_LEN]


def dumps_json(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, separators=(",", ":"), default=str)


def loads_json(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default if default is not None else {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default if default is not None else {}


def scrub_dict(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    return _json_safe(data) or {}


def build_change_set(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    tracked_fields: list[str] | tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return only fields that changed: ``{field: {old, new}}``."""
    before = before or {}
    after = after or {}
    keys = list(tracked_fields) if tracked_fields is not None else sorted(
        set(before.keys()) | set(after.keys())
    )
    changes: dict[str, dict[str, Any]] = {}
    for key in keys:
        if SENSITIVE_KEY_RE.search(str(key)) or str(key) in SETTINGS_SENSITIVE_KEYS:
            continue
        old_v = before.get(key)
        new_v = after.get(key)
        old_s = _json_safe(old_v)
        new_s = _json_safe(new_v)
        if old_s == new_s:
            continue
        changes[str(key)] = {"old": old_s, "new": new_s}
    return changes


def format_duration_label(seconds: int | None) -> str:
    if seconds is None:
        return ""
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def shooting_item_snapshot(link: Any) -> dict[str, Any]:
    return {
        "episode_number": int(getattr(link, "episode_number", 0) or 0),
        "is_episode_unassigned": bool(getattr(link, "is_episode_unassigned", False)),
        "is_establishing_shots_pool": bool(getattr(link, "is_establishing_shots_pool", False)),
        "scene_label": (getattr(link, "scene_label", None) or "").strip(),
        "scene_number": int(getattr(link, "scene_number", 0) or 0),
        "duration_seconds": int(
            getattr(link, "duration_seconds", None)
            or getattr(link, "duration", 0)
            or 0
        ),
        "notes": (getattr(link, "notes", None) or "").strip()[:TEXT_MAX_LEN],
        "status": (getattr(link, "status", None) or "").strip(),
        "sync_done": bool(getattr(link, "sync_done", False)),
        "first_edit_done": bool(getattr(link, "first_edit_done", False)),
        "needs_vfx": bool(getattr(link, "needs_vfx", False)),
        "is_critical": bool(getattr(link, "is_critical", False)),
        "shooting_item_type": (getattr(link, "shooting_item_type", None) or "").strip(),
        "runtime_selected": bool(getattr(link, "runtime_selected", False)),
        "reel_number": getattr(link, "reel_number", None),
    }


def shooting_item_label(link: Any) -> str:
    label = (getattr(link, "scene_label", None) or "").strip()
    if not label:
        label = str(int(getattr(link, "scene_number", 0) or 0))
    item_type = (getattr(link, "shooting_item_type", None) or "scene").strip() or "scene"
    if bool(getattr(link, "is_episode_unassigned", False)):
        ep = "Episode X"
    elif bool(getattr(link, "is_establishing_shots_pool", False)):
        ep = "Establishing Shots"
    else:
        ep = f"Episode {int(getattr(link, 'episode_number', 0) or 0):02d}"
    return f"{item_type.replace('_', ' ').title()} {label} ({ep})"


def shooting_day_snapshot(day: Any) -> dict[str, Any]:
    sd = getattr(day, "shooting_date", None)
    return {
        "unit_number": int(getattr(day, "unit_number", 0) or 0),
        "day_name": (getattr(day, "day_name", None) or "").strip(),
        "shooting_date": sd.isoformat() if sd else None,
        "location": (getattr(day, "location", None) or "").strip(),
        "day_note": (getattr(day, "day_note", None) or "").strip()[:TEXT_MAX_LEN],
    }


def shooting_day_label(day: Any) -> str:
    name = (getattr(day, "day_name", None) or "").strip()
    if name:
        return name
    return f"Shooting Day {int(getattr(day, 'id', 0) or 0)}"


def booking_snapshot(b: Any, *, suite_name: str = "", booked_for_name: str = "") -> dict[str, Any]:
    suite = suite_name or (
        getattr(getattr(b, "edit_suite", None), "name", None) or ""
    )
    bf = booked_for_name or (
        (getattr(getattr(b, "booked_for_user", None), "name", None) or "").strip()
    )
    bd = getattr(b, "booking_date", None)
    st = getattr(b, "start_time", None)
    et = getattr(b, "end_time", None)
    return {
        "edit_suite_id": getattr(b, "edit_suite_id", None),
        "suite_name": (suite or "").strip(),
        "project_id": getattr(b, "project_id", None),
        "booked_for_id": getattr(b, "booked_for_id", None),
        "booked_for_name": bf,
        "booking_date": bd.isoformat() if bd else None,
        "start_time": st.isoformat(timespec="seconds") if st else None,
        "end_time": et.isoformat(timespec="seconds") if et else None,
        "is_full_day": bool(getattr(b, "is_full_day", False)),
        "notes": (getattr(b, "notes", None) or "").strip()[:TEXT_MAX_LEN],
        "job_type": (getattr(b, "job_type", None) or "").strip(),
        "is_active": bool(getattr(b, "is_active", True)),
        "scene_id": getattr(b, "scene_id", None),
    }


def booking_label(b: Any, *, suite_name: str = "") -> str:
    suite = suite_name or (getattr(getattr(b, "edit_suite", None), "name", None) or "Room")
    bd = getattr(b, "booking_date", None)
    date_s = bd.isoformat() if bd else ""
    return f"{suite} · {date_s}".strip(" ·")


def project_settings_snapshot(project: Any, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Snapshot tracked settings fields from a project (and optional form data keys)."""
    src = data if data is not None else None
    out: dict[str, Any] = {}
    for key in PROJECT_SETTINGS_TRACKED_FIELDS:
        if src is not None and key in src:
            out[key] = src.get(key)
        else:
            out[key] = getattr(project, key, None)
    return scrub_dict(out)


def build_summary(
    *,
    actor_name: str,
    event_type: str,
    entity_label: str = "",
    action_hint: str = "",
    is_system_event: bool = False,
) -> str:
    actor = (actor_name or ("System" if is_system_event else "Someone")).strip()
    label = (entity_label or "").strip()
    action = (action_hint or pae.action_for_event(event_type) or "updated").strip()

    templates = {
        pae.MEDIA_COPY_STARTED: f"{actor} started media copy" + (f" for {label}" if label else ""),
        pae.MEDIA_COPY_COMPLETED: f"{actor} completed media copy" + (f" for {label}" if label else ""),
        pae.MEDIA_COPY_FAILED: f"{actor} failed media copy" + (f" for {label}" if label else ""),
        pae.MEDIA_COPY_CANCELLED: f"{actor} cancelled media copy" + (f" for {label}" if label else ""),
        pae.MEDIA_CONVERT_STARTED: f"{actor} started media convert" + (f" for {label}" if label else ""),
        pae.MEDIA_CONVERT_COMPLETED: f"{actor} completed media convert" + (f" for {label}" if label else ""),
        pae.MEDIA_CONVERT_FAILED: f"{actor} failed media convert" + (f" for {label}" if label else ""),
        pae.MEDIA_CONVERT_CANCELLED: f"{actor} cancelled media convert" + (f" for {label}" if label else ""),
        pae.SHOOTING_DAY_CREATED: f"{actor} created {label or 'a shooting day'}",
        pae.SHOOTING_DAY_UPDATED: f"{actor} updated {label or 'a shooting day'}",
        pae.SHOOTING_DAY_DELETED: f"{actor} deleted {label or 'a shooting day'}",
        pae.SHOOTING_ITEM_CREATED: f"{actor} added {label or 'a shooting item'}",
        pae.SHOOTING_ITEM_UPDATED: f"{actor} updated {label or 'a shooting item'}",
        pae.SHOOTING_ITEM_DELETED: f"{actor} deleted {label or 'a shooting item'}",
        pae.SHOOTING_ITEM_STATUS_CHANGED: f"{actor} changed status of {label or 'a shooting item'}",
        pae.SHOOTING_ITEM_EPISODE_CHANGED: f"{actor} reassigned episode for {label or 'a shooting item'}",
        pae.SHOOTING_ITEM_CONVERTED_TO_RESHOOT: f"{actor} converted {label or 'a shooting item'} to Reshoot",
        pae.BOOKING_CREATED: f"{actor} created booking" + (f" · {label}" if label else ""),
        pae.BOOKING_UPDATED: f"{actor} updated booking" + (f" · {label}" if label else ""),
        pae.BOOKING_CANCELLED: f"{actor} cancelled booking" + (f" · {label}" if label else ""),
        pae.BOOKING_DELETED: f"{actor} deleted booking" + (f" · {label}" if label else ""),
        pae.BOOKING_CONFLICT_OVERRIDDEN: f"{actor} overrode a booking conflict"
        + (f" · {label}" if label else ""),
        pae.PROJECT_MEMBER_ADDED: f"{actor} added a team member" + (f" · {label}" if label else ""),
        pae.PROJECT_MEMBER_UPDATED: f"{actor} updated a team member" + (f" · {label}" if label else ""),
        pae.PROJECT_MEMBER_REMOVED: f"{actor} removed a team member" + (f" · {label}" if label else ""),
        pae.PROJECT_SETTINGS_UPDATED: f"{actor} updated project settings",
    }
    text = templates.get(event_type) or f"{actor} {action}" + (f" · {label}" if label else "")
    return text[:SUMMARY_MAX_LEN]


def resolve_actor_display_name(user: Any = None, account: Any = None) -> str:
    if user is not None:
        name = (getattr(user, "name", None) or "").strip()
        if name:
            return name[:ACTOR_NAME_MAX]
        email = (getattr(user, "email", None) or "").strip()
        if email:
            return email[:ACTOR_NAME_MAX]
    if account is not None:
        uname = (getattr(account, "username", None) or "").strip()
        if uname:
            return uname[:ACTOR_NAME_MAX]
    return "System"


class ProjectActivityLogger:
    """Append-only writer for ``ProjectActivityLog`` rows."""

    def __init__(
        self,
        *,
        db: Any,
        model: Any,
        now_local: Callable[[], datetime],
        get_directory_user: Callable[[], Any] | None = None,
        get_account: Callable[[], Any] | None = None,
        app_logger: Any | None = None,
    ) -> None:
        self.db = db
        self.Model = model
        self.now_local = now_local
        self.get_directory_user = get_directory_user
        self.get_account = get_account
        self.app_logger = app_logger or logger

    def log(
        self,
        *,
        project_id: int,
        event_type: str,
        module: str | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: int | str | None = None,
        entity_label: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
        changes: dict[str, Any] | None = None,
        status: str | None = None,
        severity: str | None = None,
        operation_id: str | None = None,
        request_id: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_seconds: int | None = None,
        is_system_event: bool = False,
        user_id: int | None = None,
        actor_name: str | None = None,
        source: str | None = None,
        commit: bool = False,
    ) -> Any | None:
        if not pae.is_valid_event_type(event_type):
            self.app_logger.error("project_activity rejected unknown event_type=%r", event_type)
            return None
        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            self.app_logger.error("project_activity missing project_id for %s", event_type)
            return None

        mod = (module or pae.module_for_event(event_type) or "").strip() or "project"
        act = (action or pae.action_for_event(event_type) or "").strip()
        meta = scrub_dict(metadata)
        chg = scrub_dict(changes) if changes else {}

        uid = user_id
        aname = (actor_name or "").strip()
        user = None
        account = None
        if not is_system_event:
            if self.get_directory_user:
                try:
                    user = self.get_directory_user()
                except Exception:
                    user = None
            if self.get_account:
                try:
                    account = self.get_account()
                except Exception:
                    account = None
            if uid is None and user is not None and getattr(user, "id", None) is not None:
                try:
                    uid = int(user.id)
                except (TypeError, ValueError):
                    uid = None
            if not aname:
                aname = resolve_actor_display_name(user, account)
        if not aname:
            aname = "System"

        occurred = self.now_local()
        start = started_at
        end = completed_at
        dur = duration_seconds
        if dur is None and start is not None and end is not None:
            try:
                dur = max(0, int((end - start).total_seconds()))
            except Exception:
                dur = None

        ip_address = None
        user_agent = None
        if has_request_context():
            try:
                ip_address = (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[
                    :64
                ] or None
                user_agent = (request.headers.get("User-Agent") or "")[:255] or None
            except Exception:
                pass
            if not source:
                source = pae.SOURCE_API if request.is_json else pae.SOURCE_UI
        if not source:
            source = pae.SOURCE_SYSTEM if is_system_event else pae.SOURCE_UI

        eid: int | None
        try:
            eid = int(entity_id) if entity_id is not None and str(entity_id).strip() != "" else None
        except (TypeError, ValueError):
            eid = None
            if entity_id is not None:
                meta = {**meta, "entity_id_raw": str(entity_id)[:120]}

        sum_text = (summary or "").strip()
        if not sum_text:
            sum_text = build_summary(
                actor_name=aname,
                event_type=event_type,
                entity_label=entity_label or "",
                is_system_event=is_system_event,
            )

        st = (status or "").strip() or (
            pae.STATUS_FAILED
            if act == "failed"
            else pae.STATUS_CANCELLED
            if act == "cancelled"
            else pae.STATUS_COMPLETED
            if act in ("completed", "created", "deleted", "removed", "added", "updated")
            else pae.STATUS_STARTED
            if act == "started"
            else pae.STATUS_INFO
        )
        sev = (severity or "").strip() or (
            pae.SEVERITY_ERROR
            if st == pae.STATUS_FAILED or act == "failed"
            else pae.SEVERITY_WARNING
            if st == pae.STATUS_CANCELLED
            else pae.SEVERITY_INFO
        )

        row = self.Model(
            project_id=pid,
            user_id=uid,
            actor_name=aname[:ACTOR_NAME_MAX],
            event_type=event_type[:120],
            module=mod[:64],
            action=act[:64],
            entity_type=(entity_type or "")[:64],
            entity_id=eid,
            entity_label=(entity_label or "")[:ENTITY_LABEL_MAX],
            summary=sum_text[:SUMMARY_MAX_LEN],
            metadata_json=dumps_json(meta) if meta else "",
            changes_json=dumps_json(chg) if chg else "",
            occurred_at=occurred,
            started_at=start,
            completed_at=end,
            duration_seconds=dur,
            status=st[:32],
            severity=sev[:32],
            source=(source or "")[:32],
            operation_id=(operation_id or "")[:64],
            request_id=(request_id or "")[:64],
            ip_address=ip_address,
            user_agent=user_agent,
            is_system_event=bool(is_system_event),
        )
        self.db.session.add(row)
        if commit:
            self.db.session.commit()
        else:
            self.db.session.flush()
        return row

    def safe_log(self, **kwargs: Any) -> Any | None:
        """Best-effort log; never raises and never undoes the caller’s unit of work.

        Uses a SAVEPOINT so a failed insert does not roll back pending business rows.
        """
        try:
            with self.db.session.begin_nested():
                return self.log(**kwargs)
        except Exception:
            self.app_logger.exception(
                "project_activity log failed event_type=%s project_id=%s",
                kwargs.get("event_type"),
                kwargs.get("project_id"),
            )
            return None


def can_view_project_log_book(
    account: Any,
    project_id: int,
    *,
    account_can_access_project: Callable[[Any, int], bool],
    account_may_full_control_project: Callable[[Any, int], bool] | None = None,
    account_can_view_project_settings_for: Callable[[Any, int], bool] | None = None,
    account_is_elevated: Callable[[Any], bool] | None = None,
) -> bool:
    """Members with project access who can manage the project or view settings may open Log Book.

    Admins / full-control / settings viewers always qualify when they can access the project.
    Regular members with project access may view the Log Book (non-sensitive details).
    """
    if account is None:
        return False
    if not account_can_access_project(account, int(project_id)):
        return False
    if account_is_elevated and account_is_elevated(account):
        return True
    if account_may_full_control_project and account_may_full_control_project(account, int(project_id)):
        return True
    if account_can_view_project_settings_for and account_can_view_project_settings_for(
        account, int(project_id)
    ):
        return True
    # Project members with access may view operational activity (Phase 1).
    return True


def can_view_sensitive_log_details(
    account: Any,
    project_id: int,
    *,
    account_may_full_control_project: Callable[[Any, int], bool],
    account_is_elevated: Callable[[Any], bool] | None = None,
) -> bool:
    if account is None:
        return False
    if account_is_elevated and account_is_elevated(account):
        return True
    return bool(account_may_full_control_project(account, int(project_id)))


def clamp_page_size(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    if n in PAGE_SIZES:
        return n
    return DEFAULT_PAGE_SIZE


def parse_log_book_filters(args: Any) -> dict[str, Any]:
    def _int(name: str) -> int | None:
        raw = (args.get(name) or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    page = _int("page") or 1
    page = max(1, page)
    per_page = clamp_page_size(args.get("per_page"))
    date_from = (args.get("date_from") or "").strip() or None
    date_to = (args.get("date_to") or "").strip() or None
    for label, val in (("date_from", date_from), ("date_to", date_to)):
        if val:
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                if label == "date_from":
                    date_from = None
                else:
                    date_to = None
    bucket = (args.get("bucket") or args.get("card") or "all").strip().lower() or "all"
    if bucket not in (
        pae.FILTER_BUCKET_ALL,
        pae.FILTER_BUCKET_MEDIA,
        pae.FILTER_BUCKET_SHOOTING,
        pae.FILTER_BUCKET_BOOKING,
        pae.FILTER_BUCKET_TEAM,
        pae.FILTER_BUCKET_ERRORS,
    ):
        bucket = pae.FILTER_BUCKET_ALL
    return {
        "page": page,
        "per_page": per_page,
        "date_from": date_from,
        "date_to": date_to,
        "user_id": _int("user_id"),
        "module": (args.get("module") or "").strip() or None,
        "event_type": (args.get("event_type") or "").strip() or None,
        "action": (args.get("action") or "").strip() or None,
        "status": (args.get("status") or "").strip() or None,
        "entity_type": (args.get("entity_type") or "").strip() or None,
        "shooting_day_id": _int("shooting_day_id"),
        "q": (args.get("q") or "").strip() or None,
        "bucket": bucket,
    }


def apply_log_book_filters(query: Any, Model: Any, filters: dict[str, Any]) -> Any:
    q = query
    if filters.get("date_from"):
        start_dt = datetime.strptime(filters["date_from"], "%Y-%m-%d")
        q = q.filter(Model.occurred_at >= start_dt)
    if filters.get("date_to"):
        end_dt = datetime.strptime(filters["date_to"], "%Y-%m-%d") + timedelta(days=1)
        q = q.filter(Model.occurred_at < end_dt)
    if filters.get("user_id"):
        q = q.filter(Model.user_id == int(filters["user_id"]))
    if filters.get("module"):
        q = q.filter(Model.module == filters["module"])
    if filters.get("event_type"):
        q = q.filter(Model.event_type == filters["event_type"])
    if filters.get("action"):
        q = q.filter(Model.action == filters["action"])
    if filters.get("status"):
        q = q.filter(Model.status == filters["status"])
    if filters.get("entity_type"):
        q = q.filter(Model.entity_type == filters["entity_type"])
    if filters.get("shooting_day_id"):
        # Stored in metadata_json; use LIKE for SQLite without JSON1 dependency.
        needle = f'"shooting_day_id":{int(filters["shooting_day_id"])}'
        q = q.filter(Model.metadata_json.contains(needle))
    bucket = filters.get("bucket") or "all"
    if bucket == pae.FILTER_BUCKET_ERRORS:
        q = q.filter(
            (Model.status == pae.STATUS_FAILED)
            | (Model.severity == pae.SEVERITY_ERROR)
            | (Model.severity == pae.SEVERITY_CRITICAL)
        )
    elif bucket in pae.FILTER_BUCKET_MODULES and not filters.get("module"):
        mods = pae.FILTER_BUCKET_MODULES[bucket]
        q = q.filter(Model.module.in_(mods))
    search = filters.get("q")
    if search:
        like = f"%{search}%"
        q = q.filter(
            (Model.summary.ilike(like))
            | (Model.actor_name.ilike(like))
            | (Model.entity_label.ilike(like))
            | (Model.event_type.ilike(like))
        )
    return q


def compute_summary_counts(query: Any, Model: Any) -> dict[str, int]:
    """Count cards for the current (date/search/etc.) filtered base query."""
    from sqlalchemy import case, func

    rows = query.with_entities(
        func.count(Model.id),
        func.sum(case((Model.module == pae.MODULE_MEDIA, 1), else_=0)),
        func.sum(case((Model.module == pae.MODULE_SHOOTING, 1), else_=0)),
        func.sum(case((Model.module == pae.MODULE_BOOKING, 1), else_=0)),
        func.sum(case((Model.module == pae.MODULE_PROJECT, 1), else_=0)),
        func.sum(
            case(
                (
                    (Model.status == pae.STATUS_FAILED)
                    | (Model.severity == pae.SEVERITY_ERROR)
                    | (Model.severity == pae.SEVERITY_CRITICAL),
                    1,
                ),
                else_=0,
            )
        ),
    ).one()
    return {
        "all": int(rows[0] or 0),
        "media": int(rows[1] or 0),
        "shooting": int(rows[2] or 0),
        "booking": int(rows[3] or 0),
        "team": int(rows[4] or 0),
        "errors": int(rows[5] or 0),
    }


def group_rows_by_date(
    rows: list[Any],
    *,
    today: date,
    format_date_heading: Callable[[date], str] | None = None,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current_key: date | None = None
    bucket: list[Any] = []
    yesterday = today - timedelta(days=1)

    def flush() -> None:
        nonlocal bucket, current_key
        if current_key is None:
            return
        if current_key == today:
            title = "Today"
        elif current_key == yesterday:
            title = "Yesterday"
        elif format_date_heading:
            title = format_date_heading(current_key)
        else:
            title = current_key.strftime("%B %-d, %Y") if hasattr(current_key, "strftime") else str(current_key)
            # %-d is POSIX; fall back for platforms that reject it
            try:
                title = current_key.strftime("%B %-d, %Y")
            except ValueError:
                title = current_key.strftime("%B %d, %Y").replace(" 0", " ")
        groups.append({"date": current_key.isoformat(), "title": title, "rows": list(bucket)})
        bucket = []

    for row in rows:
        occurred = getattr(row, "occurred_at", None)
        d = occurred.date() if isinstance(occurred, datetime) else (occurred or today)
        if current_key is None:
            current_key = d
        if d != current_key:
            flush()
            current_key = d
        bucket.append(row)
    flush()
    return groups


def serialize_log_row(
    row: Any,
    *,
    include_sensitive: bool = False,
    include_details: bool = False,
) -> dict[str, Any]:
    meta = loads_json(getattr(row, "metadata_json", None), {})
    changes = loads_json(getattr(row, "changes_json", None), {})
    if not include_sensitive:
        meta = {k: v for k, v in (meta or {}).items() if not SENSITIVE_KEY_RE.search(str(k))}
        # Strip network forensics for non-privileged viewers
        ip = None
        ua = None
    else:
        ip = getattr(row, "ip_address", None)
        ua = getattr(row, "user_agent", None)

    payload = {
        "id": row.id,
        "project_id": row.project_id,
        "user_id": row.user_id,
        "actor_name": row.actor_name,
        "event_type": row.event_type,
        "module": row.module,
        "module_label": pae.MODULE_LABELS.get(row.module, row.module),
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "entity_label": row.entity_label,
        "summary": row.summary,
        "status": row.status,
        "severity": row.severity,
        "occurred_at": row.occurred_at.isoformat(timespec="seconds") if row.occurred_at else None,
        "started_at": row.started_at.isoformat(timespec="seconds") if row.started_at else None,
        "completed_at": row.completed_at.isoformat(timespec="seconds") if row.completed_at else None,
        "duration_seconds": row.duration_seconds,
        "duration_label": format_duration_label(row.duration_seconds),
        "operation_id": row.operation_id or "",
        "source": row.source or "",
        "is_system_event": bool(row.is_system_event),
    }
    if include_details:
        payload["metadata"] = meta or {}
        payload["changes"] = changes or {}
        if include_sensitive:
            payload["ip_address"] = ip
            payload["user_agent"] = ua
            payload["request_id"] = row.request_id or ""
    return payload


def log_book_page_url(
    endpoint: str,
    filters: dict[str, Any],
    *,
    page: int | None = None,
    url_for: Callable[..., str],
    project_id: int,
    **extra: Any,
) -> str:
    params: dict[str, Any] = {"project_id": project_id}
    for key in (
        "date_from",
        "date_to",
        "user_id",
        "module",
        "event_type",
        "action",
        "status",
        "entity_type",
        "shooting_day_id",
        "q",
        "bucket",
        "per_page",
    ):
        val = filters.get(key)
        if val not in (None, "", "all") or (key == "bucket" and val and val != "all"):
            if key == "bucket" and val == "all":
                continue
            params[key] = val
    params["page"] = page if page is not None else filters.get("page", 1)
    params.update(extra)
    return url_for(endpoint, **params)


def media_operation_id(task_id: int) -> str:
    return f"mr-task-{int(task_id)}"
