"""Import & Compare for production spreadsheets: sessions, plans and execution.

Upload, mapping and preview never touch production tables. The plan lives server-side
(HMAC-protected), confirm re-reads the file and the current database, rejects anything
that changed since the preview, and applies the user's choices in one transaction.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import secrets
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Callable

from sqlalchemy import text, update

import notification_events as notif_events
import production_import_matching as pim
import production_import_normalize as pin
import production_import_parsing as pip
import shooting_items as si

SESSION_TABLE = "production_import_sessions"
PRESET_TABLE = "production_import_presets"

STATUS_UPLOADED = "uploaded"
STATUS_PREVIEWED = "previewed"
STATUS_EXECUTING = "executing"
STATUS_EXECUTED = "executed"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"
OPEN_STATUSES = (STATUS_UPLOADED, STATUS_PREVIEWED)

SESSION_TTL = timedelta(hours=24)
AUDIT_DETAIL_RETENTION = timedelta(days=90)

LAYOUT_TABLE = "table"
LAYOUT_DAY_SHEETS = "day_sheets"

NOTIFY_EVENT_KEY = "production_import_completed"

notif_events.register_notification_event(
    NOTIFY_EVENT_KEY,
    {
        "label": "Production Import Completed",
        "category": "system",
        "description": "Sent once to the project team when shooting days or rows are imported from a spreadsheet.",
        "source": "Production",
        "source_file": "production_import_routes.py",
        "source_function": "_notify_completed",
        "source_feature": "Import & Compare",
        "default_title": "{{ notification_title }}",
        "default_body": "{{ notification_body }}",
        "default_cta_label": "",
        "default_cta_url": "",
        "default_recipients": {"preset": "project_team"},
        "exclude_actor": True,
        "dedupe_enabled": True,
        "variables": list(notif_events.COMMON_VARIABLES) + ["import_file", "import_summary"],
        "is_active": True,
    },
)


class ImportError_(Exception):
    """User-facing failure; the message is safe to show."""


class NeedsReview(ImportError_):
    def __init__(self, message: str, row_ids: list[str]):
        super().__init__(message)
        self.row_ids = row_ids


class AlreadyExecuted(ImportError_):
    pass


# --- Models -----------------------------------------------------------------------

_models: dict[str, Any] = {}


def register_models(db, now_local) -> SimpleNamespace:
    if _models:
        return SimpleNamespace(**_models)

    class ProductionImportSession(db.Model):
        __tablename__ = SESSION_TABLE

        id = db.Column(db.Integer, primary_key=True)
        token = db.Column(db.String(64), nullable=False, unique=True, index=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
        target_day_id = db.Column(db.Integer, nullable=True)
        original_filename = db.Column(db.String(255), nullable=False, default="")
        stored_name = db.Column(db.String(128), nullable=False, default="")
        file_kind = db.Column(db.String(8), nullable=False, default="")
        file_size = db.Column(db.Integer, nullable=False, default=0)
        file_sha256 = db.Column(db.String(64), nullable=False, default="")
        status = db.Column(db.String(16), nullable=False, default=STATUS_UPLOADED, index=True)
        options_json = db.Column(db.Text, nullable=False, default="{}")
        plan_json = db.Column(db.Text, nullable=False, default="")
        plan_hash = db.Column(db.String(64), nullable=False, default="")
        decisions_json = db.Column(db.Text, nullable=False, default="")
        result_json = db.Column(db.Text, nullable=False, default="")
        last_error = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)
        updated_at = db.Column(db.DateTime, nullable=False, default=now_local)
        expires_at = db.Column(db.DateTime, nullable=False, default=now_local)
        executed_at = db.Column(db.DateTime, nullable=True)

    class ProductionImportPreset(db.Model):
        __tablename__ = PRESET_TABLE
        __table_args__ = (db.UniqueConstraint("project_id", "name", name="uq_production_import_preset_name"),)

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        name = db.Column(db.String(80), nullable=False)
        mapping_json = db.Column(db.Text, nullable=False, default="{}")
        options_json = db.Column(db.Text, nullable=False, default="{}")
        created_by_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=now_local)
        updated_at = db.Column(db.DateTime, nullable=False, default=now_local)

    _models.update(Session=ProductionImportSession, Preset=ProductionImportPreset)
    return SimpleNamespace(**_models)


def ensure_tables(db, now_local) -> SimpleNamespace:
    """Create the import tables if missing (SQLite-safe; never alters other tables)."""
    m = register_models(db, now_local)
    m.Session.__table__.create(bind=db.engine, checkfirst=True)
    m.Preset.__table__.create(bind=db.engine, checkfirst=True)
    return m


# --- JSON helpers -----------------------------------------------------------------


def jload(raw: str | None, default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def jdump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)


def plan_signature(secret: str, plan_json: str) -> str:
    return hmac.new(secret.encode("utf-8"), plan_json.encode("utf-8"), hashlib.sha256).hexdigest()


# --- Service ----------------------------------------------------------------------


class ImportService:
    def __init__(self, *, db, now_local: Callable[[], datetime], models: dict[str, Any],
                 storage_dir: str | Callable[[], str], secret: str, limits: dict | None = None):
        self.db = db
        self.now = now_local
        self.M = models
        self._storage_dir = storage_dir
        self.secret = secret
        self.limits = limits or {}
        m = register_models(db, now_local)
        self.Session = m.Session
        self.Preset = m.Preset

    # -- storage & retention --

    @property
    def storage_dir(self) -> str:
        return self._storage_dir() if callable(self._storage_dir) else self._storage_dir

    def _path(self, sess) -> str:
        name = os.path.basename(sess.stored_name or "")
        if not name or name != sess.stored_name:
            raise ImportError_("The uploaded file is missing.")
        return os.path.join(self.storage_dir, name)

    def _delete_file(self, sess) -> None:
        try:
            path = self._path(sess)
        except ImportError_:
            return
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def purge_expired(self) -> int:
        """Expire open sessions past their TTL and drop old preview detail (audit summary stays)."""
        now = self.now()
        n = 0
        for sess in self.Session.query.filter(self.Session.status.in_(OPEN_STATUSES), self.Session.expires_at < now).all():
            self._delete_file(sess)
            sess.status = STATUS_EXPIRED
            sess.plan_json = ""
            sess.decisions_json = ""
            sess.updated_at = now
            n += 1
        cutoff = now - AUDIT_DETAIL_RETENTION
        for sess in self.Session.query.filter(self.Session.status == STATUS_EXECUTED, self.Session.executed_at < cutoff, self.Session.plan_json != "").all():
            sess.plan_json = ""
            sess.decisions_json = ""
        self.db.session.commit()
        return n

    def _write_private(self, data: bytes, kind: str) -> str:
        os.makedirs(self.storage_dir, exist_ok=True)
        stored = f"{secrets.token_hex(16)}.{kind}"
        path = os.path.join(self.storage_dir, stored)
        with open(path, "xb") as fh:
            fh.write(data)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return stored

    def create_session(self, *, project_id: int, account_id: int, target_day_id: int | None,
                       filename: str, data: bytes, kind: str | None = None, source: dict | None = None) -> Any:
        kind = kind or pip.file_kind(filename)
        workbook = pip.read_workbook(data, kind, limits=self.limits)
        token = secrets.token_urlsafe(24)
        stored = self._write_private(data, kind)
        options: dict[str, Any] = {
            "layout": LAYOUT_TABLE,
            "sheets": [workbook.sheets[0].name] if workbook.sheets else [],
            "sheet_settings": {},
            "mapping": {},
            "defaults": {"unit_number": "1"},
            "parse": {"duration_format": "auto"},
            "day_decisions": {},
            "step": "sheets",
        }
        if kind == pip.CSV:
            options["csv"] = {
                "encoding": workbook.csv_encoding,
                "delimiter": workbook.csv_delimiter,
                "encoding_ambiguous": workbook.csv_encoding_ambiguous,
                "delimiter_ambiguous": workbook.csv_delimiter_ambiguous,
                "confirmed": not (workbook.csv_encoding_ambiguous or workbook.csv_delimiter_ambiguous),
            }
        for sheet in workbook.sheets:
            options["sheet_settings"][sheet.name] = {"header_row": suggest_header_row(sheet) + 1, "skip_rows": 0}
        if source is not None:
            options["source"] = source
            gid_title = next((s["title"] for s in source.get("loaded") or [] if s["sheet_id"] == source.get("gid")), None)
            if gid_title:
                options["sheets"] = [gid_title]
        now = self.now()
        sess = self.Session(
            token=token, project_id=int(project_id), account_id=int(account_id),
            target_day_id=int(target_day_id) if target_day_id else None,
            original_filename=(filename if source is not None else os.path.basename(filename))[:255],
            stored_name=stored, file_kind=kind,
            file_size=len(data), file_sha256=hashlib.sha256(data).hexdigest(), status=STATUS_UPLOADED,
            options_json=jdump(options), created_at=now, updated_at=now, expires_at=now + SESSION_TTL,
        )
        self.db.session.add(sess)
        self.db.session.commit()
        return sess

    def replace_snapshot(self, sess, data: bytes, source: dict) -> None:
        """Swap in a newer source snapshot. The previous preview is rebuilt by the caller."""
        workbook = pip.read_workbook(data, pip.GSHEET, limits=self.limits)
        old = sess.stored_name
        sess.stored_name = self._write_private(data, pip.GSHEET)
        sess.file_sha256 = hashlib.sha256(data).hexdigest()
        sess.file_size = len(data)
        sess.original_filename = str(source.get("title") or sess.original_filename)[:255]
        opts = self.options(sess)
        opts["source"] = source
        names = [s.name for s in workbook.sheets]
        settings = opts.setdefault("sheet_settings", {})
        for sheet in workbook.sheets:
            settings.setdefault(sheet.name, {"header_row": suggest_header_row(sheet) + 1, "skip_rows": 0})
        opts["sheets"] = [n for n in opts.get("sheets") or [] if n in names] or names[:1]
        sess.options_json = jdump(opts)
        sess.updated_at = self.now()
        sess.expires_at = max(sess.expires_at, self.now() + timedelta(hours=2))
        self.db.session.commit()
        if old and old != sess.stored_name:
            try:
                os.remove(os.path.join(self.storage_dir, os.path.basename(old)))
            except OSError:
                pass

    def get_session(self, token: str):
        return self.Session.query.filter_by(token=str(token or "")[:64]).first()

    def options(self, sess) -> dict:
        return jload(sess.options_json, {})

    def save_options(self, sess, options: dict, *, invalidate_plan: bool = True) -> None:
        sess.options_json = jdump(options)
        sess.updated_at = self.now()
        if invalidate_plan and sess.status == STATUS_PREVIEWED:
            # The stale plan can no longer be confirmed (no valid hash) but is kept so the next
            # preview can carry over choices for rows whose data did not change.
            sess.status = STATUS_UPLOADED
            sess.plan_hash = ""
        self.db.session.commit()

    def cancel(self, sess) -> None:
        self._delete_file(sess)
        sess.status = STATUS_CANCELLED
        sess.plan_json = ""
        sess.decisions_json = ""
        sess.updated_at = self.now()
        self.db.session.commit()

    # -- reading --

    def workbook(self, sess) -> pip.Workbook:
        try:
            with open(self._path(sess), "rb") as fh:
                data = fh.read()
        except FileNotFoundError as exc:
            raise ImportError_("The uploaded file is no longer available. Upload it again.") from exc
        if hashlib.sha256(data).hexdigest() != sess.file_sha256:
            raise ImportError_("The stored upload does not match the original file. Upload it again.")
        opts = self.options(sess)
        csv_opts = opts.get("csv") or {}
        return pip.read_workbook(
            data, sess.file_kind, limits=self.limits,
            csv_encoding=csv_opts.get("encoding") or None, csv_delimiter=csv_opts.get("delimiter") or None,
        )

    # -- project snapshots --

    def project_context(self, project_id: int) -> dict:
        Project = self.M["Project"]
        p = self.db.session.get(Project, int(project_id))
        is_tv = _is_tv(p.project_type if p else "")
        max_ep = max(0, int(p.number_of_episodes or 0)) if (p and is_tv) else 1
        return {"project": p, "is_tv": is_tv, "max_episode": max_ep}

    def snapshots(self, project_id: int) -> tuple[list[dict], list[dict], list[dict]]:
        SD, SDS, SR = self.M["ShootingDay"], self.M["ShootingDayScene"], self.M["SceneRow"]
        days = [
            {"id": d.id, "unit_number": int(d.unit_number or 1), "day_name": d.day_name or "",
             "shooting_date": d.shooting_date, "location": d.location or ""}
            for d in SD.query.filter_by(project_id=int(project_id)).order_by(SD.shooting_date, SD.id).all()
        ]
        day_ids = [d["id"] for d in days]
        rows: list[dict] = []
        legacy: list[dict] = []
        if day_ids:
            for r in SDS.query.filter(SDS.shooting_day_id.in_(day_ids)).order_by(SDS.id).all():
                rows.append(row_snapshot(r))
            for r in SR.query.filter(SR.shooting_day_id.in_(day_ids)).order_by(SR.id).all():
                legacy.append({"id": r.id, "day_id": r.shooting_day_id, "episode": r.episode or "", "scene": r.scene or "",
                               "label": f"{r.episode or ''} {r.scene or ''}".strip()})
        return days, rows, legacy

    # -- pipeline --

    def source_rows(self, sess, workbook: pip.Workbook, ctx: dict) -> tuple[list[pin.SourceRow], dict]:
        opts = self.options(sess)
        parse_opts = pin.ParseOptions.from_dict(opts.get("parse") or {}, is_tv=ctx["is_tv"], max_episode=ctx["max_episode"])
        fixed = bool(sess.target_day_id)
        defaults = {}
        for key, raw in (opts.get("defaults") or {}).items():
            if key not in pin.FIELD_BY_KEY or not str(raw or "").strip():
                continue
            if fixed and key in pin.DAY_FIELD_KEYS:
                continue
            if pin.FIELD_BY_KEY[key].tv_only and not ctx["is_tv"]:
                continue
            defaults[key] = pin.parse_default(key, str(raw), parse_opts)
        out: list[pin.SourceRow] = []
        ignored: list[dict] = []
        mapped_fields: set[str] = set()
        prep_sheets: list[dict] = []
        for name in opts.get("sheets") or []:
            sheet = workbook.sheet(name)
            if sheet is None:
                continue
            st = (opts.get("sheet_settings") or {}).get(name) or {}
            header_idx = max(0, int(st.get("header_row") or 1) - 1)
            cols = sheet_columns(sheet, header_idx)
            mapping: dict[int, str] = {}
            for col in cols:
                field = (opts.get("mapping") or {}).get(col["key"]) or ""
                f = pin.FIELD_BY_KEY.get(field)
                reason = ""
                if f is None and not field and col["header"]:
                    f = pin.FIELD_BY_KEY.get(pin.suggest_mapping([col["header"]], is_tv=True).get(0, ""))
                    if f is not None and not ((f.tv_only and not ctx["is_tv"]) or (fixed and f.level == pin.DAY_LEVEL)):
                        f = None
                if f is None:
                    reason = "Ignored — no BigBang field selected." if not field else "Unsupported field."
                    if not field and col["header"] and pin.is_summary_header(col["header"]):
                        reason = "Not imported — summary/total column, not a per-row value."
                elif f.tv_only and not ctx["is_tv"]:
                    reason = "Ignored — films have no episodes."
                elif fixed and f.level == pin.DAY_LEVEL:
                    reason = "Ignored — this import goes to a fixed shooting day."
                if reason:
                    if col["header"] or col["has_data"]:
                        ignored.append({"sheet": name, "column": col["letter"], "header": col["header"], "reason": reason})
                    continue
                mapping[col["index"]] = field
                mapped_fields.add(field)
            context = {}
            if opts.get("layout") == LAYOUT_DAY_SHEETS and not fixed:
                for key, skey in (("unit_number", "unit"), ("day_name", "day"), ("shooting_date", "date")):
                    raw = str(st.get(skey) or "").strip()
                    if raw:
                        context[key] = pin.parse_default(key, raw, parse_opts)
            fill = set(fill_down_fields(st, mapping, fixed=fixed))
            stats: dict = {}
            rows = pin.build_source_rows(
                name, sheet.rows, header_row=header_idx, skip_after_header=int(st.get("skip_rows") or 0),
                mapping=mapping, defaults=defaults, sheet_day_context=context, opts=parse_opts,
                fill_down=fill, location_across_days=bool(st.get("fill_location_across_days")),
                merges=sheet.merge_anchors(), stats=stats,
            )
            out.extend(rows)
            unresolved = 0
            if "day_name" in mapping.values() and not fixed:
                unresolved = sum(1 for r in rows if r.get("day_name").state == pin.EMPTY)
            prep_sheets.append({"sheet": name, "fill_down": sorted(fill), "stats": stats, "unresolved_day": unresolved})
        return out, {
            "ignored_columns": ignored, "mapped_fields": sorted(mapped_fields), "warnings": list(workbook.warnings),
            "preparation": {"sheets": prep_sheets, "excel_time_mode": parse_opts.excel_time_mode,
                            "field_tokens": parse_opts.field_tokens},
        }

    def build_plan(self, sess, *, can_create_days: bool) -> tuple[dict, dict[str, pin.SourceRow]]:
        ctx = self.project_context(sess.project_id)
        workbook = self.workbook(sess)
        source, meta = self.source_rows(sess, workbook, ctx)
        days, rows, legacy = self.snapshots(sess.project_id)
        opts = self.options(sess)
        try:
            plan = pim.build_plan(
                source_rows=source, is_tv=ctx["is_tv"], max_episode=ctx["max_episode"], days=days, rows=rows,
                legacy_rows=legacy, fixed_day_id=sess.target_day_id, day_decisions=opts.get("day_decisions") or {},
                can_create_days=can_create_days and not sess.target_day_id, mapped_fields=set(meta["mapped_fields"]),
            )
        except ValueError as exc:
            raise ImportError_(str(exc)) from exc
        plan.update(meta)
        plan["is_tv"] = ctx["is_tv"]
        plan["file"] = {"name": sess.original_filename, "sha256": sess.file_sha256, "kind": sess.file_kind}
        plan["worksheets"] = list(opts.get("sheets") or [])
        return plan, {f"{s.sheet}!{s.row_number}": s for s in source}

    def store_plan(self, sess, plan: dict, decisions: dict | None = None) -> None:
        body = jdump(plan)
        sess.plan_json = body
        sess.plan_hash = plan_signature(self.secret, body)
        sess.decisions_json = jdump(decisions if decisions is not None else pim.default_decisions(plan))
        sess.status = STATUS_PREVIEWED
        sess.updated_at = self.now()
        sess.expires_at = max(sess.expires_at, self.now() + timedelta(hours=2))
        self.db.session.commit()

    def stored_plan(self, sess) -> dict:
        if not sess.plan_json or not hmac.compare_digest(plan_signature(self.secret, sess.plan_json), sess.plan_hash or ""):
            raise ImportError_("The preview is missing or was altered. Build the preview again.")
        return jload(sess.plan_json, {})

    # -- execution --

    def execute(self, sess, *, account, posted_hash: str, can_create_days: bool, hooks: dict) -> dict:
        """Apply the stored decisions atomically. Raises ImportError_ subclasses on refusal."""
        db = self.db
        stored = self.stored_plan(sess)
        if not hmac.compare_digest(str(posted_hash or ""), sess.plan_hash or ""):
            raise NeedsReview("The preview changed in another window. Review it again before importing.", [])
        decisions = jload(sess.decisions_json, {})
        token = sess.token
        flipped = db.session.execute(
            update(self.Session)
            .where(self.Session.id == sess.id, self.Session.status == STATUS_PREVIEWED, self.Session.plan_hash == sess.plan_hash)
            .values(status=STATUS_EXECUTING, updated_at=self.now())
        ).rowcount
        if not flipped:
            db.session.rollback()
            raise AlreadyExecuted("This import was already run or is running. Start a new import to compare again.")
        try:
            fresh, sources = self.build_plan(sess, can_create_days=can_create_days)
            changed = _changed_since_preview(stored, fresh, decisions)
            valid, errors = pim.validate_decisions(fresh, decisions)
            if changed or errors:
                db.session.rollback()
                sess = self.get_session(token)
                keep = {k: v for k, v in decisions.items() if k not in changed}
                for rid in changed:
                    keep[rid] = {"action": pim.ACTION_SKIP}
                self.store_plan(sess, fresh, keep)
                msg = (
                    f"{len(changed)} row(s) or day(s) changed since the preview and were reset to Keep. Review them again."
                    if changed else "Some choices are no longer valid: " + " ".join(errors[:3])
                )
                raise NeedsReview(msg, changed)
            result = _apply(self, sess, fresh, sources, valid, account=account, hooks=hooks)
            sess = self.get_session(token)
            sess.status = STATUS_EXECUTED
            sess.executed_at = self.now()
            sess.updated_at = self.now()
            sess.result_json = jdump(result)
            sess.last_error = ""
            hooks["log_summary"](sess, result)
            db.session.commit()
        except NeedsReview:
            raise
        except Exception as exc:
            db.session.rollback()
            message = str(exc) if isinstance(exc, ImportError_) else f"The import failed and nothing was saved: {exc}"
            sess = self.get_session(token)
            if sess is not None and sess.status == STATUS_PREVIEWED:
                sess.last_error = message[:500]
                db.session.commit()
            if isinstance(exc, ImportError_):
                raise ImportError_(f"Nothing was imported. {message}") from exc
            raise ImportError_(message) from exc
        self._delete_file(sess)
        return result

    # -- presets --

    def presets(self, project_id: int) -> list:
        return self.Preset.query.filter_by(project_id=int(project_id)).order_by(self.Preset.name).all()

    def save_preset(self, project_id: int, account_id: int, name: str, options: dict) -> Any:
        name = (name or "").strip()[:80]
        if not name:
            raise ImportError_("Enter a preset name.")
        p = self.Preset.query.filter_by(project_id=int(project_id), name=name).first()
        if p is None:
            p = self.Preset(project_id=int(project_id), name=name, created_by_account_id=int(account_id), created_at=self.now())
            self.db.session.add(p)
        p.mapping_json = jdump(options.get("mapping") or {})
        fill_by_sheet = {}
        fill_fields: list[str] = []
        for sheet_name in options.get("sheets") or []:
            st = (options.get("sheet_settings") or {}).get(sheet_name) or {}
            if "fill_down" in st:
                fill_by_sheet[sheet_name] = {"fill_down": list(st.get("fill_down") or []),
                                             "fill_location_across_days": bool(st.get("fill_location_across_days"))}
                fill_fields += [f for f in st.get("fill_down") or [] if f not in fill_fields]
        p.options_json = jdump({
            "parse": options.get("parse") or {},
            "defaults": {k: v for k, v in (options.get("defaults") or {}).items() if k in ("unit_number", "item_type", "episode")},
            "fill_down_by_sheet": fill_by_sheet,
            "fill_down_fields": fill_fields,
        })
        p.updated_at = self.now()
        self.db.session.commit()
        return p


# --- Helpers ----------------------------------------------------------------------


def _is_tv(project_type: str | None) -> bool:
    from project_settings import project_type_is_tv_series

    return bool(project_type_is_tv_series(project_type))


def fill_down_fields(sheet_settings: dict, mapping: dict[int, str], *, fixed: bool) -> list[str]:
    """Validated fill-down fields for one worksheet: day-level, mapped, and never on fixed-day imports."""
    if fixed:
        return []
    mapped = set(mapping.values())
    wanted = sheet_settings.get("fill_down") or []
    return [f for f in pin.FILL_DOWN_FIELDS if f in wanted and f in mapped]


def row_snapshot(r) -> dict:
    return {
        "id": r.id, "day_id": r.shooting_day_id, "episode_number": int(r.episode_number or 0),
        "is_episode_unassigned": bool(r.is_episode_unassigned), "is_establishing_shots_pool": bool(r.is_establishing_shots_pool),
        "scene_label": r.scene_label or "", "shooting_item_type": r.shooting_item_type or "",
        "duration_seconds": int(r.duration_seconds or 0), "reel_number": r.reel_number,
        "sync_done": bool(r.sync_done), "first_edit_done": bool(r.first_edit_done), "needs_vfx": bool(r.needs_vfx),
        "is_critical": bool(r.is_critical), "notes": r.notes or "", "runtime_selected": bool(r.runtime_selected),
    }


def suggest_header_row(sheet: pip.Sheet) -> int:
    """0-based index of the first row that looks like a header (two known aliases), else first non-empty."""
    first_nonempty = None
    for idx, row in enumerate(sheet.rows[:30]):
        texts = [c.display for c in row if c.kind != "empty"]
        if not texts:
            continue
        if first_nonempty is None:
            first_nonempty = idx
        if len(pin.suggest_mapping(texts, is_tv=True)) >= 2:
            return idx
    return first_nonempty or 0


def sheet_columns(sheet: pip.Sheet, header_idx: int) -> list[dict]:
    """Columns of a sheet with a stable mapping key (folded header text, numbered on repeats)."""
    header = sheet.rows[header_idx] if 0 <= header_idx < len(sheet.rows) else []
    width = sheet.width
    seen: dict[str, int] = {}
    cols = []
    for idx in range(width):
        cell = header[idx] if idx < len(header) else pip.Cell(None, "empty")
        text_ = cell.display.strip() if cell.kind != "empty" else ""
        folded = pin.fold_text(text_)
        if folded:
            seen[folded] = seen.get(folded, 0) + 1
            key = folded if seen[folded] == 1 else f"{folded}#{seen[folded]}"
        else:
            key = f"@{pin.column_letter(idx)}"
        samples = []
        has_data = False
        for row in sheet.rows[header_idx + 1:header_idx + 200]:
            if idx < len(row) and row[idx].kind != "empty":
                has_data = True
                if len(samples) < 4:
                    samples.append(row[idx].display[:60])
        cols.append({"index": idx, "letter": pin.column_letter(idx), "header": text_, "key": key, "samples": samples, "has_data": has_data})
    return cols


def _changed_since_preview(stored: dict, fresh: dict, decisions: dict) -> list[str]:
    """Rows (and their days) with a non-skip choice whose data differs from the preview."""
    fresh_rows = {r["id"]: r for r in fresh.get("rows", [])}
    stored_days = {g["key"]: g.get("fingerprint") for g in stored.get("days", [])}
    fresh_days = {g["key"]: g.get("fingerprint") for g in fresh.get("days", [])}
    changed = []
    for r in stored.get("rows", []):
        d = decisions.get(r["id"]) or {}
        if (d.get("action") or pim.ACTION_SKIP) == pim.ACTION_SKIP:
            continue
        f = fresh_rows.get(r["id"])
        if f is None or f.get("fingerprint") != r.get("fingerprint"):
            changed.append(r["id"])
            continue
        key = r.get("day_key")
        if key and stored_days.get(key) != fresh_days.get(key):
            changed.append(r["id"])
    return changed


def _dur_minutes(secs: int) -> int:
    return (secs + 59) // 60 if secs else 0


def _apply(svc: ImportService, sess, plan: dict, sources: dict[str, pin.SourceRow], decisions: dict,
           *, account, hooks: dict) -> dict:
    """All writes for one import. Runs inside the caller's transaction; raises to roll back."""
    db = svc.db
    M = svc.M
    SD, SDS = M["ShootingDay"], M["ShootingDayScene"]
    ctx = svc.project_context(sess.project_id)
    project = ctx["project"]
    is_tv, max_ep = ctx["is_tv"], ctx["max_episode"]
    pah, pas = hooks["pah"], hooks["pas"]
    day_by_key = {g["key"]: g for g in plan["days"]}
    day_objs: dict[str, Any] = {}
    created_days: list[dict] = []
    touched_days: dict[int, str] = {}
    row_results: list[dict] = []
    needs_vfx_bridge = False

    def day_for(key: str):
        if key in day_objs:
            return day_objs[key]
        g = day_by_key[key]
        t = g["target"]
        if t["kind"] == "existing":
            day = db.session.get(SD, int(t["day_id"]))
            if day is None or int(day.project_id) != int(sess.project_id):
                raise ImportError_("A shooting day of this import no longer belongs to the project.")
        else:
            unit = int(t["unit"])
            dkey = pin.day_key(t["day_name"])
            for d in SD.query.filter_by(project_id=int(sess.project_id), unit_number=unit).all():
                if pin.day_key(d.day_name) == dkey:
                    raise ImportError_(f"Unit {unit} {t['day_name']} was created by someone else meanwhile. Review again.")
            day = SD(project_id=int(sess.project_id), unit_number=unit, day_name=t["day_name"],
                     shooting_date=date.fromisoformat(t["date"]), location=(t.get("location") or "")[:255])
            if project is not None:
                project.lifecycle_status = "post_production"
            db.session.add(day)
            db.session.flush()
            pah.log_shooting_day_created(day, source="import")
            created_days.append({"id": int(day.id), "label": pim.day_label(_day_dict(day))})
        day_objs[key] = day
        touched_days[int(day.id)] = pim.day_label(_day_dict(day))
        return day

    for r in plan["rows"]:
        d = decisions.get(r["id"]) or {"action": pim.ACTION_SKIP}
        action = d["action"]
        if action == pim.ACTION_SKIP:
            row_results.append(_result(r, "skipped", None, None, r.get("reason", "")))
            continue
        src = sources.get(r["id"])
        if src is None:
            raise ImportError_(f"{r['id']} is no longer in the file.")
        day = day_for(r["day_key"])
        if action in (pim.ACTION_ADD, pim.ACTION_ADD_RESHOOT):
            link = _add_row(svc, src, day, reshoot=action == pim.ACTION_ADD_RESHOOT, is_tv=is_tv, max_ep=max_ep, hooks=hooks)
            needs_vfx_bridge = needs_vfx_bridge or bool(link.needs_vfx)
            pah.log_shooting_item_created(link, day)
            row_results.append(_result(r, "added", link.id, day, "Added as Reshoot." if action == pim.ACTION_ADD_RESHOOT else "Added.",
                                       identity=pim._existing_label(row_snapshot(link), is_tv=is_tv)))
        elif action == pim.ACTION_UPDATE:
            link = db.session.get(SDS, int(d["target_id"]))
            if link is None or int(link.shooting_day_id) != int(day.id):
                raise ImportError_(f"Row #{d['target_id']} no longer belongs to this shooting day.")
            before = pas.shooting_item_snapshot(link)
            _update_row(svc, link, src, d, is_tv=is_tv, max_ep=max_ep, hooks=hooks)
            after = pas.shooting_item_snapshot(link)
            pah.log_shooting_item_updated(link, before, after, day=day)
            needs_vfx_bridge = needs_vfx_bridge or bool(link.needs_vfx)
            n_fields = len(d.get("fields") or []) + len(d.get("clear") or [])
            row_results.append(_result(r, "updated", link.id, day, f"{n_fields} field(s) updated.",
                                       identity=pim._existing_label(row_snapshot(link), is_tv=is_tv)))

    for g in plan["days"]:
        dec = g.get("decision") or {}
        lc = g.get("location_change")
        if not lc or not dec.get("update_location") or not g.get("target") or g["target"]["kind"] != "existing":
            continue
        day = day_for(g["key"])
        before = pas.shooting_day_snapshot(day)
        day.location = lc["incoming"][:255]
        pah.log_shooting_day_updated(day, before, pas.shooting_day_snapshot(day))

    db.session.flush()
    counts = {
        "days_created": len(created_days),
        "rows_added": sum(1 for x in row_results if x["outcome"] == "added"),
        "rows_updated": sum(1 for x in row_results if x["outcome"] == "updated"),
        "rows_skipped": sum(1 for x in row_results if x["outcome"] == "skipped"),
    }
    return {
        "counts": counts,
        "created_days": created_days,
        "days": [{"id": k, "label": v} for k, v in touched_days.items()],
        "rows": row_results,
        "needs_vfx_bridge": needs_vfx_bridge,
        "file": sess.original_filename,
        "source": source_summary(svc.options(sess).get("source"), sess, plan.get("worksheets", [])),
        "worksheets": plan.get("worksheets", []),
        "importer_account_id": int(account.id) if account is not None else None,
        "executed_at": svc.now().isoformat(timespec="seconds"),
    }


