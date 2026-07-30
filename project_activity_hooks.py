"""Thin helpers for emitting Project Log Book events from routes.

All helpers call ``log_project_activity`` via ``current_app.extensions`` and are
best-effort (never raise).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import current_app

import project_activity_events as pae
import project_activity_service as pas


def _log(**kwargs: Any) -> Any | None:
    try:
        fn = (current_app.extensions.get("project_activity") or {}).get("log")
        if not callable(fn):
            return None
        return fn(**kwargs)
    except Exception:
        try:
            current_app.logger.exception("project_activity hook failed")
        except Exception:
            pass
        return None


def log_shooting_day_created(day: Any, *, source: str = "production") -> None:
    label = pas.shooting_day_label(day)
    _log(
        project_id=int(day.project_id),
        event_type=pae.SHOOTING_DAY_CREATED,
        module=pae.MODULE_SHOOTING,
        action="created",
        entity_type="shooting_day",
        entity_id=int(day.id),
        entity_label=label,
        metadata={
            "source": source,
            **pas.shooting_day_snapshot(day),
            "shooting_day_id": int(day.id),
            "shooting_day_label": label,
        },
        status=pae.STATUS_COMPLETED,
    )


def log_shooting_day_updated(day: Any, before: dict[str, Any], after: dict[str, Any]) -> None:
    changes = pas.build_change_set(before, after, pas.SHOOTING_DAY_TRACKED_FIELDS)
    if not changes:
        return
    label = pas.shooting_day_label(day)
    _log(
        project_id=int(day.project_id),
        event_type=pae.SHOOTING_DAY_UPDATED,
        module=pae.MODULE_SHOOTING,
        action="updated",
        entity_type="shooting_day",
        entity_id=int(day.id),
        entity_label=label,
        changes=changes,
        metadata={"shooting_day_id": int(day.id), "shooting_day_label": label},
        status=pae.STATUS_COMPLETED,
    )


def log_shooting_day_deleted(day: Any) -> None:
    label = pas.shooting_day_label(day)
    snap = pas.shooting_day_snapshot(day)
    _log(
        project_id=int(day.project_id),
        event_type=pae.SHOOTING_DAY_DELETED,
        module=pae.MODULE_SHOOTING,
        action="deleted",
        entity_type="shooting_day",
        entity_id=int(day.id),
        entity_label=label,
        metadata={**snap, "shooting_day_id": int(day.id), "shooting_day_label": label},
        status=pae.STATUS_COMPLETED,
    )


def _pick_shooting_item_event(changes: dict[str, Any], item_type: str) -> str:
    if "shooting_item_type" in changes:
        new_t = str((changes["shooting_item_type"] or {}).get("new") or "").lower()
        if "reshoot" in new_t:
            return pae.SHOOTING_ITEM_CONVERTED_TO_RESHOOT
    status_keys = {"status", "sync_done", "first_edit_done"}
    ep_keys = {"episode_number", "is_episode_unassigned", "is_establishing_shots_pool"}
    keys = set(changes.keys())
    if keys & status_keys and not (keys - status_keys - {"notes"}):
        return pae.SHOOTING_ITEM_STATUS_CHANGED
    if keys & ep_keys and not (keys - ep_keys - {"notes"}):
        return pae.SHOOTING_ITEM_EPISODE_CHANGED
    return pae.SHOOTING_ITEM_UPDATED


def log_shooting_item_created(link: Any, day: Any | None = None) -> None:
    day = day or getattr(link, "shooting_day", None)
    label = pas.shooting_item_label(link)
    day_id = int(getattr(link, "shooting_day_id", 0) or 0)
    day_label = pas.shooting_day_label(day) if day is not None else f"Shooting Day {day_id}"
    project_id = int(getattr(day, "project_id", 0) or 0) if day is not None else 0
    if not project_id:
        return
    meta = {
        **pas.shooting_item_snapshot(link),
        "shooting_day_id": day_id,
        "shooting_day_label": day_label,
        "duration": pas.format_duration_label(
            int(getattr(link, "duration_seconds", 0) or 0)
        ),
    }
    _log(
        project_id=project_id,
        event_type=pae.SHOOTING_ITEM_CREATED,
        module=pae.MODULE_SHOOTING,
        action="created",
        entity_type="shooting_item",
        entity_id=int(link.id),
        entity_label=label,
        metadata=meta,
        status=pae.STATUS_COMPLETED,
    )


def log_shooting_item_updated(
    link: Any,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    day: Any | None = None,
) -> None:
    changes = pas.build_change_set(before, after, pas.SHOOTING_ITEM_TRACKED_FIELDS)
    if not changes:
        return
    day = day or getattr(link, "shooting_day", None)
    project_id = int(getattr(day, "project_id", 0) or 0) if day is not None else 0
    if not project_id:
        return
    label = pas.shooting_item_label(link)
    event = _pick_shooting_item_event(changes, str(after.get("shooting_item_type") or ""))
    action = pae.action_for_event(event)
    _log(
        project_id=project_id,
        event_type=event,
        module=pae.MODULE_SHOOTING,
        action=action,
        entity_type="shooting_item",
        entity_id=int(link.id),
        entity_label=label,
        changes=changes,
        metadata={
            "shooting_day_id": int(getattr(link, "shooting_day_id", 0) or 0),
            "shooting_day_label": pas.shooting_day_label(day) if day else "",
        },
        status=pae.STATUS_COMPLETED,
    )


def log_shooting_item_deleted(link: Any, *, project_id: int, day: Any | None = None) -> None:
    day = day or getattr(link, "shooting_day", None)
    label = pas.shooting_item_label(link)
    snap = pas.shooting_item_snapshot(link)
    meta = {
        **snap,
        "shooting_day_id": int(getattr(link, "shooting_day_id", 0) or 0),
        "shooting_day_label": pas.shooting_day_label(day) if day else "",
        "duration": pas.format_duration_label(int(snap.get("duration_seconds") or 0)),
        "item_type": snap.get("shooting_item_type"),
        "scene_number": snap.get("scene_label") or snap.get("scene_number"),
        "episode_id": snap.get("episode_number"),
    }
    _log(
        project_id=int(project_id),
        event_type=pae.SHOOTING_ITEM_DELETED,
        module=pae.MODULE_SHOOTING,
        action="deleted",
        entity_type="shooting_item",
        entity_id=int(link.id),
        entity_label=label,
        metadata=meta,
        status=pae.STATUS_COMPLETED,
    )


def log_booking_event(
    *,
    project_id: int,
    event_type: str,
    booking: Any,
    changes: dict[str, Any] | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    if before is not None and after is not None and changes is None:
        changes = pas.build_change_set(before, after, pas.BOOKING_TRACKED_FIELDS)
        if event_type.endswith(".updated") and not changes:
            return
    label = pas.booking_label(booking)
    snap = after or pas.booking_snapshot(booking)
    _log(
        project_id=int(project_id),
        event_type=event_type,
        module=pae.MODULE_BOOKING,
        action=pae.action_for_event(event_type),
        entity_type="booking",
        entity_id=int(getattr(booking, "id", 0) or 0) or None,
        entity_label=label,
        changes=changes or {},
        metadata={
            "suite_name": snap.get("suite_name"),
            "booked_for_name": snap.get("booked_for_name"),
            "booking_date": snap.get("booking_date"),
            "job_type": snap.get("job_type"),
        },
        status=pae.STATUS_COMPLETED
        if not event_type.endswith(".cancelled")
        else pae.STATUS_CANCELLED,
    )


def log_member_added(project_id: int, *, user_id: int, user_name: str, scope: str | None = None) -> None:
    _log(
        project_id=int(project_id),
        event_type=pae.PROJECT_MEMBER_ADDED,
        module=pae.MODULE_PROJECT,
        action="added",
        entity_type="project_member",
        entity_id=int(user_id),
        entity_label=(user_name or f"User {user_id}")[:255],
        metadata={"assigned_post_scope_code": scope or ""},
        status=pae.STATUS_COMPLETED,
    )


def log_member_updated(
    project_id: int,
    *,
    user_id: int,
    user_name: str,
    changes: dict[str, Any],
) -> None:
    if not changes:
        return
    _log(
        project_id=int(project_id),
        event_type=pae.PROJECT_MEMBER_UPDATED,
        module=pae.MODULE_PROJECT,
        action="updated",
        entity_type="project_member",
        entity_id=int(user_id),
        entity_label=(user_name or f"User {user_id}")[:255],
        changes=changes,
        status=pae.STATUS_COMPLETED,
    )


def log_member_removed(project_id: int, *, user_id: int, user_name: str, scope: str | None = None) -> None:
    _log(
        project_id=int(project_id),
        event_type=pae.PROJECT_MEMBER_REMOVED,
        module=pae.MODULE_PROJECT,
        action="removed",
        entity_type="project_member",
        entity_id=int(user_id),
        entity_label=(user_name or f"User {user_id}")[:255],
        metadata={"assigned_post_scope_code": scope or ""},
        status=pae.STATUS_COMPLETED,
    )


def log_settings_updated(project_id: int, changes: dict[str, Any]) -> None:
    if not changes:
        return
    _log(
        project_id=int(project_id),
        event_type=pae.PROJECT_SETTINGS_UPDATED,
        module=pae.MODULE_PROJECT,
        action="updated",
        entity_type="project",
        entity_id=int(project_id),
        entity_label="Project settings",
        changes=changes,
        status=pae.STATUS_COMPLETED,
    )


def log_media_started(
    *,
    project_id: int,
    kind: str,
    task_id: int,
    day_label: str,
    unit_number: Any = None,
    metadata: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> None:
    is_convert = kind == "convert"
    event = pae.MEDIA_CONVERT_STARTED if is_convert else pae.MEDIA_COPY_STARTED
    label = day_label or "Shooting day"
    meta = {
        "shooting_day_label": label,
        "unit_number": unit_number,
        "task_id": int(task_id),
        **(metadata or {}),
    }
    _log(
        project_id=int(project_id),
        event_type=event,
        module=pae.MODULE_MEDIA,
        action="started",
        entity_type="media_task",
        entity_id=int(task_id),
        entity_label=label,
        metadata=meta,
        operation_id=pas.media_operation_id(task_id),
        started_at=started_at,
        status=pae.STATUS_STARTED,
    )


def log_media_finished(
    *,
    project_id: int,
    kind: str,
    task_id: int,
    day_label: str,
    started_at: datetime | None,
    completed_at: datetime | None,
    outcome: str = "completed",
    metadata: dict[str, Any] | None = None,
    unit_number: Any = None,
) -> None:
    is_convert = kind == "convert"
    if outcome == "cancelled":
        event = pae.MEDIA_CONVERT_CANCELLED if is_convert else pae.MEDIA_COPY_CANCELLED
        status = pae.STATUS_CANCELLED
    elif outcome == "failed":
        event = pae.MEDIA_CONVERT_FAILED if is_convert else pae.MEDIA_COPY_FAILED
        status = pae.STATUS_FAILED
    else:
        event = pae.MEDIA_CONVERT_COMPLETED if is_convert else pae.MEDIA_COPY_COMPLETED
        status = pae.STATUS_COMPLETED
    label = day_label or "Shooting day"
    meta = {
        "shooting_day_label": label,
        "unit_number": unit_number,
        "task_id": int(task_id),
        **(metadata or {}),
    }
    _log(
        project_id=int(project_id),
        event_type=event,
        module=pae.MODULE_MEDIA,
        action=pae.action_for_event(event),
        entity_type="media_task",
        entity_id=int(task_id),
        entity_label=label,
        metadata=meta,
        operation_id=pas.media_operation_id(task_id),
        started_at=started_at,
        completed_at=completed_at,
        status=status,
    )
