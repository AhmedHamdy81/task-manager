"""Project Working Hours routes — page, manual entry, approval, export, backfill.

All ledger logic lives in ``project_work_ledger_service``. These handlers only
resolve permissions, validate the request, and render.
"""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Any

from flask import Response, abort, flash, jsonify, redirect, render_template, request, session, url_for

import project_activity_hooks as pah
import project_work_ledger_service as pwls

BACKFILL_CONFIRM_MESSAGE = (
    "Scan ended work sessions and completed media operations and create any "
    "missing Working Hours rows? Existing rows are never duplicated or changed."
)


def register_working_hours_routes(app: Any, ctx: dict[str, Any]) -> None:
    db = ctx["db"]
    Project = ctx["Project"]
    ProjectWorkLedger = ctx["ProjectWorkLedger"]
    StudioRateCardItem = ctx.get("StudioRateCardItem")
    User = ctx["User"]
    Booking = ctx.get("Booking")
    WorkSession = ctx.get("WorkSession")
    ProjectActivityLog = ctx.get("ProjectActivityLog")
    ProjectMember = ctx.get("ProjectMember")
    EditingItem = ctx.get("EditingItem")
    ShootingDay = ctx.get("ShootingDay")
    ShootingDayScene = ctx.get("ShootingDayScene")
    VfxShot = ctx.get("VfxShot")
    now_local = ctx["now_local"]
    account_from_session = ctx["account_from_session"]
    can_view_working_hours = ctx["account_can_view_project_working_hours"]
    can_manage_working_hours = ctx["account_can_manage_project_working_hours"]
    account_can_access_admin_settings = ctx["account_can_access_admin_settings"]
    directory_user_id_for_account = ctx["directory_user_id_for_account"]
    safe_delete_request_present = ctx["safe_delete_request_present"]
    safe_delete_guard = ctx["safe_delete_guard"]
    safe_delete_service = ctx["safe_delete_service"]
    log_security_event = ctx["log_security_event"]

    import rate_card_service as rcs

    # -- shared helpers ----------------------------------------------------

    def _is_admin(acc: Any) -> bool:
        return acc is not None and bool(getattr(acc, "is_admin", False))

    def _wants_json() -> bool:
        accept = (request.headers.get("Accept") or "").lower()
        return request.is_json or "application/json" in accept

    def _page_url(project_id: int) -> str:
        return url_for("project_working_hours", project_id=project_id)

    def _deny(project_id: int | None, message: str, *, status: int = 403):
        if _wants_json():
            return jsonify({"ok": False, "error": message}), status
        flash(message, "error")
        if project_id is None:
            return redirect(url_for("projects_list"))
        return redirect(_page_url(project_id))

    def _load_project(project_id: int):
        """Return (project, account, can_manage) or raise a redirect-worthy None."""
        acc = account_from_session()
        project = Project.query.get_or_404(project_id)
        if not can_view_working_hours(acc, project.id):
            return None, acc, False
        return project, acc, bool(can_manage_working_hours(acc, project.id))

    def _entry_or_404(project_id: int, ledger_id: int):
        entry = db.session.get(ProjectWorkLedger, int(ledger_id))
        if entry is None or int(entry.project_id) != int(project_id):
            abort(404)
        return entry

    def _owns(acc: Any, entry: Any) -> bool:
        if acc is None:
            return False
        if entry.account_id and int(entry.account_id) == int(acc.id):
            return True
        uid = directory_user_id_for_account(acc)
        return bool(uid and entry.user_id and int(entry.user_id) == int(uid))

    def _project_member_users(project_id: int) -> list[Any]:
        if ProjectMember is None:
            return []
        rows = (
            db.session.query(User)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .filter(ProjectMember.project_id == int(project_id))
            .order_by(User.name.asc())
            .all()
        )
        return rows

    def _redirect_back(project_id: int, **params: Any):
        target = (request.form.get("next") or "").strip()
        if target.startswith("/") and not target.startswith("//"):
            return redirect(target)
        return redirect(url_for("project_working_hours", project_id=project_id, **params))

    # -- page --------------------------------------------------------------

    @app.route("/projects/<int:project_id>/working-hours")
    def project_working_hours(project_id: int):
        project, acc, can_manage = _load_project(project_id)
        if project is None:
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))

        viewer_user_id = directory_user_id_for_account(acc)
        # Members without approval rights only ever see their own hours.
        restrict_user_id = None if can_manage else viewer_user_id
        filters = pwls.parse_filters(request.args)
        if restrict_user_id is not None:
            filters["user_id"] = int(restrict_user_id)

        base_q = ProjectWorkLedger.query.filter(ProjectWorkLedger.project_id == int(project.id))
        if restrict_user_id is not None:
            base_q = base_q.filter(ProjectWorkLedger.user_id == int(restrict_user_id))

        # Historic copy/convert events may pre-date the ledger; pull them in
        # before totals and the approval panel so Machine Room hours are visible.
        if can_manage and ProjectActivityLog is not None:
            try:
                import project_activity_service as pas

                media_report = pwls.ensure_project_media_ledger(
                    db=db,
                    project_id=int(project.id),
                    model=ProjectWorkLedger,
                    ProjectActivityLog=ProjectActivityLog,
                    loads_json=pas.loads_json,
                    now=now_local(),
                )
                if media_report.get("media_rows_created"):
                    db.session.commit()
            except Exception:
                db.session.rollback()

        list_q = pwls.apply_filters(base_q, ProjectWorkLedger, filters)
        # The log lists signed-off hours only; anything still waiting on a
        # decision lives in the approval panel until the status filter is used.
        log_approved_only = not filters.get("status")
        if log_approved_only:
            list_q = list_q.filter(
                ProjectWorkLedger.status.in_(tuple(sorted(pwls.APPROVED_STATUSES)))
            )

        total = list_q.order_by(None).count()
        per_page = int(filters["per_page"])
        pages = max(1, math.ceil(total / per_page)) if total else 1
        page = min(int(filters["page"]), pages)
        filters["page"] = page
        ordered = pwls.order_ledger_query(list_q, ProjectWorkLedger, filters, User=User)
        rows = ordered.offset((page - 1) * per_page).limit(per_page).all()

        today = now_local().date()
        summary = pwls.summarize_project_work_hours(
            project.id, filters, model=ProjectWorkLedger, today=today, restrict_user_id=restrict_user_id
        )
        booked_minutes = pwls.summarize_booked_minutes(
            project.id,
            Booking=Booking,
            date_from=filters.get("date_from"),
            date_to=filters.get("date_to"),
            user_id=restrict_user_id,
        )

        rate_card_items = []
        if StudioRateCardItem is not None:
            created = rcs.ensure_defaults(db, StudioRateCardItem)
            created += rcs.ensure_worksheet_defaults(db, StudioRateCardItem)
            created += rcs.align_canonical_service_keys(db, StudioRateCardItem)
            if created:
                db.session.commit()
            rate_card_items = [
                rcs.serialize_item(row) for row in rcs.list_items(StudioRateCardItem)
            ]
        rate_card_work_types = rcs.work_type_choices(rate_card_items)
        pwls.set_extra_work_type_labels(rcs.work_type_label_map(rate_card_items))

        serialized = []
        for row in rows:
            payload = pwls.serialize_row(row)
            payload["can_approve"] = _may_approve(acc, row, can_manage)
            payload["can_edit_billable"] = _may_edit_billable(acc, row, can_manage)
            payload["can_delete"] = _may_delete(acc, row, can_manage)
            serialized.append(payload)
        arrange_by, include_group_headers = pwls.display_group_by(filters)
        display_rows = pwls.build_log_display_rows(
            serialized, arrange_by, include_headers=include_group_headers
        )

        pending_rows = []
        if can_manage:
            pending_rows = [
                pwls.serialize_row(r)
                for r in base_q.filter(
                    ProjectWorkLedger.status.in_(tuple(pwls.PENDING_STATUSES))
                )
                .order_by(ProjectWorkLedger.work_date.asc(), ProjectWorkLedger.id.asc())
                .limit(50)
                .all()
            ]

        def _nav(target_page: int) -> str:
            return pwls.page_url(
                "project_working_hours",
                filters,
                url_for=url_for,
                project_id=project.id,
                page=target_page,
            )

        def _sort_url(column: str) -> str:
            return pwls.page_url(
                "project_working_hours",
                filters,
                url_for=url_for,
                project_id=project.id,
                page=1,
                sort=column,
                dir=pwls.next_sort_dir(filters, column),
            )

        return render_template(
            "project_working_hours.html",
            project=project,
            workflow_active="working_hours",
            rows=serialized,
            display_rows=display_rows,
            log_approved_only=log_approved_only,
            pending_rows=pending_rows,
            filters=filters,
            summary=summary,
            booked_minutes=booked_minutes,
            booked_label=pwls.format_minutes_label(booked_minutes),
            difference_minutes=summary["actual_minutes"] - booked_minutes,
            can_manage=can_manage,
            is_admin=_is_admin(acc),
            viewer_user_id=viewer_user_id,
            today=today,
            page=page,
            pages=pages,
            total=total,
            per_page=per_page,
            page_sizes=pwls.PAGE_SIZES,
            prev_url=_nav(page - 1) if page > 1 else None,
            next_url=_nav(page + 1) if page < pages else None,
            clear_url=_page_url(project.id),
            sort_urls={
                "date": _sort_url("date"),
                "user": _sort_url("user"),
                "department": _sort_url("department"),
                "work_type": _sort_url("work_type"),
                "billable": _sort_url("billable"),
                "status": _sort_url("status"),
            },
            sort_aria={
                key: pwls.sort_aria(filters, key)
                for key in ("date", "user", "department", "work_type", "billable", "status")
            },
            group_keys=pwls.GROUP_KEYS,
            group_labels=pwls.GROUP_LABELS,
            rate_card_items=rate_card_items,
            rate_card_work_types=rate_card_work_types,
            rate_card_currency=rcs.card_currency(rate_card_items),
            rate_card_currencies=rcs.CURRENCIES,
            rate_card_export_url=url_for(
                "project_working_hours_rate_card_export", project_id=project.id
            ),
            rate_card_save_url=url_for(
                "project_working_hours_rate_card_save", project_id=project.id
            ),
            export_url=pwls.page_url(
                "project_working_hours_export",
                filters,
                url_for=url_for,
                project_id=project.id,
            ),
            daily_worksheet_export_url=pwls.page_url(
                "project_working_hours_export_daily_worksheet",
                filters,
                url_for=url_for,
                project_id=project.id,
            ),
            quotation_export_url=pwls.page_url(
                "project_working_hours_export_quotation",
                filters,
                url_for=url_for,
                project_id=project.id,
            ),
            members=_project_member_users(project.id) if can_manage else [],
            department_keys=pwls.DEPARTMENT_KEYS,
            department_labels=pwls.DEPARTMENT_LABELS,
            work_types=pwls.MANUAL_WORK_TYPES,
            work_type_labels=pwls.WORK_TYPE_LABELS,
            source_types=pwls.SOURCE_TYPES,
            source_type_labels=pwls.SOURCE_TYPE_LABELS,
            statuses=pwls.STATUSES,
            status_labels=pwls.STATUS_LABELS,
            format_minutes=pwls.format_minutes_label,
            editing_items=(
                EditingItem.query.filter_by(project_id=int(project.id), is_active=True)
                .order_by(EditingItem.sort_order.asc(), EditingItem.id.asc())
                .limit(400)
                .all()
                if EditingItem is not None
                else []
            ),
            shooting_days=(
                ShootingDay.query.filter_by(project_id=int(project.id))
                .order_by(ShootingDay.id.desc())
                .limit(400)
                .all()
                if ShootingDay is not None
                else []
            ),
            vfx_shots=(
                VfxShot.query.filter_by(project_id=int(project.id))
                .order_by(VfxShot.id.desc())
                .limit(400)
                .all()
                if VfxShot is not None
                else []
            ),
        )

    # -- permission predicates for a single row ----------------------------

    def _may_approve(acc: Any, entry: Any, can_manage: bool) -> bool:
        if not can_manage:
            return False
        if entry.status in pwls.LOCKED_STATUSES:
            return False
        if entry.status in (pwls.STATUS_CANCELLED, pwls.STATUS_FAILED, pwls.STATUS_STARTED):
            return False
        # Self-approval is an admin-only privilege.
        if _owns(acc, entry) and not _is_admin(acc):
            return False
        return True

    def _may_edit_billable(acc: Any, entry: Any, can_manage: bool) -> bool:
        if _is_admin(acc):
            return True
        if entry.status in pwls.LOCKED_STATUSES:
            return False
        if can_manage:
            return True
        return _owns(acc, entry) and entry.status in pwls.OWNER_EDITABLE_STATUSES

    def _may_delete(acc: Any, entry: Any, can_manage: bool) -> bool:
        if _is_admin(acc):
            return True
        if entry.status in pwls.LOCKED_STATUSES:
            # Deleting approved hours is an admin action.
            return False
        if entry.source_type != pwls.SOURCE_MANUAL:
            # Auto-synced rows belong to their source system.
            return False
        return _owns(acc, entry) and entry.status in pwls.OWNER_EDITABLE_STATUSES

    # -- manual hours ------------------------------------------------------

    @app.route("/projects/<int:project_id>/working-hours/manual", methods=["POST"])
    def project_working_hours_manual(project_id: int):
        acc = account_from_session()
        project = Project.query.get_or_404(project_id)
        if not can_view_working_hours(acc, project.id):
            return _deny(None, "You do not have access to that project.")
        can_manage = bool(can_manage_working_hours(acc, project.id))
        is_admin = _is_admin(acc)
        viewer_user_id = directory_user_id_for_account(acc)

        target_user_id = pwls.parse_int(request.form.get("user_id"), None) or viewer_user_id
        if target_user_id is None:
            return _deny(project.id, "Your account is not linked to a directory user.")
        if int(target_user_id) != int(viewer_user_id or 0) and not can_manage:
            return _deny(project.id, "You can only log hours for yourself.")
        if ProjectMember is not None:
            member = ProjectMember.query.filter_by(
                project_id=int(project.id), user_id=int(target_user_id)
            ).first()
            if member is None and not is_admin:
                return _deny(project.id, "That user is not a member of this project.")

        today = now_local().date()
        work_date, date_error = pwls.validate_work_date(
            request.form.get("work_date"), today=today, is_admin=is_admin
        )
        if date_error:
            return _deny(project.id, date_error, status=400)

        work_type = pwls.canonical_work_type(request.form.get("work_type"))
        rate_rows = []
        if StudioRateCardItem is not None:
            created = rcs.ensure_defaults(db, StudioRateCardItem)
            created += rcs.ensure_worksheet_defaults(db, StudioRateCardItem)
            created += rcs.align_canonical_service_keys(db, StudioRateCardItem)
            if created:
                db.session.commit()
            rate_rows = rcs.list_items(StudioRateCardItem)
        allowed_work_types = {choice["key"] for choice in rcs.work_type_choices(rate_rows)}
        allowed_work_types.update(
            key
            for choice in rcs.work_type_choices(rate_rows)
            for key in pwls.work_type_equivalent_keys(choice["key"])
        )
        if not allowed_work_types:
            return _deny(
                project.id,
                "Add at least one Rate Card service before logging hours.",
                status=400,
            )
        if work_type not in allowed_work_types:
            return _deny(project.id, "Choose a work type from the Rate Card.", status=400)
        pwls.set_extra_work_type_labels(rcs.work_type_label_map(rate_rows))
        billing_unit = rcs.billing_unit_for_work_type(rate_rows, work_type)
        allow_zero_duration = billing_unit == rcs.UNIT_FEE

        actual_minutes, duration_error = pwls.validate_work_duration(
            pwls.parse_hours_minutes(
                request.form.get("duration_hours"), request.form.get("duration_minutes")
            ),
            is_admin=is_admin,
            allow_zero=allow_zero_duration,
        )
        if duration_error:
            return _deny(project.id, duration_error, status=400)

        billable_raw = pwls.parse_hours_minutes(
            request.form.get("billable_hours"), request.form.get("billable_minutes")
        )
        if allow_zero_duration and actual_minutes == 0 and billable_raw <= 0:
            billable_minutes = 0
        else:
            billable_minutes = actual_minutes if billable_raw <= 0 else billable_raw
        if billable_minutes > actual_minutes and not can_manage and not allow_zero_duration:
            return _deny(
                project.id, "Billable hours cannot exceed the hours worked.", status=400
            )
        _, billable_error = pwls.validate_work_duration(
            billable_minutes,
            is_admin=is_admin,
            field_label="Billable duration",
            allow_zero=allow_zero_duration,
        )
        if billable_error:
            return _deny(project.id, billable_error, status=400)

        department_key = pwls.infer_department_for_work_type(work_type)
        if department_key == pwls.DEPT_OTHER:
            department_key = pwls.infer_department_from_user(
                db.session.get(User, int(target_user_id))
            )

        links, link_error = _validate_links(project.id)
        if link_error:
            return _deny(project.id, link_error, status=400)

        entry = pwls.create_manual_work_log(
            db=db,
            model=ProjectWorkLedger,
            project_id=int(project.id),
            user_id=int(target_user_id),
            account=acc if int(target_user_id) == int(viewer_user_id or 0) else None,
            created_by_account=acc,
            work_date=work_date,
            department_key=department_key,
            work_type=work_type,
            actual_minutes=actual_minutes,
            billable_minutes=billable_minutes,
            title=(request.form.get("title") or "").strip() or pwls.work_type_label(work_type),
            description=(request.form.get("description") or "").strip(),
            now=now_local(),
            **links,
        )
        db.session.flush()
        target_user = db.session.get(User, int(target_user_id))
        pah.log_working_hours_manual_created(
            entry, for_user_name=(getattr(target_user, "name", "") or "")
        )
        db.session.commit()
        if allow_zero_duration and actual_minutes == 0:
            flash(f"Logged fee entry for {pwls.work_type_label(work_type)}.", "success")
        else:
            flash(
                f"Logged {pwls.format_minutes_label(actual_minutes)} of manual hours.",
                "success",
            )
        return _redirect_back(project.id)

    def _validate_links(project_id: int) -> tuple[dict[str, Any], str | None]:
        """Resolve optional entity links, rejecting anything from another project."""
        links: dict[str, Any] = {
            "episode_id": None,
            "shooting_day_id": None,
            "scene_id": None,
            "vfx_shot_id": None,
        }
        episode_id = pwls.parse_int(request.form.get("episode_id"), None)
        if episode_id and EditingItem is not None:
            item = db.session.get(EditingItem, int(episode_id))
            if item is None or int(item.project_id) != int(project_id):
                return links, "That editing item does not belong to this project."
            links["episode_id"] = int(episode_id)

        shooting_day_id = pwls.parse_int(request.form.get("shooting_day_id"), None)
        day = None
        if shooting_day_id and ShootingDay is not None:
            day = db.session.get(ShootingDay, int(shooting_day_id))
            if day is None or int(day.project_id) != int(project_id):
                return links, "That shooting day does not belong to this project."
            links["shooting_day_id"] = int(shooting_day_id)

        scene_id = pwls.parse_int(request.form.get("scene_id"), None)
        if scene_id and ShootingDayScene is not None:
            scene = db.session.get(ShootingDayScene, int(scene_id))
            scene_day = (
                db.session.get(ShootingDay, int(scene.shooting_day_id))
                if scene is not None and ShootingDay is not None
                else None
            )
            if scene_day is None or int(scene_day.project_id) != int(project_id):
                return links, "That scene does not belong to this project."
            links["scene_id"] = int(scene_id)

        vfx_shot_id = pwls.parse_int(request.form.get("vfx_shot_id"), None)
        if vfx_shot_id and VfxShot is not None:
            shot = db.session.get(VfxShot, int(vfx_shot_id))
            if shot is None or int(shot.project_id) != int(project_id):
                return links, "That VFX shot does not belong to this project."
            links["vfx_shot_id"] = int(vfx_shot_id)
        return links, None

    # -- approval workflow -------------------------------------------------

    @app.route("/projects/<int:project_id>/working-hours/<int:ledger_id>/approve", methods=["POST"])
    def project_working_hours_approve(project_id: int, ledger_id: int):
        acc = account_from_session()
        project = Project.query.get_or_404(project_id)
        if not can_view_working_hours(acc, project.id):
            return _deny(None, "You do not have access to that project.")
        entry = _entry_or_404(project.id, ledger_id)
        can_manage = bool(can_manage_working_hours(acc, project.id))
        if not _may_approve(acc, entry, can_manage):
            return _deny(project.id, "You cannot approve this entry.")
        entry.status = pwls.STATUS_APPROVED
        entry.approved_by_account_id = int(acc.id)
        entry.approved_at = now_local()
        entry.updated_at = now_local()
        pah.log_working_hours_approved(entry)
        db.session.commit()
        return _redirect_back(project.id)

    @app.route("/projects/<int:project_id>/working-hours/<int:ledger_id>/reject", methods=["POST"])
    def project_working_hours_reject(project_id: int, ledger_id: int):
        acc = account_from_session()
        project = Project.query.get_or_404(project_id)
        if not can_view_working_hours(acc, project.id):
            return _deny(None, "You do not have access to that project.")
        entry = _entry_or_404(project.id, ledger_id)
        can_manage = bool(can_manage_working_hours(acc, project.id))
        if not _may_approve(acc, entry, can_manage):
            return _deny(project.id, "You cannot reject this entry.")
        reason = (request.form.get("reason") or "").strip()
        entry.status = pwls.STATUS_REJECTED
        entry.approved_by_account_id = int(acc.id)
        entry.approved_at = now_local()
        entry.updated_at = now_local()
        if reason:
            entry.description = (
                f"{entry.description}\n\nRejected: {reason}".strip()[: pwls.DESCRIPTION_MAX]
            )
        pah.log_working_hours_rejected(entry, reason=reason)
        db.session.commit()
        flash("Working hours rejected.", "success")
        return _redirect_back(project.id)

    @app.route(
        "/projects/<int:project_id>/working-hours/<int:ledger_id>/edit",
        methods=["POST"],
    )
    def project_working_hours_edit(project_id: int, ledger_id: int):
        acc = account_from_session()
        project = Project.query.get_or_404(project_id)
        if not can_view_working_hours(acc, project.id):
            return _deny(None, "You do not have access to that project.")
        entry = _entry_or_404(project.id, ledger_id)
        can_manage = bool(can_manage_working_hours(acc, project.id))
        if not can_manage and not _is_admin(acc):
            return _deny(project.id, "You cannot edit this entry.")
        if entry.status in pwls.LOCKED_STATUSES and not _is_admin(acc):
            return _deny(project.id, "This entry is locked.")
        if entry.status in (pwls.STATUS_CANCELLED, pwls.STATUS_FAILED):
            return _deny(project.id, "Cancelled or failed entries cannot be edited.")

        is_admin = _is_admin(acc)
        actual_minutes, duration_error = pwls.validate_work_duration(
            pwls.parse_hours_minutes(
                request.form.get("duration_hours"), request.form.get("duration_minutes")
            ),
            is_admin=is_admin,
        )
        if duration_error:
            return _deny(project.id, duration_error, status=400)

        billable_raw = pwls.parse_hours_minutes(
            request.form.get("billable_hours"), request.form.get("billable_minutes")
        )
        billable_minutes = actual_minutes if billable_raw <= 0 else billable_raw
        if billable_minutes > actual_minutes and not can_manage:
            return _deny(
                project.id, "Billable hours cannot exceed the hours worked.", status=400
            )
        _, billable_error = pwls.validate_work_duration(
            billable_minutes, is_admin=is_admin, field_label="Billable duration"
        )
        if billable_error:
            return _deny(project.id, billable_error, status=400)

        previous_billable = int(entry.billable_minutes or 0)
        title = (request.form.get("title") or "").strip()
        entry.actual_minutes = int(actual_minutes)
        entry.billable_minutes = int(billable_minutes)
        if title:
            entry.title = title[:200]
        entry.updated_at = now_local()
        if billable_minutes != previous_billable:
            pah.log_working_hours_billable_updated(
                entry, previous_minutes=previous_billable
            )
        db.session.commit()
        flash(
            f"Hours updated to {pwls.format_minutes_label(actual_minutes)}.",
            "success",
        )
        return _redirect_back(project.id)

    @app.route(
        "/projects/<int:project_id>/working-hours/<int:ledger_id>/update-billable",
        methods=["POST"],
    )
    def project_working_hours_update_billable(project_id: int, ledger_id: int):
        acc = account_from_session()
        project = Project.query.get_or_404(project_id)
        if not can_view_working_hours(acc, project.id):
            return _deny(None, "You do not have access to that project.")
        entry = _entry_or_404(project.id, ledger_id)
        can_manage = bool(can_manage_working_hours(acc, project.id))
        if not _may_edit_billable(acc, entry, can_manage):
            return _deny(project.id, "This entry is locked.")
        # Checkbox toggle: checked = billable (actual), unchecked = not billable (0).
        if request.form.get("billable_toggle"):
            minutes = (
                int(entry.actual_minutes or 0)
                if request.form.get("is_billable") == "1"
                else 0
            )
        else:
            minutes, error = pwls.validate_work_duration(
                pwls.parse_hours_minutes(
                    request.form.get("billable_hours"), request.form.get("billable_minutes")
                ),
                is_admin=_is_admin(acc),
                field_label="Billable duration",
            )
            if error:
                return _deny(project.id, error, status=400)
            if minutes > int(entry.actual_minutes or 0) and not can_manage:
                return _deny(
                    project.id, "Billable hours cannot exceed the hours worked.", status=400
                )
        previous = int(entry.billable_minutes or 0)
        if minutes == previous:
            return _redirect_back(project.id)
        entry.billable_minutes = minutes
        entry.updated_at = now_local()
        pah.log_working_hours_billable_updated(entry, previous_minutes=previous)
        db.session.commit()
        if not request.form.get("billable_toggle"):
            flash(f"Billable hours set to {pwls.format_minutes_label(minutes)}.", "success")
        return _redirect_back(project.id)

    @app.route("/projects/<int:project_id>/working-hours/<int:ledger_id>/delete", methods=["POST"])
    def project_working_hours_delete(project_id: int, ledger_id: int):
        acc = account_from_session()
        project = Project.query.get_or_404(project_id)
        if not can_view_working_hours(acc, project.id):
            return _deny(None, "You do not have access to that project.")
        entry = _entry_or_404(project.id, ledger_id)
        can_manage = bool(can_manage_working_hours(acc, project.id))
        if not _may_delete(acc, entry, can_manage):
            return _deny(project.id, "You cannot delete this entry.")
        pah.log_working_hours_deleted(entry)
        db.session.delete(entry)
        db.session.commit()
        flash("Working hours entry deleted.", "success")
        return _redirect_back(project.id)

    # -- export ------------------------------------------------------------

    @app.route("/projects/<int:project_id>/working-hours/export.csv")
    def project_working_hours_export(project_id: int):
        project, acc, can_manage = _load_project(project_id)
        if project is None:
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        restrict_user_id = None if can_manage else directory_user_id_for_account(acc)
        filters = pwls.parse_filters(request.args)
        q = ProjectWorkLedger.query.filter(ProjectWorkLedger.project_id == int(project.id))
        if restrict_user_id is not None:
            q = q.filter(ProjectWorkLedger.user_id == int(restrict_user_id))
        q = pwls.apply_filters(q, ProjectWorkLedger, filters)
        rows = q.order_by(
            ProjectWorkLedger.work_date.asc(), ProjectWorkLedger.id.asc()
        ).all()

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(pwls.CSV_HEADERS)
        for row in rows:
            writer.writerow(pwls.csv_row_values(row, project_name=project.name or ""))

        summary = pwls.summarize_rows(rows, today=now_local().date())
        for group_name, key in (
            ("department", "by_department"),
            ("user", "by_user"),
            ("work_type", "by_work_type"),
            ("source_type", "by_source_type"),
            ("week", "by_week"),
            ("month", "by_month"),
        ):
            for bucket in summary[key]:
                writer.writerow(
                    [
                        "",
                        project.name or "",
                        f"TOTAL BY {group_name.upper()}",
                        bucket["label"],
                        "",
                        "",
                        f"{bucket['entries']} entries",
                        "",
                        bucket["actual_minutes"],
                        bucket["billable_minutes"],
                        "",
                        pwls.format_hours_value(bucket["actual_minutes"]),
                        pwls.format_hours_value(bucket["billable_minutes"]),
                        "",
                        "",
                        "",
                        "",
                    ]
                )

        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", (project.name or "project")).strip("_") or "project"
        return Response(
            buffer.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{safe}_working_hours.csv"'
            },
        )

    @app.route("/projects/<int:project_id>/working-hours/export-daily-worksheet.pdf")
    def project_working_hours_export_daily_worksheet(project_id: int):
        """Managers-only Daily Worksheet PDF (approved/billable + Rate Card)."""
        import daily_worksheet_pdf_service as dws

        project, acc, can_manage = _load_project(project_id)
        if project is None:
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        if not can_manage:
            flash("Only managers can export the Daily Worksheet PDF.", "error")
            return redirect(url_for("project_working_hours", project_id=project.id))

        filters = pwls.parse_filters(request.args)
        q = ProjectWorkLedger.query.filter(ProjectWorkLedger.project_id == int(project.id))
        q = pwls.apply_filters(q, ProjectWorkLedger, filters)
        # Match Working Hours page: approved + auto_approved unless status set.
        if not filters.get("status"):
            q = q.filter(
                ProjectWorkLedger.status.in_(tuple(sorted(pwls.APPROVED_STATUSES)))
            )
        rows = q.order_by(
            ProjectWorkLedger.work_date.asc(), ProjectWorkLedger.id.asc()
        ).all()

        rate_rows = []
        if StudioRateCardItem is not None:
            created = rcs.ensure_defaults(db, StudioRateCardItem)
            created += rcs.ensure_worksheet_defaults(db, StudioRateCardItem)
            created += rcs.align_canonical_service_keys(db, StudioRateCardItem)
            if created:
                db.session.commit()
            rate_rows = rcs.list_items(StudioRateCardItem)

        worksheet_rows = dws.build_daily_worksheet_rows(rows, rate_items=rate_rows)
        wants_preview = str(request.args.get("preview") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if not worksheet_rows:
            message = (
                "No approved billable hours match the current filters for the Daily Worksheet."
            )
            if wants_preview:
                return Response(
                    dws.render_daily_worksheet_preview_error_html(message),
                    mimetype="text/html; charset=utf-8",
                    status=404,
                )
            if _wants_json():
                return jsonify({"ok": False, "error": message}), 404
            flash(message, "error")
            return redirect(
                pwls.page_url(
                    "project_working_hours",
                    filters,
                    url_for=url_for,
                    project_id=project.id,
                )
            )

        prepared_by = (request.args.get("prepared_by") or "").strip()
        if not prepared_by:
            prepared_by = (
                getattr(acc, "display_name", None)
                or getattr(acc, "email", None)
                or ""
            )
        contact = (request.args.get("contact") or "").strip()
        worksheet_date = pwls.parse_date(request.args.get("worksheet_date")) or now_local().date()
        tax_note = (request.args.get("tax_note") or "").strip() or dws.DEFAULT_TAX_NOTE
        include_tax = str(request.args.get("include_tax") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        header = dws.build_worksheet_header(
            project,
            prepared_by=prepared_by,
            contact=contact,
            worksheet_date=worksheet_date,
        )
        pdf_bytes = dws.render_daily_worksheet_pdf(
            header=header,
            rows=worksheet_rows,
            tax_note=tax_note,
            include_tax=include_tax,
        )
        safe = dws.sanitize_filename(project.name or "project")
        filename = f"{safe}_Daily_Worksheet_{worksheet_date.isoformat()}.pdf"
        if wants_preview:
            return Response(
                dws.render_daily_worksheet_preview_html(pdf_bytes),
                mimetype="text/html; charset=utf-8",
            )
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.route("/projects/<int:project_id>/working-hours/export-quotation.pdf")
    def project_working_hours_export_quotation(project_id: int):
        """Managers-only quotation PDF (approved/billable hours + Rate Card)."""
        import daily_worksheet_pdf_service as dws
        import quotation_pdf_service as qps

        project, acc, can_manage = _load_project(project_id)
        if project is None:
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        if not can_manage:
            flash("Only managers can export the quotation PDF.", "error")
            return redirect(url_for("project_working_hours", project_id=project.id))

        filters = pwls.parse_filters(request.args)
        q = ProjectWorkLedger.query.filter(ProjectWorkLedger.project_id == int(project.id))
        q = pwls.apply_filters(q, ProjectWorkLedger, filters)
        if not filters.get("status"):
            q = q.filter(
                ProjectWorkLedger.status.in_(tuple(sorted(pwls.APPROVED_STATUSES)))
            )
        rows = q.order_by(
            ProjectWorkLedger.work_date.asc(), ProjectWorkLedger.id.asc()
        ).all()

        rate_rows = []
        if StudioRateCardItem is not None:
            created = rcs.ensure_defaults(db, StudioRateCardItem)
            created += rcs.ensure_worksheet_defaults(db, StudioRateCardItem)
            created += rcs.align_canonical_service_keys(db, StudioRateCardItem)
            if created:
                db.session.commit()
            rate_rows = rcs.list_items(StudioRateCardItem)

        quote_rows = qps.build_quotation_rows(rows, rate_items=rate_rows)
        wants_preview = str(request.args.get("preview") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if not quote_rows:
            message = "No approved billable hours match the current filters for the quotation."
            if wants_preview:
                return Response(
                    qps.render_quotation_preview_error_html(message),
                    mimetype="text/html; charset=utf-8",
                    status=404,
                )
            if _wants_json():
                return jsonify({"ok": False, "error": message}), 404
            flash(message, "error")
            return redirect(
                pwls.page_url(
                    "project_working_hours",
                    filters,
                    url_for=url_for,
                    project_id=project.id,
                )
            )

        attention = (request.args.get("attention") or request.args.get("contact") or "").strip()
        quote_date = pwls.parse_date(request.args.get("quote_date")) or now_local().date()
        header = qps.build_quotation_header(
            project,
            attention=attention,
            quote_date=quote_date,
        )
        currency = rcs.card_currency(rate_rows)
        pdf_bytes = qps.render_quotation_pdf(
            header=header,
            rows=quote_rows,
            currency=currency,
        )
        safe = dws.sanitize_filename(project.name or "project")
        filename = f"{safe}_Quotation_{quote_date.isoformat()}.pdf"
        if wants_preview:
            return Response(
                qps.render_quotation_preview_html(pdf_bytes),
                mimetype="text/html; charset=utf-8",
            )
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # -- rate card ---------------------------------------------------------

    @app.route("/projects/<int:project_id>/working-hours/rate-card", methods=["POST"])
    def project_working_hours_rate_card_save(project_id: int):
        project, acc, can_manage = _load_project(project_id)
        if project is None:
            return _deny(None, "You do not have access to that project.")
        if not can_manage:
            return _deny(project.id, "Only managers can edit the rate card.")
        if StudioRateCardItem is None:
            return _deny(project.id, "Rate card is unavailable.")

        items, error = rcs.parse_items_from_form(request.form)
        if error:
            return _deny(project.id, error, status=400)
        existing = rcs.list_items(StudioRateCardItem)
        items = rcs.apply_locked_defaults(items, existing_rows=existing)
        rcs.replace_items(db, StudioRateCardItem, items or [])
        db.session.commit()
        flash("Rate card saved.", "success")
        return _redirect_back(project.id)

    @app.route(
        "/projects/<int:project_id>/working-hours/rate-card/<int:item_id>/delete",
        methods=["POST"],
    )
    def project_working_hours_rate_card_item_delete(project_id: int, item_id: int):
        project, acc, can_manage = _load_project(project_id)
        if project is None:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        if not can_manage:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        if StudioRateCardItem is None:
            return jsonify({"ok": False, "error": "unavailable"}), 400
        if not safe_delete_request_present():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "safe_delete_required",
                        "message": "Confirm with Safe Delete before removing this service.",
                    }
                ),
                400,
            )
        safe_challenge, sd_err = safe_delete_guard(
            "rate_card_item", item_id, project_id=project.id
        )
        if sd_err is not None:
            return sd_err
        remaining = StudioRateCardItem.query.count()
        if remaining <= 1:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "last_item",
                        "message": "The rate card must keep at least one service.",
                    }
                ),
                400,
            )
        removed, delete_err = rcs.delete_item(db, StudioRateCardItem, item_id)
        if delete_err == "locked_default":
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "locked_default",
                        "message": "Studio default services cannot be deleted.",
                    }
                ),
                400,
            )
        if removed is None:
            return jsonify({"ok": False, "error": "not_found", "code": "gone"}), 404
        safe_delete_service.consume(safe_challenge)
        db.session.commit()
        log_security_event(
            "safe_delete_executed",
            account_id=acc.id if acc else None,
            entity_type="rate_card_item",
            entity_id=item_id,
            project_id=project.id,
            details={
                "challenge_id": safe_challenge.id,
                "delete_kind": "permanent",
                "service_name": removed.service_name,
            },
        )
        return jsonify({"ok": True, "message": "Service removed from the rate card."})

    @app.route("/projects/<int:project_id>/working-hours/rate-card.pdf")
    def project_working_hours_rate_card_export(project_id: int):
        project, acc, can_manage = _load_project(project_id)
        if project is None:
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        if StudioRateCardItem is None:
            flash("Rate card is unavailable.", "error")
            return redirect(_page_url(project.id))
        if rcs.ensure_defaults(db, StudioRateCardItem):
            db.session.commit()
        rcs.align_canonical_service_keys(db, StudioRateCardItem)
        db.session.commit()
        rows = rcs.list_pdf_items(StudioRateCardItem)
        selected = (request.args.get("currency") or "").strip()
        currency = (
            rcs.normalize_currency(selected) if selected else rcs.card_currency(rows)
        )
        pdf_bytes = rcs.build_rate_card_pdf(rows, currency=currency)
        filename = f"RATE_CARD_{currency}_{rcs.RATE_CARD_YEAR}.pdf"
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    # -- backfill ----------------------------------------------------------

    def _run_backfill(limit: int | None = None) -> dict[str, int]:
        import project_activity_service as pas

        now = now_local()
        report = {
            "sessions_scanned": 0,
            "session_rows_created": 0,
            "media_events_scanned": 0,
            "media_rows_created": 0,
            "skipped_duplicates": 0,
            "errors": 0,
        }
        session_report = pwls.backfill_from_sessions(
            db=db, model=ProjectWorkLedger, WorkSession=WorkSession, now=now, limit=limit
        )
        db.session.commit()
        media_report = pwls.backfill_from_activity_log(
            db=db,
            model=ProjectWorkLedger,
            ProjectActivityLog=ProjectActivityLog,
            loads_json=pas.loads_json,
            now=now,
            limit=limit,
        )
        db.session.commit()
        for source in (session_report, media_report):
            for key, value in source.items():
                report[key] = report.get(key, 0) + int(value)
        return report

    @app.route("/control/working-hours/backfill", methods=["POST"])
    def control_working_hours_backfill():
        acc = account_from_session()
        if not account_can_access_admin_settings(acc):
            abort(403)
        report = _run_backfill()
        if _wants_json():
            return jsonify({"ok": True, **report})
        session["working_hours_backfill_report"] = report
        flash(
            (
                "Working Hours backfill complete: "
                f"{report['sessions_scanned']} sessions scanned, "
                f"{report['session_rows_created']} session rows created, "
                f"{report['media_events_scanned']} media events scanned, "
                f"{report['media_rows_created']} media rows created, "
                f"{report['skipped_duplicates']} duplicates skipped, "
                f"{report['errors']} errors."
            ),
            "success" if not report["errors"] else "warning",
        )
        return redirect(url_for("control_system_setup"))

    @app.cli.command("backfill-working-hours")
    def backfill_working_hours_command() -> None:
        """Create missing ProjectWorkLedger rows from sessions and media events."""
        report = _run_backfill()
        for key in (
            "sessions_scanned",
            "session_rows_created",
            "media_events_scanned",
            "media_rows_created",
            "skipped_duplicates",
            "errors",
        ):
            print(f"{key}: {report[key]}")

    app.extensions.setdefault("working_hours", {})["backfill"] = _run_backfill
    app.extensions["working_hours"]["confirm_message"] = BACKFILL_CONFIRM_MESSAGE