def source_summary(source: dict | None, sess, worksheets: list[str]) -> dict:
    if not source:
        return {"type": sess.file_kind, "file": sess.original_filename, "file_sha256": sess.file_sha256}
    loaded = {x["title"]: x for x in source.get("loaded") or []}
    fresh = source.get("freshness") or {}
    return {
        "type": "google_sheets",
        "spreadsheet_id": source.get("spreadsheet_id"),
        "title": source.get("title"),
        "worksheets": [{"title": t, "sheet_id": loaded.get(t, {}).get("sheet_id"), "range": loaded.get(t, {}).get("range")}
                       for t in worksheets],
        "fetched_at": source.get("fetched_at"),
        "time_zone": source.get("time_zone"),
        "locale": source.get("locale"),
        "snapshot_sha256": sess.file_sha256,
        "freshness": fresh.get("state") or "not_checked",
    }


def _day_dict(day) -> dict:
    return {"id": day.id, "unit_number": day.unit_number, "day_name": day.day_name, "shooting_date": day.shooting_date}


def _result(r: dict, outcome: str, record_id, day, message: str, *, identity: str = "") -> dict:
    return {
        "row_id": r["id"], "sheet": r["sheet"], "row": r["row_number"], "status": r["status"], "outcome": outcome,
        "record_id": int(record_id) if record_id else None, "day_id": int(day.id) if day is not None else None,
        "identity": identity or r.get("identity", ""), "message": message,
    }


