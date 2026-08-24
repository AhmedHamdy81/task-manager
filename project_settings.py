"""Project Settings — constants, type normalization, and form parsing."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

PROJECT_TYPE_SLUGS: tuple[str, ...] = (
    "tv_series",
    "feature_film",
    "short_film",
    "commercial",
    "documentary",
    "music_video",
    "other",
)

PROJECT_TYPE_LABELS: dict[str, str] = {
    "tv_series": "TV Series",
    "feature_film": "Feature Film",
    "short_film": "Short Film",
    "commercial": "Commercial",
    "documentary": "Documentary",
    "music_video": "Music Video",
    "other": "Other",
}

_LEGACY_TYPE_TO_SLUG: dict[str, str] = {
    "tv series": "tv_series",
    "feature film": "feature_film",
    "short film": "short_film",
    "music video": "music_video",
    "establishing shots": "other",
}

LIFECYCLE_STATUS_VALUES: tuple[str, ...] = (
    "development",
    "pre_production",
    "shooting",
    "post_production",
    "delivery",
    "delivered",
    "archived",
)

LIFECYCLE_STATUS_LABELS: dict[str, str] = {
    "development": "Development",
    "pre_production": "Pre-production",
    "shooting": "Shooting",
    "post_production": "Post-production",
    "delivery": "Delivery",
    "delivered": "Delivered",
    "archived": "Archived",
}

PRIORITY_VALUES: tuple[str, ...] = ("low", "medium", "high", "urgent")

PRIORITY_LABELS: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "urgent": "Urgent",
}

DELIVERY_RESOLUTION_OPTIONS: tuple[str, ...] = ("HD", "2K", "4K", "UHD", "Custom")
DELIVERY_FRAME_RATE_OPTIONS: tuple[str, ...] = (
    "23.976",
    "24",
    "25",
    "29.97",
    "30",
    "50",
    "60",
    "Custom",
)
DELIVERY_COLOR_SPACE_OPTIONS: tuple[str, ...] = ("Rec.709", "P3", "HDR", "Log", "Custom")
DELIVERY_AUDIO_FORMAT_OPTIONS: tuple[str, ...] = ("Stereo", "5.1", "7.1", "Atmos", "Custom")

POST_SCOPE_REQUIRED_MSG = "Select at least one post-production scope."

# Retired post_scope master codes (system_master_entries.domain=post_scope); hidden from UI.
RETIRED_POST_SCOPE_CODES: frozenset[str] = frozenset({"assistant_editing"})

# Migrate existing links to replacement master codes on startup / seed.
RETIRED_POST_SCOPE_MIGRATIONS: dict[str, str] = {
    "assistant_editing": "offline_editing",
}


def is_retired_post_scope_code(code: str | None) -> bool:
    return (code or "").strip().lower() in RETIRED_POST_SCOPE_CODES

PRODUCTION_TEAM_SCOPE_KEY = "needs_production_team"
CLIENT_GUEST_SCOPE_KEY = "needs_client_guest"

POST_MANAGEMENT_TITLE_CODES: frozenset[str] = frozenset(
    {
        "post_producer",
        "post_production_supervisor",
        "post_production_manager",
        "post_production_coordinator",
        "post_assistant",
        "head_of_post",
        "workflow_supervisor",
        "pipeline_supervisor",
        "post_operations_manager",
        "post_scheduler",
    }
)

CLIENT_GUEST_TITLE_CODES: frozenset[str] = frozenset(
    {
        "client",
        "guest",
        "client_guest",
        "client_reviewer",
        "external_reviewer",
    }
)

# Always enabled on every project (create + settings save); backfilled on startup.
AUTO_ENABLED_POST_SCOPE_KEYS: frozenset[str] = frozenset(
    {PRODUCTION_TEAM_SCOPE_KEY, "needs_mastering_delivery", CLIENT_GUEST_SCOPE_KEY}
)

# Legacy control-panel task group names mapped to post-production scope keys.
LEGACY_TASK_GROUP_TO_POST_SCOPE: dict[str, str] = {
    "Editing": "needs_offline_editing",
    "DI / Machine": "needs_mastering_delivery",
    "Color Grading": "needs_color_grading",
    "Sound": "needs_sound_design",
    "Vfx": "needs_vfx",
}

POST_SCOPE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("needs_offline_editing", "Offline Editing", "Ingest, sync, assembly, cuts, notes, picture lock, XML/AAF export."),
    ("needs_online_editing", "Online Editing", "Conform, relink media, final titles, finishing, final master exports."),
    ("needs_sound_design", "Sound Editing", "AAF check, dialogue edit, cleanup, ADR, Foley, sound design."),
    ("needs_sound_mix", "Sound Mix", "Premix, final mix, M&E, loudness, stems, final mix delivery."),
    ("needs_color_grading", "Color Grading", "Color package check, conform, grading, review, approval, graded master export."),
    ("needs_vfx", "VFX", "Breakdown, plates, assignment, VFX work, review, approval, final shot delivery."),
    ("needs_motion_graphics", "Motion graphics", "GFX, titles, and motion design."),
    ("needs_mastering_delivery", "Mastering / delivery", "Final deliverables and mastering."),
    ("needs_music", "Music", "Cue sheet, composition, temp replacement, licensing, stems delivery."),
    ("needs_qc_delivery", "QC / Delivery", "QC checks, fixes, final masters, upload, delivery confirmation, archive."),
    ("needs_machine_room", "Machine Room", "Copy, checksum, backup, storage, media transfer, archive."),
    ("needs_subtitles", "Subtitles", "Create, translate, timing, review, export, delivery."),
    ("needs_production_team", "Post-production Team", "Post-production management, coordination, and crew roles."),
    ("needs_client_guest", "Client / Guest", "External clients and guest reviewers invited to this project."),
)



def normalize_project_type_slug(raw: str | None) -> str:
    s = (raw or "").strip().casefold().replace("-", "_")
    if s in PROJECT_TYPE_SLUGS:
        return s
    legacy = (raw or "").strip().casefold()
    if legacy in _LEGACY_TYPE_TO_SLUG:
        return _LEGACY_TYPE_TO_SLUG[legacy]
    for slug in PROJECT_TYPE_SLUGS:
        if slug.replace("_", " ") == legacy:
            return slug
    return "other"


def project_type_is_tv_series(raw: str | None) -> bool:
    return normalize_project_type_slug(raw) == "tv_series"


def project_type_is_commercial(raw: str | None) -> bool:
    return normalize_project_type_slug(raw) == "commercial"


def project_type_counts_copies(raw: str | None) -> bool:
    """Commercials are planned in copies instead of episodes."""
    return project_type_is_commercial(raw)


def project_type_uses_episode_duration(raw: str | None) -> bool:
    """Only serialised formats have a per-episode target duration."""
    return project_type_is_tv_series(raw)


def project_type_shows_episode_ingest(raw: str | None) -> bool:
    """Episode metadata on ingest is optional and only shown for serialised formats."""
    return project_type_is_tv_series(raw)


def project_type_storage_slug(raw: str | None) -> str:
    """Canonical slug stored in project_type after settings save."""
    return normalize_project_type_slug(raw)


def project_type_display_label(raw: str | None) -> str:
    slug = normalize_project_type_slug(raw)
    return PROJECT_TYPE_LABELS.get(slug, (raw or "Other").strip() or "Other")


def _parse_optional_int(raw: str | None) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        v = int(s)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def _parse_optional_date(raw: str | None) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _parse_bool(form_value: str | None) -> bool:
    return (form_value or "").strip() in ("1", "on", "true", "yes")


def apply_auto_enabled_post_scopes(scope: dict[str, bool]) -> dict[str, bool]:
    """Force global auto-enabled scope keys on (e.g. Post-production Team on every project)."""
    for key in AUTO_ENABLED_POST_SCOPE_KEYS:
        if key in post_scope_key_set():
            scope[key] = True
    return scope


def post_scope_keys() -> tuple[str, ...]:
    return tuple(key for key, _, _ in POST_SCOPE_FIELDS)


def post_scope_labels() -> dict[str, str]:
    return {key: label for key, label, _ in POST_SCOPE_FIELDS}


def post_scope_key_set() -> frozenset[str]:
    return frozenset(post_scope_keys())


def parse_post_scope_keys_from_form(form: Any) -> list[str]:
    """Multi-select post scope keys from employment category forms (empty list allowed)."""
    raw: list[str] = []
    if hasattr(form, "getlist"):
        raw = list(form.getlist("post_scope_keys") or [])
    else:
        single = form.get("post_scope_keys") if form else None
        if single:
            raw = [str(single)]
    valid = post_scope_key_set()
    return sorted({k for k in raw if k in valid})


def parse_linked_post_scope_keys(raw: str | None) -> list[str]:
    if not raw:
        return []
    s = (raw or "").strip()
    if not s:
        return []
    try:
        data = json.loads(s)
        if isinstance(data, list):
            valid = post_scope_key_set()
            return sorted({str(k) for k in data if str(k) in valid})
    except (TypeError, ValueError):
        pass
    return []


def format_linked_post_scope_keys(keys: list[str] | None) -> str | None:
    valid = post_scope_key_set()
    cleaned = sorted({k for k in (keys or []) if k in valid})
    if not cleaned:
        return None
    return json.dumps(cleaned)


def post_scope_from_form(form: Any) -> dict[str, bool]:
    scope = {key: _parse_bool(form.get(key)) for key in post_scope_keys()}
    return apply_auto_enabled_post_scopes(scope)


def any_post_scope_selected(scope: dict[str, bool]) -> bool:
    return any(scope.values())


def project_has_color_grading_scope(project: Any) -> bool:
    """True when the project post-production scope includes color grading."""
    return bool(getattr(project, "needs_color_grading", False))


def project_uses_in_house_color_department(project: Any) -> bool:
    """True when project settings enable the internal Color Department board."""
    return project_has_color_grading_scope(project)


def project_enabled_post_scope_fields(project: Any) -> list[tuple[str, str, str]]:
    """Post-production scope rows enabled on this project."""
    return [row for row in POST_SCOPE_FIELDS if bool(getattr(project, row[0], False))]


def parse_assigned_post_scope_codes(value: Any) -> list[str]:
    """Split membership assigned scope field into unique scope keys (order preserved)."""
    valid = post_scope_key_set()
    out: list[str] = []
    seen: set[str] = set()
    raw = str(value or "").strip()
    if not raw:
        return out
    for part in raw.replace(";", ",").split(","):
        key = part.strip()
        if not key or key in seen:
            continue
        if key not in valid and key != "team":
            # Keep unknown keys only when they look like project scope fields.
            if not key.startswith("needs_"):
                continue
        seen.add(key)
        out.append(key)
    return out


def format_assigned_post_scope_codes(codes: list[str] | set[str] | tuple[str, ...] | None) -> str | None:
    """Serialize assigned scope keys for ProjectMember.assigned_post_scope_code."""
    ordered = parse_assigned_post_scope_codes(",".join(codes or []))
    if not ordered:
        return None
    return ",".join(ordered)


def membership_assigned_scope_keys(member: Any) -> frozenset[str]:
    return frozenset(parse_assigned_post_scope_codes(getattr(member, "assigned_post_scope_code", None)))


def collect_user_post_scope_keys(user: Any) -> frozenset[str]:
    """Scope keys linked via job title / category post scope links (needs_* project fields)."""
    valid = post_scope_key_set()
    keys: set[str] = set()
    titles = user.assigned_job_titles() if hasattr(user, "assigned_job_titles") else []
    for jt in titles:
        link_rows = [
            ln
            for ln in (getattr(jt, "post_scope_links", None) or [])
            if getattr(ln, "is_active", True)
        ]
        if not link_rows:
            cat = getattr(jt, "category", None)
            if cat is not None:
                link_rows = [
                    ln
                    for ln in (getattr(cat, "post_scope_links", None) or [])
                    if getattr(ln, "is_active", True)
                ]
        for ln in link_rows:
            entry = getattr(ln, "post_scope_entry", None)
            if entry is None:
                continue
            meta: dict[str, Any] = {}
            raw_meta = getattr(entry, "metadata_json", None)
            if raw_meta:
                try:
                    parsed = json.loads(raw_meta)
                    if isinstance(parsed, dict):
                        meta = parsed
                except (TypeError, ValueError):
                    pass
            scope_key = (meta.get("scope_key") or "").strip()
            if scope_key in valid:
                keys.add(scope_key)
    if not keys:
        # Legacy: employment category linked_post_scope_keys JSON on JobCategory
        for jt in titles:
            cat = getattr(jt, "category", None)
            if cat is None:
                continue
            linked = (
                cat.linked_scope_keys_list()
                if hasattr(cat, "linked_scope_keys_list")
                else parse_linked_post_scope_keys(getattr(cat, "linked_post_scope_keys", None))
            )
            for key in linked:
                if key in valid:
                    keys.add(key)
    if CLIENT_GUEST_SCOPE_KEY in valid and user_is_client_guest(user):
        keys.add(CLIENT_GUEST_SCOPE_KEY)
    return frozenset(keys)


def user_has_production_team_scope(user: Any) -> bool:
    """True when the user's employment categories link to Post-production Team scope."""
    return PRODUCTION_TEAM_SCOPE_KEY in collect_user_post_scope_keys(user)


