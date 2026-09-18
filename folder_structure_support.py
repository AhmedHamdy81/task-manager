"""Project folder structure templates, validation, and safe idempotent creation."""

from __future__ import annotations

import errno
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Any

from folder_structure_templates import POST_PRODUCTION_FULL_TEMPLATE

DEFAULT_TEMPLATE_KEY = "post_production_full"
CUSTOM_TEMPLATE_KEY = "custom"
CUSTOM_TEMPLATE_PREFIX = "custom:"

FOLDER_TEMPLATE_LABELS: dict[str, str] = {
    "post_production_full": "Post-Production Full Template",
    "simple_editorial": "Simple Editorial Template",
    "vfx": "VFX Template",
}

SIMPLE_EDITORIAL_TEMPLATE: tuple[str, ...] = (
    "00_ADMIN",
    "00_ADMIN/Brief",
    "00_ADMIN/Schedules",
    "01_SCRIPT",
    "01_SCRIPT/Original_Script",
    "01_SCRIPT/Revised_Scripts",
    "02_PROJECT_FILES",
    "02_PROJECT_FILES/Premiere",
    "02_PROJECT_FILES/Premiere/Main_Project",
    "03_MEDIA",
    "03_MEDIA/PROXIES",
    "03_MEDIA/PROXIES/Day_001",
    "04_EDITORIAL",
    "04_EDITORIAL/Rough_Cuts",
    "04_EDITORIAL/Fine_Cuts",
    "04_EDITORIAL/Edit_Exports",
    "14_EXPORTS",
    "14_EXPORTS/Client_Review",
    "14_EXPORTS/Internal_Review",
    "15_DELIVERY",
    "15_DELIVERY/FINAL_MASTER",
)

VFX_TEMPLATE: tuple[str, ...] = (
    "00_ADMIN",
    "00_ADMIN/Brief",
    "03_MEDIA",
    "03_MEDIA/CAMERA_ORIGINALS",
    "03_MEDIA/PROXIES",
    "05_EXCHANGE",
    "05_EXCHANGE/TO_VFX",
    "05_EXCHANGE/TO_VFX/Plates",
    "05_EXCHANGE/TO_VFX/References",
    "05_EXCHANGE/TO_VFX/EDL_XML",
    "05_EXCHANGE/TO_VFX/Notes",
    "05_EXCHANGE/FROM_VFX",
    "05_EXCHANGE/FROM_VFX/WIP",
    "05_EXCHANGE/FROM_VFX/Approved",
    "05_EXCHANGE/FROM_VFX/Final_Renders",
    "08_VFX",
    "08_VFX/Shot_List",
    "08_VFX/Plates",
    "08_VFX/Pulls",
    "08_VFX/References",
    "08_VFX/WIP",
    "08_VFX/Review",
    "08_VFX/Approved",
    "08_VFX/Final_Renders",
    "08_VFX/Nuke",
    "08_VFX/After_Effects",
    "08_VFX/Mattes",
    "08_VFX/Reports",
)

FOLDER_TEMPLATES: dict[str, tuple[str, ...]] = {
    "post_production_full": POST_PRODUCTION_FULL_TEMPLATE,
    "simple_editorial": SIMPLE_EDITORIAL_TEMPLATE,
    "vfx": VFX_TEMPLATE,
}

_UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|]')

_BLOCKED_ROOTS_UNIX_EXACT = frozenset(
    {
        "/",
        "/bin",
        "/usr",
        "/etc",
        "/sbin",
        "/dev",
        "/proc",
    }
)

_BLOCKED_ROOTS_UNIX_PREFIX = (
    "/System",
    "/Library",
    "/bin/",
    "/usr/",
    "/etc/",
    "/sbin/",
    "/dev/",
    "/proc/",
)

_BLOCKED_ROOTS_WINDOWS = frozenset(
    {
        "C:\\",
        "C:\\Windows",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
        "C:\\ProgramData",
        "C:\\Users\\Default",
    }
)

