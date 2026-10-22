"""Machine Room guided daily media processing workflow.

Operator-facing state machine for Receive → Backup → Transcode → Complete.
No filesystem copy or ffmpeg automation is claimed; progress is recorded from
operator confirmations and optional linked Task / MediaTranscodeJob rows.
"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import notification_events as notif_events

# Stages (ordered)
STAGE_RECEIVE = "receive"
STAGE_BACKUP = "backup"
STAGE_TRANSCODE = "transcode"
STAGE_COMPLETE = "complete"
WORKFLOW_STAGES: tuple[str, ...] = (
    STAGE_RECEIVE,
    STAGE_BACKUP,
    STAGE_TRANSCODE,
    STAGE_COMPLETE,
)

STAGE_LABELS: dict[str, str] = {
    STAGE_RECEIVE: "Receive",
    STAGE_BACKUP: "Backup",
    STAGE_TRANSCODE: "Transcode",
    STAGE_COMPLETE: "Complete",
}

# Overall workflow status for Mission Control counters
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_READY = "ready"
STATUS_PROBLEM = "problem"
STATUS_ENDED = "ended"
WORKFLOW_STATUSES: tuple[str, ...] = (
    STATUS_PENDING,
    STATUS_IN_PROGRESS,
    STATUS_READY,
    STATUS_PROBLEM,
    STATUS_ENDED,
)

STATUS_LABELS: dict[str, str] = {
    STATUS_PENDING: "Pending",
    STATUS_IN_PROGRESS: "In Progress",
    STATUS_READY: "Ready",
    STATUS_PROBLEM: "Problems",
    STATUS_ENDED: "Ended",
}

ENDED_ERROR = "This workflow was ended. Resume it to continue."

# Verification methods — never confuse operator confirm with checksum
VERIFY_PENDING = "pending"
VERIFY_OPERATOR = "operator_confirmed"
VERIFY_CHECKSUM = "checksum_verified"
VERIFY_FAILED = "failed"
VERIFY_SUPERVISOR = "supervisor_override"
VERIFICATION_METHODS: tuple[str, ...] = (
    VERIFY_PENDING,
    VERIFY_OPERATOR,
    VERIFY_CHECKSUM,
    VERIFY_FAILED,
    VERIFY_SUPERVISOR,
)

PROBLEM_CATEGORIES: tuple[str, ...] = (
    "drive_not_connected",
    "wrong_shooting_day",
    "missing_files",
    "backup_failed",
    "insufficient_storage",
    "transcoding_failed",
    "proxy_playback_problem",
    "other",
)

PROBLEM_CATEGORY_LABELS: dict[str, str] = {
    "drive_not_connected": "Drive not connected",
    "wrong_shooting_day": "Wrong shooting day",
    "missing_files": "Missing files",
    "backup_failed": "Backup failed",
    "insufficient_storage": "Insufficient storage",
    "transcoding_failed": "Transcoding failed",
    "proxy_playback_problem": "Proxy playback problem",
    "other": "Other",
}

# Checklist keys per stage (operator-confirmed unless noted)
RECEIVE_CHECKS: tuple[str, ...] = (
    "correct_project",
    "correct_shooting_day",
    "shuttle_identified",
    "expected_material_present",
)

BACKUP_CHECKS: tuple[str, ...] = (
    "copy_finished",
    "camera_folders_copied",
    "audio_folders_copied",
    "structure_matches",
    "no_missing_or_errors",
    "backup_verification_done",
)

TRANSCODE_PRE_CHECKS: tuple[str, ...] = (
    "backup_verified",
    "correct_shooting_day",
    "source_folder_identified",
    "destination_confirmed",
    "preset_selected",
    "enough_space",
)

TRANSCODE_POST_CHECKS: tuple[str, ...] = (
    "transcode_finished",
    "no_failed_files",
    "all_proxies_generated",
    "proxies_playable",
    "audio_mapped",
    "timecode_framerate_ok",
    "naming_relink_ok",
    "saved_to_inhouse",
)

COMPLETE_CHECKS: tuple[str, ...] = (
    "original_backed_up",
    "backup_verification_passed",
    "proxies_generated",
    "proxy_verification_passed",
    "project_day_confirmed",
    "no_critical_errors",
)

CHECK_LABELS: dict[str, str] = {
    "correct_project": "Correct project selected",
    "correct_shooting_day": "Correct shooting day selected",
    "shuttle_identified": "Transfer / Shuttle volume identified",
    "expected_material_present": "Expected camera/audio material is present",
    "copy_finished": "Copy operation finished successfully",
    "camera_folders_copied": "All expected camera folders copied",
    "audio_folders_copied": "All expected audio folders copied",
    "structure_matches": "Folder structure matches the source",
    "no_missing_or_errors": "No missing files or reported copy errors",
    "backup_verification_done": "Backup verification completed",
    "backup_verified": "Backup is verified",
    "source_folder_identified": "Correct source folder identified",
    "destination_confirmed": "In-house Storage destination confirmed",
    "preset_selected": "Correct proxy preset selected",
    "enough_space": "Enough destination storage space available",
    "transcode_finished": "Transcoding operation finished",
    "no_failed_files": "No failed media files remain unresolved",
    "all_proxies_generated": "All expected proxies were generated",
    "proxies_playable": "Proxy files can be opened and played",
    "audio_mapped": "Audio is present and correctly mapped",
    "timecode_framerate_ok": "Timecode and frame rate requirements checked",
    "naming_relink_ok": "Proxy naming and relinking requirements checked",
    "saved_to_inhouse": "Proxy files are saved to In-house Storage",
    "original_backed_up": "Original material safely backed up",
    "backup_verification_passed": "Backup verification passed",
    "proxies_generated": "Editing proxies generated",
    "proxy_verification_passed": "Proxy verification passed",
    "project_day_confirmed": "Correct project and shooting day confirmed",
    "no_critical_errors": "No unresolved critical errors",
}

DEFAULT_PROXY_PRESETS: tuple[str, ...] = (
    "Premiere Editing Proxy",
    "Avid DNxHR Proxy",
    "ProRes Proxy",
    "Custom Preset",
)

ASSISTANT_COPY: dict[str, str] = {
    STAGE_RECEIVE: "Connect the Transfer / Shuttle drive and select today's shooting day.",
    STAGE_BACKUP: "Copy the material to Projects Backup. Do not move or delete files.",
    STAGE_TRANSCODE: "Generate editing proxies and save them to In-house Storage.",
    STAGE_COMPLETE: "Check the backup and proxies, then mark the day ready.",
}

TERM_HELP: dict[str, str] = {
    "backup": "A safe copy of the original camera and audio material.",
    "proxy": "A smaller editing copy created from the original footage.",
    "transcoding": "Converting media into the required editing format.",
    "verification": "Checking that the operation completed correctly.",
}

NOTIFY_EVENT_KEY = "machine_room_media_workflow_step"

# Workflow history event → (step label for the notification, severity).
NOTIFY_STEPS: dict[str, tuple[str, str]] = {
    "workflow_created": ("Workflow started", "info"),
    "material_received": ("Material received", "info"),
    "backup_started": ("Backup started", "info"),
    "backup_copy_finished": ("Backup copy finished", "info"),
    "backup_verified": ("Backup verified", "info"),
    "backup_verify_failed": ("Backup verification failed", "error"),
    "transcode_started": ("Transcoding started", "info"),
    "transcode_finished": ("Transcoding finished", "info"),
    "proxies_verified": ("Proxies verified", "info"),
    "ready_for_editing": ("Ready for editing", "info"),
    "problem_reported": ("Problem reported", "warning"),
    "problem_resolved": ("Problem resolved", "info"),
    "workflow_ended": ("Workflow ended", "warning"),
    "workflow_resumed": ("Workflow resumed", "info"),
    "workflow_reopened": ("Workflow reopened", "warning"),
}

notif_events.register_notification_event(
    NOTIFY_EVENT_KEY,
    {
        "label": "Machine Room Media Workflow Step",
        "category": "system",
        "description": (
            "Sent to the project team at each Daily Media Processing step: received, backup, "
            "transcoding, ready for editing, problems, and end/resume."
        ),
        "source": "Machine Room",
        "source_file": "machine_room_media_workflow_routes.py",
        "source_function": "_notify_step",
        "source_feature": "Daily Media Processing",
        "default_title": "{{ notification_title }}",
        "default_body": "{{ notification_body }}",
        "default_cta_label": "",
        "default_cta_url": "",
        "default_recipients": {"preset": "project_team"},
        "variables": list(notif_events.COMMON_VARIABLES)
        + ["workflow_id", "workflow_step", "shooting_days"],
        "is_active": True,
    },
)

# Map existing StorageVolume.storage_role → workflow roles
ROLE_SHUTTLE = "transfer"
ROLE_PROJECTS_BACKUP = "project_backup"
ROLE_INHOUSE = "working_storage"

_wf_models: dict[str, Any] = {}


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if x is not None]


def _dump_json_list(items: list[str] | None) -> str:
    return json.dumps(list(items or []), ensure_ascii=False)


def register_machine_room_media_workflow_models(db, now_local) -> Any:
    """Register SQLAlchemy models once; return namespace."""
    if _wf_models:
        return SimpleNamespace(**_wf_models)

    class MachineRoomMediaWorkflow(db.Model):
        __tablename__ = "mr_media_workflow"
        __table_args__ = (
            db.UniqueConstraint(
                "project_id",
                "shooting_day_id",
                name="uq_mr_media_workflow_project_day",
            ),
        )

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        shooting_day_id = db.Column(
            db.Integer, db.ForeignKey("shooting_days_flat.id"), nullable=False, index=True
        )
        assigned_operator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

        status = db.Column(db.String(32), nullable=False, default=STATUS_PENDING, index=True)
        current_stage = db.Column(db.String(32), nullable=False, default=STAGE_RECEIVE, index=True)

        shuttle_connected_confirmed = db.Column(db.Boolean, nullable=False, default=False)
        shuttle_volume_id = db.Column(
            db.Integer, db.ForeignKey("mr_storage_volume.id"), nullable=True, index=True
        )
        shuttle_volume_name = db.Column(db.String(160), nullable=False, default="")
        receive_notes = db.Column(db.Text, nullable=False, default="")
        receive_checks_json = db.Column(db.Text, nullable=False, default="[]")
        received_at = db.Column(db.DateTime, nullable=True)
        received_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

        backup_destination_id = db.Column(
            db.Integer, db.ForeignKey("mr_storage_volume.id"), nullable=True, index=True
        )
        backup_destination_name = db.Column(db.String(160), nullable=False, default="")
        backup_destination_path = db.Column(db.String(512), nullable=False, default="")
        backup_estimated_minutes = db.Column(db.Integer, nullable=True)
        backup_started_at = db.Column(db.DateTime, nullable=True)
        backup_finished_at = db.Column(db.DateTime, nullable=True)
        backup_verified_at = db.Column(db.DateTime, nullable=True)
        backup_verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        backup_verification_method = db.Column(
            db.String(32), nullable=False, default=VERIFY_PENDING
        )
        backup_verification_evidence = db.Column(db.Text, nullable=False, default="")
        backup_checks_json = db.Column(db.Text, nullable=False, default="[]")
        backup_copy_task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True)

        proxy_source_path = db.Column(db.String(512), nullable=False, default="")
        proxy_destination_id = db.Column(
            db.Integer, db.ForeignKey("mr_storage_volume.id"), nullable=True, index=True
        )
        proxy_destination_name = db.Column(db.String(160), nullable=False, default="")
        proxy_destination_path = db.Column(db.String(512), nullable=False, default="")
        proxy_preset = db.Column(db.String(120), nullable=False, default="")
        transcode_pre_checks_json = db.Column(db.Text, nullable=False, default="[]")
        transcode_post_checks_json = db.Column(db.Text, nullable=False, default="[]")
        transcode_started_at = db.Column(db.DateTime, nullable=True)
        transcode_finished_at = db.Column(db.DateTime, nullable=True)
        transcode_verified_at = db.Column(db.DateTime, nullable=True)
        transcode_verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        transcode_verification_method = db.Column(
            db.String(32), nullable=False, default=VERIFY_PENDING
        )
        transcode_job_id = db.Column(db.Integer, nullable=True)
        convert_task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True)

        complete_checks_json = db.Column(db.Text, nullable=False, default="[]")
        completed_at = db.Column(db.DateTime, nullable=True)
        completed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

        blocked_by_issue = db.Column(db.Boolean, nullable=False, default=False)
        ended_at = db.Column(db.DateTime, nullable=True)
        ended_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        end_reason = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)
        updated_at = db.Column(db.DateTime, nullable=False, default=now_local, onupdate=now_local)

        project = db.relationship("Project")
        shooting_day = db.relationship("ShootingDay")
        assigned_operator = db.relationship("User", foreign_keys=[assigned_operator_id])
        ended_by = db.relationship("User", foreign_keys=[ended_by_id])
        completed_by = db.relationship("User", foreign_keys=[completed_by_id])
        day_links = db.relationship(
            "MachineRoomMediaWorkflowDay",
            back_populates="workflow",
            cascade="all, delete-orphan",
            lazy=True,
        )

        @property
        def days(self) -> list:
            """All shooting days in this workflow, oldest first."""
            found = [link.shooting_day for link in (self.day_links or []) if link.shooting_day]
            if not found and self.shooting_day is not None:
                found = [self.shooting_day]
            return sorted(
                found,
                key=lambda d: (d.shooting_date, d.unit_number or 0, d.id),
            )

        @property
        def day_ids(self) -> list[int]:
            return [d.id for d in self.days]
        events = db.relationship(
            "MachineRoomMediaWorkflowEvent",
            back_populates="workflow",
            cascade="all, delete-orphan",
            lazy=True,
            order_by="MachineRoomMediaWorkflowEvent.id",
        )
        issues = db.relationship(
            "MachineRoomMediaWorkflowIssue",
            back_populates="workflow",
            cascade="all, delete-orphan",
            lazy=True,
            order_by="MachineRoomMediaWorkflowIssue.id.desc()",
        )
        overrides = db.relationship(
            "MachineRoomMediaWorkflowOverride",
            back_populates="workflow",
            cascade="all, delete-orphan",
            lazy=True,
            order_by="MachineRoomMediaWorkflowOverride.id.desc()",
        )

        @property
        def receive_checks(self) -> list[str]:
            return _parse_json_list(self.receive_checks_json)

        @receive_checks.setter
        def receive_checks(self, value: list[str]) -> None:
            self.receive_checks_json = _dump_json_list(value)

        @property
        def backup_checks(self) -> list[str]:
            return _parse_json_list(self.backup_checks_json)

        @backup_checks.setter
        def backup_checks(self, value: list[str]) -> None:
            self.backup_checks_json = _dump_json_list(value)

        @property
        def transcode_pre_checks(self) -> list[str]:
            return _parse_json_list(self.transcode_pre_checks_json)

        @transcode_pre_checks.setter
        def transcode_pre_checks(self, value: list[str]) -> None:
            self.transcode_pre_checks_json = _dump_json_list(value)

        @property
        def transcode_post_checks(self) -> list[str]:
            return _parse_json_list(self.transcode_post_checks_json)

        @transcode_post_checks.setter
        def transcode_post_checks(self, value: list[str]) -> None:
            self.transcode_post_checks_json = _dump_json_list(value)

        @property
        def complete_checks(self) -> list[str]:
            return _parse_json_list(self.complete_checks_json)

        @complete_checks.setter
        def complete_checks(self, value: list[str]) -> None:
            self.complete_checks_json = _dump_json_list(value)

        def stage_state(self, stage: str) -> str:
            """Return completed | current | locked | problem | ended | skipped for UI stepper."""
            if self.status == STATUS_PROBLEM and self.current_stage == stage:
                return "problem"
            if self.status == STATUS_READY:
                return "completed"
            try:
                idx = WORKFLOW_STAGES.index(stage)
                cur = WORKFLOW_STAGES.index(self.current_stage)
            except ValueError:
                return "locked"
            if self.status == STATUS_ENDED:
                if idx < cur:
                    return "completed"
                return "ended" if idx == cur else "skipped"
            if idx < cur:
                return "completed"
            if idx == cur:
                return "current"
            return "locked"

        def media_prep_label(self) -> str:
            if self.status == STATUS_ENDED:
                return f"ENDED AT {STAGE_LABELS.get(self.current_stage, self.current_stage).upper()}"
            if self.status == STATUS_PROBLEM:
                return "PROBLEM"
            if self.status == STATUS_READY:
                return "READY FOR EDITING"
            if self.current_stage == STAGE_RECEIVE:
                if self.received_at:
                    return "RECEIVED"
                return "NOT RECEIVED"
            if self.current_stage == STAGE_BACKUP:
                if self.backup_verified_at:
                    return "BACKUP VERIFIED"
                if self.backup_started_at:
                    return "BACKUP IN PROGRESS"
                return "RECEIVED"
            if self.current_stage == STAGE_TRANSCODE:
                if self.transcode_verified_at:
                    return "PROXIES VERIFIED"
                if self.transcode_started_at:
                    return "TRANSCODING"
                return "BACKUP VERIFIED"
            if self.current_stage == STAGE_COMPLETE:
                return "FINAL CHECK"
            return STATUS_LABELS.get(self.status, self.status.upper())

    class MachineRoomMediaWorkflowDay(db.Model):
        """A shooting day processed by a workflow; each day belongs to at most one workflow."""

        __tablename__ = "mr_media_workflow_day"
        __table_args__ = (
            db.UniqueConstraint("shooting_day_id", name="uq_mr_media_workflow_day_shooting_day"),
        )

        id = db.Column(db.Integer, primary_key=True)
        workflow_id = db.Column(
            db.Integer, db.ForeignKey("mr_media_workflow.id"), nullable=False, index=True
        )
        shooting_day_id = db.Column(
            db.Integer, db.ForeignKey("shooting_days_flat.id"), nullable=False, index=True
        )
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)

        workflow = db.relationship("MachineRoomMediaWorkflow", back_populates="day_links")
        shooting_day = db.relationship("ShootingDay")

    class MachineRoomMediaWorkflowEvent(db.Model):
        __tablename__ = "mr_media_workflow_event"

        id = db.Column(db.Integer, primary_key=True)
        workflow_id = db.Column(
            db.Integer, db.ForeignKey("mr_media_workflow.id"), nullable=False, index=True
        )
        event_type = db.Column(db.String(64), nullable=False, default="")
        stage = db.Column(db.String(32), nullable=False, default="")
        message = db.Column(db.String(512), nullable=False, default="")
        actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        verification_kind = db.Column(db.String(32), nullable=False, default="")  # auto|operator|supervisor|""
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)

        workflow = db.relationship("MachineRoomMediaWorkflow", back_populates="events")
        actor = db.relationship("User", foreign_keys=[actor_user_id])

    class MachineRoomMediaWorkflowIssue(db.Model):
        __tablename__ = "mr_media_workflow_issue"

        id = db.Column(db.Integer, primary_key=True)
        workflow_id = db.Column(
            db.Integer, db.ForeignKey("mr_media_workflow.id"), nullable=False, index=True
        )
        category = db.Column(db.String(64), nullable=False, default="other")
        description = db.Column(db.Text, nullable=False, default="")
        is_critical = db.Column(db.Boolean, nullable=False, default=True)
        status = db.Column(db.String(24), nullable=False, default="open")  # open|resolved
        reported_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        resolved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        resolved_at = db.Column(db.DateTime, nullable=True)
        resolution_note = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)

        workflow = db.relationship("MachineRoomMediaWorkflow", back_populates="issues")
        reported_by = db.relationship("User", foreign_keys=[reported_by_id])

    class MachineRoomMediaWorkflowOverride(db.Model):
        __tablename__ = "mr_media_workflow_override"

        id = db.Column(db.Integer, primary_key=True)
        workflow_id = db.Column(
            db.Integer, db.ForeignKey("mr_media_workflow.id"), nullable=False, index=True
        )
        action = db.Column(db.String(64), nullable=False, default="")
        reason = db.Column(db.Text, nullable=False, default="")
        supervisor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)

        workflow = db.relationship("MachineRoomMediaWorkflow", back_populates="overrides")
        supervisor = db.relationship("User", foreign_keys=[supervisor_user_id])

    _wf_models["MachineRoomMediaWorkflow"] = MachineRoomMediaWorkflow
    _wf_models["MachineRoomMediaWorkflowDay"] = MachineRoomMediaWorkflowDay
    _wf_models["MachineRoomMediaWorkflowEvent"] = MachineRoomMediaWorkflowEvent
    _wf_models["MachineRoomMediaWorkflowIssue"] = MachineRoomMediaWorkflowIssue
    _wf_models["MachineRoomMediaWorkflowOverride"] = MachineRoomMediaWorkflowOverride
    return SimpleNamespace(**_wf_models)


def ensure_machine_room_media_workflow_tables(db, now_local) -> Any:
    models = register_machine_room_media_workflow_models(db, now_local)
    for name in (
        "MachineRoomMediaWorkflow",
        "MachineRoomMediaWorkflowDay",
        "MachineRoomMediaWorkflowEvent",
        "MachineRoomMediaWorkflowIssue",
        "MachineRoomMediaWorkflowOverride",
    ):
        getattr(models, name).__table__.create(bind=db.engine, checkfirst=True)
    _ensure_workflow_columns(db)
    _backfill_workflow_days(db)
    return models


def _ensure_workflow_columns(db) -> None:
    """Additive columns added after the workflow table first shipped."""
    from sqlalchemy import inspect, text

    insp = inspect(db.engine)
    if "mr_media_workflow" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("mr_media_workflow")}
    additions = (
        ("ended_at", "DATETIME"),
        ("ended_by_id", "INTEGER"),
        ("end_reason", "TEXT NOT NULL DEFAULT ''"),
        ("backup_estimated_minutes", "INTEGER"),
    )
    for col_name, col_def in additions:
        if col_name in cols:
            continue
        with db.engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE mr_media_workflow ADD COLUMN {col_name} {col_def}"))


def _backfill_workflow_days(db) -> None:
    """Give every pre-multi-day workflow a day link for its original shooting day."""
    from sqlalchemy import text

    with db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO mr_media_workflow_day (workflow_id, shooting_day_id, created_at) "
                "SELECT w.id, w.shooting_day_id, w.created_at FROM mr_media_workflow w "
                "WHERE NOT EXISTS (SELECT 1 FROM mr_media_workflow_day d "
                "WHERE d.shooting_day_id = w.shooting_day_id)"
            )
        )


def add_workflow_event(
    db,
    models,
    workflow,
    *,
    event_type: str,
    message: str,
    actor_user_id: int | None,
    stage: str | None = None,
    verification_kind: str = "",
    now_fn=None,
) -> Any:
    Event = models.MachineRoomMediaWorkflowEvent
    row = Event(
        workflow_id=workflow.id,
        event_type=event_type,
        stage=stage or workflow.current_stage or "",
        message=(message or "")[:512],
        actor_user_id=actor_user_id,
        verification_kind=verification_kind or "",
        created_at=now_fn() if now_fn else datetime.utcnow(),
    )
    db.session.add(row)
    workflow.updated_at = now_fn() if now_fn else datetime.utcnow()
    return row


def find_workflow_for_day(models, project_id: int, shooting_day_id: int):
    """Workflow that already includes this shooting day (any of its days), if any."""
    WF = models.MachineRoomMediaWorkflow
    Day = models.MachineRoomMediaWorkflowDay
    link = Day.query.filter_by(shooting_day_id=shooting_day_id).first()
    if link is not None:
        return link.workflow
    return (
        WF.query.filter_by(project_id=project_id, shooting_day_id=shooting_day_id)
        .order_by(WF.id.desc())
        .first()
    )


def workflow_ids_by_day(models, day_ids: list[int]) -> dict[int, int]:
    """Map shooting_day_id -> workflow_id for days that already belong to a workflow."""
    if not day_ids:
        return {}
    Day = models.MachineRoomMediaWorkflowDay
    rows = Day.query.filter(Day.shooting_day_id.in_(list(day_ids))).all()
    return {r.shooting_day_id: r.workflow_id for r in rows}


class WorkflowDayConflict(Exception):
    """Some selected days already belong to a different workflow."""

    def __init__(self, conflicts: dict[int, int]):
        super().__init__("Shooting days already belong to another workflow.")
        self.conflicts = conflicts


def _primary_day_id(days: list) -> int:
    return sorted(days, key=lambda d: (d.shooting_date, d.unit_number or 0, d.id))[0].id


def set_workflow_days(db, models, workflow, days: list) -> None:
    """Replace the workflow's day set. Caller validates project and conflicts."""
    Day = models.MachineRoomMediaWorkflowDay
    wanted = {d.id for d in days}
    for link in list(workflow.day_links or []):
        if link.shooting_day_id not in wanted:
            db.session.delete(link)
    have = {link.shooting_day_id for link in (workflow.day_links or [])}
    for d in days:
        if d.id not in have:
            db.session.add(Day(workflow_id=workflow.id, shooting_day_id=d.id))
    workflow.shooting_day_id = _primary_day_id(days)
    db.session.flush()
    db.session.expire(workflow, ["day_links"])