def user_has_mastering_delivery_scope(user: Any) -> bool:
    """True when the user's employment categories link to Mastering / delivery scope."""
    return "needs_mastering_delivery" in collect_user_post_scope_keys(user)


def project_team_users_for_post_scope(users: list, scope_key: str) -> list:
    """Project team members whose job categories link to a post-production scope key."""
    valid = post_scope_key_set()
    if scope_key not in valid:
        return []
    out = [u for u in users if scope_key in collect_user_post_scope_keys(u)]
    return sorted(out, key=lambda row: (row.name or "").lower())


def project_team_technical_members_for_scope(users: list, scope_key: str) -> list:
    """Technical team members for a scope — excludes Post Production Management oversight roles."""
    valid = post_scope_key_set()
    if scope_key not in valid:
        return []
    out = [
        u
        for u in users
        if not user_is_post_management(u) and scope_key in collect_user_post_scope_keys(u)
    ]
    return sorted(out, key=lambda row: (row.name or "").lower())


def project_team_technical_members_for_scopes(users: list, scope_keys: tuple[str, ...] | list[str]) -> list:
    """Union of technical members across multiple post-production scope keys."""
    seen: set[int] = set()
    out: list = []
    for scope_key in scope_keys or ():
        for u in project_team_technical_members_for_scope(users, scope_key):
            uid = int(u.id)
            if uid in seen:
                continue
            seen.add(uid)
            out.append(u)
    return sorted(out, key=lambda row: (row.name or "").lower())