QUICK_FOLDER_LINKS: tuple[tuple[str, str], ...] = (
    ("Project Folder", ""),
    ("Project Files", "02_PROJECT_FILES"),
    ("Media", "03_MEDIA"),
    ("Proxies", "03_MEDIA/PROXIES"),
    ("Exchange", "05_EXCHANGE"),
    ("To Sound", "05_EXCHANGE/TO_SOUND"),
    ("From Sound", "05_EXCHANGE/FROM_SOUND"),
    ("To Color", "05_EXCHANGE/TO_COLOR"),
    ("From Color", "05_EXCHANGE/FROM_COLOR"),
    ("To VFX", "05_EXCHANGE/TO_VFX"),
    ("From VFX", "05_EXCHANGE/FROM_VFX"),
    ("Sound", "06_SOUND"),
    ("Color", "07_COLOR"),
    ("VFX", "08_VFX"),
    ("Music", "09_MUSIC"),
    ("Graphics / PSD", "10_GRAPHICS_DESIGN/PSD"),
    ("Used Fonts", "11_USED_FONTS"),
    ("Downloads", "12_DOWNLOADS"),
    ("Exports", "14_EXPORTS"),
    ("Delivery", "15_DELIVERY"),
    ("Archive", "17_ARCHIVE"),
)

LEGACY_STORAGE_PATH_CANDIDATES: dict[str, tuple[str, ...]] = {
    "upload_folder_path": ("03_MEDIA", "03_MEDIA/PROXIES", "12_DOWNLOADS"),
    "frame_export_folder_path": (
        "04_EDITORIAL/Edit_Exports",
        "14_EXPORTS",
        "14_EXPORTS/Internal_Review",
    ),
    "delivery_folder_path": ("15_DELIVERY", "15_DELIVERY/FINAL_MASTER"),
    "delivery_color_path": ("07_COLOR", "05_EXCHANGE/FROM_COLOR", "05_EXCHANGE/TO_COLOR"),
    "delivery_vfx_path": (
        "08_VFX/Final_Renders",
        "08_VFX",
        "05_EXCHANGE/FROM_VFX/Final_Renders",
        "05_EXCHANGE/FROM_VFX",
    ),
}


def pick_template_subfolder(rel_paths: list[str], candidates: tuple[str, ...]) -> str | None:
    path_set = {p.strip() for p in rel_paths if (p or "").strip()}
    for candidate in candidates:
        if candidate in path_set:
            return candidate
    return None


def suggest_legacy_storage_paths(project_folder: str, rel_paths: list[str]) -> dict[str, str]:
    """Map template subfolders to legacy project settings path fields."""
    base = (project_folder or "").strip().rstrip("/\\")
    suggestions: dict[str, str] = {}
    if base:
        suggestions["storage_root_path"] = base
    for field, candidates in LEGACY_STORAGE_PATH_CANDIDATES.items():
        rel = pick_template_subfolder(rel_paths, candidates)
        if rel and base:
            suggestions[field] = os.path.join(base, rel.replace("/", os.sep))
    return suggestions


def is_valid_project_folder_name(name: str) -> bool:
    cleaned = (name or "").strip()
    if not cleaned:
        return False
    if _UNSAFE_CHARS.search(cleaned) or "/" in cleaned or "\\" in cleaned:
        return False
    return True


def safe_project_folder_name(name: str | None, project_id: int | None = None) -> str:
    """Sanitize a project name for use as a folder name on disk."""
    raw = (name or "").strip()
    cleaned = re.sub(r"\s+", "_", raw)
    cleaned = _UNSAFE_CHARS.sub("_", cleaned)
    cleaned = cleaned.strip("._")
    if not cleaned:
        return f"Project_{project_id}" if project_id is not None else "Project"
    return cleaned[:200]


