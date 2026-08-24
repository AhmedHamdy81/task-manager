"""Post-production task title presets by scope — constants and restore helpers."""

from __future__ import annotations

from typing import Any

import conform_task_support as cts


def _conform_reason_for_task_row(task: Any, detail: Any | None) -> str | None:
    text = cts.task_conform_reason_text(task, detail)
    return text or None


TASK_PRESET_SCOPE_FIELDS: tuple[tuple[str, str, str], ...] = (
    (
        "needs_offline_editing",
        "Offline Editing",
        "Ingest, sync, assembly, cuts, notes, picture lock, XML/AAF export.",
    ),
    (
        "needs_online_editing",
        "Online Editing",
        "Conform, relink media, final titles, finishing, final master exports.",
    ),
    (
        "needs_color_grading",
        "Color Grading",
        "Color package check, conform, grading, review, approval, graded master export.",
    ),
    (
        "needs_vfx",
        "VFX",
        "Breakdown, plates, assignment, VFX work, review, approval, final shot delivery.",
    ),
    (
        "needs_sound_design",
        "Sound Editing",
        "AAF check, dialogue edit, cleanup, ADR, Foley, sound design.",
    ),
    (
        "needs_sound_mix",
        "Sound Mix",
        "Premix, final mix, M&E, loudness, stems, final mix delivery.",
    ),
    (
        "needs_music",
        "Music",
        "Cue sheet, composition, temp replacement, licensing, stems delivery.",
    ),
    (
        "needs_subtitles",
        "Subtitles",
        "Create, translate, timing, review, export, delivery.",
    ),
    (
        "needs_qc_delivery",
        "QC / Delivery",
        "QC checks, fixes, final masters, upload, delivery confirmation, archive.",
    ),
    (
        "needs_machine_room",
        "Machine Room",
        "Copy, checksum, backup, storage, media transfer, archive.",
    ),
)

DEFAULT_TASK_TITLES_BY_SCOPE: dict[str, tuple[str, ...]] = {
    "needs_offline_editing": (
        "Ingest media",
        "Copy and verify media",
        "Organize footage",
        "Create proxies",
        "Sync audio/video",
        "Prepare edit project",
        "Assembly edit",
        "Rough cut",
        "Fine cut",
        "Apply notes",
        "Upload review version",
        "Prepare picture lock",
        "Export XML / AAF / EDL",
        "Send to VFX",
        "Send to Color",
        "Send to Sound",
    ),
    "needs_online_editing": (
        "Receive XML / AAF / EDL",
        "Conform timeline",
        "Relink high-resolution media",
        "Match offline reference",
        "Check speed changes",
        "Check reframes",
        "Insert final VFX",
        "Add final titles",
        "Add logos / legal cards",
        "Check final duration",
        "Export final master",
        "Export textless version",
        "Export clean version",
        "Export social versions",
        "Archive online project",
    ),
    "needs_color_grading": (
        "Receive XML / offline reference",
        "Receive source media",
        "Check color package",
        "Import XML",
        "Conform timeline",
        "Match offline reference",
        "Check VFX shots",
        "Apply base grade",
        "Match cameras",
        "Grade scenes",
        "Export color review version",
        "Apply color notes",
        "Upload revised color version",
        "Approve color",
        "Export graded master",
        "Export textless graded version",
        "Archive color project",
    ),
    "needs_vfx": (
        "Create VFX breakdown",
        "Identify VFX shots",
        "Create shot codes",
        "Upload references",
        "Upload plates / clean plates",
        "Prepare shot brief",
        "Assign artists/vendors",
        "Roto",
        "Paint cleanup",
        "Tracking",
        "Keying",
        "Compositing",
        "Screen replacement",
        "Object removal",
        "Set extension",
        "CG integration",
        "Upload VFX version",
        "Review VFX",
        "Apply VFX notes",
        "Approve shot",
        "Deliver final VFX to edit/color",
        "Archive VFX files",
    ),
    "needs_sound_design": (
        "Receive picture lock reference",
        "Receive AAF / OMF",
        "Check sync",
        "Organize audio tracks",
        "Dialogue edit",
        "Clean dialogue",
        "Noise reduction",
        "Prepare ADR list",
        "Edit ADR",
        "Add ambience",
        "Add sound effects",
        "Add Foley",
        "Add room tone",
        "Upload sound edit version",
        "Prepare for mix",
    ),
    "needs_sound_mix": (
        "Dialogue premix",
        "FX premix",
        "Music premix",
        "Final stereo mix",
        "Final 5.1 mix",
        "M&E mix",
        "Loudness check",
        "Apply mix notes",
        "Upload mix review",
        "Approve final mix",
        "Export final WAV",
        "Export stems",
        "Deliver mix files",
    ),
    "needs_music": (
        "Prepare cue sheet",
        "Compose music cues",
        "Edit temp music",
        "Replace temp music",
        "License music",
        "Review music",
        "Apply music notes",
        "Export final music",
        "Export stems",
        "Deliver music files",
    ),
    "needs_subtitles": (
        "Create subtitles",
        "Translate subtitles",
        "Spot timing",
        "Check spelling",
        "Review subtitles",
        "Export SRT",
        "Export STL / SCC / XML",
        "Burn-in subtitles if needed",
        "Deliver subtitle package",
    ),
    "needs_qc_delivery": (
        "Check picture",
        "Check sound",
        "Check sync",
        "Check black frames",
        "Check flash frames",
        "Check titles/spelling",
        "Check loudness",
        "Check delivery specs",
        "Generate QC report",
        "Fix QC issues",
        "Export ProRes master",
        "Export H.264 review file",
        "Export broadcast master",
        "Export social versions",
        "Upload final delivery",
        "Confirm delivery received",
        "Archive final masters",
    ),
    "needs_machine_room": (
        "Create folder structure",
        "Copy camera cards",
        "Verify checksum",
        "Create backups",
        "Track HDD usage",
        "Move media to departments",
        "Prepare delivery drive",
        "Archive project",
        "Track media location",
        "Check missing media",
    ),
}