def _user_assigned_job_titles(user: Any) -> list:
    if hasattr(user, "assigned_job_titles"):
        return list(user.assigned_job_titles() or [])
    jt = getattr(user, "job_title", None)
    return [jt] if jt is not None else []


def _legacy_post_management_name(name: str | None) -> bool:
    from job_titles_default_catalog import LEGACY_NAME_TO_CODE, normalize_name

    n = normalize_name(name or "")
    if not n:
        return False
    legacy_code = LEGACY_NAME_TO_CODE.get(n)
    if legacy_code and legacy_code in POST_MANAGEMENT_TITLE_CODES:
        return True
    compact = n.replace(" ", "").replace("-", "")
    if "postproducer" in compact:
        return True
    if "postproductionsupervisor" in compact or "postproductionmanager" in compact:
        return True
    if "postproductioncoordinator" in compact:
        return True
    if "headofpost" in compact:
        return True
    return False


def is_post_management_title(job_title: Any) -> bool:
    """True for post producers, supervisors, coordinators, and related management titles."""
    if job_title is None:
        return False
    code = (getattr(job_title, "code", None) or "").strip().lower()
    if code in POST_MANAGEMENT_TITLE_CODES:
        return True
    category = getattr(job_title, "category", None)
    if category is not None and (getattr(category, "code", None) or "").strip().lower() == (
        "post_production_management"
    ):
        return True
    if _legacy_post_management_name(getattr(job_title, "name", None)):
        return True
    return False


