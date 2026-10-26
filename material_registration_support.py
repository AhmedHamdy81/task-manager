"""Material registration for shooting days (shared status for every Machine Room view).

One ``mr_material_registration`` row per shooting day is the authoritative record of
what material arrived for that day. Status is derived from that row plus evidence
already stored elsewhere (workflow links, legacy HDD / volume usage, ingest batches),
so Production, Missing Information, Backups and Tasks all read the same answer.

Registration never claims a copy or a backup exists: protection stays with the
existing ingest / workflow records.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Callable, Iterable

import notification_events as notif_events

TABLE_NAME = "mr_material_registration"

# Media presence: a size of 0 or an empty field never means "no media".
MEDIA_UNKNOWN = "unknown"
MEDIA_PRESENT = "present"
MEDIA_NONE = "none"
MEDIA_STATES: tuple[str, ...] = (MEDIA_UNKNOWN, MEDIA_PRESENT, MEDIA_NONE)

MATERIAL_SOURCES: tuple[tuple[str, str], ...] = (
    ("transfer_shuttle", "Transfer / Shuttle drive"),
    ("camera_cards", "Camera cards / mags"),
    ("production_drive", "Production hard drive"),
    ("network_transfer", "Network transfer"),
    ("other", "Other"),
)
MATERIAL_SOURCE_LABELS: dict[str, str] = dict(MATERIAL_SOURCES)

STATUS_AWAITING = "awaiting"
STATUS_UPCOMING = "upcoming"
STATUS_REGISTERED = "registered"
STATUS_IN_WORKFLOW = "in_workflow"

STATUS_LABELS: dict[str, str] = {
    STATUS_AWAITING: "Awaiting material registration",
    STATUS_UPCOMING: "Awaiting material (upcoming day)",
    STATUS_REGISTERED: "Registered — copy not started",
    STATUS_IN_WORKFLOW: "Copy in progress",
}

PROTECTION_UNREGISTERED = "Unknown — material receipt not registered"
PROTECTION_NOT_COPIED = "Not protected — no copy recorded"

FIELD_LABELS: dict[str, str] = {
    "video": "Video size",
    "audio": "Audio size",
    "material_source": "Material source",
    "source": "Source disk / volume",
    "operator": "Responsible operator",
}
REQUIRED_FIELDS: tuple[str, ...] = tuple(FIELD_LABELS)

NOTIFY_EVENT_KEY = "machine_room_material_registered"

notif_events.register_notification_event(
    NOTIFY_EVENT_KEY,
    {
        "label": "Machine Room Material Registered",
        "category": "system",
        "description": (
            "Sent to the project team once when a shooting day's material registration is "
            "completed. Registration does not mean the material has been copied or backed up."
        ),
        "source": "Machine Room",
        "source_file": "material_registration_routes.py",
        "source_function": "_notify_registered",
        "source_feature": "Material registration",
        "default_title": "{{ notification_title }}",
        "default_body": "{{ notification_body }}",
        "default_cta_label": "",
        "default_cta_url": "",
        "default_recipients": {"preset": "project_team"},
        "exclude_actor": False,
        "dedupe_enabled": True,
        "variables": list(notif_events.COMMON_VARIABLES) + ["shooting_day", "registration_id"],
        "is_active": True,
    },
)

_models: dict[str, Any] = {}


def register_material_registration_model(db, now_local) -> Any:
    """Register the SQLAlchemy model once; return it."""
    if "MaterialRegistration" in _models:
        return _models["MaterialRegistration"]

    class MaterialRegistration(db.Model):
        __tablename__ = TABLE_NAME
        __table_args__ = (
            db.UniqueConstraint("shooting_day_id", name="uq_mr_material_registration_day"),
        )

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        shooting_day_id = db.Column(
            db.Integer, db.ForeignKey("shooting_days_flat.id"), nullable=False, index=True
        )
        video_state = db.Column(db.String(16), nullable=False, default=MEDIA_UNKNOWN)
        video_size_tb = db.Column(db.Float, nullable=True)
        audio_state = db.Column(db.String(16), nullable=False, default=MEDIA_UNKNOWN)
        audio_size_gb = db.Column(db.Float, nullable=True)
        material_source = db.Column(db.String(32), nullable=False, default="")
        source_volume_id = db.Column(
            db.Integer, db.ForeignKey("mr_storage_volume.id"), nullable=True, index=True
        )
        source_label = db.Column(db.String(160), nullable=False, default="")
        source_path = db.Column(db.String(512), nullable=False, default="")
        responsible_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        notes = db.Column(db.Text, nullable=False, default="")
        completed_at = db.Column(db.DateTime, nullable=True)
        completed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        completed_by_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
        updated_by_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)
        updated_at = db.Column(db.DateTime, nullable=False, default=now_local, onupdate=now_local)

    _models["MaterialRegistration"] = MaterialRegistration
    return MaterialRegistration


def ensure_material_registration_table(db, now_local) -> Any:
    """Create the table if missing (SQLite-safe, never touches existing rows)."""
    model = register_material_registration_model(db, now_local)
    model.__table__.create(bind=db.engine, checkfirst=True)
    return model


# --- Field parsing ----------------------------------------------------------


def parse_media(state_raw: Any, size_raw: Any, *, unit: str) -> tuple[str, float | None, str]:
    """(state, size, error). Empty size never becomes 0 and never means "none"."""
    state = str(state_raw or MEDIA_UNKNOWN).strip().lower()
    if state not in MEDIA_STATES:
        return MEDIA_UNKNOWN, None, f"Unknown {unit} state."
    if state != MEDIA_PRESENT:
        return state, None, ""
    text = str(size_raw if size_raw is not None else "").strip()
    if not text:
        return state, None, f"Enter the {unit} size, or choose Unknown."
    try:
        size = float(text)
    except (TypeError, ValueError):
        return state, None, f"The {unit} size must be a number."
    if size <= 0:
        return state, None, f"The {unit} size must be greater than 0 (choose No {unit} if there is none)."
    return state, size, ""


def media_known(state: str | None, size: float | None) -> bool:
    if state == MEDIA_NONE:
        return True
    return state == MEDIA_PRESENT and size is not None and size > 0


def media_display(state: str | None, size: float | None, unit: str) -> str:
    if state == MEDIA_NONE:
        return f"No {unit.split()[0].lower()}"
    if state == MEDIA_PRESENT and size:
        return f"{size:g} {unit.split()[-1]}"
    return "Unknown"


# --- Status derivation ------------------------------------------------------


def _positive(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def build_evidence(
    *,
    day_ids: list[int],
    workflows_by_day: dict[int, Any],
    volume_usages: Iterable[Any],
    hdd_usages: Iterable[Any],
    batches: Iterable[Any],
    workflow_member_counts: dict[int, int] | None = None,
) -> dict[int, dict[str, Any]]:
    """Facts about each day's material already stored outside the registration row.

    A workflow's backup sizes are the operation total for all of its days, so they count
    as a day's own size only when that workflow covers exactly one day. Shared totals are
    never copied to, or split across, member days.
    """
    ev: dict[int, dict[str, Any]] = {did: {} for did in day_ids}
    member_counts = workflow_member_counts or {}

    def keep(did: int, key: str, value: Any, origin: str) -> None:
        bucket = ev.get(did)
        if bucket is None or value is None or key in bucket:
            return
        bucket[key] = (value, origin)

    for did, w in workflows_by_day.items():
        if w is None:
            continue
        if member_counts.get(int(w.id), 0) == 1:
            keep(did, "video_tb", _positive(getattr(w, "backup_video_size_tb", None)), "workflow")
            keep(did, "audio_gb", _positive(getattr(w, "backup_audio_size_gb", None)), "workflow")
        if getattr(w, "shuttle_volume_id", None):
            keep(did, "source_volume_id", int(w.shuttle_volume_id), "workflow")
            keep(did, "material_source", "transfer_shuttle", "workflow")
        operator = getattr(w, "assigned_operator_id", None) or getattr(w, "received_by_id", None)
        if operator:
            keep(did, "operator_user_id", int(operator), "workflow")
    for u in volume_usages:
        did = int(u.shooting_day_id)
        keep(did, "video_tb", _positive(u.video_size_tb), "volume usage")
        audio_tb = _positive(u.audio_size_tb)
        keep(did, "audio_gb", audio_tb * 1000.0 if audio_tb else None, "volume usage")
    for u in hdd_usages:
        did = int(u.shooting_day_id)
        keep(did, "video_tb", _positive(u.video_size_tb), "HDD usage")
        audio_tb = _positive(u.audio_size_tb)
        keep(did, "audio_gb", audio_tb * 1000.0 if audio_tb else None, "HDD usage")
    for b in batches:
        if not getattr(b, "shooting_day_id", None):
            continue
        did = int(b.shooting_day_id)
        keep(did, "video_tb", _positive(b.video_size_tb), "media copy")
        keep(did, "audio_gb", _positive(b.audio_size_gb), "media copy")
        if b.copy_started_at or (b.status or "") in ("copying", "copied", "verified", "complete", "completed"):
            keep(did, "copy_started", True, "media copy")
    return ev


def derive_status(
    day: Any,
    reg: Any | None,
    workflow: Any | None,
    evidence: dict[str, Any],
    *,
    today: date,
    volume_names: dict[int, str],
    user_names: dict[int, str],
) -> dict[str, Any]:
    """Shared status for one shooting day. Pure: no queries, no writes."""

    def ev(key: str):
        pair = evidence.get(key)
        return pair if pair else (None, "")

    fields: dict[str, dict[str, Any]] = {}

    # Video / audio: the registration row wins; positive recorded sizes count as known.
    for key, unit, ev_key in (("video", "TB", "video_tb"), ("audio", "GB", "audio_gb")):
        state = getattr(reg, f"{key}_state", None) if reg is not None else None
        size = getattr(reg, f"{key}_size_{'tb' if key == 'video' else 'gb'}", None) if reg is not None else None
        origin = "registration"
        if not media_known(state, size):
            value, ev_origin = ev(ev_key)
            if value:
                state, size, origin = MEDIA_PRESENT, float(value), ev_origin
            else:
                state, size, origin = state or MEDIA_UNKNOWN, None, ""
        fields[key] = {
            "known": media_known(state, size),
            "state": state or MEDIA_UNKNOWN,
            "size": size,
            "display": media_display(state, size, f"{key} {unit}"),
            "origin": origin if media_known(state, size) else "",
        }

    source_key = (getattr(reg, "material_source", "") or "") if reg is not None else ""
    source_origin = "registration" if source_key else ""
    if not source_key:
        value, origin = ev("material_source")
        source_key, source_origin = (value or ""), origin
    fields["material_source"] = {
        "known": bool(source_key),
        "value": source_key,
        "display": MATERIAL_SOURCE_LABELS.get(source_key, source_key) or "—",
        "origin": source_origin,
    }

    vol_id = getattr(reg, "source_volume_id", None) if reg is not None else None
    label = ((getattr(reg, "source_label", "") or "").strip()) if reg is not None else ""
    vol_origin = "registration" if (vol_id or label) else ""
    if not vol_id and not label:
        value, origin = ev("source_volume_id")
        vol_id, vol_origin = value, origin
    fields["source"] = {
        "known": bool(vol_id or label),
        "volume_id": int(vol_id) if vol_id else None,
        "label": label,
        "display": volume_names.get(int(vol_id), f"Volume #{vol_id}") if vol_id else (label or "—"),
        "origin": vol_origin,
    }

    op_id = getattr(reg, "responsible_user_id", None) if reg is not None else None
    op_origin = "registration" if op_id else ""
    if not op_id:
        value, origin = ev("operator_user_id")
        op_id, op_origin = value, origin
    fields["operator"] = {
        "known": bool(op_id),
        "user_id": int(op_id) if op_id else None,
        "display": user_names.get(int(op_id), "—") if op_id else "—",
        "origin": op_origin,
    }

    missing = [k for k in REQUIRED_FIELDS if not fields[k]["known"]]
    complete = not missing
    upcoming = bool(day.shooting_date and day.shooting_date > today)
    copy_started = bool(
        (workflow is not None and getattr(workflow, "backup_started_at", None))
        or ev("copy_started")[0]
    )

    if copy_started:
        status = STATUS_IN_WORKFLOW
    elif complete:
        status = STATUS_REGISTERED
    elif upcoming:
        status = STATUS_UPCOMING
    else:
        status = STATUS_AWAITING

    label_text = STATUS_LABELS[status]
    if status == STATUS_IN_WORKFLOW and workflow is not None:
        try:
            label_text = workflow.media_prep_label().title()
        except Exception:
            pass
    # What the registration queue shows: an unfinished registration outranks workflow progress.
    if not complete:
        display_status = STATUS_UPCOMING if upcoming else STATUS_AWAITING
    else:
        display_status = status
    display_label = STATUS_LABELS[display_status] if display_status != STATUS_IN_WORKFLOW else label_text

    return {
        "shooting_day_id": int(day.id),
        "project_id": int(day.project_id),
        "unit_number": int(day.unit_number or 1),
        "day_name": day.day_name or "",
        "shooting_date": day.shooting_date.isoformat() if day.shooting_date else "",
        "upcoming": upcoming,
        "status": status,
        "status_label": label_text,
        "display_status": display_status,
        "display_label": display_label,
        "needs_registration": not complete,
        "complete": complete,
        "copy_started": copy_started,
        "missing": missing,
        "missing_labels": [FIELD_LABELS[k] for k in missing],
        "fields": fields,
        "source_path": ((getattr(reg, "source_path", "") or "") if reg is not None else ""),
        "notes": ((getattr(reg, "notes", "") or "") if reg is not None else ""),
        "registration_id": int(reg.id) if reg is not None else None,
        "completed_at": (
            reg.completed_at.isoformat(timespec="minutes") if reg is not None and reg.completed_at else ""
        ),
        "workflow_id": int(workflow.id) if workflow is not None else None,
        "workflow_label": workflow.media_prep_label() if workflow is not None else "",
        "protection": PROTECTION_UNREGISTERED if not complete else (
            PROTECTION_NOT_COPIED if not copy_started else ""
        ),
    }


def operation_size_defaults(
    rows: Iterable[dict[str, Any]],
    *,
    explicit_video_tb: float | None = None,
    explicit_audio_gb: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Copy-step size defaults for one operation covering ``rows`` (the workflow's days).

    Sizes recorded on the workflow itself are operator-entered operation values and win.
    Otherwise the per-day registration amounts are combined: an explicit "no video/audio"
    counts as 0, an unknown day leaves the total unknown (never a partial sum). Nothing is
    stored; the workflow only gets sizes when the operator starts the copy.
    """
    rows = list(rows)
    out: dict[str, dict[str, Any]] = {}
    for key, unit, explicit in (("video", "TB", explicit_video_tb), ("audio", "GB", explicit_audio_gb)):
        day_count = len(rows)
        if explicit is not None:
            out[key] = {
                "value": float(explicit),
                "source": "workflow",
                "hint": "",
                "unknown_days": [],
                "day_count": day_count,
            }
            continue
        unknown = [r.get("day_label") or f"Day #{r['shooting_day_id']}" for r in rows if not r["fields"][key]["known"]]
        if not rows or unknown:
            noun = key
            out[key] = {
                "value": None,
                "source": "incomplete",
                "hint": (
                    f"Total incomplete — {noun} size not registered for {', '.join(unknown)}."
                    if unknown
                    else ""
                ),
                "unknown_days": unknown,
                "day_count": day_count,
            }
            continue
        total = round(sum(float(r["fields"][key]["size"] or 0) for r in rows), 4)
        if total == 0:
            hint = f"No {key} registered for {'this day' if day_count == 1 else 'these days'}."
        elif day_count == 1:
            hint = "From material registration."
        else:
            hint = f"Combined from {day_count} registered days."
        out[key] = {
            "value": total,
            "source": "registration",
            "hint": hint,
            "unknown_days": [],
            "day_count": day_count,
        }
    return out


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Counts every page shows, computed from the same derived rows."""
    rows = list(rows)
    need = [r for r in rows if r["needs_registration"]]
    return {
        "needs_registration": len(need),
        "due": sum(1 for r in need if not r["upcoming"]),
        "upcoming": sum(1 for r in need if r["upcoming"]),
        "registered_not_copied": sum(1 for r in rows if r["status"] == STATUS_REGISTERED),
    }


class RegistrationService:
    """Loads every record the status needs in a few queries; nothing is written here."""

    def __init__(
        self,
        *,
        db,
        ShootingDay,
        Project,
        User,
        StorageVolume,
        StorageVolumeShootingDayUsage,
        MediaIngestBatch,
        HardDiskUsage,
        Workflow,
        WorkflowDay,
        Registration,
        today_fn: Callable[[], date],
    ):
        self.db = db
        self.m = SimpleNamespace(
            ShootingDay=ShootingDay,
            Project=Project,
            User=User,
            StorageVolume=StorageVolume,
            StorageVolumeShootingDayUsage=StorageVolumeShootingDayUsage,
            MediaIngestBatch=MediaIngestBatch,
            HardDiskUsage=HardDiskUsage,
            Workflow=Workflow,
            WorkflowDay=WorkflowDay,
            Registration=Registration,
        )
        self.today_fn = today_fn

    def _days(self, project_ids, day_ids):
        q = self.m.ShootingDay.query
        if project_ids is not None:
            ids = sorted({int(x) for x in project_ids})
            if not ids:
                return []
            q = q.filter(self.m.ShootingDay.project_id.in_(ids))
        if day_ids is not None:
            ids = sorted({int(x) for x in day_ids})
            if not ids:
                return []
            q = q.filter(self.m.ShootingDay.id.in_(ids))
        return q.order_by(
            self.m.ShootingDay.shooting_date.asc(),
            self.m.ShootingDay.unit_number.asc(),
            self.m.ShootingDay.id.asc(),
        ).all()

    def workflows_by_day(self, day_ids: list[int]) -> dict[int, Any]:
        """Direct workflow.shooting_day_id and the multi-day association table both count."""
        if not day_ids:
            return {}
        WF, Link = self.m.Workflow, self.m.WorkflowDay
        out: dict[int, Any] = {}
        for link in Link.query.filter(Link.shooting_day_id.in_(day_ids)).all():
            wf_row = self.db.session.get(WF, int(link.workflow_id))
            if wf_row is not None:
                out[int(link.shooting_day_id)] = wf_row
        for wf_row in WF.query.filter(WF.shooting_day_id.in_(day_ids)).all():
            out.setdefault(int(wf_row.shooting_day_id), wf_row)
        return out

    def workflow_member_counts(self, workflows) -> dict[int, int]:
        """Days per workflow: association rows plus the direct shooting_day_id, de-duplicated.

        Counts every member day, not only the days being looked at, so a two-day workflow
        is still two days when one of its days is queried on its own.
        """
        wf_rows = {int(w.id): w for w in workflows if w is not None}
        if not wf_rows:
            return {}
        Link = self.m.WorkflowDay
        members: dict[int, set[int]] = {
            wid: ({int(w.shooting_day_id)} if w.shooting_day_id else set()) for wid, w in wf_rows.items()
        }
        for link in Link.query.filter(Link.workflow_id.in_(list(wf_rows))).all():
            members[int(link.workflow_id)].add(int(link.shooting_day_id))
        return {wid: len(days) for wid, days in members.items()}

    def statuses(self, project_ids=None, day_ids=None) -> list[dict[str, Any]]:
        """project_ids None = all projects (caller already applied visibility)."""
        days = self._days(project_ids, day_ids)
        if not days:
            return []
        ids = [int(d.id) for d in days]
        regs = {
            int(r.shooting_day_id): r
            for r in self.m.Registration.query.filter(self.m.Registration.shooting_day_id.in_(ids)).all()
        }
        workflows = self.workflows_by_day(ids)
        evidence = build_evidence(
            day_ids=ids,
            workflows_by_day=workflows,
            volume_usages=self.m.StorageVolumeShootingDayUsage.query.filter(
                self.m.StorageVolumeShootingDayUsage.shooting_day_id.in_(ids)
            ).all(),
            hdd_usages=(
                self.m.HardDiskUsage.query.filter(self.m.HardDiskUsage.shooting_day_id.in_(ids)).all()
                if self.m.HardDiskUsage is not None
                else []
            ),
            batches=self.m.MediaIngestBatch.query.filter(
                self.m.MediaIngestBatch.shooting_day_id.in_(ids)
            ).all(),
            workflow_member_counts=self.workflow_member_counts(workflows.values()),
        )
        volume_names = {
            int(v.id): ((v.display_name or v.name or "").strip() or f"Volume #{v.id}")
            for v in self.m.StorageVolume.query.all()
        }
        user_ids = {
            int(x)
            for x in [getattr(r, "responsible_user_id", None) for r in regs.values()]
            + [getattr(w, "assigned_operator_id", None) for w in workflows.values()]
            + [getattr(w, "received_by_id", None) for w in workflows.values()]
            if x
        }
        user_names = (
            {int(u.id): (u.name or u.email or f"User {u.id}") for u in self.m.User.query.filter(self.m.User.id.in_(user_ids)).all()}
            if user_ids
            else {}
        )
        project_names = {
            int(p.id): p.name or f"Project #{p.id}"
            for p in self.m.Project.query.filter(self.m.Project.id.in_({int(d.project_id) for d in days})).all()
        }
        today = self.today_fn()
        rows = []
        for d in days:
            row = derive_status(
                d,
                regs.get(int(d.id)),
                workflows.get(int(d.id)),
                evidence.get(int(d.id), {}),
                today=today,
                volume_names=volume_names,
                user_names=user_names,
            )
            row["project_name"] = project_names.get(int(d.project_id), "")
            row["day_label"] = day_label(d)
            rows.append(row)
        return rows

    def status_for_day(self, day_id: int) -> dict[str, Any] | None:
        rows = self.statuses(day_ids=[int(day_id)])
        return rows[0] if rows else None


def day_label(day: Any) -> str:
    parts = [f"Unit {int(day.unit_number or 1)}"]
    name = (day.day_name or "").strip()
    if name:
        parts.append(name if name.lower().startswith("day") else f"Day {name}")
    if day.shooting_date:
        parts.append(day.shooting_date.isoformat())
    return " · ".join(parts)


def registration_snapshot(reg: Any) -> dict[str, Any]:
    """Field values recorded on the Log Book entry (sizes stay None when unknown)."""
    return {
        "video_state": reg.video_state,
        "video_size_tb": reg.video_size_tb,
        "audio_state": reg.audio_state,
        "audio_size_gb": reg.audio_size_gb,
        "material_source": reg.material_source,
        "source_volume_id": reg.source_volume_id,
        "source_label": reg.source_label,
        "source_path": reg.source_path,
        "responsible_user_id": reg.responsible_user_id,
    }
