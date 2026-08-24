"""Routes for user registration approval and role-change requests."""

from __future__ import annotations

import json
from datetime import datetime
from flask import flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload

import account_approval_support as aas
import workflow_engine as workflow_engine_mod
import workflow_types as workflow_types_mod
from user_role_mapping import role_label


def register_account_approval_routes(app, ctx: dict) -> None:
    db = ctx["db"]
    Account = ctx["Account"]
    User = ctx["User"]
    JobTitle = ctx["JobTitle"]
    UserApprovalRequest = ctx["UserApprovalRequest"]
    RoleChangeRequest = ctx["RoleChangeRequest"]
    AccountApprovalAuditLog = ctx["AccountApprovalAuditLog"]
    ReactivationRequest = ctx.get("ReactivationRequest")
    PermissionChangeRequest = ctx.get("PermissionChangeRequest")
    ApprovalRequest = ctx.get("ApprovalRequest")
    ApprovalRequestEvent = ctx.get("ApprovalRequestEvent")
    ROLE_ADMIN = ctx["ROLE_ADMIN"]
    ROLE_GUEST = ctx["ROLE_GUEST"]
    GUEST_ACCESS_VIEWER = ctx["GUEST_ACCESS_VIEWER"]
    account_from_session = ctx["account_from_session"]
    account_can_access_admin_settings = ctx["account_can_access_admin_settings"]
    directory_user_id_for_account = ctx["directory_user_id_for_account"]
    set_user_job_titles = ctx["set_user_job_titles"]
    log_security_event = ctx["log_security_event"]
    create_notification = ctx["create_notification"]
    emit_notification_to_account = ctx.get("emit_notification_to_account")
    send_managed_notification = ctx["send_managed_notification"]
    workflow_engine = ctx["workflow_engine"]
    now_local = ctx["now_local"]

    from notification_service import NotificationService

    notification_service = NotificationService(
        send_managed_notification=send_managed_notification,
        create_notification=create_notification,
        emit_notification_to_account=emit_notification_to_account,
        admin_directory_user_ids_fn=lambda: aas.admin_directory_user_ids(
            db, Account, User, ROLE_ADMIN
        ),
        now_local_fn=now_local,
    )

    notify_ctx = {
        "db": db,
        "Account": Account,
        "User": User,
        "ROLE_ADMIN": ROLE_ADMIN,
        "create_notification": create_notification,
        "emit_notification_to_account": emit_notification_to_account,
    }

    def _require_admin():
        actor = account_from_session()
        if not account_can_access_admin_settings(actor):
            flash("Only administrators can access approvals.", "error")
            return None
        return actor

    def _notify_user_account_event(event_type: str, acc, *, actor=None, context: dict | None = None):
        uid = directory_user_id_for_account(acc)
        if uid is None:
            return
        notification_service.notify(
            event_type,
            actor=actor,
            target_user_id=int(uid),
            recipient="user",
            context=context or {},
        )

    def _approval_request_for_legacy(legacy_type: str, legacy_id: int):
        if ApprovalRequest is None:
            return None
        return (
            ApprovalRequest.query.filter_by(
                legacy_request_type=(legacy_type or "").strip(),
                legacy_request_id=int(legacy_id),
            )
            .order_by(ApprovalRequest.id.desc())
            .first()
        )

    def _approval_request_or_404(request_id: int):
        if ApprovalRequest is None:
            raise ValueError("Workflow engine is not configured")
        row = db.session.get(ApprovalRequest, int(request_id))
        if row is None:
            from flask import abort

            abort(404)
        return row

    def _filter_slug_from_request_type(request_type: str) -> str:
        category = workflow_types_mod.request_type_category(request_type)
        if request_type == workflow_types_mod.REQUEST_TYPE_USER_REGISTRATION:
            return "registration"
        if request_type == workflow_types_mod.REQUEST_TYPE_ROLE_CHANGE:
            return "role_changes"
        if request_type == workflow_types_mod.REQUEST_TYPE_PERMISSION_CHANGE:
            return "permissions"
        if request_type == workflow_types_mod.REQUEST_TYPE_ACCOUNT_REACTIVATION:
            return "registration"
        return category

    @app.route("/account/pending")
    def account_pending():
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login"))
        if aas.account_may_use_app(acc):
            return redirect(url_for("index"))
        return render_template(
            "account_pending.html",
            account=acc,
            status_label=aas.status_label(getattr(acc, "status", None)),
        )

    @app.route("/account/support")
    def account_support():
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login"))
        return render_template("account_support.html", account=acc)

    @app.route("/account/reactivation-request", methods=["POST"])
    def account_reactivation_request():
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login"))
        if ReactivationRequest is None:
            flash("Reactivation workflow is not configured.", "error")
            return redirect(url_for("account_pending"))
        if not acc.status or aas.normalized_account_status(acc.status) not in (
            aas.STATUS_SUSPENDED,
            aas.STATUS_DISABLED,
        ):
            flash("Reactivation requests are only available for suspended/disabled accounts.", "error")
            return redirect(url_for("account_pending"))

        reason = (request.form.get("reason") or "").strip()
        notes = (request.form.get("notes") or "").strip() or None
        if not reason:
            flash("Reason is required.", "error")
            return redirect(url_for("account_pending"))

        existing = ReactivationRequest.query.filter_by(
            account_id=int(acc.id), status=aas.REQUEST_PENDING
        ).first()
        if existing is not None:
            flash("A reactivation request is already pending.", "warning")
            return redirect(url_for("account_pending"))

        prev_status = aas.normalized_account_status(getattr(acc, "status", None))
        req = ReactivationRequest(
            account_id=int(acc.id),
            status=aas.REQUEST_PENDING,
            previous_status=prev_status,
            reason=reason,
            admin_notes=notes,
        )
        db.session.add(req)
        db.session.flush()

        # Mark the account as awaiting reactivation approval (still restricted).
        acc.status = aas.STATUS_PENDING_REACTIVATION
        acc.is_active = False
        acc.status_notes = reason
        workflow_engine.create_request(
            request_type=workflow_types_mod.REQUEST_TYPE_ACCOUNT_REACTIVATION,
            created_by=acc,
            target_user_id=directory_user_id_for_account(acc),
            title=f"Reactivation: {acc.email}",
            description="Account reactivation request awaiting review.",
            payload={
                "account_id": int(acc.id),
                "previous_status": prev_status,
                "reason": reason,
                "notes": notes,
            },
            priority=workflow_types_mod.PRIORITY_HIGH,
            legacy_request_type="reactivation_request",
            legacy_request_id=int(req.id),
            request=request,
            replace_existing_pending=True,
        )

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="reactivation_requested",
            actor_account_id=None,
            target_account_id=acc.id,
            old_values={"status": prev_status},
            new_values={"status": acc.status},
            entity_type="reactivation_request",
            entity_id=req.id,
            request=request,
            notes=reason,
        )
        log_security_event(
            "reactivation_request_created",
            account_id=None,
            entity_type="account",
            entity_id=acc.id,
            details={},
        )
        db.session.commit()

        flash("Reactivation request submitted.", "success")
        return redirect(url_for("account_pending"))

    @app.route("/admin/accounts/<int:account_id>/suspend", methods=["POST"])
    def admin_suspend_account(account_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        acc = db.session.get(Account, account_id)
        if acc is None:
            flash("Account not found.", "error")
            return redirect(url_for("users_list"))

        reason = (request.form.get("reason") or "").strip()
        end_date_raw = (request.form.get("end_date") or "").strip()
        notes = (request.form.get("notes") or "").strip() or None
        if not reason:
            flash("Suspension reason is required.", "error")
            return redirect(url_for("users_list"))

        end_at = None
        if end_date_raw:
            try:
                end_at = datetime.fromisoformat(end_date_raw)
            except Exception:
                end_at = None

        old_status = getattr(acc, "status", None)
        acc.status = aas.STATUS_SUSPENDED
        acc.is_active = False
        acc.suspension_reason = reason
        acc.suspension_end_at = end_at
        acc.disable_reason = None
        acc.disable_notes = None
        acc.status_notes = notes or reason
        db.session.commit()

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="account_suspended",
            actor_account_id=actor.id,
            target_account_id=acc.id,
            old_values={"status": old_status},
            new_values={
                "status": acc.status,
                "suspension_reason": reason,
                "suspension_end_at": str(end_at) if end_at else None,
            },
            entity_type="account",
            entity_id=acc.id,
            request=request,
            notes=reason,
        )
        log_security_event(
            "account_suspended",
            account_id=actor.id,
            entity_type="account",
            entity_id=acc.id,
            details={},
        )
        db.session.commit()

        notification_service.notify(
            "ACCOUNT_SUSPENDED",
            actor=actor,
            recipient="user",
            target_user_id=directory_user_id_for_account(acc),
            context={"reason": reason, "end_date": str(end_at.date()) if end_at else ""},
        )
        db.session.commit()

        flash("Account suspended.", "success")
        return redirect(url_for("users_list"))

    @app.route("/admin/accounts/<int:account_id>/disable", methods=["POST"])
    def admin_disable_account(account_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        acc = db.session.get(Account, account_id)
        if acc is None:
            flash("Account not found.", "error")
            return redirect(url_for("users_list"))

        confirm = (request.form.get("confirm") or "").strip().lower()
        reason = (request.form.get("reason") or "").strip()
        notes = (request.form.get("notes") or "").strip() or None

        if confirm not in ("1", "true", "on", "yes"):
            flash("Disable requires confirmation.", "error")
            return redirect(url_for("users_list"))

        old_status = getattr(acc, "status", None)
        acc.status = aas.STATUS_DISABLED
        acc.is_active = False
        acc.disable_reason = reason or None
        acc.disable_notes = notes
        acc.suspension_reason = None
        acc.suspension_end_at = None
        acc.status_notes = notes or reason or None
        db.session.commit()

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="account_disabled",
            actor_account_id=actor.id,
            target_account_id=acc.id,
            old_values={"status": old_status},
            new_values={
                "status": acc.status,
                "disable_reason": reason or None,
            },
            entity_type="account",
            entity_id=acc.id,
            request=request,
            notes=reason or "disabled",
        )
        log_security_event(
            "account_disabled",
            account_id=actor.id,
            entity_type="account",
            entity_id=acc.id,
            details={},
        )
        db.session.commit()

        notification_service.notify(
            "ACCOUNT_DISABLED",
            actor=actor,
            recipient="user",
            target_user_id=directory_user_id_for_account(acc),
            context={"reason": reason or ""},
        )
        db.session.commit()

        flash("Account disabled.", "success")
        return redirect(url_for("users_list"))

    @app.route(
        "/admin/approvals/reactivation-requests/<int:request_id>/approve",
        methods=["POST"],
    )
    def admin_approve_reactivation(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_for_legacy("reactivation_request", request_id)
        if approval_request is not None:
            return admin_approve_approval_request(int(approval_request.id))
        if ReactivationRequest is None:
            flash("Reactivation workflow is not configured.", "error")
            return redirect(url_for("admin_approvals", tab="reactivation_requests"))

        req = ReactivationRequest.query.get_or_404(request_id)
        if req.status != aas.REQUEST_PENDING:
            flash("This reactivation request is no longer pending.", "error")
            return redirect(url_for("admin_approvals", tab="reactivation_requests"))

        acc = db.session.get(Account, req.account_id)
        if acc is None:
            flash("Account not found.", "error")
            return redirect(url_for("admin_approvals", tab="reactivation_requests"))

        old_status = getattr(acc, "status", None)

        acc.status = aas.STATUS_ACTIVE
        acc.is_active = True
        acc.status_notes = None
        acc.suspension_reason = None
        acc.suspension_end_at = None
        acc.disable_reason = None
        acc.disable_notes = None
        acc.approved_by_account_id = actor.id
        acc.approved_at = now_local()

        req.status = aas.REQUEST_APPROVED
        req.reviewed_by_account_id = actor.id
        req.reviewed_at = now_local()

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="reactivation_approved",
            actor_account_id=actor.id,
            target_account_id=acc.id,
            old_values={"status": old_status},
            new_values={"status": acc.status},
            entity_type="reactivation_request",
            entity_id=req.id,
            request=request,
            notes=req.reason,
            target_user_id=getattr(acc, "directory_user_id", None),
        )
        log_security_event(
            "reactivation_approved",
            account_id=actor.id,
            entity_type="account",
            entity_id=acc.id,
            details={},
        )

        db.session.commit()

        notification_service.notify(
            "ACCOUNT_REACTIVATED",
            actor=actor,
            recipient="user",
            target_user_id=directory_user_id_for_account(acc),
        )

        flash("Reactivation approved.", "success")
        return redirect(url_for("admin_approvals", tab="reactivation_requests"))

    @app.route(
        "/admin/approvals/reactivation-requests/<int:request_id>/reject",
        methods=["POST"],
    )
    def admin_reject_reactivation(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_for_legacy("reactivation_request", request_id)
        if approval_request is not None:
            return admin_reject_approval_request(int(approval_request.id))
        if ReactivationRequest is None:
            flash("Reactivation workflow is not configured.", "error")
            return redirect(url_for("admin_approvals", tab="reactivation_requests"))

        req = ReactivationRequest.query.get_or_404(request_id)
        if req.status != aas.REQUEST_PENDING:
            flash("This reactivation request is no longer pending.", "error")
            return redirect(url_for("admin_approvals", tab="reactivation_requests"))

        acc = db.session.get(Account, req.account_id)
        if acc is None:
            flash("Account not found.", "error")
            return redirect(url_for("admin_approvals", tab="reactivation_requests"))

        old_status = getattr(acc, "status", None)
        prev_status = req.previous_status or old_status

        acc.status = aas.normalized_account_status(prev_status)
        acc.is_active = acc.status == aas.STATUS_ACTIVE
        # Keep existing restriction fields; we only clear status_notes for clarity.
        acc.status_notes = None

        notes = (request.form.get("admin_notes") or "").strip() or req.admin_notes

        req.status = aas.REQUEST_REJECTED
        req.reviewed_by_account_id = actor.id
        req.reviewed_at = now_local()
        req.admin_notes = notes

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="reactivation_rejected",
            actor_account_id=actor.id,
            target_account_id=acc.id,
            old_values={"status": old_status},
            new_values={"status": acc.status},
            entity_type="reactivation_request",
            entity_id=req.id,
            request=request,
            notes=notes,
        )
        log_security_event(
            "reactivation_rejected",
            account_id=actor.id,
            entity_type="account",
            entity_id=acc.id,
            details={},
        )

        db.session.commit()

        notification_service.notify(
            "ACCOUNT_REACTIVATION_REJECTED",
            actor=actor,
            recipient="user",
            target_user_id=directory_user_id_for_account(acc),
            context={"reason": notes or req.reason or ""},
        )

        flash("Reactivation rejected.", "success")
        return redirect(url_for("admin_approvals", tab="reactivation_requests"))

    @app.route(
        "/admin/approvals/permission-requests/<int:request_id>/approve",
        methods=["POST"],
    )
    def admin_approve_permission_change(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_for_legacy("permission_change_request", request_id)
        if approval_request is not None:
            return admin_approve_approval_request(int(approval_request.id))
        if PermissionChangeRequest is None:
            flash("Permission workflow is not configured.", "error")
            return redirect(url_for("admin_approvals", tab="permission_requests"))

        req = PermissionChangeRequest.query.get_or_404(request_id)
        if req.status != aas.REQUEST_PENDING:
            flash("This permission request is no longer pending.", "error")
            return redirect(url_for("admin_approvals", tab="permission_requests"))

        acc = db.session.get(Account, req.account_id)
        if acc is None:
            flash("Account not found.", "error")
            return redirect(url_for("admin_approvals", tab="permission_requests"))

        notes = (request.form.get("admin_notes") or "").strip() or None
        payload = {}
        try:
            payload = json.loads(req.requested_values_json or "{}") or {}
        except Exception:
            payload = {}

        old_status = getattr(acc, "status", None)

        user = User.query.filter_by(account_id=acc.id).first()
        if user is not None and isinstance(payload.get("job_title_ids"), list):
            try:
                ids = [int(x) for x in payload.get("job_title_ids") or [] if str(x).strip()]
            except Exception:
                ids = []
            if ids:
                set_user_job_titles(user, ids)

        role = (payload.get("role") or acc.role or "").strip().lower()
        if role:
            acc.role = role
        if acc.role == ROLE_GUEST:
            acc.guest_access_level = payload.get(
                "guest_access_level", ctx.get("GUEST_ACCESS_VIEWER", GUEST_ACCESS_VIEWER)
            )
        else:
            acc.guest_access_level = GUEST_ACCESS_VIEWER

        if user is not None:
            if payload.get("department_code") is not None:
                user.department_code = payload.get("department_code")
            if payload.get("company") is not None:
                user.company = payload.get("company")
            if payload.get("employment_type_code") is not None:
                user.employment_type_code = payload.get("employment_type_code")

        acc.status = aas.STATUS_ACTIVE
        acc.is_active = True
        acc.approved_by_account_id = actor.id
        acc.approved_at = now_local()
        acc.status_notes = notes

        req.status = aas.REQUEST_APPROVED
        req.reviewed_by_account_id = actor.id
        req.reviewed_at = now_local()
        req.admin_notes = notes

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="permission_change_approved",
            actor_account_id=actor.id,
            target_account_id=acc.id,
            target_user_id=user.id if user is not None else None,
            old_values={"status": old_status},
            new_values={"status": acc.status, "role": acc.role},
            entity_type="permission_change_request",
            entity_id=req.id,
            request=request,
            notes=notes,
        )
        log_security_event(
            "permission_change_approved",
            account_id=actor.id,
            entity_type="account",
            entity_id=acc.id,
            details={},
        )

        db.session.commit()

        notification_service.notify(
            "PERMISSION_CHANGE_APPROVED",
            actor=actor,
            recipient="user",
            target_user_id=directory_user_id_for_account(acc),
        )

        flash("Permission request approved.", "success")
        return redirect(url_for("admin_approvals", tab="permission_requests"))

    @app.route(
        "/admin/approvals/permission-requests/<int:request_id>/reject",
        methods=["POST"],
    )
    def admin_reject_permission_change(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_for_legacy("permission_change_request", request_id)
        if approval_request is not None:
            return admin_reject_approval_request(int(approval_request.id))
        if PermissionChangeRequest is None:
            flash("Permission workflow is not configured.", "error")
            return redirect(url_for("admin_approvals", tab="permission_requests"))

        req = PermissionChangeRequest.query.get_or_404(request_id)
        if req.status != aas.REQUEST_PENDING:
            flash("This permission request is no longer pending.", "error")
            return redirect(url_for("admin_approvals", tab="permission_requests"))

        acc = db.session.get(Account, req.account_id)
        if acc is None:
            flash("Account not found.", "error")
            return redirect(url_for("admin_approvals", tab="permission_requests"))

        notes = (request.form.get("admin_notes") or "").strip() or None
        old_status = getattr(acc, "status", None)

        req.status = aas.REQUEST_REJECTED
        req.reviewed_by_account_id = actor.id
        req.reviewed_at = now_local()
        req.admin_notes = notes

        # Reject keeps existing approved values; bring status back to active access.
        acc.status = aas.STATUS_ACTIVE
        acc.is_active = True
        acc.status_notes = None
        acc.approved_by_account_id = actor.id
        acc.approved_at = now_local()

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="permission_change_rejected",
            actor_account_id=actor.id,
            target_account_id=acc.id,
            old_values={"status": old_status},
            new_values={"status": acc.status},
            entity_type="permission_change_request",
            entity_id=req.id,
            request=request,
            notes=notes,
        )
        log_security_event(
            "permission_change_rejected",
            account_id=actor.id,
            entity_type="account",
            entity_id=acc.id,
            details={},
        )

        db.session.commit()

        notification_service.notify(
            "PERMISSION_CHANGE_REJECTED",
            actor=actor,
            recipient="user",
            target_user_id=directory_user_id_for_account(acc),
            context={"reason": notes or ""},
        )

        flash("Permission request rejected.", "success")
        return redirect(url_for("admin_approvals", tab="permission_requests"))

    @app.route("/admin/approvals")
    def admin_approvals():
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        filter_key = (request.args.get("filter") or "").strip().lower()
        tab = (request.args.get("tab") or "").strip().lower()
        legacy_to_filter = {
            "pending_users": "registration",
            "role_requests": "role_changes",
            "permission_requests": "permissions",
            "reactivation_requests": "registration",
            "suspended": "all",
        }
        if not filter_key:
            filter_key = legacy_to_filter.get(tab, "pending")
        valid_filters = {k for k, _label in workflow_types_mod.FILTER_SPECS}
        if filter_key not in valid_filters:
            filter_key = "pending"

        query = (
            ApprovalRequest.query.options(
                joinedload(ApprovalRequest.target_user),
                joinedload(ApprovalRequest.created_by),
                joinedload(ApprovalRequest.approved_by),
                joinedload(ApprovalRequest.rejected_by),
            )
            .order_by(ApprovalRequest.requested_at.desc(), ApprovalRequest.id.desc())
        )
        if filter_key == "pending":
            query = query.filter(ApprovalRequest.status == workflow_types_mod.STATUS_PENDING)
        rows = [row for row in query.all() if workflow_engine_mod.request_filter_match(row, filter_key)]
        job_titles = JobTitle.query.filter_by(is_active=True).order_by(JobTitle.name).all()
        counts = aas.approval_queue_counts(
            db,
            Account,
            UserApprovalRequest,
            RoleChangeRequest,
            ReactivationRequest=ReactivationRequest,
            PermissionChangeRequest=PermissionChangeRequest,
            ApprovalRequest=ApprovalRequest,
        )
        request_meta = {}
        for row in rows:
            payload = row.payload_data()
            request_meta[int(row.id)] = {
                "label": workflow_types_mod.request_type_label(row.request_type),
                "category": workflow_types_mod.request_type_category(row.request_type),
                "summary": workflow_engine_mod.request_payload_summary(row),
                "payload": payload,
                "target_account": (
                    db.session.get(Account, int(row.target_user.account_id))
                    if getattr(getattr(row, "target_user", None), "account_id", None)
                    else (
                        db.session.get(Account, int(payload.get("account_id")))
                        if str(payload.get("account_id") or "").isdigit()
                        else None
                    )
                ),
            }
        return render_template(
            "admin_approvals.html",
            filter_key=filter_key,
            filter_specs=workflow_types_mod.FILTER_SPECS,
            requests=rows,
            request_meta=request_meta,
            job_titles=job_titles,
            account_roles=ctx["ACCOUNT_ROLES"],
            role_labels=ctx.get("ROLE_LABELS", {}),
            counts=counts,
            status_label=aas.status_label,
            status_badge_class=aas.status_badge_class,
            role_label_fn=role_label,
        )

    @app.route("/admin/approvals/<int:request_id>")
    def admin_approval_request_detail(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_or_404(request_id)
        workflow_engine.record_view(approval_request, actor=actor, request=request)
        db.session.commit()
        events = (
            ApprovalRequestEvent.query.filter_by(approval_request_id=int(approval_request.id))
            .order_by(ApprovalRequestEvent.created_at.asc(), ApprovalRequestEvent.id.asc())
            .all()
        )
        timeline_items = []
        index = 0
        while index < len(events):
            event = events[index]
            if event.event_type == "viewed":
                end = index
                while end < len(events) and events[end].event_type == "viewed":
                    end += 1
                last = events[end - 1]
                count = end - index
                timeline_items.append(
                    {
                        "event_type": "viewed",
                        "title": f"Viewed {count} times" if count > 1 else "Viewed",
                        "created_at": last.created_at,
                        "actor_name": last.actor.display_name if last.actor else "System",
                        "notes": None,
                        "latest": count > 1,
                    }
                )
                index = end
                continue
            timeline_items.append(
                {
                    "event_type": event.event_type,
                    "title": (event.event_type or "").replace("_", " ").title(),
                    "created_at": event.created_at,
                    "actor_name": event.actor.display_name if event.actor else "System",
                    "notes": event.notes,
                    "latest": False,
                }
            )
            index += 1
        return render_template(
            "approval_request_detail.html",
            approval_request=approval_request,
            events=timeline_items,
            request_meta={
                "label": workflow_types_mod.request_type_label(approval_request.request_type),
                "category": workflow_types_mod.request_type_category(approval_request.request_type),
                "summary": workflow_engine_mod.request_payload_summary(approval_request),
                "payload": approval_request.payload_data(),
            },
            role_label_fn=role_label,
        )

    @app.route("/admin/approvals/<int:request_id>/approve", methods=["POST"])
    def admin_approve_approval_request(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_or_404(request_id)
        approval_data = {
            "job_title_id": request.form.get("job_title_id") or None,
            "access_role": (request.form.get("access_role") or "").strip().lower() or None,
            "department_code": (request.form.get("department_code") or "").strip() or None,
            "company": (request.form.get("company") or "").strip() or None,
            "employment_type_code": (request.form.get("employment_type_code") or "").strip() or None,
            "admin_notes": (request.form.get("admin_notes") or "").strip() or None,
        }
        approval_data = {k: v for k, v in approval_data.items() if v not in (None, "")}
        try:
            workflow_engine.approve_request(
                approval_request,
                actor=actor,
                approval_data=approval_data,
                request=request,
            )
        except ValueError as exc:
            db.session.rollback()
            message = str(exc).strip()
            if message == "Request is not pending" or not message:
                message = "This request is no longer pending."
            flash(message, "error")
            return redirect(
                url_for("admin_approvals", filter=_filter_slug_from_request_type(approval_request.request_type))
            )
        db.session.commit()
        flash(f"{workflow_types_mod.request_type_label(approval_request.request_type)} completed.", "success")
        return redirect(url_for("admin_approvals", filter=_filter_slug_from_request_type(approval_request.request_type)))

    @app.route("/admin/approvals/<int:request_id>/reject", methods=["POST"])
    def admin_reject_approval_request(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_or_404(request_id)
        reason = (request.form.get("admin_notes") or request.form.get("reason") or "").strip() or None
        try:
            workflow_engine.reject_request(
                approval_request,
                actor=actor,
                reason=reason,
                request=request,
            )
        except ValueError as exc:
            db.session.rollback()
            message = str(exc).strip()
            if message == "Request is not pending" or not message:
                message = "This request is no longer pending."
            flash(message, "error")
            return redirect(
                url_for("admin_approvals", filter=_filter_slug_from_request_type(approval_request.request_type))
            )
        db.session.commit()
        flash(f"{workflow_types_mod.request_type_label(approval_request.request_type)} rejected.", "success")
        return redirect(url_for("admin_approvals", filter=_filter_slug_from_request_type(approval_request.request_type)))

    @app.route("/admin/approvals/users/<int:request_id>/approve", methods=["POST"])
    def admin_approve_user(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_for_legacy("user_approval_request", request_id)
        if approval_request is not None:
            return admin_approve_approval_request(int(approval_request.id))
        req = UserApprovalRequest.query.get_or_404(request_id)
        if req.status != aas.REQUEST_PENDING:
            flash("This registration request is no longer pending.", "error")
            return redirect(url_for("admin_approvals", tab="pending_users"))

        acc = db.session.get(Account, req.account_id)
        user = db.session.get(User, req.user_id)
        if acc is None or user is None:
            flash("Account or user record missing.", "error")
            return redirect(url_for("admin_approvals"))

        old = {"status": getattr(acc, "status", None), "role": acc.role}
        jt_id = request.form.get("job_title_id") or req.requested_job_title_id
        role = (request.form.get("access_role") or acc.role or ctx["ROLE_USER"]).strip().lower()
        if role not in ctx["ACCOUNT_ROLES"]:
            flash("Invalid access role.", "error")
            return redirect(url_for("admin_approvals", tab="pending_users"))

        dept = (request.form.get("department_code") or req.department_code or "").strip() or None
        company = (request.form.get("company") or req.company or "").strip() or None
        notes = (request.form.get("admin_notes") or "").strip() or None

        if jt_id:
            set_user_job_titles(user, [str(jt_id)])
        if dept:
            user.department_code = dept
        if company:
            user.company = company

        acc.role = role
        if role == ROLE_GUEST:
            acc.guest_access_level = ctx.get("GUEST_ACCESS_VIEWER", GUEST_ACCESS_VIEWER)
        acc.status = aas.STATUS_ACTIVE
        acc.is_active = True
        acc.approved_by_account_id = actor.id
        acc.approved_at = now_local()
        acc.status_notes = notes

        req.status = aas.REQUEST_APPROVED
        req.reviewed_by_account_id = actor.id
        req.reviewed_at = now_local()
        req.admin_notes = notes

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="registration_approved",
            actor_account_id=actor.id,
            target_account_id=acc.id,
            target_user_id=user.id,
            entity_type="user_approval_request",
            entity_id=req.id,
            old_values=old,
            new_values={
                "status": acc.status,
                "role": acc.role,
                "job_title_id": user.job_title_id,
                "department_code": user.department_code,
            },
            request=request,
            notes=notes,
        )
        log_security_event(
            "registration_approved",
            account_id=actor.id,
            entity_type="account",
            entity_id=acc.id,
            details={"user_id": user.id},
        )
        db.session.commit()

        jt_name = user.job_title.name if user.job_title else "—"
        _notify_user_account_event(
            "USER_APPROVED",
            acc,
            actor=actor,
            context={
                "assigned_job_title": jt_name,
                "assigned_access_role": role_label(acc.role),
                "department": (user.department_code or "—").replace("_", " ").title(),
            },
        )
        db.session.commit()
        flash(f"Approved {user.name}.", "success")
        return redirect(url_for("admin_approvals", tab="pending_users"))

    @app.route("/admin/approvals/users/<int:request_id>/reject", methods=["POST"])
    def admin_reject_user(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_for_legacy("user_approval_request", request_id)
        if approval_request is not None:
            return admin_reject_approval_request(int(approval_request.id))
        req = UserApprovalRequest.query.get_or_404(request_id)
        if req.status != aas.REQUEST_PENDING:
            flash("This registration request is no longer pending.", "error")
            return redirect(url_for("admin_approvals", tab="pending_users"))

        acc = db.session.get(Account, req.account_id)
        user = db.session.get(User, req.user_id)
        notes = (request.form.get("admin_notes") or "").strip() or None

        if acc is not None:
            acc.status = aas.STATUS_REJECTED
            acc.is_active = False
            acc.status_notes = notes
        req.status = aas.REQUEST_REJECTED
        req.reviewed_by_account_id = actor.id
        req.reviewed_at = now_local()
        req.admin_notes = notes

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="registration_rejected",
            actor_account_id=actor.id,
            target_account_id=acc.id if acc else None,
            target_user_id=user.id if user else None,
            entity_type="user_approval_request",
            entity_id=req.id,
            request=request,
            notes=notes,
        )
        db.session.commit()

        if acc is not None:
            _notify_user_account_event(
                "USER_REJECTED",
                acc,
                actor=actor,
                context={"reason": notes or ""},
            )
            db.session.commit()

        flash("Registration rejected.", "success")
        return redirect(url_for("admin_approvals", tab="pending_users"))

    @app.route("/admin/approvals/roles/<int:request_id>/approve", methods=["POST"])
    def admin_approve_role_change(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_for_legacy("role_change_request", request_id)
        if approval_request is not None:
            return admin_approve_approval_request(int(approval_request.id))
        req = RoleChangeRequest.query.get_or_404(request_id)
        if req.status != aas.ROLE_REQUEST_PENDING:
            flash("This role change request is no longer pending.", "error")
            return redirect(url_for("admin_approvals", tab="role_requests"))

        acc = db.session.get(Account, req.account_id)
        user = db.session.get(User, req.user_id)
        if acc is None or user is None:
            flash("Account or user missing.", "error")
            return redirect(url_for("admin_approvals"))

        old = aas.profile_snapshot(user, acc)
        jt_id = request.form.get("job_title_id") or req.requested_job_title_id
        role = (request.form.get("access_role") or req.suggested_access_role or acc.role).strip().lower()
        if role not in ctx["ACCOUNT_ROLES"]:
            flash("Invalid access role.", "error")
            return redirect(url_for("admin_approvals", tab="role_requests"))

        dept = (request.form.get("department_code") or req.requested_department_code or "").strip() or None
        company = (request.form.get("company") or req.requested_company or "").strip() or None
        emp = (request.form.get("employment_type_code") or req.requested_employment_type_code or "").strip() or None
        notes = (request.form.get("admin_notes") or "").strip() or None

        if jt_id:
            set_user_job_titles(user, [str(jt_id)])
        if dept is not None:
            user.department_code = dept or None
        if company is not None:
            user.company = company or None
        if emp is not None:
            user.employment_type_code = emp or None

        acc.role = role
        if role == ROLE_GUEST:
            acc.guest_access_level = ctx.get("GUEST_ACCESS_VIEWER", GUEST_ACCESS_VIEWER)

        acc.status = aas.STATUS_ACTIVE
        acc.is_active = True
        acc.approved_by_account_id = actor.id
        acc.approved_at = now_local()
        acc.status_notes = notes

        req.status = aas.ROLE_REQUEST_APPROVED
        req.reviewed_by_account_id = actor.id
        req.reviewed_at = now_local()
        req.admin_notes = notes

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="role_change_approved",
            actor_account_id=actor.id,
            target_account_id=acc.id,
            target_user_id=user.id,
            entity_type="role_change_request",
            entity_id=req.id,
            old_values=old,
            new_values=aas.profile_snapshot(user, acc),
            request=request,
            notes=notes,
        )
        db.session.commit()

        jt_name = user.job_title.name if user.job_title else "—"
        _notify_user_account_event(
            "ROLE_CHANGE_APPROVED",
            acc,
            actor=actor,
            context={
                "assigned_job_title": jt_name,
                "assigned_access_role": role_label(acc.role),
                "department": (user.department_code or "—").replace("_", " ").title(),
            },
        )
        db.session.commit()
        flash("Role change approved.", "success")
        return redirect(url_for("admin_approvals", tab="role_requests"))

    @app.route("/admin/approvals/roles/<int:request_id>/reject", methods=["POST"])
    def admin_reject_role_change(request_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        approval_request = _approval_request_for_legacy("role_change_request", request_id)
        if approval_request is not None:
            return admin_reject_approval_request(int(approval_request.id))
        req = RoleChangeRequest.query.get_or_404(request_id)
        if req.status != aas.ROLE_REQUEST_PENDING:
            flash("This role change request is no longer pending.", "error")
            return redirect(url_for("admin_approvals", tab="role_requests"))

        acc = db.session.get(Account, req.account_id)
        notes = (request.form.get("admin_notes") or "").strip() or None
        req.status = aas.ROLE_REQUEST_REJECTED
        req.reviewed_by_account_id = actor.id
        req.reviewed_at = now_local()
        req.admin_notes = notes

        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="role_change_rejected",
            actor_account_id=actor.id,
            target_account_id=req.account_id,
            target_user_id=req.user_id,
            entity_type="role_change_request",
            entity_id=req.id,
            request=request,
            notes=notes,
        )
        db.session.commit()

        if acc is not None:
            acc.status = aas.STATUS_ACTIVE
            acc.is_active = True
            acc.approved_by_account_id = actor.id
            acc.approved_at = now_local()
            acc.status_notes = None
            _notify_user_account_event(
                "ROLE_CHANGE_REJECTED",
                acc,
                actor=actor,
                context={"reason": notes or ""},
            )
            db.session.commit()

        flash("Role change rejected.", "success")
        return redirect(url_for("admin_approvals", tab="role_requests"))

    @app.route("/admin/approvals/accounts/<int:account_id>/reactivate", methods=["POST"])
    def admin_reactivate_account(account_id: int):
        actor = _require_admin()
        if actor is None:
            return redirect(url_for("index"))
        acc = db.session.get(Account, account_id)
        if acc is None:
            flash("Account not found.", "error")
            return redirect(url_for("admin_approvals", tab="suspended"))
        old_status = getattr(acc, "status", None)
        acc.status = aas.STATUS_ACTIVE
        acc.is_active = True
        acc.status_notes = None
        aas.write_approval_audit(
            db,
            AccountApprovalAuditLog,
            action="reactivation",
            actor_account_id=actor.id,
            target_account_id=acc.id,
            old_values={"status": old_status},
            new_values={"status": acc.status},
            request=request,
        )
        db.session.commit()
        _notify_user_account_event(
            "ACCOUNT_REACTIVATED",
            acc,
            actor=actor,
        )
        db.session.commit()
        flash("Account reactivated.", "success")
        return redirect(url_for("admin_approvals", tab="suspended"))

    @app.route("/admin/approvals/counts.json")
    def admin_approvals_counts_json():
        actor = account_from_session()
        if not account_can_access_admin_settings(actor):
            return jsonify({"ok": False}), 403
        return jsonify(
            {
                "ok": True,
                "counts": aas.approval_queue_counts(
                    db,
                    Account,
                    UserApprovalRequest,
                    RoleChangeRequest,
                    ReactivationRequest=ReactivationRequest,
                    PermissionChangeRequest=PermissionChangeRequest,
                    ApprovalRequest=ApprovalRequest,
                ),
            }
        )
