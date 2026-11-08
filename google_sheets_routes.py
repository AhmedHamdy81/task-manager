"""Connect / disconnect Google Sheets for the signed-in BigBang account.

Web: the consent runs in the same browser and the callback must come back to the same
BigBang account and browser. Desktop (Electron): Google refuses embedded sign-in, so the
app opens a single-use handoff link in the system browser; that browser only completes
Google consent for the account that started it — it is never signed in to BigBang.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from flask import Flask, abort, flash, jsonify, make_response, redirect, render_template, request, session, url_for

import google_sheets_service as gss


def register_google_sheets_routes(app: Flask, ctx: dict) -> SimpleNamespace:
    db = ctx["db"]
    Project = ctx["Project"]
    ShootingDay = ctx["ShootingDay"]
    account_from_session = ctx["account_from_session"]
    account_can_access_project = ctx["account_can_access_project"]

    svc = gss.ConnectionService(
        db=db,
        now_local=ctx["now_local"],
        token_key=app.config.get("GOOGLE_SHEETS_TOKEN_KEY") or os.environ.get(gss.TOKEN_KEY_ENV),
        client_config=ctx["client_config"],
        http=ctx.get("http"),
    )
    if svc.cipher is None:
        app.logger.warning("Google Sheets is disabled: %s is missing or unsafe.", gss.TOKEN_KEY_ENV)

    def _is_desktop() -> bool:
        return "Electron/" in (request.user_agent.string or "") or request.args.get("desktop") == "1"

    def _context(acc) -> tuple[int | None, int | None, str]:
        """Return target inside a project the account may see; anything else is dropped."""
        pid = request.values.get("project_id", type=int)
        did = request.values.get("day_id", type=int)
        link = (request.values.get("link") or "").strip()[:2048]
        if pid is None or db.session.get(Project, pid) is None or not account_can_access_project(acc, pid):
            return None, None, ""
        if did is not None:
            day = db.session.get(ShootingDay, did)
            if day is None or int(day.project_id) != pid:
                did = None
        return pid, did, link

    def _return_url(project_id, day_id, link) -> str:
        if not project_id:
            return url_for("index")
        args = {"project_id": project_id, "source": "google"}
        if day_id:
            args["day_id"] = day_id
        if link:
            args["link"] = link
        return url_for("production_import_entry", **args)

    def _with_binding(resp, binding: str):
        resp.set_cookie(
            gss.BINDING_COOKIE, binding, max_age=int(gss.STATE_TTL.total_seconds()), httponly=True,
            secure=request.is_secure, samesite="Lax", path="/integrations/google-sheets/",
        )
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    @app.route("/integrations/google-sheets/connect")
    def google_sheets_connect():
        acc = account_from_session()
        if acc is None:
            abort(403)
        pid, did, link = _context(acc)
        try:
            if _is_desktop():
                token = svc.create_handoff(account_id=acc.id, project_id=pid, day_id=did, link=link)
                row = svc.OAuthState.query.filter_by(handoff_hash=gss._sha(token)).first()
                resp = make_response(render_template(
                    "google_sheets_handoff.html",
                    handoff_url=url_for("google_sheets_browser_start", token=token, _external=True),
                    status_url=url_for("google_sheets_handoff_status", row_id=row.id),
                    return_url=_return_url(pid, did, link),
                ))
                resp.headers["Cache-Control"] = "no-store"
                return resp
            url, binding = svc.begin_web(
                account_id=acc.id, project_id=pid, day_id=did, link=link,
                redirect_uri=url_for("google_sheets_callback", _external=True),
            )
        except gss.ConnectError as exc:
            flash(str(exc), "error")
            return redirect(_return_url(pid, did, link))
        return _with_binding(redirect(url), binding)

    @app.route("/integrations/google-sheets/browser/<token>")
    def google_sheets_browser_start(token: str):
        try:
            url, binding = svc.consume_handoff(token, redirect_uri=url_for("google_sheets_callback", _external=True))
        except gss.ConnectError as exc:
            return _result_page(False, str(exc), 400, clear_binding=False)
        return _with_binding(redirect(url), binding)

    def _result_page(ok: bool, message: str, status: int = 200, *, clear_binding: bool = True):
        resp = make_response(render_template("google_sheets_connected.html", ok=ok, message=message), status)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if clear_binding:
            resp.delete_cookie(gss.BINDING_COOKIE, path="/integrations/google-sheets/")
        return resp

    @app.route("/integrations/google-sheets/callback")
    def google_sheets_callback():
        state = request.args.get("state") or ""
        row = svc.OAuthState.query.filter_by(state_hash=gss._sha(state)).first() if state else None
        mode = row.mode if row is not None else gss.MODE_DESKTOP
        try:
            row = svc.complete(
                state=state,
                code=request.args.get("code") or "",
                error=(request.args.get("error") or "").strip(),
                binding=request.cookies.get(gss.BINDING_COOKIE, ""),
                session_account_id=session.get("account_id"),
                redirect_uri=url_for("google_sheets_callback", _external=True),
            )
        except gss.ConnectError as exc:
            db.session.rollback()
            if mode == gss.MODE_WEB and row is not None and session.get("account_id") == row.account_id:
                flash(str(exc), "error")
                resp = redirect(_return_url(row.project_id, row.day_id, row.link))
                resp.delete_cookie(gss.BINDING_COOKIE, path="/integrations/google-sheets/")
                return resp
            return _result_page(False, str(exc), 400)
        except Exception:
            db.session.rollback()
            app.logger.exception("Google Sheets connection failed")
            return _result_page(False, "The Google connection failed. Try again.", 500)
        if row.mode == gss.MODE_DESKTOP:
            return _result_page(True, "Google Sheets is connected. Return to BigBang Desktop to continue — you can close this tab.")
        flash("Google Sheets connected.", "success")
        resp = redirect(_return_url(row.project_id, row.day_id, row.link))
        resp.delete_cookie(gss.BINDING_COOKIE, path="/integrations/google-sheets/")
        return resp

    @app.route("/integrations/google-sheets/handoff/<int:row_id>/status")
    def google_sheets_handoff_status(row_id: int):
        acc = account_from_session()
        row = db.session.get(svc.OAuthState, row_id)
        if acc is None or row is None or int(row.account_id) != int(acc.id):
            abort(404)
        return jsonify({"result": row.result or ("started" if row.handoff_used_at else "waiting")})

    @app.route("/integrations/google-sheets/disconnect", methods=["POST"])
    def google_sheets_disconnect():
        acc = account_from_session()
        if acc is None:
            abort(403)
        pid, did, link = _context(acc)
        try:
            disconnected = svc.disconnect(acc.id)
        except gss.ConnectError as exc:
            flash(str(exc), "error")
            return redirect(_return_url(pid, did, link))
        if disconnected:
            flash("Google Sheets disconnected. BigBang no longer has access to your spreadsheets; imports already done are kept.", "info")
        return redirect(_return_url(pid, did, link))

    api = SimpleNamespace(service=svc)
    app.extensions["google_sheets"] = api
    return api