def get_folder_template(template_key: str | None, project: Any | None = None) -> list[str]:
    key = (template_key or DEFAULT_TEMPLATE_KEY).strip().lower()
    if project is not None:
        templates = custom_templates_for_project(project)
        if key.startswith(CUSTOM_TEMPLATE_PREFIX):
            slug = key[len(CUSTOM_TEMPLATE_PREFIX) :]
            entry = templates.get(slug)
            if entry:
                return list(entry["paths"])
        elif key == CUSTOM_TEMPLATE_KEY and templates:
            first = sorted(templates.items(), key=lambda item: item[1]["label"].lower())[0]
            return list(first[1]["paths"])
    tpl = FOLDER_TEMPLATES.get(key)
    if tpl is None:
        tpl = FOLDER_TEMPLATES[DEFAULT_TEMPLATE_KEY]
    return list(tpl)


def slugify_template_name(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")[:48]
    return slug or "custom_template"


def custom_template_storage_key(slug: str) -> str:
    return f"{CUSTOM_TEMPLATE_PREFIX}{slugify_template_name(slug)}"


def parse_custom_templates_store(raw: Any) -> dict[str, dict[str, Any]]:
    if not raw:
        return {}
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for raw_slug, entry in data.items():
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or raw_slug).strip()[:120]
        paths, path_errors = normalize_custom_template_paths(
            [str(p) for p in (entry.get("paths") or [])]
        )
        if path_errors or not paths:
            continue
        slug = slugify_template_name(str(raw_slug) or label)
        out[slug] = {"label": label or slug, "paths": paths}
    return out


def custom_templates_for_project(project: Any | None) -> dict[str, dict[str, Any]]:
    if project is None:
        return {}
    store = parse_custom_templates_store(getattr(project, "folder_custom_templates", None))
    if store:
        return store
    paths = parse_folder_template_paths_json(getattr(project, "folder_template_paths", None))
    if not paths:
        return {}
    label = (getattr(project, "folder_template_custom_label", None) or "").strip() or "Custom template"
    slug = slugify_template_name(label)
    return {slug: {"label": label, "paths": paths}}


def list_custom_templates_for_project(project: Any | None) -> list[dict[str, Any]]:
    templates = custom_templates_for_project(project)
    items: list[dict[str, Any]] = []
    for slug, entry in sorted(templates.items(), key=lambda item: item[1]["label"].lower()):
        items.append(
            {
                "slug": slug,
                "key": custom_template_storage_key(slug),
                "label": entry["label"],
                "folder_count": len(entry["paths"]),
            }
        )
    return items


def custom_template_paths_for_project(project: Any | None) -> list[str]:
    if project is None:
        return []
    key = (getattr(project, "folder_template_key", None) or "").strip().lower()
    return get_folder_template(key or CUSTOM_TEMPLATE_KEY, project)


def folder_template_label_for_key(project: Any | None, template_key: str | None) -> str:
    key = (template_key or DEFAULT_TEMPLATE_KEY).strip().lower()
    if project is not None and key.startswith(CUSTOM_TEMPLATE_PREFIX):
        slug = key[len(CUSTOM_TEMPLATE_PREFIX) :]
        entry = custom_templates_for_project(project).get(slug)
        if entry:
            return format_custom_template_option_label(entry["label"], len(entry["paths"]))
    if project is not None and key == CUSTOM_TEMPLATE_KEY:
        templates = custom_templates_for_project(project)
        if templates:
            first = sorted(templates.items(), key=lambda item: item[1]["label"].lower())[0]
            return format_custom_template_option_label(first[1]["label"], len(first[1]["paths"]))
    return FOLDER_TEMPLATE_LABELS.get(key, key)


def folder_template_label_for_project(project: Any | None) -> str:
    if project is None:
        return "Custom template"
    return folder_template_label_for_key(project, getattr(project, "folder_template_key", None))


def format_custom_template_option_label(label: str, folder_count: int) -> str:
    name = (label or "").strip() or "Custom template"
    count = max(0, int(folder_count or 0))
    return f"Custom · {name} ({count} folder{'s' if count != 1 else ''})"