def user_is_post_management(user: Any) -> bool:
    return any(is_post_management_title(jt) for jt in _user_assigned_job_titles(user))


def is_client_guest_title(job_title: Any) -> bool:
    """True for client / guest reviewer job titles."""
    if job_title is None:
        return False
    code = (getattr(job_title, "code", None) or "").strip().lower()
    if code in CLIENT_GUEST_TITLE_CODES:
        return True
    category = getattr(job_title, "category", None)
    cat_code = (getattr(category, "code", None) or "").strip().lower() if category else ""
    dept = (getattr(category, "department_code", None) or "").strip().lower() if category else ""
    if cat_code in {"client_review", "client_guest", "guest"} or dept == "client_review":
        return True
    name = (getattr(job_title, "name", None) or "").strip().casefold()
    if not name:
        return False
    return (
        "client" in name
        or name == "guest"
        or name.startswith("guest ")
        or " guest" in name
    )


def user_is_client_guest(user: Any) -> bool:
    """True when the directory user is a client/guest reviewer."""
    if any(is_client_guest_title(jt) for jt in _user_assigned_job_titles(user)):
        return True
    emp = (getattr(user, "employment_type_code", None) or "").strip().lower()
    if emp in {"client", "guest", "client_guest"}:
        return True
    for jt in _user_assigned_job_titles(user):
        aud = (getattr(jt, "user_type", None) or "").strip().lower()
        if aud == "client":
            return True
    account = getattr(user, "account", None)
    role = (getattr(account, "role", None) or "").strip().lower().replace(" ", "_")
    if role in {"guest", "client_guest", "client"}:
        return True
    return False


