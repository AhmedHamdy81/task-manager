"""Import & Compare for production spreadsheets (.xlsx / .csv)."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from datetime import date, datetime, time, timedelta
from unittest import mock

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_production_import.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

import openpyxl

from app import app, db
import production_import_matching as pim
import production_import_normalize as pin
import production_import_parsing as pip
import production_import_service as pis

HEADERS = "Day,Unit,Date,Episode,Scene,Type,Duration,Sync,First Edit,Notes,BigBang ID,Camera"
MAP = {
    "day": "day_name", "unit": "unit_number", "date": "shooting_date", "episode": "episode", "scene": "scene_label",
    "type": "item_type", "duration": "duration", "sync": "sync_done", "first edit": "first_edit_done",
    "notes": "notes", "bigbang id": "record_id", "camera": "",
}


def _csv(*lines: str, headers: str = HEADERS) -> bytes:
    return ("\ufeff" + "\n".join((headers,) + lines) + "\n").encode("utf-8")


class ParsingTests(unittest.TestCase):
    """File reading and value interpretation (no database)."""

    def test_csv_bom_arabic_headers_and_digits(self):
        data = "\ufeffاليوم;الوحدة;التاريخ;الحلقة;المشهد;المدة\nيوم ٥;١;2026-10-05;٣;١٢A;٣:١٥\n".encode("utf-8")
        wb = pip.read_workbook(data, pip.CSV)
        self.assertEqual(wb.csv_encoding, "utf-8-sig")
        self.assertEqual(wb.csv_delimiter, ";")
        self.assertFalse(wb.csv_encoding_ambiguous)
        heads = [c.display for c in wb.sheets[0].rows[0]]
        self.assertEqual(heads[0], "اليوم")
        mapping = pin.suggest_mapping(heads, is_tv=True)
        self.assertEqual(
            [mapping[i] for i in range(6)],
            ["day_name", "unit_number", "shooting_date", "episode", "scene_label", "duration"],
        )
        opts = pin.ParseOptions(is_tv=True, max_episode=10)
        rows = pin.build_source_rows("CSV", wb.sheets[0].rows, header_row=0, skip_after_header=0, mapping=mapping,
                                     defaults={}, sheet_day_context={}, opts=opts)
        v = rows[0].values
        self.assertEqual(pin.day_key(v["day_name"].value), "5")
        self.assertEqual(v["unit_number"].value, 1)
        self.assertEqual(v["episode"].value, "3")
        self.assertEqual(v["scene_label"].value, "12A")
        self.assertEqual(v["duration"].value, 195)

    def test_cp1256_and_delimiter_ambiguity_are_reported(self):
        data = "Scene,Notes\n1,مرحبا\n".encode("cp1256")
        wb = pip.read_workbook(data, pip.CSV)
        self.assertTrue(wb.csv_encoding_ambiguous)
        self.assertEqual(wb.sheets[0].rows[1][1].display, "مرحبا")
        _delim, ambiguous = pip.detect_csv_delimiter("a,b;c\n1,2;3\n")
        self.assertTrue(ambiguous)

    def test_rejects_wrong_content_malformed_and_oversized(self):
        with self.assertRaises(pip.ImportFileError):
            pip.read_workbook(b"PK\x03\x04not really a zip", pip.XLSX)
        with self.assertRaises(pip.ImportFileError):
            pip.read_workbook(b"<html><body>x</body></html>", pip.CSV)
        with self.assertRaises(pip.ImportFileError):
            pip.read_workbook(b"Scene\n1\n", pip.XLSX)
        with self.assertRaises(pip.ImportFileError):
            pip.read_workbook(b"a,b\n" * 100, pip.CSV, limits={"max_bytes": 50})
        with self.assertRaises(pip.ImportFileError):
            pip.file_kind("report.xls")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("hello.txt", "x")
        with self.assertRaises(pip.ImportFileError):
            pip.read_workbook(buf.getvalue(), pip.XLSX)

    def test_xlsx_header_selection_typed_cells_and_formulas(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Day 5"
        ws.append(["Production report"])
        ws.append([])
        ws.append(["Scene", "Date", "Duration", "Takes", "Total"])
        ws.append(["12A", datetime(2026, 10, 5), time(3, 15), 2, "=D4*2"])
        ws.append(["14", datetime(2026, 10, 5), time(1, 0), 3, "=D5*2"])
        buf = io.BytesIO()
        wb.save(buf)
        data = _set_cached_value(buf.getvalue(), "E4", "4")
        book = pip.read_workbook(data, pip.XLSX)
        sheet = book.sheets[0]
        self.assertEqual(pis.suggest_header_row(sheet), 2)
        row = sheet.rows[3]
        self.assertEqual(row[1].kind, "datetime")
        self.assertEqual(row[2].kind, "time")
        self.assertEqual((row[4].kind, row[4].value), ("number", 4))
        self.assertEqual(sheet.rows[4][4].kind, "formula_missing")
        self.assertEqual(sheet.formula_missing, 1)
        self.assertTrue(any("formula" in w for w in book.warnings))
        missing = pin.parse_field("notes", sheet.rows[4][4], pin.ParseOptions())
        self.assertEqual(missing.state, pin.INVALID)
        # Excel time cells are never guessed.
        self.assertEqual(pin.parse_duration(row[2], pin.ParseOptions()).state, pin.INVALID)
        self.assertEqual(pin.parse_duration(row[2], pin.ParseOptions(excel_time_mode="mss")).value, 195)
        self.assertEqual(pin.parse_duration(row[2], pin.ParseOptions(excel_time_mode="hmm")).value, 3 * 3600 + 15 * 60)

    def test_date_and_duration_interpretation(self):
        T = lambda s: pip.Cell(s, "text")  # noqa: E731
        self.assertEqual(pin.parse_date(T("03/04/2026"), pin.ParseOptions()).state, pin.INVALID)
        self.assertEqual(pin.parse_date(T("03/04/2026"), pin.ParseOptions(date_order="dmy")).value, date(2026, 4, 3))
        self.assertEqual(pin.parse_date(T("03/04/2026"), pin.ParseOptions(date_order="mdy")).value, date(2026, 3, 4))
        self.assertEqual(pin.parse_date(T("25/04/2026"), pin.ParseOptions()).value, date(2026, 4, 25))
        self.assertEqual(pin.parse_date(T("٢٠٢٦-١٠-٠٥"), pin.ParseOptions()).value, date(2026, 10, 5))
        self.assertEqual(pin.parse_date(T("5 Oct 2026"), pin.ParseOptions()).value, date(2026, 10, 5))
        dur = lambda s, f: pin.parse_duration(T(s), pin.ParseOptions(duration_format=f))  # noqa: E731
        self.assertEqual(dur("3:15", "auto").value, 195)
        self.assertEqual(dur("0315", "auto").value, 195)
        self.assertEqual(dur("3", "auto").value, 180)
        self.assertEqual(dur("3:15", "mss").value, 195)
        self.assertEqual(dur("1:02:03", "hmmss").value, 3723)
        self.assertEqual(dur("3:15", "hmmss").value, 3 * 3600 + 15 * 60)
        self.assertEqual(dur("90", "seconds").value, 90)
        self.assertEqual(dur("2.5", "minutes").value, 150)
        self.assertEqual(dur("abc", "auto").state, pin.INVALID)
        zero = pin.parse_duration(T("0"), pin.ParseOptions(duration_format="seconds"))
        self.assertEqual((zero.state, zero.value), (pin.VALUE, 0))
        self.assertEqual(pin.parse_duration(pip.Cell(None, "empty"), pin.ParseOptions()).state, pin.EMPTY)

    def test_status_tokens_distinguish_empty_false_and_unknown(self):
        o = pin.ParseOptions()
        self.assertEqual(pin.parse_bool(pip.Cell("نعم", "text"), o, "Sync").value, True)
        no = pin.parse_bool(pip.Cell("No", "text"), o, "Sync")
        self.assertEqual((no.state, no.value), (pin.VALUE, False))
        self.assertEqual(pin.parse_bool(pip.Cell(None, "empty"), o, "Sync").state, pin.EMPTY)
        self.assertEqual(pin.parse_bool(pip.Cell("maybe", "text"), o, "Sync").state, pin.INVALID)
        custom = pin.ParseOptions.from_dict({"true_tokens": ["maybe"]}, is_tv=False, max_episode=1)
        self.assertTrue(pin.parse_bool(pip.Cell("Maybe", "text"), custom, "Sync").value)

    def test_day_names_and_item_types(self):
        for raw in ("Day 05", "D5", "5", "day5", "يوم ٥", "اليوم 5", "Shooting Day 5"):
            self.assertEqual(pin.day_key(raw), "5", raw)
        self.assertEqual(pin.storage_day_name("05"), "Day 5")
        self.assertEqual(pin.parse_item_type(pip.Cell("re-shoot", "text")).value, "Reshoot")
        self.assertEqual(pin.parse_item_type(pip.Cell("إعادة", "text")).value, "Reshoot")
        self.assertEqual(pin.parse_item_type(pip.Cell("B-Roll", "text")).value, "B-Roll")
        self.assertEqual(pin.parse_item_type(pip.Cell("Drone pass", "text")).state, pin.INVALID)

    def test_results_csv_escapes_formulas(self):
        self.assertEqual(pis.csv_safe("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(pis.csv_safe("+1"), "'+1")
        self.assertEqual(pis.csv_safe("12A"), "12A")
        body = pis.results_csv({"days": [], "rows": [{"sheet": "=S", "row": 2, "status": "new", "outcome": "added",
                                                       "identity": "@x", "message": "-1"}]})
        self.assertIn("'=S", body)
        self.assertIn("'@x", body)
        self.assertIn("'-1", body)


def _set_cached_value(xlsx: bytes, ref: str, value: str) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(xlsx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet"):
                text = data.decode("utf-8")
                text = re.sub(rf'(<c r="{ref}"[^>]*>\s*<f>[^<]*</f>\s*)<v\s*/?>(</v>)?', rf"\1<v>{value}</v>", text)
                data = text.encode("utf-8")
            dst.writestr(item, data)
    return out.getvalue()


class ImportFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = tempfile.mkdtemp(prefix="tm_pim_")
        app.config["PRODUCTION_IMPORT_STORAGE_DIR"] = cls.storage
        with app.app_context():
            assert not str(db.engine.url).endswith("instance/app.db"), db.engine.url
            db.create_all()
            import material_registration_support as regs
            import machine_room_dashboard_support as mr_dash
            import machine_room_media_workflow_support as wf

            now = datetime.utcnow
            mr_dash.ensure_machine_room_dashboard_tables(db, now)
            wf.ensure_machine_room_media_workflow_tables(db, now)
            regs.ensure_material_registration_table(db, now)
            pis.ensure_tables(db, now)

    @classmethod
    def tearDownClass(cls):
        app.config.pop("PRODUCTION_IMPORT_STORAGE_DIR", None)
        shutil.rmtree(cls.storage, ignore_errors=True)

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.api = app.extensions["production_import"]
        self.svc = self.api.service
        self.M = {**app.extensions["tm_test_models"], **self.svc.M}
        self._wipe()
        M = self.M
        self.admin = self._account("pim-admin@test.local", "admin", "Importer")
        self.other = self._account("pim-other@test.local", "admin", "Other Admin")
        self.member = self._account("pim-member@test.local", "producer", "Producer")
        self.project = M["Project"](name="Import Show", project_type="TV Series", number_of_episodes=10,
                                    production_house="T", director="T")
        self.other_project = M["Project"](name="Other Show", project_type="TV Series", number_of_episodes=5,
                                          production_house="T", director="T")
        db.session.add_all([self.project, self.other_project])
        db.session.flush()
        db.session.add(M["ProjectMember"](project_id=self.project.id, user_id=self.member[1].id))
        SD, SDS = M["ShootingDay"], M["ShootingDayScene"]
        self.day1 = SD(project_id=self.project.id, unit_number=1, day_name="Day 1", shooting_date=date(2026, 10, 1),
                       location="Studio A")
        self.foreign_day = SD(project_id=self.other_project.id, unit_number=1, day_name="Day 1",
                              shooting_date=date(2026, 10, 1))
        db.session.add_all([self.day1, self.foreign_day])
        db.session.flush()

        def row(day, ep, label, typ="Scene", secs=0, **kw):
            r = SDS(shooting_day_id=day.id, scene_id=SDS.query.filter_by(shooting_day_id=day.id).count() + 1,
                    episode_number=ep, scene_label=label, shooting_item_type=typ, duration_seconds=secs,
                    duration=(secs + 59) // 60, actual_duration_minutes=(secs + 59) // 60, **kw)
            db.session.add(r)
            db.session.flush()
            return r

        self.row_12a = row(self.day1, 1, "12A", secs=195, notes="old note", runtime_selected=True)
        self.row_7 = row(self.day1, 1, "7", secs=60, notes="", runtime_selected=True)
        self.reshoot_a = row(self.day1, 1, "5", "Reshoot", 60)
        self.reshoot_b = row(self.day1, 1, "5", "Reshoot", 70)
        self.foreign_row = row(self.foreign_day, 1, "1", secs=10)
        self.legacy = M["SceneRow"](shooting_day_id=self.day1.id, episode="1", scene="30", sort_order=0)
        db.session.add(self.legacy)
        db.session.commit()
        self._login(self.admin[0])

    def tearDown(self):
        db.session.rollback()
        self._wipe()
        db.session.remove()
        self.ctx.pop()

    def _wipe(self):
        M = self.M
        for model in (
            self.svc.Session, self.svc.Preset, M["ProjectActivityLog"], M["Notification"], M["SceneRow"],
            M["ShootingDayScene"], M["ShootingDay"], M["ProjectMember"], M["Project"], M["User"], M["Account"],
        ):
            db.session.query(model).delete()
        reg_api = app.extensions.get("material_registration")
        if reg_api is not None:
            db.session.query(reg_api.Registration).delete()
        db.session.commit()

    def _account(self, email, role, name):
        acc = self.M["Account"](email=email, password_hash="x", role=role)
        db.session.add(acc)
        db.session.flush()
        user = self.M["User"](name=name, email=email, account_id=acc.id)
        db.session.add(user)
        db.session.flush()
        return acc, user

    def _login(self, acc):
        with self.client.session_transaction() as s:
            s["account_id"] = acc.id

    # -- wizard helpers --

    def _base(self, pid=None):
        return f"/projects/{pid or self.project.id}/production/days/import"

    def _upload(self, data: bytes, name="shoot.csv", day_id=None, expect_ok=True):
        url = self._base() + (f"?day_id={day_id}" if day_id else "")
        res = self.client.post(url, data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 302, res.data[:300])
        m = re.search(r"/import/([^/]+)/sheets", res.headers["Location"])
        if expect_ok:
            self.assertIsNotNone(m, res.headers["Location"])
        return m.group(1) if m else None

    def _sheets(self, token, **form):
        sess = self.svc.get_session(token)
        opts = self.svc.options(sess)
        data = {"layout": "table", "sheets": opts["sheets"], "header_0": "1", "skip_0": "0"}
        if sess.file_kind == "csv":
            data.update(csv_encoding=opts["csv"]["encoding"], csv_delimiter=opts["csv"]["delimiter"])
        data.update(form)
        return self.client.post(f"{self._base()}/{token}/sheets", data=data)

    def _mapping(self, token, mapping=None, **form):
        data = {f"map__{k}": v for k, v in (mapping or MAP).items()}
        data.update({"action": "continue", "default__unit_number": "1", "duration_format": "auto", "date_order": "dmy"})
        data.update(form)
        return self.client.post(f"{self._base()}/{token}/mapping", data=data)

    def _plan(self, token, *, page=True):
        if page:
            res = self.client.get(f"{self._base()}/{token}/preview")
            self.assertEqual(res.status_code, 200, res.data[:500])
        sess = self.svc.get_session(token)
        db.session.refresh(sess)
        return json.loads(sess.plan_json)

    def _prepare(self, data, **kw):
        token = self._upload(data, **{k: v for k, v in kw.items() if k in ("name", "day_id")})
        self.assertEqual(self._sheets(token).status_code, 302)
        res = self._mapping(token, kw.get("mapping"))
        self.assertEqual(res.status_code, 302, res.data[:2000])
        return token, self._plan(token)

    def _decide(self, token, decisions):
        sess = self.svc.get_session(token)
        res = self.client.post(f"{self._base()}/{token}/preview",
                               data={"action": "decisions", "plan_hash": sess.plan_hash, "decisions": json.dumps(decisions)})
        return res

    def _confirm(self, token):
        sess = self.svc.get_session(token)
        db.session.refresh(sess)
        return self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": sess.plan_hash})

    def _by_row(self, plan):
        return {r["row_number"]: r for r in plan["rows"]}

    def _counts(self):
        M = self.M
        return (
            M["ShootingDay"].query.count(), M["ShootingDayScene"].query.count(), M["ProjectActivityLog"].query.count(),
            M["Notification"].query.count(),
            tuple((r.id, r.duration_seconds, r.sync_done, r.notes) for r in M["ShootingDayScene"].query.order_by("id")),
        )

    STATUS_FILE = _csv(
        "Day 1,1,01/10/2026,1,12a,Scene,3:15,,,,,A-cam",        # 2 identical (case-insensitive 12A)
        "Day 1,1,01/10/2026,1,7,Scene,2:00,yes,,,,A-cam",       # 3 changed
        "Day 1,1,01/10/2026,1,5,Reshoot,1:00,,,,,",             # 4 ambiguous: two reshoots exist
        "Day 1,1,01/10/2026,1,99,Scene,abc,,,,,",               # 5 invalid duration
        "D2,1,02/10/2026,2,1,Scene,1:30,,,,,",                  # 6 new on a new day
        "D2,1,02/10/2026,2,1,Scene,1:30,,,,,",                  # 7 duplicate in source
        "Day 1,1,01/10/2026,1,30,Scene,,,,,,",                  # 8 legacy row match -> ambiguous
        "Day 1,1,01/10/2026,1,12A,Reshoot,0:40,,,,,",           # 9 new: reshoot never merges into the scene
        "Day 2,1,02/10/2026,1,7,Scene,1:10,,,,,",               # 10 scene exists on Day 1 -> ambiguous
    )

    # -- tests --

    def test_all_six_statuses_and_matching_rules(self):
        _token, plan = self._prepare(self.STATUS_FILE)
        rows = self._by_row(plan)
        self.assertEqual(rows[2]["status"], pim.STATUS_IDENTICAL)
        self.assertEqual(rows[2]["match"]["id"], self.row_12a.id)
        self.assertEqual(rows[3]["status"], pim.STATUS_CHANGED)
        self.assertEqual({d["field"] for d in rows[3]["diffs"]}, {"duration", "sync_done"})
        self.assertEqual(rows[4]["status"], pim.STATUS_AMBIGUOUS)
        self.assertEqual({c["id"] for c in rows[4]["candidates"]}, {self.reshoot_a.id, self.reshoot_b.id})
        self.assertEqual(rows[5]["status"], pim.STATUS_INVALID)
        self.assertEqual(rows[5]["errors"][0]["value"], "abc")
        self.assertIn("Duration", rows[5]["errors"][0]["column"])
        self.assertEqual(rows[6]["status"], pim.STATUS_NEW)
        self.assertEqual(rows[7]["status"], pim.STATUS_DUPLICATE)
        self.assertEqual(rows[8]["status"], pim.STATUS_AMBIGUOUS)
        self.assertEqual(rows[8]["legacy_match"]["id"], self.legacy.id)
        self.assertEqual(rows[9]["status"], pim.STATUS_NEW)
        self.assertEqual(rows[10]["status"], pim.STATUS_AMBIGUOUS)
        self.assertIn(pim.ACTION_ADD_RESHOOT, rows[10]["allowed_actions"])
        self.assertNotIn(pim.ACTION_ADD, rows[10]["allowed_actions"])
        days = {g["key"]: g for g in plan["days"]}
        self.assertEqual(days["u1|1"]["status"], pim.DAY_EXISTING)
        self.assertEqual(days["u1|2"]["status"], pim.DAY_NEW)
        self.assertTrue(any(c["header"] == "Camera" for c in plan["ignored_columns"]))
        # Defaults: identical skipped, new added, changed/ambiguous kept, invalid excluded.
        self.assertEqual(rows[2]["default_action"], "skip")
        self.assertEqual(rows[6]["default_action"], "add")
        self.assertEqual(rows[3]["default_action"], "skip")
        self.assertEqual(rows[4]["default_action"], "skip")
        self.assertEqual(rows[5]["allowed_actions"], ["skip"])

    def test_upload_mapping_and_preview_do_not_mutate(self):
        before = self._counts()
        self._prepare(self.STATUS_FILE)
        self.assertEqual(self._counts(), before)
        self.assertEqual(os.listdir(self.storage) != [], True)

    def test_execute_field_level_updates_clears_new_days_and_audit(self):
        token, plan = self._prepare(self.STATUS_FILE)
        rows = self._by_row(plan)
        decisions = {
            rows[3]["id"]: {"action": "update", "target_id": self.row_7.id, "fields": ["sync_done"]},
            rows[2]["id"]: {"action": "update", "target_id": self.row_12a.id, "fields": [], "clear": ["notes"]},
            rows[6]["id"]: {"action": "add"},
            rows[9]["id"]: {"action": "add"},
            rows[10]["id"]: {"action": "add_reshoot"},
        }
        res = self._decide(token, decisions)
        self.assertEqual(res.status_code, 302, res.data[:500])
        self.assertIn("/confirm", res.headers["Location"])
        page = self.client.get(f"{self._base()}/{token}/confirm")
        self.assertIn(b"row(s) added", page.data)
        res = self._confirm(token)
        self.assertEqual(res.status_code, 302)
        self.assertIn("/results", res.headers["Location"])
        M = self.M
        db.session.expire_all()
        r7 = db.session.get(M["ShootingDayScene"], self.row_7.id)
        self.assertTrue(r7.sync_done)
        self.assertEqual(r7.duration_seconds, 60, "unselected fields stay unchanged")
        self.assertEqual(r7.status, "pending")
        r12 = db.session.get(M["ShootingDayScene"], self.row_12a.id)
        self.assertEqual(r12.notes, "")
        self.assertEqual(r12.scene_label, "12A")
        self.assertTrue(r12.runtime_selected)
        day2 = M["ShootingDay"].query.filter_by(project_id=self.project.id, day_name="Day 2").one()
        self.assertEqual(day2.shooting_date, date(2026, 10, 2))
        added = M["ShootingDayScene"].query.filter_by(shooting_day_id=day2.id).order_by("id").all()
        self.assertEqual([(a.episode_number, a.scene_label, a.shooting_item_type) for a in added],
                         [(2, "1", "Scene"), (1, "7", "Reshoot")])
        self.assertEqual(added[0].duration_seconds, 90)
        self.assertTrue(added[0].runtime_selected)
        self.assertFalse(added[1].runtime_selected, "original Day 1 scene 7 keeps the runtime take")
        reshoot_12a = M["ShootingDayScene"].query.filter_by(shooting_day_id=self.day1.id, scene_label="12A",
                                                            shooting_item_type="Reshoot").one()
        self.assertEqual(reshoot_12a.duration_seconds, 40)
        # Untouched rows: identical/ambiguous/legacy rows are never merged or rewritten.
        self.assertEqual(db.session.get(M["ShootingDayScene"], self.reshoot_a.id).duration_seconds, 60)
        self.assertEqual(M["SceneRow"].query.count(), 1)
        logs = M["ProjectActivityLog"].query.filter_by(project_id=self.project.id).all()
        types = [l.event_type for l in logs]
        self.assertEqual(types.count("shooting_day.import.completed"), 1)
        self.assertEqual(types.count("shooting_day.created"), 1)
        self.assertEqual(types.count("shooting_item.created"), 3)
        summary = next(l for l in logs if l.event_type == "shooting_day.import.completed")
        meta = json.loads(summary.metadata_json)
        self.assertEqual(meta["file"], "shoot.csv")
        self.assertEqual(meta["worksheets"], ["CSV"])
        self.assertEqual((meta["rows_added"], meta["rows_updated"], meta["days_created"]), (3, 2, 1))
        self.assertEqual(summary.user_id, self.admin[1].id)
        notes = M["Notification"].query.all()
        self.assertTrue(notes, "one summary notification for the project team")
        self.assertTrue(all("Production import" in (n.title or "") for n in notes))
        self.assertFalse(any("Shooting day created" in (n.title or "") for n in notes))
        # Imported day joins the material-registration queue without being registered or protected.
        status = app.extensions["material_registration"].service.status_for_day(day2.id)
        self.assertTrue(status["needs_registration"])
        self.assertEqual(db.session.query(app.extensions["material_registration"].Registration).count(), 0)
        sess = self.svc.get_session(token)
        self.assertEqual(sess.status, pis.STATUS_EXECUTED)
        self.assertFalse(os.path.exists(os.path.join(self.storage, sess.stored_name)), "source file removed")
        csv_res = self.client.get(f"{self._base()}/{token}/results.csv")
        self.assertEqual(csv_res.status_code, 200)
        self.assertIn("added", csv_res.get_data(as_text=True))

    def test_update_requires_explicit_fields_and_rejects_disallowed_actions(self):
        token, plan = self._prepare(self.STATUS_FILE)
        rows = self._by_row(plan)
        res = self._decide(token, {rows[3]["id"]: {"action": "update", "target_id": self.row_7.id, "fields": []}})
        self.assertIn("/preview", res.headers["Location"])
        res = self._decide(token, {rows[5]["id"]: {"action": "add"}})
        self.assertIn("/preview", res.headers["Location"])
        res = self._decide(token, {rows[4]["id"]: {"action": "update", "target_id": self.foreign_row.id, "fields": ["duration"]}})
        self.assertIn("/preview", res.headers["Location"])
        res = self._decide(token, {rows[10]["id"]: {"action": "add"}})
        self.assertIn("/preview", res.headers["Location"])

    def test_duplicate_confirm_and_reimport(self):
        token, plan = self._prepare(self.STATUS_FILE)
        rows = self._by_row(plan)
        self._decide(token, {rows[6]["id"]: {"action": "add"}})
        self.assertIn("/results", self._confirm(token).headers["Location"])
        after_first = self._counts()
        res = self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": "anything"})
        self.assertIn("/results", res.headers["Location"])
        self.assertEqual(self._counts(), after_first)
        _t2, plan2 = self._prepare(self.STATUS_FILE)
        rows2 = self._by_row(plan2)
        self.assertEqual(rows2[6]["status"], pim.STATUS_IDENTICAL)
        self.assertEqual(rows2[7]["status"], pim.STATUS_DUPLICATE)
        self.assertEqual({g["key"]: g["status"] for g in plan2["days"]}["u1|2"], pim.DAY_EXISTING)

    def test_changes_since_preview_require_review(self):
        token, plan = self._prepare(self.STATUS_FILE)
        rows = self._by_row(plan)
        self._decide(token, {
            rows[3]["id"]: {"action": "update", "target_id": self.row_7.id, "fields": ["duration"]},
            rows[6]["id"]: {"action": "add"},
        })
        r7 = db.session.get(self.M["ShootingDayScene"], self.row_7.id)
        r7.duration_seconds = 75
        db.session.commit()
        before = self._counts()
        res = self._confirm(token)
        self.assertIn("/preview", res.headers["Location"])
        self.assertEqual(self._counts(), before)
        sess = self.svc.get_session(token)
        db.session.refresh(sess)
        self.assertEqual(sess.status, pis.STATUS_PREVIEWED)
        decisions = json.loads(sess.decisions_json)
        self.assertEqual(decisions[rows[3]["id"]]["action"], "skip")
        self.assertEqual(decisions[rows[6]["id"]]["action"], "add")

    def test_failure_rolls_back_everything(self):
        token, plan = self._prepare(self.STATUS_FILE)
        rows = self._by_row(plan)
        self._decide(token, {
            rows[3]["id"]: {"action": "update", "target_id": self.row_7.id, "fields": ["sync_done"]},
            rows[6]["id"]: {"action": "add"},
            rows[9]["id"]: {"action": "add"},
        })
        before = self._counts()
        real_add = pis._add_row
        calls = {"n": 0}

        def flaky(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("disk full")
            return real_add(*a, **kw)

        with mock.patch.object(pis, "_add_row", side_effect=flaky):
            res = self._confirm(token)
        self.assertIn("/confirm", res.headers["Location"])
        db.session.expire_all()
        self.assertEqual(self._counts(), before)
        sess = self.svc.get_session(token)
        self.assertEqual(sess.status, pis.STATUS_PREVIEWED)
        self.assertIn("disk full", sess.last_error)
        res = self._confirm(token)
        self.assertIn("/results", res.headers["Location"])

    def test_permissions_and_ownership(self):
        token = self._upload(self.STATUS_FILE)
        self._login(self.other[0])
        self.assertEqual(self.client.get(f"{self._base()}/{token}/sheets").status_code, 404)
        self._login(self.admin[0])
        other_base = self._base(self.other_project.id)
        self.assertEqual(self.client.get(f"{other_base}/{token}/sheets").status_code, 404)
        self.assertEqual(self.client.get(f"{self._base()}?day_id={self.foreign_day.id}").status_code, 404)
        ga = app.extensions["guest_access"]
        with mock.patch.dict(ga, {"account_may_edit_production": lambda _a, _p: False}):
            res = self.client.get(self._base())
            self.assertIn(res.status_code, (302, 403))
            res = self.client.post(f"{self._base()}/{token}/cancel")
            self.assertIn(res.status_code, (302, 403))
        self.assertEqual(self.svc.get_session(token).status, pis.STATUS_UPLOADED)
        self.client.get("/logout")
        with self.client.session_transaction() as s:
            s.clear()
        res = self.client.get(f"{self._base()}/{token}/sheets")
        self.assertIn(res.status_code, (302, 401, 403))

    def test_record_ids_are_validated_against_project_and_day(self):
        data = _csv(
            f"Day 1,1,01/10/2026,1,7,Scene,1:00,,,,{self.row_7.id},",
            f"Day 1,1,01/10/2026,1,1,Scene,1:00,,,,{self.foreign_row.id},",
            f"Day 1,1,01/10/2026,1,9,Scene,1:00,,,,{self.row_12a.id},",
            "Day 1,1,01/10/2026,1,9,Scene,1:00,,,,999999,",
        )
        _token, plan = self._prepare(data)
        rows = self._by_row(plan)
        self.assertEqual(rows[2]["status"], pim.STATUS_IDENTICAL)
        self.assertEqual(rows[3]["status"], pim.STATUS_INVALID)
        self.assertIn("not a shooting row of this project", rows[3]["reason"])
        self.assertEqual(rows[4]["status"], pim.STATUS_CHANGED)
        self.assertTrue(any(d["identity"] and d["field"] == "scene_label" for d in rows[4]["diffs"]))
        self.assertEqual(rows[5]["status"], pim.STATUS_INVALID)
        _t, plan_day2 = self._prepare(_csv(f"D2,1,02/10/2026,1,12A,Scene,,,,,{self.row_12a.id},"))
        self.assertIn("belongs to", plan_day2["rows"][0]["reason"])

    def test_day_conflict_and_choice(self):
        token, plan = self._prepare(_csv("Day 1,1,05/10/2026,1,40,Scene,1:00,,,,,"))
        g = plan["days"][0]
        self.assertEqual(g["status"], pim.DAY_CONFLICT)
        self.assertEqual(plan["rows"][0]["status"], pim.STATUS_AMBIGUOUS)
        self.assertEqual(plan["rows"][0]["allowed_actions"], ["skip"])
        res = self.client.post(f"{self._base()}/{token}/preview",
                               data={"action": "days", f"day_choice__{g['key']}": f"existing:{self.day1.id}"})
        self.assertEqual(res.status_code, 302)
        plan = self._plan(token)
        self.assertEqual(plan["rows"][0]["status"], pim.STATUS_NEW)
        res = self.client.post(f"{self._base()}/{token}/preview",
                               data={"action": "days", f"day_choice__{g['key']}": "create",
                                     f"day_name__{g['key']}": "Day 1", f"day_date__{g['key']}": "2026-10-05"})
        plan = self._plan(token)
        self.assertIn("already has a day", plan["days"][0]["decision_error"])

    # -- export --

    def _export(self, fmt="xlsx", **params):
        q = "&".join(f"{k}={v}" for k, v in {"format": fmt, **params}.items())
        return self.client.get(f"/projects/{self.project.id}/production/days/export?{q}")

    def _reimport(self, data: bytes, name: str):
        token = self._upload(data, name=name)
        self.assertEqual(self._sheets(token).status_code, 302)
        sheet = self.svc.workbook(self.svc.get_session(token)).sheets[0]
        cols = pis.sheet_columns(sheet, 0)
        suggested = pin.suggest_mapping([c["header"] for c in cols], is_tv=True)
        mapping = {c["key"]: suggested.get(i, "") for i, c in enumerate(cols)}
        res = self._mapping(token, mapping)
        self.assertEqual(res.status_code, 302, res.data[:2000])
        return mapping, self._plan(token)

    def test_export_xlsx_lists_project_rows_and_round_trips_identical(self):
        self.row_7.notes = "=HYPERLINK(\"x\")"
        db.session.commit()
        res = self._export("xlsx")
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res.headers["Content-Disposition"])
        self.assertIn("Import Show - shooting days.xlsx", res.headers["Content-Disposition"])
        self.assertEqual(res.headers["Cache-Control"], "no-store")
        ws = openpyxl.load_workbook(io.BytesIO(res.data)).active
        rows = list(ws.iter_rows(values_only=True))
        self.assertEqual(rows[0][:6], ("BigBang record ID", "Unit", "Shooting day", "Shooting date", "Location", "Episode"))
        ids = [r[0] for r in rows[1:]]
        self.assertEqual(sorted(ids), sorted([self.row_12a.id, self.row_7.id, self.reshoot_a.id, self.reshoot_b.id]),
                         "own canonical rows only: no other project, no legacy rows")
        by_id = {r[0]: dict(zip(rows[0], r)) for r in rows[1:]}
        r12 = by_id[self.row_12a.id]
        self.assertEqual((r12["Shooting day"], r12["Episode"], r12["Scene / description"], r12["Duration"], r12["Notes"]),
                         ("Day 1", 1, "12A", "3:15", "old note"))
        self.assertEqual(r12["Shooting date"].date(), date(2026, 10, 1))
        self.assertEqual(ws.cell(row=ids.index(self.row_7.id) + 2, column=15).data_type, "s", "notes never become formulas")
        mapping, plan = self._reimport(res.data, "export.xlsx")
        self.assertIn("record_id", mapping.values())
        self.assertEqual({r["status"] for r in plan["rows"]}, {pim.STATUS_IDENTICAL}, [r["reason"] for r in plan["rows"]])

    def test_export_csv_guards_formulas_and_round_trips(self):
        self.row_7.notes = "=SUM(1)"
        db.session.commit()
        res = self._export("csv")
        self.assertEqual(res.status_code, 200)
        body = res.data.decode("utf-8-sig")
        self.assertIn("'=SUM(1)", body)
        self.assertTrue(body.startswith("BigBang record ID,Unit,Shooting day,Shooting date"))
        self.assertIn("2026-10-01", body)
        _mapping, plan = self._reimport(res.data, "export.csv")
        self.assertEqual({r["status"] for r in plan["rows"]}, {pim.STATUS_IDENTICAL}, [r["reason"] for r in plan["rows"]])

    def test_export_one_day_and_access_rules(self):
        SD = self.M["ShootingDay"]
        day2 = SD(project_id=self.project.id, unit_number=1, day_name="Day 2", shooting_date=date(2026, 10, 2))
        db.session.add(day2)
        db.session.commit()
        res = self._export("csv", day_id=day2.id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data.decode("utf-8-sig").strip().splitlines()), 1, "header only: Day 2 has no rows")
        self.assertIn("Unit 1 Day 2", res.headers["Content-Disposition"])
        self.assertEqual(self._export("csv", day_id=self.foreign_day.id).status_code, 404)
        self.assertEqual(self._export("pdf").status_code, 404)
        outsider = self._account("pim-outsider@test.local", "producer", "Outsider")
        self._login(outsider[0])
        self.assertIn(self._export("xlsx").status_code, (302, 403))

    def test_export_film_has_no_episode_column(self):
        self.project.project_type = "Feature Film"
        db.session.commit()
        ws = openpyxl.load_workbook(io.BytesIO(self._export("xlsx").data)).active
        headers = [c.value for c in ws[1]]
        self.assertNotIn("Episode", headers)
        self.assertIn("Scene / description", headers)

    def test_apply_to_all_days_then_adjust_one(self):
        days_before = self.M["ShootingDay"].query.filter_by(project_id=self.project.id).count()
        token, plan = self._prepare(_csv(
            "Day 5,1,,1,50,Scene,1:00,,,,,",
            "Day 6,1,,1,60,Scene,1:00,,,,,",
            "Day 7,1,,1,70,Scene,1:00,,,,,",
        ))
        keys = [g["key"] for g in plan["days"]]
        self.assertTrue(all(g["needs_decision"] for g in plan["days"]))
        res = self.client.post(f"{self._base()}/{token}/preview", data={
            "action": "days_all", "all_choice": "create", "all_start": "2026-10-01",
            "all_off": ["4"], "all_scope": "open"})
        self.assertEqual(res.status_code, 302)
        plan = self._plan(token)
        self.assertEqual([g["target"]["date"] for g in plan["days"]], ["2026-10-01", "2026-10-03", "2026-10-04"])
        self.assertEqual([g["target"]["day_name"] for g in plan["days"]], ["Day 5", "Day 6", "Day 7"])
        self.assertTrue(all(r["status"] == pim.STATUS_NEW for r in plan["rows"]))

        form = {"action": "days"}
        for k, d in zip(keys, ("2026-10-01", "2026-10-10", "2026-10-04")):
            form.update({f"day_choice__{k}": "create", f"day_name__{k}": "", f"day_date__{k}": d})
        self.client.post(f"{self._base()}/{token}/preview", data=form)
        plan = self._plan(token)
        self.assertEqual(plan["days"][1]["target"]["date"], "2026-10-10")

        res = self.client.post(f"{self._base()}/{token}/preview", data={
            "action": "days_all", "all_choice": "skip", "all_scope": "open"})
        self.assertEqual(self._plan(token)["days"][1]["target"]["date"], "2026-10-10")
        self.client.post(f"{self._base()}/{token}/preview", data={
            "action": "days_all", "all_choice": "skip", "all_scope": "all"})
        self.assertTrue(all(g.get("skipped") for g in self._plan(token)["days"]))
        self.assertEqual(self.M["ShootingDay"].query.filter_by(project_id=self.project.id).count(), days_before)

    def test_apply_to_all_days_needs_a_start_date(self):
        token, _plan = self._prepare(_csv("Day 5,1,,1,50,Scene,1:00,,,,,"))
        self.client.post(f"{self._base()}/{token}/preview", data={
            "action": "days_all", "all_choice": "create", "all_start": "", "all_scope": "open"})
        with self.client.session_transaction() as s:
            msgs = [m for _c, m in s.get("_flashes", [])]
        self.assertIn("Enter the date of the first shooting day.", msgs)
        self.assertTrue(self._plan(token)["days"][0]["needs_decision"])

    def test_fixed_day_import_ignores_day_columns(self):
        data = _csv("Day 9,3,09/10/2026,1,41,Scene,2:00,,,,,")
        token, plan = self._prepare(data, day_id=self.day1.id)
        self.assertEqual(plan["days"][0]["status"], pim.DAY_FIXED)
        self.assertEqual(plan["rows"][0]["status"], pim.STATUS_NEW)
        reasons = {c["header"]: c["reason"] for c in plan["ignored_columns"]}
        self.assertIn("fixed shooting day", reasons["Day"])
        self._decide(token, {plan["rows"][0]["id"]: {"action": "add"}})
        self._confirm(token)
        self.assertEqual(self.M["ShootingDay"].query.filter_by(project_id=self.project.id).count(), 1)
        self.assertEqual(self.M["ShootingDayScene"].query.filter_by(shooting_day_id=self.day1.id, scene_label="41").count(), 1)

    def test_day_per_worksheet_layout_uses_explicit_context(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Day 3"
        ws.append(["Scene", "Episode", "Duration"])
        ws.append(["50", 1, "2:00"])
        ws2 = wb.create_sheet("Notes")
        ws2.append(["Anything"])
        buf = io.BytesIO()
        wb.save(buf)
        token = self._upload(buf.getvalue(), name="days.xlsx")
        res = self._sheets(token, layout="day_sheets", sheets=["Day 3"], header_0="1", unit_0="", day_0="", date_0="")
        self.assertEqual(res.status_code, 302)
        res = self._mapping(token, {"scene": "scene_label", "episode": "episode", "duration": "duration"},
                            default__unit_number="")
        self.assertEqual(res.status_code, 200, "no day context and no day column: must ask")
        self.assertIn(b"shooting day", res.data)
        self._sheets(token, layout="day_sheets", sheets=["Day 3"], header_0="1", unit_0="2", day_0="7", date_0="2026-10-07")
        res = self._mapping(token, {"scene": "scene_label", "episode": "episode", "duration": "duration"})
        self.assertEqual(res.status_code, 302)
        plan = self._plan(token)
        self.assertEqual(plan["days"][0]["target"], {"kind": "new", "unit": 2, "day_name": "Day 7", "date": "2026-10-07", "location": ""})

    def test_mapping_requires_date_order_and_time_mode(self):
        token = self._upload(_csv("Day 1,1,03/04/2026,1,40,Scene,1:00,,,,,"))
        self._sheets(token)
        res = self._mapping(token, date_order="")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Choose the date order", res.data)
        res = self._mapping(token, date_order="mdy")
        self.assertEqual(res.status_code, 302)

    def test_presets_round_trip(self):
        token = self._upload(self.STATUS_FILE)
        self._sheets(token)
        data = {f"map__{k}": v for k, v in MAP.items()}
        data.update(action="save_preset", preset_name="Daily report", date_order="dmy", default__unit_number="1")
        self.assertEqual(self.client.post(f"{self._base()}/{token}/mapping", data=data).status_code, 302)
        preset = self.svc.Preset.query.filter_by(project_id=self.project.id).one()
        token2 = self._upload(self.STATUS_FILE)
        self._sheets(token2)
        res = self.client.post(f"{self._base()}/{token2}/mapping", data={"action": "apply_preset", "preset_id": preset.id})
        self.assertEqual(res.status_code, 302)
        opts = self.svc.options(self.svc.get_session(token2))
        self.assertEqual(opts["mapping"]["scene"], "scene_label")
        self.assertEqual(opts["parse"]["date_order"], "dmy")

    def test_film_project_has_no_episode_field(self):
        self.project.project_type = "Feature Film"
        db.session.commit()
        _token, plan = self._prepare(_csv("Day 1,1,01/10/2026,4,7,Scene,1:00,,,,,"))
        reasons = {c["header"]: c["reason"] for c in plan["ignored_columns"]}
        self.assertIn("films have no episodes", reasons["Episode"])
        self.assertEqual(plan["rows"][0]["status"], pim.STATUS_IDENTICAL)
        self.assertNotIn("Episode", plan["rows"][0]["identity"])

    def test_expired_sessions_are_purged(self):
        token = self._upload(self.STATUS_FILE)
        sess = self.svc.get_session(token)
        path = os.path.join(self.storage, sess.stored_name)
        self.assertTrue(os.path.exists(path))
        sess.expires_at = datetime.now() - timedelta(minutes=1)
        db.session.commit()
        res = self.client.get(f"{self._base()}/{token}/sheets")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.svc.get_session(token).status, pis.STATUS_EXPIRED)
        self.assertFalse(os.path.exists(path))

    def test_multi_sheet_picker_full_preview_and_combined_import(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Hadota Manseya"
        ws.append(["Day", "Unit", "Date", "EPS", "Scene", "Duration"])
        for n in range(1, 151):
            ws.append(["Day 1", 1, "2026-10-01", 1, str(100 + n), "1:00"])
        ws2 = wb.create_sheet("Day 2 sheet")
        ws2.append(["Day", "Unit", "Date", "EPS", "Scene", "Duration"])
        ws2.append(["Day 2", 1, "2026-10-02", 2, "5", "2:00"])
        buf = io.BytesIO()
        wb.save(buf)
        token = self._upload(buf.getvalue(), name="multi.xlsx")
        page = self.client.get(f"{self._base()}/{token}/sheets").get_data(as_text=True)
        self.assertIn("Choose worksheets", page)
        self.assertIn('data-autopen="1"', page)
        self.assertIn('data-pim-sheet-toggle="1"', page)
        self.assertIn("Showing 100 of 151 rows", page)
        self.assertIn("Show all 151 rows", page)
        rows = self.client.get(f"{self._base()}/{token}/sheets/rows?sheet=0&start=100").get_json()
        self.assertEqual((rows["start"], rows["total"], len(rows["rows"])), (100, 151, 51))
        self.assertEqual(rows["rows"][-1][4][1], "250")
        self._login(self.other[0])
        self.assertEqual(self.client.get(f"{self._base()}/{token}/sheets/rows?sheet=0").status_code, 404)
        self._login(self.admin[0])
        res = self.client.post(f"{self._base()}/{token}/sheets", data={
            "layout": "table", "sheets": ["Hadota Manseya", "Day 2 sheet"], "header_0": "1", "header_1": "1"})
        self.assertEqual(res.status_code, 302)
        mapping = {"day": "day_name", "unit": "unit_number", "date": "shooting_date", "eps": "episode",
                   "scene": "scene_label", "duration": "duration"}
        res = self._mapping(token, mapping)
        self.assertEqual(res.status_code, 302, res.data[:2000])
        plan = self._plan(token)
        self.assertEqual({r["sheet"] for r in plan["rows"]}, {"Hadota Manseya", "Day 2 sheet"})
        self.assertEqual(len(plan["rows"]), 151)
        page = self.client.get(f"{self._base()}/{token}/sheets").get_data(as_text=True)
        self.assertIn('data-autopen="0"', page, "the modal opens only until worksheets are chosen")

    def test_entry_points_render(self):
        page = self.client.get(f"/projects/{self.project.id}/production")
        self.assertIn(b"Import &amp; Compare", page.data)
        page = self.client.get(f"/projects/{self.project.id}/production/day/{self.day1.id}")
        self.assertIn(f"/production/days/import?day_id={self.day1.id}".encode(), page.data)
        token = self._upload(self.STATUS_FILE)
        for step in ("sheets", "mapping"):
            self.assertEqual(self.client.get(f"{self._base()}/{token}/{step}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