def _identity_for(src: pin.SourceRow, *, item_type: str | None, is_tv: bool, max_ep: int) -> dict:
    if item_type:
        src = pin.SourceRow(sheet=src.sheet, row_number=src.row_number, values={**src.values, "item_type": pin.ParsedValue(pin.VALUE, item_type, item_type)})
    ident, err = pim.row_identity(src, is_tv=is_tv, max_episode=max_ep)
    if err or ident is None:
        raise ImportError_(f"{src.sheet} row {src.row_number}: {err}")
    return ident


def _value(src: pin.SourceRow, key: str, default: Any) -> Any:
    v = src.get(key)
    return v.value if v.state == pin.VALUE else default


def _add_row(svc: ImportService, src: pin.SourceRow, day, *, reshoot: bool, is_tv: bool, max_ep: int, hooks: dict):
    SDS = svc.M["ShootingDayScene"]
    ident = _identity_for(src, item_type="Reshoot" if reshoot else None, is_tv=is_tv, max_ep=max_ep)
    item_type = si.coerce_shooting_item_type(ident["item_type"])
    if item_type != ident["item_type"]:
        raise ImportError_(f"{src.sheet} row {src.row_number}: “{ident['item_type']}” cannot be created.")
    if si.should_check_episode_scene_duplicate(item_type):
        dup = hooks["find_duplicate"](
            int(day.project_id), ident["episode_number"], ident["scene_label"],
            is_episode_unassigned=ident["unassigned"], is_establishing_shots_pool=ident["pool"],
        )
        if dup is not None:
            raise ImportError_(
                f"{src.sheet} row {src.row_number}: scene {ident['scene_label']} already exists in this episode (row #{dup.id})."
            )
    secs = int(_value(src, "duration", 0) or 0)
    sync_done = bool(_value(src, "sync_done", False))
    first_edit = bool(_value(src, "first_edit_done", False))
    link = SDS(
        shooting_day_id=int(day.id),
        scene_id=hooks["next_scene_id"](int(day.id)),
        episode_number=ident["episode_number"],
        is_episode_unassigned=ident["unassigned"],
        is_establishing_shots_pool=ident["pool"],
        scene_label=ident["scene_label"],
        scene_number=1,
        duration=_dur_minutes(secs),
        duration_seconds=secs,
        actual_duration_minutes=_dur_minutes(secs),
        notes=str(_value(src, "notes", "") or "").strip(),
        status="done" if (sync_done and first_edit) else "pending",
        sync_done=sync_done,
        first_edit_done=first_edit,
        needs_vfx=si.apply_auto_vfx_for_type(item_type, bool(_value(src, "needs_vfx", False))),
        is_critical=bool(_value(src, "is_critical", False)),
        shooting_item_type=item_type,
        reel_number=_value(src, "reel_number", None),
    )
    svc.db.session.add(link)
    svc.db.session.flush()
    siblings = hooks["runtime_siblings"](int(day.project_id), link, exclude_link_id=link.id)
    si.apply_runtime_selection_for_new_row(link, siblings)
    return link