def get_or_create_workflow(
    db,
    models,
    *,
    project_id: int,
    shooting_days: list,
    operator_user_id: int | None,
    now_fn,
) -> tuple[Any, bool]:
    """Return (workflow, created). Never puts a shooting day in two workflows.

    If every selected day is already in the same workflow, that workflow reopens.
    If only some are, WorkflowDayConflict is raised so nothing is split silently.
    """
    if not shooting_days:
        raise ValueError("At least one shooting day is required.")

    owners = workflow_ids_by_day(models, [d.id for d in shooting_days])
    if owners:
        owner_ids = set(owners.values())
        if len(owner_ids) == 1 and len(owners) == len(shooting_days):
            return db.session.get(models.MachineRoomMediaWorkflow, owner_ids.pop()), False
        raise WorkflowDayConflict(owners)

    WF = models.MachineRoomMediaWorkflow
    row = WF(
        project_id=project_id,
        shooting_day_id=_primary_day_id(shooting_days),
        assigned_operator_id=operator_user_id,
        status=STATUS_PENDING,
        current_stage=STAGE_RECEIVE,
        created_at=now_fn(),
        updated_at=now_fn(),
    )
    db.session.add(row)
    db.session.flush()
    set_workflow_days(db, models, row, shooting_days)
    add_workflow_event(
        db,
        models,
        row,
        event_type="workflow_created",
        message=f"Workflow created for {format_days_label(row.days)}",
        actor_user_id=operator_user_id,
        stage=STAGE_RECEIVE,
        now_fn=now_fn,
    )
    return row, True