def folder_template_options_for_project(project: Any | None) -> dict[str, str]:
    options = dict(FOLDER_TEMPLATE_LABELS)
    for slug, entry in sorted(
        custom_templates_for_project(project).items(),
        key=lambda item: item[1]["label"].lower(),
    ):
        options[custom_template_storage_key(slug)] = format_custom_template_option_label(
            entry["label"], len(entry["paths"])
        )
    return options


def unique_custom_template_label(project: Any, label: str) -> str:
    """Return a label that does not collide with an existing custom template slug."""
    name = (label or "").strip()[:120] or "Custom template"
    templates = custom_templates_for_project(project)
    slug = slugify_template_name(name)
    if slug not in templates:
        return name
    base = name[:100]
    i = 2
    while True:
        candidate = f"{base} ({i})"
        if slugify_template_name(candidate) not in templates:
            return candidate[:120]
        i += 1


def import_custom_folder_template(
    project: Any,
    paths: list[str],
    label: str = "",
) -> tuple[str | None, list[str]]:
    """Copy a custom template into this project's library (auto-renames on conflict)."""
    name = unique_custom_template_label(project, label)
    return save_custom_folder_template(project, paths, name)


def list_importable_custom_templates_from_projects(
    projects: list[Any],
    *,
    target_project_id: int,
) -> list[dict[str, Any]]:
    """Custom templates from other projects that are not already on the target project."""
    target = next(
        (p for p in projects if int(getattr(p, "id", 0) or 0) == int(target_project_id)),
        None,
    )
    existing_path_sets = {
        tuple(entry["paths"]) for entry in custom_templates_for_project(target).values()
    }
    items: list[dict[str, Any]] = []
    seen_path_sets: set[tuple[str, ...]] = set(existing_path_sets)
    for project in projects:
        pid = int(getattr(project, "id", 0) or 0)
        if pid == int(target_project_id):
            continue
        project_name = (getattr(project, "name", None) or f"Project {pid}").strip()
        for slug, entry in sorted(
            custom_templates_for_project(project).items(),
            key=lambda item: item[1]["label"].lower(),
        ):
            path_key = tuple(entry["paths"])
            if path_key in seen_path_sets:
                continue
            seen_path_sets.add(path_key)
            items.append(
                {
                    "source_project_id": pid,
                    "source_project_name": project_name,
                    "slug": slug,
                    "key": custom_template_storage_key(slug),
                    "label": entry["label"],
                    "folder_count": len(entry["paths"]),
                }
            )
    items.sort(key=lambda row: (row["label"].lower(), row["source_project_name"].lower()))
    return items


def parse_folder_template_paths_json(raw: Any) -> list[str]:
    if not raw:
        return []
    paths: list[Any]
    if isinstance(raw, list):
        paths = raw
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        paths = parsed
    else:
        return []
    normalized, _errors = normalize_custom_template_paths([str(p) for p in paths])
    return normalized


def save_custom_folder_template(
    project: Any,
    paths: list[str],
    label: str = "",
    *,
    overwrite_slug: str | None = None,
) -> tuple[str | None, list[str]]:
    normalized, errors = normalize_custom_template_paths(paths)
    if errors:
        return None, errors
    if not normalized:
        return None, ["Select at least one folder for the template."]
    name = (label or "").strip()[:120]
    if not name:
        return None, ["Template name is required."]

    templates = dict(custom_templates_for_project(project))
    if overwrite_slug:
        slug = slugify_template_name(overwrite_slug)
        if slug not in templates:
            return None, ["Selected template was not found."]
    else:
        slug = slugify_template_name(name)
        if slug in templates:
            return None, [
                f'A template named "{templates[slug]["label"]}" already exists. Select it below to overwrite, or choose a different name.'
            ]

    templates[slug] = {"label": name, "paths": normalized}
    storage_key = custom_template_storage_key(slug)
    project.folder_custom_templates = json.dumps(templates)
    project.folder_template_key = storage_key
    project.folder_template_paths = json.dumps(normalized)
    project.folder_template_custom_label = name
    return storage_key, []