def preset_scope_keys() -> tuple[str, ...]:
    return tuple(key for key, _, _ in TASK_PRESET_SCOPE_FIELDS)


def preset_scope_key_set() -> frozenset[str]:
    return frozenset(preset_scope_keys())


def preset_scope_labels() -> dict[str, str]:
    return {key: label for key, label, _ in TASK_PRESET_SCOPE_FIELDS}


def scope_label(key: str | None) -> str:
    if not key:
        return "Unassigned"
    return preset_scope_labels().get(key, key)


def _add_missing_default_titles(
    db: Any,
    TaskGroup: Any,
    TaskGroupTitle: Any,
    scope_key: str,
) -> int:
    titles = DEFAULT_TASK_TITLES_BY_SCOPE.get(scope_key)
    if not titles:
        return 0

    group = TaskGroup.query.filter_by(post_scope_key=scope_key).first()
    if group is None:
        return 0

    have = {
        row.title
        for row in TaskGroupTitle.query.filter_by(group_id=group.id).all()
    }
    added = 0
    for title in titles:
        if title in have:
            continue
        mx = (
            db.session.query(db.func.max(TaskGroupTitle.sort_order))
            .filter(TaskGroupTitle.group_id == group.id)
            .scalar()
        )
        nxt = (mx if mx is not None else -1) + 1
        db.session.add(
            TaskGroupTitle(group_id=group.id, title=title, sort_order=nxt)
        )
        have.add(title)
        added += 1
    return added