def volumes_for_role(StorageVolume, role: str) -> list:
    return (
        StorageVolume.query.filter_by(storage_role=role)
        .order_by(StorageVolume.display_name.asc(), StorageVolume.name.asc())
        .all()
    )


def volume_label(vol) -> str:
    if vol is None:
        return ""
    return (getattr(vol, "display_name", None) or getattr(vol, "name", "") or "").strip()


def invalidate_downstream_after_receive_change(workflow, now_fn) -> None:
    """Reopening receive after later work invalidates dependent confirmations."""
    workflow.backup_verified_at = None
    workflow.backup_verified_by_id = None
    workflow.backup_verification_method = VERIFY_PENDING
    workflow.backup_verification_evidence = ""
    workflow.backup_checks = []
    workflow.backup_finished_at = None
    # Keep started_at history but require re-verify
    workflow.transcode_verified_at = None
    workflow.transcode_verified_by_id = None
    workflow.transcode_verification_method = VERIFY_PENDING
    workflow.transcode_post_checks = []
    workflow.transcode_pre_checks = []
    workflow.transcode_finished_at = None
    workflow.complete_checks = []
    workflow.completed_at = None
    workflow.completed_by_id = None
    if workflow.status == STATUS_READY:
        workflow.status = STATUS_IN_PROGRESS
    workflow.current_stage = STAGE_RECEIVE
    workflow.updated_at = now_fn()


