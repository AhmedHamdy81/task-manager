"""Booking blueprint: edit suites and room bookings (JSON API + HTML shells)."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from flask import Blueprint, abort, current_app, jsonify, render_template, request
from sqlalchemy.orm import joinedload

from time_utils import now_local, today_cairo

booking_bp = Blueprint("booking", __name__, url_prefix="/booking")

END_OF_DAY = time(23, 59, 59)
NOTES_MAX_LEN = 10_000
BOOKING_JOB_TYPES = (
    "Sync",
    "Selection",
    "Assembly",
    "Offline Editing",
    "Online editing",
    "Color Grading",
)
BOOKING_JOB_TYPE_SET = frozenset(BOOKING_JOB_TYPES)


def _ctx() -> dict[str, Any]:
    return current_app.extensions.get("booking") or {}


def _wants_json() -> bool:
    if (request.args.get("json") or "").strip() == "1":
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return accept.startswith("application/json")


def _require_json() -> tuple[dict | None, tuple | None]:
    if not request.is_json:
        return None, (jsonify({"error": "JSON body required"}), 400)
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return None, (jsonify({"error": "Invalid JSON"}), 400)
    return data, None


def _parse_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, str):
        s = val.strip()
        try:
            y, m, d = (int(x) for x in s.split("-")[:3])
            return date(y, m, d)
        except (ValueError, TypeError):
            return None
    return None


def _parse_time(val: Any) -> time | None:
    if val is None:
        return None
    if isinstance(val, time):
        return val
    if isinstance(val, str):
        parts = val.strip().split(":")
        if len(parts) < 2:
            return None
        try:
            h = int(parts[0])
            m = int(parts[1])
            sec = int(parts[2]) if len(parts) > 2 else 0
            return time(h, m, sec)
        except (ValueError, TypeError):
            return None
    return None


def _today() -> date:
    return today_cairo()


def _validate_not_past_booking_date(d: date) -> tuple | None:
    if d < _today():
        return jsonify({"error": "validation", "message": "Booking date cannot be in the past."}), 400
    return None


def _suite_to_dict(s: Any) -> dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "is_active": bool(s.is_active),
        "subtitle": "Edit suite",
    }


def _booking_to_dict(b: Any) -> dict[str, Any]:
    suite = b.edit_suite
    suite_name = suite.name if suite is not None else ""
    proj = b.project
    project_name = proj.name if proj is not None else ""
    by = b.booked_by_user
    bf = b.booked_for_user
    booked_by_name = (by.name or by.email).strip() if by is not None else ""
    booked_for_name = (bf.name or bf.email).strip() if bf is not None else ""
    scene_id = getattr(b, "scene_id", None)
    scene_label = ""
    sc = getattr(b, "shooting_day_scene", None)
    if sc is not None:
        sl = (getattr(sc, "scene_label", None) or "").strip()
        if not sl:
            sl = str(int(getattr(sc, "scene_number", 0) or 0))
        scene_label = f"Ep {int(sc.episode_number or 0)} · {sl}"
    return {
        "id": b.id,
        "edit_suite_id": b.edit_suite_id,
        "suite_name": suite_name,
        "project_id": b.project_id,
        "project_name": project_name,
        "booked_by_id": b.booked_by_id,
        "booked_by_name": booked_by_name,
        "booked_for_id": b.booked_for_id,
        "booked_for_name": booked_for_name,
        "booking_date": b.booking_date.isoformat(),
        "start_time": b.start_time.isoformat(timespec="seconds"),
        "end_time": b.end_time.isoformat(timespec="seconds"),
        "is_full_day": bool(b.is_full_day),
        "notes": (b.notes or "").strip(),
        "job_type": (getattr(b, "job_type", None) or "").strip(),
        "is_active": bool(b.is_active),
        "created_at": b.created_at.isoformat(timespec="seconds") if b.created_at else None,
        "scene_id": scene_id,
        "scene_label": scene_label,
    }


def _parse_job_type(val: Any) -> tuple[str | None, tuple | None]:
    job_type = (val or "").strip() if isinstance(val, str) or val is None else str(val).strip()
    if not job_type:
        return None, (
            jsonify({"error": "validation", "message": "Job is required."}),
            400,
        )
    if job_type not in BOOKING_JOB_TYPE_SET:
        return None, (
            jsonify({"error": "validation", "message": "Invalid job type."}),
            400,
        )
    return job_type, None


def _booking_timeline_mask_dict(b: Any) -> dict[str, Any]:
    """Minimal booking payload for timeline occupancy (no project or people details)."""
    return {
        "id": b.id,
        "edit_suite_id": b.edit_suite_id,
        "booking_date": b.booking_date.isoformat(),
        "start_time": b.start_time.isoformat(timespec="seconds"),
        "end_time": b.end_time.isoformat(timespec="seconds"),
        "is_full_day": bool(b.is_full_day),
        "is_active": bool(b.is_active),
        "timeline_masked": True,
        "project_id": 0,
        "project_name": "",
        "booked_by_id": 0,
        "booked_by_name": "",
        "booked_for_id": 0,
        "booked_for_name": "",
        "notes": "",
        "job_type": "",
        "scene_id": None,
        "scene_label": "",
        "created_at": None,
    }


def _overlap_exists(
    booking_date: date,
    suite_id: int,
    start_t: time,
    end_t: time,
    exclude_id: int | None = None,
) -> bool:
    ctx = _ctx()
    db = ctx["db"]
    B = ctx["Booking"]
    q = B.query.filter(
        B.edit_suite_id == suite_id,
        B.booking_date == booking_date,
        B.is_active.is_(True),
    )
    if exclude_id is not None:
        q = q.filter(B.id != exclude_id)
    new_start = datetime.combine(booking_date, start_t)
    new_end = datetime.combine(booking_date, end_t)
    for b in q.all():
        bs = datetime.combine(b.booking_date, b.start_time)
        be = datetime.combine(b.booking_date, b.end_time)
        if bs < new_end and be > new_start:
            return True
    return False


def _require_admin() -> tuple | None:
    ctx = _ctx()
    acc = ctx["account_from_session"]()
    if acc is None or not ctx["account_can_access_admin_settings"](acc):
        return jsonify({"error": "forbidden"}), 403
    return None


def _directory_uid() -> int | None:
    ctx = _ctx()
    acc = ctx["account_from_session"]()
    if acc is None:
        return None
    return ctx["directory_user_id_for_account"](acc)


def _booking_can_mutate(b: Any, uid: int | None, admin: bool) -> bool:
    if admin:
        return True
    if uid is None:
        return False
    return b.booked_by_id == uid or b.booked_for_id == uid


@booking_bp.route("/projects", methods=["GET"])
def booking_projects_json():
    ctx = _ctx()
    if not ctx:
        abort(500)
    Project = ctx["Project"]
    acc = ctx["account_from_session"]()
    if acc is None:
        return jsonify({"error": "forbidden"}), 403
    vis = ctx["visible_project_ids_for_account"](acc)
    q = Project.query.order_by(Project.sort_order.asc(), Project.id.asc())
    if vis is None:
        projects = q.all()
    elif not vis:
        projects = []
    else:
        projects = q.filter(Project.id.in_(vis)).all()
    return jsonify({"projects": [{"id": p.id, "name": p.name} for p in projects]})


@booking_bp.route("/project-scenes/<int:project_id>", methods=["GET"])
def booking_project_scenes_json(project_id: int):
    """Planned scenes for a project (optional booking target)."""
    ctx = _ctx()
    if not ctx:
        abort(500)
    SDS = ctx.get("ShootingDayScene")
    SD = ctx.get("ShootingDay")
    if SDS is None or SD is None:
        return jsonify({"scenes": []})
    acc = ctx["account_from_session"]()
    if acc is None or not ctx["account_can_access_project"](acc, project_id):
        return jsonify({"error": "forbidden"}), 403
    rows = (
        SDS.query.join(SD, SDS.shooting_day_id == SD.id)
        .filter(SD.project_id == project_id)
        .order_by(SDS.episode_number.asc(), SDS.scene_label.asc(), SDS.id.asc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for sc in rows:
        sec = int(getattr(sc, "duration_seconds", 0) or 0)
        if sec <= 0:
            sec = max(0, int(getattr(sc, "duration", 0) or 0)) * 60
        sl = (getattr(sc, "scene_label", None) or "").strip()
        if not sl:
            sl = str(int(getattr(sc, "scene_number", 0) or 0))
        label = f"Ep {int(sc.episode_number or 0)} · {sl}"
        desc = (sc.notes or "").strip()
        if desc:
            label += " — " + (desc[:48] + "..." if len(desc) > 48 else desc)
        out.append(
            {
                "id": sc.id,
                "label": label,
                "estimated_duration_minutes": max(0, (sec + 59) // 60) if sec else 0,
                "ready_for_editing": bool(sc.first_edit_done),
                "project_id": project_id,
            }
        )
    return jsonify({"scenes": out})


@booking_bp.route("/project-members/<int:project_id>", methods=["GET"])
def booking_project_members_json(project_id: int):
    """Directory users on the project team (for Booked-for dropdown). JSON array of {id, name}."""
    ctx = _ctx()
    if not ctx:
        abort(500)
    acc = ctx["account_from_session"]()
    if acc is None:
        return jsonify({"error": "forbidden"}), 403
    can = ctx.get("account_can_access_project")
    if can is not None and not can(acc, project_id):
        return jsonify({"error": "forbidden"}), 403
    User = ctx["User"]
    ProjectMember = ctx.get("ProjectMember")
    if ProjectMember is None:
        return jsonify([])
    users = (
        User.query.join(ProjectMember, ProjectMember.user_id == User.id)
        .filter(ProjectMember.project_id == project_id)
        .order_by(User.name.asc(), User.id.asc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for u in users:
        if (u.name or "").strip().casefold() == "admin":
            continue
        out.append(
            {
                "id": u.id,
                "name": (u.name or u.email or "").strip() or str(u.id),
            }
        )
    return jsonify(out)


@booking_bp.route("/users", methods=["GET"])
def booking_users_json():
    ctx = _ctx()
    if not ctx:
        abort(500)
    User = ctx["User"]
    ProjectMember = ctx.get("ProjectMember")
    if ctx["account_from_session"]() is None:
        return jsonify({"error": "forbidden"}), 403
    include_id: int | None = None
    raw_inc = request.args.get("include_user_id")
    if raw_inc is not None and str(raw_inc).strip() != "":
        try:
            include_id = int(raw_inc)
        except (TypeError, ValueError):
            include_id = None
    project_id: int | None = None
    raw_pid = request.args.get("project_id")
    if raw_pid is not None and str(raw_pid).strip() != "":
        try:
            project_id = int(raw_pid)
        except (TypeError, ValueError):
            project_id = None

    if project_id and ProjectMember is not None:
        member_ids = {
            pm.user_id for pm in ProjectMember.query.filter_by(project_id=project_id).all()
        }
        if include_id is not None:
            member_ids.add(include_id)
        if member_ids:
            users = (
                User.query.filter(User.id.in_(member_ids))
                .order_by(User.name.asc(), User.id.asc())
                .all()
            )
        else:
            users = []
    else:
        users = User.query.order_by(User.name.asc(), User.id.asc()).all()
    out = []
    for u in users:
        if (u.name or "").strip().casefold() == "admin" and (include_id is None or u.id != include_id):
            continue
        out.append(
            {
                "id": u.id,
                "name": (u.name or u.email or "").strip() or str(u.id),
            }
        )
    return jsonify({"users": out})


@booking_bp.route("/today", methods=["GET"])
def booking_today_json():
    """Today's booking for the current user as `booked_for` (dashboard card)."""
    ctx = _ctx()
    if not ctx:
        abort(500)
    B = ctx["Booking"]
    uid = _directory_uid()
    if uid is None:
        return jsonify({"booking": None})
    b = (
        B.query.options(
            joinedload(B.edit_suite),
            joinedload(B.project),
            joinedload(B.booked_for_user),
            joinedload(B.booked_by_user),
        )
        .filter(
            B.booked_for_id == uid,
            B.booking_date == _today(),
            B.is_active.is_(True),
        )
        .order_by(B.start_time.asc())
        .first()
    )
    if b is None:
        return jsonify({"booking": None})
    return jsonify({"booking": _booking_to_dict(b)})