def is_known_folder_template_key(template_key: str | None, project: Any | None = None) -> bool:
    key = (template_key or "").strip().lower()
    if key in FOLDER_TEMPLATES:
        return True
    if key.startswith(CUSTOM_TEMPLATE_PREFIX):
        slug = key[len(CUSTOM_TEMPLATE_PREFIX) :]
        return slug in custom_templates_for_project(project)
    if key == CUSTOM_TEMPLATE_KEY and custom_templates_for_project(project):
        return True
    return False


def _ancestor_paths(rel: str) -> list[str]:
    parts = [p for p in (rel or "").replace("\\", "/").split("/") if p]
    return ["/".join(parts[: i + 1]) for i in range(max(0, len(parts) - 1))]


def _with_ancestor_paths(rel_paths: list[str]) -> set[str]:
    out: set[str] = set()
    for rel in rel_paths:
        cleaned = (rel or "").replace("\\", "/").strip("/")
        if not cleaned:
            continue
        out.add(cleaned)
        out.update(_ancestor_paths(cleaned))
    return out


def _mkdir_blocked_message(path: str, exc: OSError) -> str:
    if getattr(exc, "errno", None) != errno.EPERM:
        return f"Could not create {path}: {exc}"
    root = os.path.dirname(path.rstrip(os.sep)) or path
    return (
        f"macOS blocked this server from writing to {root} "
        f"(Operation not permitted). Finder can still have access. "
        f"Restart the app from Terminal.app (not a sandboxed Cursor terminal) "
        f"so Python can write to network volumes, then try Create again."
    )


def _relative_path_safe(rel: str) -> bool:
    if not rel or rel.startswith("/") or rel.startswith("\\"):
        return False
    parts = rel.replace("\\", "/").split("/")
    return all(part and part not in (".", "..") for part in parts)


def normalize_custom_template_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        rel = (raw or "").strip().replace("\\", "/").strip("/")
        if not rel:
            continue
        if not _relative_path_safe(rel):
            errors.append(f"Invalid folder path: {raw}")
            continue
        if rel in seen:
            continue
        seen.add(rel)
        normalized.append(rel)
    normalized.sort(key=lambda s: s.lower())
    return normalized, errors



def is_absolute_storage_path(path: str | None) -> bool:
    raw = (path or "").strip()
    if not raw:
        return False
    if raw.startswith(("/", "\\")):
        return True
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        return True
    return False


def sanitize_project_root_path(root: str | None, folder_name: str | None = None) -> str:
    """Drop mistaken folder-name values; only keep absolute parent paths."""
    raw = (root or "").strip()
    if not raw:
        return ""
    folder = (folder_name or "").strip()
    if folder and raw == folder:
        return ""
    if folder:
        base = raw.replace("\\", "/").rstrip("/").split("/")[-1]
        if base == folder and not is_absolute_storage_path(raw):
            return ""
    if not is_absolute_storage_path(raw):
        return ""
    return raw


def sanitize_legacy_storage_path(path: str | None) -> str:
    raw = (path or "").strip()
    if not raw:
        return ""
    return raw if is_absolute_storage_path(raw) else ""


def join_project_root_and_folder(root: str, folder_name: str) -> str:
    root = (root or "").strip().rstrip("/\\")
    folder_name = (folder_name or "").strip().strip("/\\")
    if not root and not folder_name:
        return ""
    if not folder_name:
        return root
    if not root:
        return folder_name
    if root == folder_name:
        return root
    root_base = root.replace("\\", "/").rsplit("/", 1)[-1]
    if root_base == folder_name:
        return root
    if root.endswith("/" + folder_name) or root.endswith("\\" + folder_name):
        return root
    return os.path.join(root, folder_name)