def invalidate_downstream_after_backup_change(workflow, now_fn) -> None:
    workflow.transcode_verified_at = None
    workflow.transcode_verified_by_id = None
    workflow.transcode_verification_method = VERIFY_PENDING
    workflow.transcode_post_checks = []
    workflow.transcode_pre_checks = []
    workflow.transcode_finished_at = None
    workflow.complete_checks = []
    workflow.completed_at = None
    workflow.completed_by_id = None
    if workflow.status == STATUS_READY:
        workflow.status = STATUS_IN_PROGRESS
    if WORKFLOW_STAGES.index(workflow.current_stage) > WORKFLOW_STAGES.index(STAGE_BACKUP):
        workflow.current_stage = STAGE_BACKUP
    workflow.updated_at = now_fn()


def checks_summary(selected: list[str], keys: tuple[str, ...]) -> str:
    """Report line like "4 of 6 checks ticked: Copy finished, …" for optional checklists."""
    ticked = [CHECK_LABELS.get(k, k) for k in keys if k in set(selected or [])]
    head = f"{len(ticked)} of {len(keys)} checks ticked"
    return f"{head}: {', '.join(ticked)}" if ticked else head


def checks_complete(selected: list[str], required: tuple[str, ...]) -> bool:
    sel = set(selected or [])
    return all(k in sel for k in required)