def post_scope_label_for_key(scope_key: str) -> str:
    for key, label, _hint in POST_SCOPE_FIELDS:
        if key == scope_key:
            return label
    return (scope_key or "").replace("needs_", "").replace("_", " ").title()


def post_management_coverage_scope_keys(user: Any, project: Any) -> list[str]:
    """Technical post scopes a management user supervises (enabled on this project)."""
    if not user_is_post_management(user):
        return []
    enabled = {key for key, _, _ in project_enabled_post_scope_fields(project)}
    linked = collect_user_post_scope_keys(user)
    order = {key: idx for idx, (key, _, _) in enumerate(POST_SCOPE_FIELDS)}
    coverage = [
        key
        for key in linked
        if key != PRODUCTION_TEAM_SCOPE_KEY and key in enabled
    ]
    return sorted(coverage, key=lambda k: (order.get(k, 999), k))


def post_management_coverage_labels(user: Any, project: Any) -> list[str]:
    return [post_scope_label_for_key(key) for key in post_management_coverage_scope_keys(user, project)]


def project_team_member_scope_keys(user: Any) -> frozenset[str]:
    """Scope keys where the user counts as a normal technical/member assignment."""
    keys = collect_user_post_scope_keys(user)
    if user_is_post_management(user):
        return frozenset({PRODUCTION_TEAM_SCOPE_KEY})
    return keys


def count_project_team_members_for_scope(users: list, scope_key: str) -> int:
    """Member count for a scope card — technical members only, not post-management oversight."""
    if scope_key == PRODUCTION_TEAM_SCOPE_KEY:
        return sum(1 for u in users if user_is_post_management(u))
    if scope_key == CLIENT_GUEST_SCOPE_KEY:
        return sum(
            1
            for u in users
            if not user_is_post_management(u) and user_is_client_guest(u)
        )
    return sum(
        1
        for u in users
        if not user_is_post_management(u) and scope_key in collect_user_post_scope_keys(u)
    )


