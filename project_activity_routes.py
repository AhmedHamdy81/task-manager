"""Project Log Book routes and registration."""

from __future__ import annotations

import math
from typing import Any, Callable

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload

import project_activity_events as pae
import project_activity_service as pas


def register_project_activity_routes(app: Any, ctx: dict[str, Any]) -> None:
    db = ctx["db"]
    Project = ctx["Project"]
    ProjectActivityLog = ctx["ProjectActivityLog"]
    User = ctx["User"]
    ShootingDay = ctx.get("ShootingDay")
    now_local = ctx["now_local"]
    account_from_session = ctx["account_from_session"]
    account_can_access_project = ctx["account_can_access_project"]
    account_may_full_control_project = ctx["account_may_full_control_project"]
    account_can_view_project_settings_for = ctx.get("account_can_view_project_settings_for")
    account_is_elevated = ctx.get("account_is_elevated")
    format_datetime_cairo = ctx.get("format_datetime_cairo")

    def _can_view(acc: Any, project_id: int) -> bool:
        return pas.can_view_project_log_book(
            acc,
            project_id,
            account_can_access_project=account_can_access_project,
            account_may_full_control_project=account_may_full_control_project,
            account_can_view_project_settings_for=account_can_view_project_settings_for,
            account_is_elevated=account_is_elevated,
        )

    def _can_sensitive(acc: Any, project_id: int) -> bool:
        return pas.can_view_sensitive_log_details(
            acc,
            project_id,
            account_may_full_control_project=account_may_full_control_project,
            account_is_elevated=account_is_elevated,
        )

    @app.route("/projects/<int:project_id>/log-book")
    def project_log_book(project_id: int):
        acc = account_from_session()
        p = Project.query.get_or_404(project_id)
        if not _can_view(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))

        filters = pas.parse_log_book_filters(request.args)
        sensitive = _can_sensitive(acc, p.id)

        base_q = ProjectActivityLog.query.filter_by(project_id=int(p.id))
        # Summary cards use date range + search but ignore bucket/module card selection
        summary_filters = {**filters, "bucket": "all", "module": None}
        summary_q = pas.apply_log_book_filters(base_q, ProjectActivityLog, summary_filters)
        summary = pas.compute_summary_counts(summary_q, ProjectActivityLog)

        list_q = pas.apply_log_book_filters(base_q, ProjectActivityLog, filters)
        total = list_q.order_by(None).count()
        per_page = int(filters["per_page"])
        pages = max(1, math.ceil(total / per_page)) if total else 1
        page = min(int(filters["page"]), pages)
        filters["page"] = page
        rows = (
            list_q.order_by(ProjectActivityLog.occurred_at.desc(), ProjectActivityLog.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        today = now_local().date()

        def _heading(d):
            try:
                return d.strftime("%B %-d, %Y")
            except ValueError:
                return d.strftime("%B %d, %Y").replace(" 0", " ")

        groups = pas.group_rows_by_date(rows, today=today, format_date_heading=_heading)
        serialized_groups = []
        for g in groups:
            serialized_groups.append(
                {
                    "date": g["date"],
                    "title": g["title"],
                    "rows": [
                        pas.serialize_log_row(r, include_sensitive=sensitive, include_details=False)
                        for r in g["rows"]
                    ],
                }
            )

        # Actors who have logged activity on this project (for filter dropdown)
        actor_rows = (
            db.session.query(ProjectActivityLog.user_id, ProjectActivityLog.actor_name)
            .filter(
                ProjectActivityLog.project_id == int(p.id),
                ProjectActivityLog.user_id.isnot(None),
            )
            .distinct()
            .order_by(ProjectActivityLog.actor_name.asc())
            .limit(200)
            .all()
        )
        actors = [{"id": int(uid), "name": name} for uid, name in actor_rows if uid]

        shooting_days = []
        if ShootingDay is not None:
            shooting_days = (
                ShootingDay.query.filter_by(project_id=int(p.id))
                .order_by(ShootingDay.shooting_date.desc(), ShootingDay.id.desc())
                .limit(200)
                .all()
            )

        event_types = sorted(pae.ALL_EVENT_TYPES)
        modules = [
            {"value": k, "label": v} for k, v in pae.MODULE_LABELS.items()
        ]

        prev_url = (
            pas.log_book_page_url(
                "project_log_book", filters, page=page - 1, url_for=url_for, project_id=p.id
            )
            if page > 1
            else None
        )
        next_url = (
            pas.log_book_page_url(
                "project_log_book", filters, page=page + 1, url_for=url_for, project_id=p.id
            )
            if page < pages
            else None
        )
        clear_url = url_for("project_log_book", project_id=p.id)

        def card_url(bucket: str) -> str:
            f2 = {**filters, "bucket": bucket, "page": 1}
            if bucket != "all":
                f2["module"] = None
            return pas.log_book_page_url(
                "project_log_book", f2, page=1, url_for=url_for, project_id=p.id
            )

        return render_template(
            "project_log_book.html",
            project=p,
            workflow_active="log_book",
            groups=serialized_groups,
            filters=filters,
            summary=summary,
            page=page,
            pages=pages,
            total=total,
            per_page=per_page,
            page_sizes=pas.PAGE_SIZES,
            prev_url=prev_url,
            next_url=next_url,
            clear_url=clear_url,
            card_url=card_url,
            actors=actors,
            shooting_days=shooting_days,
            event_types=event_types,
            modules=modules,
            can_view_sensitive=sensitive,
            format_datetime=format_datetime_cairo,
            detail_url=url_for("project_log_book_detail", project_id=p.id, log_id=0).replace(
                "/0", "/__ID__"
            ),
        )

    @app.route("/projects/<int:project_id>/log-book/<int:log_id>.json")
    def project_log_book_detail(project_id: int, log_id: int):
        acc = account_from_session()
        p = Project.query.get_or_404(project_id)
        if not _can_view(acc, p.id):
            return jsonify({"error": "forbidden"}), 403
        row = ProjectActivityLog.query.filter_by(id=log_id, project_id=int(p.id)).first()
        if row is None:
            return jsonify({"error": "not_found"}), 404
        sensitive = _can_sensitive(acc, p.id)
        return jsonify(
            {
                "log": pas.serialize_log_row(
                    row, include_sensitive=sensitive, include_details=True
                )
            }
        )