def can_advance_from_receive(workflow) -> tuple[bool, str]:
    if workflow.status == STATUS_ENDED:
        return False, ENDED_ERROR
    if workflow.blocked_by_issue:
        return False, "A critical problem is open. Resolve it before continuing."
    if not workflow.project_id or not workflow.shooting_day_id:
        return False, "Select the project and shooting day."
    if not workflow.shuttle_volume_id:
        return False, "Select the Transfer / Shuttle volume."
    return True, ""


def can_start_backup(workflow) -> tuple[bool, str]:
    if workflow.status == STATUS_ENDED:
        return False, ENDED_ERROR
    if workflow.blocked_by_issue:
        return False, "A critical problem is open. Resolve it before continuing."
    if workflow.current_stage not in (STAGE_BACKUP, STAGE_RECEIVE):
        # Allow if receive done
        pass
    if not workflow.received_at:
        return False, "Complete Receive before starting backup."
    if not workflow.shuttle_volume_id:
        return False, "Source Transfer / Shuttle volume is required."
    if not workflow.backup_destination_id:
        return False, "Select a Projects Backup destination."
    if workflow.shuttle_volume_id == workflow.backup_destination_id:
        return False, "Source and destination must be different volumes."
    if not workflow.backup_estimated_minutes:
        return False, "Enter the estimated backup time (HH : MM)."
    return True, ""


