"""System Setup — master data health page, seed route, and CLI."""

from __future__ import annotations

import os

import click
from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.routing import BuildError

import mail_service as mail_service_mod
import mail_settings as mail_settings_mod
import folder_structure_support as folder_structure_support_mod
import system_seed as sseed


SEED_CONFIRM_MESSAGE = (
    "This will add missing essential setup data only. "
    "It will not delete projects, users, tasks, VFX, color, chat, bookings, or files."
)

# Legacy ?section= values still accepted for redirects to dedicated pages.
SYSTEM_SETUP_SECTIONS = frozenset(
    {
        "overview",
        "connection",
        "email",
        "upload",
        "project-folders",
        "health",
        "working-hours",
        "industry",
    }
)
SYSTEM_SETUP_PAGES = frozenset(
    {"email", "connection", "upload", "project-folders", "health"}
)
SYSTEM_SETUP_PAGE_ENDPOINTS = {
    "email": "control_system_setup_email",
    "connection": "control_system_setup_connection",
    "upload": "control_system_setup_upload",
    "project-folders": "control_system_setup_project_folders",
    "health": "control_system_setup_health",
}


def register_system_seed_routes(app, ctx: dict) -> None:
    db = ctx["db"]
    models = ctx["system_seed_models"]
    Project = ctx["Project"]
    account_from_session = ctx["account_from_session"]
    account_can_access_admin_settings = ctx["account_can_access_admin_settings"]
    log_security_event = ctx.get("log_security_event")
    register_safe_delete_entity = app.extensions.get("register_safe_delete_entity")
    safe_delete_guard = app.extensions.get("safe_delete_guard")
    safe_delete_service = app.extensions.get("safe_delete_service")
    # Application root (mail secret file lives under instance/).
    app_root = os.path.dirname(os.path.abspath(__file__))

    def _admin_required():
        acc = account_from_session()
        if not account_can_access_admin_settings(acc):
            abort(403)
        return acc

    def _request_is_local_host() -> bool:
        """True when the browser is on the same machine as this server process."""
        return (request.remote_addr or "").strip() in {"127.0.0.1", "::1"}

    def _wants_json() -> bool:
        accept = (request.headers.get("Accept") or "").lower()
        return request.is_json or "application/json" in accept

    def _mail_form_payload() -> dict:
        return {
            "mail_enabled": request.form.get("mail_enabled") or "0",
            "mail_provider": request.form.get("mail_provider") or "custom",
            "mail_server": request.form.get("mail_server") or "",
            "mail_port": request.form.get("mail_port") or "587",
            "mail_encryption": request.form.get("mail_encryption") or "starttls",
            "mail_username": request.form.get("mail_username") or "",
            "mail_password": request.form.get("mail_password") or "",
            "mail_sender_name": request.form.get("mail_sender_name") or "",
            "mail_sender_email": request.form.get("mail_sender_email") or "",
            "public_application_url": request.form.get("public_application_url") or "",
            "mail_reset_expiry_minutes": request.form.get("mail_reset_expiry_minutes")
            or str(mail_settings_mod.DEFAULT_RESET_EXPIRY_MINUTES),
            "mail_admin_fallback": request.form.get("mail_admin_fallback") or "0",
        }

    def _upload_directory_fallback() -> str:
        return app.config.get("UPLOAD_DATA_DIR") or sseed.default_instance_directory()

    def _upload_directory_history_for_page(SystemSetting, *, fallback: str = "") -> list:
        history = list(sseed.get_upload_directory_history(SystemSetting))
        current = sseed.current_upload_directory(SystemSetting, fallback=fallback)
        if current and current not in history:
            history.insert(0, current)
        return history[: sseed.UPLOAD_DIRECTORY_HISTORY_MAX]

    def _mail_page_context() -> dict:
        mail_settings_mod.ensure_mail_setting_defaults(db, models.SystemSetting)
        mail = mail_settings_mod.resolve_mail_config(
            models.SystemSetting,
            app=app,
            app_root=app_root,
            include_password=False,
        )
        # Re-resolve with password flag for readiness only (never expose secret).
        mail_ready = mail_settings_mod.resolve_mail_config(
            models.SystemSetting,
            app=app,
            app_root=app_root,
            include_password=True,
        )
        public = mail.public_dict()
        public["password_configured"] = mail_ready.password_configured
        public["password_source"] = mail_ready.password_source
        public["password_env_locked"] = mail_ready.password_env_locked
        public["password_placeholder"] = (
            mail_settings_mod.MAIL_PASSWORD_PLACEHOLDER
            if mail_ready.password_configured
            else ""
        )
        public["can_send_test"] = mail_ready.can_send_test
        public["is_ready"] = mail_ready.is_ready
        public["status"] = "configured" if mail_ready.is_ready else "not_configured"
        return {
            "mail": public,
            "mail_providers": mail_settings_mod.PROVIDERS,
            "mail_encryption_options": mail_settings_mod.ENCRYPTION_OPTIONS,
            "mail_reset_expiry_min": mail_settings_mod.RESET_EXPIRY_MIN,
            "mail_reset_expiry_max": mail_settings_mod.RESET_EXPIRY_MAX,
            "mail_example_reset_url": mail_settings_mod.example_reset_url(
                mail.public_base_url or sseed.current_connection_http_address(
                    models.SystemSetting,
                    fallback=(request.url_root or "").rstrip("/"),
                )
            ),
            "mail_save_url": url_for("control_system_setup_email"),
            "mail_test_url": url_for("control_system_setup_email_test"),
            "mail_password_env": mail_settings_mod.MAIL_PASSWORD_ENV,
        }

    def _seed_ctx() -> dict:
        return {
            "perm_models": ctx["perm_models"],
            "JobCategory": ctx["JobCategory"],
            "JobTitle": ctx["JobTitle"],
            "TaskGroup": ctx["TaskGroup"],
            "TaskGroupTitle": ctx["TaskGroupTitle"],
            "TaskPriority": ctx["TaskPriority"],
            "IndustryNewsSource": ctx.get("IndustryNewsSource"),
            "IndustryNewsItem": ctx.get("IndustryNewsItem"),
        }

    if register_safe_delete_entity is not None:

        @register_safe_delete_entity(sseed.UPLOAD_DIRECTORY_HISTORY_SAFE_DELETE_TYPE)
        def _safe_delete_describe_upload_directory_history(
            acc, entity_id: int, project_id: int | None
        ):
            if not account_can_access_admin_settings(acc):
                return {"exists": False, "can_delete": False, "display_name": ""}
            path = sseed.upload_directory_for_history_entity_id(
                models.SystemSetting,
                entity_id,
                fallback=_upload_directory_fallback(),
            )
            if not path:
                return {"exists": False, "can_delete": False, "display_name": ""}
            return {
                "exists": True,
                "can_delete": True,
                "display_name": path,
            }

    def _setup_section_url(section: str) -> str:
        endpoint = SYSTEM_SETUP_PAGE_ENDPOINTS.get(section) or "control_system_setup_email"
        return url_for(endpoint)

    def _legacy_section_redirect():
        section = (request.args.get("section") or "").strip().lower()
        if section == "working-hours" or section == "industry" or section == "overview":
            section = "health"
        if section in SYSTEM_SETUP_PAGES:
            return redirect(_setup_section_url(section))
        return redirect(url_for("control_system_setup_email"))

    def _shared_setup_nav_context(*, active_section: str) -> dict:
        return {
            "active_section": active_section,
            "setup_nav": [
                {
                    "key": "email",
                    "label": "Email & Password Reset",
                    "url": url_for("control_system_setup_email"),
                },
                {
                    "key": "connection",
                    "label": "Connection",
                    "url": url_for("control_system_setup_connection"),
                },
                {
                    "key": "upload",
                    "label": "Upload directory",
                    "url": url_for("control_system_setup_upload"),
                },
                {
                    "key": "project-folders",
                    "label": "Project folders",
                    "url": url_for("control_system_setup_project_folders"),
                },
                {
                    "key": "health",
                    "label": "Health",
                    "url": url_for("control_system_setup_health"),
                },
            ],
            "seed_run_url": url_for("control_system_seed_run"),
            "seed_confirm_message": SEED_CONFIRM_MESSAGE,
        }

    def _project_folder_rows() -> list[dict]:
        rows: list[dict] = []
        projects = Project.query.order_by(Project.name.asc(), Project.id.asc()).all()
        for project in projects:
            root = folder_structure_support_mod.effective_project_root_path(project)
            folder_name = folder_structure_support_mod.effective_project_folder_name(project)
            # Only treat as a full disk path when a root is configured; otherwise
            # build_project_folder_path() returns just the folder name slug.
            final_path = (
                folder_structure_support_mod.build_project_folder_path(project) if root else ""
            )
            status = (getattr(project, "project_status", None) or "active").strip().lower()
            rows.append(
                {
                    "id": int(project.id),
                    "name": (project.name or "").strip() or f"Project {project.id}",
                    "status": status,
                    "root_path": root or "",
                    "folder_name": folder_name or "",
                    "final_path": final_path or "",
                    "template_label": folder_structure_support_mod.folder_template_label_for_project(
                        project
                    ),
                    "configured": bool(root),
                    "exists_on_disk": bool(final_path and os.path.isdir(final_path)),
                    "created_at": getattr(project, "folder_structure_created_at", None),
                    "validated_at": getattr(project, "folder_structure_validated_at", None),
                    "settings_url": url_for("project_settings", project_id=int(project.id)),
                    "reveal_url": url_for(
                        "control_system_setup_project_folder_reveal",
                        project_id=int(project.id),
                    ),
                }
            )
        return rows

    def _render_setup_email_page():
        return render_template(
            "control_system_setup.html",
            **_shared_setup_nav_context(active_section="email"),
            **_mail_page_context(),
        )

    def _render_setup_connection_page():
        return render_template(
            "control_system_setup.html",
            **_shared_setup_nav_context(active_section="connection"),
            connection_http_address=sseed.current_connection_http_address(
                models.SystemSetting,
                fallback=(request.url_root or "").rstrip("/"),
            ),
            connection_save_url=url_for("control_system_setup_connection"),
        )

    def _render_setup_upload_page():
        fallback = app.config.get("UPLOAD_DATA_DIR") or sseed.default_instance_directory()
        return render_template(
            "control_system_setup.html",
            **_shared_setup_nav_context(active_section="upload"),
            upload_directory=sseed.current_upload_directory(
                models.SystemSetting,
                fallback=fallback,
            ),
            upload_directory_active=fallback,
            upload_directory_history=_upload_directory_history_for_page(
                models.SystemSetting,
                fallback=fallback,
            ),
            upload_directory_history_stored=sseed.get_upload_directory_history(
                models.SystemSetting
            ),
            upload_directory_save_url=url_for("control_system_setup_upload_directory"),
            upload_directory_history_remove_url=url_for(
                "control_system_setup_upload_directory_history_remove"
            ),
            upload_directory_history_entity_id=sseed.upload_directory_history_entity_id,
            upload_directory_history_safe_delete_type=sseed.UPLOAD_DIRECTORY_HISTORY_SAFE_DELETE_TYPE,
            upload_directory_env_locked=bool(
                (os.environ.get(sseed.UPLOAD_DIRECTORY_ENV) or "").strip()
            ),
            upload_directory_browse_url=url_for(
                "control_system_setup_upload_directory_browse"
            ),
            upload_directory_reveal_url=url_for(
                "control_system_setup_upload_directory_reveal"
            ),
        )

    def _render_setup_project_folders_page():
        rows = _project_folder_rows()
        configured_count = sum(1 for row in rows if row["configured"])
        on_disk_count = sum(1 for row in rows if row["exists_on_disk"])
        return render_template(
            "control_system_setup.html",
            **_shared_setup_nav_context(active_section="project-folders"),
            project_folder_rows=rows,
            project_folder_total=len(rows),
            project_folder_configured_count=configured_count,
            project_folder_on_disk_count=on_disk_count,
        )

    def _render_setup_health_page():
        health = sseed.build_health_report(db, models, _seed_ctx())
        last_run = sseed.last_seed_run(models)
        seed_report = session.pop("system_seed_report", None)
        try:
            working_hours_backfill_url = url_for("control_working_hours_backfill")
        except BuildError:
            working_hours_backfill_url = None
        return render_template(
            "control_system_setup.html",
            **_shared_setup_nav_context(active_section="health"),
            health=health,
            groups=health["groups"],
            warnings=health["warnings"],
            has_missing_essential=health["has_missing_essential"],
            latest_backup_path=sseed.latest_backup_path(app),
            last_seed_run=last_run,
            seed_report=seed_report,
            industry_radar_sources_url=url_for("updates_page", section="news"),
            industry_radar_rebuild_url=url_for("control_industry_news_sources_rebuild"),
            working_hours_backfill_url=working_hours_backfill_url,
            working_hours_backfill_confirm=(
                (app.extensions.get("working_hours") or {}).get("confirm_message") or ""
            ),
            working_hours_backfill_report=session.pop("working_hours_backfill_report", None),
        )

    @app.route("/control/system-setup")
    def control_system_setup():
        _admin_required()
        return _legacy_section_redirect()

    @app.route("/control/system-setup/email", methods=["GET", "POST"])
    def control_system_setup_email():
        if request.method == "GET":
            _admin_required()
            return _render_setup_email_page()
        acc = _admin_required()
        payload = _mail_form_payload()
        replace_requested = (
            str(request.form.get("replace_password") or "").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        submitted_password = str(payload.get("mail_password") or "")
        password_is_env_locked = bool(
            (os.environ.get(mail_settings_mod.MAIL_PASSWORD_ENV) or "").strip()
        )
        # First-time setup has no visible "Replace password" button, so accept
        # the entered secret even if older JavaScript leaves the hidden flag at
        # zero. Existing secrets still require the explicit replace action.
        replace_password = bool(
            submitted_password
            and submitted_password != mail_settings_mod.MAIL_PASSWORD_PLACEHOLDER
            and not password_is_env_locked
            and (
                replace_requested
                or not mail_settings_mod.mail_password_configured(app_root=app_root)
            )
        )
        before = mail_settings_mod.resolve_mail_config(
            models.SystemSetting, app=app, app_root=app_root, include_password=True
        )
        mail, errors = mail_settings_mod.save_mail_settings(
            db,
            models.SystemSetting,
            payload,
            app_root=app_root,
            replace_password=replace_password,
        )
        if errors:
            msg = errors[0]
            if _wants_json():
                return jsonify({"ok": False, "errors": errors}), 400
            flash(msg, "error")
            return redirect(url_for("control_system_setup_email"))
        mail_settings_mod.apply_mail_config_to_app(app, mail)
        changed = mail_settings_mod.changed_mail_setting_keys(
            before,
            mail,
            password_replaced=bool(
                replace_password
                and (payload.get("mail_password") or "").strip()
                and payload.get("mail_password") != mail_settings_mod.MAIL_PASSWORD_PLACEHOLDER
            ),
        )
        if log_security_event is not None:
            log_security_event(
                "system_setup_mail_settings_updated",
                account_id=int(acc.id) if acc and getattr(acc, "id", None) else None,
                entity_type="system_setting",
                details={"changed": changed},
            )
        if _wants_json():
            return jsonify({"ok": True, "mail": mail.public_dict(), "changed": changed})
        flash("Email & password-reset settings saved.", "success")
        return redirect(url_for("control_system_setup_email"))

    @app.route("/control/system-setup/email/test", methods=["POST"])
    def control_system_setup_email_test():
        acc = _admin_required()
        allowed, retry_after = mail_settings_mod.check_test_email_rate_limit(int(acc.id))
        if not allowed:
            msg = f"Please wait {retry_after} seconds before sending another test email."
            if _wants_json() or request.is_json:
                return jsonify({"ok": False, "error": msg, "retry_after": retry_after}), 429
            flash(msg, "error")
            return redirect(url_for("control_system_setup_email"))

        data = request.get_json(silent=True) or {}
        recipient = (
            (data.get("test_recipient") if isinstance(data, dict) else None)
            or request.form.get("test_recipient")
            or ""
        ).strip()
        if not mail_settings_mod.is_valid_email(recipient):
            msg = "Enter a valid recipient email address for the test message."
            if _wants_json() or request.is_json:
                return jsonify({"ok": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("control_system_setup_email"))

        # Prefer unsaved form values when present; otherwise use saved settings.
        if request.form.get("mail_server") is not None or (
            isinstance(data, dict) and data.get("mail_server") is not None
        ):
            if isinstance(data, dict) and data.get("mail_server") is not None:
                payload = {
                    "mail_enabled": data.get("mail_enabled") or "1",
                    "mail_provider": data.get("mail_provider") or "custom",
                    "mail_server": data.get("mail_server") or "",
                    "mail_port": data.get("mail_port") or "587",
                    "mail_encryption": data.get("mail_encryption") or "starttls",
                    "mail_username": data.get("mail_username") or "",
                    "mail_password": data.get("mail_password") or "",
                    "mail_sender_name": data.get("mail_sender_name") or "",
                    "mail_sender_email": data.get("mail_sender_email") or "",
                    "public_application_url": data.get("public_application_url") or "",
                    "mail_reset_expiry_minutes": data.get("mail_reset_expiry_minutes")
                    or str(mail_settings_mod.DEFAULT_RESET_EXPIRY_MINUTES),
                    "mail_admin_fallback": data.get("mail_admin_fallback") or "0",
                }
            else:
                payload = _mail_form_payload()
            cfg = mail_settings_mod.resolve_mail_config(
                models.SystemSetting,
                app=app,
                app_root=app_root,
                form=payload,
                include_password=True,
            )
        else:
            cfg = mail_settings_mod.resolve_mail_config(
                models.SystemSetting,
                app=app,
                app_root=app_root,
                include_password=True,
            )

        if not cfg.can_send_test:
            msg = (
                "Complete SMTP server, sender, encryption, and password before "
                "sending a test email."
            )
            if _wants_json() or request.is_json:
                return jsonify({"ok": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("control_system_setup_email"))

        mapping = cfg.flask_mail_mapping()
        mapping["MAIL_ENABLED"] = "1"
        app_name = str(app.config.get("APP_NAME") or "BIGbang Studios")
        text_body, html_body = mail_settings_mod.build_test_email_bodies(
            app_name=app_name,
            sender=cfg.sender_header,
        )
        try:
            mail_service_mod.send_email(
                mapping,
                to_address=recipient,
                subject=f"Test email from {app_name}",
                text_body=text_body,
                html_body=html_body,
            )
        except Exception as exc:  # noqa: BLE001
            safe = mail_settings_mod.sanitize_smtp_error(exc)
            app.logger.warning(
                "System Setup test email failed for account %s: %s",
                getattr(acc, "id", None),
                type(exc).__name__,
            )
            if log_security_event is not None:
                log_security_event(
                    "system_setup_mail_test_failed",
                    account_id=int(acc.id) if acc and getattr(acc, "id", None) else None,
                    entity_type="system_setting",
                    details={"recipient_domain": recipient.split("@")[-1][:80]},
                )
            if _wants_json() or request.is_json:
                return jsonify({"ok": False, "error": safe}), 502
            flash(safe, "error")
            return redirect(url_for("control_system_setup_email"))

        mail_settings_mod.mark_test_email_sent(int(acc.id))
        if log_security_event is not None:
            log_security_event(
                "system_setup_mail_test_sent",
                account_id=int(acc.id) if acc and getattr(acc, "id", None) else None,
                entity_type="system_setting",
                details={"recipient_domain": recipient.split("@")[-1][:80]},
            )
        ok_msg = f"Test email sent to {recipient}."
        if _wants_json() or request.is_json:
            return jsonify({"ok": True, "message": ok_msg})
        flash(ok_msg, "success")
        return redirect(url_for("control_system_setup_email"))

    @app.route("/control/system-setup/connection", methods=["GET", "POST"])
    def control_system_setup_connection():
        if request.method == "GET":
            _admin_required()
            return _render_setup_connection_page()
        _admin_required()
        normalized = sseed.normalize_connection_http_address(
            request.form.get("connection_http_address")
        )
        if not normalized:
            msg = "Enter a valid http:// or https:// address (for example http://127.0.0.1:5001)."
            if _wants_json():
                return jsonify({"ok": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("control_system_setup_connection"))
        sseed.set_system_setting(
            db,
            models.SystemSetting,
            sseed.CONNECTION_HTTP_ADDRESS_KEY,
            normalized,
            description=sseed.CONNECTION_HTTP_ADDRESS_DESCRIPTION,
        )
        db.session.commit()
        if _wants_json():
            return jsonify({"ok": True, "connection_http_address": normalized})
        flash(f"Connection address saved: {normalized}", "success")
        return redirect(url_for("control_system_setup_connection"))

    @app.route("/control/system-setup/upload", methods=["GET"])
    def control_system_setup_upload():
        _admin_required()
        return _render_setup_upload_page()

    @app.route("/control/system-setup/project-folders", methods=["GET"])
    def control_system_setup_project_folders():
        _admin_required()
        return _render_setup_project_folders_page()

    @app.route(
        "/control/system-setup/project-folders/<int:project_id>/reveal",
        methods=["POST"],
    )
    def control_system_setup_project_folder_reveal(project_id: int):
        """Open a project's folder path in Finder / file manager on the server host."""
        _admin_required()
        if not _request_is_local_host():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": (
                            "Show in Finder is only available when using this server "
                            "from the same computer (localhost), or from the desktop app."
                        ),
                    }
                ),
                403,
            )

        project = db.session.get(Project, int(project_id))
        if project is None:
            return jsonify({"ok": False, "error": "Project not found."}), 404

        root = folder_structure_support_mod.effective_project_root_path(project)
        if not root:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "Set a project root path in Project Settings first.",
                    }
                ),
                400,
            )

        target = folder_structure_support_mod.build_project_folder_path(project)
        if not target:
            return jsonify({"ok": False, "error": "Project folder path is empty."}), 400

        # Prefer the project folder; fall back to the root if the leaf is not created yet.
        open_target = target if os.path.isdir(target) else root
        if not os.path.isdir(open_target):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "That folder does not exist on disk yet.",
                        "path": target,
                    }
                ),
                400,
            )

        opened, result = folder_structure_support_mod.open_folder_in_os(open_target)
        if opened:
            return jsonify({"ok": True, "path": result, "opened": True})
        return jsonify({"ok": False, "error": result or "Could not open that folder."}), 400

    @app.route("/control/system-setup/health", methods=["GET"])
    def control_system_setup_health():
        _admin_required()
        return _render_setup_health_page()

    @app.route("/control/system-setup/upload-directory/browse", methods=["POST"])
    def control_system_setup_upload_directory_browse():
        """Open a native folder dialog on the server host (localhost admins / desktop)."""
        _admin_required()
        if (os.environ.get(sseed.UPLOAD_DIRECTORY_ENV) or "").strip():
            msg = (
                f"Upload directory is locked by {sseed.UPLOAD_DIRECTORY_ENV}. "
                "Unset that environment variable to change it here."
            )
            return jsonify({"ok": False, "error": msg}), 400

        if not _request_is_local_host():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": (
                            "Folder picker is only available when using this server "
                            "from the same computer (localhost), or from the desktop app."
                        ),
                    }
                ),
                403,
            )

        chosen = sseed.pick_directory_with_native_dialog(
            prompt="Choose upload directory"
        )
        if not chosen:
            return jsonify({"ok": False, "error": "canceled", "canceled": True}), 200

        normalized = sseed.normalize_upload_directory(chosen)
        if not normalized:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": (
                            "That folder cannot be used as the upload directory. "
                            "Choose an absolute path outside protected system folders."
                        ),
                    }
                ),
                400,
            )
        return jsonify({"ok": True, "upload_directory": normalized})

    @app.route("/control/system-setup/upload-directory/reveal", methods=["POST"])
    def control_system_setup_upload_directory_reveal():
        """Open a known upload-directory path in Finder / file manager on the server host."""
        _admin_required()
        if not _request_is_local_host():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": (
                            "Show in Finder is only available when using this server "
                            "from the same computer (localhost), or from the desktop app."
                        ),
                    }
                ),
                403,
            )

        data = request.get_json(silent=True) or {}
        raw_path = data.get("upload_directory") or request.form.get("upload_directory")
        normalized = sseed.normalize_upload_directory(raw_path)
        if not normalized:
            return jsonify({"ok": False, "error": "Choose a valid directory path."}), 400

        fallback = _upload_directory_fallback()
        allowed = set(_upload_directory_history_for_page(models.SystemSetting, fallback=fallback))
        current = sseed.current_upload_directory(models.SystemSetting, fallback=fallback)
        if current:
            allowed.add(current)
        if normalized not in allowed:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "That path is not in Upload directory history.",
                    }
                ),
                400,
            )

        opened, result = folder_structure_support_mod.open_folder_in_os(normalized)
        if opened:
            return jsonify({"ok": True, "upload_directory": result, "opened": True})
        # Keep the API message short; raw LaunchServices text is not useful in UI.
        err = (result or "").strip()
        if (
            len(err) > 180
            or "NSOSStatusErrorDomain" in err
            or "Connection Invalid" in err
            or "osascript" in err.lower()
            or "hiservices-xpcservice" in err
        ):
            err = (
                "Could not open Finder from this server process. "
                "Restart the app from Terminal (or the desktop app), then try again."
            )
        return jsonify({"ok": False, "error": err or "Could not open that folder."}), 400

    @app.route("/control/system-setup/upload-directory", methods=["POST"])
    def control_system_setup_upload_directory():
        _admin_required()
        if (os.environ.get(sseed.UPLOAD_DIRECTORY_ENV) or "").strip():
            msg = (
                f"Upload directory is locked by {sseed.UPLOAD_DIRECTORY_ENV}. "
                "Unset that environment variable to change it here."
            )
            if _wants_json():
                return jsonify({"ok": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("control_system_setup_upload"))
        normalized = sseed.normalize_upload_directory(request.form.get("upload_directory"))
        if not normalized:
            msg = (
                "Enter a valid absolute folder path "
                "(for example /Users/you/Documents/Cursor/task-manager/instance)."
            )
            if _wants_json():
                return jsonify({"ok": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("control_system_setup_upload"))
        try:
            os.makedirs(normalized, exist_ok=True)
            os.makedirs(os.path.join(normalized, "uploads"), exist_ok=True)
            sseed.write_upload_directory_pointer(normalized)
        except OSError as exc:
            msg = f"Could not use that folder: {exc}"
            if _wants_json():
                return jsonify({"ok": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("control_system_setup_upload"))
        sseed.set_system_setting(
            db,
            models.SystemSetting,
            sseed.UPLOAD_DIRECTORY_KEY,
            normalized,
            description=sseed.UPLOAD_DIRECTORY_DESCRIPTION,
        )
        sseed.add_upload_directory_history(db, models.SystemSetting, normalized)
        db.session.commit()
        if _wants_json():
            return jsonify({"ok": True, "upload_directory": normalized, "restart_required": True})
        flash(
            f"Upload directory saved: {normalized}. Restart the server to apply it to new uploads.",
            "success",
        )
        return redirect(url_for("control_system_setup_upload"))

    @app.route("/control/system-setup/upload-directory/history/remove", methods=["POST"])
    def control_system_setup_upload_directory_history_remove():
        _admin_required()
        data = request.get_json(silent=True) or {}
        raw_path = data.get("upload_directory") or request.form.get("upload_directory")
        normalized = sseed.normalize_upload_directory(raw_path)
        if not normalized:
            # Resolve from Safe Delete entity id when the client only sends the challenge.
            try:
                entity_id = int(data.get("entity_id"))
            except (TypeError, ValueError):
                entity_id = None
            if entity_id is not None:
                normalized = sseed.upload_directory_for_history_entity_id(
                    models.SystemSetting,
                    entity_id,
                    fallback=_upload_directory_fallback(),
                )
        if not normalized:
            msg = "Choose a valid directory from history to remove."
            if _wants_json() or request.is_json:
                return jsonify({"ok": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("control_system_setup_upload"))
        entity_id = sseed.upload_directory_history_entity_id(normalized)
        if entity_id is None:
            msg = "Choose a valid directory from history to remove."
            if _wants_json() or request.is_json:
                return jsonify({"ok": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("control_system_setup_upload"))

        if safe_delete_guard is None or safe_delete_service is None:
            msg = "Safe Delete is unavailable."
            if _wants_json() or request.is_json:
                return jsonify({"ok": False, "error": msg}), 503
            flash(msg, "error")
            return redirect(url_for("control_system_setup_upload"))

        data_json = request.get_json(silent=True) or {}
        if not data_json.get("challenge_token"):
            msg = "Confirm with Safe Delete before removing this directory from history."
            if _wants_json() or request.is_json:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "safe_delete_required",
                            "message": msg,
                        }
                    ),
                    400,
                )
            flash(msg, "error")
            return redirect(url_for("control_system_setup_upload"))

        safe_challenge, sd_err = safe_delete_guard(
            sseed.UPLOAD_DIRECTORY_HISTORY_SAFE_DELETE_TYPE,
            entity_id,
        )
        if sd_err is not None:
            return sd_err

        history = sseed.remove_upload_directory_history(
            db, models.SystemSetting, normalized
        )
        safe_delete_service.consume(safe_challenge)
        db.session.commit()
        if _wants_json() or request.is_json:
            return jsonify(
                {
                    "ok": True,
                    "upload_directory_history": history,
                    "redirect": url_for("control_system_setup_upload"),
                }
            )
        flash(f"Removed from history: {normalized}", "success")
        return redirect(url_for("control_system_setup_upload"))

    @app.route("/control/system-seed/run", methods=["POST"])
    def control_system_seed_run():
        acc = _admin_required()
        result = sseed.run_system_seed(
            db,
            app,
            models=models,
            ctx=_seed_ctx(),
            created_by=int(acc.id) if acc and getattr(acc, "id", None) else None,
            require_backup=True,
        )
        if result.get("failed_count") and result.get("backup_path") is None:
            msg = "System seed stopped: database backup failed."
            if _wants_json():
                return jsonify({"ok": False, "error": msg, **result}), 503
            flash(msg, "error")
            if result.get("warnings"):
                flash("; ".join(result["warnings"][:3]), "error")
            return redirect(url_for("control_system_setup_health"))

        if _wants_json():
            return jsonify({"ok": True, **result})

        session["system_seed_report"] = result
        created = int(result.get("created_count") or 0)
        skipped = int(result.get("skipped_existing_count") or 0)
        updated = int(result.get("updated_count") or 0)
        failed = int(result.get("failed_count") or 0)
        flash(
            (
                f"System seed complete: created {created}, updated {updated}, "
                f"skipped {skipped} existing, failed {failed}."
            ),
            "success" if failed == 0 else "warning",
        )
        if result.get("backup_path"):
            flash(f"Backup saved: {result['backup_path']}", "success")
        for warning in (result.get("warnings") or [])[:5]:
            flash(warning, "warning")
        return redirect(url_for("control_system_setup_health"))

    @app.cli.command("seed-system-data")
    @click.option("--skip-backup", is_flag=True, help="Skip pre-seed database backup (not recommended).")
    def seed_system_data_cli(skip_backup: bool):
        """Add missing essential master setup data (additive, idempotent)."""
        with app.app_context():
            result = sseed.run_system_seed(
                db,
                app,
                models=models,
                ctx=_seed_ctx(),
                created_by=None,
                require_backup=not skip_backup,
            )
        if result.get("failed_count") and not result.get("backup_path") and not skip_backup:
            click.echo("Seed aborted: backup failed.", err=True)
            for warning in result.get("warnings") or []:
                click.echo(f"  {warning}", err=True)
            raise SystemExit(1)
        click.echo(
            "System seed complete: "
            f"created {result.get('created_count', 0)}, "
            f"updated {result.get('updated_count', 0)}, "
            f"skipped {result.get('skipped_existing_count', 0)}, "
            f"failed {result.get('failed_count', 0)}."
        )
        if result.get("backup_path"):
            click.echo(f"Backup: {result['backup_path']}")
        for warning in result.get("warnings") or []:
            click.echo(f"Warning: {warning}", err=True)
        if int(result.get("failed_count") or 0) > 0:
            raise SystemExit(1)