def _update_row(svc: ImportService, link, src: pin.SourceRow, decision: dict, *, is_tv: bool, max_ep: int, hooks: dict) -> None:
    fields = set(decision.get("fields") or [])
    clear = set(decision.get("clear") or [])
    identity_change = bool(fields & set(pim.IDENTITY_FIELDS))
    if identity_change:
        merged = pin.SourceRow(sheet=src.sheet, row_number=src.row_number, values=dict(src.values))
        current_ep = "X" if link.is_episode_unassigned else ("establishing" if link.is_establishing_shots_pool else str(link.episode_number or ""))
        if "episode" not in fields:
            merged.values["episode"] = pin.ParsedValue(pin.VALUE, current_ep, current_ep) if current_ep else pin.ParsedValue(pin.EMPTY)
        if "scene_label" not in fields:
            merged.values["scene_label"] = pin.ParsedValue(pin.VALUE, link.scene_label or "", link.scene_label or "")
        if "item_type" not in fields:
            merged.values["item_type"] = pin.ParsedValue(pin.VALUE, si.normalize_shooting_item_type(link.shooting_item_type), "")
        ident = _identity_for(merged, item_type=None, is_tv=is_tv, max_ep=max_ep)
        new_type = ident["item_type"]
        if "item_type" in fields and si.coerce_shooting_item_type(new_type) != new_type:
            raise ImportError_(f"{src.sheet} row {src.row_number}: “{new_type}” cannot be set on a row.")
        if si.should_check_episode_scene_duplicate(new_type):
            dup = hooks["find_duplicate"](
                int(link.shooting_day.project_id), ident["episode_number"], ident["scene_label"],
                is_episode_unassigned=ident["unassigned"], is_establishing_shots_pool=ident["pool"], exclude_link_id=link.id,
            )
            if dup is not None:
                raise ImportError_(f"{src.sheet} row {src.row_number}: scene {ident['scene_label']} already exists (row #{dup.id}).")
        link.episode_number = ident["episode_number"]
        link.is_episode_unassigned = ident["unassigned"]
        link.is_establishing_shots_pool = ident["pool"]
        link.scene_label = ident["scene_label"]
        link.scene_number = 1
        link.shooting_item_type = new_type
    if "duration" in fields:
        secs = int(_value(src, "duration", 0) or 0)
        link.duration_seconds, link.duration, link.actual_duration_minutes = secs, _dur_minutes(secs), _dur_minutes(secs)
    if "duration" in clear:
        link.duration_seconds = link.duration = link.actual_duration_minutes = 0
    if "reel_number" in fields:
        link.reel_number = _value(src, "reel_number", None)
    if "reel_number" in clear:
        link.reel_number = None
    if "notes" in fields:
        link.notes = str(_value(src, "notes", "") or "").strip()
    if "notes" in clear:
        link.notes = ""
    for key in ("sync_done", "first_edit_done", "needs_vfx", "is_critical"):
        if key in fields:
            setattr(link, key, bool(_value(src, key, False)))
    link.needs_vfx = si.apply_auto_vfx_for_type(link.shooting_item_type, bool(link.needs_vfx))
    if fields & {"sync_done", "first_edit_done"}:
        link.status = "done" if (link.sync_done and link.first_edit_done) else "pending"
    if identity_change:
        svc.db.session.flush()
        if si.is_runtime_eligible_row(link):
            siblings = hooks["runtime_siblings"](int(link.shooting_day.project_id), link, exclude_link_id=link.id)
            link.runtime_selected = False
            si.apply_runtime_selection_for_new_row(link, siblings)
        else:
            link.runtime_selected = False