def format_hhmm(minutes: int | None) -> str:
    """Minutes as HH:MM, e.g. 90 -> "01:30"."""
    total = max(0, int(minutes or 0))
    return f"{total // 60:02d}:{total % 60:02d}"


MAX_ESTIMATE_MINUTES = 48 * 60 + 59


def parse_estimate_minutes(raw) -> int | None:
    """Accept minutes as int/str; return None when missing, 0, or out of range."""
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    if val <= 0 or val > MAX_ESTIMATE_MINUTES:
        return None
    return val


def can_verify_backup(workflow) -> tuple[bool, str]:
    if workflow.status == STATUS_ENDED:
        return False, ENDED_ERROR
    if workflow.blocked_by_issue:
        return False, "A critical problem is open. Resolve it before continuing."
    if not workflow.backup_started_at:
        return False, "Start the backup first."
    if not workflow.backup_finished_at:
        return False, "Mark the copy as finished first."
    if workflow.backup_verification_method == VERIFY_FAILED:
        return False, "Backup verification failed. Resolve the problem before continuing."
    return True, ""


def can_start_transcode(workflow) -> tuple[bool, str]:
    if workflow.status == STATUS_ENDED:
        return False, ENDED_ERROR
    if workflow.blocked_by_issue:
        return False, "A critical problem is open. Resolve it before continuing."
    if not workflow.backup_verified_at:
        return False, "Backup must be verified before transcoding."
    if workflow.backup_verification_method in (VERIFY_PENDING, VERIFY_FAILED):
        return False, "Backup verification is not complete."
    if not workflow.proxy_destination_id:
        return False, "Select an In-house Storage destination."
    return True, ""