def effective_project_root_path(project: Any) -> str:
    folder = effective_project_folder_name(project)
    root = sanitize_project_root_path(
        getattr(project, "project_root_path", None), folder
    )
    if root:
        return root
    return sanitize_project_root_path(
        getattr(project, "storage_root_path", None), folder
    )


def effective_project_folder_name(project: Any) -> str:
    custom = (getattr(project, "project_folder_name", None) or "").strip()
    if custom:
        return custom
    return safe_project_folder_name(getattr(project, "name", None), getattr(project, "id", None))


def build_project_folder_path(project: Any) -> str:
    root = effective_project_root_path(project)
    folder_name = effective_project_folder_name(project)
    return join_project_root_and_folder(root, folder_name)


def legacy_storage_paths_for_settings_form(project: Any) -> dict[str, str]:
    return {
        "storage_root_path": sanitize_legacy_storage_path(
            getattr(project, "storage_root_path", None)
        ),
        "upload_folder_path": sanitize_legacy_storage_path(
            getattr(project, "upload_folder_path", None)
        ),
        "frame_export_folder_path": sanitize_legacy_storage_path(
            getattr(project, "frame_export_folder_path", None)
        ),
        "delivery_folder_path": sanitize_legacy_storage_path(
            getattr(project, "delivery_folder_path", None)
        ),
        "delivery_color_path": sanitize_legacy_storage_path(
            getattr(project, "delivery_color_path", None)
        ),
        "delivery_vfx_path": sanitize_legacy_storage_path(
            getattr(project, "delivery_vfx_path", None)
        ),
    }


def _normalize_abs_path(path: str) -> str:
    expanded = os.path.expanduser((path or "").strip())
    return os.path.normpath(os.path.abspath(expanded))


def is_safe_storage_root(path: str) -> tuple[bool, str]:
    """Return (ok, error_message). Rejects traversal, system roots, and non-allowlisted roots."""
    from path_security import validate_storage_root

    return validate_storage_root(path)