# --- Results download -------------------------------------------------------------

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: Any) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(_FORMULA_PREFIXES) else s


def results_csv(result: dict, plan_rows: list[dict] | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Worksheet", "Row", "Preview status", "Outcome", "BigBang record", "Shooting day", "Identity", "Details"])
    days = {d["id"]: d["label"] for d in result.get("days", [])}
    for r in result.get("rows", []):
        w.writerow([csv_safe(x) for x in (
            r.get("sheet"), r.get("row"), pim.STATUS_LABELS.get(r.get("status"), r.get("status")), r.get("outcome"),
            r.get("record_id") or "", days.get(r.get("day_id"), ""), r.get("identity"), r.get("message"),
        )])
    return "\ufeff" + buf.getvalue()


def _secs_label(secs: int) -> str:
    return f"{secs} s · {pim.format_duration(secs)}"


def _shift_signal(cells: list[pip.Cell]) -> bool:
    """True when Excel times look like typed M:SS (whole minutes only, small "hours")."""
    secs = [pin.excel_time_seconds(c, "hmm") for c in cells]
    return bool(secs) and all(s % 60 == 0 for s in secs) and any(s >= 3600 for s in secs) and all(s < 60 * 3600 for s in secs)


def scan_examples(svc: ImportService, sess, workbook: pip.Workbook, ctx: dict, *, mapping: dict | None = None) -> dict:
    """Preparation scan of the mapped columns: examples, duration analysis, status tokens, fill-down.

    ``mapping`` (column key → field) overrides the saved mapping, e.g. the suggestions shown on a first visit.
    """
    opts = svc.options(sess)
    if mapping is not None:
        opts["mapping"] = mapping
    parse_opts = pin.ParseOptions.from_dict(opts.get("parse") or {}, is_tv=ctx["is_tv"], max_episode=ctx["max_episode"])
    fixed = bool(sess.target_day_id)
    out: dict[str, Any] = {
        "date_ambiguous": 0, "time_cells": 0, "formula_missing": 0, "examples": {},
        "durations": [], "duration_needs_choice": False, "duration_recommended": "hmm",
        "tokens": {}, "tokens_unknown": 0, "fill_candidates": {}, "placeholders": 0,
    }
    mapping_opts = opts.get("mapping") or {}
    for name in opts.get("sheets") or []:
        sheet = workbook.sheet(name)
        if sheet is None:
            continue
        out["formula_missing"] += sheet.formula_missing
        st = (opts.get("sheet_settings") or {}).get(name) or {}
        header_idx = max(0, int(st.get("header_row") or 1) - 1)
        first = header_idx + 1 + int(st.get("skip_rows") or 0)
        data_rows = list(enumerate(sheet.rows[first:], start=first + 1))
        cols = sheet_columns(sheet, header_idx)
        mapped = {c["index"]: mapping_opts.get(c["key"]) or "" for c in cols}
        mapped = {i: f for i, f in mapped.items() if f in pin.FIELD_BY_KEY}
        anchors = sheet.merge_anchors()
        for col in cols:
            field = mapped.get(col["index"], "")
            if not field:
                continue
            idx = col["index"]
            cells = [(rn, row[idx]) for rn, row in data_rows if idx < len(row) and row[idx].kind != "empty"]
            if field == "duration":
                _scan_duration(out, name, col, cells, parse_opts)
                continue
            if pin.FIELD_BY_KEY[field].kind == "bool":
                _scan_tokens(out, name, col, field, cells, parse_opts)
                continue
            if field in ("shooting_date", "item_type", "day_name", "episode", "scene_label"):
                ex = out["examples"].setdefault(field, [])
                for _rn, cell in cells:
                    if field == "shooting_date" and pin.date_is_ambiguous(cell):
                        out["date_ambiguous"] += 1
                    if len(ex) >= 5 or cell.display in {e["raw"] for e in ex}:
                        continue
                    pv = pin.parse_field(field, cell, parse_opts)
                    shown = pv.value
                    if field == "day_name" and pv.state == pin.VALUE:
                        shown = pin.storage_day_name(str(pv.value))
                    elif isinstance(shown, date):
                        shown = shown.strftime("%d %b %Y")
                    ex.append({"raw": cell.display, "kind": cell.kind, "value": "" if shown is None else str(shown),
                               "error": pv.error})
        if not fixed:
            other = [i for i, f in mapped.items() if f not in pin.FILL_DOWN_FIELDS]
            cands = []
            for idx, field in mapped.items():
                if field not in pin.FILL_DOWN_FIELDS:
                    continue
                explicit = blank = merged = 0
                seen_value = False
                for rn, row in data_rows:
                    cell = row[idx] if idx < len(row) else pip.Cell(None, "empty")
                    has_other = any(i < len(row) and row[i].kind != "empty" for i in other)
                    if cell.kind != "empty":
                        explicit += 1
                        seen_value = True
                    elif has_other and seen_value:
                        blank += 1
                        if (rn, idx + 1) in anchors:
                            merged += 1
                cands.append({
                    "field": field, "label": pin.FIELD_BY_KEY[field].label, "column": pin.column_letter(idx),
                    "explicit": explicit, "blank": blank, "merged": merged,
                    "suggested": explicit > 0 and blank >= explicit,
                })
            cands.sort(key=lambda c: pin.FILL_DOWN_FIELDS.index(c["field"]))
            if cands:
                out["fill_candidates"][name] = cands
    durations = out["durations"]
    out["time_cells"] = sum(d["counts"].get(pin.DURATION_TIME_OF_DAY, 0) for d in durations)
    out["has_excel_times"] = any(d["counts"].get(pin.DURATION_ELAPSED) or d["counts"].get(pin.DURATION_TIME_OF_DAY)
                                 for d in durations)
    out["duration_needs_choice"] = out["time_cells"] > 0
    if any(d.get("shift_signal") for d in durations):
        out["duration_recommended"] = ""
    out["tokens_unknown"] = sum(1 for f in out["tokens"].values() for t in f["items"] if not t["meaning"])
    return out


def _scan_duration(out: dict, sheet_name: str, col: dict, cells: list, parse_opts: pin.ParseOptions) -> None:
    counts: dict[str, int] = {}
    formats: dict[str, int] = {}
    excel_cells: list[pip.Cell] = []
    by_kind: dict[str, list] = {}
    placeholders = 0
    longest = None
    for rn, cell in cells:
        if cell.kind == "text" and pin.blank_key(cell.value) in parse_opts.blank_tokens:
            placeholders += 1
            continue
        kind = pin.duration_cell_kind(cell)
        counts[kind] = counts.get(kind, 0) + 1
        label = cell.fmt or ("General" if cell.kind in ("number", "text") else cell.kind)
        formats[label] = formats.get(label, 0) + 1
        by_kind.setdefault(kind, []).append((rn, cell))
        if kind in (pin.DURATION_ELAPSED, pin.DURATION_TIME_OF_DAY):
            excel_cells.append(cell)
            secs = pin.excel_time_seconds(cell, "hmm")
            if longest is None or secs > longest[0]:
                longest = (secs, rn, cell)
    picks: list = []
    for kind in (pin.DURATION_ELAPSED, pin.DURATION_TIME_OF_DAY, pin.DURATION_NUMBER, pin.DURATION_TEXT):
        for item in by_kind.get(kind, [])[: (4 if kind == pin.DURATION_ELAPSED else 2)]:
            picks.append(item)
    if longest and longest[0] >= 86400 and all(p[0] != longest[1] for p in picks):
        picks.append((longest[1], longest[2]))
    examples = []
    for rn, cell in picks:
        kind = pin.duration_cell_kind(cell)
        ex = {"ref": f"{col['letter']}{rn}", "raw": cell.display, "fmt": cell.fmt or "General",
              "kind": pin.DURATION_KIND_LABELS[kind]}
        if kind in (pin.DURATION_ELAPSED, pin.DURATION_TIME_OF_DAY):
            ex["as_shown"] = _secs_label(pin.excel_time_seconds(cell, "hmm"))
            ex["shifted"] = _secs_label(pin.excel_time_seconds(cell, "mss"))
        pv = pin.parse_field("duration", cell, parse_opts)
        ex["result"] = _secs_label(int(pv.value)) if pv.state == pin.VALUE else ""
        ex["error"] = pv.error
        examples.append(ex)
    out["placeholders"] += placeholders
    out["durations"].append({
        "sheet": sheet_name, "column": col["letter"], "header": col["header"], "counts": counts,
        "formats": sorted(formats.items(), key=lambda kv: -kv[1]), "placeholders": placeholders,
        "examples": examples, "shift_signal": _shift_signal(excel_cells),
        "longest": _secs_label(longest[0]) if longest else "",
    })


def _scan_tokens(out: dict, sheet_name: str, col: dict, field: str, cells: list, parse_opts: pin.ParseOptions) -> None:
    entry = out["tokens"].setdefault(field, {"field": field, "label": pin.FIELD_BY_KEY[field].label,
                                             "columns": [], "items": []})
    entry["columns"].append(f"{sheet_name} ({col['letter']})")
    items = {t["token"]: t for t in entry["items"]}
    for rn, cell in cells:
        if cell.kind == "bool":
            continue
        if cell.kind == "text" and pin.blank_key(cell.value) in parse_opts.blank_tokens:
            continue
        raw = cell.display.strip()
        tok = pin.token_key(raw)
        if not tok:
            continue
        item = items.get(tok)
        if item is None:
            meaning = parse_opts.token_meaning(field, tok)
            scope = "field" if tok in parse_opts.field_tokens.get(field, {}) else ("shared" if meaning else "")
            item = {"token": tok, "display": raw, "count": 0, "samples": [], "meaning": meaning, "scope": scope}
            items[tok] = item
            entry["items"].append(item)
        item["count"] += 1
        if len(item["samples"]) < 3:
            item["samples"].append(f"{sheet_name}!{col['letter']}{rn}")
    entry["items"].sort(key=lambda t: (bool(t["meaning"]), -t["count"]))