def can_verify_transcode(workflow) -> tuple[bool, str]:
    if workflow.status == STATUS_ENDED:
        return False, ENDED_ERROR
    if workflow.blocked_by_issue:
        return False, "A critical problem is open. Resolve it before continuing."
    if not workflow.transcode_started_at:
        return False, "Start transcoding first."
    if not workflow.transcode_finished_at:
        return False, "Mark transcoding as finished first."
    if not checks_complete(workflow.transcode_post_checks, TRANSCODE_POST_CHECKS):
        return False, "Complete the proxy verification checklist."
    return True, ""


def can_mark_ready(workflow) -> tuple[bool, str]:
    if workflow.status == STATUS_ENDED:
        return False, ENDED_ERROR
    if workflow.blocked_by_issue:
        return False, "A critical problem is open. Resolve it before continuing."
    if not workflow.backup_verified_at:
        return False, "Backup verification is required."
    if not workflow.transcode_verified_at:
        return False, "Proxy verification is required."
    if not checks_complete(workflow.complete_checks, COMPLETE_CHECKS):
        return False, "Complete the final checklist."
    return True, ""


def overview_counts(models) -> dict[str, int]:
    from sqlalchemy import func

    WF = models.MachineRoomMediaWorkflow
    counts = {
        STATUS_PENDING: 0,
        STATUS_IN_PROGRESS: 0,
        STATUS_READY: 0,
        STATUS_PROBLEM: 0,
    }
    rows = (
        WF.query.with_entities(WF.status, func.count(WF.id))
        .group_by(WF.status)
        .all()
    )
    for status, n in rows:
        if status in counts:
            counts[status] = int(n)
    return counts


