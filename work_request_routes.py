"""Internal Request Management routes — list, create, detail, status transitions."""

from __future__ import annotations

from typing import Any

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

import project_activity_events as pae
import project_activity_hooks as pah
import work_request_support as wrs


def register_work_request_routes(app, ctx: dict[str, Any]) -> None:
    db = ctx["db"]
    Account = ctx["Account"]
    User = ctx["User"]
    Project = ctx["Project"]
    ProjectMember = ctx["ProjectMember"]
    Task = ctx["Task"]
    ProductionEpisode = ctx["ProductionEpisode"]
    ProductionScene = ctx["ProductionScene"]
    WorkRequest = ctx["WorkRequest"]
    WorkRequestEvent = ctx["WorkRequestEvent"]
    now_local = ctx["now_local"]
    account_from_session = ctx["account_from_session"]
    directory_user_id_for_account = ctx["directory_user_id_for_account"]
    visible_project_ids_for_account = ctx["visible_project_ids_for_account"]
    send_managed_notification = ctx["send_managed_notification"]
    format_datetime_cairo = ctx.get("format_datetime_cairo")
    perm_svc = ctx["perm_svc"]

    PAGE_SIZE = 40

    def _projects_for(acc, vis):
        q = Project.query.order_by(Project.sort_order.asc(), Project.id.asc())
        if vis is not None:
            if not vis:
                return []
            q = q.filter(Project.id.in_(list(vis)))
        return q.all()

    def _users_for_projects(vis) -> list:
        if vis is not None and not vis:
            return []
        q = User.query.options(joinedload(User.job_title)).order_by(User.name)
        if vis is None:
            return q.all()
        member_ids = {
            pm.user_id
            for pm in ProjectMember.query.filter(ProjectMember.project_id.in_(list(vis))).all()
        }
        if not member_ids:
            return []
        return q.filter(User.id.in_(member_ids)).all()

    def _user_project_ids(vis) -> dict[int, list[int]]:
        q = ProjectMember.query
        if vis is not None:
            if not vis:
                return {}
            q = q.filter(ProjectMember.project_id.in_(list(vis)))
        out: dict[int, list[int]] = {}
        for pm in q.all():
            out.setdefault(int(pm.user_id), []).append(int(pm.project_id))
        return out

    def _can_view_all(acc) -> bool:
        return perm_svc.can(acc, "requests", "view_all") or perm_svc.can(acc, "requests", "edit")

    def _can_see_row(acc, row, uid: int | None, vis) -> bool:
        if row is None or row.archived:
            return False
        if vis is not None:
            if row.project_id is None:
                pass
            elif int(row.project_id) not in vis:
                return False
        if _can_view_all(acc):
            return True
        if uid is None:
            return False
        return int(row.requested_by_id or 0) == int(uid) or int(row.assigned_to_id or 0) == int(uid)

    def _can_edit_row(acc, row, uid: int | None) -> bool:
        if perm_svc.can(acc, "requests", "edit"):
            return True
        if uid is None:
            return False
        owner = int(row.requested_by_id or 0)
        return perm_svc.can(acc, "requests", "edit_own", owner_user_id=owner)

    def _can_change_status(acc, row, uid: int | None) -> bool:
        if perm_svc.can(acc, "requests", "edit_status") or perm_svc.can(acc, "requests", "edit"):
            if _can_view_all(acc) or _can_edit_row(acc, row, uid):
                return True
            if uid is not None and int(row.assigned_to_id or 0) == int(uid):
                return True
            if uid is not None and int(row.requested_by_id or 0) == int(uid):
                return True
        return _can_edit_row(acc, row, uid)

    def _can_reopen(acc, row, uid: int | None) -> bool:
        return perm_svc.can(acc, "requests", "edit") or _can_edit_row(acc, row, uid)

    def _can_assign(acc, row, uid: int | None) -> bool:
        return perm_svc.can(acc, "requests", "assign") or _can_edit_row(acc, row, uid)

    def _can_delete(acc, row, uid: int | None) -> bool:
        if perm_svc.can(acc, "requests", "delete"):
            return True
        if uid is None:
            return False
        return perm_svc.can(
            acc, "requests", "delete_own", owner_user_id=int(row.requested_by_id or 0)
        )

    def _member_ok(project_id: int | None, user_id: int | None) -> bool:
        if project_id is None or user_id is None:
            return True
        return (
            ProjectMember.query.filter_by(project_id=int(project_id), user_id=int(user_id)).first()
            is not None
        )

    def _load_row(request_id: int):
        return (
            WorkRequest.query.options(
                joinedload(WorkRequest.project),
                joinedload(WorkRequest.requester),
                joinedload(WorkRequest.assignee),
                joinedload(WorkRequest.related_task),
                joinedload(WorkRequest.related_episode),
                joinedload(WorkRequest.related_scene),
                joinedload(WorkRequest.events).joinedload(WorkRequestEvent.actor),
            )
            .filter_by(id=int(request_id))
            .first()
        )

    def _add_event(row, *, event_type: str, actor_uid: int | None, body: str = "", metadata: dict | None = None):
        ev = WorkRequestEvent(
            request_id=int(row.id),
            event_type=event_type,
            body=(body or "").strip(),
            actor_user_id=actor_uid,
            created_at=now_local(),
            metadata_json=None,
        )
        if metadata:
            import json

            ev.metadata_json = json.dumps(metadata, default=str)
        db.session.add(ev)
        return ev

    def _notify(event_key: str, row, actor, *, comment: str = "", previous_status: str = ""):
        project = row.project
        if project is None and row.project_id:
            project = db.session.get(Project, int(row.project_id))
        actor_uid = directory_user_id_for_account(actor) if actor is not None else None
        href = url_for("request_detail", request_id=int(row.id))
        ctx_n = {
            "request_id": int(row.id),
            "request_title": row.title or "",
            "request_status": row.status or "",
            "request_priority": row.priority or "",
            "previous_status": previous_status,
            "comment": comment or "",
            "assigned_user_id": row.assigned_to_id,
            "requested_by_id": row.requested_by_id,
            "project_id": int(row.project_id) if row.project_id else "",
            "project_name": (project.name if project is not None else "No project"),
        }
        fallback_ids = wrs.recipient_user_ids(row, actor_uid)
        titles = {
            "work_request_assigned": f"A new request was assigned to you: {row.title}",
            "work_request_started": f"{ctx_n.get('actor_name', 'Someone')} started request: {row.title}",
            "work_request_finished": f"{ctx_n.get('actor_name', 'Someone')} finished request: {row.title}",
            "work_request_failed": f"{ctx_n.get('actor_name', 'Someone')} marked request as failed: {row.title}",
            "work_request_reopened": f"{ctx_n.get('actor_name', 'Someone')} reopened request: {row.title}",
        }
        bodies = {
            "work_request_assigned": f"A new request was assigned to you: {row.title}.",
            "work_request_started": f"Request “{row.title}” is now started.",
            "work_request_finished": f"Request “{row.title}” is finished.{(' ' + comment) if comment else ''}",
            "work_request_failed": f"Request “{row.title}” failed.{(' Reason: ' + comment) if comment else ''}",
            "work_request_reopened": f"Request “{row.title}” was reopened and is pending again.",
        }
        try:
            send_managed_notification(
                event_key,
                project=project,
                actor=actor,
                context=ctx_n,
                fallback_title=titles.get(event_key, row.title),
                fallback_body=bodies.get(event_key, row.title),
                fallback_url=href,
                fallback_recipient_user_ids=fallback_ids,
            )
        except Exception:
            app.logger.exception("work request notification failed for %s", event_key)

    def _log_activity(row, event_type: str, action: str, extra: dict | None = None):
        if not row.project_id:
            return
        meta = {
            "request_id": int(row.id),
            "request_title": row.title,
            "status": row.status,
            **(extra or {}),
        }
        pah._log(
            project_id=int(row.project_id),
            event_type=event_type,
            module=pae.MODULE_REQUESTS,
            action=action,
            entity_type="work_request",
            entity_id=int(row.id),
            entity_label=row.title or f"Request {row.id}",
            metadata=meta,
            status=pae.STATUS_COMPLETED,
        )

    @app.route("/requests")
    def requests_page():
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login", next=url_for("requests_page")))
        if not perm_svc.can(acc, "requests", "view"):
            abort(403)
        uid = directory_user_id_for_account(acc)
        vis = visible_project_ids_for_account(acc)
        view_all = _can_view_all(acc)

        status = wrs.normalize_status(request.args.get("status"))
        priority = (request.args.get("priority") or "").strip().lower()
        if priority not in wrs.PRIORITIES:
            priority = None
        request_type = wrs.normalize_request_type(request.args.get("type"))
        project_id = wrs.parse_optional_int(request.args.get("project_id"))
        requester_id = wrs.parse_optional_int(request.args.get("requester_id"))
        assignee_id = wrs.parse_optional_int(request.args.get("assignee_id"))
        search = (request.args.get("q") or "").strip()
        sort = (request.args.get("sort") or "updated").strip().lower()
        if sort not in wrs.SORT_KEYS:
            sort = "updated"
        direction = (request.args.get("dir") or "desc").strip().lower()
        if direction not in ("asc", "desc"):
            direction = "desc"
        try:
            page = max(1, int(request.args.get("page") or 1))
        except (TypeError, ValueError):
            page = 1

        q = wrs.visible_request_query(WorkRequest, vis=vis, uid=uid, view_all=view_all)
        q = wrs.apply_list_filters(
            q,
            WorkRequest,
            status=status,
            project_id=project_id,
            requester_id=requester_id,
            assignee_id=assignee_id,
            priority=priority,
            search=search,
            request_type=request_type,
        )
        q = q.options(
            joinedload(WorkRequest.project),
            joinedload(WorkRequest.requester),
            joinedload(WorkRequest.assignee),
        )
        total = q.count()
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if page > pages:
            page = pages
        rows = (
            q.order_by(wrs.sort_clause(WorkRequest, sort, direction), WorkRequest.id.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
            .all()
        )
        projects = _projects_for(acc, vis)
        users = _users_for_projects(vis)
        return render_template(
            "requests.html",
            requests=rows,
            total=total,
            page=page,
            pages=pages,
            page_size=PAGE_SIZE,
            filter_status=status or "",
            filter_priority=priority or "",
            filter_type=request_type or "",
            filter_project_id=project_id,
            filter_requester_id=requester_id,
            filter_assignee_id=assignee_id,
            filter_search=search,
            filter_sort=sort,
            filter_dir=direction,
            projects=projects,
            users=users,
            user_project_ids=_user_project_ids(vis),
            request_types=wrs.REQUEST_TYPES,
            status_labels=wrs.STATUS_LABELS,
            statuses=wrs.STATUSES,
            priorities=wrs.PRIORITIES,
            can_create=perm_svc.can(acc, "requests", "create"),
            uid=uid,
        )

    @app.route("/requests/new", methods=["POST"])
    def requests_create():
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login", next=url_for("requests_page")))
        if not perm_svc.can(acc, "requests", "create"):
            abort(403)
        uid = directory_user_id_for_account(acc)
        if uid is None:
            flash(
                "Your account is not linked to a directory user, so requests cannot be created.",
                "error",
            )
            return redirect(url_for("requests_page"))
        vis = visible_project_ids_for_account(acc)
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Enter a request title.", "error")
            return redirect(url_for("requests_page"))
        if len(title) > 200:
            flash("Title must be 200 characters or fewer.", "error")
            return redirect(url_for("requests_page"))
        description = (request.form.get("description") or "").strip()
        request_type = wrs.normalize_request_type(request.form.get("request_type")) or "general"
        priority = wrs.normalize_priority(request.form.get("priority"))
        project_id = wrs.parse_optional_int(request.form.get("project_id"))
        assigned_to_id = wrs.parse_optional_int(request.form.get("user_id") or request.form.get("assigned_to_id"))
        related_task_id = wrs.parse_optional_int(request.form.get("related_task_id"))
        related_episode_id = wrs.parse_optional_int(request.form.get("related_episode_id"))
        related_scene_id = wrs.parse_optional_int(request.form.get("related_scene_id"))

        if vis is not None and project_id is not None and int(project_id) not in vis:
            flash("You cannot create requests for that project.", "error")
            return redirect(url_for("requests_page"))
        if project_id is not None:
            project = db.session.get(Project, int(project_id))
            if project is None:
                flash("Invalid project.", "error")
                return redirect(url_for("requests_page"))
        if assigned_to_id is not None:
            assignee = db.session.get(User, int(assigned_to_id))
            if assignee is None:
                flash("Invalid assignee.", "error")
                return redirect(url_for("requests_page"))
            if not _member_ok(project_id, assigned_to_id):
                flash(
                    "Only users assigned to this project can receive requests. Add them on the project page.",
                    "error",
                )
                return redirect(url_for("requests_page"))
        if related_task_id is not None:
            task = db.session.get(Task, int(related_task_id))
            if task is None or (project_id and task.project_id and int(task.project_id) != int(project_id)):
                flash("Related task is invalid for this project.", "error")
                return redirect(url_for("requests_page"))
        if related_episode_id is not None:
            ep = db.session.get(ProductionEpisode, int(related_episode_id))
            if ep is None or (project_id and int(ep.project_id) != int(project_id)):
                flash("Related episode is invalid for this project.", "error")
                return redirect(url_for("requests_page"))
        if related_scene_id is not None:
            sc = db.session.get(ProductionScene, int(related_scene_id))
            if sc is None:
                flash("Related scene is invalid.", "error")
                return redirect(url_for("requests_page"))

        now = now_local()
        row = WorkRequest(
            title=title,
            description=description,
            request_type=request_type,
            priority=priority,
            status=wrs.STATUS_PENDING,
            project_id=project_id,
            requested_by_id=int(uid),
            assigned_to_id=assigned_to_id,
            related_task_id=related_task_id,
            related_episode_id=related_episode_id,
            related_scene_id=related_scene_id,
            estimated_duration_minutes=None,
            started_at=None,
            finished_at=None,
            failed_at=None,
            created_at=now,
            updated_at=now,
            version=1,
            archived=False,
        )
        db.session.add(row)
        try:
            db.session.flush()
            _add_event(row, event_type=wrs.EVENT_CREATED, actor_uid=int(uid), body="")
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Could not create the request. Try again.", "error")
            return redirect(url_for("requests_page"))
        _log_activity(row, pae.REQUEST_CREATED, "created")
        if assigned_to_id is not None:
            _notify("work_request_assigned", row, acc)
        flash("Request created.", "ok")
        return redirect(url_for("request_detail", request_id=int(row.id)))

    @app.route("/requests/<int:request_id>")
    def request_detail(request_id: int):
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login", next=url_for("request_detail", request_id=request_id)))
        if not perm_svc.can(acc, "requests", "view"):
            abort(403)
        uid = directory_user_id_for_account(acc)
        vis = visible_project_ids_for_account(acc)
        row = _load_row(request_id)
        if row is None or not _can_see_row(acc, row, uid, vis):
            abort(404)
        events = sorted(row.events or [], key=lambda e: (e.created_at or now_local(), e.id or 0))
        next_sts = wrs.next_actions(row.status)
        if wrs.STATUS_PENDING in next_sts and not _can_reopen(acc, row, uid):
            next_sts = [s for s in next_sts if s != wrs.STATUS_PENDING]
        can_status = _can_change_status(acc, row, uid)
        vis_projects = _projects_for(acc, vis)
        return render_template(
            "request_detail.html",
            item=row,
            events=events,
            next_statuses=next_sts if can_status else [],
            can_change_status=can_status,
            can_reopen=_can_reopen(acc, row, uid),
            can_assign=_can_assign(acc, row, uid),
            can_delete=_can_delete(acc, row, uid),
            can_edit=_can_edit_row(acc, row, uid),
            status_labels=wrs.STATUS_LABELS,
            request_type_labels=wrs.REQUEST_TYPE_LABELS,
            projects=vis_projects,
            users=_users_for_projects(vis),
            user_project_ids=_user_project_ids(vis),
            format_datetime_cairo=format_datetime_cairo,
        )

    def _transition(request_id: int, target: str):
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login", next=url_for("request_detail", request_id=request_id)))
        uid = directory_user_id_for_account(acc)
        vis = visible_project_ids_for_account(acc)
        row = _load_row(request_id)
        if row is None or not _can_see_row(acc, row, uid, vis):
            abort(404)
        if wrs.is_reopen(row.status, target):
            if not _can_reopen(acc, row, uid):
                abort(403)
        elif not _can_change_status(acc, row, uid):
            abort(403)
        comment = (request.form.get("comment") or request.form.get("reason") or "").strip()
        minutes = wrs.parse_optional_minutes(request.form.get("estimated_duration_minutes"))
        if minutes == "invalid":
            flash("Estimated duration must be a whole number of minutes.", "error")
            return redirect(url_for("request_detail", request_id=request_id))
        expected = wrs.parse_optional_int(request.form.get("version"))
        previous = row.status
        err = wrs.apply_status_transition(
            row,
            target=target,
            actor_user_id=uid,
            now=now_local(),
            estimated_minutes=minutes if isinstance(minutes, int) else None,
            comment=comment,
            expected_version=expected,
        )
        if err:
            flash(err, "error")
            return redirect(url_for("request_detail", request_id=request_id))
        event_type = wrs.event_type_for_status(target)
        try:
            _add_event(
                row,
                event_type=event_type,
                actor_uid=uid,
                body=comment,
                metadata={"from": previous, "to": target},
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Could not update the request. Try again.", "error")
            return redirect(url_for("request_detail", request_id=request_id))
        _log_activity(
            row,
            {
                wrs.STATUS_STARTED: pae.REQUEST_STARTED,
                wrs.STATUS_FINISHED: pae.REQUEST_FINISHED,
                wrs.STATUS_FAILED: pae.REQUEST_FAILED,
                wrs.STATUS_PENDING: pae.REQUEST_REOPENED,
            }.get(target, pae.REQUEST_UPDATED),
            "status_changed",
            extra={"from": previous, "to": target, "comment": comment},
        )
        notify_key = {
            wrs.STATUS_STARTED: "work_request_started",
            wrs.STATUS_FINISHED: "work_request_finished",
            wrs.STATUS_FAILED: "work_request_failed",
            wrs.STATUS_PENDING: "work_request_reopened",
        }.get(target)
        if notify_key:
            _notify(notify_key, row, acc, comment=comment, previous_status=previous)
        flash(f"Request marked {wrs.STATUS_LABELS.get(target, target).lower()}.", "ok")
        return redirect(url_for("request_detail", request_id=request_id))

    @app.route("/requests/<int:request_id>/start", methods=["POST"])
    def requests_start(request_id: int):
        return _transition(request_id, wrs.STATUS_STARTED)

    @app.route("/requests/<int:request_id>/finish", methods=["POST"])
    def requests_finish(request_id: int):
        return _transition(request_id, wrs.STATUS_FINISHED)

    @app.route("/requests/<int:request_id>/fail", methods=["POST"])
    def requests_fail(request_id: int):
        return _transition(request_id, wrs.STATUS_FAILED)

    @app.route("/requests/<int:request_id>/reopen", methods=["POST"])
    def requests_reopen(request_id: int):
        return _transition(request_id, wrs.STATUS_PENDING)

    @app.route("/requests/<int:request_id>/comment", methods=["POST"])
    def requests_comment(request_id: int):
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login", next=url_for("request_detail", request_id=request_id)))
        uid = directory_user_id_for_account(acc)
        vis = visible_project_ids_for_account(acc)
        row = _load_row(request_id)
        if row is None or not _can_see_row(acc, row, uid, vis):
            abort(404)
        if not _can_change_status(acc, row, uid) and not _can_edit_row(acc, row, uid):
            abort(403)
        body = (request.form.get("comment") or "").strip()
        if not body:
            flash("Enter a comment.", "error")
            return redirect(url_for("request_detail", request_id=request_id))
        row.updated_at = now_local()
        _add_event(row, event_type=wrs.EVENT_COMMENTED, actor_uid=uid, body=body)
        db.session.commit()
        flash("Comment added.", "ok")
        return redirect(url_for("request_detail", request_id=request_id))

    @app.route("/requests/<int:request_id>/assign", methods=["POST"])
    def requests_assign(request_id: int):
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login", next=url_for("request_detail", request_id=request_id)))
        uid = directory_user_id_for_account(acc)
        vis = visible_project_ids_for_account(acc)
        row = _load_row(request_id)
        if row is None or not _can_see_row(acc, row, uid, vis):
            abort(404)
        if not _can_assign(acc, row, uid):
            abort(403)
        assigned_to_id = wrs.parse_optional_int(request.form.get("assigned_to_id"))
        if assigned_to_id is not None:
            if db.session.get(User, int(assigned_to_id)) is None:
                flash("Invalid assignee.", "error")
                return redirect(url_for("request_detail", request_id=request_id))
            if not _member_ok(row.project_id, assigned_to_id):
                flash("Only project members can be assigned.", "error")
                return redirect(url_for("request_detail", request_id=request_id))
        prev = row.assigned_to_id
        row.assigned_to_id = assigned_to_id
        row.updated_at = now_local()
        row.version = int(row.version or 0) + 1
        _add_event(
            row,
            event_type=wrs.EVENT_EDITED,
            actor_uid=uid,
            body="Assignee updated.",
            metadata={"from": prev, "to": assigned_to_id},
        )
        db.session.commit()
        if assigned_to_id and assigned_to_id != prev:
            _notify("work_request_assigned", row, acc)
        flash("Assignee updated.", "ok")
        return redirect(url_for("request_detail", request_id=request_id))

    @app.route("/requests/<int:request_id>/delete", methods=["POST"])
    def requests_delete(request_id: int):
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login", next=url_for("request_detail", request_id=request_id)))
        uid = directory_user_id_for_account(acc)
        vis = visible_project_ids_for_account(acc)
        row = _load_row(request_id)
        if row is None or not _can_see_row(acc, row, uid, vis):
            abort(404)
        if not _can_delete(acc, row, uid):
            abort(403)
        row.archived = True
        row.updated_at = now_local()
        _add_event(row, event_type=wrs.EVENT_EDITED, actor_uid=uid, body="Request archived.")
        db.session.commit()
        flash("Request deleted.", "ok")
        return redirect(url_for("requests_page"))
