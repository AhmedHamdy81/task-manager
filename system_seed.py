"""Idempotent master-data seed / repair for essential app setup (additive only)."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import func

_seed_models: dict[str, type] = {}


def normalize_code(name: str | None) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "item"


# ---------------------------------------------------------------------------
# Seed catalogs (reference master data)
# ---------------------------------------------------------------------------

USER_ROLE_SEEDS: tuple[dict[str, Any], ...] = (
    {"code": "admin", "name": "Admin", "description": "Full system access.", "sort_order": 10},
    {"code": "super_user", "name": "Super User", "description": "Same system access as Administrator.", "sort_order": 20},
    {"code": "producer", "name": "Producer / Project Manager", "description": "Manages projects, production and post workflow.", "sort_order": 30},
    {"code": "department_supervisor", "name": "Department Supervisor", "description": "Manages department work such as VFX, Color, Sound, Editing.", "sort_order": 40},
    {"code": "artist_operator", "name": "Artist / Operator", "description": "Works on assigned tasks, shots, color items, files or review notes.", "sort_order": 50},
    {"code": "machine_room", "name": "Machine Room", "description": "Machine room copy and storage workflows.", "sort_order": 55},
    {"code": "user", "name": "User", "description": "Standard assigned-project user.", "sort_order": 60},
    {"code": "client_guest", "name": "Client / Guest", "description": "External reviewer with limited access to shared review links.", "sort_order": 70},
    {"code": "guest", "name": "Guest", "description": "Guest account (viewer/reviewer/approver levels).", "sort_order": 75},
    {"code": "viewer", "name": "Viewer", "description": "Read-only user.", "sort_order": 80},
)

EMPLOYMENT_TYPE_SEEDS: tuple[dict[str, Any], ...] = (
    {"code": "in_house", "name": "In-house", "description": "Works inside BigBang Studios.", "metadata": {"can_be_assigned_to_projects": True, "can_access_internal_files": True, "can_be_paid": True}},
    {"code": "freelancer", "name": "Freelancer", "description": "External person hired per project or task.", "metadata": {"can_be_assigned_to_projects": True, "can_access_internal_files": False, "can_be_paid": True}},
    {"code": "vendor", "name": "Vendor", "description": "External company or studio.", "metadata": {"can_be_assigned_to_projects": True, "can_access_internal_files": False, "can_be_paid": True}},
    {"code": "client", "name": "Client", "description": "Production house/client reviewer.", "metadata": {"can_be_assigned_to_projects": True, "can_access_internal_files": False, "can_access_external_review_links": True}},
    {"code": "guest", "name": "Guest", "description": "Temporary external reviewer.", "metadata": {"can_be_assigned_to_projects": True, "can_access_internal_files": False, "can_access_external_review_links": True, "can_be_paid": False}},
    {"code": "intern_trainee", "name": "Intern / Trainee", "description": "Limited internal user.", "metadata": {"can_be_assigned_to_projects": True, "can_access_internal_files": False}},
    {"code": "partner", "name": "Partner", "description": "Strategic partner or collaborating studio.", "metadata": {"can_be_assigned_to_projects": True, "can_access_internal_files": True}},
)

DEPARTMENT_SEEDS: tuple[dict[str, Any], ...] = (
    {"code": "management", "name": "Management", "metadata": {"can_receive_work": False, "has_dashboard": True}},
    {"code": "production", "name": "Production", "metadata": {"can_receive_work": True, "has_dashboard": True}},
    {"code": "post_production", "name": "Post Production", "metadata": {"can_receive_work": True, "has_dashboard": True}},
    {"code": "editing", "name": "Editing", "metadata": {"can_receive_work": True, "has_dashboard": True}},
    {"code": "vfx", "name": "VFX", "metadata": {"can_receive_work": True, "has_dashboard": True}},
    {"code": "color_grading", "name": "Color Grading", "metadata": {"can_receive_work": True, "has_dashboard": True}},
    {"code": "sound", "name": "Sound", "metadata": {"can_receive_work": True, "has_dashboard": True}},
    {"code": "music", "name": "Music", "metadata": {"can_receive_work": True, "has_dashboard": True}},
    {"code": "delivery", "name": "Delivery", "metadata": {"can_receive_work": True, "has_dashboard": True}},
    {"code": "machine_room", "name": "Machine Room", "metadata": {"can_receive_work": True, "has_dashboard": True}},
    {"code": "client_review", "name": "Client Review", "metadata": {"can_receive_work": False, "has_dashboard": False}},
)

PROJECT_TYPE_SEEDS: tuple[dict[str, Any], ...] = (
    {"code": "feature_film", "name": "Feature Film", "metadata": {"needs_episodes": False, "needs_scenes": True, "needs_shooting_days": True}},
    {"code": "tv_series", "name": "TV Series", "metadata": {"needs_episodes": True, "needs_scenes": True, "needs_shooting_days": True}},
    {"code": "tv_program", "name": "TV Program", "metadata": {"needs_episodes": True, "needs_scenes": False, "needs_shooting_days": True}},
    {"code": "documentary", "name": "Documentary", "metadata": {"needs_episodes": False, "needs_scenes": True, "needs_shooting_days": True}},
    {"code": "commercial", "name": "Commercial", "metadata": {"needs_episodes": False, "needs_scenes": False, "needs_shooting_days": True}},
    {"code": "music_video", "name": "Music Video", "metadata": {"needs_episodes": False, "needs_scenes": False, "needs_shooting_days": True}},
    {"code": "social_media_campaign", "name": "Social Media Campaign", "metadata": {"needs_episodes": False, "needs_scenes": False, "needs_shooting_days": False}},
    {"code": "short_film", "name": "Short Film", "metadata": {"needs_episodes": False, "needs_scenes": True, "needs_shooting_days": True}},
    {"code": "animation", "name": "Animation", "metadata": {"needs_episodes": True, "needs_scenes": True, "needs_shooting_days": False}},
    {"code": "trailer_promo", "name": "Trailer / Promo", "metadata": {"needs_episodes": False, "needs_scenes": False, "needs_shooting_days": False}},
    {"code": "vfx_only", "name": "VFX-only Project", "metadata": {"needs_episodes": False, "needs_scenes": True, "needs_shooting_days": False}},
    {"code": "color_only", "name": "Color-only Project", "metadata": {"needs_episodes": True, "needs_scenes": False, "needs_shooting_days": False}},
    {"code": "sound_only", "name": "Sound-only Project", "metadata": {"needs_episodes": True, "needs_scenes": False, "needs_shooting_days": False}},
    {"code": "other", "name": "Other", "metadata": {}},
)

POST_SCOPE_SEEDS: tuple[dict[str, Any], ...] = (
    {"code": "offline_editing", "name": "Offline Editing", "metadata": {"department": "editing", "scope_key": "needs_offline_editing"}},
    {"code": "online_editing", "name": "Online Editing", "metadata": {"department": "editing", "scope_key": "needs_online_editing"}},
    {"code": "conform", "name": "Conform", "metadata": {"department": "color_grading", "scope_key": "needs_color_grading", "type": "finishing"}},
    {"code": "vfx", "name": "VFX", "metadata": {"department": "vfx", "scope_key": "needs_vfx"}},
    {"code": "color_grading", "name": "Color Grading", "metadata": {"department": "color_grading", "scope_key": "needs_color_grading"}},
    {"code": "sound_editing", "name": "Sound Editing", "metadata": {"department": "sound", "scope_key": "needs_sound_design"}},
    {"code": "sound_design", "name": "Sound Design", "metadata": {"department": "sound", "scope_key": "needs_sound_design"}},
    {"code": "music", "name": "Music", "metadata": {"department": "music", "scope_key": "needs_music"}},
    {"code": "mixing", "name": "Mixing", "metadata": {"department": "sound", "scope_key": "needs_sound_mix"}},
    {"code": "subtitles", "name": "Subtitles", "metadata": {"department": "delivery", "scope_key": "needs_subtitles"}},
    {"code": "production_team", "name": "Post-production Team", "metadata": {"department": "post_production", "scope_key": "needs_production_team"}},
    {"code": "client_guest", "name": "Client / Guest", "metadata": {"department": "client_review", "scope_key": "needs_client_guest"}},
    {"code": "qc", "name": "QC", "metadata": {"department": "delivery", "scope_key": "needs_qc_delivery"}},
    {"code": "mastering", "name": "Mastering", "metadata": {"department": "delivery", "scope_key": "needs_mastering_delivery"}},
    {"code": "delivery", "name": "Delivery", "metadata": {"department": "delivery", "scope_key": "needs_mastering_delivery"}},
    {"code": "archiving", "name": "Archiving", "metadata": {"department": "machine_room", "scope_key": "needs_machine_room"}},
)

TASK_STATUS_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n}
    for c, n in (
        ("open", "Open"),
        ("in_progress", "In Progress"),
        ("waiting", "Waiting"),
        ("blocked", "Blocked"),
        ("review", "Review"),
        ("approved", "Approved"),
        ("done", "Done"),
        ("cancelled", "Cancelled"),
        ("not_started", "Not Started"),
        ("assigned", "Assigned"),
        ("ready", "Ready"),
        ("needs_revision", "Needs Revision"),
        ("delivered", "Delivered"),
        ("client_approved", "Client Approved"),
    )
)

VFX_EDITOR_STATUS_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n.title() if len(n) > 3 else n.upper()}
    for c, n in (
        ("pending", "Pending"),
        ("sent", "Sent to VFX"),
        ("review", "In Review"),
        ("approved", "Approved"),
        ("blocked", "Blocked"),
        ("delivered", "Delivered"),
    )
)

VFX_DEPT_STATUS_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n.replace("_", " ").title()}
    for c, n in (
        ("pending", "pending"),
        ("assigned", "assigned"),
        ("in_progress", "in_progress"),
        ("internal_review", "internal_review"),
        ("client_review", "client_review"),
        ("approved", "approved"),
        ("delivered", "delivered"),
        ("blocked", "blocked"),
        ("on_hold", "on_hold"),
    )
)

COLOR_STATUS_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n.replace("_", " ").title()}
    for c, n in (
        ("not_sent", "not_sent"),
        ("sent_to_color", "sent_to_color"),
        ("preparing", "preparing"),
        ("pending", "pending"),
        ("waiting_for_picture_lock", "waiting_for_picture_lock"),
        ("waiting_for_vfx", "waiting_for_vfx"),
        ("ready", "ready"),
        ("assigned", "assigned"),
        ("in_progress", "in_progress"),
        ("color_in_progress", "color_in_progress"),
        ("internal_review", "internal_review"),
        ("client_review", "client_review"),
        ("revision_requested", "revision_requested"),
        ("approved", "approved"),
        ("mastered", "mastered"),
        ("delivered", "delivered"),
        ("blocked", "blocked"),
        ("not_started", "not_started"),
    )
)

PRIORITY_SEEDS: tuple[dict[str, Any], ...] = (
    {"code": "low", "name": "Low", "sort_order": 10},
    {"code": "normal", "name": "Normal", "sort_order": 20},
    {"code": "medium", "name": "Medium", "sort_order": 25},
    {"code": "high", "name": "High", "sort_order": 30},
    {"code": "urgent", "name": "Urgent", "sort_order": 40},
    {"code": "critical", "name": "Critical", "sort_order": 50},
)

REVIEW_TYPE_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": normalize_code(n), "name": n}
    for n in (
        "Internal Review",
        "Director Review",
        "Producer Review",
        "Client Review",
        "Platform Review",
        "Final Approval",
        "Technical QC",
        "Creative QC",
    )
)

DELIVERY_FORMAT_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n}
    for c, n in (
        ("prores_422_hq", "ProRes 422 HQ"),
        ("prores_4444", "ProRes 4444"),
        ("dnxhr_hqx", "DNxHR HQX"),
        ("h264_mp4", "H.264 MP4"),
        ("h265_mp4", "H.265 MP4"),
        ("exr_sequence", "EXR Sequence"),
        ("dpx_sequence", "DPX Sequence"),
        ("wav", "WAV"),
        ("aaf", "AAF"),
        ("xml", "XML"),
        ("edl", "EDL"),
        ("srt", "SRT"),
        ("dcp", "DCP"),
        ("imf", "IMF"),
    )
)

RESOLUTION_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n}
    for c, n in (
        ("hd_1080", "HD 1920x1080"),
        ("two_k", "2K 2048x1080"),
        ("uhd_4k", "UHD 3840x2160"),
        ("dci_4k", "4K DCI 4096x2160"),
        ("six_k", "6K"),
        ("eight_k", "8K"),
        ("custom", "Custom"),
    )
)

FRAME_RATE_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n}
    for c, n in (
        ("23_976", "23.976"),
        ("24", "24"),
        ("25", "25"),
        ("29_97", "29.97"),
        ("30", "30"),
        ("50", "50"),
        ("59_94", "59.94"),
        ("60", "60"),
    )
)

SHOOTING_ELEMENT_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {
        "code": normalize_code(name),
        "name": name,
        "metadata": {"counts_in_episode_scene_count": name.lower() in ("scene",)},
    }
    for name in (
        "Scene",
        "Reshoot",
        "Pickup",
        "Establishing Shot",
        "Insert Shot",
        "VFX Plate",
        "Green Screen",
        "Clean Plate",
        "Reference Shot",
        "B-Roll",
        "Drone Shot",
        "Stunt Shot",
        "Montage",
        "Promo Shot",
        "Behind The Scenes",
        "Sound Wild Track",
        "Test Shot",
    )
)

STORAGE_TYPE_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n}
    for c, n in (
        ("hdd", "HDD"),
        ("ssd", "SSD"),
        ("nvme", "NVMe"),
        ("raid", "RAID"),
        ("nas", "NAS"),
        ("lto", "LTO"),
        ("cloud_storage", "Cloud Storage"),
        ("shuttle_drive", "Shuttle Drive"),
        ("backup_drive", "Backup Drive"),
    )
)

STORAGE_STATUS_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n.replace("_", " ").title()}
    for c, n in (
        ("available", "available"),
        ("in_use", "in_use"),
        ("full", "full"),
        ("archived", "archived"),
        ("damaged", "damaged"),
        ("missing", "missing"),
        ("transferred", "transferred"),
        ("backup_verified", "backup_verified"),
    )
)

NOTIFICATION_TYPE_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n}
    for c, n in (
        ("task_assigned", "Task assigned"),
        ("task_updated", "Task updated"),
        ("comment_added", "Comment added"),
        ("mention", "Mention"),
        ("vfx_shot_sent", "VFX shot sent"),
        ("vfx_status_changed", "VFX status changed"),
        ("color_item_sent", "Color item sent"),
        ("external_link_created", "External link created"),
        ("review_submitted", "Review submitted"),
        ("file_uploaded", "File uploaded"),
        ("deadline_approaching", "Deadline approaching"),
        ("whatsapp_sent", "WhatsApp sent"),
    )
)

SHARE_LINK_TYPE_SEEDS: tuple[dict[str, Any], ...] = tuple(
    {"code": c, "name": n}
    for c, n in (
        ("color_gallery", "Color Gallery"),
        ("vfx_review", "VFX Review"),
        ("episode_review", "Episode Review"),
        ("scene_review", "Scene Review"),
        ("file_delivery", "File Delivery"),
        ("client_approval", "Client Approval"),
    )
)

SYSTEM_SETTING_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    ("company_name", "BigBang Studios", "Studio display name"),
    ("default_timezone", "Africa/Cairo", "Default application timezone"),
    ("default_country_code", "20", "Default phone country code"),
    (
        "public_base_url",
        "",
        "Public application / connection HTTP address (desktop, share links, password-reset emails)",
    ),
    ("max_upload_size_mb", "500", "Maximum upload size in megabytes"),
    ("allowed_video_extensions", "mp4,mov,mxf", "Allowed video extensions"),
    ("allowed_image_extensions", "jpg,jpeg,png,webp", "Allowed image extensions"),
    ("allowed_audio_extensions", "wav,mp3,aac", "Allowed audio extensions"),
    ("industry_radar_auto_refresh", "true", "Enable Industry Radar auto refresh"),
    ("industry_radar_refresh_hour", "8", "Industry Radar daily refresh hour"),
    ("industry_radar_refresh_minute", "0", "Industry Radar daily refresh minute"),
    ("industry_radar_timezone", "Africa/Cairo", "Industry Radar scheduler timezone"),
    ("whatsapp_cloud_api_enabled", "false", "Enable WhatsApp Cloud API"),
    ("backup_before_system_seed", "true", "Backup database before system seed from admin UI"),
    ("mail_enabled", "false", "Enable outbound SMTP email delivery"),
    ("mail_provider", "custom", "SMTP provider preset (custom, gmail, microsoft365)"),
    ("mail_server", "", "SMTP server hostname"),
    ("mail_port", "587", "SMTP port"),
    ("mail_encryption", "starttls", "SMTP encryption: starttls, ssl, or none"),
    ("mail_username", "", "SMTP username"),
    ("mail_sender_name", "", "Default sender display name"),
    ("mail_sender_email", "", "Default sender email address"),
    ("mail_reset_expiry_minutes", "60", "Password-reset link expiry in minutes"),
    (
        "mail_admin_fallback_on_failure",
        "true",
        "Notify administrators when password-reset email delivery fails",
    ),
)

CONNECTION_HTTP_ADDRESS_KEY = "public_base_url"
CONNECTION_HTTP_ADDRESS_DESCRIPTION = (
    "Public application / connection HTTP address "
    "(desktop, share links, password-reset emails)"
)

UPLOAD_DIRECTORY_KEY = "upload_directory"
UPLOAD_DIRECTORY_DESCRIPTION = (
    "Directory for uploaded files (avatars, chat, media, scripts, and related assets)"
)
UPLOAD_DIRECTORY_POINTER_NAME = ".upload_data_dir"
UPLOAD_DIRECTORY_ENV = "TASK_MANAGER_UPLOAD_DIR"


def pick_directory_with_native_dialog(*, prompt: str = "Choose a folder") -> str | None:
    """Open a native folder chooser on the machine running this process.

    macOS uses Finder via AppleScript. Returns a normalized absolute path, or
    ``None`` when the user cancels or the platform is unsupported.
    """
    system = platform.system()
    if system == "Darwin":
        script = (
            f'POSIX path of (choose folder with prompt "{prompt.replace(chr(34), "")}")'
        )
        try:
            completed = subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        raw = (completed.stdout or "").strip()
        return normalize_upload_directory(raw) or (os.path.normpath(raw) if raw else None)

    if system == "Linux":
        for cmd in (
            ["zenity", "--file-selection", "--directory", f"--title={prompt}"],
            ["kdialog", "--getexistingdirectory", os.path.expanduser("~")],
        ):
            try:
                completed = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if completed.returncode != 0:
                continue
            raw = (completed.stdout or "").strip()
            if raw:
                return normalize_upload_directory(raw) or os.path.normpath(raw)
        return None

    return None


def default_instance_directory(app_root: str | None = None) -> str:
    """Default instance folder next to the application package."""
    root = app_root or os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(root, "instance"))


def upload_directory_pointer_path(app_root: str | None = None) -> str:
    """Stable pointer file so startup can resolve uploads before the DB is ready."""
    return os.path.join(default_instance_directory(app_root), UPLOAD_DIRECTORY_POINTER_NAME)


def normalize_upload_directory(raw: str | None) -> str | None:
    """Return a canonical absolute upload data directory, or None if invalid."""
    text = (raw or "").strip()
    if not text:
        return None
    if "\0" in text:
        return None
    # Reject traversal segments before absolutizing.
    if ".." in text.replace("\\", "/").split("/"):
        return None
    try:
        abs_path = os.path.normpath(os.path.abspath(os.path.expanduser(text)))
    except (OSError, ValueError):
        return None
    if not os.path.isabs(abs_path):
        return None
    cmp = (abs_path.rstrip(os.sep) or abs_path).replace("\\", "/")
    blocked_exact = {
        "/",
        "/etc",
        "/bin",
        "/sbin",
        "/usr",
        "/dev",
        "/proc",
        "/sys",
        "/boot",
        "/root",
        "/private",
        "/System",
        "/Library",
        "/Applications",
        "/var",
    }
    if cmp in blocked_exact:
        return None
    # Allow /var/folders (temp) and similar; still block other sensitive trees.
    blocked_prefixes = (
        "/etc/",
        "/bin/",
        "/sbin/",
        "/usr/",
        "/dev/",
        "/proc/",
        "/sys/",
        "/boot/",
        "/root/",
        "/private/",
        "/System/",
        "/Library/",
        "/Applications/",
    )
    for prefix in blocked_prefixes:
        if cmp.startswith(prefix):
            return None
    return abs_path


def read_upload_directory_pointer(app_root: str | None = None) -> str | None:
    path = upload_directory_pointer_path(app_root)
    try:
        with open(path, encoding="utf-8") as fh:
            return normalize_upload_directory(fh.read())
    except OSError:
        return None


def write_upload_directory_pointer(directory: str, app_root: str | None = None) -> str:
    normalized = normalize_upload_directory(directory)
    if not normalized:
        raise ValueError("Invalid upload directory")
    pointer = upload_directory_pointer_path(app_root)
    os.makedirs(os.path.dirname(pointer), exist_ok=True)
    with open(pointer, "w", encoding="utf-8") as fh:
        fh.write(normalized + "\n")
    return normalized


def resolve_upload_data_directory(*, app_root: str | None = None, fallback: str | None = None) -> str:
    """
    Resolve the active upload data directory.

    Order: TASK_MANAGER_UPLOAD_DIR env → pointer file → fallback → default instance.
    """
    env_raw = (os.environ.get(UPLOAD_DIRECTORY_ENV) or "").strip()
    if env_raw:
        env_norm = normalize_upload_directory(env_raw)
        if env_norm:
            return env_norm
    pointed = read_upload_directory_pointer(app_root)
    if pointed:
        return pointed
    if fallback:
        fb = normalize_upload_directory(fallback)
        if fb:
            return fb
    return default_instance_directory(app_root)


def current_upload_directory(SystemSetting, *, fallback: str = "") -> str:
    stored = normalize_upload_directory(
        get_system_setting(SystemSetting, UPLOAD_DIRECTORY_KEY)
    )
    if stored:
        return stored
    return normalize_upload_directory(fallback) or (fallback or "").rstrip()


UPLOAD_DIRECTORY_HISTORY_KEY = "upload_directory_history"
UPLOAD_DIRECTORY_HISTORY_DESCRIPTION = "Recently used upload directories"
UPLOAD_DIRECTORY_HISTORY_MAX = 12
UPLOAD_DIRECTORY_HISTORY_SAFE_DELETE_TYPE = "upload_directory_history"


def upload_directory_history_entity_id(directory: str) -> int | None:
    """Stable positive int for Safe Delete challenges on a history path."""
    import zlib

    normalized = normalize_upload_directory(directory)
    if not normalized:
        return None
    value = zlib.crc32(normalized.encode("utf-8")) & 0x7FFFFFFF
    return value or 1


def upload_directory_for_history_entity_id(
    SystemSetting, entity_id: int, *, fallback: str = ""
) -> str | None:
    try:
        want = int(entity_id)
    except (TypeError, ValueError):
        return None
    candidates = list(get_upload_directory_history(SystemSetting))
    current = current_upload_directory(SystemSetting, fallback=fallback)
    if current and current not in candidates:
        candidates.insert(0, current)
    for path in candidates:
        if upload_directory_history_entity_id(path) == want:
            return path
    return None


def get_upload_directory_history(SystemSetting) -> list[str]:
    raw = get_system_setting(SystemSetting, UPLOAD_DIRECTORY_HISTORY_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in data:
        normalized = normalize_upload_directory(str(item) if item is not None else "")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
        if len(out) >= UPLOAD_DIRECTORY_HISTORY_MAX:
            break
    return out


def set_upload_directory_history(db, SystemSetting, paths: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in paths:
        normalized = normalize_upload_directory(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
        if len(cleaned) >= UPLOAD_DIRECTORY_HISTORY_MAX:
            break
    set_system_setting(
        db,
        SystemSetting,
        UPLOAD_DIRECTORY_HISTORY_KEY,
        json.dumps(cleaned),
        description=UPLOAD_DIRECTORY_HISTORY_DESCRIPTION,
    )
    return cleaned


def add_upload_directory_history(db, SystemSetting, directory: str) -> list[str]:
    normalized = normalize_upload_directory(directory)
    if not normalized:
        return get_upload_directory_history(SystemSetting)
    history = [normalized] + [
        path for path in get_upload_directory_history(SystemSetting) if path != normalized
    ]
    return set_upload_directory_history(db, SystemSetting, history)


def remove_upload_directory_history(db, SystemSetting, directory: str) -> list[str]:
    normalized = normalize_upload_directory(directory)
    history = get_upload_directory_history(SystemSetting)
    if not normalized:
        return history
    next_history = [path for path in history if path != normalized]
    if len(next_history) == len(history):
        return history
    return set_upload_directory_history(db, SystemSetting, next_history)


def normalize_connection_http_address(raw: str | None) -> str | None:
    """Return a canonical http(s) origin (optional path), or None if invalid."""
    text = (raw or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    if not parsed.hostname:
        return None
    path = (parsed.path or "").rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")).rstrip("/")


def get_system_setting(SystemSetting, key: str, default: str = "") -> str:
    row = SystemSetting.query.filter_by(key=key).first()
    if row is None:
        return default
    return (row.value or "").strip() or default


def set_system_setting(
    db,
    SystemSetting,
    key: str,
    value: str,
    *,
    description: str | None = None,
) -> Any:
    row = SystemSetting.query.filter_by(key=key).first()
    now = datetime.utcnow()
    if row is None:
        row = SystemSetting(
            key=key,
            value=value,
            description=description,
            updated_at=now,
        )
        db.session.add(row)
        return row
    row.value = value
    row.updated_at = now
    if description and not (row.description or "").strip():
        row.description = description
    return row


def current_connection_http_address(SystemSetting, *, fallback: str = "") -> str:
    stored = normalize_connection_http_address(
        get_system_setting(SystemSetting, CONNECTION_HTTP_ADDRESS_KEY)
    )
    if stored:
        return stored
    return normalize_connection_http_address(fallback) or (fallback or "").rstrip("/")


def absolute_url_from_path(SystemSetting, path: str, *, fallback: str = "") -> str:
    raw = (path or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    base = current_connection_http_address(SystemSetting, fallback=fallback).rstrip("/")
    if not base:
        return raw
    if not raw.startswith("/"):
        raw = "/" + raw
    return base + raw


SETUP_DISPLAY_GROUPS: tuple[tuple[str, str, str | None, str, int], ...] = (
    ("user_role", "User Roles", "user_role", "system_master_entries", 7),
    ("permission_action", "Permissions", None, "permission_actions", 10),
    ("employment_type", "Employment Structure", "employment_type", "system_master_entries", 5),
    ("employment_scope_link", "Employment Scope Links", None, "employment_scope_links", 1),
    ("job_category", "Job Categories", None, "job_categories", 10),
    ("job_title", "Job Titles", None, "job_titles", 150),
    ("job_title_employment_link", "Job Title Employment Links", None, "job_title_employment_links", 1),
    ("job_category_post_scope_link", "Job Category Post Scope Links", None, "job_category_post_scope_links", 1),
    ("job_title_post_scope_link", "Job Title Post Scope Links", None, "job_title_post_scope_links", 1),
    ("department", "Departments", "department", "system_master_entries", 8),
    ("project_type", "Project Types", "project_type", "system_master_entries", 8),
    ("post_scope", "Post-production Scope", "post_scope", "system_master_entries", 10),
    ("post_scope_groups", "Post-production Task Groups", None, "task_groups", 8),
    ("task_status", "Task Statuses", "task_status", "system_master_entries", 8),
    ("vfx_editor_status", "VFX Editor Statuses", "vfx_editor_status", "system_master_entries", 4),
    ("vfx_dept_status", "VFX Department Statuses", "vfx_dept_status", "system_master_entries", 6),
    ("color_status", "Color Statuses", "color_status", "system_master_entries", 8),
    ("priority", "Priority Levels", "priority", "task_priorities", 4),
    ("review_type", "Review Types", "review_type", "system_master_entries", 4),
    ("delivery_format", "Delivery Formats", "delivery_format", "system_master_entries", 8),
    ("resolution", "Resolutions", "resolution", "system_master_entries", 4),
    ("frame_rate", "Frame Rates", "frame_rate", "system_master_entries", 4),
    ("shooting_element_type", "Shooting Element Types", "shooting_element_type", "system_master_entries", 8),
    ("storage_type", "Storage Types", "storage_type", "system_master_entries", 4),
    ("storage_status", "Storage Statuses", "storage_status", "system_master_entries", 4),
    ("notification_type", "Notification Types", "notification_type", "system_master_entries", 6),
    ("share_link_type", "External Share Link Types", "share_link_type", "system_master_entries", 4),
    ("system_settings", "System Settings", None, "system_settings", 5),
    ("industry_radar_source", "Industry Radar Sources", None, "industry_news_sources", 1),
    ("industry_radar_item", "Industry Radar Items", None, "industry_news_items", 0),
)


def register_system_seed_models(db) -> SimpleNamespace:
    if _seed_models:
        return SimpleNamespace(**_seed_models)

    class SystemMasterEntry(db.Model):
        __tablename__ = "system_master_entries"
        __table_args__ = (
            db.UniqueConstraint("domain", "code", name="uq_system_master_domain_code"),
        )

        id = db.Column(db.Integer, primary_key=True)
        domain = db.Column(db.String(64), nullable=False, index=True)
        code = db.Column(db.String(80), nullable=False, index=True)
        name = db.Column(db.String(200), nullable=False, default="")
        description = db.Column(db.Text, nullable=True)
        sort_order = db.Column(db.Integer, nullable=False, default=0)
        is_active = db.Column(db.Boolean, nullable=False, default=True)
        metadata_json = db.Column(db.Text, nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    class SystemSetting(db.Model):
        __tablename__ = "system_settings"

        id = db.Column(db.Integer, primary_key=True)
        key = db.Column(db.String(120), nullable=False, unique=True, index=True)
        value = db.Column(db.Text, nullable=False, default="")
        description = db.Column(db.Text, nullable=True)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    class SystemSeedRun(db.Model):
        __tablename__ = "system_seed_runs"

        id = db.Column(db.Integer, primary_key=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
        created_by_account_id = db.Column(db.Integer, nullable=True, index=True)
        backup_path = db.Column(db.Text, nullable=True)
        created_count = db.Column(db.Integer, nullable=False, default=0)
        skipped_existing_count = db.Column(db.Integer, nullable=False, default=0)
        updated_count = db.Column(db.Integer, nullable=False, default=0)
        failed_count = db.Column(db.Integer, nullable=False, default=0)
        tables_touched_json = db.Column(db.Text, nullable=True)
        warnings_json = db.Column(db.Text, nullable=True)
        summary_json = db.Column(db.Text, nullable=True)

    for name, cls in {
        "SystemMasterEntry": SystemMasterEntry,
        "SystemSetting": SystemSetting,
        "SystemSeedRun": SystemSeedRun,
    }.items():
        _seed_models[name] = cls

    return SimpleNamespace(**_seed_models)


def ensure_sqlite_system_seed_tables(db) -> None:
    from sqlalchemy import inspect, text

    if db.engine.dialect.name != "sqlite":
        models = register_system_seed_models(db)
        for key in ("SystemMasterEntry", "SystemSetting", "SystemSeedRun"):
            models.__dict__[key].__table__.create(bind=db.engine, checkfirst=True)
        return
    models = register_system_seed_models(db)
    for key in ("SystemMasterEntry", "SystemSetting", "SystemSeedRun"):
        models.__dict__[key].__table__.create(bind=db.engine, checkfirst=True)


@dataclass
class SeedSummary:
    created_count: int = 0
    skipped_existing_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    tables_touched: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    backup_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def record(self, action: str, table: str) -> None:
        self.tables_touched.add(table)
        if action == "created":
            self.created_count += 1
        elif action == "updated":
            self.updated_count += 1
        elif action == "failed":
            self.failed_count += 1
        else:
            self.skipped_existing_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_count": self.created_count,
            "skipped_existing_count": self.skipped_existing_count,
            "updated_count": self.updated_count,
            "failed_count": self.failed_count,
            "tables_touched": sorted(self.tables_touched),
            "backup_path": self.backup_path,
            "warnings": list(self.warnings),
            "details": self.details,
        }


def create_backup_before_seed(app) -> str:
    instance_path = app.instance_path
    src = os.path.join(instance_path, "app.db")
    if not os.path.isfile(src):
        raise FileNotFoundError(f"Database not found: {src}")
    backup_dir = os.path.join(instance_path, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    dest = os.path.join(backup_dir, f"app.db.{stamp}.db")
    shutil.copy2(src, dest)
    if not os.path.isfile(dest) or os.path.getsize(dest) < 1:
        raise OSError(f"Backup verification failed: {dest}")
    return dest


def latest_backup_path(app) -> str | None:
    backup_dir = os.path.join(app.instance_path, "backups")
    if not os.path.isdir(backup_dir):
        return None
    candidates = [
        os.path.join(backup_dir, name)
        for name in os.listdir(backup_dir)
        if name.startswith("app.db.") and name.endswith(".db")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def ensure_master_entry(
    db,
    SystemMasterEntry,
    *,
    domain: str,
    code: str,
    name: str,
    description: str | None = None,
    sort_order: int = 0,
    metadata: dict[str, Any] | None = None,
    is_active: bool = True,
) -> str:
    code_norm = normalize_code(code)
    row = SystemMasterEntry.query.filter_by(domain=domain, code=code_norm).first()
    meta_json = json.dumps(metadata, sort_keys=True) if metadata else None
    if row is None:
        db.session.add(
            SystemMasterEntry(
                domain=domain,
                code=code_norm,
                name=(name or code_norm).strip(),
                description=(description or "").strip() or None,
                sort_order=int(sort_order or 0),
                is_active=bool(is_active),
                metadata_json=meta_json,
            )
        )
        return "created"
    changed = False
    if not (row.name or "").strip() and name:
        row.name = name.strip()
        changed = True
    if not (row.description or "").strip() and description:
        row.description = description.strip()
        changed = True
    if not (row.metadata_json or "").strip() and meta_json:
        row.metadata_json = meta_json
        changed = True
    if changed:
        row.updated_at = datetime.utcnow()
        return "updated"
    return "skipped"


def seed_master_domain(
    db,
    SystemMasterEntry,
    summary: SeedSummary,
    domain: str,
    entries: tuple[dict[str, Any], ...],
) -> None:
    for spec in entries:
        try:
            action = ensure_master_entry(
                db,
                SystemMasterEntry,
                domain=domain,
                code=spec["code"],
                name=spec.get("name") or spec["code"],
                description=spec.get("description"),
                sort_order=int(spec.get("sort_order") or 0),
                metadata=spec.get("metadata"),
            )
            summary.record(action, "system_master_entries")
        except Exception as exc:
            summary.failed_count += 1
            summary.warnings.append(f"{domain}/{spec.get('code')}: {exc}")


def seed_user_roles(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "user_role", USER_ROLE_SEEDS)


def seed_employment_structure(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "employment_type", EMPLOYMENT_TYPE_SEEDS)


def seed_departments(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "department", DEPARTMENT_SEEDS)


def seed_project_types(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "project_type", PROJECT_TYPE_SEEDS)


def seed_post_production_scope_master(db, SystemMasterEntry, summary: SeedSummary, ctx: dict[str, Any] | None = None) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "post_scope", POST_SCOPE_SEEDS)
    if ctx:
        import job_titles_master_support as jtms

        jt_models = ctx.get("job_titles_master_models") or {}
        emp_models = ctx.get("employment_structure_models") or {}
        try:
            report = jtms.retire_post_scope_master_code(
                db,
                SystemMasterEntry,
                retired_code="assistant_editing",
                migrate_to_code="offline_editing",
                JobCategoryPostScopeLink=jt_models.get("JobCategoryPostScopeLink"),
                JobTitlePostScopeLink=jt_models.get("JobTitlePostScopeLink"),
                EmploymentScopeLink=emp_models.get("EmploymentScopeLink"),
            )
            if report.get("links_migrated") or report.get("links_removed") or report.get("master_retired"):
                summary.details["retired_post_scope_assistant_editing"] = report
        except Exception as exc:
            summary.warnings.append(f"retire assistant_editing post_scope: {exc}")


def seed_task_statuses(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "task_status", TASK_STATUS_SEEDS)


def seed_vfx_statuses(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "vfx_editor_status", VFX_EDITOR_STATUS_SEEDS)
    seed_master_domain(db, SystemMasterEntry, summary, "vfx_dept_status", VFX_DEPT_STATUS_SEEDS)


def seed_color_statuses(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "color_status", COLOR_STATUS_SEEDS)


def seed_review_types(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "review_type", REVIEW_TYPE_SEEDS)


def seed_delivery_formats(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "delivery_format", DELIVERY_FORMAT_SEEDS)


def seed_resolutions(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "resolution", RESOLUTION_SEEDS)


def seed_frame_rates(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "frame_rate", FRAME_RATE_SEEDS)


def seed_shooting_element_types(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "shooting_element_type", SHOOTING_ELEMENT_SEEDS)


def seed_storage_types(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "storage_type", STORAGE_TYPE_SEEDS)


def seed_storage_statuses(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "storage_status", STORAGE_STATUS_SEEDS)


def seed_notification_types(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "notification_type", NOTIFICATION_TYPE_SEEDS)


def seed_external_share_link_types(db, SystemMasterEntry, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "share_link_type", SHARE_LINK_TYPE_SEEDS)


def seed_permissions(db, perm_models, JobTitle, summary: SeedSummary) -> None:
    from permissions import seed_permissions as _seed_permissions

    try:
        _seed_permissions(db, perm_models, JobTitle)
        summary.record("updated", "permission_pages")
        summary.record("updated", "permission_actions")
        summary.record("updated", "role_permissions")
        summary.details["permissions"] = "seed_permissions completed"
    except Exception as exc:
        summary.failed_count += 1
        summary.warnings.append(f"permissions: {exc}")


def seed_priority_levels(db, SystemMasterEntry, TaskPriority, summary: SeedSummary) -> None:
    seed_master_domain(db, SystemMasterEntry, summary, "priority", PRIORITY_SEEDS)
    for spec in PRIORITY_SEEDS:
        name = spec["name"]
        existing = TaskPriority.query.filter(
            func.lower(TaskPriority.name) == name.lower()
        ).first()
        if existing is None:
            db.session.add(TaskPriority(name=name))
            summary.record("created", "task_priorities")
        else:
            summary.record("skipped", "task_priorities")


def seed_post_production_scope_groups(db, TaskGroup, summary: SeedSummary) -> None:
    from project_settings import LEGACY_TASK_GROUP_TO_POST_SCOPE, POST_SCOPE_FIELDS

    import task_preset_support as tps

    scope_rows: list[tuple[str, str, str]] = list(tps.TASK_PRESET_SCOPE_FIELDS)
    preset_keys = {k for k, _, _ in tps.TASK_PRESET_SCOPE_FIELDS}
    for row in POST_SCOPE_FIELDS:
        if row[0] not in preset_keys:
            scope_rows.append(row)
    legacy_by_scope = {v: k for k, v in LEGACY_TASK_GROUP_TO_POST_SCOPE.items()}
    for i, (key, label, _hint) in enumerate(scope_rows):
        g = TaskGroup.query.filter_by(post_scope_key=key).first()
        if g is None:
            legacy_name = legacy_by_scope.get(key)
            if legacy_name:
                g = TaskGroup.query.filter_by(name=legacy_name).first()
        if g is None:
            db.session.add(TaskGroup(name=label, sort_order=i, post_scope_key=key))
            summary.record("created", "task_groups")
        else:
            summary.record("skipped", "task_groups")


def seed_task_preset_titles(db, TaskGroup, TaskGroupTitle, summary: SeedSummary) -> None:
    import task_preset_support as tps

    try:
        counts = tps.restore_all_default_titles(db, TaskGroup, TaskGroupTitle)
        added = sum(int(v or 0) for v in counts.values())
        summary.details["task_preset_titles_added"] = added
        if added:
            summary.created_count += added
            summary.tables_touched.add("task_group_titles")
        else:
            summary.skipped_existing_count += 1
            summary.tables_touched.add("task_group_titles")
    except Exception as exc:
        summary.failed_count += 1
        summary.warnings.append(f"task_preset_titles: {exc}")


def seed_job_titles(db, JobCategory, JobTitle, summary: SeedSummary, ctx: dict[str, Any] | None = None) -> None:
    import job_titles_master_support as jtms

    SystemMasterEntry = (ctx or {}).get("SystemMasterEntry")
    EmploymentLink = (ctx or {}).get("JobTitleEmploymentTypeLink")
    ScopeLink = (ctx or {}).get("JobTitlePostScopeLink")
    CategoryScopeLink = (ctx or {}).get("JobCategoryPostScopeLink")
    if SystemMasterEntry is None or EmploymentLink is None or ScopeLink is None:
        from studio_job_titles_seed import seed_studio_job_titles

        try:
            report = seed_studio_job_titles(db, JobCategory, JobTitle)
            summary.created_count += int(report.get("inserted") or 0)
            summary.updated_count += int(report.get("updated") or 0)
            summary.skipped_existing_count += int(report.get("skipped") or 0)
            summary.tables_touched.add("job_titles")
            summary.tables_touched.add("job_categories")
            summary.details["studio_job_titles"] = report
        except Exception as exc:
            summary.failed_count += 1
            summary.warnings.append(f"job_titles: {exc}")
        return
    try:
        report = jtms.seed_default_job_titles_master(
            db, JobCategory, JobTitle, SystemMasterEntry, EmploymentLink, ScopeLink, CategoryScopeLink
        )
        summary.created_count += int(report.get("categories_created") or 0)
        summary.created_count += int(report.get("titles_created") or 0)
        summary.created_count += int(report.get("employment_links_created") or 0)
        summary.created_count += int(report.get("category_scope_links_created") or 0)
        summary.created_count += int(report.get("scope_links_created") or 0)
        summary.updated_count += int(report.get("categories_updated") or 0)
        summary.updated_count += int(report.get("titles_updated") or 0)
        summary.skipped_existing_count += int(report.get("categories_skipped") or 0)
        summary.skipped_existing_count += int(report.get("titles_skipped") or 0)
        summary.skipped_existing_count += int(report.get("employment_links_skipped") or 0)
        summary.skipped_existing_count += int(report.get("category_scope_links_skipped") or 0)
        summary.skipped_existing_count += int(report.get("scope_links_skipped") or 0)
        summary.failed_count += int(report.get("failed_count") or 0)
        summary.tables_touched.update(
            {
                "job_categories",
                "job_titles",
                "job_title_employment_type_links",
                "job_category_post_scope_links",
                "job_title_post_scope_links",
            }
        )
        summary.details["job_titles_master"] = report
    except Exception as exc:
        summary.failed_count += 1
        summary.warnings.append(f"job_titles: {exc}")


def seed_system_settings(db, SystemSetting, summary: SeedSummary) -> None:
    for key, value, description in SYSTEM_SETTING_DEFAULTS:
        row = SystemSetting.query.filter_by(key=key).first()
        if row is None:
            db.session.add(
                SystemSetting(
                    key=key,
                    value=value,
                    description=description,
                )
            )
            summary.record("created", "system_settings")
        else:
            changed = False
            if not (row.value or "").strip() and value:
                row.value = value
                changed = True
            if not (row.description or "").strip() and description:
                row.description = description
                changed = True
            summary.record("updated" if changed else "skipped", "system_settings")


def count_for_health(
    db,
    models,
    ctx: dict[str, Any],
    *,
    master_domain: str | None,
    table_kind: str,
) -> int:
    if table_kind == "system_master_entries":
        SystemMasterEntry = models.SystemMasterEntry
        if not master_domain:
            return 0
        return SystemMasterEntry.query.filter_by(domain=master_domain).count()
    if table_kind == "permission_actions":
        return ctx["perm_models"].PermissionAction.query.count()
    if table_kind == "job_titles":
        return ctx["JobTitle"].query.count()
    if table_kind == "job_categories":
        return ctx["JobCategory"].query.count()
    if table_kind == "job_title_employment_links":
        model = ctx.get("JobTitleEmploymentTypeLink")
        return model.query.count() if model else 0
    if table_kind == "job_title_post_scope_links":
        model = ctx.get("JobTitlePostScopeLink")
        return model.query.count() if model else 0
    if table_kind == "job_category_post_scope_links":
        model = ctx.get("JobCategoryPostScopeLink")
        return model.query.count() if model else 0
    if table_kind == "task_groups":
        return ctx["TaskGroup"].query.filter(ctx["TaskGroup"].post_scope_key.isnot(None)).count()
    if table_kind == "task_priorities":
        return ctx["TaskPriority"].query.count()
    if table_kind == "system_settings":
        return models.SystemSetting.query.count()
    if table_kind == "industry_news_sources":
        model = ctx.get("IndustryNewsSource")
        return model.query.count() if model else 0
    if table_kind == "industry_news_items":
        model = ctx.get("IndustryNewsItem")
        return model.query.count() if model else 0
    if table_kind == "employment_scope_links":
        model = ctx.get("EmploymentScopeLink")
        return model.query.count() if model else 0
    return 0


def build_health_report(db, models, ctx: dict[str, Any]) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    warnings: list[str] = []
    for key, label, master_domain, table_kind, min_expected in SETUP_DISPLAY_GROUPS:
        count = count_for_health(
            db, models, ctx, master_domain=master_domain, table_kind=table_kind
        )
        ok = count >= min_expected
        if not ok and min_expected > 0:
            warnings.append(f"{label}: expected at least {min_expected}, found {count}")
        groups.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "min_expected": min_expected,
                "ok": ok,
                "is_industry_radar": key.startswith("industry_radar"),
            }
        )
    SystemMasterEntry = models.SystemMasterEntry
    master_total = SystemMasterEntry.query.count()
    emp_type_count = SystemMasterEntry.query.filter_by(domain="employment_type").count()
    link_model = ctx.get("EmploymentScopeLink")
    link_count = link_model.query.count() if link_model else 0
    if emp_type_count > 0 and link_count == 0:
        warnings.append(
            "Employment Structure: employment categories exist but no scope links are configured"
        )
    JobCategory = ctx.get("JobCategory")
    JobTitle = ctx.get("JobTitle")
    if JobCategory and JobTitle:
        cat_count = JobCategory.query.count()
        title_count = JobTitle.query.count()
        if cat_count > 0 and title_count < 50:
            warnings.append(
                f"Job Titles: categories exist ({cat_count}) but title count is low ({title_count})"
            )
        scope_link_model = ctx.get("JobTitlePostScopeLink")
        cat_scope_link_model = ctx.get("JobCategoryPostScopeLink")
        if title_count > 20 and scope_link_model and scope_link_model.query.count() == 0:
            warnings.append("Job Titles: titles exist but no post scope links are configured")
        if cat_count > 5 and cat_scope_link_model and cat_scope_link_model.query.count() == 0:
            warnings.append("Job Categories: categories exist but no category post scope links are configured")
        if scope_link_model and cat_scope_link_model:
            t_links = scope_link_model.query.count()
            c_links = cat_scope_link_model.query.count()
            if title_count > 20 and t_links < 10 and c_links < 3:
                warnings.append(
                    f"Job Title Scope Links: low link counts (titles={t_links}, categories={c_links})"
                )
    return {
        "groups": groups,
        "warnings": warnings,
        "master_entry_total": master_total,
        "has_missing_essential": bool(warnings),
    }


def seed_employment_scope_links(db, ctx: dict[str, Any], summary: SeedSummary) -> None:
    import employment_structure_support as esup

    EmploymentScopeLink = ctx.get("EmploymentScopeLink")
    if EmploymentScopeLink is None:
        summary.warnings.append("employment_scope_links: EmploymentScopeLink model missing")
        return
    SystemMasterEntry = ctx.get("SystemMasterEntry") or ctx.get("system_seed_models")
    if hasattr(SystemMasterEntry, "SystemMasterEntry"):
        SystemMasterEntry = SystemMasterEntry.SystemMasterEntry
    try:
        created_scopes = esup.seed_extra_post_scopes(db, SystemMasterEntry, ensure_master_entry)
        if created_scopes:
            summary.created_count += created_scopes
            summary.tables_touched.add("system_master_entries")
        report = esup.seed_default_employment_scope_links(db, SystemMasterEntry, EmploymentScopeLink)
        summary.created_count += int(report.get("created") or 0)
        summary.updated_count += int(report.get("updated") or 0)
        summary.skipped_existing_count += int(report.get("skipped") or 0)
        summary.tables_touched.add("employment_scope_links")
        summary.details["employment_scope_links"] = report
    except Exception as exc:
        summary.failed_count += 1
        summary.warnings.append(f"employment_scope_links: {exc}")


def run_system_seed(
    db,
    app,
    *,
    models: SimpleNamespace,
    ctx: dict[str, Any],
    created_by: int | None = None,
    require_backup: bool = True,
) -> dict[str, Any]:
    """Run full additive master-data seed. Does not touch transactional workflow rows."""
    summary = SeedSummary()
    SystemMasterEntry = models.SystemMasterEntry
    SystemSetting = models.SystemSetting
    SystemSeedRun = models.SystemSeedRun

    if require_backup:
        try:
            summary.backup_path = create_backup_before_seed(app)
        except Exception as exc:
            summary.failed_count += 1
            summary.warnings.append(f"backup failed: {exc}")
            return summary.to_dict()

    seed_user_roles(db, SystemMasterEntry, summary)
    seed_permissions(db, ctx["perm_models"], ctx["JobTitle"], summary)
    seed_employment_structure(db, SystemMasterEntry, summary)
    seed_post_production_scope_master(db, SystemMasterEntry, summary, ctx)
    seed_ctx_links = dict(ctx)
    seed_ctx_links["SystemMasterEntry"] = SystemMasterEntry
    seed_employment_scope_links(db, seed_ctx_links, summary)
    seed_departments(db, SystemMasterEntry, summary)
    seed_job_titles(db, ctx["JobCategory"], ctx["JobTitle"], summary, ctx)
    seed_project_types(db, SystemMasterEntry, summary)
    seed_post_production_scope_groups(db, ctx["TaskGroup"], summary)
    seed_task_preset_titles(db, ctx["TaskGroup"], ctx["TaskGroupTitle"], summary)
    seed_task_statuses(db, SystemMasterEntry, summary)
    seed_vfx_statuses(db, SystemMasterEntry, summary)
    seed_color_statuses(db, SystemMasterEntry, summary)
    seed_priority_levels(db, SystemMasterEntry, ctx["TaskPriority"], summary)
    seed_review_types(db, SystemMasterEntry, summary)
    seed_delivery_formats(db, SystemMasterEntry, summary)
    seed_resolutions(db, SystemMasterEntry, summary)
    seed_frame_rates(db, SystemMasterEntry, summary)
    seed_shooting_element_types(db, SystemMasterEntry, summary)
    seed_storage_types(db, SystemMasterEntry, summary)
    seed_storage_statuses(db, SystemMasterEntry, summary)
    seed_notification_types(db, SystemMasterEntry, summary)
    seed_external_share_link_types(db, SystemMasterEntry, summary)
    seed_system_settings(db, SystemSetting, summary)

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        summary.failed_count += 1
        summary.warnings.append(f"commit failed: {exc}")
        return summary.to_dict()

    result = summary.to_dict()
    try:
        run_row = SystemSeedRun(
            created_by_account_id=created_by,
            backup_path=summary.backup_path,
            created_count=summary.created_count,
            skipped_existing_count=summary.skipped_existing_count,
            updated_count=summary.updated_count,
            failed_count=summary.failed_count,
            tables_touched_json=json.dumps(result.get("tables_touched") or []),
            warnings_json=json.dumps(result.get("warnings") or []),
            summary_json=json.dumps(result),
        )
        db.session.add(run_row)
        db.session.commit()
        result["seed_run_id"] = int(run_row.id)
    except Exception as exc:
        db.session.rollback()
        summary.warnings.append(f"could not log seed run: {exc}")
        result["warnings"] = summary.warnings

    return result


def last_seed_run(models) -> dict[str, Any] | None:
    SystemSeedRun = models.SystemSeedRun
    row = SystemSeedRun.query.order_by(SystemSeedRun.created_at.desc()).first()
    if row is None:
        return None
    summary = {}
    if row.summary_json:
        try:
            summary = json.loads(row.summary_json)
        except json.JSONDecodeError:
            summary = {}
    return {
        "id": int(row.id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "backup_path": row.backup_path,
        "created_count": row.created_count,
        "skipped_existing_count": row.skipped_existing_count,
        "updated_count": row.updated_count,
        "failed_count": row.failed_count,
        "summary": summary,
    }