def build_project_team_admin_warnings(users: list) -> list[str]:
    """Admin-only data-quality notes for post-management team grouping."""
    warnings: list[str] = []
    for u in users:
        if not user_is_post_management(u):
            continue
        name = (getattr(u, "name", None) or "User").strip()
        linked = collect_user_post_scope_keys(u)
        tech_linked = [k for k in linked if k != PRODUCTION_TEAM_SCOPE_KEY]
        if len(tech_linked) >= 2:
            warnings.append(
                f"{name} is Post Production Management. Scope links should display as coverage, "
                "not normal technical membership."
            )
        for jt in _user_assigned_job_titles(u):
            if not is_post_management_title(jt):
                continue
            code = (getattr(jt, "code", None) or "").strip()
            cat_code = (
                (getattr(getattr(jt, "category", None), "code", None) or "").strip().lower()
            )
            if not code and cat_code != "post_production_management":
                title_name = (getattr(jt, "name", None) or "title").strip()
                warnings.append(
                    f"{name} has a legacy/unclassified post-production title ({title_name}). "
                    "Repair job title seed or update their job title."
                )
            elif (
                not code
                and cat_code == "post_production_management"
                and _legacy_post_management_name(getattr(jt, "name", None))
            ):
                title_name = (getattr(jt, "name", None) or "title").strip()
                warnings.append(
                    f"{name} has a legacy/unclassified post-production title ({title_name}). "
                    "Repair job title seed or update their job title."
                )
    return warnings


def group_project_team_by_post_scope(
    project: Any,
    users: list,
    *,
    membership_scopes: dict[int, set[str] | frozenset[str] | list[str]] | None = None,
) -> tuple[list[dict], dict[int, list[str]]]:
    """Group project team members under each enabled post-production scope.

    When ``membership_scopes`` maps a user id to one or more assigned scope keys,
    that user is listed only under those teams — not every job-title-linked scope.
    Users without an assigned membership scope still fall back to job-title links.
    """
    enabled = project_enabled_post_scope_fields(project)
    enabled_keys = {key for key, _, _ in enabled}
    buckets: dict[str, list] = {key: [] for key, _, _ in enabled}
    oversight: dict[str, list] = {key: [] for key, _, _ in enabled}
    unassigned: list = []
    seen: dict[str, set[int]] = {key: set() for key, _, _ in enabled}
    coverage_by_user: dict[int, list[str]] = {}
    scope_map = membership_scopes or {}

    oversight_seen: dict[str, set[int]] = {key: set() for key, _, _ in enabled}

    for u in users:
        uid = int(u.id)
        if user_is_post_management(u):
            coverage_by_user[uid] = post_management_coverage_labels(u, project)
            home_key = PRODUCTION_TEAM_SCOPE_KEY
            if home_key in buckets and uid not in seen[home_key]:
                buckets[home_key].append(u)
                seen[home_key].add(uid)
            for cov_key in post_management_coverage_scope_keys(u, project):
                if cov_key in oversight and uid not in oversight_seen[cov_key]:
                    oversight[cov_key].append(u)
                    oversight_seen[cov_key].add(uid)
            continue

        assigned = {
            str(k).strip()
            for k in (scope_map.get(uid) or [])
            if str(k).strip() and str(k).strip() != "team"
        }
        assigned &= enabled_keys
        if assigned:
            matched = False
            for key in assigned:
                if key in buckets and uid not in seen[key]:
                    buckets[key].append(u)
                    seen[key].add(uid)
                    matched = True
            if not matched:
                unassigned.append(u)
            continue

        if user_is_client_guest(u) and CLIENT_GUEST_SCOPE_KEY in buckets:
            if uid not in seen[CLIENT_GUEST_SCOPE_KEY]:
                buckets[CLIENT_GUEST_SCOPE_KEY].append(u)
                seen[CLIENT_GUEST_SCOPE_KEY].add(uid)
            continue

        user_keys = collect_user_post_scope_keys(u)
        matched = False
        for key, _, _ in enabled:
            if key == PRODUCTION_TEAM_SCOPE_KEY:
                continue
            if key in user_keys:
                if uid not in seen[key]:
                    buckets[key].append(u)
                    seen[key].add(uid)
                matched = True
        if not matched:
            unassigned.append(u)

    groups: list[dict] = []
    for key, label, _ in enabled:
        members = sorted(buckets[key], key=lambda row: (row.name or "").lower())
        oversight_members = sorted(oversight[key], key=lambda row: (row.name or "").lower())
        groups.append(
            {
                "scope_key": key,
                "scope_label": label,
                "members": members,
                "count": len(members),
                "oversight": oversight_members,
                "oversight_count": len(oversight_members),
            }
        )
    if unassigned:
        members = sorted(unassigned, key=lambda row: (row.name or "").lower())
        groups.append(
            {
                "scope_key": "team",
                "scope_label": "Team",
                "members": members,
                "count": len(members),
                "oversight": [],
                "oversight_count": 0,
            }
        )
    return groups, coverage_by_user


