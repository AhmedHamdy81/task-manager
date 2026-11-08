"""Import & Compare wizard: Upload → Worksheets → Mapping → Compare → Confirm → Results.

Routes live under /projects/<id>/production/days/import so the existing production-day
page permissions apply; every handler also re-checks project access, production edit
rights and session ownership. Nothing before Confirm writes production data.
"""

from __future__ import annotations

import io
import json
import os
from types import SimpleNamespace

from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from sqlalchemy import text

import google_sheets_client as gsc
import production_export as pex
import production_import_matching as pim
import production_import_normalize as pin
import production_import_parsing as pip
import production_import_service as pis

STEPS = (
    ("upload", "Upload"),
    ("sheets", "Worksheets & layout"),
    ("mapping", "Map columns"),
    ("preview", "Preview & compare"),
    ("confirm", "Confirm"),
    ("results", "Results"),
)

# (Python weekday, label) in the order of an Egyptian working week.
WEEKDAYS = ((5, "Sat"), (6, "Sun"), (0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"))
DAYS_ALL_SCOPES = ("open", "all")


def _apply_days_to_all(plan: dict, opts: dict, form, *, can_create: bool) -> str:
    """Write one day decision per day group from the "Apply to all days" form.

    Dates for new days run consecutively per unit in file order from the start date,
    skipping the ticked days off. Returns an error message, or "" on success.
    """
    from datetime import date as _date, timedelta

    choice = form.get("all_choice") or ""
    scope = form.get("all_scope") if form.get("all_scope") in DAYS_ALL_SCOPES else "open"
    if choice not in ("create", "skip"):
        return "Choose what to do with the days."
    if choice == "create" and not can_create:
        return "You do not have permission to add shooting days."
    start = None
    off: set[int] = set()
    if choice == "create":
        try:
            start = _date.fromisoformat((form.get("all_start") or "").strip())
        except ValueError:
            return "Enter the date of the first shooting day."
        off = {int(v) for v in form.getlist("all_off") if v.isdigit() and int(v) < 7}
        if len(off) == 7:
            return "Leave at least one weekday as a shooting day."
    decisions = dict(opts.get("day_decisions") or {})
    next_date: dict[int, _date] = {}
    touched = 0
    for g in plan.get("days", []):
        if g.get("status") in ("fixed", "invalid"):
            continue
        if scope == "open" and not g.get("needs_decision"):
            continue
        if choice == "skip":
            decisions[g["key"]] = {"choice": "skip"}
            touched += 1
            continue
        if g.get("status") != "new":
            continue
        unit = int(g.get("unit") or 1)
        d = next_date.get(unit, start)
        while d.weekday() in off:
            d += timedelta(days=1)
        decisions[g["key"]] = {"choice": "create", "day_name": pin.storage_day_name(str(g.get("day_name") or "")), "date": d.isoformat()}
        next_date[unit] = d + timedelta(days=1)
        touched += 1
    if not touched:
        return "No days matched. Choose “All days in the file” to change days that are already set."
    opts["day_decisions"] = decisions
    return ""


def register_production_import_routes(app: Flask, ctx: dict) -> SimpleNamespace:
    db = ctx["db"]
    now_local = ctx["now_local"]
    Project = ctx["Project"]
    ShootingDay = ctx["ShootingDay"]
    account_from_session = ctx["account_from_session"]
    account_can_access_project = ctx["account_can_access_project"]
    account_may_edit_production_for = ctx["account_may_edit_production_for"]
    account_can_add_shooting_days_for = ctx["account_can_add_shooting_days_for"]
    send_managed_notification = ctx.get("send_managed_notification")
    notification_push_realtime_for_project = ctx.get("notification_push_realtime_for_project")
    ensure_vfx_bridge = ctx.get("ensure_vfx_bridge")

    svc = pis.ImportService(
        db=db,
        now_local=now_local,
        models={
            "Project": Project,
            "ShootingDay": ShootingDay,
            "ShootingDayScene": ctx["ShootingDayScene"],
            "SceneRow": ctx["SceneRow"],
        },
        storage_dir=lambda: app.config.get("PRODUCTION_IMPORT_STORAGE_DIR") or ctx["storage_dir"],
        secret=str(app.config.get("SECRET_KEY") or "production-import"),
        limits=app.config.get("PRODUCTION_IMPORT_LIMITS") or {},
    )

    def _hooks() -> dict:
        import project_activity_hooks as pah
        import project_activity_service as pas

        return {
            "pah": pah,
            "pas": pas,
            "find_duplicate": ctx["find_episode_scene_label_duplicate"],
            "runtime_siblings": ctx["shooting_day_scene_runtime_siblings"],
            "next_scene_id": ctx["next_legacy_scene_id_for_day"],
            "log_summary": _log_summary,
        }

    # -- access ------------------------------------------------------------------

    def _project_or_abort(project_id: int):
        acc = account_from_session()
        if acc is None:
            abort(403)
        project = db.session.get(Project, int(project_id))
        if project is None:
            abort(404)
        if not account_can_access_project(acc, project.id) or not account_may_edit_production_for(acc, project.id):
            abort(403)
        return acc, project

    def _load(project_id: int, token: str, *, allow_closed: bool = False):
        acc, project = _project_or_abort(project_id)
        sess = svc.get_session(token)
        if sess is None or int(sess.project_id) != int(project.id) or int(sess.account_id) != int(acc.id):
            abort(404)
        if sess.status in pis.OPEN_STATUSES and sess.expires_at < now_local():
            svc.purge_expired()
            sess = svc.get_session(token)
        if not allow_closed and sess.status not in pis.OPEN_STATUSES:
            if sess.status == pis.STATUS_EXECUTED:
                return acc, project, sess, redirect(url_for("production_import_results", project_id=project.id, token=token))
            flash("This import session has ended (expired or cancelled). Upload the file again.", "error")
            return acc, project, sess, redirect(_entry_url(project.id, sess.target_day_id))
        if sess.target_day_id:
            day = db.session.get(ShootingDay, int(sess.target_day_id))
            if day is None or int(day.project_id) != int(project.id):
                flash("The shooting day of this import no longer exists.", "error")
                return acc, project, sess, redirect(url_for("project_production", project_id=project.id))
        return acc, project, sess, None

    @app.route("/projects/<int:project_id>/production/days/export")
    def production_export(project_id: int):
        acc = account_from_session()
        if acc is None:
            abort(403)
        project = db.session.get(Project, int(project_id))
        if project is None:
            abort(404)
        if not account_can_access_project(acc, project.id):
            abort(403)
        fmt = (request.args.get("format") or "xlsx").lower()
        if fmt not in pex.FORMATS:
            abort(404)
        raw_day = (request.args.get("day_id") or "").strip()
        day = None
        if raw_day:
            day = db.session.get(ShootingDay, int(raw_day)) if raw_day.isdigit() else None
            if day is None or int(day.project_id) != int(project.id):
                abort(404)
        pctx = svc.project_context(project.id)
        days, rows, _legacy = svc.snapshots(project.id)
        fields = pex.export_fields(is_tv=pctx["is_tv"])
        items = pex.export_rows(days, rows, is_tv=pctx["is_tv"], day_id=day.id if day else None)
        if fmt == "csv":
            data, mimetype = pex.to_csv(items, fields), "text/csv; charset=utf-8"
        else:
            data, mimetype = pex.to_xlsx(items, fields), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        day_info = {"unit_number": day.unit_number, "day_name": day.day_name} if day else None
        resp = send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True,
                         download_name=pex.download_name(project.name, day=day_info, fmt=fmt))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def _entry_url(project_id: int, day_id: int | None = None) -> str:
        return url_for("production_import_entry", project_id=project_id, **({"day_id": day_id} if day_id else {}))

    def _fixed_day(sess):
        return db.session.get(ShootingDay, int(sess.target_day_id)) if sess.target_day_id else None

    def _gs():
        return app.extensions.get("google_sheets")

    def _render(step: str, project, sess=None, **kw):
        kw.setdefault("excel_time_modes", pin.EXCEL_TIME_MODES)
        return render_template(
            "production_import.html",
            project=project,
            sess=sess,
            step=step,
            steps=STEPS,
            source=(svc.options(sess).get("source") if sess is not None else None),
            fixed_day=_fixed_day(sess) if sess is not None else kw.pop("fixed_day", None),
            fields=pin.FIELDS,
            status_labels=pim.STATUS_LABELS,
            action_labels=pim.ACTION_LABELS,
            **kw,
        )

    # -- 1. Upload ---------------------------------------------------------------

    @app.route("/projects/<int:project_id>/production/days/import", methods=["GET", "POST"])
    def production_import_entry(project_id: int):
        acc, project = _project_or_abort(project_id)
        svc.purge_expired()
        raw_day = request.values.get("day_id", "").strip()
        fixed_day = None
        if raw_day:
            if not raw_day.isdigit():
                abort(404)
            fixed_day = db.session.get(ShootingDay, int(raw_day))
            if fixed_day is None or int(fixed_day.project_id) != int(project.id):
                abort(404)
        limits = {**pip.DEFAULT_LIMITS, **(app.config.get("PRODUCTION_IMPORT_LIMITS") or {})}
        if request.method == "POST":
            upload = request.files.get("file")
            if upload is None or not (upload.filename or "").strip():
                flash("Choose an .xlsx or .csv file.", "error")
                return redirect(_entry_url(project.id, fixed_day.id if fixed_day else None))
            data = upload.stream.read(int(limits["max_bytes"]) + 1)
            try:
                sess = svc.create_session(
                    project_id=project.id, account_id=acc.id, target_day_id=fixed_day.id if fixed_day else None,
                    filename=upload.filename, data=data,
                )
            except pip.ImportFileError as exc:
                flash(str(exc), "error")
                return redirect(_entry_url(project.id, fixed_day.id if fixed_day else None))
            return redirect(url_for("production_import_sheets", project_id=project.id, token=sess.token))
        gs = _gs()
        return _render(
            "upload", project, fixed_day=fixed_day, limits=limits,
            can_create_days=account_can_add_shooting_days_for(acc, project.id),
            source_tab="google" if request.args.get("source") == "google" else "file",
            google_link=(request.args.get("link") or "")[:2048],
            google_configured=bool(gs and gs.service.configured()),
            google_status=gs.service.status(acc.id) if gs else {"connected": False},
        )

    # -- 1b. Google Sheets source ----------------------------------------------------

    def _google_fail(project, day_id, link, exc) -> Response:
        flash(str(exc), "error")
        args = {"project_id": project.id, "source": "google"}
        if day_id:
            args["day_id"] = day_id
        if link:
            args["link"] = link
        return redirect(url_for("production_import_entry", **args))

    @app.route("/projects/<int:project_id>/production/days/import/google", methods=["POST"])
    def production_import_google(project_id: int):
        acc, project = _project_or_abort(project_id)
        gs = _gs()
        if gs is None:
            abort(404)
        raw_day = (request.form.get("day_id") or "").strip()
        fixed_day = None
        if raw_day:
            if not raw_day.isdigit():
                abort(404)
            fixed_day = db.session.get(ShootingDay, int(raw_day))
            if fixed_day is None or int(fixed_day.project_id) != int(project.id):
                abort(404)
        day_id = fixed_day.id if fixed_day else None
        link_text = (request.form.get("link") or "").strip()[:2048]
        try:
            link = gsc.parse_sheets_link(link_text)
        except gsc.GoogleSheetsError as exc:
            return _google_fail(project, day_id, link_text, exc)
        if not gs.service.status(acc.id)["connected"]:
            args = {"project_id": project.id, "link": link_text}
            if day_id:
                args["day_id"] = day_id
            return redirect(url_for("google_sheets_connect", **args))
        try:
            data, source = gsc.fetch_snapshot(gs.service.api(acc.id), link, limits=app.config.get("PRODUCTION_IMPORT_LIMITS"))
            sess = svc.create_session(
                project_id=project.id, account_id=acc.id, target_day_id=day_id,
                filename=source["title"], data=data, kind=pip.GSHEET, source=source,
            )
        except (gsc.GoogleSheetsError, pip.ImportFileError) as exc:
            db.session.rollback()
            return _google_fail(project, day_id, link_text, exc)
        return redirect(url_for("production_import_sheets", project_id=project.id, token=sess.token))

    @app.route("/projects/<int:project_id>/production/days/import/<token>/source", methods=["POST"])
    def production_import_source(project_id: int, token: str):
        """Load more worksheets or refresh the Google Sheets snapshot (never during execution)."""
        acc, project, sess, early = _load(project_id, token)
        if early is not None:
            return early
        opts = svc.options(sess)
        source = opts.get("source") or {}
        gs = _gs()
        if sess.file_kind != pip.GSHEET or gs is None or not source:
            abort(400)
        back = request.form.get("back") if request.form.get("back") in ("sheets", "mapping", "preview", "confirm") else "sheets"
        loaded_ids = [int(x["sheet_id"]) for x in source.get("loaded") or []]
        if request.form.get("action") == "load":
            wanted = [int(x) for x in request.form.getlist("sheet_ids") if str(x).isdigit()]
            sheet_ids = list(dict.fromkeys(loaded_ids + wanted))
        else:
            sheet_ids = loaded_ids
        link = gsc.SheetsLink(spreadsheet_id=str(source.get("spreadsheet_id") or ""), gid=source.get("gid"))
        try:
            data, new_source = gsc.fetch_snapshot(gs.service.api(acc.id), link, sheet_ids=sheet_ids,
                                                  limits=app.config.get("PRODUCTION_IMPORT_LIMITS"))
        except (gsc.GoogleSheetsError, pip.ImportFileError) as exc:
            db.session.rollback()
            flash(f"The source was not refreshed — your current snapshot is kept. {exc}", "error")
            return redirect(url_for(f"production_import_{back}", project_id=project.id, token=token))
        same = new_source["loaded"] == source.get("loaded")
        svc.replace_snapshot(sess, data, new_source)
        if sess.status == pis.STATUS_PREVIEWED:
            old = pis.jload(sess.decisions_json, {})
            try:
                plan = _rebuild(acc, project, sess)
            except (pis.ImportError_, pip.ImportFileError) as exc:
                flash(str(exc), "error")
                return redirect(url_for("production_import_mapping", project_id=project.id, token=token))
            kept = pis.jload(sess.decisions_json, {})
            reset = sum(1 for k, v in old.items() if (v or {}).get("action", "skip") != "skip" and kept.get(k) != v)
            opts = svc.options(sess)
            opts["step"] = "preview"
            svc.save_options(sess, opts, invalidate_plan=False)
            msg = "Source refreshed." + (" Nothing changed in the selected worksheets." if same else
                                         f" The comparison was rebuilt; {reset} choice(s) were reset to Keep and need review.")
            flash(msg, "info")
            return redirect(url_for("production_import_preview", project_id=project.id, token=token))
        flash("Worksheets loaded." if request.form.get("action") == "load" else "Source refreshed.", "info")
        return redirect(url_for(f"production_import_{back}", project_id=project.id, token=token))

    # -- 2. Worksheets & layout ----------------------------------------------------

    @app.route("/projects/<int:project_id>/production/days/import/<token>/sheets", methods=["GET", "POST"])
    def production_import_sheets(project_id: int, token: str):
        acc, project, sess, early = _load(project_id, token)
        if early is not None:
            return early
        opts = svc.options(sess)
        if request.method == "POST":
            form = request.form
            reparse = False
            if sess.file_kind == pip.CSV:
                enc = form.get("csv_encoding") or ""
                delim = form.get("csv_delimiter") or ""
                if enc not in {e for e, _ in pip.CSV_ENCODINGS} or delim not in {d for d, _ in pip.CSV_DELIMITERS}:
                    flash("Choose a valid encoding and delimiter.", "error")
                    return redirect(request.url)
                csv_opts = opts.setdefault("csv", {})
                reparse = enc != csv_opts.get("encoding") or delim != csv_opts.get("delimiter")
                ambiguous = csv_opts.get("encoding_ambiguous") or csv_opts.get("delimiter_ambiguous")
                csv_opts.update(encoding=enc, delimiter=delim)
                if reparse:
                    csv_opts["confirmed"] = False
                    svc.save_options(sess, opts)
                    flash("The file was read again with the new settings. Check the preview, then continue.", "info")
                    return redirect(request.url)
                if ambiguous and not form.get("csv_confirmed"):
                    flash("Check the preview below and confirm the encoding and delimiter.", "error")
                    return redirect(request.url)
                csv_opts["confirmed"] = True
            try:
                workbook = svc.workbook(sess)
            except (pis.ImportError_, pip.ImportFileError) as exc:
                flash(str(exc), "error")
                return redirect(_entry_url(project.id, sess.target_day_id))
            names = [s.name for s in workbook.sheets]
            chosen = [n for n in form.getlist("sheets") if n in names]
            if not chosen:
                flash("Select at least one worksheet.", "error")
                return redirect(request.url)
            layout = form.get("layout") if form.get("layout") in (pis.LAYOUT_TABLE, pis.LAYOUT_DAY_SHEETS) else pis.LAYOUT_TABLE
            if sess.target_day_id:
                layout = pis.LAYOUT_TABLE
            settings = opts.setdefault("sheet_settings", {})
            for idx, name in enumerate(names):
                sheet = workbook.sheets[idx]
                st = settings.setdefault(name, {})
                try:
                    header_row = int(form.get(f"header_{idx}") or st.get("header_row") or 1)
                    skip = int(form.get(f"skip_{idx}") or 0)
                except ValueError:
                    flash(f"“{name}”: header row and skipped rows must be numbers.", "error")
                    return redirect(request.url)
                if name in chosen and not (1 <= header_row <= max(1, len(sheet.rows))):
                    flash(f"“{name}”: the header row must be between 1 and {max(1, len(sheet.rows))}.", "error")
                    return redirect(request.url)
                st.update(header_row=header_row, skip_rows=max(0, min(skip, 50)))
                for key in ("unit", "day", "date"):
                    st[key] = (form.get(f"{key}_{idx}") or "").strip()[:50]
            opts.update(layout=layout, sheets=chosen, step="mapping", sheets_chosen=True)
            svc.save_options(sess, opts)
            return redirect(url_for("production_import_mapping", project_id=project.id, token=token))
        try:
            workbook = svc.workbook(sess)
        except (pis.ImportError_, pip.ImportFileError) as exc:
            flash(str(exc), "error")
            return redirect(_entry_url(project.id, sess.target_day_id))
        return _render(
            "sheets", project, sess, opts=opts, workbook=workbook,
            csv_encodings=pip.CSV_ENCODINGS, csv_delimiters=pip.CSV_DELIMITERS,
            choose_sheets=len(workbook.sheets) > 1 and (request.args.get("choose") == "1" or not opts.get("sheets_chosen")),
        )

    @app.route("/projects/<int:project_id>/production/days/import/<token>/sheets/rows")
    def production_import_sheet_rows(project_id: int, token: str):
        """Read-only preview rows of one worksheet (for "Show all rows")."""
        acc, project, sess, early = _load(project_id, token)
        if early is not None:
            abort(404)
        try:
            workbook = svc.workbook(sess)
        except (pis.ImportError_, pip.ImportFileError) as exc:
            return jsonify({"error": str(exc)}), 400
        idx = request.args.get("sheet", type=int)
        start = max(0, request.args.get("start", default=0, type=int) or 0)
        if idx is None or not (0 <= idx < len(workbook.sheets)):
            abort(404)
        rows = workbook.sheets[idx].rows
        return jsonify({
            "start": start,
            "total": len(rows),
            "rows": [[[c.kind, c.display[:500]] for c in row] for row in rows[start:]],
        })

    # -- 3. Column mapping ----------------------------------------------------------

    def _mapping_columns(sess, workbook, opts) -> list[dict]:
        merged: dict[str, dict] = {}
        for name in opts.get("sheets") or []:
            sheet = workbook.sheet(name)
            if sheet is None:
                continue
            st = (opts.get("sheet_settings") or {}).get(name) or {}
            for col in pis.sheet_columns(sheet, max(0, int(st.get("header_row") or 1) - 1)):
                if not col["header"] and not col["has_data"]:
                    continue
                item = merged.setdefault(col["key"], {"key": col["key"], "header": col["header"] or f"Column {col['letter']}", "sheets": [], "letters": [], "samples": []})
                item["sheets"].append(name)
                item["letters"].append(col["letter"])
                for s in col["samples"]:
                    if len(item["samples"]) < 4 and s not in item["samples"]:
                        item["samples"].append(s)
        return list(merged.values())

    @app.route("/projects/<int:project_id>/production/days/import/<token>/mapping", methods=["GET", "POST"])
    def production_import_mapping(project_id: int, token: str):
        acc, project, sess, early = _load(project_id, token)
        if early is not None:
            return early
        opts = svc.options(sess)
        pctx = svc.project_context(project.id)
        try:
            workbook = svc.workbook(sess)
        except (pis.ImportError_, pip.ImportFileError) as exc:
            flash(str(exc), "error")
            return redirect(_entry_url(project.id, sess.target_day_id))
        columns = _mapping_columns(sess, workbook, opts)
        suggested = pin.suggest_mapping([c["header"] for c in columns], is_tv=pctx["is_tv"])
        suggested_by_key = {columns[i]["key"]: f for i, f in suggested.items()}
        fixed = bool(sess.target_day_id)
        allowed_fields = [
            f for f in pin.FIELDS
            if not (f.tv_only and not pctx["is_tv"]) and not (fixed and f.level == pin.DAY_LEVEL)
        ]
        allowed_keys = {f.key for f in allowed_fields}
        errors: list[str] = []
        if request.method == "POST":
            form = request.form
            action = form.get("action") or "continue"
            if action == "apply_preset":
                preset = svc.Preset.query.filter_by(id=int(form.get("preset_id") or 0), project_id=project.id).first()
                if preset is None:
                    flash("Choose a preset.", "error")
                else:
                    pm = pis.jload(preset.mapping_json, {})
                    po = pis.jload(preset.options_json, {})
                    opts["mapping"] = {c["key"]: pm.get(c["key"], "") for c in columns if pm.get(c["key"], "") in allowed_keys}
                    opts["parse"] = po.get("parse") or opts.get("parse") or {}
                    opts["defaults"] = {**(opts.get("defaults") or {}), **(po.get("defaults") or {})}
                    if not fixed:
                        by_sheet = po.get("fill_down_by_sheet") or {}
                        generic = [f for f in po.get("fill_down_fields") or [] if f in pin.FILL_DOWN_FIELDS]
                        for sheet_name in opts.get("sheets") or []:
                            st = opts.setdefault("sheet_settings", {}).setdefault(sheet_name, {})
                            saved = by_sheet.get(sheet_name)
                            if saved is not None:
                                st["fill_down"] = [f for f in saved.get("fill_down") or [] if f in pin.FILL_DOWN_FIELDS]
                                st["fill_location_across_days"] = bool(saved.get("fill_location_across_days"))
                            elif "fill_down_fields" in po:
                                st["fill_down"] = list(generic)
                    opts["mapping_touched"] = True
                    svc.save_options(sess, opts)
                    flash(f"Preset “{preset.name}” applied — {_interpretation_text(opts)}. Review every column before continuing.", "info")
                return redirect(request.url)
            if action == "remove_preset":
                preset = svc.Preset.query.filter_by(id=int(form.get("preset_id") or 0), project_id=project.id).first()
                if preset is not None:
                    db.session.delete(preset)
                    db.session.commit()
                    flash("Preset removed.", "info")
                return redirect(request.url)
            mapping = {}
            for c in columns:
                val = form.get(f"map__{c['key']}", "")
                mapping[c["key"]] = val if val in allowed_keys else ""
            defaults = {}
            for key in ("unit_number", "day_name", "shooting_date", "item_type", "episode"):
                if key in allowed_keys:
                    defaults[key] = (form.get(f"default__{key}") or "").strip()[:50]
            old_parse = opts.get("parse") or {}
            parse = {
                "date_order": form.get("date_order") if form.get("date_order") in {k for k, _ in pin.DATE_ORDERS} else "",
                "duration_format": form.get("duration_format") if form.get("duration_format") in {k for k, _ in pin.DURATION_FORMATS} else "auto",
                "excel_time_mode": form.get("excel_time_mode") if form.get("excel_time_mode") in {k for k, _ in pin.EXCEL_TIME_MODES} else "",
                "true_tokens": [t.strip() for t in (form.get("true_tokens") or "").split(",") if t.strip()] or list(pin.DEFAULT_TRUE_TOKENS),
                "false_tokens": [t.strip() for t in (form.get("false_tokens") or "").split(",") if t.strip()] or list(pin.DEFAULT_FALSE_TOKENS),
                "blank_tokens": ([t.strip() for t in (form.get("blank_tokens") or "").split(",") if t.strip()]
                                 if "blank_tokens" in form else list(old_parse.get("blank_tokens") or pin.DEFAULT_BLANK_TOKENS)),
            }
            overlap = {pin.token_key(t) for t in parse["true_tokens"]} & {pin.token_key(t) for t in parse["false_tokens"]}
            field_tokens, token_errors = _form_field_tokens(form, old_parse.get("field_tokens") or {})
            parse["field_tokens"] = field_tokens
            errors.extend(token_errors)
            if not fixed:
                for idx, sheet_name in enumerate(n for n in (opts.get("sheets") or [])):
                    if form.get(f"fill_seen__{idx}") != "1":
                        continue
                    mode = form.get(f"fill_mode__{idx}") or ""
                    st = opts.setdefault("sheet_settings", {}).setdefault(sheet_name, {})
                    chosen = [f for f in form.getlist(f"fill__{idx}") if f in pin.FILL_DOWN_FIELDS]
                    if mode == "off":
                        st["fill_down"] = []
                    elif mode == "fill":
                        if not chosen:
                            errors.append(f"“{sheet_name}”: tick the columns to fill down, or choose “Keep blank cells blank”.")
                        st["fill_down"] = chosen
                    else:
                        st.pop("fill_down", None)
                    st["fill_location_across_days"] = form.get(f"fill_across__{idx}") == "1"
            opts.update(mapping=mapping, defaults=defaults, parse=parse, mapping_touched=True)
            if overlap:
                errors.append("These values are in both the Yes and No lists: " + ", ".join(sorted(overlap)) + ".")
            if action == "save_preset":
                if not errors:
                    try:
                        svc.save_preset(project.id, acc.id, form.get("preset_name") or "", opts)
                        flash("Mapping preset saved for this project.", "success")
                    except pis.ImportError_ as exc:
                        errors.append(str(exc))
                svc.save_options(sess, opts)
                if not errors:
                    return redirect(request.url)
            elif action == "examples":
                svc.save_options(sess, opts)
                return redirect(request.url + "#examples")
            else:
                svc.save_options(sess, opts)
                errors.extend(_mapping_errors(sess, workbook, opts, columns, pctx))
                if not errors:
                    opts["step"] = "preview"
                    opts["day_decisions"] = {}
                    svc.save_options(sess, opts)
                    return redirect(url_for("production_import_preview", project_id=project.id, token=token))
        current = opts.get("mapping") if opts.get("mapping_touched") else suggested_by_key
        examples = pis.scan_examples(svc, sess, workbook, pctx, mapping=dict(current or {}))
        prep = _preparation_summary(sess, workbook, pctx) if opts.get("mapping_touched") else None
        return _render(
            "mapping", project, sess, opts=opts, columns=columns, current_mapping=current or {},
            suggested=suggested_by_key, allowed_fields=allowed_fields, examples=examples, errors=errors,
            presets=svc.presets(project.id), date_orders=pin.DATE_ORDERS, duration_formats=pin.DURATION_FORMATS,
            excel_time_modes=pin.EXCEL_TIME_MODES, is_tv=pctx["is_tv"],
            true_tokens=", ".join((opts.get("parse") or {}).get("true_tokens") or pin.DEFAULT_TRUE_TOKENS),
            false_tokens=", ".join((opts.get("parse") or {}).get("false_tokens") or pin.DEFAULT_FALSE_TOKENS),
            blank_tokens=", ".join((opts.get("parse") or {}).get("blank_tokens") or pin.DEFAULT_BLANK_TOKENS),
            token_choices=pin.TOKEN_CHOICES, item_types=pim.si.SHOOTING_ITEM_TYPE_CHOICES,
            field_tokens=(opts.get("parse") or {}).get("field_tokens") or {}, prep=prep,
            summary_columns={c["key"] for c in columns if pin.is_summary_header(c["header"])},
        )

    def _form_field_tokens(form, existing: dict) -> tuple[dict, list[str]]:
        """Per-field status meanings from the form (tok__<field>__<n> + tokname__<field>__<n>)."""
        out: dict[str, dict[str, str]] = {f: dict(m) for f, m in existing.items()
                                          if f in pin.FIELD_BY_KEY and isinstance(m, dict)}
        errors: list[str] = []
        seen: dict[tuple[str, str], str] = {}
        for name in form:
            if not name.startswith("tokname__"):
                continue
            _p, fkey, n = (name.split("__") + ["", ""])[:3]
            if fkey not in pin.FIELD_BY_KEY or pin.FIELD_BY_KEY[fkey].kind != "bool":
                continue
            tok = pin.token_key(form.get(name) or "")
            meaning = form.get(f"tok__{fkey}__{n}") or ""
            if not tok:
                continue
            if meaning and (fkey, tok) in seen and seen[(fkey, tok)] != meaning:
                errors.append(f"{pin.FIELD_BY_KEY[fkey].label}: “{form.get(name)}” was given two different meanings.")
                continue
            field_map = out.setdefault(fkey, {})
            if meaning in (pin.TOKEN_YES, pin.TOKEN_NO, pin.TOKEN_IGNORE):
                field_map[tok] = meaning
                seen[(fkey, tok)] = meaning
            else:
                field_map.pop(tok, None)
        return {f: m for f, m in out.items() if m}, errors

    def _interpretation_text(opts: dict) -> str:
        parse = opts.get("parse") or {}
        bits = []
        mode = dict(pin.EXCEL_TIME_MODES).get(parse.get("excel_time_mode") or "")
        bits.append("Excel times: " + (mode.split(" — ")[0] if mode else "not set"))
        for fkey, mapping in (parse.get("field_tokens") or {}).items():
            if fkey in pin.FIELD_BY_KEY and mapping:
                bits.append(pin.FIELD_BY_KEY[fkey].label + ": " + ", ".join(f"“{t}” = {m}" for t, m in sorted(mapping.items())))
        fills = sorted({pin.FIELD_BY_KEY[f].label for st in (opts.get("sheet_settings") or {}).values()
                        for f in (st.get("fill_down") or []) if f in pin.FIELD_BY_KEY})
        bits.append("fill-down: " + (", ".join(fills) if fills else "off"))
        return "; ".join(bits)

    def _preparation_summary(sess, workbook, pctx) -> dict | None:
        """What preview will see with the current settings (counts only; nothing is saved)."""
        try:
            rows, meta = svc.source_rows(sess, workbook, pctx)
        except Exception:  # noqa: BLE001 - summary is informational
            return None
        prep = meta.get("preparation") or {}
        invalid = sum(1 for r in rows if r.errors)
        return {
            "rows": len(rows), "invalid": invalid, "sheets": prep.get("sheets") or [],
            "ignored": len(meta.get("ignored_columns") or []),
            "unresolved_day": sum(s.get("unresolved_day", 0) for s in prep.get("sheets") or []),
        }

    def _mapping_errors(sess, workbook, opts, columns, pctx) -> list[str]:
        errors = []
        mapping = opts.get("mapping") or {}
        for name in opts.get("sheets") or []:
            sheet = workbook.sheet(name)
            st = (opts.get("sheet_settings") or {}).get(name) or {}
            seen: dict[str, str] = {}
            for col in pis.sheet_columns(sheet, max(0, int(st.get("header_row") or 1) - 1)) if sheet else []:
                f = mapping.get(col["key"]) or ""
                if not f:
                    continue
                if f in seen:
                    errors.append(f"“{name}”: columns {seen[f]} and {col['letter']} are both mapped to {pin.FIELD_BY_KEY[f].label}.")
                seen[f] = col["letter"]
        mapped = {v for v in mapping.values() if v}
        defaults = opts.get("defaults") or {}
        if "scene_label" not in mapped:
            errors.append("Map the Scene / description column.")
        if pctx["is_tv"] and pctx["max_episode"] < 1:
            errors.append("This TV series has no number of episodes set, so no episode can be accepted. "
                          "Set “Number of episodes” in the project settings, then continue.")
        if not sess.target_day_id:
            per_sheet = opts.get("layout") == pis.LAYOUT_DAY_SHEETS
            sheets = opts.get("sheets") or []
            settings = opts.get("sheet_settings") or {}
            for key, skey, label in (("unit_number", "unit", "unit"), ("day_name", "day", "shooting day")):
                if key in mapped or (defaults.get(key) or "").strip():
                    continue
                if per_sheet and all((settings.get(n) or {}).get(skey) for n in sheets):
                    continue
                errors.append(f"Map a {label} column, enter a default {label}, or set it for every worksheet.")
        scan = pis.scan_examples(svc, sess, workbook, pctx)
        parse = opts.get("parse") or {}
        if scan["date_ambiguous"] and not parse.get("date_order"):
            errors.append(f"{scan['date_ambiguous']} date(s) could be read as day/month or month/day. Choose the date order.")
        if scan["duration_needs_choice"] and not parse.get("excel_time_mode"):
            errors.append(
                f"{scan['time_cells']} duration cell(s) are Excel time-of-day values. Confirm how to read them "
                "under “Durations” (the examples show the result of each choice)."
            )
        unknown = [f"{t['label']}: " + ", ".join(f"“{i['display']}” ({i['count']})" for i in t["items"] if not i["meaning"])
                   for t in scan["tokens"].values() if any(not i["meaning"] for i in t["items"])]
        if unknown:
            errors.append("Define these status values under “Status values”, or set the column to Don't import — "
                          + "; ".join(unknown) + ".")
        settings = opts.get("sheet_settings") or {}
        for sheet_name, cands in scan["fill_candidates"].items():
            suggested = [c["label"] for c in cands if c["suggested"]]
            if suggested and "fill_down" not in (settings.get(sheet_name) or {}):
                errors.append(f"“{sheet_name}”: {', '.join(suggested)} are only filled at the start of each group. "
                              "Choose under “Fill down” whether to carry them to the rows below.")
        return errors

    # -- 4. Preview & compare --------------------------------------------------------

    def _can_create(acc, project, sess) -> bool:
        return not sess.target_day_id and account_can_add_shooting_days_for(acc, project.id)

    def _rebuild(acc, project, sess, *, keep_decisions: bool = True) -> dict:
        old_plan = pis.jload(sess.plan_json, {}) if sess.plan_json else {}
        old_decisions = pis.jload(sess.decisions_json, {})
        plan, _ = svc.build_plan(sess, can_create_days=_can_create(acc, project, sess))
        decisions = pim.default_decisions(plan)
        if keep_decisions and old_plan:
            old_fp = {r["id"]: r.get("fingerprint") for r in old_plan.get("rows", [])}
            for r in plan["rows"]:
                if old_fp.get(r["id"]) == r["fingerprint"] and r["id"] in old_decisions:
                    decisions[r["id"]] = old_decisions[r["id"]]
        svc.store_plan(sess, plan, decisions)
        return plan

    @app.route("/projects/<int:project_id>/production/days/import/<token>/preview", methods=["GET", "POST"])
    def production_import_preview(project_id: int, token: str):
        acc, project, sess, early = _load(project_id, token)
        if early is not None:
            return early
        opts = svc.options(sess)
        if (opts.get("step") or "") not in ("preview", "confirm"):
            return redirect(url_for("production_import_mapping", project_id=project.id, token=token))
        if request.method == "POST":
            action = request.form.get("action") or ""
            if action == "days_all":
                plan = svc.stored_plan(sess) if sess.plan_json else {"days": []}
                error = _apply_days_to_all(plan, opts, request.form, can_create=_can_create(acc, project, sess))
                if error:
                    flash(error, "error")
                    return redirect(url_for("production_import_preview", project_id=project.id, token=token) + "#days")
                svc.save_options(sess, opts, invalidate_plan=False)
                try:
                    _rebuild(acc, project, sess)
                except (pis.ImportError_, pip.ImportFileError) as exc:
                    flash(str(exc), "error")
                return redirect(url_for("production_import_preview", project_id=project.id, token=token) + "#days")
            if action == "days":
                plan = svc.stored_plan(sess) if sess.plan_json else {"days": []}
                decisions = opts.get("day_decisions") or {}
                for g in plan.get("days", []):
                    k = g["key"]
                    choice = request.form.get(f"day_choice__{k}", "")
                    entry = {"choice": choice} if choice else {}
                    if choice == "create":
                        entry.update(day_name=(request.form.get(f"day_name__{k}") or "").strip()[:50], date=(request.form.get(f"day_date__{k}") or "").strip()[:10])
                    if request.form.get(f"day_location__{k}"):
                        entry["update_location"] = True
                    if entry:
                        decisions[k] = entry
                    else:
                        decisions.pop(k, None)
                opts["day_decisions"] = decisions
                svc.save_options(sess, opts, invalidate_plan=False)
                try:
                    _rebuild(acc, project, sess)
                except (pis.ImportError_, pip.ImportFileError) as exc:
                    flash(str(exc), "error")
                return redirect(url_for("production_import_preview", project_id=project.id, token=token) + "#days")
            if action == "refresh":
                try:
                    _rebuild(acc, project, sess)
                    flash("Compared again with the current project data.", "info")
                except (pis.ImportError_, pip.ImportFileError) as exc:
                    flash(str(exc), "error")
                return redirect(url_for("production_import_preview", project_id=project.id, token=token))
            if action == "decisions":
                try:
                    plan = svc.stored_plan(sess)
                except pis.ImportError_ as exc:
                    flash(str(exc), "error")
                    return redirect(request.url)
                if request.form.get("plan_hash") != sess.plan_hash:
                    flash("The comparison changed in another window. Review it again.", "error")
                    return redirect(request.url)
                try:
                    raw = json.loads(request.form.get("decisions") or "{}")
                except ValueError:
                    raw = {}
                valid, errors = pim.validate_decisions(plan, raw if isinstance(raw, dict) else {})
                merged = {**pis.jload(sess.decisions_json, {}), **{k: v for k, v in (raw if isinstance(raw, dict) else {}).items() if isinstance(v, dict)}}
                sess.decisions_json = pis.jdump(merged)
                db.session.commit()
                if errors:
                    for e in errors[:8]:
                        flash(e, "error")
                    if len(errors) > 8:
                        flash(f"…and {len(errors) - 8} more.", "error")
                    return redirect(request.url)
                sess.decisions_json = pis.jdump(valid)
                opts["step"] = "confirm"
                svc.save_options(sess, opts, invalidate_plan=False)
                return redirect(url_for("production_import_confirm", project_id=project.id, token=token))
            abort(400)
        try:
            if sess.status != pis.STATUS_PREVIEWED or not sess.plan_json:
                plan = _rebuild(acc, project, sess, keep_decisions=True)
            else:
                plan = svc.stored_plan(sess)
        except (pis.ImportError_, pip.ImportFileError) as exc:
            flash(str(exc), "error")
            return redirect(url_for("production_import_mapping", project_id=project.id, token=token))
        all_days = ShootingDay.query.filter_by(project_id=project.id).order_by(ShootingDay.unit_number, ShootingDay.shooting_date, ShootingDay.id).all()
        return _render(
            "preview", project, sess, opts=opts, plan=plan, decisions=pis.jload(sess.decisions_json, {}),
            all_days=all_days, can_create_days=_can_create(acc, project, sess), weekdays=WEEKDAYS,
        )

    # -- 5. Confirm ------------------------------------------------------------------

    @app.route("/projects/<int:project_id>/production/days/import/<token>/confirm", methods=["GET", "POST"])
    def production_import_confirm(project_id: int, token: str):
        acc, project, sess, early = _load(project_id, token)
        if early is not None:
            return early
        try:
            plan = svc.stored_plan(sess)
        except pis.ImportError_ as exc:
            flash(str(exc), "error")
            return redirect(url_for("production_import_preview", project_id=project.id, token=token))
        decisions = pis.jload(sess.decisions_json, {})
        valid, errors = pim.validate_decisions(plan, decisions)
        if errors:
            for e in errors[:5]:
                flash(e, "error")
            return redirect(url_for("production_import_preview", project_id=project.id, token=token))
        freshness = None
        if sess.file_kind == pip.GSHEET:
            source = svc.options(sess).get("source") or {}
            fresh = source.get("freshness") or {}
            if fresh.get("snapshot") != sess.file_sha256:
                fresh = {}
            if request.method == "GET" or not fresh:
                fresh = _check_source(acc, sess, plan)
            freshness = fresh
            if request.method == "POST" and fresh.get("state") != "unchanged" and request.form.get("ack_source") != "1":
                flash("Confirm that you want to import the reviewed snapshot, or refresh the source first.", "error")
                return redirect(request.url)
        if request.method == "POST":
            try:
                result = svc.execute(
                    sess, account=acc, posted_hash=request.form.get("plan_hash") or "",
                    can_create_days=_can_create(acc, project, sess), hooks=_hooks(),
                )
            except pis.AlreadyExecuted as exc:
                sess = svc.get_session(token)
                if sess is not None and sess.status == pis.STATUS_EXECUTED:
                    flash("This import was already completed.", "info")
                    return redirect(url_for("production_import_results", project_id=project.id, token=token))
                flash(str(exc), "error")
                return redirect(request.url)
            except pis.NeedsReview as exc:
                flash(str(exc), "error")
                return redirect(url_for("production_import_preview", project_id=project.id, token=token))
            except pis.ImportError_ as exc:
                flash(str(exc), "error")
                return redirect(request.url)
            _after_commit(acc, project, sess, result)
            return redirect(url_for("production_import_results", project_id=project.id, token=token))
        summary = pim.summarize_decisions(plan, valid)
        rows_by_id = {r["id"]: r for r in plan["rows"]}
        updates = []
        for rid, d in valid.items():
            if d["action"] != pim.ACTION_UPDATE:
                continue
            r = rows_by_id[rid]
            diffs = r["diffs"] if r.get("match") and r["match"]["id"] == d["target_id"] else next(
                (c["diffs"] for c in r.get("candidates", []) if c["id"] == d["target_id"]), [])
            clr = r["clearable"] if r.get("match") and r["match"]["id"] == d["target_id"] else next(
                (c["clearable"] for c in r.get("candidates", []) if c["id"] == d["target_id"]), [])
            updates.append({
                "row": r, "target_id": d["target_id"],
                "fields": [x for x in diffs if x["field"] in d["fields"]],
                "clears": [x for x in clr if x["field"] in d.get("clear", [])],
            })
        adds = [rows_by_id[rid] | {"_action": d["action"]} for rid, d in valid.items() if d["action"] in (pim.ACTION_ADD, pim.ACTION_ADD_RESHOOT)]
        identity_changes = sum(1 for u in updates if any(f["identity"] for f in u["fields"]))
        new_days = [g for g in plan["days"] if g.get("target") and g["target"]["kind"] == "new"
                    and any(rows_by_id[rid].get("day_key") == g["key"] for rid, d in valid.items() if d["action"] in (pim.ACTION_ADD, pim.ACTION_ADD_RESHOOT))]
        return _render(
            "confirm", project, sess, plan=plan, summary=summary, updates=updates, adds=adds,
            identity_changes=identity_changes, new_days=new_days, freshness=freshness,
        )

    def _check_source(acc, sess, plan) -> dict:
        """Compare the reviewed snapshot with Google now. Never changes the snapshot."""
        opts = svc.options(sess)
        source = opts.get("source") or {}
        gs = _gs()
        if gs is None or not gs.service.status(acc.id)["connected"]:
            fresh = {"state": "failed", "code": "not_connected", "changed": [],
                     "message": "Google Sheets is not connected, so BigBang could not check whether the source changed."}
        else:
            fresh = gsc.check_freshness(gs.service.api(acc.id), source, list(plan.get("worksheets") or []),
                                        limits=app.config.get("PRODUCTION_IMPORT_LIMITS"))
        fresh["snapshot"] = sess.file_sha256
        source["freshness"] = fresh
        opts["source"] = source
        svc.save_options(sess, opts, invalidate_plan=False)
        return fresh

    # -- 6. Results ------------------------------------------------------------------

    @app.route("/projects/<int:project_id>/production/days/import/<token>/results")
    def production_import_results(project_id: int, token: str):
        acc, project, sess, _early = _load(project_id, token, allow_closed=True)
        if sess.status != pis.STATUS_EXECUTED:
            return redirect(url_for("production_import_preview", project_id=project.id, token=token))
        result = pis.jload(sess.result_json, {})
        return _render("results", project, sess, result=result)

    @app.route("/projects/<int:project_id>/production/days/import/<token>/results.csv")
    def production_import_results_csv(project_id: int, token: str):
        acc, project, sess, _early = _load(project_id, token, allow_closed=True)
        if sess.status != pis.STATUS_EXECUTED:
            abort(404)
        body = pis.results_csv(pis.jload(sess.result_json, {}))
        base = os.path.splitext(os.path.basename(sess.original_filename or "import"))[0][:60] or "import"
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in base)
        return Response(
            body, mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe}-import-results.csv"', "X-Content-Type-Options": "nosniff"},
        )

    @app.route("/projects/<int:project_id>/production/days/import/<token>/cancel", methods=["POST"])
    def production_import_cancel(project_id: int, token: str):
        acc, project, sess, early = _load(project_id, token)
        if early is not None:
            return early
        day_id = sess.target_day_id
        svc.cancel(sess)
        flash("Import cancelled. Nothing was changed.", "info")
        if day_id:
            return redirect(url_for("project_production_day", project_id=project.id, day_id=day_id))
        return redirect(url_for("project_production", project_id=project.id))

    # -- after commit -----------------------------------------------------------------

    def _log_summary(sess, result: dict) -> None:
        import project_activity_events as pae
        import project_activity_hooks as pah

        c = result["counts"]
        pah._log(
            project_id=int(sess.project_id),
            event_type=pae.SHOOTING_DAY_IMPORT_COMPLETED,
            module=pae.MODULE_SHOOTING,
            action="completed",
            entity_type="production_import",
            entity_id=int(sess.id),
            entity_label=sess.original_filename,
            metadata={
                "file": sess.original_filename,
                "file_sha256": sess.file_sha256,
                "worksheets": result.get("worksheets", []),
                "days_created": c["days_created"],
                "rows_added": c["rows_added"],
                "rows_updated": c["rows_updated"],
                "rows_skipped": c["rows_skipped"],
                "created_day_ids": [d["id"] for d in result.get("created_days", [])],
                "shooting_day_ids": [d["id"] for d in result.get("days", [])],
                "import_session_id": int(sess.id),
                "source": result.get("source") or {},
            },
            status=pae.STATUS_COMPLETED,
        )

    def _after_commit(acc, project, sess, result: dict) -> None:
        if result.get("needs_vfx_bridge") and ensure_vfx_bridge is not None:
            try:
                ensure_vfx_bridge(int(project.id))
            except Exception:
                app.logger.exception("VFX bridge refresh after import failed")
        _notify_completed(acc, project, sess, result)

    def _notify_completed(acc, project, sess, result: dict) -> None:
        c = result["counts"]
        if send_managed_notification is None or not (c["days_created"] or c["rows_added"] or c["rows_updated"]):
            return
        parts = []
        if c["days_created"]:
            parts.append(f"{c['days_created']} new shooting day(s)")
        if c["rows_added"]:
            parts.append(f"{c['rows_added']} row(s) added")
        if c["rows_updated"]:
            parts.append(f"{c['rows_updated']} row(s) updated")
        title = f"{project.name or 'Project'} · Production import"
        origin = sess.original_filename + (" (Google Sheets)" if sess.file_kind == pip.GSHEET else "")
        body = f"Imported from {origin}: " + ", ".join(parts) + "."
        recipients = [
            int(uid) for (uid,) in db.session.execute(
                text("SELECT user_id FROM project_members WHERE project_id = :pid"), {"pid": int(project.id)}
            ) if uid is not None
        ]
        try:
            sent = send_managed_notification(
                pis.NOTIFY_EVENT_KEY,
                project=project,
                actor=acc,
                context={
                    "notification_title": title,
                    "notification_body": body,
                    "notification_severity": "info",
                    "entity_type": "production_import",
                    "entity_id": int(sess.id),
                    "rule_entity_id": int(sess.id),
                    "import_file": sess.original_filename,
                    "import_summary": ", ".join(parts),
                },
                fallback_title=title,
                fallback_body=body,
                fallback_recipient_user_ids=recipients,
            )
            if sent and notification_push_realtime_for_project:
                notification_push_realtime_for_project(int(project.id), actor=acc)
        except Exception:
            app.logger.exception("Production import notification failed")

    api = SimpleNamespace(service=svc)
    app.extensions["production_import"] = api
    return api