@booking_bp.route("/edit-suites", methods=["GET"])
def edit_suites_list():
    ctx = _ctx()
    if not ctx:
        abort(500)
    EditSuite = ctx["EditSuite"]
    acc = ctx["account_from_session"]()
    if acc is None:
        return jsonify({"error": "forbidden"}), 403
    admin = ctx["account_can_access_admin_settings"](acc)
    q = EditSuite.query
    if not admin or (request.args.get("all") or "").strip() != "1":
        q = q.filter(EditSuite.is_active.is_(True))
    suites = q.order_by(EditSuite.name.asc(), EditSuite.id.asc()).all()
    return jsonify({"suites": [_suite_to_dict(s) for s in suites]})


@booking_bp.route("/edit-suites", methods=["POST"])
def edit_suites_create():
    ctx = _ctx()
    if not ctx:
        abort(500)
    err = _require_admin()
    if err:
        return err
    db = ctx["db"]
    EditSuite = ctx["EditSuite"]
    data, bad = _require_json()
    if bad:
        return bad
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "validation", "message": "Suite name is required."}), 400
    if len(name) > 200:
        return jsonify({"error": "validation", "message": "Suite name is too long."}), 400
    s = EditSuite(name=name, is_active=True)
    db.session.add(s)
    db.session.commit()
    return jsonify({"suite": _suite_to_dict(s)}), 201