def format_shooting_day_label(day) -> str:
    if day is None:
        return "—"
    parts = []
    if getattr(day, "unit_number", None):
        parts.append(f"Unit {day.unit_number}")
    name = (getattr(day, "day_name", None) or "").strip()
    if name:
        parts.append(name if name.lower().startswith("day") else f"Day {name}")
    else:
        parts.append(f"Day #{day.id}")
    dt = getattr(day, "shooting_date", None)
    if dt:
        try:
            parts.append(dt.strftime("%d %b %Y").upper())
        except Exception:
            parts.append(str(dt))
    return " · ".join(parts)


def _short_day_name(day) -> str:
    name = (getattr(day, "day_name", None) or "").strip()
    if not name:
        return f"Day #{day.id}"
    return name if name.lower().startswith("day") else f"Day {name}"


def format_days_label(days: list) -> str:
    """One day keeps the full label; several days read e.g. "Unit 1 · Day 1 + Day 2 · 16 – 17 OCT 2026"."""
    days = [d for d in (days or []) if d is not None]
    if not days:
        return "—"
    if len(days) == 1:
        return format_shooting_day_label(days[0])
    units = {int(d.unit_number or 1) for d in days}
    if len(units) == 1:
        names = " + ".join(_short_day_name(d) for d in days)
        head = f"Unit {units.pop()} · {names}"
    else:
        head = " + ".join(f"U{int(d.unit_number or 1)} {_short_day_name(d)}" for d in days)
    first, last = days[0].shooting_date, days[-1].shooting_date
    if not first or not last:
        return head
    if first == last:
        span = first.strftime("%d %b %Y").upper()
    elif first.year == last.year:
        span = f"{first.strftime('%d %b').upper()} – {last.strftime('%d %b %Y').upper()}"
    else:
        span = f"{first.strftime('%d %b %Y').upper()} – {last.strftime('%d %b %Y').upper()}"
    return f"{head} · {span}"


def serialize_workflow_card(workflow, *, operator_name: str = "") -> dict[str, Any]:
    day = workflow.shooting_day
    days = workflow.days
    project = workflow.project
    stages = []
    for st in WORKFLOW_STAGES:
        stages.append(
            {
                "key": st,
                "label": STAGE_LABELS[st],
                "state": workflow.stage_state(st),
            }
        )
    return {
        "id": workflow.id,
        "project_id": workflow.project_id,
        "project_name": (project.name if project else "") or f"Project #{workflow.project_id}",
        "shooting_day_id": workflow.shooting_day_id,
        "shooting_day_ids": [d.id for d in days],
        "days": [{"id": d.id, "label": format_shooting_day_label(d)} for d in days],
        "day_count": len(days),
        "shooting_day_label": format_days_label(days),
        "day_name": (day.day_name if day else "") or "",
        "shooting_date": day.shooting_date.isoformat() if day and day.shooting_date else "",
        "shooting_date_display": (
            day.shooting_date.strftime("%d %b %Y").upper()
            if day and day.shooting_date
            else "—"
        ),
        "operator": operator_name
        or (
            workflow.assigned_operator.name
            if workflow.assigned_operator
            else "Unassigned"
        ),
        "status": workflow.status,
        "status_label": STATUS_LABELS.get(workflow.status, workflow.status),
        "current_stage": workflow.current_stage,
        "current_stage_label": STAGE_LABELS.get(workflow.current_stage, workflow.current_stage),
        "media_prep": workflow.media_prep_label(),
        "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else "",
        "completed_at_display": (
            workflow.completed_at.strftime("%d %b %Y · %H:%M") if workflow.completed_at else "—"
        ),
        "completed_by": workflow.completed_by.name if workflow.completed_by else "—",
        "backup_destination_name": workflow.backup_destination_name or "—",
        "proxy_destination_name": workflow.proxy_destination_name or "—",
        "proxy_preset": workflow.proxy_preset or "",
        "stages": stages,
        "steps_done": sum(1 for s in stages if s["state"] == "completed"),
        "blocked": bool(workflow.blocked_by_issue),
        "action_hint": (
            f"Ended at {STAGE_LABELS.get(workflow.current_stage, workflow.current_stage)}"
            + (f": {workflow.end_reason}" if workflow.end_reason else ".")
            if workflow.status == STATUS_ENDED
            else ASSISTANT_COPY.get(workflow.current_stage, "")
        ),
    }