def classify_scope_titles(
    scope_key: str,
    existing_titles: list[str] | tuple[str, ...] | None = None,
) -> dict[str, list[str]]:
    """Split a scope's titles into default catalog, custom added, already present, and missing."""
    defaults = list(DEFAULT_TASK_TITLES_BY_SCOPE.get(scope_key) or ())
    default_set = set(defaults)
    existing: list[str] = []
    seen: set[str] = set()
    for raw in existing_titles or ():
        title = str(raw or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        existing.append(title)
    existing_set = set(existing)
    return {
        "default": defaults,
        "added": [title for title in existing if title not in default_set],
        "existed": [title for title in defaults if title in existing_set],
        "missing": [title for title in defaults if title not in existing_set],
    }


def restore_default_titles_for_scope(
    db: Any,
    TaskGroup: Any,
    TaskGroupTitle: Any,
    scope_key: str,
) -> int:
    """Add missing default titles for one scope. Skips duplicates; does not remove custom titles."""
    added = _add_missing_default_titles(db, TaskGroup, TaskGroupTitle, scope_key)
    if added:
        db.session.commit()
    return added


def restore_all_default_titles(
    db: Any,
    TaskGroup: Any,
    TaskGroupTitle: Any,
) -> dict[str, int]:
    """Add missing default titles for every preset scope. Returns added count per scope key."""
    counts: dict[str, int] = {}
    total = 0
    for scope_key in preset_scope_keys():
        added = _add_missing_default_titles(db, TaskGroup, TaskGroupTitle, scope_key)
        counts[scope_key] = added
        total += added
    if total:
        db.session.commit()
    return counts


def api_task_row_payload(
    task: Any,
    *,
    isoformat_fn,
    effective_scope_key_fn,
) -> dict:
    """JSON payload for /api/tasks (admin All Tasks)."""
    p = getattr(task, "project", None)
    assignee = getattr(task, "assignee", None)
    requester = getattr(task, "requested_by", None)
    item = getattr(task, "editing_item", None)
    scope_key = effective_scope_key_fn(task)
    scope_label_text = scope_label(scope_key)
    conform_detail = getattr(task, "conform_detail", None)
    conform_result = (
        (getattr(task, "conform_result", None) or "").strip().lower()
        or (
            (getattr(conform_detail, "result", None) or "").strip().lower()
            if conform_detail
            else ""
        )
    )
    handoff_name = None
    guide_name = None
    if conform_detail is not None:
        handoff_name = getattr(conform_detail, "xml_file_name", None)
        guide_name = getattr(conform_detail, "guide_video_file_name", None)
    handoff_name = handoff_name or getattr(task, "conform_handoff_file_name", None)
    conform_handoff_label = cts._handoff_package_label(
        handoff_file_name=handoff_name,
        guide_video_file_name=guide_name,
    )
    return {
        "id": int(task.id),
        "title": task.title or "",
        "description": (task.description or "") if task.description is not None else "",
        "status": task.status,
        "priority": (task.priority or "medium"),
        "archived": bool(getattr(task, "archived", False)),
        "due_date": task.due_date.isoformat() if getattr(task, "due_date", None) else None,
        "created_at": isoformat_fn(task.created_at),
        "updated_at": isoformat_fn(getattr(task, "updated_at", None)),
        "completed_at": isoformat_fn(task.completed_at),
        "post_scope_key": scope_key or "",
        "post_scope_label": scope_label_text,
        "project": {"id": p.id, "name": p.name} if p is not None else None,
        "editing_item": (
            {
                "id": int(item.id),
                "code": (item.code or "").strip(),
                "title": (item.title or "").strip(),
                "item_type": (item.item_type or "").strip(),
            }
            if item is not None
            else None
        ),
        "requested_by": (
            {"id": int(requester.id), "name": (requester.name or "").strip()}
            if requester is not None
            else None
        ),
        "assigned_to": (
            {"id": int(assignee.id), "name": (assignee.name or "").strip()}
            if assignee is not None
            else None
        ),
        "conform_result": conform_result or None,
        "conform_reason": _conform_reason_for_task_row(task, conform_detail),
        "conform_handoff_label": conform_handoff_label or None,
        "is_conform_request": bool(
            scope_key == cts.CONFORM_SCOPE_KEY
            and item is not None
            or conform_detail is not None
        ),
        "has_conform_checklist": False,
        "conform_status_url": f"/api/tasks/{int(task.id)}/conform-status",
        "conform_failed_url": f"/conform-tasks/{int(task.id)}/fail",
        # Backward compatibility
        "user": (
            {"id": int(assignee.id), "name": (assignee.name or "").strip()}
            if assignee is not None
            else None
        ),
    }