@booking_bp.route("/edit-suites/<int:suite_id>", methods=["PUT"])
def edit_suites_update(suite_id: int):
    ctx = _ctx()
    if not ctx:
        abort(500)
    err = _require_admin()
    if err:
        return err
    db = ctx["db"]
    EditSuite = ctx["EditSuite"]
    data, bad = _require_json()
    if bad:
        return bad
    s = db.session.get(EditSuite, suite_id)
    if s is None:
        return jsonify({"error": "not_found"}), 404
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "validation", "message": "Suite name is required."}), 400
        if len(name) > 200:
            return jsonify({"error": "validation", "message": "Suite name is too long."}), 400
        s.name = name
    if "is_active" in data:
        s.is_active = bool(data.get("is_active"))
    db.session.commit()
    return jsonify({"suite": _suite_to_dict(s)})


@booking_bp.route("/edit-suites/<int:suite_id>", methods=["DELETE"])
def edit_suites_delete(suite_id: int):
    ctx = _ctx()
    if not ctx:
        abort(500)
    err = _require_admin()
    if err:
        return err
    db = ctx["db"]
    EditSuite = ctx["EditSuite"]
    s = db.session.get(EditSuite, suite_id)
    if s is None:
        return jsonify({"error": "not_found"}), 404
    s.is_active = False
    db.session.commit()
    return jsonify({"ok": True, "suite": _suite_to_dict(s)})


