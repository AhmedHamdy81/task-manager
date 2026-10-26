"""Routes and shared account-aware service for shooting-day material registration."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from flask import Flask, abort, jsonify, request, url_for
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import machine_room_dashboard_support as mr_support
import machine_room_media_workflow_support as wf
import material_registration_support as reg_support


def register_material_registration_routes(app: Flask, ctx: dict) -> SimpleNamespace:
    db = ctx["db"]
    now_local = ctx["now_local"]
    today_fn = ctx["today_fn"]
    Project = ctx["Project"]
    ShootingDay = ctx["ShootingDay"]
    User = ctx["User"]
    mr_models = ctx["machine_room_dashboard_models"]
    StorageVolume = mr_models.StorageVolume
    StorageVolumeProjectLink = mr_models.StorageVolumeProjectLink
    MachineRoomAuditLog = mr_models.MachineRoomAuditLog
    account_from_session = ctx["account_from_session"]
    account_is_machine_room_role = ctx["account_is_machine_room_role"]
    account_is_elevated = ctx["account_is_elevated"]
    account_is_producerish = ctx["account_is_producerish"]
    visible_project_ids_for_account = ctx["visible_project_ids_for_account"]
    account_can_access_project = ctx["account_can_access_project"]
    account_may_edit_production_for = ctx["account_may_edit_production_for"]
    directory_user_id_for_account = ctx["directory_user_id_for_account"]
    send_managed_notification = ctx.get("send_managed_notification")
    notification_push_realtime_for_project = ctx.get("notification_push_realtime_for_project")

    wf_models = app.extensions["mr_media_workflow_models"]
    Registration = reg_support.register_material_registration_model(db, now_local)
    service = reg_support.RegistrationService(
        db=db,
        ShootingDay=ShootingDay,
        Project=Project,
        User=User,
        StorageVolume=StorageVolume,
        StorageVolumeShootingDayUsage=mr_models.StorageVolumeShootingDayUsage,
        MediaIngestBatch=mr_models.MediaIngestBatch,
        HardDiskUsage=ctx.get("HardDiskUsage"),
        Workflow=wf_models.MachineRoomMediaWorkflow,
        WorkflowDay=wf_models.MachineRoomMediaWorkflowDay,
        Registration=Registration,
        today_fn=today_fn,
    )

    # --- Permissions ---------------------------------------------------------

    def can_view(acc) -> bool:
        """Machine Room operators and their supervisors (same set that runs the workflow)."""
        if acc is None:
            return False
        if account_is_machine_room_role(acc) or account_is_elevated(acc):
            return True
        try:
            return bool(account_is_producerish(acc))
        except Exception:
            return False

    def can_register(acc, project_id: int) -> bool:
        return can_view(acc) and account_can_access_project(acc, int(project_id))

    def can_edit_date(acc, project_id: int) -> bool:
        if not can_register(acc, project_id):
            return False
        if account_is_elevated(acc):
            return True
        return bool(account_may_edit_production_for(acc, int(project_id)))

    def _scope(acc, project_id: int | None = None):
        """Project ids the account may see (None = every project), or False for no access."""
        if not can_view(acc):
            return False
        if project_id is not None:
            return {int(project_id)} if account_can_access_project(acc, int(project_id)) else False
        vis = visible_project_ids_for_account(acc)
        return None if vis is None else set(vis)

    def rows_for_account(acc, project_id: int | None = None) -> list[dict]:
        scope = _scope(acc, project_id)
        if scope is False:
            return []
        return service.statuses(project_ids=scope)

    def queue_for_account(acc, project_id: int | None = None) -> list[dict]:
        return [r for r in rows_for_account(acc, project_id) if r["needs_registration"]]

    def summary_for_account(acc, project_id: int | None = None) -> dict:
        return reg_support.summarize(rows_for_account(acc, project_id))

    def day_statuses_for_current(project_id) -> dict[int, dict]:
        """Production cards: {} for accounts that do not handle registration."""
        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            return {}
        acc = account_from_session()
        return {r["shooting_day_id"]: r for r in rows_for_account(acc, pid)}

    app.jinja_env.globals["mr_reg_day_statuses"] = day_statuses_for_current
    app.jinja_env.globals["mr_reg_status_labels"] = reg_support.STATUS_LABELS

    api = SimpleNamespace(
        service=service,
        Registration=Registration,
        can_view=can_view,
        can_register=can_register,
        rows_for_account=rows_for_account,
        queue_for_account=queue_for_account,
        summary_for_account=summary_for_account,
        summarize=reg_support.summarize,
    )
    app.extensions["material_registration"] = api

    # --- Helpers -------------------------------------------------------------

    def _json_error(message: str, status: int = 400):
        return jsonify({"ok": False, "error": message}), status

    def _day_or_404(day_id: int):
        day = db.session.get(ShootingDay, int(day_id))
        if day is None:
            abort(404)
        return day

    def _require(acc, day) -> None:
        if acc is None:
            abort(401)
        if not can_register(acc, int(day.project_id)):
            abort(403)

    def _volume_options(project_id: int) -> list[dict]:
        linked = {
            int(link.volume_id)
            for link in StorageVolumeProjectLink.query.filter_by(project_id=int(project_id)).all()
        }
        out = []
        for v in StorageVolume.query.all():
            out.append(
                {
                    "id": int(v.id),
                    "name": (v.display_name or v.name or "").strip() or f"Volume #{v.id}",
                    "role": mr_support.normalize_storage_role(v.storage_role),
                    "role_label": mr_support.storage_role_label(v.storage_role),
                    "linked": int(v.id) in linked,
                    "mounted": (v.mounted_status or "") == "mounted",
                    "mount_path": (v.mount_path or "").strip(),
                    "browse_url": url_for("machine_room_volume_browse", volume_id=int(v.id)),
                }
            )
        out.sort(key=lambda o: (not o["linked"], o["role"] != wf.ROLE_SHUTTLE, o["name"].lower()))
        return out

    def _operator_options(acc, current_id: int | None) -> list[dict]:
        users = User.query.filter(User.account_id.isnot(None)).order_by(User.name.asc()).all()
        keep = {current_id, directory_user_id_for_account(acc)}
        out = []
        for u in users:
            account = getattr(u, "account", None)
            if u.id in keep or (account is not None and account_is_machine_room_role(account)):
                out.append({"id": int(u.id), "name": u.name or u.email or f"User {u.id}"})
        if current_id and all(o["id"] != current_id for o in out):
            u = db.session.get(User, int(current_id))
            if u is not None:
                out.append({"id": int(u.id), "name": u.name or f"User {u.id}"})
        return out

    def _form_values(row: dict, reg) -> dict:
        f = row["fields"]
        return {
            "video_state": f["video"]["state"],
            "video_size_tb": f["video"]["size"],
            "audio_state": f["audio"]["state"],
            "audio_size_gb": f["audio"]["size"],
            "material_source": f["material_source"]["value"],
            "source_volume_id": f["source"]["volume_id"],
            "source_label": f["source"]["label"],
            "source_path": row["source_path"],
            "responsible_user_id": f["operator"]["user_id"],
            "notes": row["notes"],
            "origins": {k: f[k].get("origin", "") for k in reg_support.REQUIRED_FIELDS},
        }

    def _audit(acc, action: str, reg, detail: str) -> None:
        db.session.add(
            MachineRoomAuditLog(
                account_id=int(acc.id) if acc else None,
                action=action,
                entity_type="material_registration",
                entity_id=int(reg.id),
                detail=detail[:4000],
                created_at=now_local(),
            )
        )

    def _log_book(day, event_type: str, action: str, reg, changes: dict | None = None) -> None:
        try:
            import project_activity_events as pae
            import project_activity_hooks as pah

            label = reg_support.day_label(day)
            pah._log(
                project_id=int(day.project_id),
                event_type=event_type,
                module=pae.MODULE_MEDIA,
                action=action,
                entity_type="material_registration",
                entity_id=int(reg.id),
                entity_label=label,
                changes=changes or None,
                metadata={
                    "shooting_day_id": int(day.id),
                    "shooting_day_label": label,
                    **reg_support.registration_snapshot(reg),
                },
                status=pae.STATUS_COMPLETED,
            )
        except Exception:
            app.logger.exception("Material registration Log Book entry failed")

    def _notify_registered(acc, day, reg, row: dict) -> None:
        if send_managed_notification is None:
            return
        project = db.session.get(Project, int(day.project_id))
        if project is None:
            return
        label = reg_support.day_label(day)
        f = row["fields"]
        title = f"{project.name or 'Project'} · {label}: Material registered"
        body = (
            f"Video {f['video']['display']}, audio {f['audio']['display']}, "
            f"source {f['source']['display']}. Copying has not started yet."
        )
        recipients = [
            int(uid)
            for (uid,) in db.session.execute(
                text("SELECT user_id FROM project_members WHERE project_id = :pid"),
                {"pid": int(day.project_id)},
            )
            if uid is not None
        ]
        try:
            sent = send_managed_notification(
                reg_support.NOTIFY_EVENT_KEY,
                project=project,
                actor=acc,
                context={
                    "notification_title": title,
                    "notification_body": body,
                    "notification_severity": "info",
                    "entity_type": "shooting_day",
                    "entity_id": int(day.id),
                    "rule_entity_id": int(reg.id),
                    "shooting_day": label,
                    "registration_id": int(reg.id),
                },
                fallback_title=title,
                fallback_body=body,
                fallback_recipient_user_ids=recipients,
            )
            if sent and notification_push_realtime_for_project:
                notification_push_realtime_for_project(int(day.project_id), actor=acc)
        except Exception:
            app.logger.exception("Material registration notification failed")

    def _parse(data: dict, day) -> tuple[dict, str]:
        video_state, video_tb, err = reg_support.parse_media(
            data.get("video_state"), data.get("video_size_tb"), unit="video"
        )
        if err:
            return {}, err
        audio_state, audio_gb, err = reg_support.parse_media(
            data.get("audio_state"), data.get("audio_size_gb"), unit="audio"
        )
        if err:
            return {}, err
        source = str(data.get("material_source") or "").strip()
        if source and source not in reg_support.MATERIAL_SOURCE_LABELS:
            return {}, "Unknown material source."
        vol = None
        raw_vol = data.get("source_volume_id")
        if raw_vol not in (None, "", 0, "0"):
            try:
                vol = db.session.get(StorageVolume, int(raw_vol))
            except (TypeError, ValueError):
                vol = None
            if vol is None:
                return {}, "Select a configured source volume."
        label = str(data.get("source_label") or "").strip()
        if len(label) > 160:
            return {}, "Source disk name is too long (160 characters max)."
        path, err = wf.validate_destination_path(
            data.get("source_path"),
            (vol.mount_path or "") if vol is not None else "",
            wf.volume_label(vol) if vol is not None else "source",
        )
        if err:
            return {}, err.replace("Destination", "Source")
        operator = None
        raw_op = data.get("responsible_user_id")
        if raw_op not in (None, "", 0, "0"):
            try:
                operator = db.session.get(User, int(raw_op))
            except (TypeError, ValueError):
                operator = None
            if operator is None:
                return {}, "Select a valid responsible operator."
        notes = str(data.get("notes") or "").strip()
        if len(notes) > 4000:
            return {}, "Notes are too long (4000 characters max)."
        new_date = None
        raw_date = str(data.get("shooting_date") or "").strip()
        if raw_date:
            try:
                new_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                return {}, "Enter a valid shooting date."
        return {
            "video_state": video_state,
            "video_size_tb": video_tb,
            "audio_state": audio_state,
            "audio_size_gb": audio_gb,
            "material_source": source,
            "source_volume_id": int(vol.id) if vol is not None else None,
            "source_label": label if vol is None else "",
            "source_path": path,
            "responsible_user_id": int(operator.id) if operator is not None else None,
            "notes": notes,
            "shooting_date": new_date,
        }, ""

    def _apply(acc, day, values: dict) -> tuple[Any, dict, dict | None]:
        """Write the registration (and permitted date change). Returns (reg, changes, day_change)."""
        reg = Registration.query.filter_by(shooting_day_id=int(day.id)).first()
        if reg is None:
            reg = Registration(project_id=int(day.project_id), shooting_day_id=int(day.id))
            db.session.add(reg)
        before = reg_support.registration_snapshot(reg) if reg.id else {}
        for key in (
            "video_state",
            "video_size_tb",
            "audio_state",
            "audio_size_gb",
            "material_source",
            "source_volume_id",
            "source_label",
            "source_path",
            "responsible_user_id",
            "notes",
        ):
            setattr(reg, key, values[key])
        reg.updated_by_account_id = int(acc.id)
        reg.updated_at = now_local()
        after = reg_support.registration_snapshot(reg)
        changes = {k: {"old": before.get(k), "new": v} for k, v in after.items() if before.get(k) != v}
        day_change = None
        if values["shooting_date"] and values["shooting_date"] != day.shooting_date:
            import project_activity_service as pas

            day_before = pas.shooting_day_snapshot(day)
            day.shooting_date = values["shooting_date"]
            day_change = (day_before, pas.shooting_day_snapshot(day))
        return reg, changes, day_change

    # --- Routes --------------------------------------------------------------

    @app.route("/machine-room/material-registration/<int:day_id>")
    def material_registration_detail(day_id: int):
        acc = account_from_session()
        day = _day_or_404(day_id)
        _require(acc, day)
        row = service.status_for_day(day_id)
        reg = Registration.query.filter_by(shooting_day_id=int(day_id)).first()
        values = _form_values(row, reg)
        project = db.session.get(Project, int(day.project_id))
        return jsonify(
            {
                "ok": True,
                "day": {
                    "id": int(day.id),
                    "project_id": int(day.project_id),
                    "project_name": project.name if project else "",
                    "unit_number": int(day.unit_number or 1),
                    "day_name": day.day_name or "",
                    "label": reg_support.day_label(day),
                    "shooting_date": day.shooting_date.isoformat() if day.shooting_date else "",
                },
                "status": {
                    "key": row["status"],
                    "label": row["status_label"],
                    "missing": row["missing_labels"],
                    "complete": row["complete"],
                    "upcoming": row["upcoming"],
                    "protection": row["protection"],
                    "completed_at": row["completed_at"],
                },
                "values": values,
                "can_edit_date": can_edit_date(acc, int(day.project_id)),
                "workflow": (
                    {
                        "id": row["workflow_id"],
                        "label": row["workflow_label"],
                        "url": url_for("machine_room_workflow_page", workflow_id=row["workflow_id"]),
                    }
                    if row["workflow_id"]
                    else None
                ),
                "options": {
                    "material_sources": [
                        {"key": k, "label": v} for k, v in reg_support.MATERIAL_SOURCES
                    ],
                    "volumes": _volume_options(int(day.project_id)),
                    "operators": _operator_options(acc, values["responsible_user_id"]),
                    "default_operator_id": directory_user_id_for_account(acc),
                },
            }
        )

    @app.route("/machine-room/material-registration/<int:day_id>", methods=["POST"])
    def material_registration_save(day_id: int):
        acc = account_from_session()
        day = _day_or_404(day_id)
        _require(acc, day)
        data = request.get_json(silent=True) or {}
        action = str(data.get("action") or "save").strip().lower()
        if action not in ("save", "start"):
            return _json_error("Unknown action.")
        values, err = _parse(data, day)
        if err:
            return _json_error(err)
        if values["shooting_date"] and values["shooting_date"] != day.shooting_date:
            if not can_edit_date(acc, int(day.project_id)):
                return _json_error("You do not have permission to change the shooting date.", 403)

        for attempt in (1, 2):
            try:
                reg, changes, day_change = _apply(acc, day, values)
                db.session.commit()
                break
            except IntegrityError:
                # Another request created this day's registration first; update that row instead.
                db.session.rollback()
                day = _day_or_404(day_id)
                if attempt == 2:
                    raise

        if day_change is not None:
            try:
                import project_activity_hooks as pah

                pah.log_shooting_day_updated(day, day_change[0], day_change[1])
            except Exception:
                app.logger.exception("Shooting day date change log failed")

        row = service.status_for_day(day_id)
        completed_now = False
        if row["complete"]:
            uid = directory_user_id_for_account(acc)
            stamp = now_local()
            # Only the request that flips completed_at from NULL notifies, so repeated
            # clicks or concurrent saves cannot send the completion twice.
            result = db.session.execute(
                text(
                    f"UPDATE {reg_support.TABLE_NAME} SET completed_at = :ts, "
                    "completed_by_user_id = :uid, completed_by_account_id = :aid "
                    "WHERE id = :id AND completed_at IS NULL"
                ),
                {"ts": stamp, "uid": uid, "aid": int(acc.id), "id": int(reg.id)},
            )
            completed_now = bool(result.rowcount)
        if completed_now:
            _audit(acc, "material_registration_completed", reg, f"{reg_support.day_label(day)}: registration completed")
            db.session.commit()
            db.session.refresh(reg)
            import project_activity_events as pae

            _log_book(day, pae.MEDIA_REGISTRATION_COMPLETED, "completed", reg, changes)
            _notify_registered(acc, day, reg, row)
        elif changes:
            _audit(acc, "material_registration_saved", reg, f"{reg_support.day_label(day)}: registration updated")
            db.session.commit()
            import project_activity_events as pae

            _log_book(day, pae.MEDIA_REGISTRATION_UPDATED, "updated", reg, changes)
        row = service.status_for_day(day_id)

        payload: dict[str, Any] = {
            "ok": True,
            "status": {
                "key": row["status"],
                "label": row["status_label"],
                "missing": row["missing_labels"],
                "complete": row["complete"],
            },
            "completed_now": completed_now,
            "workflow_id": row["workflow_id"],
        }
        if action == "start":
            start = app.extensions.get("mr_media_workflow_start")
            if start is None:
                return _json_error("The media workflow is not available.", 503)
            existing = wf.find_workflow_for_day(wf_models, int(day.project_id), int(day.id))
            created = False
            if existing is None:
                shuttle_id = None
                vol = db.session.get(StorageVolume, reg.source_volume_id) if reg.source_volume_id else None
                if (
                    vol is not None
                    and vol.storage_role == wf.ROLE_SHUTTLE
                    and StorageVolumeProjectLink.query.filter_by(
                        volume_id=int(vol.id), project_id=int(day.project_id)
                    ).first()
                    is not None
                ):
                    shuttle_id = int(vol.id)
                try:
                    existing, created = start(
                        acc,
                        int(day.project_id),
                        [day],
                        operator_user_id=reg.responsible_user_id,
                        shuttle_volume_id=shuttle_id,
                        receive_notes=reg.notes or "",
                    )
                except wf.WorkflowDayConflict as exc:
                    other_id = next(iter(exc.conflicts.values()))
                    existing = db.session.get(wf_models.MachineRoomMediaWorkflow, other_id)
            payload.update(
                {
                    "workflow_id": int(existing.id),
                    "workflow_created": created,
                    "redirect": url_for("machine_room_workflow_page", workflow_id=int(existing.id)),
                }
            )
        return jsonify(payload)

    return api
