"""Production ShootingDayScene ↔ VFX Management bridge (VfxSceneItem / VfxSceneItemSource)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Callable

import shooting_items as shooting_items_mod

VFX_ITEM_TYPES = frozenset(
    {
        "scene",
        "custom_group",
        "plate",
        "green_screen",
        "clean_plate",
        "wire_removal",
        "set_extension",
        "screen_replacement",
        "cleanup",
        "other",
    }
)

VFX_ITEM_STATUSES = frozenset(
    {
        "pending",
        "ready",
        "assigned",
        "in_progress",
        "internal_review",
        "client_review",
        "approved",
        "delivered",
        "on_hold",
        "blocked",
    }
)


def _scene_label_display(row) -> str:
    raw = (getattr(row, "scene_label", None) or "").strip()
    if raw:
        return raw
    sn = getattr(row, "scene_number", None)
    return str(sn).strip() if sn is not None else ""


def picker_label_for_row(row) -> str:
    """Human label for scene pickers (include modal, add scene)."""
    raw = _scene_label_display(row)
    sn = getattr(row, "scene_number", None)
    return _picker_label_from_parts(raw, sn, getattr(row, "id", None))


def picker_label_from_dict(data: dict) -> str:
    raw = str(data.get("scene_label") or data.get("label") or "").strip()
    sn = data.get("scene_number")
    return _picker_label_from_parts(raw, sn, data.get("id"))


def _picker_label_from_parts(
    raw: str, scene_number: int | str | None, row_id: int | str | None = None
) -> str:
    cleaned = raw.strip()
    generic = cleaned.casefold() in {"", "scene", "scenes", "sc"}
    if cleaned and not generic:
        lower = cleaned.casefold()
        if lower.startswith("scene ") or lower.startswith("scenes "):
            return cleaned
        return f"Scene {cleaned}"
    if scene_number is not None and str(scene_number).strip() not in {"", "0"}:
        return f"Scene {int(scene_number) if str(scene_number).isdigit() else scene_number}"
    if row_id is not None:
        return f"Scene #{int(row_id)}"
    return "Unnamed scene"


def _default_display_name_for_row(row) -> str:
    label = _scene_label_display(row)
    if label:
        return label if label.lower().startswith("scene") else f"Scene {label}"
    return "Scene"


def episode_key_for_row(row) -> int:
    if bool(getattr(row, "is_episode_unassigned", False)):
        return 0
    if shooting_items_mod.is_establishing_shots_pool_row(row):
        return -1
    return int(getattr(row, "episode_number", None) or 1)


def active_source_links_for_project(query_models, project_id: int) -> list:
    VfxSceneItem = query_models["VfxSceneItem"]
    VfxSceneItemSource = query_models["VfxSceneItemSource"]
    return (
        VfxSceneItemSource.query.join(
            VfxSceneItem, VfxSceneItemSource.vfx_scene_item_id == VfxSceneItem.id
        )
        .filter(
            VfxSceneItem.project_id == int(project_id),
            VfxSceneItem.is_active.is_(True),
            VfxSceneItemSource.is_active.is_(True),
        )
        .all()
    )


def scene_ids_in_active_items(query_models, project_id: int) -> set[int]:
    return {int(link.shooting_day_scene_id) for link in active_source_links_for_project(query_models, project_id)}


def scene_ids_blocked_from_auto_vfx(query_models, project_id: int) -> set[int]:
    """Production scenes removed from VFX that should not be auto-recreated while needs_vfx stays on."""
    VfxSceneItem = query_models["VfxSceneItem"]
    VfxSceneItemSource = query_models["VfxSceneItemSource"]
    active = scene_ids_in_active_items(query_models, project_id)
    blocked: set[int] = set()
    rows = (
        VfxSceneItemSource.query.join(
            VfxSceneItem, VfxSceneItemSource.vfx_scene_item_id == VfxSceneItem.id
        )
        .filter(
            VfxSceneItem.project_id == int(project_id),
            VfxSceneItem.is_active.is_(False),
        )
        .all()
    )
    for link in rows:
        sid = int(link.shooting_day_scene_id)
        if sid not in active:
            blocked.add(sid)
    return blocked


def item_for_scene_id(query_models, project_id: int, scene_id: int):
    VfxSceneItem = query_models["VfxSceneItem"]
    VfxSceneItemSource = query_models["VfxSceneItemSource"]
    return (
        VfxSceneItem.query.join(
            VfxSceneItemSource, VfxSceneItemSource.vfx_scene_item_id == VfxSceneItem.id
        )
        .filter(
            VfxSceneItem.project_id == int(project_id),
            VfxSceneItem.is_active.is_(True),
            VfxSceneItemSource.is_active.is_(True),
            VfxSceneItemSource.shooting_day_scene_id == int(scene_id),
        )
        .first()
    )


def active_items_for_project(query_models, project_id: int) -> list:
    VfxSceneItem = query_models["VfxSceneItem"]
    return (
        VfxSceneItem.query.filter_by(project_id=int(project_id), is_active=True)
        .order_by(
            VfxSceneItem.episode_number.asc(),
            VfxSceneItem.display_name.asc(),
            VfxSceneItem.id.asc(),
        )
        .all()
    )


def sources_for_item(query_models, item_id: int, *, active_only: bool = True) -> list:
    VfxSceneItemSource = query_models["VfxSceneItemSource"]
    q = VfxSceneItemSource.query.filter_by(vfx_scene_item_id=int(item_id))
    if active_only:
        q = q.filter_by(is_active=True)
    return q.order_by(VfxSceneItemSource.id.asc()).all()


def primary_source_scene_id(sources: list) -> int | None:
    if not sources:
        return None
    return int(sources[0].shooting_day_scene_id)


def get_source_episode_number_for_vfx_item(item, source_rows: list) -> int | str | None:
    """Primary production episode for a VFX item (never the VFX portal episode)."""
    if not source_rows:
        return None
    row = source_rows[0]
    if bool(getattr(row, "is_episode_unassigned", False)):
        return "X"
    if shooting_items_mod.is_establishing_shots_pool_row(row):
        return "EST"
    return int(getattr(row, "episode_number", None) or 0) or None


def format_original_episode_prefix(source_scene) -> str:
    if source_scene is None:
        return ""
    if bool(getattr(source_scene, "is_episode_unassigned", False)):
        return "EPX"
    if shooting_items_mod.is_establishing_shots_pool_row(source_scene):
        return "EST"
    ep = int(getattr(source_scene, "episode_number", None) or 0)
    if ep <= 0:
        return ""
    return f"EP{ep:02d}"


def original_episode_long_label(source_scene) -> str:
    if source_scene is None:
        return ""
    if bool(getattr(source_scene, "is_episode_unassigned", False)):
        return "Episode X"
    if shooting_items_mod.is_establishing_shots_pool_row(source_scene):
        return "Establishing"
    ep = int(getattr(source_scene, "episode_number", None) or 0)
    if ep <= 0:
        return ""
    return f"Episode {ep:02d}"


def _display_name_has_episode_prefix(name: str) -> bool:
    import re

    text = (name or "").strip()
    if not text:
        return False
    if re.match(r"^(EP|Ep|Episode)\s*\d", text, re.IGNORECASE):
        return True
    if re.match(r"^EPX\b", text, re.IGNORECASE):
        return True
    if re.match(r"^EST\b", text, re.IGNORECASE):
        return True
    return False


def vfx_portal_group_key(item, *, is_tv: bool, max_episode: int) -> int:
    """Sidebar/board group key from VfxSceneItem.episode_number (VFX portal placement)."""
    epn = int(getattr(item, "episode_number", None) or 0)
    if is_tv:
        return epn if epn > 0 else shooting_items_mod.VFX_GROUP_EPISODE_X
    if epn > 0:
        return epn
    return 1


def _source_episode_keys(source_rows: list) -> set[int]:
    return {episode_key_for_row(row) for row in source_rows}


def source_row_display_label_with_prefix(
    row,
    *,
    vfx_group_key: int,
    force_prefix: bool,
) -> str:
    label = picker_label_for_row(row)
    src_key = episode_key_for_row(row)
    need_prefix = force_prefix or src_key != vfx_group_key
    if not need_prefix:
        return label
    prefix = format_original_episode_prefix(row)
    if not prefix or _display_name_has_episode_prefix(label):
        return label
    return f"{prefix} {label}".strip()


def vfx_scene_display_name_with_source_prefix(
    item,
    source_rows: list,
    *,
    is_tv: bool,
    max_episode: int,
) -> str:
    meta = build_vfx_item_display_meta(item, source_rows, is_tv=is_tv, max_episode=max_episode)
    return str(meta.get("displayNameWithSourcePrefix") or meta.get("displayName") or "")


def _editorial_group_key(effective_ep: int, *, is_tv: bool) -> int:
    """Portal group key from a resolved EFFECTIVE editorial episode number."""
    eff = int(effective_ep or 0)
    if is_tv:
        return eff if eff > 0 else shooting_items_mod.VFX_GROUP_EPISODE_X
    return eff if eff > 0 else 1


def build_vfx_item_display_meta(
    item,
    source_rows: list,
    *,
    is_tv: bool,
    max_episode: int,
    effective_episode_fn: Callable[[Any], int] | None = None,
) -> dict[str, Any]:
    """Display + grouping metadata for a VFX item.

    When ``effective_episode_fn`` is supplied (VFX portal / editorial mode), the
    portal GROUP is the linked scenes' current *effective editorial episode*
    (primary SceneEditorialAssignment), NOT the cached ``VfxSceneItem.episode_number``.
    Origin (production) episode is always derived from the immutable scene
    ``episode_number`` and shown as the source prefix. Without the callable the
    legacy behaviour (group by stored ``episode_number``) is preserved.
    """
    base_name = (getattr(item, "display_name", None) or "").strip() or "VFX Item"
    primary = source_rows[0] if source_rows else None
    if effective_episode_fn is not None:
        eff_keys = {int(effective_episode_fn(r)) for r in source_rows} if source_rows else set()
        mixed_sources = len(eff_keys) > 1
        eff_primary = int(effective_episode_fn(primary)) if primary is not None else 0
        vfx_group = _editorial_group_key(eff_primary, is_tv=is_tv)
        vfx_ep = eff_primary
        primary_prod_key = episode_key_for_row(primary) if primary is not None else None
        moved = mixed_sources or (
            primary_prod_key is not None and int(primary_prod_key) != eff_primary
        )
    else:
        vfx_ep = int(getattr(item, "episode_number", None) or 0)
        vfx_group = vfx_portal_group_key(item, is_tv=is_tv, max_episode=max_episode)
        source_keys = _source_episode_keys(source_rows)
        mixed_sources = len(source_keys) > 1
        primary_key = episode_key_for_row(primary) if primary is not None else None
        moved = (
            mixed_sources
            or (primary_key is not None and primary_key != vfx_group)
        )

    if mixed_sources:
        display_with_prefix = f"Mixed Episodes · {base_name}"
    elif moved and primary is not None:
        prefix = format_original_episode_prefix(primary)
        if prefix and not _display_name_has_episode_prefix(base_name):
            display_with_prefix = f"{prefix} {base_name}".strip()
        else:
            display_with_prefix = base_name
    else:
        display_with_prefix = base_name

    orig_num = get_source_episode_number_for_vfx_item(item, source_rows)
    orig_label = format_original_episode_prefix(primary) if primary is not None else ""

    return {
        "displayName": base_name,
        "displayNameWithSourcePrefix": display_with_prefix,
        "originalEpisodeNumber": orig_num,
        "originalEpisodeLabel": orig_label,
        "originalEpisodeLongLabel": original_episode_long_label(primary),
        "vfxEpisodeNumber": vfx_ep,
        "movedFromOriginalEpisode": bool(moved),
        "mixedSourceEpisodes": mixed_sources,
        "groupKey": vfx_group,
    }


def build_included_scene_display_meta(
    row,
    *,
    vfx_group_key: int,
    mixed_sources: bool,
) -> dict[str, Any]:
    src_key = episode_key_for_row(row)
    label = picker_label_for_row(row)
    force_prefix = mixed_sources
    display = source_row_display_label_with_prefix(
        row, vfx_group_key=vfx_group_key, force_prefix=force_prefix
    )
    moved = force_prefix or src_key != vfx_group_key
    return {
        "label": label,
        "originalEpisodeNumber": get_source_episode_number_for_vfx_item(None, [row]),
        "originalEpisodeLabel": format_original_episode_prefix(row),
        "displayLabelWithSourcePrefix": display,
        "movedFromOriginalEpisode": bool(moved),
    }


def move_vfx_item_to_portal_group(
    db,
    query_models,
    *,
    project_id: int,
    target_group_key: int,
    is_tv: bool,
    max_episode: int,
    scene_id: int | None = None,
    item_id: int | None = None,
) -> str | None:
    """Move a VFX item between portal episodes/reels without changing production scenes."""
    VfxSceneItem = query_models["VfxSceneItem"]
    item = None
    if item_id is not None:
        item = VfxSceneItem.query.filter_by(
            id=int(item_id), project_id=int(project_id), is_active=True
        ).first()
    if item is None and scene_id is not None:
        item = item_for_scene_id(query_models, project_id, int(scene_id))
    if item is None:
        return "not_found"
    target = int(target_group_key)
    if is_tv:
        if target < 1 or (max_episode > 0 and target > max_episode):
            return "invalid_group"
    elif target < 1:
        return "invalid_group"
    now_fn = query_models.get("now_local")
    item.episode_number = target
    item.updated_at = now_fn() if callable(now_fn) else datetime.utcnow()
    return None


def reconcile_bundled_sources_without_parent_in_vfx(
    db, query_models, project_id: int
) -> int:
    """Unlink bundled scenes when their parent (primary source) is not on the VFX board."""
    now_fn = query_models.get("now_local")
    now = now_fn() if callable(now_fn) else datetime.utcnow()
    deactivated = 0
    changed = True
    while changed:
        changed = False
        on_vfx = scene_ids_in_active_items(query_models, project_id)
        for item in active_items_for_project(query_models, project_id):
            all_links = sources_for_item(query_models, int(item.id), active_only=False)
            if len(all_links) < 2:
                continue
            primary_id = int(all_links[0].shooting_day_scene_id)
            if primary_id in on_vfx:
                continue
            for link in sources_for_item(query_models, int(item.id), active_only=True):
                sid = int(link.shooting_day_scene_id)
                if sid == primary_id:
                    continue
                link.is_active = False
                deactivated += 1
                changed = True
                item.updated_at = now
        for item in active_items_for_project(query_models, project_id):
            if not sources_for_item(query_models, int(item.id), active_only=True):
                item.is_active = False
                item.updated_at = now
                changed = True
    return deactivated


def build_item_warnings(item, source_rows: list) -> list[str]:
    warnings: list[str] = []
    if not source_rows:
        warnings.append("Custom VFX item has no linked production scene.")
    for row in source_rows:
        if not bool(getattr(row, "needs_vfx", False)):
            label = _scene_label_display(row) or str(getattr(row, "id", ""))
            warnings.append(f"Source scene {label} is no longer marked as Needs VFX.")
    return warnings


def serialize_available_scene(
    row,
    shooting_day,
    *,
    thumbnail_url_fn: Callable[[int, str], str] | None = None,
    project_id: int | None = None,
) -> dict[str, Any]:
    thumb = (getattr(row, "scene_thumbnail_frame", None) or "").strip()
    thumb_url = ""
    if thumb and thumbnail_url_fn and project_id is not None:
        thumb_url = thumbnail_url_fn(int(project_id), thumb)
    day_name = ""
    shoot_date = ""
    if shooting_day is not None:
        day_name = (getattr(shooting_day, "day_name", None) or "").strip()
        sd = getattr(shooting_day, "shooting_date", None)
        if sd is not None:
            shoot_date = sd.isoformat() if hasattr(sd, "isoformat") else str(sd)
    return {
        "id": int(row.id),
        "episode_number": episode_key_for_row(row),
        "scene_number": int(getattr(row, "scene_number", None) or 1),
        "scene_label": _scene_label_display(row),
        "shooting_day_id": int(getattr(row, "shooting_day_id", 0) or 0),
        "shooting_day_name": day_name,
        "shoot_date": shoot_date,
        "needs_vfx": bool(getattr(row, "needs_vfx", False)),
        "item_type": (getattr(row, "shooting_item_type", None) or "").strip(),
        "duration_seconds": int(getattr(row, "duration_seconds", None) or 0),
        "thumbnail_url": thumb_url,
        "notes": (getattr(row, "notes", None) or "").strip(),
        "runtime_selected": bool(getattr(row, "runtime_selected", False)),
    }


def _production_scene_rows_for_episode(query_models, project_id: int, episode_number: int) -> list:
    ShootingDayScene = query_models["ShootingDayScene"]
    ShootingDay = query_models["ShootingDay"]
    ep = int(episode_number)
    rows = (
        ShootingDayScene.query.join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
        .filter(ShootingDay.project_id == int(project_id))
        .order_by(
            ShootingDay.shooting_date.asc(),
            ShootingDayScene.scene_number.asc(),
            ShootingDayScene.id.asc(),
        )
        .all()
    )
    out: list = []
    for row in rows:
        if not shooting_items_mod.is_scene_row_type(getattr(row, "shooting_item_type", None)):
            continue
        if episode_key_for_row(row) != ep:
            continue
        out.append(row)
    return out


def scene_vfx_item_labels(query_models, project_id: int) -> dict[int, str]:
    """Map production scene ids to the active VFX item display name they are linked to."""
    VfxSceneItem = query_models["VfxSceneItem"]
    out: dict[int, str] = {}
    for link in active_source_links_for_project(query_models, project_id):
        item = VfxSceneItem.query.filter_by(id=int(link.vfx_scene_item_id)).first()
        if item is None:
            continue
        sid = int(link.shooting_day_scene_id)
        name = (item.display_name or "").strip() or "VFX item"
        out[sid] = name
    return out


def production_scenes_for_episode(
    query_models,
    project_id: int,
    episode_number: int,
    *,
    thumbnail_url_fn: Callable[[int, str], str] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _production_scene_rows_for_episode(query_models, project_id, episode_number):
        out.append(
            serialize_available_scene(
                row,
                getattr(row, "shooting_day", None),
                thumbnail_url_fn=thumbnail_url_fn,
                project_id=project_id,
            )
        )
    return out


def available_scenes_for_episode(
    query_models,
    project_id: int,
    episode_number: int,
    *,
    thumbnail_url_fn: Callable[[int, str], str] | None = None,
) -> list[dict[str, Any]]:
    taken = scene_ids_in_active_items(query_models, project_id)
    return [
        scene
        for scene in production_scenes_for_episode(
            query_models,
            project_id,
            episode_number,
            thumbnail_url_fn=thumbnail_url_fn,
        )
        if int(scene["id"]) not in taken
    ]


def needs_vfx_not_in_vfx(query_models, project_id: int) -> list:
    ShootingDayScene = query_models["ShootingDayScene"]
    ShootingDay = query_models["ShootingDay"]
    taken = scene_ids_in_active_items(query_models, project_id)
    blocked = scene_ids_blocked_from_auto_vfx(query_models, project_id)
    rows = (
        ShootingDayScene.query.join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
        .filter(
            ShootingDay.project_id == int(project_id),
            ShootingDayScene.needs_vfx.is_(True),
        )
        .order_by(
            ShootingDayScene.episode_number.asc(),
            ShootingDayScene.scene_number.asc(),
            ShootingDayScene.id.asc(),
        )
        .all()
    )
    return [
        row
        for row in rows
        if int(row.id) not in taken
        and shooting_items_mod.is_scene_row_type(getattr(row, "shooting_item_type", None))
    ]


def validate_included_scenes(
    query_models,
    project_id: int,
    episode_number: int,
    scene_ids: list[int],
    *,
    exclude_item_id: int | None = None,
) -> tuple[list, str | None]:
    if not scene_ids:
        return [], "included_scenes_required"
    ShootingDayScene = query_models["ShootingDayScene"]
    ShootingDay = query_models["ShootingDay"]
    taken = scene_ids_in_active_items(query_models, project_id)
    if exclude_item_id is not None:
        for link in sources_for_item(query_models, exclude_item_id, active_only=True):
            taken.discard(int(link.shooting_day_scene_id))
    ep = int(episode_number)
    rows: list = []
    for sid in scene_ids:
        row = (
            ShootingDayScene.query.join(
                ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id
            )
            .filter(
                ShootingDay.project_id == int(project_id),
                ShootingDayScene.id == int(sid),
            )
            .first()
        )
        if row is None:
            return [], "invalid_scene_id"
        if episode_key_for_row(row) != ep:
            return [], "scene_episode_mismatch"
        if not shooting_items_mod.is_scene_row_type(getattr(row, "shooting_item_type", None)):
            return [], "invalid_scene_type"
        if int(row.id) in taken:
            return [], "scene_already_in_vfx"
        rows.append(row)
    return rows, None


def create_vfx_item(
    db,
    query_models,
    *,
    project_id: int,
    episode_number: int,
    display_name: str,
    item_type: str = "scene",
    included_scene_ids: list[int],
    priority: str = "normal",
    vendor: str = "in_house",
    description: str = "",
    status: str = "pending",
    created_by_id: int | None = None,
) -> tuple[Any | None, str | None]:
    VfxSceneItem = query_models["VfxSceneItem"]
    VfxSceneItemSource = query_models["VfxSceneItemSource"]
    name = (display_name or "").strip()
    if not name:
        return None, "display_name_required"
    itype = (item_type or "scene").strip().lower()
    if itype not in VFX_ITEM_TYPES:
        return None, "invalid_item_type"
    st = (status or "pending").strip().lower()
    if st not in VFX_ITEM_STATUSES:
        st = "pending"
    rows, err = validate_included_scenes(
        query_models, project_id, episode_number, included_scene_ids
    )
    if err:
        return None, err
    now_fn = query_models.get("now_local")
    now = now_fn() if callable(now_fn) else datetime.utcnow()
    item = VfxSceneItem(
        project_id=int(project_id),
        episode_number=int(episode_number),
        display_name=name[:200],
        item_type=itype,
        description=(description or "")[:5000],
        status=st,
        priority=(priority or "normal")[:16],
        vendor=(vendor or "in_house")[:24],
        created_by_id=created_by_id,
        created_at=now,
        updated_at=now,
        is_active=True,
    )
    db.session.add(item)
    db.session.flush()
    for row in rows:
        db.session.add(
            VfxSceneItemSource(
                vfx_scene_item_id=int(item.id),
                shooting_day_scene_id=int(row.id),
                created_by_id=created_by_id,
                created_at=now,
                is_active=True,
            )
        )
    return item, None


def include_scenes_on_item(
    db,
    query_models,
    *,
    project_id: int,
    item_id: int,
    included_scene_ids: list[int],
    created_by_id: int | None = None,
) -> str | None:
    VfxSceneItem = query_models["VfxSceneItem"]
    VfxSceneItemSource = query_models["VfxSceneItemSource"]
    item = VfxSceneItem.query.filter_by(
        id=int(item_id), project_id=int(project_id), is_active=True
    ).first()
    if item is None:
        return "not_found"
    ep = int(item.episode_number or 0)
    rows, err = validate_included_scenes(
        query_models,
        project_id,
        ep,
        included_scene_ids,
        exclude_item_id=int(item.id),
    )
    if err:
        return err
    now_fn = query_models.get("now_local")
    now = now_fn() if callable(now_fn) else datetime.utcnow()
    existing = {
        int(s.shooting_day_scene_id)
        for s in sources_for_item(query_models, int(item.id), active_only=True)
    }
    for row in rows:
        if int(row.id) in existing:
            continue
        db.session.add(
            VfxSceneItemSource(
                vfx_scene_item_id=int(item.id),
                shooting_day_scene_id=int(row.id),
                created_by_id=created_by_id,
                created_at=now,
                is_active=True,
            )
        )
    item.updated_at = now
    return None


def remove_vfx_item(db, query_models, *, project_id: int, item_id: int) -> str | None:
    """Soft-remove a VFX item and fully unlink all of its production scenes from VFX."""
    VfxSceneItem = query_models["VfxSceneItem"]
    VfxSceneItemSource = query_models["VfxSceneItemSource"]
    item = VfxSceneItem.query.filter_by(id=int(item_id), project_id=int(project_id)).first()
    if item is None:
        return "not_found"
    if not item.is_active:
        return None
    now_fn = query_models.get("now_local")
    now = now_fn() if callable(now_fn) else datetime.utcnow()
    display_key = (item.display_name or "").strip()
    ep = int(item.episode_number or 0)
    active_items = VfxSceneItem.query.filter_by(
        project_id=int(project_id), is_active=True
    ).all()
    if display_key:
        siblings = [
            it
            for it in active_items
            if int(it.episode_number or 0) == ep
            and (it.display_name or "").strip() == display_key
        ]
    else:
        siblings = [item]
    if not siblings:
        siblings = [item]

    scene_ids: set[int] = set()
    for it in siblings:
        for link in VfxSceneItemSource.query.filter_by(vfx_scene_item_id=int(it.id)).all():
            scene_ids.add(int(link.shooting_day_scene_id))

    for link in active_source_links_for_project(query_models, project_id):
        if int(link.shooting_day_scene_id) in scene_ids:
            link.is_active = False

    for it in siblings:
        it.is_active = False
        it.updated_at = now
        for link in VfxSceneItemSource.query.filter_by(vfx_scene_item_id=int(it.id)).all():
            link.is_active = False

    reconcile_bundled_sources_without_parent_in_vfx(db, query_models, project_id)
    return None


def remove_source_from_item(
    db, query_models, *, project_id: int, item_id: int, source_id: int
) -> str | None:
    VfxSceneItem = query_models["VfxSceneItem"]
    VfxSceneItemSource = query_models["VfxSceneItemSource"]
    item = VfxSceneItem.query.filter_by(
        id=int(item_id), project_id=int(project_id), is_active=True
    ).first()
    if item is None:
        return "not_found"
    link = VfxSceneItemSource.query.filter_by(
        id=int(source_id), vfx_scene_item_id=int(item.id)
    ).first()
    if link is None:
        return "source_not_found"
    link.is_active = False
    now_fn = query_models.get("now_local")
    item.updated_at = now_fn() if callable(now_fn) else datetime.utcnow()
    reconcile_bundled_sources_without_parent_in_vfx(db, query_models, project_id)
    return None


def move_scene_to_item(
    db,
    query_models,
    *,
    project_id: int,
    scene_id: int,
    target_item_id: int,
    created_by_id: int | None = None,
) -> str | None:
    """Re-parent a production scene from its current VfxSceneItem to another item.

    Deactivates the scene's active source link on its current item(s), links it to
    the target item, and deactivates any old item left with no active sources. This
    keeps the VFX portal in sync because the portal is derived from active
    VfxSceneItemSource rows.
    """
    VfxSceneItem = query_models["VfxSceneItem"]
    VfxSceneItemSource = query_models["VfxSceneItemSource"]
    ShootingDayScene = query_models["ShootingDayScene"]
    ShootingDay = query_models["ShootingDay"]

    scene_id = int(scene_id)
    target = VfxSceneItem.query.filter_by(
        id=int(target_item_id), project_id=int(project_id), is_active=True
    ).first()
    if target is None:
        return "target_not_found"

    row = (
        ShootingDayScene.query.join(
            ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id
        )
        .filter(
            ShootingDay.project_id == int(project_id),
            ShootingDayScene.id == scene_id,
        )
        .first()
    )
    if row is None:
        return "invalid_scene_id"
    if not shooting_items_mod.is_scene_row_type(getattr(row, "shooting_item_type", None)):
        return "invalid_scene_type"

    now_fn = query_models.get("now_local")
    now = now_fn() if callable(now_fn) else datetime.utcnow()

    current_links = (
        VfxSceneItemSource.query.join(
            VfxSceneItem, VfxSceneItemSource.vfx_scene_item_id == VfxSceneItem.id
        )
        .filter(
            VfxSceneItem.project_id == int(project_id),
            VfxSceneItemSource.shooting_day_scene_id == scene_id,
            VfxSceneItemSource.is_active.is_(True),
        )
        .all()
    )
    current_item_ids = {int(l.vfx_scene_item_id) for l in current_links}
    if current_item_ids == {int(target.id)}:
        return "already_in_target"

    affected_item_ids: set[int] = set()
    for link in current_links:
        if int(link.vfx_scene_item_id) == int(target.id):
            continue
        link.is_active = False
        affected_item_ids.add(int(link.vfx_scene_item_id))

    existing_target_link = VfxSceneItemSource.query.filter_by(
        vfx_scene_item_id=int(target.id), shooting_day_scene_id=scene_id
    ).first()
    if existing_target_link is not None:
        existing_target_link.is_active = True
    else:
        db.session.add(
            VfxSceneItemSource(
                vfx_scene_item_id=int(target.id),
                shooting_day_scene_id=scene_id,
                created_by_id=created_by_id,
                created_at=now,
                is_active=True,
            )
        )
    target.updated_at = now

    for item_id in affected_item_ids:
        remaining = VfxSceneItemSource.query.filter_by(
            vfx_scene_item_id=int(item_id), is_active=True
        ).count()
        if remaining == 0:
            old_item = VfxSceneItem.query.get(int(item_id))
            if old_item is not None and old_item.is_active:
                old_item.is_active = False
                old_item.updated_at = now

    reconcile_bundled_sources_without_parent_in_vfx(db, query_models, project_id)
    return None


def sync_needs_vfx_scenes_to_vfx_items(db, query_models, project_id: int) -> int:
    """Create VfxSceneItem rows for needs_vfx production scenes not yet linked."""
    ShootingDayScene = query_models["ShootingDayScene"]
    ShootingDay = query_models["ShootingDay"]
    taken = scene_ids_in_active_items(query_models, project_id)
    blocked = scene_ids_blocked_from_auto_vfx(query_models, project_id)
    rows = (
        ShootingDayScene.query.join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
        .filter(
            ShootingDay.project_id == int(project_id),
            ShootingDayScene.needs_vfx.is_(True),
        )
        .all()
    )
    created = 0
    for row in rows:
        if int(row.id) in taken:
            continue
        if int(row.id) in blocked:
            continue
        if not shooting_items_mod.is_scene_row_type(getattr(row, "shooting_item_type", None)):
            continue
        ep = episode_key_for_row(row)
        item, err = create_vfx_item(
            db,
            query_models,
            project_id=int(project_id),
            episode_number=ep,
            display_name=_default_display_name_for_row(row),
            item_type="scene",
            included_scene_ids=[int(row.id)],
            created_by_id=None,
        )
        if item is not None and err is None:
            created += 1
            taken.add(int(row.id))
    if created:
        db.session.commit()
    return created


def migrate_legacy_inclusions(db, query_models, project_id: int) -> None:
    """One-time style migration from VfxSceneInclusion to VfxSceneItemSource."""
    VfxSceneInclusion = query_models.get("VfxSceneInclusion")
    if VfxSceneInclusion is None:
        return
    ShootingDayScene = query_models["ShootingDayScene"]
    links = VfxSceneInclusion.query.filter_by(project_id=int(project_id)).all()
    if not links:
        return
    by_container: dict[int, list[int]] = defaultdict(list)
    for link in links:
        by_container[int(link.container_scene_id)].append(int(link.included_scene_id))
    taken = scene_ids_in_active_items(query_models, project_id)
    for container_id, child_ids in by_container.items():
        container = db.session.get(ShootingDayScene, container_id)
        if container is None:
            continue
        all_ids = [container_id] + [c for c in child_ids if c != container_id]
        if any(i in taken for i in all_ids):
            continue
        ep = episode_key_for_row(container)
        item, err = create_vfx_item(
            db,
            query_models,
            project_id=int(project_id),
            episode_number=ep,
            display_name=_default_display_name_for_row(container),
            item_type="custom_group" if len(all_ids) > 1 else "scene",
            included_scene_ids=all_ids,
        )
        if item is not None and err is None:
            taken.update(all_ids)
    db.session.commit()


def migrate_orphan_vfx_scenes(db, query_models, project_id: int) -> None:
    """Ensure shooting rows with VFX shots/markers have a VfxSceneItem."""
    ShootingDayScene = query_models["ShootingDayScene"]
    ShootingDay = query_models["ShootingDay"]
    VfxShot = query_models["VfxShot"]
    taken = scene_ids_in_active_items(query_models, project_id)
    blocked = scene_ids_blocked_from_auto_vfx(query_models, project_id)
    shot_scene_ids = {
        int(r[0])
        for r in db.session.query(VfxShot.scene_id)
        .filter_by(project_id=int(project_id))
        .distinct()
        .all()
    }
    rows = (
        ShootingDayScene.query.join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
        .filter(ShootingDay.project_id == int(project_id))
        .all()
    )
    for row in rows:
        sid = int(row.id)
        if sid in taken:
            continue
        if sid in blocked:
            continue
        has_shots = sid in shot_scene_ids
        markers = getattr(row, "vfx_scene_markers", None) or []
        if not has_shots and not markers and not bool(row.needs_vfx):
            continue
        if not shooting_items_mod.is_scene_row_type(getattr(row, "shooting_item_type", None)):
            continue
        ep = episode_key_for_row(row)
        item, _err = create_vfx_item(
            db,
            query_models,
            project_id=int(project_id),
            episode_number=ep,
            display_name=_default_display_name_for_row(row),
            item_type="scene",
            included_scene_ids=[sid],
        )
        if item is not None:
            taken.add(sid)
    db.session.commit()


def vfx_item_shot_count(query_models, project_id: int, item_id: int, source_scene_ids: list[int]) -> int:
    VfxShot = query_models["VfxShot"]
    q = VfxShot.query.filter_by(project_id=int(project_id))
    if source_scene_ids:
        from sqlalchemy import or_

        q = q.filter(
            or_(
                VfxShot.vfx_scene_item_id == int(item_id),
                VfxShot.scene_id.in_([int(x) for x in source_scene_ids]),
            )
        )
    else:
        q = q.filter(VfxShot.vfx_scene_item_id == int(item_id))
    return q.count()