@booking_bp.route("/manage", methods=["GET"])
def booking_manage_page():
    return render_template("booking_manage.html")


@booking_bp.route("", methods=["GET"])
def booking_home():
    ctx = _ctx()
    if not ctx:
        abort(500)
    if _wants_json():
        return _bookings_json_list()
    return render_template("booking.html")


@booking_bp.route("", methods=["POST"])
def booking_create():
    ctx = _ctx()
    if not ctx:
        abort(500)
    db = ctx["db"]
    Booking = ctx["Booking"]
    EditSuite = ctx["EditSuite"]
    User = ctx["User"]
    uid = _directory_uid()
    if uid is None:
        return jsonify(
            {
                "error": "no_directory_user",
                "message": "Your account is not linked to a directory user; bookings are unavailable.",
            }
        ), 403
    data, bad = _require_json()
    if bad:
        return bad
    try:
        suite_id = int(data.get("edit_suite_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "validation", "message": "Room is required."}), 400
    try:
        project_id = int(data.get("project_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "validation", "message": "Project is required."}), 400
    try:
        booked_for_id = int(data.get("booked_for_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "validation", "message": "Booked for is required."}), 400
    parsed_scene_id: int | None = None
    raw_sc = data.get("scene_id")
    if raw_sc is not None and str(raw_sc).strip() != "":
        try:
            parsed_scene_id = int(raw_sc)
        except (TypeError, ValueError):
            return jsonify({"error": "validation", "message": "Invalid scene."}), 400
    booking_date = _parse_date(data.get("booking_date"))
    if booking_date is None:
        return jsonify({"error": "validation", "message": "Invalid booking date."}), 400
    past_err = _validate_not_past_booking_date(booking_date)
    if past_err:
        return past_err
    is_full_day = bool(data.get("is_full_day"))
    start_t = _parse_time(data.get("start_time"))
    end_t = _parse_time(data.get("end_time"))
    if start_t is None:
        return jsonify({"error": "validation", "message": "Start time is required."}), 400
    if is_full_day:
        end_t = END_OF_DAY
    elif end_t is None:
        return jsonify({"error": "validation", "message": "End time is required."}), 400
    if start_t >= end_t:
        return jsonify({"error": "validation", "message": "End time must be after start time."}), 400
    notes = (data.get("notes") or "").strip()
    if len(notes) > NOTES_MAX_LEN:
        return jsonify({"error": "validation", "message": "Notes are too long."}), 400
    job_type, job_err = _parse_job_type(data.get("job_type"))
    if job_err:
        return job_err
    acc = ctx["account_from_session"]()
    if acc is None or not ctx["account_can_access_project"](acc, project_id):
        return jsonify({"error": "validation", "message": "You cannot book under that project."}), 400
    SDS = ctx.get("ShootingDayScene")
    if parsed_scene_id is not None:
        if SDS is None:
            return jsonify({"error": "validation", "message": "Scenes are not available."}), 400
        sc_row = db.session.get(SDS, parsed_scene_id)
        if sc_row is None:
            return jsonify({"error": "validation", "message": "Unknown scene."}), 400
        if sc_row.shooting_day is None or sc_row.shooting_day.project_id != project_id:
            return jsonify({"error": "validation", "message": "Scene does not belong to that project."}), 400
    suite = db.session.get(EditSuite, suite_id)
    if suite is None or not suite.is_active:
        return jsonify({"error": "validation", "message": "That room is not available."}), 400
    if db.session.get(User, booked_for_id) is None:
        return jsonify({"error": "validation", "message": "Invalid user for Booked for."}), 400
    if _overlap_exists(booking_date, suite_id, start_t, end_t, None):
        emit_overlap = ctx.get("emit_booking_overlap_alert")
        if callable(emit_overlap):
            emit_overlap(
                project_id=project_id,
                suite_id=suite_id,
                booking_date=booking_date,
                start_t=start_t,
                end_t=end_t,
                attempting_user_id=uid,
            )
            db.session.commit()
        return jsonify(
            {
                "error": "conflict",
                "message": "That room is already booked for an overlapping time on this date.",
            }
        ), 409
    b = Booking(
        edit_suite_id=suite_id,
        user_id=uid,
        project_id=project_id,
        booked_by_id=uid,
        booked_for_id=booked_for_id,
        booking_date=booking_date,
        start_time=start_t,
        end_time=end_t,
        is_full_day=is_full_day,
        notes=notes,
        job_type=job_type or "",
        is_active=True,
        created_at=now_local(),
        scene_id=parsed_scene_id,
    )
    db.session.add(b)
    db.session.commit()
    db.session.refresh(b)
    b = (
        Booking.query.options(
            joinedload(Booking.edit_suite),
            joinedload(Booking.project),
            joinedload(Booking.booked_by_user),
            joinedload(Booking.booked_for_user),
            joinedload(Booking.shooting_day_scene),
        )
        .filter_by(id=b.id)
        .first()
    )
    try:
        import project_activity_events as pae
        import project_activity_hooks as pah

        pah.log_booking_event(
            project_id=project_id,
            event_type=pae.BOOKING_CREATED,
            booking=b,
        )
        db.session.commit()
    except Exception:
        current_app.logger.exception("booking create activity log failed")
    return jsonify({"booking": _booking_to_dict(b)}), 201


@booking_bp.route("/<int:booking_id>", methods=["PUT"])
def booking_update(booking_id: int):
    ctx = _ctx()
    if not ctx:
        abort(500)
    db = ctx["db"]
    Booking = ctx["Booking"]
    EditSuite = ctx["EditSuite"]
    User = ctx["User"]
    uid = _directory_uid()
    if uid is None:
        return jsonify(
            {
                "error": "no_directory_user",
                "message": "Your account is not linked to a directory user; bookings are unavailable.",
            }
        ), 403
    acc = ctx["account_from_session"]()
    admin = acc is not None and ctx["account_can_access_admin_settings"](acc)
    b = (
        Booking.query.options(
            joinedload(Booking.edit_suite),
            joinedload(Booking.project),
            joinedload(Booking.booked_by_user),
            joinedload(Booking.booked_for_user),
            joinedload(Booking.shooting_day_scene),
        )
        .filter_by(id=booking_id)
        .first()
    )
    if b is None:
        return jsonify({"error": "not_found"}), 404
    if not _booking_can_mutate(b, uid, admin):
        return jsonify({"error": "forbidden"}), 403
    if not b.is_active:
        return jsonify({"error": "validation", "message": "This booking is cancelled."}), 400
    data, bad = _require_json()
    if bad:
        return bad
    import project_activity_service as pas

    before_snap = pas.booking_snapshot(b)
    suite_id = b.edit_suite_id
    if "edit_suite_id" in data:
        try:
            suite_id = int(data.get("edit_suite_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "validation", "message": "Invalid edit suite."}), 400
    project_id = b.project_id
    if "project_id" in data:
        try:
            project_id = int(data.get("project_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "validation", "message": "Invalid project."}), 400
        if acc is None or not ctx["account_can_access_project"](acc, project_id):
            return jsonify({"error": "validation", "message": "You cannot assign that project."}), 400
    booked_for_id = b.booked_for_id
    if "booked_for_id" in data:
        try:
            booked_for_id = int(data.get("booked_for_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "validation", "message": "Invalid Booked for user."}), 400
        if db.session.get(User, booked_for_id) is None:
            return jsonify({"error": "validation", "message": "Invalid user for Booked for."}), 400
    booking_date = b.booking_date
    if "booking_date" in data:
        booking_date = _parse_date(data.get("booking_date"))
        if booking_date is None:
            return jsonify({"error": "validation", "message": "Invalid booking date."}), 400
        past_err = _validate_not_past_booking_date(booking_date)
        if past_err:
            return past_err
    is_full_day = bool(b.is_full_day)
    if "is_full_day" in data:
        is_full_day = bool(data.get("is_full_day"))
    start_t = b.start_time
    end_t = b.end_time
    if "start_time" in data:
        start_t = _parse_time(data.get("start_time"))
        if start_t is None:
            return jsonify({"error": "validation", "message": "Invalid start time."}), 400
    if is_full_day:
        end_t = END_OF_DAY
    elif "end_time" in data:
        end_t = _parse_time(data.get("end_time"))
        if end_t is None:
            return jsonify({"error": "validation", "message": "Invalid end time."}), 400
    if start_t >= end_t:
        return jsonify({"error": "validation", "message": "End time must be after start time."}), 400
    if "notes" in data:
        notes = (data.get("notes") or "").strip()
        if len(notes) > NOTES_MAX_LEN:
            return jsonify({"error": "validation", "message": "Notes are too long."}), 400
        b.notes = notes
    if "job_type" in data:
        job_type, job_err = _parse_job_type(data.get("job_type"))
        if job_err:
            return job_err
        b.job_type = job_type or ""
    if "scene_id" in data:
        SDS = ctx.get("ShootingDayScene")
        raw_sc = data.get("scene_id")
        if raw_sc is None or str(raw_sc).strip() == "":
            b.scene_id = None
        else:
            try:
                sid = int(raw_sc)
            except (TypeError, ValueError):
                return jsonify({"error": "validation", "message": "Invalid scene."}), 400
            if SDS is None:
                return jsonify({"error": "validation", "message": "Scenes are not available."}), 400
            sc_row = db.session.get(SDS, sid)
            if sc_row is None:
                return jsonify({"error": "validation", "message": "Unknown scene."}), 400
            if sc_row.shooting_day is None or sc_row.shooting_day.project_id != project_id:
                return jsonify({"error": "validation", "message": "Scene does not belong to that project."}), 400
            b.scene_id = sid
    suite = db.session.get(EditSuite, suite_id)
    if suite is None or not suite.is_active:
        return jsonify({"error": "validation", "message": "That room is not available."}), 400
    if _overlap_exists(booking_date, suite_id, start_t, end_t, exclude_id=b.id):
        emit_overlap = ctx.get("emit_booking_overlap_alert")
        if callable(emit_overlap):
            emit_overlap(
                project_id=project_id,
                suite_id=suite_id,
                booking_date=booking_date,
                start_t=start_t,
                end_t=end_t,
                attempting_user_id=uid,
            )
            db.session.commit()
        return jsonify(
            {
                "error": "conflict",
                "message": "That room is already booked for an overlapping time on this date.",
            }
        ), 409
    b.edit_suite_id = suite_id
    b.project_id = project_id
    b.booked_for_id = booked_for_id
    b.booking_date = booking_date
    b.start_time = start_t
    b.end_time = end_t
    b.is_full_day = is_full_day
    db.session.commit()
    b = (
        Booking.query.options(
            joinedload(Booking.edit_suite),
            joinedload(Booking.project),
            joinedload(Booking.booked_by_user),
            joinedload(Booking.booked_for_user),
            joinedload(Booking.shooting_day_scene),
        )
        .filter_by(id=b.id)
        .first()
    )
    try:
        import project_activity_events as pae
        import project_activity_hooks as pah
        import project_activity_service as pas

        after_snap = pas.booking_snapshot(b)
        pah.log_booking_event(
            project_id=int(b.project_id),
            event_type=pae.BOOKING_UPDATED,
            booking=b,
            before=before_snap,
            after=after_snap,
        )
        db.session.commit()
    except Exception:
        current_app.logger.exception("booking update activity log failed")
    return jsonify({"booking": _booking_to_dict(b)})


@booking_bp.route("/<int:booking_id>", methods=["DELETE"])
def booking_delete(booking_id: int):
    ctx = _ctx()
    if not ctx:
        abort(500)
    db = ctx["db"]
    Booking = ctx["Booking"]
    uid = _directory_uid()
    if uid is None:
        return jsonify(
            {
                "error": "no_directory_user",
                "message": "Your account is not linked to a directory user; bookings are unavailable.",
            }
        ), 403
    acc = ctx["account_from_session"]()
    admin = acc is not None and ctx["account_can_access_admin_settings"](acc)
    b = db.session.get(Booking, booking_id)
    if b is None:
        return jsonify({"error": "not_found"}), 404
    if not _booking_can_mutate(b, uid, admin):
        return jsonify({"error": "forbidden"}), 403
    b.is_active = False
    try:
        import project_activity_events as pae
        import project_activity_hooks as pah

        pah.log_booking_event(
            project_id=int(b.project_id),
            event_type=pae.BOOKING_CANCELLED,
            booking=b,
        )
    except Exception:
        current_app.logger.exception("booking cancel activity log failed")
    db.session.commit()
    b = (
        Booking.query.options(
            joinedload(Booking.edit_suite),
            joinedload(Booking.project),
            joinedload(Booking.booked_by_user),
            joinedload(Booking.booked_for_user),
            joinedload(Booking.shooting_day_scene),
        )
        .filter_by(id=b.id)
        .first()
    )
    return jsonify({"ok": True, "booking": _booking_to_dict(b)})


def _bookings_json_list():
    ctx = _ctx()
    Booking = ctx["Booking"]

    acc = ctx["account_from_session"]()
    if acc is None:
        return jsonify({"error": "forbidden"}), 403
    admin = ctx["account_can_access_admin_settings"](acc)
    uid = ctx["directory_user_id_for_account"](acc)
    if uid is None:
        return jsonify({"bookings_mine": [], "bookings_assigned": [], "bookings_timeline": []})
    opts = (
        joinedload(Booking.edit_suite),
        joinedload(Booking.project),
        joinedload(Booking.booked_by_user),
        joinedload(Booking.booked_for_user),
        joinedload(Booking.shooting_day_scene),
    )
    base = Booking.query.options(*opts).filter(Booking.is_active.is_(True))
    from_s = _parse_date(request.args.get("from"))
    to_s = _parse_date(request.args.get("to"))

    q_mine = base.filter(Booking.booked_by_id == uid).order_by(
        Booking.booking_date.desc(), Booking.start_time.asc()
    )
    q_asg = base.filter(
        Booking.booked_for_id == uid,
        Booking.booked_by_id != uid,
    ).order_by(Booking.booking_date.desc(), Booking.start_time.asc())
    if from_s is not None:
        q_mine = q_mine.filter(Booking.booking_date >= from_s)
        q_asg = q_asg.filter(Booking.booking_date >= from_s)
    if to_s is not None:
        q_mine = q_mine.filter(Booking.booking_date <= to_s)
        q_asg = q_asg.filter(Booking.booking_date <= to_s)
    mine = q_mine.all()
    assigned = q_asg.all()
    visible_ids = {b.id for b in mine} | {b.id for b in assigned}
    q_all = base.order_by(Booking.booking_date.asc(), Booking.start_time.asc())
    if from_s is not None:
        q_all = q_all.filter(Booking.booking_date >= from_s)
    if to_s is not None:
        q_all = q_all.filter(Booking.booking_date <= to_s)
    all_rows = q_all.all()
    if admin:
        mine_out = [
            _booking_to_dict(b)
            for b in sorted(all_rows, key=lambda b: (-(b.booking_date.toordinal()), b.start_time))
        ]
        assigned_out: list[dict[str, Any]] = []
        bookings_timeline = [_booking_to_dict(b) for b in all_rows]
    else:
        mine_out = [_booking_to_dict(b) for b in mine]
        assigned_out = [_booking_to_dict(b) for b in assigned]
        bookings_timeline = []
        for b in all_rows:
            if b.id in visible_ids:
                bookings_timeline.append(_booking_to_dict(b))
            else:
                bookings_timeline.append(_booking_timeline_mask_dict(b))
    return jsonify(
        {
            "bookings_mine": mine_out,
            "bookings_assigned": assigned_out,
            "bookings_timeline": bookings_timeline,
        }
    )
