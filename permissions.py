"""Centralized access control: pages, actions, role/job-title grants, user overrides."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from types import SimpleNamespace
from typing import Any, Callable

from flask import abort, flash, jsonify, redirect, request, session, url_for
from sqlalchemy import or_

# ---------------------------------------------------------------------------
# Seed catalog
# ---------------------------------------------------------------------------

DEFAULT_ACTIONS: tuple[dict[str, str], ...] = (
    {"key": "view", "name": "View", "description": "Open and read this module"},
    {"key": "view_all", "name": "View all", "description": "View every record regardless of owner"},
    {"key": "create", "name": "Create", "description": "Create new records"},
    {"key": "create_all", "name": "Create for anyone", "description": "Create records on behalf of other users"},
    {"key": "edit", "name": "Edit", "description": "Edit any record in this module"},
    {"key": "edit_own", "name": "Edit own", "description": "Edit records owned by the user"},
    {"key": "edit_all", "name": "Edit all", "description": "Edit any record regardless of owner"},
    {"key": "delete", "name": "Delete", "description": "Delete any record"},
    {"key": "delete_own", "name": "Delete own", "description": "Delete records owned by the user"},
    {"key": "delete_all", "name": "Delete all", "description": "Delete any record regardless of owner"},
    {"key": "upload", "name": "Upload", "description": "Upload files or media"},
    {"key": "download", "name": "Download", "description": "Download or export files"},
    {"key": "approve", "name": "Approve", "description": "Approve workflow items"},
    {"key": "reject", "name": "Reject", "description": "Reject workflow items"},
    {"key": "cancel", "name": "Cancel", "description": "Cancel workflow items"},
    {"key": "assign", "name": "Assign", "description": "Assign people or ownership"},
    {"key": "export", "name": "Export", "description": "Export data or documents"},
    {"key": "archive", "name": "Archive", "description": "Archive records"},
    {"key": "manage_settings", "name": "Manage settings", "description": "Change module settings"},
    {"key": "manage_users", "name": "Manage users", "description": "Create and manage user accounts"},
    {"key": "manage_permissions", "name": "Manage permissions", "description": "Configure access control"},
    {"key": "manage_updates", "name": "Manage updates", "description": "Publish product updates"},
    {"key": "test", "name": "Test", "description": "Preview or send test notifications"},
    {"key": "audit", "name": "Audit", "description": "View audit history"},
    {"key": "restore_defaults", "name": "Restore defaults", "description": "Restore default configuration"},
    {"key": "start_copy", "name": "Start copy", "description": "Start machine-room copy tasks"},
    {"key": "manage_hdd", "name": "Manage HDD", "description": "Manage hard disks in machine room"},
    {"key": "send_to_department", "name": "Send to department", "description": "Send VFX shots to department"},
    {"key": "send_to_color_department", "name": "Send to color department", "description": "Send episodes to Color Department"},
    {"key": "export_pdf", "name": "Export PDF", "description": "Export VFX PDF reports"},
    {"key": "create_client_review", "name": "Create client review", "description": "Create client review links"},
    {"key": "create_shot", "name": "Create shot", "description": "Create VFX shots"},
    {"key": "edit_shot", "name": "Edit shot", "description": "Edit VFX shots"},
    {"key": "delete_shot", "name": "Delete shot", "description": "Delete VFX shots"},
    {"key": "edit_status", "name": "Edit status", "description": "Change workflow status"},
    {"key": "upload_version", "name": "Upload version", "description": "Upload VFX versions"},
    {"key": "deliver", "name": "Deliver", "description": "Mark items as delivered"},
    {"key": "manage_departments", "name": "Manage departments", "description": "Manage editorial department routing"},
    {"key": "upload_versions", "name": "Upload versions", "description": "Upload editorial department versions"},
    {"key": "link_scenes", "name": "Link scenes", "description": "Link production scenes to editing items"},
    {"key": "add_notes", "name": "Add notes", "description": "Add editorial review notes"},
    {"key": "scan", "name": "Scan", "description": "Scan music library mounts"},
    {"key": "mount", "name": "Mount", "description": "Add music library mounts"},
    {"key": "add_to_project", "name": "Add to project", "description": "Link music to projects"},
    {"key": "manage_roles", "name": "Manage roles", "description": "Change user roles"},
    {"key": "manage_job_titles", "name": "Manage job titles", "description": "Manage directory job titles"},
    {"key": "create_link", "name": "Create link", "description": "Create share links"},
    {"key": "disable_link", "name": "Disable link", "description": "Disable share links"},
    {"key": "export_comments", "name": "Export comments", "description": "Export review comments"},
    {"key": "upload_episode_version", "name": "Upload episode version", "description": "Upload full episode review cuts"},
    {"key": "upload_scene_version", "name": "Upload scene version", "description": "Upload individual scene review cuts"},
    {"key": "edit_notes", "name": "Edit notes", "description": "Add or edit episode notes"},
    {"key": "delete_version", "name": "Delete version", "description": "Delete episode or scene versions"},
    {"key": "approve_version", "name": "Approve version", "description": "Approve episode or scene versions"},
    {"key": "download_original", "name": "Download original", "description": "Download original media files"},
)

DEFAULT_PAGES: tuple[dict[str, str | bool], ...] = (
    {"key": "dashboard", "name": "Dashboard", "description": "Home overview", "route_pattern": "/", "module": "core"},
    {"key": "industry_radar", "name": "Industry Radar", "description": "Cinema industry news feed", "route_pattern": "/industry-radar", "module": "core"},
    {"key": "criticals", "name": "Criticals", "description": "Critical alerts list", "route_pattern": "/criticals", "module": "core"},
    {"key": "projects", "name": "Projects", "description": "Project list and management", "route_pattern": "/projects", "module": "production"},
    {"key": "project_detail", "name": "Project detail", "description": "Single project pages", "route_pattern": "/projects/", "module": "production"},
    {"key": "tasks", "name": "Tasks", "description": "Task list and workflow", "route_pattern": "/tasks", "module": "production"},
    {"key": "requests", "name": "Requests", "description": "Internal request inbox and workflow", "route_pattern": "/requests", "module": "production"},
    {"key": "action_board", "name": "Action Board", "description": "Unified notes, TO DOs, and hybrid action items", "route_pattern": "/actions", "module": "production"},
    {"key": "todos", "name": "TO DO", "description": "Personal and project TO DO items (legacy)", "route_pattern": "/todos", "module": "production"},
    {"key": "sticky_notes", "name": "Sticky Notes", "description": "Dashboard sticky notes (legacy)", "route_pattern": "/sticky-notes", "module": "production"},
    {"key": "booking", "name": "Booking", "description": "Edit suite booking", "route_pattern": "/booking", "module": "production"},
    {"key": "machine_room", "name": "Machine room", "description": "Machine room HDD and copy workflow", "route_pattern": "/machine", "module": "machine_room"},
    {"key": "vfx_editor", "name": "VFX Editor", "description": "Editorial VFX authoring", "route_pattern": "/projects/", "module": "vfx"},
    {"key": "vfx_department", "name": "VFX Department", "description": "In-house VFX pipeline", "route_pattern": "/vfx-department", "module": "vfx"},
    {"key": "color_department", "name": "Color Department", "description": "Color grading pipeline", "route_pattern": "/color-department", "module": "color"},
    {"key": "color_overview", "name": "Color overview", "description": "Project color grading overview", "route_pattern": "/projects/", "module": "color"},
    {"key": "client_review", "name": "Client review", "description": "Client review link management", "route_pattern": "/projects/", "module": "vfx"},
    {"key": "music_library", "name": "Audio Library", "description": "Audio library sources, Music and SFX folders", "route_pattern": "/music-library", "module": "media"},
    {"key": "users", "name": "Users", "description": "User directory and accounts", "route_pattern": "/users", "module": "admin"},
    {"key": "approval_center", "name": "Approval Center", "description": "Generic workflow approval queue and request history", "route_pattern": "/admin/approvals", "module": "admin"},
    {"key": "control_panel", "name": "Task management", "description": "System configuration", "route_pattern": "/control", "module": "admin"},
    {"key": "task_log", "name": "Task Log", "description": "Admin audit of all tasks", "route_pattern": "/admin/task-log", "module": "admin"},
    {"key": "notification_log", "name": "Notification log", "description": "Audit trail of sent notifications", "route_pattern": "/admin/notification-log", "module": "admin"},
    {"key": "updates", "name": "Updates", "description": "Product updates feed", "route_pattern": "/updates", "module": "admin"},
    {"key": "notification_management", "name": "Notification Management", "description": "Configure notification rules and recipients", "route_pattern": "/admin/notification-management", "module": "admin"},
    {"key": "producer_hunt", "name": "Producer Hunt", "description": "Entertainment mini-game", "route_pattern": "/producer-hunt", "module": "fun"},
    {"key": "profile", "name": "Profile", "description": "User profile settings", "route_pattern": "/profile", "module": "core"},
    {"key": "episode_detail", "name": "Episode detail", "description": "Episode production hub — scenes, VFX, versions", "route_pattern": "/projects/", "module": "production"},
    {"key": "editing_items", "name": "Editing Items", "description": "Editorial pipeline — episodes, reels, deliverables", "route_pattern": "/projects/", "module": "production"},
    {"key": "working_hours", "name": "Working Hours", "description": "Project working hours ledger — actual, billable, and booked time", "route_pattern": "/projects/", "module": "production"},
)

# More specific path rules evaluated before generic route_pattern prefix match.
PATH_PAGE_RULES: tuple[tuple[str, str], ...] = (
    ("/vfx-department", "vfx_department"),
    ("/color-department", "color_department"),
    ("/color", "color_department"),
    ("/music-library", "music_library"),
    ("/audio-library", "music_library"),
    ("/machine-room", "machine_room"),
    ("/machine/", "machine_room"),
    ("/machine/project", "machine_room"),
    ("/booking", "booking"),
    ("/criticals", "criticals"),
    ("/industry-radar", "industry_radar"),
    ("/users", "users"),
    ("/admin/approvals", "approval_center"),
    ("/control", "control_panel"),
    ("/control/access-control", "control_panel"),
    ("/admin/access-control", "control_panel"),
    ("/admin/api/permissions", "control_panel"),
    ("/admin/task-log", "task_log"),
    ("/admin/notification-log", "notification_log"),
    ("/updates", "updates"),
    ("/producer-hunt", "producer_hunt"),
    ("/profile", "profile"),
    ("/tasks", "tasks"),
    ("/requests", "requests"),
    ("/actions", "action_board"),
    ("/todos", "todos"),
    ("/sticky-notes", "sticky_notes"),
    ("/projects", "projects"),
)

VFX_EDITOR_PATH_MARKERS = ("/vfx", "/vfx/api", "/vfx-department")
VFX_EDITOR_ONLY_MARKERS = ("/projects/", "/vfx")

# Guest accounts use role=guest plus guest_access_level; permissions resolve via these keys.
GUEST_ROLE_VIEWER = "guest_viewer"
GUEST_ROLE_REVIEWER = "guest_reviewer"
GUEST_ROLE_APPROVER = "guest_approver"

_GUEST_VIEWER_PAGES: dict[str, tuple[str, ...]] = {
    "dashboard": ("view",),
    "projects": ("view",),
    "project_detail": ("view",),
    "editing_items": ("view",),
    "episode_detail": ("view",),
    "color_overview": ("view",),
    "vfx_editor": ("view",),
    "profile": ("view", "edit"),
}

_GUEST_REVIEWER_EXTRA: dict[str, tuple[str, ...]] = {
    "editing_items": ("add_notes",),
    "episode_detail": ("edit_notes", "download_original"),
    "color_overview": ("add_notes",),
    "vfx_editor": ("add_notes",),
}

_GUEST_APPROVER_EXTRA: dict[str, tuple[str, ...]] = {
    "editing_items": ("approve",),
    "episode_detail": ("approve_version",),
    "color_overview": ("approve",),
    "vfx_editor": ("approve",),
}


def _merge_guest_pages(
    base: dict[str, tuple[str, ...]], *extras: dict[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    out: dict[str, set[str]] = {k: set(v) for k, v in base.items()}
    for extra in extras:
        for page_key, actions in extra.items():
            out.setdefault(page_key, set()).update(actions)
    return {k: tuple(sorted(v)) for k, v in out.items()}


ROLE_SEED: dict[str, dict[str, tuple[str, ...]]] = {
    "super_user": {
        "dashboard": ("view",),
        "industry_radar": ("view",),
        "criticals": ("view",),
        "projects": ("view", "create", "edit"),
        "project_detail": ("view", "edit"),
        "episode_detail": (
            "view",
            "upload_episode_version",
            "upload_scene_version",
            "edit_notes",
            "delete_version",
            "approve_version",
            "download_original",
        ),
        "tasks": ("view", "create", "edit", "delete"),
        "requests": ("view", "create", "edit", "delete", "assign", "edit_status", "view_all"),
        "action_board": ("view", "create", "edit", "delete"),
        "todos": ("view", "create", "edit", "delete"),
        "sticky_notes": ("view", "create", "edit", "delete"),
        "booking": ("view", "create", "edit", "delete_own", "edit_own", "edit_all", "delete_all"),
        "machine_room": ("view", "edit", "create", "start_copy", "manage_hdd", "scan"),
        "vfx_editor": ("view", "create_shot", "edit_shot", "upload", "send_to_department", "export_pdf", "create_client_review", "export"),
        "vfx_department": ("view",),
        "color_department": ("view", "assign", "edit_status", "approve", "upload_version"),
        "color_overview": ("view", "edit", "assign", "send_to_color_department"),
        "editing_items": (
            "view",
            "create",
            "edit",
            "delete",
            "manage_departments",
            "upload_versions",
            "link_scenes",
            "add_notes",
            "deliver",
        ),
        "music_library": ("view", "scan", "mount", "add_to_project"),
        "working_hours": (
            "view",
            "view_all",
            "create",
            "create_all",
            "approve",
            "reject",
            "edit",
            "delete",
            "export",
        ),
        "profile": ("view", "edit"),
        "approval_center": ("view", "create", "approve", "reject", "cancel", "audit"),
        "notification_management": ("view", "create", "edit", "delete", "test", "audit", "restore_defaults"),
        "producer_hunt": ("view",),
    },
    "user": {
        "dashboard": ("view",),
        "industry_radar": ("view",),
        "criticals": ("view",),
        "projects": ("view",),
        "project_detail": ("view",),
        "editing_items": ("view",),
        "episode_detail": ("view", "download_original"),
        "tasks": ("view", "create", "edit_own"),
        "requests": ("view", "create", "edit_own", "edit_status"),
        "action_board": ("view", "create", "edit_own"),
        "todos": ("view", "create", "edit_own"),
        "sticky_notes": ("view", "create", "edit_own"),
        "booking": ("view", "create", "edit_own", "delete_own"),
        "working_hours": ("view", "create", "edit_own", "delete_own"),
        "producer_hunt": ("view",),
        "profile": ("view", "edit"),
    },
    "producer": {
        "dashboard": ("view",),
        "industry_radar": ("view",),
        "criticals": ("view",),
        "projects": ("view", "create", "edit"),
        "project_detail": ("view", "edit"),
        "episode_detail": (
            "view",
            "upload_episode_version",
            "upload_scene_version",
            "edit_notes",
            "approve_version",
            "download_original",
        ),
        "tasks": ("view", "create", "edit"),
        "requests": ("view", "create", "edit", "assign", "edit_status", "view_all"),
        "action_board": ("view", "create", "edit"),
        "todos": ("view", "create", "edit"),
        "sticky_notes": ("view", "create", "edit"),
        "booking": ("view", "create", "edit_own", "edit_all", "delete_own", "delete_all"),
        "machine_room": ("view", "create", "edit", "start_copy", "manage_hdd", "scan"),
        "editing_items": (
            "view",
            "create",
            "edit",
            "delete",
            "manage_departments",
            "upload_versions",
            "link_scenes",
            "add_notes",
            "deliver",
        ),
        "client_review": ("view", "create_link"),
        "working_hours": (
            "view",
            "view_all",
            "create",
            "create_all",
            "approve",
            "reject",
            "edit",
            "export",
        ),
        "producer_hunt": ("view",),
        "profile": ("view", "edit"),
    },
    "machine_room": {
        "dashboard": ("view",),
        "industry_radar": ("view",),
        "criticals": ("view",),
        "machine_room": ("view", "create", "edit", "start_copy", "manage_hdd", "scan"),
        "tasks": ("view", "edit"),
        "requests": ("view", "create", "edit", "edit_status"),
        "action_board": ("view", "create", "edit_own"),
        "todos": ("view", "create", "edit_own"),
        "sticky_notes": ("view", "create", "edit_own"),
        "working_hours": ("view", "create", "edit_own", "delete_own"),
        "profile": ("view", "edit"),
    },
    GUEST_ROLE_VIEWER: _GUEST_VIEWER_PAGES,
    GUEST_ROLE_REVIEWER: _merge_guest_pages(_GUEST_VIEWER_PAGES, _GUEST_REVIEWER_EXTRA),
    GUEST_ROLE_APPROVER: _merge_guest_pages(
        _GUEST_VIEWER_PAGES, _GUEST_REVIEWER_EXTRA, _GUEST_APPROVER_EXTRA
    ),
}

JOB_TITLE_SEED: dict[str, dict[str, tuple[str, ...]]] = {
    "vfx supervisor": {
        "vfx_department": ("view", "assign", "edit_status", "approve", "deliver", "export", "upload_version", "edit"),
        "vfx_editor": ("view",),
    },
    "vfx artist": {
        "vfx_department": ("view", "upload_version", "edit_status"),
    },
    "fx artist": {
        "vfx_department": ("view", "upload_version", "edit_status"),
    },
    "editor": {
        "vfx_editor": ("view", "create_shot", "edit_shot", "upload", "send_to_department", "export_pdf", "create_client_review", "export"),
        "color_department": ("view",),
        "color_overview": ("view", "send_to_color_department"),
        "episode_detail": (
            "view",
            "upload_episode_version",
            "upload_scene_version",
            "edit_notes",
            "download_original",
        ),
        "editing_items": ("view", "edit", "upload_versions", "add_notes", "link_scenes"),
        "music_library": ("view", "add_to_project"),
        "action_board": ("view", "create", "edit_own"),
        "todos": ("view", "create", "edit_own"),
        "sticky_notes": ("view", "create", "edit_own"),
        "projects": ("view",),
        "project_detail": ("view",),
    },
    "machine room": {
        "machine_room": ("view", "create", "edit", "start_copy", "manage_hdd", "scan"),
        "projects": ("view",),
        "project_detail": ("view",),
    },
    "producer": {
        "projects": ("view",),
        "project_detail": ("view",),
        "booking": ("view", "create"),
        "client_review": ("view",),
        "machine_room": ("view", "create", "edit", "start_copy", "manage_hdd", "scan"),
    },
    "sound designer": {
        "music_library": ("view", "add_to_project"),
        "projects": ("view",),
    },
    "colorist": {
        "color_department": ("view", "upload_version", "edit_status"),
        "color_overview": ("view",),
        "projects": ("view",),
        "project_detail": ("view",),
    },
    "senior colorist": {
        "color_department": ("view", "upload_version", "edit_status", "deliver"),
        "color_overview": ("view",),
        "projects": ("view",),
        "project_detail": ("view",),
    },
    "color supervisor": {
        "color_department": ("view", "assign", "edit_status", "approve", "deliver", "export", "upload_version", "edit"),
        "color_overview": ("view", "edit", "assign", "approve"),
        "projects": ("view",),
        "project_detail": ("view",),
    },
}

_EPISODE_DETAIL_PATH = re.compile(r"^/projects/\d+/episodes/\d+")
_EPISODE_COLOR_PATH = re.compile(r"^/episodes/\d+/color(?:-editor-mode)?")
# Color editor routes enforce account_may_* in color_grading_routes (not perm_svc page keys).
_COLOR_EDITOR_MODE_PATH = re.compile(r"^/episodes/\d+/color-editor-mode(?:/|$)")
# Color item workspace + readiness — color_grading_routes enforces account_may_use_color_portal.
_COLOR_ITEM_WORKSPACE_PATH = re.compile(
    r"^/projects/\d+/color/items/\d+(?:/send-readiness)?$"
)
# Color item send API — route enforces account_may_send_episode_to_color_department.
_COLOR_ITEM_SEND_PATH = re.compile(r"^/projects/\d+/color/items/\d+/send-to-department$")
# Color Portal overview + legacy scene list — routes enforce account_may_use_color_portal.
_COLOR_PORTAL_OVERVIEW_PATH = re.compile(
    r"^/projects/\d+/color(?:/(?:episodes|scenes))?$"
)
# Editing-item conform actions — conform_routes enforces _may_request_conform.
_EDITING_ITEM_COLOR_CONFORM_PATH = re.compile(
    r"^/editing-items/\d+/color/(?:request-conform|start-conform)$"
)
_CONFORM_TASK_FAIL_PATH = re.compile(r"^/conform-tasks/\d+/(?:fail|issues)$")
# DIT assignment helpers for color conform flow — routes enforce their own access checks.
_COLOR_CONFORM_PROJECT_PATH = re.compile(
    r"^/projects/\d+/(?:dit-conform-users|mastering-delivery-users|add-dit-conform-user|add-mastering-delivery-user)$"
)
# Color department JSON APIs enforce account_may_* per route.
_COLOR_DEPARTMENT_API_PATH = re.compile(r"^/color-department/\d+/api/")
# VFX editor routes enforce account_can_access_project and guest_access per handler.
_PROJECT_MACHINE_ROOM_PATH = re.compile(r"^/projects/\d+/machine-room(?:/|$)")
_VFX_EDITOR_PROJECT_PATH = re.compile(r"^/projects/\d+/vfx(?:/|$)")
_USER_AVATAR_PATH = re.compile(r"^/users/\d+/avatar$")
_PROFILE_AVATAR_FILE_PATH = re.compile(r"^/profile/avatar-file/")

SKIP_PATH_PREFIXES = (
    "/static",
    "/socket.io",
    "/login",
    "/register",
    "/logout",
    "/client-review",
    "/color-gallery",
    "/ui/fragment",
    "/admin/api/permissions",
)

SKIP_ENDPOINT_PREFIXES = ("client_review_", "color_gallery_", "static")
SKIP_ENDPOINTS = frozenset({
    "login",
    "register",
    "logout",
    "producer_hunt.static",
    # Own auth via account_may_machine_room_operate_stream_task (path is under /tasks).
    "tasks_machine_room_stream_update_estimate",
    "tasks_machine_room_stream_finish",
    "tasks_machine_room_stream_cancel_delete",
    "user_avatar_file",
    "profile_avatar_file",
})


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"[\s\-]+", "_", s.strip().lower())


def _norm_title(s: str | None) -> str:
    return (s or "").strip().lower()


# ---------------------------------------------------------------------------
# Models (registered once per app)
# ---------------------------------------------------------------------------

_perm_models: dict[str, type] = {}


def register_permission_models(db) -> SimpleNamespace:
    if _perm_models:
        return SimpleNamespace(**_perm_models)

    class PermissionPage(db.Model):
        __tablename__ = "permission_pages"

        id = db.Column(db.Integer, primary_key=True)
        key = db.Column(db.String(64), nullable=False, unique=True, index=True)
        name = db.Column(db.String(120), nullable=False)
        description = db.Column(db.Text, nullable=True)
        route_pattern = db.Column(db.String(255), nullable=False, default="")
        module = db.Column(db.String(64), nullable=False, default="core")
        is_active = db.Column(db.Boolean, nullable=False, default=True)

    class PermissionAction(db.Model):
        __tablename__ = "permission_actions"

        id = db.Column(db.Integer, primary_key=True)
        key = db.Column(db.String(64), nullable=False, unique=True, index=True)
        name = db.Column(db.String(120), nullable=False)
        description = db.Column(db.Text, nullable=True)

    class RolePermission(db.Model):
        __tablename__ = "role_permissions"
        __table_args__ = (
            db.UniqueConstraint("role_name", "page_key", "action_key", name="uq_role_perm"),
        )

        id = db.Column(db.Integer, primary_key=True)
        role_name = db.Column(db.String(64), nullable=False, index=True)
        page_key = db.Column(db.String(64), nullable=False, index=True)
        action_key = db.Column(db.String(64), nullable=False, index=True)
        is_allowed = db.Column(db.Boolean, nullable=False, default=True)

    class JobTitlePermission(db.Model):
        __tablename__ = "job_title_permissions"
        __table_args__ = (
            db.UniqueConstraint("job_title_id", "page_key", "action_key", name="uq_jt_perm"),
        )

        id = db.Column(db.Integer, primary_key=True)
        job_title_id = db.Column(db.Integer, db.ForeignKey("job_titles.id"), nullable=False, index=True)
        page_key = db.Column(db.String(64), nullable=False, index=True)
        action_key = db.Column(db.String(64), nullable=False, index=True)
        is_allowed = db.Column(db.Boolean, nullable=False, default=True)

    class UserPermissionOverride(db.Model):
        __tablename__ = "user_permission_overrides"
        __table_args__ = (
            db.UniqueConstraint("user_id", "page_key", "action_key", name="uq_user_perm_override"),
        )

        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
        page_key = db.Column(db.String(64), nullable=False, index=True)
        action_key = db.Column(db.String(64), nullable=False, index=True)
        is_allowed = db.Column(db.Boolean, nullable=False, default=True)
        note = db.Column(db.String(255), nullable=True)

    class PermissionAuditLog(db.Model):
        __tablename__ = "permission_audit_logs"

        id = db.Column(db.Integer, primary_key=True)
        admin_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
        target_type = db.Column(db.String(32), nullable=False)
        target_id = db.Column(db.String(64), nullable=True)
        page_key = db.Column(db.String(64), nullable=True)
        action_key = db.Column(db.String(64), nullable=True)
        old_value = db.Column(db.String(32), nullable=True)
        new_value = db.Column(db.String(32), nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    for name, cls in {
        "PermissionPage": PermissionPage,
        "PermissionAction": PermissionAction,
        "RolePermission": RolePermission,
        "JobTitlePermission": JobTitlePermission,
        "UserPermissionOverride": UserPermissionOverride,
        "PermissionAuditLog": PermissionAuditLog,
    }.items():
        _perm_models[name] = cls

    return SimpleNamespace(**_perm_models)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    source: str
    detail: str = ""


@dataclass(frozen=True)
class _CachedPermissionPage:
    """Scalar snapshot — avoids DetachedInstanceError when the ORM session closes."""

    key: str
    name: str
    module: str
    route_pattern: str


class PermissionService:
    def __init__(
        self,
        *,
        db,
        Account,
        User,
        JobTitle,
        PermissionPage,
        PermissionAction,
        RolePermission,
        JobTitlePermission,
        UserPermissionOverride,
        PermissionAuditLog,
        normalized_role_key: Callable[[str | None], str],
        directory_user_id_for_account: Callable[[Any], int | None],
        may_full_control_project: Callable[[Any, int], bool] | None = None,
        may_add_project_notes: Callable[[Any, int], bool] | None = None,
        may_manage_project_team: Callable[[Any, int], bool] | None = None,
        resolve_project_id_from_path: Callable[[str], int | None] | None = None,
        account_has_vfx_job_title: Callable[[Any], bool] | None = None,
        guest_effective_role_key: Callable[[Any], str] | None = None,
    ):
        self.db = db
        self.Account = Account
        self.User = User
        self.JobTitle = JobTitle
        self.PermissionPage = PermissionPage
        self.PermissionAction = PermissionAction
        self.RolePermission = RolePermission
        self.JobTitlePermission = JobTitlePermission
        self.UserPermissionOverride = UserPermissionOverride
        self.PermissionAuditLog = PermissionAuditLog
        self.normalized_role_key = normalized_role_key
        self.directory_user_id_for_account = directory_user_id_for_account
        self.may_full_control_project = may_full_control_project
        self.may_add_project_notes = may_add_project_notes
        self.may_manage_project_team = may_manage_project_team
        self.resolve_project_id_from_path = resolve_project_id_from_path
        self.account_has_vfx_job_title = account_has_vfx_job_title
        self.guest_effective_role_key = guest_effective_role_key
        self._page_cache: list[_CachedPermissionPage] | None = None

    def invalidate_cache(self) -> None:
        self._page_cache = None

    def _pages(self) -> list[_CachedPermissionPage]:
        if self._page_cache is None:
            rows = (
                self.PermissionPage.query.filter_by(is_active=True)
                .order_by(self.PermissionPage.module.asc(), self.PermissionPage.name.asc())
                .all()
            )
            self._page_cache = [
                _CachedPermissionPage(
                    key=(p.key or "").strip(),
                    name=(p.name or "").strip(),
                    module=(p.module or "").strip(),
                    route_pattern=(p.route_pattern or "").strip(),
                )
                for p in rows
            ]
        return self._page_cache

    def _is_vfx_access_role(self, acc) -> bool:
        """True when the account is a VFX-titled user on the standard User access role.

        Access role "VFX" is stored as account.role=user plus a VFX job title.
        Those users work through VFX Department — not the Projects list.
        Elevated roles (admin / super_user / producer / machine_room) are excluded.
        """
        if acc is None or self.account_has_vfx_job_title is None:
            return False
        role = self._role_key(acc)
        if role in ("admin", "super_user", "producer", "machine_room") or self._is_admin(acc):
            return False
        return bool(self.account_has_vfx_job_title(acc))

    def _account_is_vfx_supervisor_by_title(self, acc) -> bool:
        for jt_id in self._job_title_ids(acc):
            row = self.db.session.get(self.JobTitle, jt_id)
            name = ((row.name if row else "") or "").strip()
            if not name:
                continue
            if re.search(r"vfx\s*supervisor", name, re.IGNORECASE):
                return True
            s_lower = name.lower()
            if "vfx" in s_lower and "supervisor" in s_lower:
                return True
        return False

    def _account_is_vfx_artist_by_title(self, acc) -> bool:
        for jt_id in self._job_title_ids(acc):
            row = self.db.session.get(self.JobTitle, jt_id)
            name = ((row.name if row else "") or "").strip()
            if not name:
                continue
            if re.search(r"(?:vfx|fx)\s*artist", name, re.IGNORECASE):
                return True
            compact = re.sub(r"[\s\-_/]+", "", name.lower())
            if compact in ("vfxartist", "fxartist"):
                return True
        return False

    def _account_is_editing_team(self, acc) -> bool:
        for jt_id in self._job_title_ids(acc):
            row = self.db.session.get(self.JobTitle, jt_id)
            if row is None:
                continue
            dept = ((getattr(row, "department_code", None) or "")).strip().lower()
            if dept == "editing":
                return True
        return False

    def _editing_team_music_library_allowed(self, acc, action_key: str) -> bool:
        """Editorial/offline editors may browse Audio Library and attach tracks to projects."""
        if action_key not in ("view", "add_to_project"):
            return False
        return self._account_is_editing_team(acc)

    def _editing_team_notes_allowed(self, acc, action_key: str) -> bool:
        """Offline/Online Editing team may view and add project notes."""
        if action_key not in ("view", "create", "edit_own", "edit"):
            return False
        return self._account_is_editing_team(acc)

    def _vfx_department_member_allowed(self, acc, action_key: str) -> bool:
        if self.account_has_vfx_job_title is None or not self.account_has_vfx_job_title(acc):
            return False
        if action_key == "view":
            return True
        if self.can_direct(acc, "vfx_department", action_key):
            return True
        artist_actions = JOB_TITLE_SEED.get("vfx artist", {}).get("vfx_department", ())
        if action_key in artist_actions and self._account_is_vfx_artist_by_title(acc):
            return True
        supervisor_actions = JOB_TITLE_SEED.get("vfx supervisor", {}).get("vfx_department", ())
        if action_key in supervisor_actions and self._account_is_vfx_supervisor_by_title(acc):
            return True
        return False

    def resolve_page_key(self, path: str) -> str | None:
        p = (path or "").split("?", 1)[0].rstrip("/") or "/"
        if p == "/":
            return "dashboard"
        if _EPISODE_DETAIL_PATH.match(p):
            return "episode_detail"
        if _EPISODE_COLOR_PATH.match(p):
            return "color_department"
        if _PROJECT_MACHINE_ROOM_PATH.match(p):
            return "machine_room"
        if "/editing-items" in p:
            return "editing_items"
        if "/working-hours" in p:
            return "working_hours"
        for prefix, key in PATH_PAGE_RULES:
            if p == prefix.rstrip("/") or p.startswith(prefix):
                if key == "projects" and "/vfx" in p:
                    if "/vfx-department" in p:
                        return "vfx_department"
                    return "vfx_editor"
                if key == "projects" and "/color" in p:
                    return "color_overview"
                return key
        for page in sorted(self._pages(), key=lambda x: len(x.route_pattern or ""), reverse=True):
            pat = (page.route_pattern or "").rstrip("/")
            if not pat:
                continue
            if p == pat or p.startswith(pat + "/"):
                return page.key
        return None

    def _is_admin(self, acc) -> bool:
        return acc is not None and bool(getattr(acc, "is_admin", False))

    def _user_row(self, acc):
        if acc is None:
            return None
        return self.User.query.filter_by(account_id=acc.id).first()

    def _job_title_ids(self, acc) -> list[int]:
        u = self._user_row(acc)
        if u is None:
            return []
        links = getattr(u, "user_job_title_links", None) or []
        if links:
            return [int(link.job_title_id) for link in links if link.job_title_id is not None]
        jt_id = getattr(u, "job_title_id", None)
        return [int(jt_id)] if jt_id is not None else []

    def _role_key(self, acc) -> str:
        if acc is None:
            return ""
        role = self.normalized_role_key(getattr(acc, "role", None))
        if role == "guest" and self.guest_effective_role_key is not None:
            return self.guest_effective_role_key(acc)
        return role

    def _lookup_override(self, user_id: int | None, page_key: str, action_key: str):
        if user_id is None:
            return None
        return (
            self.UserPermissionOverride.query.filter_by(
                user_id=user_id, page_key=page_key, action_key=action_key
            ).first()
        )

    def _lookup_role(self, role_name: str, page_key: str, action_key: str):
        return (
            self.RolePermission.query.filter_by(
                role_name=role_name, page_key=page_key, action_key=action_key
            ).first()
        )

    def _lookup_job_title(self, job_title_id: int | None, page_key: str, action_key: str):
        if job_title_id is None:
            return None
        return (
            self.JobTitlePermission.query.filter_by(
                job_title_id=job_title_id, page_key=page_key, action_key=action_key
            ).first()
        )

    def explain(self, acc, page_key: str, action_key: str) -> PermissionDecision:
        if self._is_admin(acc):
            return PermissionDecision(True, "admin", "Administrators have full access")
        u = self._user_row(acc)
        uid = u.id if u else None
        ov = self._lookup_override(uid, page_key, action_key)
        if ov is not None:
            return PermissionDecision(
                bool(ov.is_allowed),
                "user_override",
                ov.note or ("Allowed by override" if ov.is_allowed else "Denied by override"),
            )
        # VFX access role: hide/block Projects list; VFX Department is the workspace.
        if page_key == "projects" and self._is_vfx_access_role(acc):
            return PermissionDecision(
                False,
                "vfx_access_role",
                "VFX access uses VFX Department, not Projects",
            )
        role = self._lookup_role(self._role_key(acc), page_key, action_key)
        if role is not None:
            return PermissionDecision(
                bool(role.is_allowed),
                "role",
                f"Role {self._role_key(acc)}",
            )
        for jt_id in self._job_title_ids(acc):
            jt = self._lookup_job_title(jt_id, page_key, action_key)
            if jt is not None:
                jt_name = ""
                row = self.db.session.get(self.JobTitle, jt_id)
                jt_name = row.name if row else ""
                if jt.is_allowed:
                    return PermissionDecision(bool(jt.is_allowed), "job_title", jt_name or "Job title")
        return PermissionDecision(False, "default_deny", "No matching permission")

    def _project_full_control_allows(self, page_key: str, action_key: str) -> bool:
        """Production team on a project inherits super_user seed permissions for that project."""
        seed = ROLE_SEED.get("super_user", {})
        page_actions = seed.get(page_key, ())
        if action_key in page_actions:
            return True
        if action_key.endswith("_own"):
            broad = action_key.replace("_own", "")
            broad_all = action_key.replace("_own", "_all")
            if broad in page_actions or broad_all in page_actions:
                return True
        return False

    def can_direct(self, acc, page_key: str, action_key: str) -> bool:
        return self.explain(acc, page_key, action_key).allowed

    def can(
        self,
        acc,
        page_key: str,
        action_key: str,
        *,
        owner_user_id: int | None = None,
        project_id: int | None = None,
    ) -> bool:
        if self._is_admin(acc):
            return True
        # Project note creation is scoped to `/projects/<id>/actions/create`.
        # Our business rule is: project team users with a Lead (supervisor) job title may add notes.
        try:
            path = request.path or ""
        except RuntimeError:
            path = ""
        if (
            self.may_add_project_notes is not None
            and action_key == "create"
            and project_id is not None
            and path.find("/actions/create") != -1
        ):
            try:
                if self.may_add_project_notes(acc, int(project_id)):
                    return True
            except Exception:
                pass
        # Project team membership: Lead team members may add/remove within their scopes.
        if (
            self.may_manage_project_team is not None
            and project_id is not None
            and page_key in ("projects", "project_detail")
            and (
                "/members/add" in path
                or ("/members/" in path and path.rstrip("/").endswith("/remove"))
            )
        ):
            try:
                if self.may_manage_project_team(acc, int(project_id)):
                    return True
            except Exception:
                pass
        if page_key == "vfx_department" and self._vfx_department_member_allowed(acc, action_key):
            return True
        if page_key == "music_library" and self._editing_team_music_library_allowed(acc, action_key):
            return True
        if page_key in ("action_board", "todos", "sticky_notes") and self._editing_team_notes_allowed(
            acc, action_key
        ):
            return True
        if project_id is not None and self.may_full_control_project is not None:
            try:
                if self.may_full_control_project(acc, int(project_id)):
                    if self._project_full_control_allows(page_key, action_key):
                        return True
            except (TypeError, ValueError):
                pass
        if action_key.endswith("_own"):
            broad = action_key.replace("_own", "")
            broad_all = action_key.replace("_own", "_all")
            if self.can_direct(acc, page_key, broad) or self.can_direct(acc, page_key, broad_all):
                return True
            du = self.directory_user_id_for_account(acc)
            if owner_user_id is not None and du is not None and int(du) == int(owner_user_id):
                return self.can_direct(acc, page_key, action_key)
            return False
        return self.can_direct(acc, page_key, action_key)

    def infer_action(self, method: str, path: str, endpoint: str | None) -> str:
        m = (method or "GET").upper()
        ep = endpoint or ""
        p = path or ""
        if m == "GET":
            return "view"
        if m == "DELETE" or "delete" in ep or "/delete" in p:
            return "delete"
        if any(tok in ep for tok in ("_new", "_create")) or "/create" in p:
            return "create"
        if "upload" in p or "upload" in ep or "versions" in p:
            if "delivery-docs" in p or "delivery_document" in ep:
                return "edit"
            if "vfx-department" in p or "vfx_department" in ep:
                return "upload_version"
            return "upload"
        if "approve" in p or "approve" in ep:
            return "approve"
        if "assign" in p or "assign" in ep:
            return "assign"
        if p.endswith(".pdf") or "export" in p or "report" in p:
            return "export"
        if "scan" in p:
            return "scan"
        if "mount" in p and m == "POST":
            return "mount"
        if "machine-room/copy-estimate" in p or "machine-room/cancel-delete" in p:
            return "edit"
        if "machine-room/finish" in p:
            return "edit"
        if "start" in ep:
            return "start_copy"
        if "/machine/" in p and "hdd" in p:
            return "manage_hdd"
        if "client-review" in p:
            return "create_client_review"
        if "send" in ep:
            return "send_to_department"
        return "edit"

    def map_action_for_page(self, page_key: str, action_key: str) -> str:
        p = request.path or ""
        if page_key == "requests":
            if "/requests/" in p and p.rstrip("/").endswith("/start"):
                return "edit_status"
            if "/requests/" in p and p.rstrip("/").endswith("/finish"):
                return "edit_status"
            if "/requests/" in p and p.rstrip("/").endswith("/fail"):
                return "edit_status"
            if "/requests/" in p and p.rstrip("/").endswith("/reopen"):
                return "edit_status"
            if "/requests/" in p and p.rstrip("/").endswith("/comment"):
                return "edit_status"
            if "/requests/" in p and p.rstrip("/").endswith("/assign"):
                return "assign"
        if page_key == "working_hours":
            tail = p.rstrip("/").rsplit("/", 1)[-1]
            if tail == "manual":
                return "create"
            if tail == "reject":
                return "reject"
            return action_key
        # Delivery PDF uploads live under project settings; treat as project edit,
        # not a separate "upload" action (which project_detail roles do not have).
        if page_key == "project_detail" and "/settings/delivery-docs" in p:
            if action_key in ("upload", "create", "delete"):
                return "edit"
        if page_key == "machine_room" and action_key == "scan":
            # Storage scans on MR dashboard volumes — route enforces _require_scan().
            if "/machine-room/volumes/" in p and (
                "/scan/" in p
                or "/check-status" in p
                or "/discover" in p
                or "/add-discovered" in p
                or "/update-from-discovery" in p
                or "/debug-mount" in p
            ):
                return "manage_hdd"
        if page_key == "machine_room" and action_key == "assign":
            # Volume → project link; path contains "assign" but is MR edit, not task assign.
            if "/machine-room/volumes/" in p and p.rstrip("/").endswith("/assign"):
                return "edit"
        if page_key == "episode_detail":
            if request.endpoint in (
                "project_episode_script_remove",
                "project_episode_script_scene_count",
            ):
                return "upload_episode_version"
            if "/scene-versions/" in p and "/cancel-preview" in p:
                return "upload_scene_version"
            if "/scene-versions/" in p and "/comments" in p:
                return "edit_notes"
            if action_key == "upload":
                if "versions/scene" in p or "/scene-versions/" in p:
                    return "upload_scene_version"
                return "upload_episode_version"
            if action_key == "delete":
                return "delete_version"
            if action_key == "approve":
                return "approve_version"
            if "/original" in p:
                return "download_original"
            if "notes" in p and (request.method or "").upper() == "POST":
                return "edit_notes"
        if page_key == "editing_items":
            if action_key == "create":
                if "/notes/" in p:
                    return "add_notes"
                if "/deliveries/" in p:
                    return "deliver"
                if "/versions/" in p:
                    return "upload_versions"
            if "/notes/" in p or "editing-item-notes" in p:
                status = (request.form.get("status") or "").strip().lower()
                if status in ("approved", "rejected", "changes_requested"):
                    return "approve"
                return "add_notes"
            if "/versions/" in p or "editing-item-versions" in p:
                status = (request.form.get("status") or "").strip().lower()
                if status == "approved" or action_key == "approve":
                    return "approve"
                return "upload_versions"
            if "scenes" in p:
                return "link_scenes"
            if "deliveries" in p:
                return "deliver"
            if action_key == "upload":
                return "upload_versions"
            if "sync-status" in p or "accept-suggestions" in p:
                return "edit"
        aliases = {
            ("vfx_editor", "edit"): "edit_shot",
            ("vfx_editor", "create"): "create_shot",
            ("vfx_editor", "delete"): "delete_shot",
            ("vfx_department", "edit"): "edit_status",
            ("vfx_department", "upload"): "upload_version",
            ("machine_room", "edit"): "edit",
            ("machine_room", "create"): "create",
            ("task_log", "edit"): "edit_status",
        }
        return aliases.get((page_key, action_key), action_key)

    def check_request(self, acc, *, skip: bool = False) -> PermissionDecision | None:
        if skip or acc is None:
            return None
        path = request.path or ""
        for prefix in SKIP_PATH_PREFIXES:
            if path.startswith(prefix):
                return None
        if _COLOR_EDITOR_MODE_PATH.match(path):
            return None
        if _COLOR_ITEM_WORKSPACE_PATH.match(path):
            return None
        if _COLOR_ITEM_SEND_PATH.match(path):
            return None
        if _COLOR_PORTAL_OVERVIEW_PATH.match(path):
            return None
        if _EDITING_ITEM_COLOR_CONFORM_PATH.match(path):
            return None
        if _CONFORM_TASK_FAIL_PATH.match(path):
            return None
        if _COLOR_CONFORM_PROJECT_PATH.match(path):
            return None
        if _COLOR_DEPARTMENT_API_PATH.match(path):
            return None
        if _VFX_EDITOR_PROJECT_PATH.match(path):
            return None
        if _USER_AVATAR_PATH.match(path) or _PROFILE_AVATAR_FILE_PATH.match(path):
            return None
        ep = request.endpoint or ""
        if ep in SKIP_ENDPOINTS:
            return None
        for prefix in SKIP_ENDPOINT_PREFIXES:
            if ep.startswith(prefix):
                return None
        page_key = self.resolve_page_key(path)
        if not page_key:
            return None
        action_key = self.infer_action(request.method, path, ep)
        action_key = self.map_action_for_page(page_key, action_key)
        project_id = None
        if self.resolve_project_id_from_path is not None:
            try:
                project_id = self.resolve_project_id_from_path(path)
            except Exception:
                project_id = None
        if action_key == "view":
            allowed = self.can(acc, page_key, "view", project_id=project_id)
            source = "view"
        else:
            allowed = self.can(acc, page_key, action_key, project_id=project_id)
            if not allowed and action_key == "edit":
                allowed = self.can(acc, page_key, "edit_own", project_id=project_id)
                if not allowed and page_key == "working_hours":
                    # Billable edits target a ledger row the path cannot resolve to an
                    # owner, so a scoped grant opens the gate and the route re-checks.
                    allowed = self.can_direct(acc, page_key, "edit_own")
            if not allowed and action_key == "delete":
                # The owner cannot be resolved from the path, so a scoped grant opens
                # the gate and the route (booking) re-checks ownership before deleting.
                allowed = self.can_direct(acc, page_key, "delete_own") or self.can_direct(
                    acc, page_key, "delete_all"
                )
            source = action_key
        if allowed:
            return PermissionDecision(True, source, page_key)
        return PermissionDecision(False, "denied", f"{page_key}/{action_key}")

    def preview_user(self, user_id: int) -> dict[str, Any]:
        u = self.db.session.get(self.User, user_id)
        if u is None:
            return {"error": "not_found"}
        acc = self.db.session.get(self.Account, u.account_id) if u.account_id else None
        jt = self.db.session.get(self.JobTitle, u.job_title_id) if u.job_title_id else None
        pages = self._pages()
        actions = self.PermissionAction.query.order_by(self.PermissionAction.key.asc()).all()
        matrix: list[dict[str, Any]] = []
        for page in pages:
            row_actions: list[dict[str, Any]] = []
            for act in actions:
                decision = self.explain(acc, page.key, act.key)
                if decision.allowed:
                    row_actions.append(
                        {
                            "action": act.key,
                            "allowed": True,
                            "source": decision.source,
                            "detail": decision.detail,
                        }
                    )
            if row_actions or self.can(acc, page.key, "view"):
                matrix.append(
                    {
                        "page_key": page.key,
                        "page_name": page.name,
                        "module": page.module,
                        "can_view": self.can(acc, page.key, "view"),
                        "view_source": self.explain(acc, page.key, "view").source,
                        "actions": row_actions,
                    }
                )
        return {
            "user_id": u.id,
            "user_name": u.name,
            "role": self._role_key(acc),
            "job_title": jt.name if jt else None,
            "pages": matrix,
        }

    def log_audit(
        self,
        *,
        admin_user_id: int | None,
        target_type: str,
        target_id: str | None,
        page_key: str | None,
        action_key: str | None,
        old_value: str | None,
        new_value: str | None,
    ) -> None:
        row = self.PermissionAuditLog(
            admin_user_id=admin_user_id,
            target_type=target_type,
            target_id=target_id,
            page_key=page_key,
            action_key=action_key,
            old_value=old_value,
            new_value=new_value,
        )
        self.db.session.add(row)

    def set_role_permission(
        self,
        *,
        admin_user_id: int | None,
        role_name: str,
        page_key: str,
        action_key: str,
        is_allowed: bool,
    ) -> None:
        row = self._lookup_role(role_name, page_key, action_key)
        old = None if row is None else ("1" if row.is_allowed else "0")
        if row is None:
            row = self.RolePermission(
                role_name=role_name,
                page_key=page_key,
                action_key=action_key,
                is_allowed=is_allowed,
            )
            self.db.session.add(row)
        else:
            row.is_allowed = is_allowed
        self.log_audit(
            admin_user_id=admin_user_id,
            target_type="role",
            target_id=role_name,
            page_key=page_key,
            action_key=action_key,
            old_value=old,
            new_value="1" if is_allowed else "0",
        )

    def set_job_title_permission(
        self,
        *,
        admin_user_id: int | None,
        job_title_id: int,
        page_key: str,
        action_key: str,
        is_allowed: bool,
    ) -> None:
        row = self._lookup_job_title(job_title_id, page_key, action_key)
        old = None if row is None else ("1" if row.is_allowed else "0")
        if row is None:
            row = self.JobTitlePermission(
                job_title_id=job_title_id,
                page_key=page_key,
                action_key=action_key,
                is_allowed=is_allowed,
            )
            self.db.session.add(row)
        else:
            row.is_allowed = is_allowed
        self.log_audit(
            admin_user_id=admin_user_id,
            target_type="job_title",
            target_id=str(job_title_id),
            page_key=page_key,
            action_key=action_key,
            old_value=old,
            new_value="1" if is_allowed else "0",
        )

    def set_user_override(
        self,
        *,
        admin_user_id: int | None,
        user_id: int,
        page_key: str,
        action_key: str,
        is_allowed: bool,
        note: str | None = None,
    ) -> UserPermissionOverride:
        row = self._lookup_override(user_id, page_key, action_key)
        old = None if row is None else ("1" if row.is_allowed else "0")
        if row is None:
            row = self.UserPermissionOverride(
                user_id=user_id,
                page_key=page_key,
                action_key=action_key,
                is_allowed=is_allowed,
                note=note,
            )
            self.db.session.add(row)
        else:
            row.is_allowed = is_allowed
            row.note = note
        self.log_audit(
            admin_user_id=admin_user_id,
            target_type="user",
            target_id=str(user_id),
            page_key=page_key,
            action_key=action_key,
            old_value=old,
            new_value="1" if is_allowed else "0",
        )
        return row


def seed_permissions(db, perm_models, JobTitle) -> None:
    PermissionPage = perm_models.PermissionPage
    PermissionAction = perm_models.PermissionAction
    RolePermission = perm_models.RolePermission
    JobTitlePermission = perm_models.JobTitlePermission

    for spec in DEFAULT_ACTIONS:
        row = PermissionAction.query.filter_by(key=spec["key"]).first()
        if row is None:
            db.session.add(PermissionAction(**spec))
    for spec in DEFAULT_PAGES:
        row = PermissionPage.query.filter_by(key=spec["key"]).first()
        if row is None:
            db.session.add(PermissionPage(**spec))
    db.session.commit()

    def _ensure_role(role_name: str, page_key: str, action_key: str) -> None:
        exists = RolePermission.query.filter_by(
            role_name=role_name, page_key=page_key, action_key=action_key
        ).first()
        if exists is None:
            db.session.add(
                RolePermission(
                    role_name=role_name,
                    page_key=page_key,
                    action_key=action_key,
                    is_allowed=True,
                )
            )

    for role_name, pages in ROLE_SEED.items():
        for page_key, actions in pages.items():
            for action_key in actions:
                _ensure_role(role_name, page_key, action_key)

    admin_actions = [a["key"] for a in DEFAULT_ACTIONS]
    admin_pages = [p["key"] for p in DEFAULT_PAGES]
    for page_key in admin_pages:
        for action_key in admin_actions:
            _ensure_role("admin", page_key, action_key)

    for title_name, pages in JOB_TITLE_SEED.items():
        if title_name == "editor":
            # Apply editor package to the full editing department, not only a title named "Editor".
            titles = JobTitle.query.filter(
                or_(
                    JobTitle.department_code == "editing",
                    JobTitle.name.ilike(title_name),
                    JobTitle.name.ilike(title_name.title()),
                )
            ).all()
        else:
            jt = JobTitle.query.filter(
                or_(
                    JobTitle.name.ilike(title_name),
                    JobTitle.name.ilike(title_name.title()),
                )
            ).first()
            titles = [jt] if jt is not None else []
        for jt in titles:
            if jt is None:
                continue
            for page_key, actions in pages.items():
                for action_key in actions:
                    exists = JobTitlePermission.query.filter_by(
                        job_title_id=jt.id, page_key=page_key, action_key=action_key
                    ).first()
                    if exists is None:
                        db.session.add(
                            JobTitlePermission(
                                job_title_id=jt.id,
                                page_key=page_key,
                                action_key=action_key,
                                is_allowed=True,
                            )
                        )
    db.session.commit()


def build_require_permission(perm_svc: PermissionService, account_from_session: Callable):
    def require_permission(page_key: str, action_key: str, *, owner_user_id: Callable | None = None):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                acc = account_from_session()
                oid = owner_user_id(*args, **kwargs) if owner_user_id else None
                if not perm_svc.can(acc, page_key, action_key, owner_user_id=oid):
                    if request.accept_mimetypes.best == "application/json" or request.is_json:
                        return jsonify({"ok": False, "error": "forbidden"}), 403
                    abort(403)
                return view(*args, **kwargs)

            return wrapped

        return decorator

    return require_permission


def permission_denied_response(*, json_error: bool = False):
    msg = "You do not have permission to access this page."
    if json_error or (
        request.accept_mimetypes.best == "application/json"
        or request.path.startswith("/api/")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    ):
        return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
    flash(msg, "error")
    ep = request.endpoint or ""
    path = (request.path or "").rstrip("/") or "/"
    if ep == "index" or path == "/":
        abort(403)
    return redirect(url_for("index"))