def member_post_coverage_for_groups(_groups: list[dict], coverage_by_user: dict[int, list[str]]) -> dict[int, list[str]]:
    return coverage_by_user


def _clean_text(raw: str | None, max_len: int | None = None) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    if max_len is not None:
        return s[:max_len]
    return s


def parse_settings_form(
    form: Any,
    *,
    current_type_slug: str,
    max_episode_in_use: int,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Parse POST form into field updates. Returns (ok, errors, data)."""
    errors: list[str] = []
    data: dict[str, Any] = {}

    name = (form.get("name") or "").strip()
    if not name:
        errors.append("Project name is required.")
    data["name"] = name[:200]

    type_slug = normalize_project_type_slug(form.get("project_type"))
    if type_slug not in PROJECT_TYPE_SLUGS:
        errors.append("Invalid project type.")
    data["project_type"] = type_slug

    production_company = (form.get("production_company") or "").strip()
    if not production_company:
        errors.append("Production company is required.")
    data["production_company"] = production_company[:200]
    data["production_house"] = production_company[:200]

    director = (form.get("director") or "").strip()
    if not director:
        errors.append("Director is required.")
    data["director"] = director[:200]

    lifecycle = (form.get("lifecycle_status") or "").strip().lower()
    if lifecycle and lifecycle not in LIFECYCLE_STATUS_VALUES:
        errors.append("Invalid project status.")
    data["lifecycle_status"] = lifecycle or None

    priority = (form.get("priority") or "").strip().lower()
    if priority and priority not in PRIORITY_VALUES:
        errors.append("Invalid priority.")
    data["priority"] = priority or None

    start_d = _parse_optional_date(form.get("start_date"))
    deadline_d = _parse_optional_date(form.get("deadline_date"))
    if start_d and deadline_d and deadline_d < start_d:
        errors.append("Deadline cannot be before the start date.")
    data["start_date"] = start_d
    data["deadline_date"] = deadline_d

    data["project_code"] = _clean_text(form.get("project_code"), 80)
    data["client_name"] = _clean_text(form.get("client_name"), 200)
    data["producer_name"] = _clean_text(form.get("producer_name"), 200)
    data["description"] = _clean_text(form.get("description"))
    data["settings_notes"] = _clean_text(form.get("settings_notes"))

    pm_raw = (form.get("project_manager_id") or "").strip()
    if pm_raw:
        try:
            data["project_manager_id"] = int(pm_raw)
        except (TypeError, ValueError):
            errors.append("Invalid project manager.")
    else:
        data["project_manager_id"] = None

    # Type-specific fields (always parsed; hidden sections may still post values)
    data["season_number"] = _parse_optional_int(form.get("season_number"))
    ep_count = _parse_optional_int(form.get("number_of_episodes"))
    if ep_count is None:
        ep_count = 0
    data["number_of_episodes"] = ep_count if type_slug == "tv_series" else 0
    copy_count = _parse_optional_int(form.get("number_of_copies"))
    if copy_count is None:
        copy_count = 0
    data["number_of_copies"] = max(0, copy_count) if type_slug == "commercial" else 0
    data["estimated_shooting_days"] = _parse_optional_int(form.get("estimated_shooting_days")) or 0
    data["number_of_units"] = _parse_optional_int(form.get("number_of_units"))
    ep_dur = _parse_optional_int(form.get("episode_target_duration"))
    data["estimated_episode_duration_minutes"] = (ep_dur or 0) if type_slug == "tv_series" else 0
    data["broadcast_platform"] = _clean_text(form.get("broadcast_platform"), 200)

    data["runtime_target"] = _clean_text(form.get("runtime_target"), 80)
    data["release_target"] = _clean_text(form.get("release_target"), 120)
    data["film_format"] = _clean_text(form.get("film_format"), 120)

    data["brand_name"] = _clean_text(form.get("brand_name"), 200)
    data["agency_name"] = _clean_text(form.get("agency_name"), 200)
    data["campaign_name"] = _clean_text(form.get("campaign_name"), 200)
    data["duration_versions"] = _clean_text(form.get("duration_versions"), 255)
    data["delivery_platforms"] = _clean_text(form.get("delivery_platforms"), 255)

    data["subject"] = _clean_text(form.get("subject"), 255)
    data["locations"] = _clean_text(form.get("locations"))
    data["interview_count"] = _parse_optional_int(form.get("interview_count"))
    data["archive_material_needed"] = _parse_bool(form.get("archive_material_needed"))

    data["artist_name"] = _clean_text(form.get("artist_name"), 200)
    data["song_name"] = _clean_text(form.get("song_name"), 200)
    data["label_name"] = _clean_text(form.get("label_name"), 200)
    data["type_details_notes"] = _clean_text(form.get("type_details_notes"))

    for key, _, _ in POST_SCOPE_FIELDS:
        data[key] = _parse_bool(form.get(key))
    apply_auto_enabled_post_scopes(data)
    if not any_post_scope_selected({key: data[key] for key, _, _ in POST_SCOPE_FIELDS}):
        errors.append(POST_SCOPE_REQUIRED_MSG)
    data["archive_material_needed"] = _parse_bool(form.get("archive_material_needed"))

    data["storage_root_path"] = _clean_text(form.get("storage_root_path"), 512)
    data["upload_folder_path"] = _clean_text(form.get("upload_folder_path"), 512)
    data["frame_export_folder_path"] = _clean_text(form.get("frame_export_folder_path"), 512)
    data["delivery_folder_path"] = _clean_text(form.get("delivery_folder_path"), 512)
    data["delivery_color_path"] = _clean_text(form.get("delivery_color_path"), 512)
    data["delivery_vfx_path"] = _clean_text(form.get("delivery_vfx_path"), 512)

    data["delivery_resolution"] = _clean_text(form.get("delivery_resolution"), 32)
    data["delivery_frame_rate"] = _clean_text(form.get("delivery_frame_rate"), 32)
    data["delivery_color_space"] = _clean_text(form.get("delivery_color_space"), 32)
    data["delivery_audio_format"] = _clean_text(form.get("delivery_audio_format"), 32)
    data["delivery_format_notes"] = _clean_text(form.get("delivery_format_notes"))

    if type_slug == "tv_series" and max_episode_in_use > 0:
        if ep_count < max_episode_in_use:
            confirmed = (form.get("confirm_episode_reduce") or "").strip() == "1"
            if not confirmed:
                errors.append(
                    f"Episode count ({ep_count}) is below existing episode data (up to episode "
                    f"{max_episode_in_use}). Check the confirmation box to save anyway."
                )

    return (len(errors) == 0, errors, data)


def apply_settings_to_project(project: Any, data: dict[str, Any]) -> None:
    for key, value in data.items():
        setattr(project, key, value)


def settings_form_defaults(project: Any) -> dict[str, Any]:
    """Build template-friendly defaults from a Project instance."""
    slug = normalize_project_type_slug(getattr(project, "project_type", None))
    prod_co = getattr(project, "production_company", None) or getattr(project, "production_house", None) or ""
    return {
        "type_slug": slug,
        "type_label": project_type_display_label(project.project_type),
        "production_company": prod_co,
        "lifecycle_status": getattr(project, "lifecycle_status", None) or "development",
        "priority": getattr(project, "priority", None) or "medium",
    }
