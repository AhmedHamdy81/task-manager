"""Classify imported rows against one project's current shooting days and rows.

Pure functions over plain snapshots (dicts) so the same code builds the preview and
re-validates it at confirm time. Nothing here writes to the database.

Row identity = shooting day + episode bucket + scene label (casefolded, "12A" kept)
+ item type. A scene number alone never matches, reshoots/pickups/VFX/establishing
items never merge into scenes, and several candidates are always Ambiguous.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from typing import Any

import shooting_items as si
from production_import_normalize import (
    EMPTY,
    INVALID,
    VALUE,
    FIELD_BY_KEY,
    ParsedValue,
    SourceRow,
    ascii_digits,
    day_key,
    fold_text,
    storage_day_name,
)

STATUS_NEW = "new"
STATUS_IDENTICAL = "identical"
STATUS_CHANGED = "changed"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_INVALID = "invalid"
STATUS_DUPLICATE = "duplicate"
STATUS_LABELS = {
    STATUS_NEW: "New",
    STATUS_IDENTICAL: "Identical",
    STATUS_CHANGED: "Changed",
    STATUS_AMBIGUOUS: "Ambiguous",
    STATUS_INVALID: "Invalid",
    STATUS_DUPLICATE: "Duplicate in source",
}

ACTION_ADD = "add"
ACTION_UPDATE = "update"
ACTION_SKIP = "skip"
ACTION_ADD_RESHOOT = "add_reshoot"
ACTION_LABELS = {
    ACTION_ADD: "Add new row",
    ACTION_UPDATE: "Update selected fields",
    ACTION_SKIP: "Keep / skip",
    ACTION_ADD_RESHOOT: "Add as Reshoot",
}

DAY_EXISTING = "existing"
DAY_NEW = "new"
DAY_CONFLICT = "conflict"
DAY_AMBIGUOUS = "ambiguous"
DAY_INVALID = "invalid"
DAY_FIXED = "fixed"

ROW_COMPARE_FIELDS = (
    "episode", "scene_label", "item_type", "reel_number", "duration",
    "sync_done", "first_edit_done", "needs_vfx", "is_critical", "notes",
)
IDENTITY_FIELDS = ("episode", "scene_label", "item_type")
CLEARABLE_FIELDS = ("notes", "reel_number", "duration")

CONSEQUENCES = {
    "episode": "Identity change: the row moves to another episode; runtime takes and duplicate checks are recalculated.",
    "scene_label": "Identity change: the row becomes a different scene; runtime takes and duplicate checks are recalculated.",
    "item_type": "Identity change: the item type decides runtime eligibility and duplicate rules.",
    "duration": "Changes shooting-day and episode runtime totals.",
    "sync_done": "Changes completion: a row is Done only when Sync and First Edit are both Yes.",
    "first_edit_done": "Changes completion: a row is Done only when Sync and First Edit are both Yes.",
    "needs_vfx": "Adds or removes the row from VFX tracking.",
}


# --- Small helpers ----------------------------------------------------------------


def label_key(label: Any) -> str:
    return si.normalize_scene_label_key(ascii_digits(str(label or "")))


def dup_bucket(*, episode_number: int, unassigned: bool, pool: bool) -> str:
    """Same grouping as find_episode_scene_label_duplicate."""
    if unassigned:
        return "x"
    if pool:
        return "pool"
    return f"ep:{int(episode_number or 0)}"


def bucket_label(bucket: str, *, is_tv: bool, item_type: str = "") -> str:
    if si.is_establishing_shot_type(item_type):
        return "Establishing"
    if not is_tv:
        return "—"
    if bucket == "x":
        return "Episode X"
    if bucket == "pool":
        return "Establishing Shots"
    try:
        n = int(bucket.split(":", 1)[1])
    except (IndexError, ValueError):
        return bucket
    return f"Episode {n:02d}" if n > 0 else "—"


def format_duration(secs: int | None) -> str:
    if secs is None:
        return ""
    s = int(secs)
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _yes(v: Any) -> str:
    return "Yes" if v else "No"


def fingerprint(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def day_label(day: dict) -> str:
    d = day.get("shooting_date")
    ds = d.isoformat() if isinstance(d, date) else str(d or "")
    return f"Unit {int(day.get('unit_number') or 1)} · {day.get('day_name') or 'Day'}" + (f" · {ds}" if ds else "")


# --- Current/incoming field values -------------------------------------------------


def current_fields(row: dict, *, is_tv: bool) -> dict[str, dict[str, Any]]:
    """Comparable value + display for every compare field of an existing canonical row."""
    item_type = si.normalize_shooting_item_type(row.get("shooting_item_type"))
    bucket = dup_bucket(
        episode_number=row.get("episode_number") or 0,
        unassigned=bool(row.get("is_episode_unassigned")),
        pool=bool(row.get("is_establishing_shots_pool")),
    )
    reel = row.get("reel_number")
    notes = str(row.get("notes") or "").strip()
    out = {
        "scene_label": {"value": label_key(row.get("scene_label")), "display": str(row.get("scene_label") or "")},
        "item_type": {"value": item_type, "display": item_type},
        "reel_number": {"value": int(reel) if reel else None, "display": str(reel or "")},
        "duration": {"value": int(row.get("duration_seconds") or 0), "display": format_duration(row.get("duration_seconds") or 0)},
        "sync_done": {"value": bool(row.get("sync_done")), "display": _yes(row.get("sync_done"))},
        "first_edit_done": {"value": bool(row.get("first_edit_done")), "display": _yes(row.get("first_edit_done"))},
        "needs_vfx": {"value": bool(row.get("needs_vfx")), "display": _yes(row.get("needs_vfx"))},
        "is_critical": {"value": bool(row.get("is_critical")), "display": _yes(row.get("is_critical"))},
        "notes": {"value": notes, "display": notes[:200]},
    }
    if is_tv:
        out["episode"] = {"value": bucket, "display": bucket_label(bucket, is_tv=is_tv, item_type=item_type)}
    return out


def _incoming_fields(src: SourceRow, ident: dict, *, is_tv: bool) -> dict[str, dict[str, Any]]:
    """Only fields with an explicit incoming value; empty cells carry no information."""
    out: dict[str, dict[str, Any]] = {}
    if is_tv and src.get("episode").state == VALUE:
        out["episode"] = {"value": ident["bucket"], "display": ident["episode_display"]}
    if src.get("scene_label").state == VALUE:
        out["scene_label"] = {"value": label_key(ident["scene_label"]), "display": ident["scene_label"]}
    if src.get("item_type").state == VALUE:
        out["item_type"] = {"value": ident["item_type"], "display": ident["item_type"]}
    v = src.get("reel_number")
    if v.state == VALUE:
        out["reel_number"] = {"value": int(v.value), "display": str(v.value)}
    v = src.get("duration")
    if v.state == VALUE:
        out["duration"] = {"value": int(v.value), "display": format_duration(int(v.value))}
    for key in ("sync_done", "first_edit_done", "needs_vfx", "is_critical"):
        v = src.get(key)
        if v.state == VALUE:
            val = bool(v.value)
            if key == "needs_vfx":
                val = si.apply_auto_vfx_for_type(ident["item_type"], val)
            out[key] = {"value": val, "display": _yes(val)}
    v = src.get("notes")
    if v.state == VALUE:
        out["notes"] = {"value": str(v.value).strip(), "display": str(v.value).strip()[:200]}
    return out


def _diffs(current: dict, incoming: dict) -> list[dict[str, Any]]:
    out = []
    for key in ROW_COMPARE_FIELDS:
        if key not in incoming or key not in current:
            continue
        if incoming[key]["value"] == current[key]["value"]:
            continue
        out.append({
            "field": key,
            "label": FIELD_BY_KEY[key].label,
            "current": current[key]["display"],
            "incoming": incoming[key]["display"],
            "identity": key in IDENTITY_FIELDS,
            "consequence": CONSEQUENCES.get(key, ""),
        })
    return out


def _clearable(src: SourceRow, current: dict, mapped: set[str]) -> list[dict[str, Any]]:
    out = []
    for key in CLEARABLE_FIELDS:
        if key not in mapped or src.get(key).state != EMPTY:
            continue
        cur = current.get(key) or {}
        if cur.get("value") in (None, "", 0):
            continue
        out.append({
            "field": key,
            "label": FIELD_BY_KEY[key].label,
            "current": cur.get("display", ""),
            "consequence": CONSEQUENCES.get(key, "") or "The stored value will be removed.",
        })
    return out


# --- Identity ---------------------------------------------------------------------


def row_identity(src: SourceRow, *, is_tv: bool, max_episode: int) -> tuple[dict | None, str]:
    """(identity, error). Uses the same validation as the shooting-day row form."""
    t = src.get("item_type")
    item_type = t.value if t.state == VALUE else si.SHOOTING_ITEM_TYPE_DEFAULT
    ep = src.get("episode")
    raw_ep = str(ep.value) if ep.state == VALUE else ""
    scene = src.get("scene_label")
    raw_scene = str(scene.value) if scene.state == VALUE else ""
    ep_num, scene_label, err, unassigned, pool = si.parse_shooting_row_identity(
        item_type, raw_ep, raw_scene, is_tv_project=is_tv, max_episode=max(1, max_episode),
    )
    if err:
        return None, err
    bucket = dup_bucket(episode_number=ep_num, unassigned=unassigned, pool=pool)
    return {
        "item_type": item_type,
        "item_type_assumed": t.state != VALUE,
        "legacy_type": item_type in si.LEGACY_SHOOTING_ITEM_TYPES,
        "episode_number": ep_num,
        "unassigned": unassigned,
        "pool": pool,
        "bucket": bucket,
        "episode_display": bucket_label(bucket, is_tv=is_tv, item_type=item_type),
        "scene_label": scene_label,
        "label_key": label_key(scene_label),
    }, ""


def _identity_display(ident: dict | None, src: SourceRow) -> str:
    if ident is None:
        sc = src.get("scene_label")
        return sc.display or "—"
    parts = []
    if ident["episode_display"] not in ("—", ""):
        parts.append(ident["episode_display"])
    parts.append(ident["scene_label"] or "(no scene)")
    parts.append(ident["item_type"] + (" (assumed)" if ident["item_type_assumed"] else ""))
    return " · ".join(parts)


def _source_signature(src: SourceRow) -> str:
    return fingerprint({k: [v.state, v.value] for k, v in sorted(src.values.items())})


# --- Day groups -------------------------------------------------------------------


def _group_rows(
    source_rows: list[SourceRow], *, fixed_day: dict | None
) -> tuple[dict[str, list[SourceRow]], list[tuple[SourceRow, str]]]:
    groups: dict[str, list[SourceRow]] = defaultdict(list)
    orphans: list[tuple[SourceRow, str]] = []
    for src in source_rows:
        if fixed_day is not None:
            groups["fixed"].append(src)
            continue
        unit = src.get("unit_number")
        day = src.get("day_name")
        if unit.state == INVALID or day.state == INVALID:
            orphans.append((src, "The unit or shooting day value is invalid."))
            continue
        if unit.state != VALUE:
            orphans.append((src, "No unit — map a Unit column or set a default unit."))
            continue
        if day.state != VALUE and "day_name" in src.values:
            orphans.append((src, "The Day cell is blank. If the day is written only on the first row of each group, "
                                 "turn on Fill down for Shooting day under Map columns → Fill down."))
            continue
        if day.state != VALUE:
            orphans.append((src, "No shooting day — map a Day column, set a default, or set the worksheet's day."))
            continue
        groups[f"u{int(unit.value)}|{day_key(day.value)}"].append(src)
    return groups, orphans


def _resolve_day_group(
    key: str,
    rows: list[SourceRow],
    *,
    days: list[dict],
    fixed_day: dict | None,
    decision: dict | None,
    can_create_days: bool,
    taken_new_names: set[tuple[int, str]],
) -> dict[str, Any]:
    first = rows[0]
    sources = sorted({f"{r.sheet}" for r in rows})
    row_numbers = [r.row_number for r in rows]
    group: dict[str, Any] = {
        "key": key,
        "sources": sources,
        "row_count": len(rows),
        "row_span": f"{min(row_numbers)}–{max(row_numbers)}" if len(rows) > 1 else str(row_numbers[0]),
        "status": "",
        "reason": "",
        "candidates": [],
        "target": None,
        "decision": decision or {},
        "location_change": None,
        "needs_decision": False,
        "can_create": can_create_days,
    }
    locations = {str(r.get("location").value).strip() for r in rows if r.get("location").state == VALUE}
    incoming_location = next(iter(locations)) if len(locations) == 1 else ""
    if len(locations) > 1:
        group["warning"] = "Rows of this day list different locations; the location is not changed."

    if fixed_day is not None:
        group.update(
            status=DAY_FIXED, unit=fixed_day["unit_number"], day_name=fixed_day["day_name"],
            date=_iso(fixed_day["shooting_date"]), label=day_label(fixed_day),
            target={"kind": "existing", "day_id": int(fixed_day["id"])},
            reason="Day-specific import: every row goes to this shooting day.",
        )
        _location_change(group, fixed_day, incoming_location)
        return group

    unit = int(first.get("unit_number").value)
    raw_day = str(first.get("day_name").value)
    dkey = day_key(raw_day)
    dates = {r.get("shooting_date").value for r in rows if r.get("shooting_date").state == VALUE}
    group.update(unit=unit, day_name=raw_day, day_key=dkey, new_name=storage_day_name(raw_day))
    group["label"] = f"Unit {unit} · {storage_day_name(raw_day)}"
    if len(dates) > 1:
        group.update(
            status=DAY_INVALID, date="",
            reason="Rows of this day have different dates: " + ", ".join(sorted(_iso(d) for d in dates)) + ".",
        )
        return group
    incoming_date = next(iter(dates)) if dates else None
    group["date"] = _iso(incoming_date)
    group["label"] += f" · {_iso(incoming_date)}" if incoming_date else ""
    matches = [d for d in days if int(d["unit_number"]) == unit and day_key(d["day_name"]) == dkey]
    group["candidates"] = [_day_option(d) for d in matches]

    if len(matches) == 1:
        existing = matches[0]
        if incoming_date is None or incoming_date == existing["shooting_date"]:
            group.update(
                status=DAY_EXISTING, target={"kind": "existing", "day_id": int(existing["id"])},
                reason="Matches an existing day." + ("" if incoming_date else " The file has no date for it."),
                matched_label=day_label(existing),
            )
            _location_change(group, existing, incoming_location)
        else:
            group.update(
                status=DAY_CONFLICT, needs_decision=True,
                reason=(
                    f"{day_label(existing)} already exists with date {_iso(existing['shooting_date'])}; "
                    f"the file says {_iso(incoming_date)}. Choose the day to use."
                ),
            )
    elif len(matches) > 1:
        group.update(
            status=DAY_AMBIGUOUS, needs_decision=True,
            reason=f"{len(matches)} existing days match Unit {unit} / {raw_day}. Choose one.",
        )
    else:
        group.update(status=DAY_NEW, reason="No existing day matches; a new shooting day is proposed.")
        if not can_create_days:
            group.update(needs_decision=True, reason="No existing day matches and you cannot add shooting days. Choose an existing day or skip.")
        elif incoming_date is None:
            group.update(needs_decision=True, reason="New day without a date. Enter its date or choose an existing day.")
        else:
            name = storage_day_name(raw_day)
            if (unit, day_key(name)) in taken_new_names:
                group.update(status=DAY_INVALID, reason="The same new day appears twice in this import.")
                return group
            group["target"] = {"kind": "new", "unit": unit, "day_name": name, "date": _iso(incoming_date), "location": incoming_location}

    _apply_day_decision(group, decision, days=days, can_create_days=can_create_days, taken_new_names=taken_new_names, incoming_location=incoming_location)
    if group["target"] and group["target"]["kind"] == "new":
        taken_new_names.add((int(group["target"]["unit"]), day_key(group["target"]["day_name"])))
    return group


def _apply_day_decision(group, decision, *, days, can_create_days, taken_new_names, incoming_location) -> None:
    if not decision:
        return
    choice = str(decision.get("choice") or "")
    group["decision_error"] = ""
    if choice == "skip":
        group.update(target=None, skipped=True, needs_decision=False)
        return
    if choice.startswith("existing:"):
        try:
            day_id = int(choice.split(":", 1)[1])
        except ValueError:
            day_id = 0
        day = next((d for d in days if int(d["id"]) == day_id), None)
        if day is None:
            group["decision_error"] = "That shooting day is not part of this project."
            return
        group.update(
            target={"kind": "existing", "day_id": day_id}, needs_decision=False,
            matched_label=day_label(day), reason=group["reason"] + f" Using {day_label(day)}.",
        )
        _location_change(group, day, incoming_location)
        return
    if choice == "create":
        if not can_create_days:
            group["decision_error"] = "You do not have permission to add shooting days."
            return
        name = storage_day_name(str(decision.get("day_name") or group.get("day_name") or ""))
        unit = int(group.get("unit") or 1)
        try:
            new_date = date.fromisoformat(str(decision.get("date") or group.get("date") or ""))
        except ValueError:
            group["decision_error"] = "Enter a valid date for the new day."
            return
        if not day_key(name):
            group["decision_error"] = "Enter a name for the new day."
            return
        if any(int(d["unit_number"]) == unit and day_key(d["day_name"]) == day_key(name) for d in days):
            group["decision_error"] = f"Unit {unit} already has a day called {name}. Choose another name or that existing day."
            return
        if (unit, day_key(name)) in taken_new_names:
            group["decision_error"] = "Another day in this import already uses that name."
            return
        group.update(
            target={"kind": "new", "unit": unit, "day_name": name, "date": new_date.isoformat(), "location": incoming_location},
            needs_decision=False,
            reason=f"A new day, Unit {unit} · {name}, will be added on {new_date.isoformat()}.",
        )


def _location_change(group: dict, day: dict, incoming: str) -> None:
    current = str(day.get("location") or "").strip()
    if incoming and incoming != current:
        group["location_change"] = {"current": current, "incoming": incoming}


def _day_option(d: dict) -> dict:
    return {"id": int(d["id"]), "label": day_label(d)}


def _iso(d: Any) -> str:
    return d.isoformat() if isinstance(d, date) else (str(d) if d else "")


# --- Plan -------------------------------------------------------------------------


def build_plan(
    *,
    source_rows: list[SourceRow],
    is_tv: bool,
    max_episode: int,
    days: list[dict],
    rows: list[dict],
    legacy_rows: list[dict],
    fixed_day_id: int | None = None,
    day_decisions: dict[str, dict] | None = None,
    can_create_days: bool = True,
    mapped_fields: set[str] | None = None,
) -> dict[str, Any]:
    day_decisions = day_decisions or {}
    mapped = set(mapped_fields or ())
    days_by_id = {int(d["id"]): d for d in days}
    fixed_day = days_by_id.get(int(fixed_day_id)) if fixed_day_id else None
    if fixed_day_id and fixed_day is None:
        raise ValueError("The shooting day for this import no longer exists.")
    rows_by_id = {int(r["id"]): r for r in rows}
    rows_by_day: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        rows_by_day[int(r["day_id"])].append(r)
    legacy_by_day: dict[int, list[dict]] = defaultdict(list)
    for r in legacy_rows:
        legacy_by_day[int(r["day_id"])].append(r)
    project_scene_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        b = dup_bucket(episode_number=r.get("episode_number") or 0, unassigned=bool(r.get("is_episode_unassigned")), pool=bool(r.get("is_establishing_shots_pool")))
        project_scene_index[(b, label_key(r.get("scene_label")))].append(r)

    groups, orphans = _group_rows(source_rows, fixed_day=fixed_day)
    taken_new: set[tuple[int, str]] = set()
    day_plans: list[dict] = []
    for key, grows in groups.items():
        day_plans.append(_resolve_day_group(
            key, grows, days=days, fixed_day=fixed_day, decision=day_decisions.get(key),
            can_create_days=can_create_days, taken_new_names=taken_new,
        ))
    day_by_key = {g["key"]: g for g in day_plans}

    plan_rows: list[dict] = []
    for src, reason in orphans:
        plan_rows.append(_row_base(src, None, is_tv=is_tv) | {
            "status": STATUS_INVALID, "reason": reason, "allowed_actions": [ACTION_SKIP], "default_action": ACTION_SKIP,
        })

    seen_signatures: dict[tuple, str] = {}
    record_refs: dict[int, list[dict]] = defaultdict(list)
    new_scene_claims: dict[tuple[str, str], str] = {}
    identity_groups: dict[tuple, list[dict]] = defaultdict(list)

    ordered = sorted(
        ((g, src) for g in day_plans for src in groups[g["key"]]),
        key=lambda t: (t[1].sheet, t[1].row_number),
    )
    for group, src in ordered:
        ident, id_err = row_identity(src, is_tv=is_tv, max_episode=max_episode)
        base = _row_base(src, ident, is_tv=is_tv)
        base["day_key"] = group["key"]
        base["day_label"] = group.get("label", "")
        plan_rows.append(base)
        if group.get("skipped"):
            base.update(status=STATUS_INVALID, reason="Its shooting day is skipped.", allowed_actions=[ACTION_SKIP], default_action=ACTION_SKIP, day_skipped=True)
            continue
        errors = list(src.errors)
        if group["status"] == DAY_INVALID:
            errors.append({"sheet": src.sheet, "row": str(src.row_number), "column": "", "value": "", "message": group["reason"]})
        if id_err:
            errors.append({"sheet": src.sheet, "row": str(src.row_number), "column": "", "value": "", "message": id_err})
        if errors:
            base.update(status=STATUS_INVALID, reason=errors[0]["message"], errors=errors, allowed_actions=[ACTION_SKIP], default_action=ACTION_SKIP)
            continue
        if group.get("target") is None:
            base.update(
                status=STATUS_AMBIGUOUS, reason="Choose this row's shooting day first (see Shooting days above).",
                allowed_actions=[ACTION_SKIP], default_action=ACTION_SKIP, waiting_for_day=True,
            )
            continue
        sig = (group["key"], _source_signature(src))
        if sig in seen_signatures:
            base.update(
                status=STATUS_DUPLICATE, reason=f"Same identity and values as {seen_signatures[sig]}.",
                allowed_actions=[ACTION_SKIP], default_action=ACTION_SKIP,
            )
            continue
        seen_signatures[sig] = f"{src.sheet} row {src.row_number}"
        base["_src"] = src
        base["_ident"] = ident
        base["_group"] = group
        rec = src.get("record_id")
        if rec.state == VALUE:
            record_refs[int(rec.value)].append(base)
        else:
            identity_groups[(group["key"], ident["bucket"], ident["label_key"], ident["item_type"])].append(base)

    for record_id, refs in record_refs.items():
        if len(refs) > 1:
            for base in refs:
                base.update(
                    status=STATUS_AMBIGUOUS, reason=f"Several rows of the file reference record #{record_id}.",
                    allowed_actions=[ACTION_SKIP], default_action=ACTION_SKIP,
                )
            continue
        base = refs[0]
        group = base["_group"]
        existing = rows_by_id.get(record_id)
        if existing is None:
            base.update(status=STATUS_INVALID, reason=f"Record #{record_id} is not a shooting row of this project.", allowed_actions=[ACTION_SKIP], default_action=ACTION_SKIP)
            continue
        target = group["target"]
        if target["kind"] != "existing" or int(existing["day_id"]) != int(target["day_id"]):
            owner = days_by_id.get(int(existing["day_id"]))
            base.update(
                status=STATUS_INVALID,
                reason=f"Record #{record_id} belongs to {day_label(owner) if owner else 'another day'}, not this row's shooting day.",
                allowed_actions=[ACTION_SKIP], default_action=ACTION_SKIP,
            )
            continue
        _compare_with(base, existing, is_tv=is_tv, mapped=mapped)

    for (_gkey, bucket, lkey, item_type), bases in identity_groups.items():
        group = bases[0]["_group"]
        target = group["target"]
        candidates = []
        legacy_hits = []
        if target["kind"] == "existing":
            day_id = int(target["day_id"])
            candidates = [
                r for r in rows_by_day.get(day_id, [])
                if dup_bucket(episode_number=r.get("episode_number") or 0, unassigned=bool(r.get("is_episode_unassigned")), pool=bool(r.get("is_establishing_shots_pool"))) == bucket
                and label_key(r.get("scene_label")) == lkey
                and si.normalize_shooting_item_type(r.get("shooting_item_type")) == item_type
            ]
            legacy_hits = [r for r in legacy_by_day.get(day_id, []) if _legacy_matches(r, bases[0]["_ident"], is_tv=is_tv)]
        k, m = len(bases), len(candidates)
        if k == 1 and m == 1:
            _compare_with(bases[0], candidates[0], is_tv=is_tv, mapped=mapped)
            continue
        if m >= 1:
            for base in bases:
                reason = (
                    f"{m} existing rows on this day share this identity" if m > 1
                    else "The file has several rows for one existing row on this day"
                ) + " — reshoots and takes are never merged. Choose the row to update, or skip."
                _ambiguous_with_candidates(base, candidates, reason, is_tv=is_tv, mapped=mapped)
            continue
        for idx, base in enumerate(bases):
            ident = base["_ident"]
            if ident["legacy_type"]:
                base.update(status=STATUS_INVALID, reason=f"“{ident['item_type']}” is a legacy type and cannot be created; use a current item type.", allowed_actions=[ACTION_SKIP], default_action=ACTION_SKIP)
                continue
            if k > 1 and si.should_check_episode_scene_duplicate(item_type):
                base.update(
                    status=STATUS_AMBIGUOUS,
                    reason="The file has this scene more than once on the same day with different values. Add the others as Reshoot, or skip.",
                    allowed_actions=[ACTION_SKIP, ACTION_ADD_RESHOOT] + ([ACTION_ADD] if idx == 0 else []),
                    default_action=ACTION_SKIP,
                )
                continue
            if legacy_hits:
                base.update(
                    status=STATUS_AMBIGUOUS,
                    reason=f"Matches legacy spreadsheet row #{legacy_hits[0]['id']} on this day. Legacy rows are not changed by imports; add a new row only if it is a different item.",
                    allowed_actions=[ACTION_SKIP, ACTION_ADD], default_action=ACTION_SKIP,
                    legacy_match={"id": int(legacy_hits[0]["id"]), "label": legacy_hits[0].get("label", "")},
                )
                continue
            if si.should_check_episode_scene_duplicate(item_type):
                elsewhere = project_scene_index.get((bucket, lkey)) or []
                if elsewhere:
                    other = elsewhere[0]
                    owner = days_by_id.get(int(other["day_id"]))
                    base.update(
                        status=STATUS_AMBIGUOUS,
                        reason=(
                            f"Scene {ident['scene_label']} already exists in {ident['episode_display']} "
                            f"({day_label(owner) if owner else 'another day'}). Add it as a Reshoot, or skip."
                        ),
                        allowed_actions=[ACTION_SKIP, ACTION_ADD_RESHOOT], default_action=ACTION_SKIP,
                        conflict_record={"id": int(other["id"]), "day": day_label(owner) if owner else ""},
                    )
                    continue
                claim = (bucket, lkey)
                if claim in new_scene_claims:
                    base.update(
                        status=STATUS_AMBIGUOUS,
                        reason=f"This scene is already added from {new_scene_claims[claim]}. Add it as a Reshoot, or skip.",
                        allowed_actions=[ACTION_SKIP, ACTION_ADD_RESHOOT], default_action=ACTION_SKIP,
                    )
                    continue
                new_scene_claims[claim] = f"{base['sheet']} row {base['row_number']}"
            note = " Added as a separate item (takes are never merged)." if k > 1 else ""
            base.update(
                status=STATUS_NEW,
                reason=("New row on a new shooting day." if target["kind"] == "new" else "No matching row on this day.") + note,
                allowed_actions=[ACTION_ADD, ACTION_SKIP], default_action=ACTION_ADD,
                incoming=_incoming_fields(base["_src"], ident, is_tv=is_tv),
            )

    for base in plan_rows:
        base.pop("_src", None)
        base.pop("_ident", None)
        base.pop("_group", None)
        base.setdefault("errors", [])
        base.setdefault("candidates", [])
        base["fingerprint"] = fingerprint({k: v for k, v in base.items() if k not in ("fingerprint", "default_action")})
    for g in day_plans:
        day = days_by_id.get(int(g["target"]["day_id"])) if g.get("target") and g["target"]["kind"] == "existing" else None
        g["fingerprint"] = fingerprint({
            "target": g.get("target"),
            "day": [day.get("unit_number"), day.get("day_name"), _iso(day.get("shooting_date")), day.get("location")] if day else None,
            "status": g["status"],
        })
    plan_rows.sort(key=lambda r: (r["sheet"], r["row_number"]))
    return {"days": day_plans, "rows": plan_rows, "counts": count_statuses(plan_rows)}


def _row_base(src: SourceRow, ident: dict | None, *, is_tv: bool) -> dict[str, Any]:
    return {
        "id": f"{src.sheet}!{src.row_number}",
        "sheet": src.sheet,
        "row_number": src.row_number,
        "identity": _identity_display(ident, src),
        "identity_parts": {
            "item_type": ident["item_type"], "bucket": ident["bucket"], "scene_label": ident["scene_label"],
        } if ident else None,
        "values": {k: v.display for k, v in src.values.items() if v.state != EMPTY},
        "inherited": dict(src.inherited),
        "errors": [],
        "match": None,
        "diffs": [],
        "clearable": [],
        "candidates": [],
    }


def _compare_with(base: dict, existing: dict, *, is_tv: bool, mapped: set[str]) -> None:
    current = current_fields(existing, is_tv=is_tv)
    incoming = _incoming_fields(base["_src"], base["_ident"], is_tv=is_tv)
    diffs = _diffs(current, incoming)
    clearable = _clearable(base["_src"], current, mapped)
    base["match"] = {
        "id": int(existing["id"]), "day_id": int(existing["day_id"]),
        "label": _existing_label(existing, is_tv=is_tv),
        "current": {k: v["display"] for k, v in current.items()},
        "runtime_selected": bool(existing.get("runtime_selected")),
    }
    base["incoming"] = incoming
    base["diffs"] = diffs
    base["clearable"] = clearable
    if diffs:
        base.update(
            status=STATUS_CHANGED,
            reason=f"{len(diffs)} field(s) differ from row #{existing['id']}. Review before updating.",
            allowed_actions=[ACTION_UPDATE, ACTION_SKIP], default_action=ACTION_SKIP,
        )
    else:
        base.update(
            status=STATUS_IDENTICAL,
            reason=f"Same as row #{existing['id']}." + (" Some mapped cells are empty; existing values are kept." if clearable else ""),
            allowed_actions=[ACTION_SKIP] + ([ACTION_UPDATE] if clearable else []), default_action=ACTION_SKIP,
        )


def _ambiguous_with_candidates(base: dict, candidates: list[dict], reason: str, *, is_tv: bool, mapped: set[str]) -> None:
    incoming = _incoming_fields(base["_src"], base["_ident"], is_tv=is_tv)
    opts = []
    for c in candidates:
        current = current_fields(c, is_tv=is_tv)
        opts.append({
            "id": int(c["id"]),
            "label": _existing_label(c, is_tv=is_tv),
            "current": {k: v["display"] for k, v in current.items()},
            "diffs": _diffs(current, incoming),
            "clearable": _clearable(base["_src"], current, mapped),
            "runtime_selected": bool(c.get("runtime_selected")),
        })
    allowed = [ACTION_SKIP, ACTION_UPDATE]
    if not si.should_check_episode_scene_duplicate(base["_ident"]["item_type"]) and not base["_ident"]["legacy_type"]:
        allowed.append(ACTION_ADD)
    base.update(
        status=STATUS_AMBIGUOUS, reason=reason, candidates=opts, incoming=incoming,
        allowed_actions=allowed, default_action=ACTION_SKIP,
    )


def _existing_label(row: dict, *, is_tv: bool) -> str:
    item_type = si.normalize_shooting_item_type(row.get("shooting_item_type"))
    bucket = dup_bucket(episode_number=row.get("episode_number") or 0, unassigned=bool(row.get("is_episode_unassigned")), pool=bool(row.get("is_establishing_shots_pool")))
    ep = bucket_label(bucket, is_tv=is_tv, item_type=item_type)
    parts = [f"#{row['id']}"]
    if ep not in ("—", ""):
        parts.append(ep)
    parts.append(str(row.get("scene_label") or "(no scene)"))
    parts.append(item_type)
    if row.get("duration_seconds"):
        parts.append(format_duration(row.get("duration_seconds")))
    return " · ".join(parts)


def _legacy_matches(row: dict, ident: dict, *, is_tv: bool) -> bool:
    if label_key(row.get("scene")) != ident["label_key"] or not ident["label_key"]:
        return False
    if not is_tv:
        return True
    raw = fold_text(row.get("episode"))
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not raw:
        return True
    if ident["bucket"].startswith("ep:"):
        return digits == ident["bucket"].split(":", 1)[1]
    return raw in ("x", "episode x") and ident["bucket"] == "x"


def count_statuses(plan_rows: list[dict]) -> dict[str, int]:
    counts = {k: 0 for k in STATUS_LABELS}
    for r in plan_rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


# --- Decisions --------------------------------------------------------------------


def default_decisions(plan: dict) -> dict[str, dict]:
    out = {}
    for r in plan["rows"]:
        out[r["id"]] = {"action": r.get("default_action", ACTION_SKIP)}
    return out


def validate_decisions(plan: dict, decisions: dict[str, Any]) -> tuple[dict[str, dict], list[str]]:
    """Normalise user choices against the plan. Nothing is accepted that the plan does not allow."""
    errors: list[str] = []
    out: dict[str, dict] = {}
    updated_targets: dict[int, str] = {}
    day_by_key = {g["key"]: g for g in plan["days"]}
    for r in plan["rows"]:
        raw = decisions.get(r["id"]) if isinstance(decisions, dict) else None
        raw = raw if isinstance(raw, dict) else {"action": r.get("default_action", ACTION_SKIP)}
        action = str(raw.get("action") or ACTION_SKIP)
        where = f"{r['sheet']} row {r['row_number']}"
        if action not in r.get("allowed_actions", [ACTION_SKIP]):
            errors.append(f"{where}: “{ACTION_LABELS.get(action, action)}” is not allowed for a {STATUS_LABELS[r['status']]} row.")
            continue
        if action == ACTION_SKIP:
            out[r["id"]] = {"action": ACTION_SKIP}
            continue
        group = day_by_key.get(r.get("day_key") or "")
        if group is None or not group.get("target"):
            errors.append(f"{where}: choose its shooting day first.")
            continue
        if action in (ACTION_ADD, ACTION_ADD_RESHOOT):
            out[r["id"]] = {"action": action}
            continue
        target_id = raw.get("target_id")
        try:
            target_id = int(target_id) if target_id not in (None, "") else (r["match"]["id"] if r.get("match") else None)
        except (TypeError, ValueError):
            target_id = None
        if r.get("match") and target_id == r["match"]["id"]:
            diffs, clearable = r["diffs"], r["clearable"]
        else:
            cand = next((c for c in r.get("candidates", []) if c["id"] == target_id), None)
            if cand is None:
                errors.append(f"{where}: choose which existing row to update.")
                continue
            diffs, clearable = cand["diffs"], cand["clearable"]
        allowed_fields = {d["field"] for d in diffs}
        allowed_clear = {c["field"] for c in clearable}
        fields = [str(f) for f in (raw.get("fields") or []) if str(f) in allowed_fields]
        clear = [str(f) for f in (raw.get("clear") or []) if str(f) in allowed_clear and str(f) not in fields]
        if not fields and not clear:
            errors.append(f"{where}: select at least one field to update, or keep the row.")
            continue
        if target_id in updated_targets:
            errors.append(f"{where}: row #{target_id} is already updated by {updated_targets[target_id]}.")
            continue
        updated_targets[target_id] = where
        out[r["id"]] = {"action": ACTION_UPDATE, "target_id": target_id, "fields": fields, "clear": clear}
    return out, errors


def summarize_decisions(plan: dict, decisions: dict[str, dict]) -> dict[str, Any]:
    day_by_key = {g["key"]: g for g in plan["days"]}
    new_days: set[str] = set()
    adds = updates = fields = clears = skipped = 0
    for r in plan["rows"]:
        d = decisions.get(r["id"]) or {"action": ACTION_SKIP}
        if d["action"] in (ACTION_ADD, ACTION_ADD_RESHOOT):
            adds += 1
            g = day_by_key.get(r.get("day_key") or "")
            if g and g.get("target") and g["target"]["kind"] == "new":
                new_days.add(g["key"])
        elif d["action"] == ACTION_UPDATE:
            updates += 1
            fields += len(d.get("fields") or [])
            clears += len(d.get("clear") or [])
        else:
            skipped += 1
    location_updates = sum(
        1 for g in plan["days"]
        if g.get("location_change") and (g.get("decision") or {}).get("update_location") and g.get("target", {}) and g["target"]["kind"] == "existing"
    )
    return {
        "days_created": len(new_days),
        "rows_added": adds,
        "rows_updated": updates,
        "fields_updated": fields,
        "fields_cleared": clears,
        "rows_skipped": skipped,
        "day_locations_updated": location_updates,
    }
