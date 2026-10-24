"""Routes and page bundle for Machine Room guided media workflow."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Callable

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import event as sa_event
from sqlalchemy import text

import machine_room_dashboard_support as mr_support
import machine_room_media_workflow_support as wf
import machine_room_storage_scan as scan_mod

# db.session is process-wide; app factories re-register, so keep one set of listeners.
_SESSION_LISTENERS: list[tuple[str, Callable]] = []


def register_machine_room_media_workflow_routes(app: Flask, ctx: dict) -> None:
    db = ctx["db"]
    now_local: Callable = ctx["now_local"]
    Project = ctx["Project"]
    ShootingDay = ctx["ShootingDay"]
    User = ctx["User"]
    StorageVolume = ctx["StorageVolume"]
    account_from_session = ctx["account_from_session"]
    account_is_machine_room_role = ctx["account_is_machine_room_role"]
    account_is_elevated = ctx["account_is_elevated"]
    account_is_producerish = ctx.get("account_is_producerish") or (
        lambda acc: bool(acc and getattr(acc, "role", "") in ("producer", "admin", "super_user"))
    )
    directory_user_id_for_account = ctx["directory_user_id_for_account"]
    send_managed_notification = ctx.get("send_managed_notification")
    log_security_event = ctx.get("log_security_event")
    Task = ctx.get("Task")
    MR_STREAM_COPY_TITLE = ctx.get("MR_STREAM_COPY_TITLE", "Copy Material")
    MR_STREAM_CONVERT_TITLE = ctx.get("MR_STREAM_CONVERT_TITLE", "Convert")
    notify_mr_stream_task_status = ctx.get("notify_mr_stream_task_status")
    emit_shooting_day_created_activity = ctx.get("emit_shooting_day_created_activity")
    notification_push_realtime_for_project = ctx.get("notification_push_realtime_for_project")
    ShootingDayCriticalNote = ctx.get("ShootingDayCriticalNote")
    emit_shooting_day_critical_created = ctx.get("emit_shooting_day_critical_created")
    socketio = ctx.get("socketio")
    account_can_access_project = ctx.get("account_can_access_project")

    StorageVolumeProjectLink = mr_support.register_machine_room_dashboard_models(
        db, now_local
    ).StorageVolumeProjectLink
    models = wf.register_machine_room_media_workflow_models(db, now_local)
    MachineRoomMediaWorkflow = models.MachineRoomMediaWorkflow
    MachineRoomMediaWorkflowIssue = models.MachineRoomMediaWorkflowIssue
    MachineRoomMediaWorkflowOverride = models.MachineRoomMediaWorkflowOverride
    MachineRoomMediaWorkflowDay = models.MachineRoomMediaWorkflowDay

    _CHANGED_KEY = "mr_wf_changed_project_ids"

    def _collect_workflow_changes(session, _flush_context) -> None:
        changed: set[int] = session.info.setdefault(_CHANGED_KEY, set())
        lookup: set[int] = set()
        for obj in list(session.new) + list(session.dirty) + list(session.deleted):
            if isinstance(obj, MachineRoomMediaWorkflow):
                if obj.project_id:
                    changed.add(int(obj.project_id))
            elif isinstance(obj, MachineRoomMediaWorkflowDay):
                loaded = obj.__dict__.get("workflow")
                if loaded is not None and loaded.project_id:
                    changed.add(int(loaded.project_id))
                elif obj.workflow_id:
                    lookup.add(int(obj.workflow_id))
        if lookup:
            rows = session.connection().execute(
                text(
                    "SELECT project_id FROM mr_media_workflow WHERE id IN ("
                    + ",".join(str(i) for i in sorted(lookup))
                    + ")"
                )
            )
            changed.update(int(r[0]) for r in rows if r[0])

    def _emit_workflow_changes(session) -> None:
        ids = session.info.pop(_CHANGED_KEY, None)
        if not ids or socketio is None:
            return
        try:
            socketio.emit("mr_workflow_changed", {"project_ids": sorted(ids)}, room="tasks_feed")
        except Exception:
            app.logger.exception("mr_workflow_changed emit failed")

    def _drop_workflow_changes(session) -> None:
        session.info.pop(_CHANGED_KEY, None)

    for name, fn in _SESSION_LISTENERS:
        if sa_event.contains(db.session, name, fn):
            sa_event.remove(db.session, name, fn)
    _SESSION_LISTENERS[:] = [
        ("after_flush", _collect_workflow_changes),
        ("after_commit", _emit_workflow_changes),
        ("after_soft_rollback", lambda s, _t: _drop_workflow_changes(s)),
    ]
    for name, fn in _SESSION_LISTENERS:
        sa_event.listen(db.session, name, fn)

    def _actor():
        return account_from_session()

    def _require_mr_or_supervisor():
        acc = _actor()
        if acc is None:
            abort(403)
        if account_is_machine_room_role(acc) or _is_supervisor(acc):
            return acc
        abort(403)

    def _is_supervisor(acc) -> bool:
        if acc is None:
            return False
        if account_is_elevated(acc):
            return True
        try:
            return bool(account_is_producerish(acc))
        except Exception:
            return False

    def _user_id(acc) -> int | None:
        return directory_user_id_for_account(acc)

    def _json_error(message: str, status: int = 400):
        return jsonify({"ok": False, "error": message}), status

    def _parse_checks(payload: dict, key: str) -> list[str]:
        raw = payload.get(key)
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(x) for x in raw if str(x).strip()]
        if isinstance(raw, str):
            return [x.strip() for x in raw.split(",") if x.strip()]
        return []

    def _volume_options():
        shuttle = wf.volumes_for_role(StorageVolume, wf.ROLE_SHUTTLE)
        backup = wf.volumes_for_role(StorageVolume, wf.ROLE_PROJECTS_BACKUP)
        inhouse = wf.volumes_for_role(StorageVolume, wf.ROLE_INHOUSE)
        return shuttle, backup, inhouse

    def _setup_warnings(shuttle, backup, inhouse) -> list[str]:
        warnings = []
        if not shuttle:
            warnings.append(
                "No Transfer / Shuttle volumes are configured. An administrator must set storage roles on Storage."
            )
        if not backup:
            warnings.append(
                "No Projects Backup volumes are configured. An administrator must set storage roles on Storage."
            )
        if not inhouse:
            warnings.append(
                "No In-house Storage volumes are configured. An administrator must set storage roles on Storage."
            )
        return warnings

    def _notify_step(w, event_type: str, message: str, event_row_id: int) -> None:
        """Tell the workflow's project team about a step (managed rule, project-team fallback).

        Each notification points at its history row so successive steps of one workflow
        don't share a notification key and overwrite each other.
        """
        step = wf.NOTIFY_STEPS.get(event_type)
        if step is None or send_managed_notification is None or not w.project_id:
            return
        label, severity = step
        project = db.session.get(Project, w.project_id)
        if project is None:
            return
        acc = account_from_session()
        days = wf.format_days_label(w.days)
        title = f"{project.name or 'Project'} · {days}: {label}"
        recipients = [
            int(uid)
            for (uid,) in db.session.execute(
                text("SELECT user_id FROM project_members WHERE project_id = :pid"),
                {"pid": int(w.project_id)},
            )
            if uid is not None
        ]
        entity_type, entity_id = "mr_media_workflow_step", int(event_row_id)
        if event_type in wf.NOTIFY_BACKUP_LIVE_STEPS and w.backup_copy_task_id:
            entity_type, entity_id = "task", int(w.backup_copy_task_id)
        elif event_type in wf.NOTIFY_CONVERT_LIVE_STEPS and w.convert_task_id:
            entity_type, entity_id = "task", int(w.convert_task_id)
        try:
            sent = send_managed_notification(
                wf.NOTIFY_EVENT_KEY,
                project=project,
                actor=acc,
                context={
                    "notification_title": title,
                    "notification_body": message,
                    "notification_severity": severity,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "rule_entity_id": int(event_row_id),
                    "workflow_id": int(w.id),
                    "workflow_step": label,
                    "shooting_days": days,
                },
                fallback_title=title,
                fallback_body=message,
                fallback_recipient_user_ids=recipients,
            )
            if sent and notification_push_realtime_for_project:
                notification_push_realtime_for_project(int(w.project_id), actor=acc)
        except Exception:
            app.logger.exception("Machine Room workflow notification failed")

    def _add_event(db_, models_, w, **kwargs):
        """Record a workflow history event and notify the project team for step events."""
        row = wf.add_workflow_event(db_, models_, w, **kwargs)
        event_type = kwargs.get("event_type", "")
        if event_type in wf.NOTIFY_STEPS:
            db_.session.flush()
            _notify_step(w, event_type, kwargs.get("message", ""), row.id)
        return row

    def build_mission_control_bundle(actor) -> dict[str, Any]:
        """Context for progress tab Mission Control + optional active workflow."""
        shuttle, backup, inhouse = _volume_options()
        counts = wf.overview_counts(models)
        workflows = (
            MachineRoomMediaWorkflow.query.order_by(
                MachineRoomMediaWorkflow.updated_at.desc(),
                MachineRoomMediaWorkflow.id.desc(),
            )
            .limit(200)
            .all()
        )
        cards = []
        for w in workflows:
            op_name = ""
            if w.assigned_operator:
                op_name = w.assigned_operator.name or ""
            cards.append(wf.serialize_workflow_card(w, operator_name=op_name))
        ready_rows = sorted(
            (c for c in cards if c["status"] == wf.STATUS_READY),
            key=lambda c: c["completed_at"],
            reverse=True,
        )
        cards = [c for c in cards if c["status"] != wf.STATUS_READY]
        cards.sort(key=lambda c: (c["status"] == wf.STATUS_ENDED, -c["steps_done"]))

        projects = Project.query.order_by(Project.name.asc()).all()
        project_choices = [{"id": p.id, "name": p.name} for p in projects]

        active_id = request.args.get("workflow_id", type=int)
        active = None
        active_detail = None
        if active_id:
            active = db.session.get(MachineRoomMediaWorkflow, active_id)
            if active:
                active_detail = _workflow_detail(active, actor, detect_mounts=True)

        day_owner = {
            link.shooting_day_id: link.workflow_id
            for link in models.MachineRoomMediaWorkflowDay.query.all()
        }
        completed_ids = {
            row.id
            for row in MachineRoomMediaWorkflow.query.filter_by(status=wf.STATUS_READY)
            .with_entities(MachineRoomMediaWorkflow.id)
            .all()
        }
        days_by_project: dict[int, list[dict]] = {}
        for p in projects:
            days = (
                ShootingDay.query.filter_by(project_id=p.id)
                .order_by(
                    ShootingDay.shooting_date.asc(),
                    ShootingDay.unit_number.asc(),
                    ShootingDay.id.asc(),
                )
                .all()
            )
            days_by_project[p.id] = [
                {
                    "id": d.id,
                    "label": wf.format_shooting_day_label(d),
                    "day_name": d.day_name or "",
                    "unit_number": int(d.unit_number or 1),
                    "date": d.shooting_date.isoformat() if d.shooting_date else "",
                    "workflow_id": day_owner.get(d.id),
                    "workflow_completed": day_owner.get(d.id) in completed_ids,
                }
                for d in days
            ]

        links_by_project: dict[int, set[int]] = {}
        for link in StorageVolumeProjectLink.query.all():
            links_by_project.setdefault(int(link.project_id), set()).add(int(link.volume_id))
        linked_any = set().union(*links_by_project.values()) if links_by_project else set()
        if active is None:
            checked_mounts = False
            for v in shuttle:
                if v.id not in linked_any:
                    continue
                try:
                    mr_support.apply_volume_status_check(v, now_local())
                    checked_mounts = True
                except Exception:
                    app.logger.exception("Mount check failed for volume %s", v.id)
            if checked_mounts:
                db.session.commit()
        shuttle_by_project = {}
        for p in projects:
            ids = links_by_project.get(int(p.id), set())
            rows = []
            for v in shuttle:
                if v.id not in ids:
                    continue
                d = _vol_dict(v)
                rows.append({
                    "id": v.id,
                    "name": d["name"],
                    "mounted": d["mounted"],
                    "free_pct": round(d["free_pct"]) if d["free_pct"] is not None and d["capacity_tb"] else None,
                })
            shuttle_by_project[p.id] = rows

        return {
            "mr_workflow_enabled": True,
            "mr_wf_shuttle_by_project": shuttle_by_project,
            "mr_wf_counts": counts,
            "mr_wf_cards": cards,
            "mr_wf_ready_rows": ready_rows,
            "mr_wf_active": active_detail,
            "mr_wf_active_id": active.id if active else None,
            "mr_wf_project_choices": project_choices,
            "mr_wf_days_by_project": days_by_project,
            "mr_wf_shuttle_volumes": [
                _vol_dict(v) for v in shuttle
            ],
            "mr_wf_backup_volumes": [_vol_dict(v) for v in backup],
            "mr_wf_inhouse_volumes": [_vol_dict(v) for v in inhouse],
            "mr_wf_setup_warnings": _setup_warnings(shuttle, backup, inhouse),
            "mr_wf_proxy_presets": list(wf.DEFAULT_PROXY_PRESETS),
            "mr_wf_problem_categories": [
                {"key": k, "label": wf.PROBLEM_CATEGORY_LABELS[k]} for k in wf.PROBLEM_CATEGORIES
            ],
            "mr_wf_check_labels": wf.CHECK_LABELS,
            "mr_wf_receive_checks": list(wf.RECEIVE_CHECKS),
            "mr_wf_backup_checks": list(wf.BACKUP_CHECKS),
            "mr_wf_transcode_pre_checks": list(wf.TRANSCODE_PRE_CHECKS),
            "mr_wf_transcode_post_checks": list(wf.TRANSCODE_POST_CHECKS),
            "mr_wf_complete_checks": list(wf.COMPLETE_CHECKS),
            "mr_wf_assistant": wf.ASSISTANT_COPY,
            "mr_wf_term_help": wf.TERM_HELP,
            "mr_wf_is_supervisor": _is_supervisor(actor),
            "mr_wf_stage_labels": wf.STAGE_LABELS,
        }

    def _vol_dict(v) -> dict:
        mounted = (getattr(v, "mounted_status", None) or "") == "mounted" or bool(
            getattr(v, "is_mounted", False)
        )
        free_pct = getattr(v, "free_percentage", None)
        if free_pct is None and getattr(v, "capacity_tb", 0):
            try:
                free_pct = (float(v.free_tb or 0) / float(v.capacity_tb)) * 100.0
            except Exception:
                free_pct = None
        return {
            "id": v.id,
            "name": wf.volume_label(v),
            "mount_path": getattr(v, "mount_path", "") or "",
            "mounted": mounted,
            "mounted_status": getattr(v, "mounted_status", "") or "",
            "capacity_tb": getattr(v, "capacity_tb", 0) or 0,
            "used_tb": getattr(v, "used_tb", 0) or 0,
            "free_tb": getattr(v, "free_tb", 0) or 0,
            "free_pct": free_pct,
            "volume_code": getattr(v, "volume_code", "") or "",
            "storage_role": getattr(v, "storage_role", "") or "",
        }

    stage_roles = {
        wf.STAGE_RECEIVE: (wf.ROLE_SHUTTLE, "shuttle_volume_id"),
        wf.STAGE_BACKUP: (wf.ROLE_PROJECTS_BACKUP, "backup_destination_id"),
        wf.STAGE_TRANSCODE: (wf.ROLE_INHOUSE, "proxy_destination_id"),
    }

    # Stages that only ever offer volumes linked to the workflow's project.
    strict_link_stages = {wf.STAGE_RECEIVE}

    def _project_volume_ids(project_id: int) -> set[int]:
        return {
            link.volume_id
            for link in StorageVolumeProjectLink.query.filter_by(project_id=project_id).all()
        }

    def _shuttle_link_error(w) -> str:
        """Why the selected Transfer / Shuttle volume can't be used for this project, or ''."""
        if not w.shuttle_volume_id or w.shuttle_volume_id in _project_volume_ids(w.project_id):
            return ""
        vol = db.session.get(StorageVolume, w.shuttle_volume_id)
        name = wf.volume_label(vol) or "That volume"
        project = w.project.name if w.project else "this project"
        return f"{name} is not linked to {project}. Pick a volume linked to the project."

    def _stage_volumes(w, detect: bool) -> dict:
        """Volumes per stage: project-linked ones for the stage's role.

        Receive shows linked volumes only; later stages fall back to every volume of
        the role when none are linked.
        """
        linked_ids = _project_volume_ids(w.project_id)
        out: dict[str, dict] = {}
        checked = False
        for stage, (role, selected_attr) in stage_roles.items():
            strict = stage in strict_link_stages
            all_role = wf.volumes_for_role(StorageVolume, role)
            linked = [v for v in all_role if v.id in linked_ids]
            vols = list(linked if strict else (linked or all_role))
            selected_id = getattr(w, selected_attr)
            if not strict and selected_id and all(v.id != selected_id for v in vols):
                sel = db.session.get(StorageVolume, selected_id)
                if sel is not None:
                    vols.append(sel)
            run_check = detect and stage == w.current_stage
            if run_check:
                for v in vols:
                    try:
                        mr_support.apply_volume_status_check(v, now_local())
                        checked = True
                    except Exception:
                        app.logger.exception("Mount check failed for volume %s", v.id)
            out[stage] = {
                "volumes": [{**_vol_dict(v), "linked": v.id in linked_ids} for v in vols],
                "linked_only": bool(linked) or strict,
                "strict": strict,
                "detected": run_check,
            }
        if checked:
            db.session.commit()
        return out

    def _workflow_detail(w, actor, *, detect_mounts: bool = False) -> dict:
        events = [
            {
                "id": e.id,
                "at": e.created_at.isoformat(timespec="minutes") if e.created_at else "",
                "at_display": e.created_at.strftime("%H:%M") if e.created_at else "",
                "date_display": e.created_at.strftime("%d %b %Y") if e.created_at else "",
                "message": e.message,
                "event_type": e.event_type,
                "stage": e.stage,
                "actor": e.actor.name if e.actor else "",
                "verification_kind": e.verification_kind or "",
            }
            for e in (w.events or [])
        ]
        open_issues = [
            {
                "id": i.id,
                "category": i.category,
                "category_label": wf.PROBLEM_CATEGORY_LABELS.get(i.category, i.category),
                "description": i.description,
                "is_critical": i.is_critical,
                "status": i.status,
            }
            for i in (w.issues or [])
            if i.status == "open"
        ]
        card = wf.serialize_workflow_card(w)
        shuttle_vol = db.session.get(StorageVolume, w.shuttle_volume_id) if w.shuttle_volume_id else None
        backup_vol = (
            db.session.get(StorageVolume, w.backup_destination_id) if w.backup_destination_id else None
        )
        proxy_vol = (
            db.session.get(StorageVolume, w.proxy_destination_id) if w.proxy_destination_id else None
        )

        ok_recv, err_recv = wf.can_advance_from_receive(w)
        if ok_recv:
            link_err = _shuttle_link_error(w)
            if link_err:
                ok_recv, err_recv = False, link_err
        ok_start_b, err_start_b = wf.can_start_backup(w, require_estimate=False)
        ok_ver_b, err_ver_b = wf.can_verify_backup(w)
        ok_start_t, err_start_t = wf.can_start_transcode(w)
        ok_ver_t, err_ver_t = wf.can_verify_transcode(w)
        ok_ready, err_ready = wf.can_mark_ready(w)

        return {
            **card,
            "shuttle_connected_confirmed": bool(w.shuttle_connected_confirmed),
            "shuttle_volume_id": w.shuttle_volume_id,
            "shuttle_volume": _vol_dict(shuttle_vol) if shuttle_vol else None,
            "receive_notes": w.receive_notes or "",
            "received_at": w.received_at.isoformat(timespec="minutes") if w.received_at else "",
            "backup_destination_id": w.backup_destination_id,
            "backup_destination": _vol_dict(backup_vol) if backup_vol else None,
            "backup_estimated_minutes": w.backup_estimated_minutes or 0,
            "backup_estimate_hhmm": (
                wf.format_hhmm(w.backup_estimated_minutes) if w.backup_estimated_minutes else ""
            ),
            "backup_expected_finish": (
                (w.backup_started_at + timedelta(minutes=w.backup_estimated_minutes)).strftime("%H:%M")
                if w.backup_started_at and w.backup_estimated_minutes
                else ""
            ),
            "backup_copy_task_id": w.backup_copy_task_id,
            "backup_paused": bool(w.backup_paused_at and not w.backup_finished_at),
            "transcode_paused": bool(w.transcode_paused_at and not w.transcode_finished_at),
            "convert_task_id": w.convert_task_id,
            "transcode_estimated_minutes": w.transcode_estimated_minutes or 0,
            "transcode_notes": w.transcode_notes or "",
            "proxy_destination_path": w.proxy_destination_path or "",
            "proxy_from_day": bool(
                w.proxy_destination_path
                and _day_proxy_location(w)[1] == w.proxy_destination_path
            ),
            "backup_copy": {
                "video_size_tb": w.backup_video_size_tb,
                "audio_size_gb": w.backup_audio_size_gb,
                "destination_path": w.backup_destination_path or "",
                "checksum_method": (w.backup_checksum_method or "").replace("_", " ").title(),
                "checksum_status": w.backup_checksum_status or "",
                "notes": w.backup_copy_notes or "",
                "critical": bool(w.backup_copy_critical),
            },
            "checksum_methods": list(wf.CHECKSUM_METHODS),
            "backup_started_at": w.backup_started_at.isoformat(timespec="minutes")
            if w.backup_started_at
            else "",
            "backup_finished_at": w.backup_finished_at.isoformat(timespec="minutes")
            if w.backup_finished_at
            else "",
            "backup_verified_at": w.backup_verified_at.isoformat(timespec="minutes")
            if w.backup_verified_at
            else "",
            "backup_verification_method": w.backup_verification_method,
            "backup_verification_evidence": w.backup_verification_evidence or "",
            "receive_checks": w.receive_checks,
            "receive_checks_summary": wf.checks_summary(w.receive_checks, wf.RECEIVE_CHECKS),
            "backup_checks": w.backup_checks,
            "backup_checks_summary": wf.checks_summary(w.backup_checks, wf.BACKUP_CHECKS),
            "transcode_pre_checks_summary": wf.checks_summary(
                w.transcode_pre_checks, wf.TRANSCODE_PRE_CHECKS
            ),
            "proxy_destination_id": w.proxy_destination_id,
            "proxy_destination": _vol_dict(proxy_vol) if proxy_vol else None,
            "proxy_preset": w.proxy_preset or "",
            "proxy_source_path": w.proxy_source_path or "",
            "transcode_pre_checks": w.transcode_pre_checks,
            "transcode_post_checks": w.transcode_post_checks,
            "transcode_started_at": w.transcode_started_at.isoformat(timespec="minutes")
            if w.transcode_started_at
            else "",
            "transcode_finished_at": w.transcode_finished_at.isoformat(timespec="minutes")
            if w.transcode_finished_at
            else "",
            "transcode_verified_at": w.transcode_verified_at.isoformat(timespec="minutes")
            if w.transcode_verified_at
            else "",
            "transcode_verification_method": w.transcode_verification_method,
            "complete_checks": w.complete_checks,
            "completed_at": w.completed_at.isoformat(timespec="minutes") if w.completed_at else "",
            "events": events,
            "open_issues": open_issues,
            "ended": w.status == wf.STATUS_ENDED,
            "ended_at_display": w.ended_at.strftime("%d %b %Y %H:%M") if w.ended_at else "",
            "ended_by": w.ended_by.name if w.ended_by else "",
            "end_reason": w.end_reason or "",
            "current_stage_label": wf.STAGE_LABELS.get(w.current_stage, w.current_stage),
            "stage_volumes": _stage_volumes(w, detect_mounts),
            "gates": {
                "receive_continue": {"ok": ok_recv, "error": err_recv},
                "backup_start": {"ok": ok_start_b, "error": err_start_b},
                "backup_verify": {"ok": ok_ver_b, "error": err_ver_b},
                "transcode_start": {"ok": ok_start_t, "error": err_start_t},
                "transcode_verify": {"ok": ok_ver_t, "error": err_ver_t},
                "mark_ready": {"ok": ok_ready, "error": err_ready},
            },
            "automation_note": (
                "This app records the workflow. File copy and proxy conversion are performed "
                "with your approved tools — the system does not claim to copy or transcode files automatically."
            ),
            "is_supervisor": _is_supervisor(actor),
        }

    # Expose bundle builder for machine_room_tasks_page_bundle
    app.extensions["mr_media_workflow_bundle"] = build_mission_control_bundle
    app.extensions["mr_media_workflow_models"] = models

    def mr_wf_day_statuses(project_id) -> dict[int, dict]:
        """Shooting day id → workflow status chip data for one project's production cards."""
        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            return {}
        rows = (
            db.session.query(models.MachineRoomMediaWorkflowDay.shooting_day_id, MachineRoomMediaWorkflow)
            .join(
                MachineRoomMediaWorkflow,
                MachineRoomMediaWorkflow.id == models.MachineRoomMediaWorkflowDay.workflow_id,
            )
            .filter(MachineRoomMediaWorkflow.project_id == pid)
            .all()
        )
        return {
            int(day_id): {"label": w.media_prep_label(), "status": w.status, "workflow_id": int(w.id)}
            for day_id, w in rows
        }

    app.jinja_env.globals["mr_wf_day_statuses"] = mr_wf_day_statuses

    @app.route("/projects/<int:project_id>/production/workflow-statuses")
    def project_production_workflow_statuses(project_id: int):
        acc = _actor()
        if acc is None:
            return jsonify({"error": "Sign in required."}), 401
        if account_can_access_project is not None and not account_can_access_project(acc, project_id):
            return jsonify({"error": "No access to this project."}), 403
        days = mr_wf_day_statuses(project_id)
        return jsonify(
            {"days": {str(k): {"label": v["label"], "status": v["status"]} for k, v in days.items()}}
        )

    @app.route("/machine-room/workflow")
    def machine_room_workflow_page():
        acc = _actor()
        if acc is None:
            return redirect(url_for("login"))
        perms = app.extensions.get("permissions")
        granted = bool(perms and perms.can(acc, "mr_workflow", "view"))
        if not (granted or account_is_machine_room_role(acc) or _is_supervisor(acc)):
            flash("That page is only available for Machine Room accounts.", "error")
            return redirect(url_for("index"))
        return render_template("machine_room_workflow.html", **build_mission_control_bundle(acc))

    @app.before_request
    def _workflow_links_open_workflow_page():
        """Older links opened a workflow on the Tasks page (/machine-room/tasks/progress?workflow_id=N)."""
        if request.endpoint == "machine_room_tasks_tab" and request.args.get("workflow_id", type=int):
            return redirect(
                url_for("machine_room_workflow_page", workflow_id=request.args.get("workflow_id", type=int))
            )
        return None

    @app.route("/machine-room/workflows/shooting-days", methods=["POST"])
    def machine_room_workflow_shooting_day_create():
        acc = _require_mr_or_supervisor()
        data = request.get_json(silent=True) or {}
        try:
            project_id = int(data.get("project_id"))
        except (TypeError, ValueError):
            return _json_error("Select a project first.")
        project = db.session.get(Project, project_id)
        if project is None:
            return _json_error("Project not found.", 404)

        try:
            unit_number = int(data.get("unit_number") or 1)
        except (TypeError, ValueError):
            return _json_error("Unit number must be a whole number.")
        if unit_number < 1:
            return _json_error("Unit number must be at least 1.")

        day_number = re.sub(r"(?i)^day\s*", "", (data.get("day_name") or "").strip())
        if not day_number:
            return _json_error("Enter the shooting day number.")
        day_name = f"Day {day_number}"
        if len(day_name) > 50:
            return _json_error("Day name must be 50 characters or fewer.")

        raw_date = (data.get("shooting_date") or "").strip()
        try:
            shooting_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            return _json_error("Enter a valid shooting date.")

        existing = ShootingDay.query.filter(
            ShootingDay.project_id == project_id,
            ShootingDay.unit_number == unit_number,
            ShootingDay.day_name.in_([day_name, day_number]),
        ).first()
        if existing is not None:
            return jsonify(
                {
                    "ok": True,
                    "created": False,
                    "day": {
                        "id": existing.id,
                        "label": wf.format_shooting_day_label(existing),
                        "day_name": existing.day_name or "",
                        "unit_number": int(existing.unit_number or 1),
                        "date": existing.shooting_date.isoformat() if existing.shooting_date else "",
                        "workflow_id": wf.workflow_ids_by_day(models, [existing.id]).get(existing.id),
                    },
                }
            )

        day = ShootingDay(
            project_id=project_id,
            unit_number=unit_number,
            day_name=day_name,
            shooting_date=shooting_date,
        )
        db.session.add(day)
        db.session.flush()
        if emit_shooting_day_created_activity:
            try:
                emit_shooting_day_created_activity(day, "machine room", actor=acc)
            except Exception:
                app.logger.exception("Shooting day activity notification failed")
        try:
            import project_activity_hooks as pah

            pah.log_shooting_day_created(day, source="machine_room")
        except Exception:
            app.logger.exception("Shooting day activity log failed")
        db.session.commit()
        return jsonify(
            {
                "ok": True,
                "created": True,
                "day": {
                    "id": day.id,
                    "label": wf.format_shooting_day_label(day),
                    "day_name": day.day_name or "",
                    "unit_number": int(day.unit_number or 1),
                    "date": day.shooting_date.isoformat(),
                    "workflow_id": None,
                },
            }
        )

    def _task_day_name(w) -> str:
        """Day label for linked Copy / Convert tasks (column holds 80 chars)."""
        names = [(d.day_name or "").strip() for d in w.days]
        return ", ".join(n for n in names if n)[:80]

    def _parse_day_ids(data) -> list[int]:
        raw = data.get("shooting_day_ids")
        if raw is None and data.get("shooting_day_id") not in (None, ""):
            raw = [data.get("shooting_day_id")]
        if isinstance(raw, str):
            raw = [x for x in raw.split(",") if x.strip()]
        ids: list[int] = []
        for item in raw or []:
            try:
                val = int(item)
            except (TypeError, ValueError):
                continue
            if val not in ids:
                ids.append(val)
        return ids

    def _load_project_days(project_id: int, day_ids: list[int]):
        days = ShootingDay.query.filter(ShootingDay.id.in_(day_ids)).all() if day_ids else []
        if not days or len(days) != len(day_ids) or any(d.project_id != project_id for d in days):
            return None
        return days

    def _conflict_response(conflicts: dict[int, int]):
        other_id = next(iter(conflicts.values()))
        other = db.session.get(MachineRoomMediaWorkflow, other_id)
        taken = [db.session.get(ShootingDay, did) for did in conflicts]
        names = ", ".join(wf.format_shooting_day_label(d) for d in taken if d)
        label = wf.format_days_label(other.days) if other else f"workflow #{other_id}"
        return (
            jsonify(
                {
                    "ok": False,
                    "error": (
                        f"{names} already belongs to another workflow ({label}). "
                        "Open that workflow or untick the day."
                    ),
                    "conflict_workflow_id": other_id,
                    "redirect": url_for(
                        "machine_room_workflow_page", workflow_id=other_id
                    ),
                }
            ),
            409,
        )

    @app.route("/machine-room/workflows", methods=["POST"])
    def machine_room_workflow_create():
        acc = _require_mr_or_supervisor()
        data = request.get_json(silent=True) or request.form
        try:
            project_id = int(data.get("project_id"))
        except (TypeError, ValueError):
            return _json_error("Project and shooting day are required.")
        day_ids = _parse_day_ids(data)
        if not day_ids:
            return _json_error("Select at least one shooting day.")

        project = db.session.get(Project, project_id)
        days = _load_project_days(project_id, day_ids)
        if project is None or days is None:
            return _json_error("Invalid project or shooting day.", 404)
        _, shuttle_err = _shuttle_volume_error(project_id, data.get("shuttle_volume_id"))
        if shuttle_err:
            return _json_error(shuttle_err)

        uid = _user_id(acc)
        try:
            row, created = wf.get_or_create_workflow(
                db,
                models,
                project_id=project_id,
                shooting_days=days,
                operator_user_id=uid,
                now_fn=now_local,
            )
        except wf.WorkflowDayConflict as exc:
            db.session.rollback()
            return _conflict_response(exc.conflicts)
        if not created and not row.assigned_operator_id and uid:
            row.assigned_operator_id = uid
        if created:
            started = (
                models.MachineRoomMediaWorkflowEvent.query.filter_by(
                    workflow_id=row.id, event_type="workflow_created"
                )
                .order_by(models.MachineRoomMediaWorkflowEvent.id.desc())
                .first()
            )
            if started is not None:
                _notify_step(
                    row,
                    "workflow_created",
                    f"Daily Media Processing started for {wf.format_days_label(row.days)}.",
                    started.id,
                )
        if data.get("shuttle_volume_id") and not row.received_at and row.status != wf.STATUS_ENDED:
            _apply_shuttle(row, acc, data.get("shuttle_volume_id"))
            if data.get("receive_notes"):
                row.receive_notes = str(data.get("receive_notes"))[:4000]
            _mark_received(row, acc)
        db.session.commit()

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(
                {
                    "ok": True,
                    "created": created,
                    "workflow_id": row.id,
                    "redirect": url_for("machine_room_workflow_page", workflow_id=row.id),
                }
            )
        flash(
            "Opened existing workflow." if not created else "Workflow started.",
            "success" if created else "info",
        )
        return redirect(
            url_for("machine_room_workflow_page", workflow_id=row.id)
        )

    def _day_proxy_location(w) -> tuple[Any, str]:
        """Proxy folder chosen when the shooting day was added (first day that has one)."""
        for day in w.days:
            path = (getattr(day, "proxy_path", None) or "").strip()
            vid = getattr(day, "proxy_volume_id", None)
            if not path or not vid:
                continue
            vol = db.session.get(StorageVolume, int(vid))
            if vol is not None and mr_support.normalize_storage_role(vol.storage_role) == "working_storage":
                return vol, path
        return None, ""

    def _shuttle_volume_error(project_id: int, raw_vid) -> tuple[Any, str]:
        """(volume, error) for a Transfer / Shuttle volume picked for a project."""
        try:
            vid = int(raw_vid) if raw_vid else None
        except (TypeError, ValueError):
            return None, "Invalid Transfer / Shuttle volume."
        if not vid:
            return None, ""
        vol = db.session.get(StorageVolume, vid)
        if vol is None or vol.storage_role != wf.ROLE_SHUTTLE:
            return None, "Select a configured Transfer / Shuttle volume."
        if vid not in _project_volume_ids(project_id):
            project = db.session.get(Project, project_id)
            return None, (
                f"{wf.volume_label(vol)} is not linked to "
                f"{project.name if project else 'this project'}."
            )
        return vol, ""

    def _apply_shuttle(w, acc, raw_vid) -> str:
        vol, err = _shuttle_volume_error(w.project_id, raw_vid)
        if err:
            return err
        if vol is None:
            w.shuttle_volume_id = None
            w.shuttle_volume_name = ""
            return ""
        if w.shuttle_volume_id and w.shuttle_volume_id != vol.id and w.backup_verified_at:
            wf.invalidate_downstream_after_receive_change(w, now_local)
            _add_event(
                db,
                models,
                w,
                event_type="source_changed",
                message="Shuttle volume changed — later verifications cleared for recheck",
                actor_user_id=_user_id(acc),
                stage=wf.STAGE_RECEIVE,
                now_fn=now_local,
            )
        w.shuttle_volume_id = vol.id
        w.shuttle_volume_name = wf.volume_label(vol)
        return ""

    def _mark_received(w, acc) -> str:
        ok, err = wf.can_advance_from_receive(w)
        if ok:
            err = _shuttle_link_error(w)
            ok = not err
        if not ok:
            return err
        w.received_at = now_local()
        w.received_by_id = _user_id(acc)
        w.current_stage = wf.STAGE_BACKUP
        w.status = wf.STATUS_IN_PROGRESS
        if not w.assigned_operator_id:
            w.assigned_operator_id = _user_id(acc)
        if not w.backup_destination_id:
            backups = wf.volumes_for_role(StorageVolume, wf.ROLE_PROJECTS_BACKUP)
            if len(backups) == 1:
                w.backup_destination_id = backups[0].id
                w.backup_destination_name = wf.volume_label(backups[0])
        _add_event(
            db,
            models,
            w,
            event_type="material_received",
            message=(
                "Shuttle received — material confirmed — "
                f"{wf.checks_summary(w.receive_checks, wf.RECEIVE_CHECKS)}"
            ),
            actor_user_id=_user_id(acc),
            stage=wf.STAGE_RECEIVE,
            verification_kind="operator",
            now_fn=now_local,
        )
        return ""

    def _start_card(vol) -> dict:
        d = _vol_dict(vol)
        return {
            "id": vol.id,
            "name": d["name"],
            "mounted": d["mounted"],
            "free_pct": round(d["free_pct"]) if d["free_pct"] is not None and d["capacity_tb"] else None,
        }

    @app.route("/machine-room/workflows/connected-drives")
    def machine_room_workflow_connected_drives():
        """Drives mounted under /Volumes that are new to the system, or shuttles not yet linked to the project."""
        _require_mr_or_supervisor()
        project_id = request.args.get("project_id", type=int)
        if not project_id or db.session.get(Project, project_id) is None:
            return _json_error("Select a project first.")
        linked = _project_volume_ids(project_id)
        new_drives, linkable = [], []
        for row in scan_mod.discover_mounted_volumes(StorageVolume):
            info = {
                "name": row.get("display_name") or row.get("name") or "",
                "mount_path": row.get("mount_path") or "",
                "capacity_tb": round(float(row.get("capacity_tb") or 0), 2),
                "free_pct": round(float(row.get("free_percentage") or 0)),
                "connection": (row.get("connection_type") or "").replace("_", " "),
            }
            if not row.get("already_added"):
                new_drives.append(info)
                continue
            vol = db.session.get(StorageVolume, row.get("existing_volume_id") or 0)
            if vol is not None and vol.storage_role == wf.ROLE_SHUTTLE and vol.id not in linked:
                linkable.append({**info, "volume_id": vol.id, "name": wf.volume_label(vol)})
        return jsonify({"ok": True, "new": new_drives, "linkable": linkable})

    @app.route("/machine-room/workflows/connected-drives/add", methods=["POST"])
    def machine_room_workflow_connected_drive_add():
        """Register a connected drive as Transfer / Shuttle (or link an existing one) for the project."""
        _require_mr_or_supervisor()
        data = request.get_json(silent=True) or {}
        try:
            project_id = int(data.get("project_id"))
        except (TypeError, ValueError):
            return _json_error("Select a project first.")
        project = db.session.get(Project, project_id)
        if project is None:
            return _json_error("Project not found.", 404)

        vol = None
        if data.get("volume_id"):
            vol = db.session.get(StorageVolume, int(data["volume_id"]))
            if vol is None or vol.storage_role != wf.ROLE_SHUTTLE:
                return _json_error("That drive is not a Transfer / Shuttle volume.")
        else:
            mount_path = (data.get("mount_path") or "").strip()
            row = next(
                (
                    r for r in scan_mod.discover_mounted_volumes(StorageVolume)
                    if r.get("mount_path") == mount_path
                ),
                None,
            )
            if row is None:
                return _json_error("That drive is no longer connected. Find drives again.")
            if row.get("already_added"):
                return _json_error("That drive is already registered on Storage.")
            values, errors = mr_support.discovery_values_from_form(
                {**{k: v for k, v in row.items() if not isinstance(v, dict)}, "storage_role": wf.ROLE_SHUTTLE}
            )
            if errors:
                return _json_error(errors[0])
            vol = StorageVolume()
            for key, val in mr_support.create_volume_from_discovery(values, now_local()).items():
                setattr(vol, key, val)
            vol.storage_role = wf.ROLE_SHUTTLE
            vol.is_mounted = True
            vol.mounted_status = "mounted"
            vol.last_seen_at = now_local()
            vol.created_at = now_local()
            vol.updated_at = now_local()
            db.session.add(vol)
            db.session.flush()

        mr_support.ensure_volume_project_links(
            db,
            StorageVolumeProjectLink,
            int(vol.id),
            [project_id],
            default_root_path_fn=lambda pid: scan_mod.default_project_root_path(vol, project.name),
        )
        db.session.commit()
        return jsonify({"ok": True, "volume": _start_card(vol)})

    @app.route("/machine-room/workflows/<int:workflow_id>")
    def machine_room_workflow_detail(workflow_id: int):
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            abort(404)
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    @app.route("/machine-room/workflows/<int:workflow_id>/receive", methods=["POST"])
    def machine_room_workflow_receive(workflow_id: int):
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        if w.status == wf.STATUS_ENDED:
            return _json_error(wf.ENDED_ERROR, 409)
        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "save").strip()

        if "shooting_day_ids" in data or "shooting_day_id" in data:
            day_ids = _parse_day_ids(data)
            if not day_ids:
                return _json_error("Keep at least one shooting day in this workflow.")
            days = _load_project_days(w.project_id, day_ids)
            if days is None:
                return _json_error("Those shooting days are not in this project.")
            owners = wf.workflow_ids_by_day(models, day_ids)
            conflicts = {did: oid for did, oid in owners.items() if oid != w.id}
            if conflicts:
                return _conflict_response(conflicts)
            if sorted(day_ids) != sorted(w.day_ids):
                had_later = bool(w.received_at or w.backup_started_at)
                wf.set_workflow_days(db, models, w, days)
                if had_later:
                    wf.invalidate_downstream_after_receive_change(w, now_local)
                _add_event(
                    db,
                    models,
                    w,
                    event_type="days_changed",
                    message=(
                        f"Shooting days set to {wf.format_days_label(w.days)}"
                        + (" — later verifications cleared for recheck" if had_later else "")
                    ),
                    actor_user_id=_user_id(acc),
                    stage=wf.STAGE_RECEIVE,
                    now_fn=now_local,
                )

        if "shuttle_volume_id" in data:
            err = _apply_shuttle(w, acc, data.get("shuttle_volume_id"))
            if err:
                return _json_error(err)

        if "receive_notes" in data:
            w.receive_notes = (data.get("receive_notes") or "")[:4000]
        if "checks" in data:
            allowed = set(wf.RECEIVE_CHECKS)
            w.receive_checks = [c for c in _parse_checks(data, "checks") if c in allowed]

        if action == "continue":
            err = _mark_received(w, acc)
            if err:
                return _json_error(err)
            db.session.commit()
            return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

        w.updated_at = now_local()
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    @app.route("/machine-room/workflows/<int:workflow_id>/backup/estimate", methods=["POST"])
    def machine_room_workflow_backup_estimate(workflow_id: int):
        """Edit time left on a running backup (same contract as the copy-task estimate modal)."""
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        if w.status == wf.STATUS_ENDED:
            return _json_error(wf.ENDED_ERROR, 409)
        if not w.backup_started_at or w.backup_finished_at:
            return _json_error("Time left can only be changed while the backup is running.")
        data = request.get_json(silent=True) or {}
        try:
            remaining = int(data.get("remaining_minutes"))
        except (TypeError, ValueError):
            return _json_error("Enter time left between 1 minute and 48 hours.")
        if remaining < 1 or remaining > 2880:
            return _json_error("Enter time left between 1 minute and 48 hours.")
        elapsed = wf.operation_active_minutes(w, "backup", now_local())
        total = max(1, min(2880, int(-(-elapsed // 1)) + remaining))
        w.backup_estimated_minutes = total
        if Task is not None and w.backup_copy_task_id:
            t = db.session.get(Task, w.backup_copy_task_id)
            if t is not None:
                t.copy_estimated_minutes = total
        _add_event(
            db,
            models,
            w,
            event_type="backup_estimate_changed",
            message=f"Backup time left set to {wf.format_hhmm(remaining)} — total estimate {wf.format_hhmm(total)}",
            actor_user_id=_user_id(acc),
            stage=wf.STAGE_BACKUP,
            now_fn=now_local,
        )
        w.updated_at = now_local()
        db.session.commit()
        summary = wf.workflow_progress_summary(w)
        return jsonify(
            {
                "ok": True,
                "estimated_minutes": total,
                "remaining_minutes": remaining,
                "started_ms": summary["operations"][0]["started_ms"] or 0,
            }
        )

    def _pause_or_resume(w, acc, key: str, action: str):
        """Pause / continue a running backup or transcode; pauses are excluded from elapsed time."""
        stage = wf.STAGE_BACKUP if key == "backup" else wf.STAGE_TRANSCODE
        noun = "Backup" if key == "backup" else "Transcoding"
        started = getattr(w, key + "_started_at")
        if not started or getattr(w, key + "_finished_at"):
            return _json_error(f"{noun} is not running.")
        paused_at = getattr(w, key + "_paused_at")
        now = now_local()
        if action == "pause":
            if paused_at:
                return _json_error(f"{noun} is already paused.")
            setattr(w, key + "_paused_at", now)
            event_type, message = f"{key}_paused", f"{noun} paused by operator"
        else:
            if not paused_at:
                return _json_error(f"{noun} is not paused.")
            paused_for = max(0, int((now - paused_at).total_seconds()))
            setattr(w, key + "_paused_seconds", int(getattr(w, key + "_paused_seconds") or 0) + paused_for)
            setattr(w, key + "_paused_at", None)
            event_type = f"{key}_resumed"
            message = f"{noun} continued after {wf.format_hhmm(max(1, paused_for // 60))} paused"
        task_id = w.backup_copy_task_id if key == "backup" else w.convert_task_id
        if Task is not None and task_id:
            t = db.session.get(Task, task_id)
            if t is not None and t.status != "done":
                t.copy_started_at = wf.operation_effective_start(w, key)
        _add_event(
            db,
            models,
            w,
            event_type=event_type,
            message=message,
            actor_user_id=_user_id(acc),
            stage=stage,
            now_fn=now_local,
        )
        w.updated_at = now
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    def _fold_pause_on_finish(w, key: str, finished_at) -> None:
        paused_at = getattr(w, key + "_paused_at")
        if paused_at:
            extra = max(0, int((finished_at - paused_at).total_seconds()))
            setattr(w, key + "_paused_seconds", int(getattr(w, key + "_paused_seconds") or 0) + extra)
            setattr(w, key + "_paused_at", None)

    @app.route("/machine-room/workflows/<int:workflow_id>/transcode/estimate", methods=["POST"])
    def machine_room_workflow_transcode_estimate(workflow_id: int):
        """Edit time left on running transcoding (same contract as the copy-task estimate modal)."""
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        if w.status == wf.STATUS_ENDED:
            return _json_error(wf.ENDED_ERROR, 409)
        if not w.transcode_started_at or w.transcode_finished_at:
            return _json_error("Time left can only be changed while transcoding is running.")
        data = request.get_json(silent=True) or {}
        try:
            remaining = int(data.get("remaining_minutes"))
        except (TypeError, ValueError):
            return _json_error("Enter time left between 1 minute and 48 hours.")
        if remaining < 1 or remaining > 2880:
            return _json_error("Enter time left between 1 minute and 48 hours.")
        elapsed = wf.operation_active_minutes(w, "transcode", now_local())
        total = max(1, min(2880, int(-(-elapsed // 1)) + remaining))
        w.transcode_estimated_minutes = total
        if Task is not None and w.convert_task_id:
            t = db.session.get(Task, w.convert_task_id)
            if t is not None:
                t.copy_estimated_minutes = total
        _add_event(
            db,
            models,
            w,
            event_type="transcode_estimate_changed",
            message=f"Transcoding time left set to {wf.format_hhmm(remaining)} — total estimate {wf.format_hhmm(total)}",
            actor_user_id=_user_id(acc),
            stage=wf.STAGE_TRANSCODE,
            now_fn=now_local,
        )
        w.updated_at = now_local()
        db.session.commit()
        summary = wf.workflow_progress_summary(w)
        return jsonify(
            {
                "ok": True,
                "estimated_minutes": total,
                "remaining_minutes": remaining,
                "started_ms": summary["operations"][1]["started_ms"] or 0,
            }
        )

    @app.route("/machine-room/workflows/<int:workflow_id>/backup", methods=["POST"])
    def machine_room_workflow_backup(workflow_id: int):
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        if w.status == wf.STATUS_ENDED:
            return _json_error(wf.ENDED_ERROR, 409)
        if not w.received_at:
            return _json_error("Complete Receive before backup.")
        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "save").strip()

        if "backup_estimated_minutes" in data and not w.backup_started_at:
            w.backup_estimated_minutes = wf.parse_estimate_minutes(data.get("backup_estimated_minutes"))

        if "backup_destination_id" in data:
            try:
                vid = int(data["backup_destination_id"]) if data.get("backup_destination_id") else None
            except (TypeError, ValueError):
                return _json_error("Invalid Projects Backup volume.")
            if vid:
                vol = db.session.get(StorageVolume, vid)
                if vol is None or vol.storage_role != wf.ROLE_PROJECTS_BACKUP:
                    return _json_error("Select a configured Projects Backup volume.")
                if w.shuttle_volume_id and vid == w.shuttle_volume_id:
                    return _json_error("Source and destination must be different.")
                if (
                    w.backup_destination_id
                    and w.backup_destination_id != vid
                    and w.backup_verified_at
                ):
                    wf.invalidate_downstream_after_backup_change(w, now_local)
                    _add_event(
                        db,
                        models,
                        w,
                        event_type="destination_changed",
                        message="Backup destination changed — later verifications cleared",
                        actor_user_id=_user_id(acc),
                        stage=wf.STAGE_BACKUP,
                        now_fn=now_local,
                    )
                w.backup_destination_id = vid
                w.backup_destination_name = wf.volume_label(vol)
                w.backup_destination_path = (vol.mount_path or "")[:512]
            elif w.backup_started_at:
                return _json_error("Backup already started — the destination can't be cleared.")
            else:
                w.backup_destination_id = None
                w.backup_destination_name = ""
                w.backup_destination_path = ""

        if "checks" in data:
            allowed = set(wf.BACKUP_CHECKS)
            w.backup_checks = [c for c in _parse_checks(data, "checks") if c in allowed]

        if action == "start":
            if "backup_destination_id" in data and data.get("backup_destination_id"):
                try:
                    vid = int(data["backup_destination_id"])
                    vol = db.session.get(StorageVolume, vid)
                    if vol and vol.storage_role == wf.ROLE_PROJECTS_BACKUP:
                        if w.shuttle_volume_id and vid == w.shuttle_volume_id:
                            return _json_error("Source and destination must be different.")
                        w.backup_destination_id = vid
                        w.backup_destination_name = wf.volume_label(vol)
                        w.backup_destination_path = (vol.mount_path or "")[:512]
                except (TypeError, ValueError):
                    pass
            ok, err = wf.can_start_backup(w)
            if not ok:
                return _json_error(err)
            dest_vol = db.session.get(StorageVolume, w.backup_destination_id)
            details, err = wf.parse_copy_details(
                data, mount_path=(getattr(dest_vol, "mount_path", "") or "")
            )
            if err:
                return _json_error(err)
            w.backup_video_size_tb = details["video_size_tb"]
            w.backup_audio_size_gb = details["audio_size_gb"]
            if details["destination_path"]:
                w.backup_destination_path = details["destination_path"]
            w.backup_checksum_method = details["checksum_method"]
            w.backup_checksum_status = details["checksum_status"]
            w.backup_copy_notes = details["notes"]
            w.backup_copy_critical = details["critical"]
            if details["critical"] and ShootingDayCriticalNote is not None:
                for day in w.days:
                    note = ShootingDayCriticalNote(
                        shooting_day_id=day.id,
                        body=details["notes"],
                        created_by_user_id=_user_id(acc),
                    )
                    db.session.add(note)
                    db.session.flush()
                    if emit_shooting_day_critical_created is not None:
                        emit_shooting_day_critical_created(note, day, actor=acc)
            w.current_stage = wf.STAGE_BACKUP
            w.status = wf.STATUS_IN_PROGRESS
            w.backup_started_at = now_local()
            w.backup_finished_at = None
            w.backup_verified_at = None
            w.backup_verification_method = wf.VERIFY_PENDING
            # Optional linked Copy Material task (tracking only — no filesystem copy)
            assignee = w.assigned_operator_id or _user_id(acc)
            if Task is not None and not w.backup_copy_task_id and assignee:
                day = w.shooting_day
                t = Task(
                    title=MR_STREAM_COPY_TITLE,
                    status="in_progress",
                    project_id=w.project_id,
                    user_id=assignee,
                    copy_started_at=now_local(),
                    copy_estimated_minutes=w.backup_estimated_minutes,
                    copy_day_name=_task_day_name(w),
                    copy_unit_number=getattr(day, "unit_number", None) or 1,
                )
                db.session.add(t)
                db.session.flush()
                w.backup_copy_task_id = t.id
            _add_event(
                db,
                models,
                w,
                event_type="backup_started",
                message=(
                    "Backup started — estimated "
                    f"{wf.format_hhmm(w.backup_estimated_minutes)} — "
                    "operator to COPY (not move) to Projects Backup"
                    + "".join(
                        f" · {label}: {value}"
                        for label, value in (
                            ("Path", w.backup_destination_path),
                            ("Video", f"{w.backup_video_size_tb:g} TB" if w.backup_video_size_tb else ""),
                            ("Audio", f"{w.backup_audio_size_gb:g} GB" if w.backup_audio_size_gb else ""),
                            ("Checksum", " / ".join(
                                x for x in (w.backup_checksum_method, w.backup_checksum_status) if x
                            )),
                            ("Critical note" if w.backup_copy_critical else "Notes", w.backup_copy_notes),
                        )
                        if value
                    )
                ),
                actor_user_id=_user_id(acc),
                stage=wf.STAGE_BACKUP,
                now_fn=now_local,
            )
            db.session.commit()
            return jsonify(
                {
                    "ok": True,
                    "workflow": _workflow_detail(w, acc),
                    "automation": False,
                    "note": (
                        "Backup recording started. Copy files with your approved tools. "
                        "This system is not copying files automatically."
                    ),
                }
            )

        if action in ("pause", "resume"):
            return _pause_or_resume(w, acc, "backup", action)

        if action == "finish_copy":
            if not w.backup_started_at:
                return _json_error("Start backup first.")
            w.backup_finished_at = now_local()
            _fold_pause_on_finish(w, "backup", w.backup_finished_at)
            if Task is not None and w.backup_copy_task_id:
                t = db.session.get(Task, w.backup_copy_task_id)
                if t and t.status != "done":
                    t.status = "done"
                    t.copy_started_at = wf.operation_effective_start(w, "backup")
                    t.completed_at = w.backup_finished_at
            _add_event(
                db,
                models,
                w,
                event_type="backup_copy_finished",
                message="Operator marked copy finished",
                actor_user_id=_user_id(acc),
                stage=wf.STAGE_BACKUP,
                verification_kind="operator",
                now_fn=now_local,
            )
            db.session.commit()
            return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

        if action == "verify":
            if "checks" in data:
                allowed = set(wf.BACKUP_CHECKS)
                w.backup_checks = [c for c in _parse_checks(data, "checks") if c in allowed]
            ok, err = wf.can_verify_backup(w)
            if not ok:
                return _json_error(err)
            method = (data.get("verification_method") or wf.VERIFY_OPERATOR).strip()
            if method not in (wf.VERIFY_OPERATOR, wf.VERIFY_CHECKSUM):
                method = wf.VERIFY_OPERATOR
            evidence = (data.get("evidence") or "").strip()
            if method == wf.VERIFY_CHECKSUM and not evidence:
                return _json_error(
                    "Checksum verification requires evidence from an approved verification tool."
                )
            if method == wf.VERIFY_OPERATOR:
                evidence = evidence or (
                    "Operator verified file counts, folder structure and sizes."
                )
            w.backup_verified_at = now_local()
            w.backup_verified_by_id = _user_id(acc)
            w.backup_verification_method = method
            w.backup_verification_evidence = evidence[:4000]
            w.current_stage = wf.STAGE_TRANSCODE
            if not w.proxy_destination_id:
                day_vol, day_path = _day_proxy_location(w)
                if day_vol is not None:
                    w.proxy_destination_id = day_vol.id
                    w.proxy_destination_name = wf.volume_label(day_vol)
                    w.proxy_destination_path = day_path[:512]
            # Default inhouse destination
            if not w.proxy_destination_id:
                inhouse = wf.volumes_for_role(StorageVolume, wf.ROLE_INHOUSE)
                if len(inhouse) == 1:
                    w.proxy_destination_id = inhouse[0].id
                    w.proxy_destination_name = wf.volume_label(inhouse[0])
                    w.proxy_destination_path = (inhouse[0].mount_path or "")[:512]
            if Task is not None and w.backup_copy_task_id:
                t = db.session.get(Task, w.backup_copy_task_id)
                if t and t.status != "done":
                    t.status = "done"
                    t.completed_at = now_local()
            _add_event(
                db,
                models,
                w,
                event_type="backup_verified",
                message=(
                    f"Backup verified ({method}) — "
                    f"{wf.checks_summary(w.backup_checks, wf.BACKUP_CHECKS)}"
                ),
                actor_user_id=_user_id(acc),
                stage=wf.STAGE_BACKUP,
                verification_kind="auto" if method == wf.VERIFY_CHECKSUM else "operator",
                now_fn=now_local,
            )
            db.session.commit()
            return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

        if action == "fail_verify":
            w.backup_verification_method = wf.VERIFY_FAILED
            w.status = wf.STATUS_PROBLEM
            _add_event(
                db,
                models,
                w,
                event_type="backup_verify_failed",
                message="Backup verification failed",
                actor_user_id=_user_id(acc),
                stage=wf.STAGE_BACKUP,
                now_fn=now_local,
            )
            db.session.commit()
            return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

        w.updated_at = now_local()
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    @app.route("/machine-room/workflows/<int:workflow_id>/transcode", methods=["POST"])
    def machine_room_workflow_transcode(workflow_id: int):
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        if w.status == wf.STATUS_ENDED:
            return _json_error(wf.ENDED_ERROR, 409)
        if not w.backup_verified_at:
            return _json_error("Backup must be verified before transcoding.")
        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "save").strip()

        if "proxy_destination_id" in data:
            try:
                vid = int(data["proxy_destination_id"]) if data.get("proxy_destination_id") else None
            except (TypeError, ValueError):
                return _json_error("Invalid In-house Storage volume.")
            if vid:
                vol = db.session.get(StorageVolume, vid)
                if vol is None or vol.storage_role != wf.ROLE_INHOUSE:
                    return _json_error("Select a configured In-house Storage volume.")
                if (
                    w.proxy_destination_id
                    and w.proxy_destination_id != vid
                    and w.transcode_verified_at
                ):
                    w.transcode_verified_at = None
                    w.transcode_verification_method = wf.VERIFY_PENDING
                    w.transcode_post_checks = []
                    w.complete_checks = []
                    w.completed_at = None
                    if w.status == wf.STATUS_READY:
                        w.status = wf.STATUS_IN_PROGRESS
                    w.current_stage = wf.STAGE_TRANSCODE
                w.proxy_destination_id = vid
                w.proxy_destination_name = wf.volume_label(vol)
                w.proxy_destination_path = (vol.mount_path or "")[:512]
            elif w.transcode_started_at:
                return _json_error("Transcoding already started — the destination can't be cleared.")
            else:
                w.proxy_destination_id = None
                w.proxy_destination_name = ""
                w.proxy_destination_path = ""

        if "proxy_preset" in data:
            w.proxy_preset = (data.get("proxy_preset") or "").strip()[:120]
        if "proxy_source_path" in data:
            # Store as display note only — never execute as a shell path
            w.proxy_source_path = (data.get("proxy_source_path") or "").strip()[:512]
        if "pre_checks" in data:
            allowed = set(wf.TRANSCODE_PRE_CHECKS)
            w.transcode_pre_checks = [
                c for c in _parse_checks(data, "pre_checks") if c in allowed
            ]
        if "post_checks" in data:
            allowed = set(wf.TRANSCODE_POST_CHECKS)
            w.transcode_post_checks = [
                c for c in _parse_checks(data, "post_checks") if c in allowed
            ]

        if action == "start":
            if "pre_checks" in data:
                allowed = set(wf.TRANSCODE_PRE_CHECKS)
                w.transcode_pre_checks = [
                    c for c in _parse_checks(data, "pre_checks") if c in allowed
                ]
            if "proxy_destination_id" in data and data.get("proxy_destination_id"):
                try:
                    vid = int(data["proxy_destination_id"])
                    vol = db.session.get(StorageVolume, vid)
                    if vol and vol.storage_role == wf.ROLE_INHOUSE:
                        w.proxy_destination_id = vid
                        w.proxy_destination_name = wf.volume_label(vol)
                        w.proxy_destination_path = (vol.mount_path or "")[:512]
                except (TypeError, ValueError):
                    pass
            if "proxy_preset" in data:
                w.proxy_preset = (data.get("proxy_preset") or "").strip()[:120]
            ok, err = wf.can_start_transcode(w)
            if not ok:
                return _json_error(err)
            estimate = wf.parse_estimate_minutes(data.get("transcode_estimated_minutes"))
            if not estimate:
                return _json_error("Enter the estimated transcoding time (HH : MM).")
            dest_vol = db.session.get(StorageVolume, w.proxy_destination_id)
            path, err = wf.validate_destination_path(
                data.get("destination_path"),
                getattr(dest_vol, "mount_path", "") or "",
                "In-house Storage",
            )
            if err:
                return _json_error(err)
            notes = str(data.get("notes") or "").strip()
            if len(notes) > 20_000:
                return _json_error("Notes are too long.")
            w.transcode_estimated_minutes = estimate
            w.transcode_notes = notes
            if path:
                w.proxy_destination_path = path
            w.current_stage = wf.STAGE_TRANSCODE
            w.status = wf.STATUS_IN_PROGRESS
            w.transcode_started_at = now_local()
            w.transcode_finished_at = None
            w.transcode_verified_at = None
            w.transcode_verification_method = wf.VERIFY_PENDING
            assignee = w.assigned_operator_id or _user_id(acc)
            if Task is not None and not w.convert_task_id and assignee:
                day = w.shooting_day
                t = Task(
                    title=MR_STREAM_CONVERT_TITLE,
                    status="in_progress",
                    project_id=w.project_id,
                    user_id=assignee,
                    copy_started_at=now_local(),
                    copy_estimated_minutes=estimate,
                    copy_day_name=_task_day_name(w),
                    copy_unit_number=getattr(day, "unit_number", None) or 1,
                )
                db.session.add(t)
                db.session.flush()
                w.convert_task_id = t.id
            elif Task is not None and w.convert_task_id:
                t = db.session.get(Task, w.convert_task_id)
                if t is not None:
                    t.status = "in_progress"
                    t.completed_at = None
                    t.copy_started_at = w.transcode_started_at
                    t.copy_estimated_minutes = estimate
            _add_event(
                db,
                models,
                w,
                event_type="transcode_started",
                message=(
                    f"Transcoding started — estimated {wf.format_hhmm(estimate)} — "
                    f"preset: {w.proxy_preset or 'not recorded'} — "
                    f"{wf.checks_summary(w.transcode_pre_checks, wf.TRANSCODE_PRE_CHECKS)}"
                    + (f" · Path: {w.proxy_destination_path}" if w.proxy_destination_path else "")
                    + (f" · Notes: {notes}" if notes else "")
                ),
                actor_user_id=_user_id(acc),
                stage=wf.STAGE_TRANSCODE,
                now_fn=now_local,
            )
            db.session.commit()
            return jsonify(
                {
                    "ok": True,
                    "workflow": _workflow_detail(w, acc),
                    "automation": False,
                    "note": (
                        "Transcode recording started. Generate proxies with your approved tools. "
                        "This system is not transcoding files automatically."
                    ),
                }
            )

        if action in ("pause", "resume"):
            return _pause_or_resume(w, acc, "transcode", action)

        if action == "finish":
            if not w.transcode_started_at:
                return _json_error("Start transcoding first.")
            w.transcode_finished_at = now_local()
            _fold_pause_on_finish(w, "transcode", w.transcode_finished_at)
            if Task is not None and w.convert_task_id:
                t = db.session.get(Task, w.convert_task_id)
                if t and t.status != "done":
                    t.status = "done"
                    t.copy_started_at = wf.operation_effective_start(w, "transcode")
                    t.completed_at = w.transcode_finished_at
            _add_event(
                db,
                models,
                w,
                event_type="transcode_finished",
                message="Operator marked transcoding finished",
                actor_user_id=_user_id(acc),
                stage=wf.STAGE_TRANSCODE,
                verification_kind="operator",
                now_fn=now_local,
            )
            db.session.commit()
            return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

        if action == "verify":
            if "post_checks" in data:
                allowed = set(wf.TRANSCODE_POST_CHECKS)
                w.transcode_post_checks = [
                    c for c in _parse_checks(data, "post_checks") if c in allowed
                ]
            ok, err = wf.can_verify_transcode(w)
            if not ok:
                return _json_error(err)
            w.transcode_verified_at = now_local()
            w.transcode_verified_by_id = _user_id(acc)
            w.transcode_verification_method = wf.VERIFY_OPERATOR
            w.current_stage = wf.STAGE_COMPLETE
            if Task is not None and w.convert_task_id:
                t = db.session.get(Task, w.convert_task_id)
                if t and t.status != "done":
                    t.status = "done"
                    t.completed_at = now_local()
            _add_event(
                db,
                models,
                w,
                event_type="proxies_verified",
                message="Proxies verified (operator confirmed)",
                actor_user_id=_user_id(acc),
                stage=wf.STAGE_TRANSCODE,
                verification_kind="operator",
                now_fn=now_local,
            )
            db.session.commit()
            return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

        w.updated_at = now_local()
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    @app.route("/machine-room/workflows/<int:workflow_id>/complete", methods=["POST"])
    def machine_room_workflow_complete(workflow_id: int):
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        if w.status == wf.STATUS_ENDED:
            return _json_error(wf.ENDED_ERROR, 409)
        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "save").strip()

        if "checks" in data:
            allowed = set(wf.COMPLETE_CHECKS)
            w.complete_checks = [c for c in _parse_checks(data, "checks") if c in allowed]

        if action == "mark_ready":
            if "checks" in data:
                allowed = set(wf.COMPLETE_CHECKS)
                w.complete_checks = [c for c in _parse_checks(data, "checks") if c in allowed]
            ok, err = wf.can_mark_ready(w)
            if not ok:
                return _json_error(err)
            w.completed_at = now_local()
            w.completed_by_id = _user_id(acc)
            w.status = wf.STATUS_READY
            w.current_stage = wf.STAGE_COMPLETE
            _add_event(
                db,
                models,
                w,
                event_type="ready_for_editing",
                message="Marked ready for editing",
                actor_user_id=_user_id(acc),
                stage=wf.STAGE_COMPLETE,
                verification_kind="operator",
                now_fn=now_local,
            )
            db.session.commit()
            return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

        w.updated_at = now_local()
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    @app.route("/machine-room/workflows/<int:workflow_id>/issues", methods=["POST"])
    def machine_room_workflow_report_issue(workflow_id: int):
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        if w.status == wf.STATUS_ENDED:
            return _json_error(wf.ENDED_ERROR, 409)
        data = request.get_json(silent=True) or {}
        category = (data.get("category") or "other").strip()
        if category not in wf.PROBLEM_CATEGORIES:
            category = "other"
        description = (data.get("description") or "").strip()
        if not description:
            return _json_error("Describe the problem.")
        is_critical = data.get("is_critical")
        if is_critical is None:
            is_critical = category in (
                "backup_failed",
                "transcoding_failed",
                "missing_files",
                "insufficient_storage",
            )
        issue = MachineRoomMediaWorkflowIssue(
            workflow_id=w.id,
            category=category,
            description=description[:4000],
            is_critical=bool(is_critical),
            status="open",
            reported_by_id=_user_id(acc),
            created_at=now_local(),
        )
        db.session.add(issue)
        if issue.is_critical:
            w.blocked_by_issue = True
            w.status = wf.STATUS_PROBLEM
        _add_event(
            db,
            models,
            w,
            event_type="problem_reported",
            message=f"Problem reported: {wf.PROBLEM_CATEGORY_LABELS.get(category, category)}",
            actor_user_id=_user_id(acc),
            now_fn=now_local,
        )
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc), "issue_id": issue.id})

    @app.route(
        "/machine-room/workflows/<int:workflow_id>/issues/<int:issue_id>/resolve",
        methods=["POST"],
    )
    def machine_room_workflow_resolve_issue(workflow_id: int, issue_id: int):
        acc = _require_mr_or_supervisor()
        if not _is_supervisor(acc):
            return _json_error("Only a supervisor can resolve critical issues.", 403)
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        issue = db.session.get(MachineRoomMediaWorkflowIssue, issue_id)
        if w is None or issue is None or issue.workflow_id != w.id:
            return _json_error("Issue not found.", 404)
        data = request.get_json(silent=True) or {}
        note = (data.get("resolution_note") or "").strip()
        if not note:
            return _json_error("A resolution note is required.")
        issue.status = "resolved"
        issue.resolved_at = now_local()
        issue.resolved_by_id = _user_id(acc)
        issue.resolution_note = note[:4000]
        open_critical = any(
            i.status == "open" and i.is_critical for i in (w.issues or []) if i.id != issue.id
        )
        w.blocked_by_issue = open_critical
        if not open_critical and w.status == wf.STATUS_PROBLEM:
            w.status = wf.STATUS_IN_PROGRESS if w.received_at else wf.STATUS_PENDING
        ov = MachineRoomMediaWorkflowOverride(
            workflow_id=w.id,
            action="resolve_issue",
            reason=note[:4000],
            supervisor_user_id=_user_id(acc),
            created_at=now_local(),
        )
        db.session.add(ov)
        _add_event(
            db,
            models,
            w,
            event_type="problem_resolved",
            message=f"Problem resolved by supervisor: {note[:120]}",
            actor_user_id=_user_id(acc),
            verification_kind="supervisor",
            now_fn=now_local,
        )
        if log_security_event:
            try:
                log_security_event(
                    "mr_workflow_issue_resolved",
                    account_id=getattr(acc, "id", None),
                    detail=f"workflow={w.id} issue={issue.id}",
                )
            except Exception:
                pass
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    @app.route("/machine-room/workflows/<int:workflow_id>/reopen", methods=["POST"])
    def machine_room_workflow_reopen(workflow_id: int):
        acc = _require_mr_or_supervisor()
        if not _is_supervisor(acc):
            return _json_error("Only a supervisor can reopen a completed workflow.", 403)
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        data = request.get_json(silent=True) or {}
        reason = (data.get("reason") or "").strip()
        if not reason:
            return _json_error("A written reason is required.")
        stage = (data.get("stage") or wf.STAGE_COMPLETE).strip()
        if stage not in wf.WORKFLOW_STAGES:
            stage = wf.STAGE_COMPLETE
        # Reopen does NOT flip failed/unverified into verified
        w.status = wf.STATUS_IN_PROGRESS
        w.current_stage = stage
        w.completed_at = None
        w.completed_by_id = None
        if stage in (wf.STAGE_RECEIVE, wf.STAGE_BACKUP):
            wf.invalidate_downstream_after_receive_change(w, now_local) if stage == wf.STAGE_RECEIVE else wf.invalidate_downstream_after_backup_change(w, now_local)
        elif stage == wf.STAGE_TRANSCODE:
            w.transcode_verified_at = None
            w.transcode_verification_method = wf.VERIFY_PENDING
            w.complete_checks = []
        ov = MachineRoomMediaWorkflowOverride(
            workflow_id=w.id,
            action=f"reopen_to_{stage}",
            reason=reason[:4000],
            supervisor_user_id=_user_id(acc),
            created_at=now_local(),
        )
        db.session.add(ov)
        _add_event(
            db,
            models,
            w,
            event_type="workflow_reopened",
            message=f"Reopened to {wf.STAGE_LABELS.get(stage, stage)}: {reason[:160]}",
            actor_user_id=_user_id(acc),
            stage=stage,
            verification_kind="supervisor",
            now_fn=now_local,
        )
        if log_security_event:
            try:
                log_security_event(
                    "mr_workflow_reopened",
                    account_id=getattr(acc, "id", None),
                    detail=f"workflow={w.id} stage={stage}",
                )
            except Exception:
                pass
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    @app.route("/machine-room/workflows/<int:workflow_id>/assign", methods=["POST"])
    def machine_room_workflow_assign(workflow_id: int):
        acc = _require_mr_or_supervisor()
        if not _is_supervisor(acc):
            return _json_error("Only a supervisor can reassign operators.", 403)
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        data = request.get_json(silent=True) or {}
        try:
            uid = int(data.get("operator_user_id"))
        except (TypeError, ValueError):
            return _json_error("operator_user_id required.")
        user = db.session.get(User, uid)
        if user is None:
            return _json_error("User not found.", 404)
        reason = (data.get("reason") or "Reassigned by supervisor").strip()
        w.assigned_operator_id = uid
        ov = MachineRoomMediaWorkflowOverride(
            workflow_id=w.id,
            action="reassign_operator",
            reason=reason[:4000],
            supervisor_user_id=_user_id(acc),
            created_at=now_local(),
        )
        db.session.add(ov)
        _add_event(
            db,
            models,
            w,
            event_type="operator_reassigned",
            message=f"Assigned to {user.name}: {reason[:120]}",
            actor_user_id=_user_id(acc),
            verification_kind="supervisor",
            now_fn=now_local,
        )
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    # Allow navigating to a completed stage for inspection (no silent invalidation)
    @app.route("/machine-room/workflows/<int:workflow_id>/view-stage", methods=["POST"])
    def machine_room_workflow_view_stage(workflow_id: int):
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        data = request.get_json(silent=True) or {}
        stage = (data.get("stage") or "").strip()
        if stage not in wf.WORKFLOW_STAGES:
            return _json_error("Invalid stage.")
        state = w.stage_state(stage)
        if state == "locked" and not _is_supervisor(acc):
            return _json_error("That step is locked until earlier steps are complete.")
        # Viewing only — return detail with focus_stage hint; do not mutate current_stage
        detail = _workflow_detail(w, acc)
        detail["focus_stage"] = stage
        return jsonify({"ok": True, "workflow": detail})

    @app.route("/machine-room/workflows/<int:workflow_id>/end", methods=["POST"])
    def machine_room_workflow_end(workflow_id: int):
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        if w.status == wf.STATUS_ENDED:
            return _json_error("This workflow is already ended.", 409)
        if w.status == wf.STATUS_READY:
            return _json_error("This workflow is already complete.", 409)
        data = request.get_json(silent=True) or {}
        reason = (data.get("reason") or "").strip()
        if not reason:
            return _json_error("Write a short reason for ending the workflow here.")
        stage_label = wf.STAGE_LABELS.get(w.current_stage, w.current_stage)
        w.status = wf.STATUS_ENDED
        w.ended_at = now_local()
        w.ended_by_id = _user_id(acc)
        w.end_reason = reason[:4000]
        _add_event(
            db,
            models,
            w,
            event_type="workflow_ended",
            message=f"Ended at {stage_label}: {reason[:300]}",
            actor_user_id=_user_id(acc),
            now_fn=now_local,
        )
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    @app.route("/machine-room/workflows/<int:workflow_id>/resume", methods=["POST"])
    def machine_room_workflow_resume(workflow_id: int):
        acc = _require_mr_or_supervisor()
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return _json_error("Workflow not found.", 404)
        if w.status != wf.STATUS_ENDED:
            return _json_error("Only an ended workflow can be resumed.", 409)
        open_critical = any(i.status == "open" and i.is_critical for i in (w.issues or []))
        if open_critical:
            w.status = wf.STATUS_PROBLEM
        else:
            w.status = wf.STATUS_IN_PROGRESS if w.received_at else wf.STATUS_PENDING
        w.ended_at = None
        w.ended_by_id = None
        w.end_reason = ""
        _add_event(
            db,
            models,
            w,
            event_type="workflow_resumed",
            message=f"Resumed at {wf.STAGE_LABELS.get(w.current_stage, w.current_stage)}",
            actor_user_id=_user_id(acc),
            now_fn=now_local,
        )
        db.session.commit()
        return jsonify({"ok": True, "workflow": _workflow_detail(w, acc)})

    @app.route("/machine-room/workflows/<int:workflow_id>/remove", methods=["POST"])
    def machine_room_workflow_remove(workflow_id: int):
        acc = _require_mr_or_supervisor()
        data = request.get_json(silent=True) or {}
        if not (data.get("challenge_token") or "").strip():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "safe_delete_required",
                        "message": "Confirm with Safe Delete before deleting this workflow.",
                    }
                ),
                400,
            )
        guard = app.extensions.get("safe_delete_guard")
        safe_delete_svc = app.extensions.get("safe_delete_service")
        if guard is None or safe_delete_svc is None:
            abort(500)
        challenge, sd_err = guard("mr_media_workflow", workflow_id)
        if sd_err is not None:
            return sd_err
        w = db.session.get(MachineRoomMediaWorkflow, workflow_id)
        if w is None:
            return jsonify({"ok": False, "error": "not_found", "code": "gone"}), 404
        label = f"{w.project.name if w.project else 'Project'} · {wf.format_days_label(w.days)}"
        if Task is not None:
            for task_id in (w.backup_copy_task_id, w.convert_task_id):
                task = db.session.get(Task, task_id) if task_id else None
                if task is not None and task.status != "done":
                    task.archived = True
        db.session.delete(w)
        safe_delete_svc.consume(challenge)
        db.session.commit()
        if log_security_event:
            try:
                log_security_event(
                    "safe_delete_executed",
                    account_id=getattr(acc, "id", None),
                    entity_type="mr_media_workflow",
                    entity_id=int(workflow_id),
                    details={"challenge_id": challenge.id, "name": label, "delete_kind": "permanent"},
                )
            except Exception:
                app.logger.exception("Could not log workflow delete")
        return jsonify(
            {
                "ok": True,
                "workflow_id": workflow_id,
                "redirect": url_for("machine_room_workflow_page"),
            }
        )

    register_sd = app.extensions.get("register_safe_delete_entity")
    if callable(register_sd):

        @register_sd("mr_media_workflow")
        def _safe_delete_describe_media_workflow(acc, entity_id: int, project_id):
            w = db.session.get(MachineRoomMediaWorkflow, int(entity_id))
            if w is None:
                return {"exists": False, "can_delete": False, "display_name": ""}
            name = f"{w.project.name if w.project else 'Project'} · {wf.format_days_label(w.days)}"
            allowed = bool(acc and (account_is_machine_room_role(acc) or _is_supervisor(acc)))
            return {"exists": True, "can_delete": allowed, "display_name": name}