def resolve_selected_template_paths(
    template_key: str | None,
    selected_paths: list[str] | None,
    project: Any | None = None,
    *,
    template_paths_override: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Filter template paths to a user selection. None means all template paths."""
    if template_paths_override is not None:
        rel_paths, norm_errors = normalize_custom_template_paths(template_paths_override)
        if norm_errors:
            return [], norm_errors
    else:
        rel_paths = get_folder_template(template_key, project)
    if not selected_paths:
        # None or [] → whole template. Create must not no-op when the tree
        # preview has nothing checked.
        return rel_paths, []

    template_set = _with_ancestor_paths(rel_paths)
    chosen: set[str] = set()
    errors: list[str] = []
    for raw in selected_paths:
        rel = (raw or "").strip().replace("\\", "/").strip("/")
        if not rel:
            continue
        if not _relative_path_safe(rel):
            errors.append(f"Invalid folder path: {raw}")
            continue
        if rel not in template_set:
            errors.append(f"Folder not in template: {rel}")
            continue
        chosen.add(rel)
        chosen.update(_ancestor_paths(rel))

    if errors:
        return [], errors
    if not chosen:
        return rel_paths, []

    ordered = [p for p in rel_paths if p in chosen]
    extras = [p for p in sorted(chosen, key=str.lower) if p not in set(ordered)]
    return ordered + extras, []


def _absolute_paths_for_template(
    project: Any,
    template_key: str | None = None,
    *,
    selected_paths: list[str] | None = None,
    template_paths_override: list[str] | None = None,
) -> tuple[str, list[str], list[str]]:
    key = template_key or getattr(project, "folder_template_key", None)
    rel_paths, sel_errors = resolve_selected_template_paths(
        key,
        selected_paths,
        project,
        template_paths_override=template_paths_override,
    )
    project_folder = build_project_folder_path(project)
    errors: list[str] = list(sel_errors)
    abs_paths: list[str] = []
    if not project_folder:
        errors.append("Project root path and folder name are required.")
        return project_folder, rel_paths, errors
    root_ok, root_err = is_safe_storage_root(effective_project_root_path(project))
    if not root_ok:
        errors.append(root_err)
        return project_folder, rel_paths, errors
    for rel in rel_paths:
        if not _relative_path_safe(rel):
            errors.append(f"Unsafe template path: {rel}")
            continue
        abs_paths.append(os.path.join(project_folder, rel.replace("/", os.sep)))
    return project_folder, rel_paths, errors


def build_folder_tree(relative_paths: list[str]) -> list[dict[str, Any]]:
    """Nested tree nodes: {name, path, children}."""
    root: dict[str, Any] = {"name": "", "path": "", "children": {}}

    for rel in relative_paths:
        if not rel:
            continue
        parts = rel.split("/")
        node = root
        built: list[str] = []
        for part in parts:
            built.append(part)
            children = node.setdefault("children", {})
            key = part
            if key not in children:
                children[key] = {
                    "name": part,
                    "path": "/".join(built),
                    "children": {},
                }
            node = children[key]

    def _to_list(node_map: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for name in sorted(node_map.keys(), key=lambda s: s.lower()):
            child = node_map[name]
            items.append(
                {
                    "name": child["name"],
                    "path": child["path"],
                    "children": _to_list(child.get("children") or {}),
                }
            )
        return items

    return _to_list(root.get("children") or {})


def validate_project_folder_structure(
    project: Any,
    *,
    template_key: str | None = None,
    selected_paths: list[str] | None = None,
    template_paths_override: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    key = template_key or getattr(project, "folder_template_key", None) or DEFAULT_TEMPLATE_KEY
    project_folder, rel_paths, errors = _absolute_paths_for_template(
        project,
        key,
        selected_paths=selected_paths,
        template_paths_override=template_paths_override,
    )
    abs_paths = [
        os.path.join(project_folder, rel.replace("/", os.sep))
        for rel in rel_paths
        if project_folder
    ]
    existing: list[str] = []
    missing: list[str] = []

    root = effective_project_root_path(project)
    if root and not errors:
        root_abs = _normalize_abs_path(root)
        if not os.path.isdir(root_abs):
            errors.append("Root path does not exist. Create it first or choose another path.")

    if project_folder and not errors:
        if os.path.isdir(project_folder):
            existing.append(".")
        else:
            missing.append(".")

    for rel, abs_path in zip(rel_paths, abs_paths):
        if errors:
            break
        if os.path.isdir(abs_path):
            existing.append(rel)
        else:
            missing.append(rel)

    if now is not None and hasattr(project, "folder_structure_validated_at"):
        project.folder_structure_validated_at = now

    return {
        "project_folder": project_folder,
        "template_key": key,
        "total": len(rel_paths) + (1 if project_folder else 0),
        "existing": existing,
        "missing": missing,
        "errors": errors,
        "created_count": 0,
        "existing_count": len(existing),
        "missing_count": len(missing),
    }


def create_project_folder_structure(
    project: Any,
    *,
    template_key: str | None = None,
    selected_paths: list[str] | None = None,
    template_paths_override: list[str] | None = None,
    create_root: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    key = template_key or getattr(project, "folder_template_key", None) or DEFAULT_TEMPLATE_KEY
    report = validate_project_folder_structure(
        project,
        template_key=key,
        selected_paths=selected_paths,
        template_paths_override=template_paths_override,
        now=None,
    )
    if report["errors"]:
        return report

    root = effective_project_root_path(project)
    root_abs = _normalize_abs_path(root)
    created = 0
    already = 0

    if not os.path.isdir(root_abs):
        if create_root:
            os.makedirs(root_abs, exist_ok=True)
            created += 1
        else:
            report["errors"].append(
                "Root path does not exist. Create it first or choose another path."
            )
            return report

    project_folder = build_project_folder_path(project)
    rel_paths, _ = resolve_selected_template_paths(
        key,
        selected_paths,
        project,
        template_paths_override=template_paths_override,
    )
    paths_to_create = [project_folder] + [
        os.path.join(project_folder, rel.replace("/", os.sep)) for rel in rel_paths
    ]

    for path in paths_to_create:
        existed = os.path.isdir(path)
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            report["errors"].append(_mkdir_blocked_message(path, exc))
            if getattr(exc, "errno", None) == errno.EPERM:
                break
            continue
        if existed:
            already += 1
        else:
            created += 1

    create_errors = list(report.get("errors") or [])
    report = validate_project_folder_structure(
        project,
        template_key=key,
        selected_paths=selected_paths,
        template_paths_override=template_paths_override,
        now=now if not create_errors else None,
    )
    report["created_count"] = created
    report["existing_count"] = already
    if create_errors:
        report["errors"] = create_errors + list(report.get("errors") or [])
    elif created == 0 and already == 0 and paths_to_create:
        report["errors"].append(
            "No folders were created. Check that the project root path exists and is writable."
        )
    if report["errors"]:
        return report
    if now is not None:
        if hasattr(project, "folder_structure_created_at"):
            project.folder_structure_created_at = now
        if hasattr(project, "folder_structure_validated_at"):
            project.folder_structure_validated_at = now
    return report


def build_quick_links(project: Any) -> list[dict[str, Any]]:
    project_folder = build_project_folder_path(project)
    links: list[dict[str, Any]] = []
    for label, rel in QUICK_FOLDER_LINKS:
        abs_path = project_folder if not rel else os.path.join(project_folder, rel.replace("/", os.sep))
        exists = bool(project_folder and os.path.isdir(abs_path))
        links.append(
            {
                "label": label,
                "relative_path": rel or ".",
                "absolute_path": abs_path,
                "exists": exists,
            }
        )
    return links


def open_folder_in_os(path: str) -> tuple[bool, str]:
    """Open folder in Finder/Explorer when running locally."""
    folder = (path or "").strip()
    if not folder or not os.path.isdir(folder):
        return False, "Folder does not exist."
    abs_path = _normalize_abs_path(folder).rstrip("/\\") or _normalize_abs_path(folder)
    try:
        if sys.platform == "darwin":
            # Prefer Finder via AppleScript — same approach as the native folder
            # picker. Plain `open` often fails (LaunchServices -10661) when the
            # Flask process was not started from a normal macOS GUI session.
            posix_literal = json.dumps(abs_path)
            script = (
                f"set p to POSIX file {posix_literal}\n"
                "tell application \"Finder\"\n"
                "  reveal p\n"
                "  activate\n"
                "end tell"
            )
            completed = subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if completed.returncode == 0:
                return True, abs_path
            # Fallback for environments where AppleScript is blocked but `open` works.
            fallback = subprocess.run(
                ["open", abs_path],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if fallback.returncode == 0:
                return True, abs_path
            err = (
                (completed.stderr or "").strip()
                or (fallback.stderr or "").strip()
                or (completed.stdout or "").strip()
                or "Could not open Finder."
            )
            return False, err
        if sys.platform.startswith("win"):
            os.startfile(abs_path)  # type: ignore[attr-defined]
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", abs_path], check=True)
        else:
            return False, "Open folder is not supported on this platform."
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return True, abs_path


def storage_summary_for_project(project: Any) -> dict[str, Any]:
    key = getattr(project, "folder_template_key", None) or DEFAULT_TEMPLATE_KEY
    return {
        "project_root_path": effective_project_root_path(project),
        "project_folder_name": effective_project_folder_name(project),
        "project_folder_path": build_project_folder_path(project),
        "folder_template_key": key,
        "folder_template_label": folder_template_label_for_key(project, key),
        "folder_structure_created_at": getattr(project, "folder_structure_created_at", None),
        "folder_structure_validated_at": getattr(project, "folder_structure_validated_at", None),
        "template_folder_count": len(get_folder_template(key, project)),
    }
