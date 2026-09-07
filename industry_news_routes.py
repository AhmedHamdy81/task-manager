"""Industry Radar — Flask routes and CLI."""

from __future__ import annotations

import click
from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

import industry_news as inews
import scheduled_jobs as sched


def sources_admin_list_url(**query):
    """Canonical admin UI for news sources (combined Updates & News page)."""
    params = {}
    for key, value in query.items():
        if value is None or value == "" or key == "section":
            continue
        params[key] = value
    params["section"] = "news"
    return url_for("updates_page", **params)


def build_industry_news_sources_template_vars(
    ctx: dict, app, *, group_filter: str | None = None
) -> dict:
    """Template kwargs for the Industry News Sources admin section."""
    db = ctx["db"]
    IndustryNewsSource = ctx["IndustryNewsSource"]
    IndustryNewsItem = ctx["IndustryNewsItem"]
    group = str(group_filter or "all").strip().lower() or "all"
    all_sources = IndustryNewsSource.query.order_by(IndustryNewsSource.name.asc()).all()
    if group != "all":
        sources = [s for s in all_sources if inews.source_matches_group(s, group)]
    else:
        sources = all_sources
    item_counts: dict[int, int] = {}
    for sid, cnt in (
        db.session.query(IndustryNewsItem.source_id, db.func.count(IndustryNewsItem.id))
        .group_by(IndustryNewsItem.source_id)
        .all()
    ):
        if sid is not None:
            item_counts[int(sid)] = int(cnt)
    expanded_report = session.pop("ir_expanded_report", None)
    rebuild_report = session.pop("ir_rebuild_report", None)
    show_backup_warning = len(all_sources) < 3 or IndustryNewsItem.query.count() < 5
    return {
        "sources": sources,
        "all_sources_count": len(all_sources),
        "item_counts": item_counts,
        "categories": inews.INDUSTRY_NEWS_CATEGORIES,
        "regions": inews.INDUSTRY_NEWS_REGIONS,
        "source_groups": inews.INDUSTRY_NEWS_SOURCE_GROUPS,
        "source_group_labels": inews.INDUSTRY_NEWS_SOURCE_GROUP_LABELS,
        "category_labels": inews.INDUSTRY_NEWS_CATEGORY_LABELS,
        "region_labels": inews.INDUSTRY_NEWS_REGION_LABELS,
        "group_filter": group,
        "expanded_report": expanded_report,
        "rebuild_report": rebuild_report,
        "show_backup_warning": show_backup_warning,
        "add_defaults_url": url_for("control_industry_news_sources_add_defaults"),
        "add_expanded_url": url_for("control_industry_news_sources_add_expanded"),
        "refresh_all_url": url_for("control_industry_news_sources_refresh_all"),
        "rebuild_url": url_for("control_industry_news_sources_rebuild"),
        "discover_url": url_for("control_industry_news_sources_discover"),
        "create_from_discovery_url": url_for(
            "control_industry_news_sources_create_from_discovery"
        ),
        "scheduler_info": sched.get_scheduler_admin_info(app),
        "infer_source_group": inews.infer_source_group,
    }


