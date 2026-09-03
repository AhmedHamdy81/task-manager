"""Central registry of Project Log Book event types (module.entity.action).

Add new event types here before using them in routes. Unvalidated string event
types are rejected by the logging service.
"""

from __future__ import annotations

from typing import Final

# --- Media ---
MEDIA_COPY_STARTED: Final = "media.copy.started"
MEDIA_COPY_COMPLETED: Final = "media.copy.completed"
MEDIA_COPY_FAILED: Final = "media.copy.failed"
MEDIA_COPY_CANCELLED: Final = "media.copy.cancelled"

MEDIA_CONVERT_STARTED: Final = "media.convert.started"
MEDIA_CONVERT_COMPLETED: Final = "media.convert.completed"
MEDIA_CONVERT_FAILED: Final = "media.convert.failed"
MEDIA_CONVERT_CANCELLED: Final = "media.convert.cancelled"

# --- Shooting day ---
SHOOTING_DAY_CREATED: Final = "shooting_day.created"
SHOOTING_DAY_UPDATED: Final = "shooting_day.updated"
SHOOTING_DAY_DELETED: Final = "shooting_day.deleted"

# --- Shooting item ---
SHOOTING_ITEM_CREATED: Final = "shooting_item.created"
SHOOTING_ITEM_UPDATED: Final = "shooting_item.updated"
SHOOTING_ITEM_DELETED: Final = "shooting_item.deleted"
SHOOTING_ITEM_STATUS_CHANGED: Final = "shooting_item.status_changed"
SHOOTING_ITEM_EPISODE_CHANGED: Final = "shooting_item.episode_changed"
SHOOTING_ITEM_CONVERTED_TO_RESHOOT: Final = "shooting_item.converted_to_reshoot"

# --- Booking ---
BOOKING_CREATED: Final = "booking.created"
BOOKING_UPDATED: Final = "booking.updated"
BOOKING_CANCELLED: Final = "booking.cancelled"
BOOKING_DELETED: Final = "booking.deleted"
BOOKING_CONFLICT_OVERRIDDEN: Final = "booking.conflict_overridden"

# --- Project team / settings ---
PROJECT_MEMBER_ADDED: Final = "project.member.added"
PROJECT_MEMBER_UPDATED: Final = "project.member.updated"
PROJECT_MEMBER_REMOVED: Final = "project.member.removed"
PROJECT_SETTINGS_UPDATED: Final = "project.settings.updated"

# --- Work requests ---
REQUEST_CREATED: Final = "request.request.created"
REQUEST_UPDATED: Final = "request.request.updated"
REQUEST_STARTED: Final = "request.request.started"
REQUEST_FINISHED: Final = "request.request.finished"
REQUEST_FAILED: Final = "request.request.failed"
REQUEST_REOPENED: Final = "request.request.reopened"

# Future modules (reserved; registered so Phase 2 can adopt without redesign):
# tasks.task.created, vfx.shot.updated, color.version.uploaded, etc.

ALL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        MEDIA_COPY_STARTED,
        MEDIA_COPY_COMPLETED,
        MEDIA_COPY_FAILED,
        MEDIA_COPY_CANCELLED,
        MEDIA_CONVERT_STARTED,
        MEDIA_CONVERT_COMPLETED,
        MEDIA_CONVERT_FAILED,
        MEDIA_CONVERT_CANCELLED,
        SHOOTING_DAY_CREATED,
        SHOOTING_DAY_UPDATED,
        SHOOTING_DAY_DELETED,
        SHOOTING_ITEM_CREATED,
        SHOOTING_ITEM_UPDATED,
        SHOOTING_ITEM_DELETED,
        SHOOTING_ITEM_STATUS_CHANGED,
        SHOOTING_ITEM_EPISODE_CHANGED,
        SHOOTING_ITEM_CONVERTED_TO_RESHOOT,
        BOOKING_CREATED,
        BOOKING_UPDATED,
        BOOKING_CANCELLED,
        BOOKING_DELETED,
        BOOKING_CONFLICT_OVERRIDDEN,
        PROJECT_MEMBER_ADDED,
        PROJECT_MEMBER_UPDATED,
        PROJECT_MEMBER_REMOVED,
        PROJECT_SETTINGS_UPDATED,
        REQUEST_CREATED,
        REQUEST_UPDATED,
        REQUEST_STARTED,
        REQUEST_FINISHED,
        REQUEST_FAILED,
        REQUEST_REOPENED,
    }
)

MODULE_MEDIA: Final = "media"
MODULE_SHOOTING: Final = "shooting"
MODULE_BOOKING: Final = "booking"
MODULE_PROJECT: Final = "project"
MODULE_REQUESTS: Final = "requests"

MODULE_LABELS: Final[dict[str, str]] = {
    MODULE_MEDIA: "Media",
    MODULE_SHOOTING: "Shooting",
    MODULE_BOOKING: "Booking",
    MODULE_PROJECT: "Team & Settings",
    MODULE_REQUESTS: "Requests",
}

STATUS_STARTED: Final = "started"
STATUS_COMPLETED: Final = "completed"
STATUS_FAILED: Final = "failed"
STATUS_CANCELLED: Final = "cancelled"
STATUS_INFO: Final = "info"

SEVERITY_INFO: Final = "info"
SEVERITY_WARNING: Final = "warning"
SEVERITY_ERROR: Final = "error"
SEVERITY_CRITICAL: Final = "critical"

SOURCE_UI: Final = "ui"
SOURCE_API: Final = "api"
SOURCE_SYSTEM: Final = "system"

# Summary card / filter buckets (not DB modules — UI grouping).
FILTER_BUCKET_ALL: Final = "all"
FILTER_BUCKET_MEDIA: Final = "media"
FILTER_BUCKET_SHOOTING: Final = "shooting"
FILTER_BUCKET_BOOKING: Final = "booking"
FILTER_BUCKET_TEAM: Final = "team"
FILTER_BUCKET_ERRORS: Final = "errors"

FILTER_BUCKET_MODULES: Final[dict[str, tuple[str, ...]]] = {
    FILTER_BUCKET_MEDIA: (MODULE_MEDIA,),
    FILTER_BUCKET_SHOOTING: (MODULE_SHOOTING,),
    FILTER_BUCKET_BOOKING: (MODULE_BOOKING,),
    FILTER_BUCKET_TEAM: (MODULE_PROJECT,),
}


def is_valid_event_type(event_type: str | None) -> bool:
    return bool(event_type) and str(event_type).strip() in ALL_EVENT_TYPES


def module_for_event(event_type: str) -> str:
    """Derive module segment from event_type (first dotted segment)."""
    et = (event_type or "").strip()
    if not et:
        return ""
    return et.split(".", 1)[0]


def action_for_event(event_type: str) -> str:
    et = (event_type or "").strip()
    parts = et.split(".")
    return parts[-1] if parts else ""