def register_industry_news_routes(app, ctx: dict) -> None:
    db = ctx["db"]
    IndustryNewsSource = ctx["IndustryNewsSource"]
    IndustryNewsItem = ctx["IndustryNewsItem"]
    account_from_session = ctx["account_from_session"]
    account_can_access_admin_settings = ctx["account_can_access_admin_settings"]
    now_local = ctx["now_local"]

    def _admin_required():
        acc = account_from_session()
        if not account_can_access_admin_settings(acc):
            abort(403)
        return acc

    def _parse_source_form(data) -> dict:
        name = str(data.get("name") or "").strip()
        source_type = str(data.get("source_type") or "rss").strip().lower()
        if source_type not in ("rss", "api"):
            source_type = "rss"
        feed_url = str(data.get("feed_url") or "").strip() or None
        api_url = str(data.get("api_url") or "").strip() or None
        api_key_name = str(data.get("api_key_name") or "").strip() or None
        default_category = inews._normalize_choice(
            data.get("default_category"), inews.INDUSTRY_NEWS_CATEGORIES, "cinema"
        )
        default_region = inews._normalize_choice(
            data.get("default_region"), inews.INDUSTRY_NEWS_REGIONS, "global"
        )
        source_group = inews._normalize_choice(
            data.get("source_group"), inews.INDUSTRY_NEWS_SOURCE_GROUPS, "global_cinema"
        )
        keyword_filter = str(data.get("keyword_filter") or "").strip() or None
        is_active = data.get("is_active") in (True, "1", "on", "true", 1)
        return {
            "name": name,
            "source_type": source_type,
            "feed_url": feed_url,
            "api_url": api_url,
            "api_key_name": api_key_name,
            "default_category": default_category,
            "default_region": default_region,
            "source_group": source_group,
            "keyword_filter": keyword_filter,
            "is_active": is_active,
        }

    @app.route("/industry-radar")
    def industry_radar_page():
        acc = account_from_session()
        if acc is None:
            return redirect(url_for("login", next=request.path))
        q = str(request.args.get("q") or "").strip()
        category = str(request.args.get("category") or "").strip().lower() or None
        region = str(request.args.get("region") or "").strip().lower() or None
        source_id_raw = str(request.args.get("source_id") or "").strip()
        source_id = int(source_id_raw) if source_id_raw.isdigit() else None
        featured_only = request.args.get("featured") == "1"
        pinned_only = request.args.get("pinned") == "1"
        page = max(1, int(request.args.get("page") or 1))
        per_page = 24

        query = IndustryNewsItem.query.filter(IndustryNewsItem.is_active.is_(True))
        if category and category in inews.INDUSTRY_NEWS_CATEGORIES:
            query = query.filter(IndustryNewsItem.category == category)
        if region and region in inews.INDUSTRY_NEWS_REGIONS:
            query = query.filter(IndustryNewsItem.region == region)
        if source_id is not None:
            query = query.filter(IndustryNewsItem.source_id == source_id)
        if featured_only:
            query = query.filter(IndustryNewsItem.is_featured.is_(True))
        if pinned_only:
            query = query.filter(IndustryNewsItem.is_pinned.is_(True))
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    IndustryNewsItem.title.ilike(like),
                    IndustryNewsItem.summary.ilike(like),
                    IndustryNewsItem.source_name.ilike(like),
                )
            )
        query = query.order_by(
            IndustryNewsItem.is_featured.desc(),
            IndustryNewsItem.is_pinned.desc(),
            IndustryNewsItem.published_at.desc().nulls_last(),
            IndustryNewsItem.created_at.desc(),
        )
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        items = [inews.serialize_industry_news_item(r) for r in pagination.items]
        sources = IndustryNewsSource.query.order_by(IndustryNewsSource.name.asc()).all()
        return render_template(
            "industry_radar.html",
            items=items,
            pagination=pagination,
            sources=sources,
            q=q,
            category=category or "",
            region=region or "",
            source_id=source_id,
            featured_only=featured_only,
            pinned_only=pinned_only,
            category_labels=inews.INDUSTRY_NEWS_CATEGORY_LABELS,
            region_labels=inews.INDUSTRY_NEWS_REGION_LABELS,
            categories=inews.INDUSTRY_NEWS_CATEGORIES,
            regions=inews.INDUSTRY_NEWS_REGIONS,
        )

    @app.route("/industry-radar/widget-feed")
    def industry_radar_widget_feed():
        acc = account_from_session()
        if acc is None:
            return jsonify({"ok": False, "error": "Sign in required."}), 401
        category = str(request.args.get("category") or "").strip().lower() or None
        if category and category not in inews.INDUSTRY_NEWS_CATEGORIES:
            category = None
        mena = request.args.get("mena") == "1"
        items = inews.fetch_dashboard_industry_news(
            IndustryNewsItem, category=category, mena=mena
        )
        total = inews.count_active_industry_news(
            IndustryNewsItem, category=category, mena=mena
        )
        html = render_template(
            "partials/industry_radar_widget_items.html",
            industry_radar_items=items,
        )
        view_all_url = url_for("industry_radar_page")
        if mena:
            view_all_url = url_for("industry_radar_page", region="mena")
        elif category:
            view_all_url = url_for("industry_radar_page", category=category)
        return jsonify(
            {
                "ok": True,
                "html": html,
                "shown": len(items),
                "total": total,
                "viewAllUrl": view_all_url,
            }
        )

    def _wants_json() -> bool:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return True
        accept = request.headers.get("Accept") or ""
        return "application/json" in accept and "text/html" not in accept

    @app.route("/control/industry-news-sources/scheduler-status")
    def control_industry_news_sources_scheduler_status():
        _admin_required()
        return jsonify(sched.get_scheduler_status(app))

    @app.route("/control/industry-news-sources")
    def control_industry_news_sources():
        _admin_required()
        return redirect(sources_admin_list_url(**request.args.to_dict(flat=True)))

    @app.route("/control/industry-news-sources/discover", methods=["GET", "POST"])
    def control_industry_news_sources_discover():
        _admin_required()
        if request.method == "GET" and not _wants_json():
            return redirect(sources_admin_list_url())
        raw_url = ""
        if request.is_json:
            payload = request.get_json(silent=True) or {}
            raw_url = str(payload.get("url") or "").strip()
        else:
            raw_url = str(request.form.get("url") or "").strip()
        if not raw_url:
            return jsonify({"ok": False, "errors": ["URL is required."]}), 400
        discovery = inews.discover_source_from_url(
            raw_url,
            allow_localhost=bool(getattr(app, "debug", False)),
        )
        rec = discovery.get("recommended_source") or {}
        feed_url = rec.get("feed_url")
        if feed_url:
            existing = inews._find_source_by_feed_url(IndustryNewsSource, feed_url)
            if existing is not None:
                discovery["existing_source_id"] = int(existing.id)
                discovery["existing_source_name"] = existing.name
        return jsonify(discovery)

    @app.route("/control/industry-news-sources/create-from-discovery", methods=["POST"])
    def control_industry_news_sources_create_from_discovery():
        _admin_required()
        fields = _parse_source_form(request.form)
        name = fields.get("name") or ""
        feed_url = fields.get("feed_url") or ""
        if not name:
            flash("Source name is required.", "error")
            return redirect(sources_admin_list_url())
        if not feed_url:
            flash("Feed URL is required.", "error")
            return redirect(sources_admin_list_url())
        existing = inews._find_source_by_feed_url(IndustryNewsSource, feed_url)
        if existing is not None:
            flash(f"This source already exists: “{existing.name}”.", "warning")
            return redirect(sources_admin_list_url())
        check = inews.validate_feed_candidate(feed_url, include_samples=False)
        if not check.get("valid"):
            flash(
                f"Feed URL is not valid: {check.get('error') or 'unknown error'}",
                "error",
            )
            return redirect(sources_admin_list_url())
        now = now_local()
        row = IndustryNewsSource(
            **fields,
            created_at=now,
            updated_at=now,
        )
        db.session.add(row)
        try:
            inews._commit_session_retry(db)
        except Exception:
            db.session.rollback()
            flash("Could not save source. Database may be busy — try again.", "error")
            return redirect(sources_admin_list_url())
        flash(f"Source added successfully: “{name}”.", "success")
        return redirect(sources_admin_list_url())

    @app.route("/control/industry-news-sources/create", methods=["POST"])
    def control_industry_news_sources_create():
        _admin_required()
        fields = _parse_source_form(request.form)
        if not fields["name"]:
            flash("Source name is required.", "error")
            return redirect(sources_admin_list_url())
        now = now_local()
        row = IndustryNewsSource(
            **fields,
            created_at=now,
            updated_at=now,
        )
        db.session.add(row)
        db.session.commit()
        flash(f"Added source “{fields['name']}”.", "success")
        return redirect(sources_admin_list_url())

    @app.route("/control/industry-news-sources/<int:source_id>/update", methods=["POST"])
    def control_industry_news_sources_update(source_id: int):
        _admin_required()
        row = db.session.get(IndustryNewsSource, source_id)
        if row is None:
            abort(404)
        fields = _parse_source_form(request.form)
        if not fields["name"]:
            flash("Source name is required.", "error")
            return redirect(sources_admin_list_url())
        for key, val in fields.items():
            setattr(row, key, val)
        row.updated_at = now_local()
        db.session.commit()
        flash("Source updated.", "success")
        return redirect(sources_admin_list_url())

    @app.route("/control/industry-news-sources/<int:source_id>/toggle", methods=["POST"])
    def control_industry_news_sources_toggle(source_id: int):
        _admin_required()
        row = db.session.get(IndustryNewsSource, source_id)
        if row is None:
            abort(404)
        row.is_active = not bool(row.is_active)
        row.updated_at = now_local()
        db.session.commit()
        flash(
            f"Source “{row.name}” is now {'active' if row.is_active else 'inactive'}.",
            "success",
        )
        return redirect(sources_admin_list_url())

    @app.route("/control/industry-news-sources/<int:source_id>/test", methods=["POST"])
    def control_industry_news_sources_test(source_id: int):
        _admin_required()
        row = db.session.get(IndustryNewsSource, source_id)
        if row is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        try:
            stype = (row.source_type or "rss").strip().lower()
            if stype == "api":
                items = inews.parse_api_source(row)
            else:
                items = inews.parse_rss_source(row)
            sample = items[0] if items else None
            return jsonify(
                {
                    "ok": True,
                    "entry_count": len(items),
                    "sample_title": (sample or {}).get("title"),
                }
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)[:500]}), 400

    @app.route("/control/industry-news-sources/<int:source_id>/refresh", methods=["POST"])
    def control_industry_news_sources_refresh(source_id: int):
        _admin_required()
        row = db.session.get(IndustryNewsSource, source_id)
        if row is None:
            if _wants_json():
                return jsonify({"ok": False, "error": "not_found"}), 404
            abort(404)
        result = inews.fetch_industry_news_source(
            row, db, IndustryNewsItem, limit=20, now=now_local()
        )
        if _wants_json():
            return jsonify({"ok": result.get("error") is None, **result})
        if result.get("error"):
            flash(
                f"Refresh failed for “{row.name}”: {result['error']}",
                "error",
            )
        else:
            imported = int(result.get("imported") or 0)
            skipped = int(result.get("skipped") or 0)
            backfilled = int(result.get("images_backfilled") or 0)
            with_image = int(result.get("with_image") or 0)
            without_image = int(result.get("without_image") or 0)
            og_fallback = int(result.get("og_image_fallback") or 0)
            wp_fallback = int(result.get("wordpress_image_count") or 0)
            article_fallback = int(result.get("article_image_count") or 0)
            rss_images = int(result.get("rss_image_count") or 0)
            skipped_kw = int(result.get("skipped_keyword") or 0)
            skipped_dup = int(result.get("skipped_duplicate") or 0)
            flash(
                f"“{row.name}”: imported {imported} items, {with_image} with images "
                f"({rss_images} RSS, {wp_fallback} WordPress, {og_fallback} Open Graph, "
                f"{article_fallback} article page), "
                f"{without_image} without images, "
                f"backfilled {backfilled} thumbnails, skipped {skipped_dup} duplicates"
                f"{f', {skipped_kw} keyword-filtered' if skipped_kw else ''}.",
                "success",
            )
            sched.record_refresh_run(
                app,
                {
                    "imported": imported,
                    "skipped": skipped,
                    "errors": 0 if not result.get("error") else 1,
                    "with_image": with_image,
                    "without_image": without_image,
                    "sources": [{"name": row.name, **result}],
                },
                trigger="manual",
            )
        return redirect(sources_admin_list_url())

    @app.route("/control/industry-news-sources/refresh-all", methods=["POST"])
    def control_industry_news_sources_refresh_all():
        _admin_required()
        totals = sched.run_industry_news_refresh(app, trigger="manual", limit_per_source=20)
        if totals.get("skipped_lock"):
            flash("Refresh already in progress. Please wait and try again.", "warning")
            return redirect(sources_admin_list_url())
        imported = int(totals.get("imported") or 0)
        skipped = int(totals.get("skipped") or 0)
        skipped_kw = int(totals.get("skipped_keyword") or 0)
        skipped_dup = int(totals.get("skipped_duplicate") or 0)
        errors = int(totals.get("errors") or 0)
        with_image = int(totals.get("with_image") or 0)
        without_image = int(totals.get("without_image") or 0)
        wp_images = int(totals.get("wordpress_image_count") or 0)
        og_images = int(totals.get("og_image_fallback") or 0)
        article_images = int(totals.get("article_image_count") or 0)
        rss_images = int(totals.get("rss_image_count") or 0)
        if _wants_json():
            return jsonify(
                {
                    "ok": totals.get("ok", True) and not totals.get("error"),
                    "imported": imported,
                    "skipped": skipped,
                    "errors": errors,
                    "imported_count": imported,
                    "skipped_count": skipped,
                    "error_count": errors,
                    **totals,
                }
            )
        if totals.get("error") and not imported and not skipped:
            flash(f"Refresh failed: {totals['error']}", "error")
        else:
            msg = (
                f"Imported {imported} items, {with_image} with images "
                f"({rss_images} RSS, {wp_images} WordPress, {og_images} Open Graph, "
                f"{article_images} article page), "
                f"{without_image} without images, skipped {skipped_dup} duplicates"
            )
            if skipped_kw:
                msg += f", {skipped_kw} keyword-filtered"
            if errors:
                msg += f", {errors} sources failed"
            msg += "."
            flash(msg, "success" if errors == 0 else "warning")
        return redirect(sources_admin_list_url())

    @app.route("/control/industry-news-sources/refresh", methods=["POST"])
    def control_industry_news_sources_refresh_alias():
        return control_industry_news_sources_refresh_all()

    @app.route("/control/industry-news-sources/add-defaults", methods=["POST"])
    def control_industry_news_sources_add_defaults():
        _admin_required()
        result = inews.add_default_industry_news_sources(
            db, IndustryNewsSource, now_local()
        )
        created = int(result.get("created_count") or 0)
        skipped = int(result.get("skipped_count") or 0)
        total = int(result.get("total_sources") or 0)
        if _wants_json():
            return jsonify({"ok": True, **result})
        flash(
            f"Created {created} sources, skipped {skipped} existing sources.",
            "success",
        )
        return redirect(sources_admin_list_url())

    @app.route("/control/industry-news-sources/add-expanded-defaults", methods=["POST"])
    def control_industry_news_sources_add_expanded():
        _admin_required()
        try:
            result = inews.add_expanded_default_industry_news_sources(
                db, IndustryNewsSource, now_local()
            )
        except Exception as exc:
            db.session.rollback()
            msg = str(exc)
            if "locked" in msg.lower():
                err = "Database busy while validating feeds. Please try again in a moment."
            else:
                err = f"Could not add expanded sources: {msg[:200]}"
            if _wants_json():
                return jsonify({"ok": False, "error": err}), 503
            flash(err, "error")
            return redirect(sources_admin_list_url())
        if _wants_json():
            return jsonify({"ok": True, **result})
        session["ir_expanded_report"] = result
        created = int(result.get("created_count") or 0)
        skipped = int(result.get("skipped_count") or 0)
        failed = int(result.get("failed_count") or 0)
        flash(
            f"Created {created} sources, skipped {skipped} existing, failed {failed}.",
            "success" if failed == 0 else "warning",
        )
        return redirect(sources_admin_list_url())

    @app.route("/control/industry-news-sources/rebuild-industry-radar", methods=["POST"])
    def control_industry_news_sources_rebuild():
        _admin_required()
        try:
            result = inews.rebuild_industry_radar(
                db, IndustryNewsSource, IndustryNewsItem, now=now_local()
            )
        except Exception as exc:
            db.session.rollback()
            msg = str(exc)
            if "locked" in msg.lower():
                err = "Database busy while rebuilding Industry Radar. Please try again."
            else:
                err = f"Industry Radar rebuild failed: {msg[:240]}"
            if _wants_json():
                return jsonify({"ok": False, "error": err}), 503
            flash(err, "error")
            return redirect(sources_admin_list_url())
        if _wants_json():
            return jsonify({"ok": True, **result})
        session["ir_rebuild_report"] = result
        flash(
            (
                f"Industry Radar rebuilt: created {result.get('created_sources_count', 0)} sources, "
                f"skipped {result.get('skipped_sources_count', 0)} existing, "
                f"failed {result.get('failed_sources_count', 0)}; "
                f"imported {result.get('imported_items_count', 0)} items "
                f"({result.get('items_with_images_count', 0)} with images, "
                f"{result.get('items_without_images_count', 0)} without), "
                f"skipped {result.get('skipped_duplicate_items_count', 0)} duplicates; "
                f"{result.get('sources_with_errors_count', 0)} sources with errors."
            ),
            "success" if int(result.get("failed_sources_count") or 0) == 0 else "warning",
        )
        return redirect(sources_admin_list_url())

    @app.route("/control/industry-news-sources/seed", methods=["POST"])
    def control_industry_news_sources_seed():
        """Legacy alias for add-defaults."""
        return control_industry_news_sources_add_defaults()

    @app.route("/control/industry-news-sources/<int:source_id>/delete", methods=["POST"])
    def control_industry_news_sources_delete(source_id: int):
        _admin_required()
        row = db.session.get(IndustryNewsSource, source_id)
        if row is None:
            abort(404)
        name = row.name
        IndustryNewsItem.query.filter_by(source_id=source_id).update(
            {IndustryNewsItem.source_id: None}, synchronize_session=False
        )
        db.session.delete(row)
        db.session.commit()
        flash(f"Deleted source “{name}”. Imported items were kept.", "success")
        return redirect(sources_admin_list_url())

    @app.route("/control/industry-news")
    def control_industry_news():
        _admin_required()
        q = str(request.args.get("q") or "").strip()
        category = str(request.args.get("category") or "").strip().lower() or None
        region = str(request.args.get("region") or "").strip().lower() or None
        source_id_raw = str(request.args.get("source_id") or "").strip()
        source_id = int(source_id_raw) if source_id_raw.isdigit() else None
        active_filter = request.args.get("active")
        page = max(1, int(request.args.get("page") or 1))

        query = IndustryNewsItem.query.options(joinedload(IndustryNewsItem.source))
        if category and category in inews.INDUSTRY_NEWS_CATEGORIES:
            query = query.filter(IndustryNewsItem.category == category)
        if region and region in inews.INDUSTRY_NEWS_REGIONS:
            query = query.filter(IndustryNewsItem.region == region)
        if source_id is not None:
            query = query.filter(IndustryNewsItem.source_id == source_id)
        if active_filter == "1":
            query = query.filter(IndustryNewsItem.is_active.is_(True))
        elif active_filter == "0":
            query = query.filter(IndustryNewsItem.is_active.is_(False))
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    IndustryNewsItem.title.ilike(like),
                    IndustryNewsItem.summary.ilike(like),
                )
            )
        query = query.order_by(
            IndustryNewsItem.is_featured.desc(),
            IndustryNewsItem.is_pinned.desc(),
            IndustryNewsItem.published_at.desc().nulls_last(),
            IndustryNewsItem.created_at.desc(),
        )
        pagination = query.paginate(page=page, per_page=30, error_out=False)
        sources = IndustryNewsSource.query.order_by(IndustryNewsSource.name.asc()).all()
        return render_template(
            "control_industry_news.html",
            items=pagination.items,
            pagination=pagination,
            sources=sources,
            q=q,
            category=category or "",
            region=region or "",
            source_id=source_id,
            active_filter=active_filter or "",
            category_labels=inews.INDUSTRY_NEWS_CATEGORY_LABELS,
            region_labels=inews.INDUSTRY_NEWS_REGION_LABELS,
            category_fallback_labels=inews.INDUSTRY_NEWS_CATEGORY_FALLBACK_LABELS,
            categories=inews.INDUSTRY_NEWS_CATEGORIES,
            regions=inews.INDUSTRY_NEWS_REGIONS,
        )

    @app.route("/control/industry-news/fetch-missing-thumbnails", methods=["POST"])
    @app.route("/control/industry-news/fetch-missing-images", methods=["POST"])
    def control_industry_news_fetch_missing_thumbnails():
        _admin_required()
        result = inews.update_missing_images_for_existing_items(
            db, IndustryNewsItem, now=now_local()
        )
        return jsonify({"ok": True, **result})

    @app.route("/control/industry-news/<int:item_id>/update", methods=["POST"])
    def control_industry_news_update(item_id: int):
        _admin_required()
        row = db.session.get(IndustryNewsItem, item_id)
        if row is None:
            abort(404)
        title = str(request.form.get("title") or row.title).strip()
        summary = str(request.form.get("summary") or "").strip() or None
        category = inews._normalize_choice(
            request.form.get("category"), inews.INDUSTRY_NEWS_CATEGORIES, row.category
        )
        region = inews._normalize_choice(
            request.form.get("region"), inews.INDUSTRY_NEWS_REGIONS, row.region
        )
        clear_image = request.form.get("clear_image") in ("1", "on", "true")
        image_url_raw = str(request.form.get("image_url") or "").strip()
        if clear_image:
            row.image_url = None
        elif image_url_raw:
            validated_image = inews.validate_image_url(image_url_raw)
            if not validated_image:
                flash("Image URL must be a valid http or https address.", "error")
                return redirect(url_for("control_industry_news", **request.args.to_dict()))
            row.image_url = validated_image
        if title:
            row.title = title[:500]
        row.summary = summary
        row.category = category
        row.region = region
        row.updated_at = now_local()
        db.session.commit()
        flash("News item updated.", "success")
        return redirect(url_for("control_industry_news", **request.args.to_dict()))

    @app.route("/control/industry-news/<int:item_id>/toggle-active", methods=["POST"])
    def control_industry_news_toggle_active(item_id: int):
        _admin_required()
        row = db.session.get(IndustryNewsItem, item_id)
        if row is None:
            abort(404)
        row.is_active = not bool(row.is_active)
        row.updated_at = now_local()
        db.session.commit()
        return redirect(url_for("control_industry_news", **request.args.to_dict()))

    @app.route("/control/industry-news/<int:item_id>/toggle-pin", methods=["POST"])
    def control_industry_news_toggle_pin(item_id: int):
        _admin_required()
        row = db.session.get(IndustryNewsItem, item_id)
        if row is None:
            abort(404)
        row.is_pinned = not bool(row.is_pinned)
        row.updated_at = now_local()
        db.session.commit()
        return redirect(url_for("control_industry_news", **request.args.to_dict()))

    @app.route("/control/industry-news/<int:item_id>/toggle-feature", methods=["POST"])
    def control_industry_news_toggle_feature(item_id: int):
        _admin_required()
        row = db.session.get(IndustryNewsItem, item_id)
        if row is None:
            abort(404)
        row.is_featured = not bool(row.is_featured)
        row.updated_at = now_local()
        db.session.commit()
        return redirect(url_for("control_industry_news", **request.args.to_dict()))

    @app.route("/control/industry-news/<int:item_id>/delete", methods=["POST"])
    def control_industry_news_delete(item_id: int):
        _admin_required()
        row = db.session.get(IndustryNewsItem, item_id)
        if row is None:
            abort(404)
        db.session.delete(row)
        db.session.commit()
        flash("News item deleted.", "success")
        return redirect(url_for("control_industry_news", **request.args.to_dict()))

    @app.cli.command("fetch-industry-news")
    @click.option("--source-id", type=int, default=None, help="Fetch a single source by ID")
    def fetch_industry_news_cli(source_id):
        """Fetch all active industry news RSS/API sources into the database."""
        totals = sched.run_industry_news_refresh(
            app, trigger="cli", source_id=source_id, limit_per_source=20
        )
        if totals.get("skipped_lock"):
            click.echo("Refresh already in progress.")
            return
        if totals.get("error") and not totals.get("sources"):
            click.echo(f"ERROR — {totals['error']}")
            return
        for src in totals.get("sources", []):
            err = src.get("error")
            if err:
                click.echo(f"{src['name']}: ERROR — {err}")
            else:
                click.echo(
                    f"{src['name']}: imported={src['imported']} skipped={src['skipped']} "
                    f"with_image={src.get('with_image', 0)} without_image={src.get('without_image', 0)} "
                    f"rss={src.get('rss_image_count', 0)} wp={src.get('wordpress_image_count', 0)} "
                    f"og={src.get('og_image_fallback', 0)} article={src.get('article_image_count', 0)}"
                )
        click.echo(
            f"Total: imported={totals.get('imported', 0)} skipped={totals.get('skipped', 0)} "
            f"with_image={totals.get('with_image', 0)} without_image={totals.get('without_image', 0)} "
            f"rss={totals.get('rss_image_count', 0)} wp={totals.get('wordpress_image_count', 0)} "
            f"og={totals.get('og_image_fallback', 0)} article={totals.get('article_image_count', 0)} "
            f"errors={totals.get('errors', 0)}"
        )

    @app.cli.command("industry-news-status")
    def industry_news_status_cli():
        """Show Industry Radar source and refresh status."""
        info = sched.get_scheduler_admin_info(app)
        status = sched.get_scheduler_status(app)
        click.echo(f"Auto refresh: {'enabled' if status.get('enabled') else 'disabled'}")
        click.echo(f"Schedule: {status.get('schedule_label')}")
        click.echo(f"Scheduler running: {status.get('running')}")
        if status.get("next_run_time"):
            click.echo(f"Next run: {status['next_run_time']}")
        if status.get("warning"):
            click.echo(f"Warning: {status['warning']}")
        click.echo(f"Sources: {info.get('total_sources', 0)} total, {info.get('active_sources', 0)} active")
        click.echo(f"Active news items: {info.get('active_items', 0)}")
        if info.get("latest_item_date_display"):
            click.echo(f"Latest item date: {info['latest_item_date_display']}")
        if info.get("last_fetched_display"):
            click.echo(f"Latest source fetch: {info['last_fetched_display']}")
        if info.get("last_success_at"):
            click.echo(f"Last recorded refresh: {info['last_success_at']} ({info.get('last_trigger') or '—'})")
        err_count = int(info.get("error_source_count") or 0)
        if err_count:
            click.echo(f"Sources with errors: {err_count}")
            for src in info.get("error_sources") or []:
                click.echo(f"  - {src['name']}: {src['last_error'][:120]}")
        else:
            click.echo("Sources with errors: 0")

    @app.cli.command("rebuild-industry-radar")
    def rebuild_industry_radar_cli():
        """Rebuild Industry Radar sources and fetch news (IndustryNewsSource/Item only)."""
        result = inews.rebuild_industry_radar(
            db, IndustryNewsSource, IndustryNewsItem, now=now_local()
        )
        click.echo("Industry Radar rebuild complete.")
        click.echo(f"created_sources_count={result.get('created_sources_count', 0)}")
        click.echo(f"skipped_sources_count={result.get('skipped_sources_count', 0)}")
        click.echo(f"failed_sources_count={result.get('failed_sources_count', 0)}")
        click.echo(f"imported_items_count={result.get('imported_items_count', 0)}")
        click.echo(
            f"skipped_duplicate_items_count={result.get('skipped_duplicate_items_count', 0)}"
        )
        click.echo(f"sources_with_errors_count={result.get('sources_with_errors_count', 0)}")
        click.echo(f"items_with_images_count={result.get('items_with_images_count', 0)}")
        click.echo(f"items_without_images_count={result.get('items_without_images_count', 0)}")
        for fail in result.get("failed_sources") or []:
            click.echo(f"FAILED source {fail.get('name')}: {fail.get('error')}")
        for src in (result.get("fetch_totals") or {}).get("sources") or []:
            if src.get("error"):
                click.echo(f"FETCH ERROR {src.get('name')}: {src.get('error')}")
