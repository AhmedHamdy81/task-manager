"""Import & Compare preparation: Excel durations, fill-down, status tokens (synthetic fixtures)."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import date, datetime, time, timedelta

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_import_preparation.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

import openpyxl

from app import app, db
import google_sheets_client as gsc
import production_import_normalize as pin
import production_import_parsing as pip
import production_import_service as pis

C = pip.Cell
E = lambda: pip.Cell(None, "empty")  # noqa: E731
T = lambda v: pip.Cell(v, "text")  # noqa: E731
N = lambda v: pip.Cell(v, "number")  # noqa: E731


def _xlsx(build) -> bytes:
    wb = openpyxl.Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _reference_like(wb):
    """Small copy of the 7adota_Mansya layout: grouped Day/Location, merges, summaries, `o` tokens."""
    ws = wb.active
    ws.title = "Hadota Manseya"
    ws.append(["Location", "Day", "EPS", "Scene", "Sync", "1st-Edit", "Final-Edit", "Notes", "Duration", "Duration All"])
    ws.append([None] * 9 + [timedelta(seconds=1000)])
    rows = [
        ["Beet Omar 1", 1, 1, 13, "o", None, None, None, timedelta(seconds=170)],
        [None, None, 5, 11, "o", None, None, None, timedelta(seconds=180)],
        [None, None, 5, 23, None, None, None, None, timedelta(seconds=30)],
        [None, None, 5, 24, "o", "1", None, None, time(0, 0, 40)],
    ]
    for r in rows:
        ws.append(r)
    ws.append([None] * 9 + [timedelta(seconds=420)])  # summary row 7
    ws.append([None, 2, 1, 4, "o", "aya", None, None, timedelta(seconds=150)])  # new Day without Location
    ws.append([None, None, 1, 14, "o", None, None, None, "--"])
    ws.append([None, None, 2, "08A", "o", None, None, None, timedelta(hours=30, minutes=5)])
    for r in range(3, 7):
        ws.cell(r, 9).number_format = "[h]:mm:ss"
    ws.cell(6, 9).number_format = "h:mm:ss"
    ws.cell(8, 9).number_format = "[h]:mm:ss"
    ws.cell(10, 9).number_format = "[h]:mm:ss"
    ws.merge_cells("A3:A6")
    ws.merge_cells("B3:B6")
    ws.merge_cells("B8:B10")
    summary = wb.create_sheet("Duration_EPS")
    summary.append(["EPS", "Duration"])
    summary.append([1, timedelta(seconds=2741)])


class DurationTests(unittest.TestCase):
    def test_xlsx_formats_are_preserved_and_classified(self):
        def build(wb):
            ws = wb.active
            ws.append(["Duration"])
            ws.append([timedelta(seconds=170)])
            ws.append([time(0, 0, 40)])
            ws.append([timedelta(hours=30, minutes=5)])
            ws.append([1.25])
            ws.append(["0:03:00"])
            ws.append([90])
            ws.cell(2, 1).number_format = "[h]:mm:ss"
            ws.cell(3, 1).number_format = "h:mm:ss"
            ws.cell(4, 1).number_format = "[h]:mm:ss"
            ws.cell(5, 1).number_format = "[h]:mm:ss"

        book = pip.read_workbook(_xlsx(build), pip.XLSX)
        cells = [r[0] for r in book.sheets[0].rows[1:]]
        kinds = [pin.duration_cell_kind(c) for c in cells]
        self.assertEqual(kinds, ["elapsed", "time_of_day", "elapsed", "elapsed", "text", "number"])
        self.assertEqual(cells[0].fmt, "[h]:mm:ss")
        self.assertEqual(cells[1].fmt, "h:mm:ss")
        o = pin.ParseOptions()
        self.assertEqual(pin.parse_duration(cells[0], o).value, 170)
        self.assertEqual(pin.parse_duration(cells[1], o).state, pin.INVALID, "time of day needs a confirmed reading")
        self.assertEqual(pin.parse_duration(cells[1], pin.ParseOptions(excel_time_mode="hmm")).value, 40)
        self.assertEqual(pin.parse_duration(cells[2], o).value, 30 * 3600 + 300, "over 24 h is never wrapped")
        self.assertEqual(pin.parse_duration(cells[3], o).value, 30 * 3600)
        self.assertEqual(pin.parse_duration(cells[4], o).value, 180)
        self.assertEqual(pin.parse_duration(cells[0], pin.ParseOptions(excel_time_mode="mss")).value, 2,
                         "Shifted is only used when chosen explicitly")

    def test_expected_reference_examples(self):
        for secs, expected in ((170, 170), (180, 180), (30, 30), (40, 40)):
            self.assertEqual(pin.excel_time_seconds(C(timedelta(seconds=secs), "duration", fmt="[h]:mm:ss"), "hmm"), expected)

    def test_rounding_and_wrapped_excel_times(self):
        self.assertEqual(pin.round_half_up(169.5), 170)
        self.assertEqual(pin.round_half_up(169.4999), 169)
        self.assertEqual(pin.excel_time_seconds(C(timedelta(seconds=169.9999996), "duration"), "hmm"), 170)
        self.assertEqual(pin.excel_time_seconds(C(time(0, 2, 49, 600000), "time"), "hmm"), 170)
        wrapped = C(datetime(1900, 1, 1, 1, 0), "datetime", fmt="h:mm")
        self.assertEqual(pin.excel_time_seconds(wrapped, "hmm"), 25 * 3600, "serial value, not the wrapped clock time")
        self.assertEqual(pin.parse_duration(T("90.5"), pin.ParseOptions(duration_format="seconds")).value, 91)
        self.assertEqual(pin.parse_duration(T("2.5"), pin.ParseOptions(duration_format="minutes")).value, 150)
        self.assertEqual(pin.parse_field("duration", T("--"), pin.ParseOptions()).state, pin.EMPTY)

    def test_summary_columns_are_never_suggested(self):
        heads = ["Scene", "Duration", "Duration All", "Total duration", "إجمالي المدة"]
        self.assertEqual(pin.suggest_mapping(heads, is_tv=True), {0: "scene_label", 1: "duration"})
        self.assertEqual(pin.suggest_mapping(["Duration All", "Scene"], is_tv=True), {1: "scene_label"})

    def test_excel_dates_are_not_scene_labels(self):
        self.assertEqual(pin.parse_scene(C(datetime(2023, 8, 9), "datetime", fmt="m-d")).state, pin.INVALID)


class FillDownTests(unittest.TestCase):
    MAP = {0: "location", 1: "day_name", 2: "episode", 3: "scene_label", 4: "notes"}

    def build(self, rows, fill=("day_name", "location"), across=False, merges=None, stats=None):
        header = [T("Location"), T("Day"), T("EPS"), T("Scene"), T("Notes"), T("Total")]
        return {r.row_number: r for r in pin.build_source_rows(
            "S", [header] + rows, header_row=0, skip_after_header=0, mapping=self.MAP, defaults={},
            sheet_day_context={}, opts=pin.ParseOptions(is_tv=True, max_episode=50), fill_down=set(fill),
            location_across_days=across, merges=merges, stats=stats if stats is not None else {})}

    def test_rules(self):
        rows = [
            [E(), E(), N(1), N(1), E(), E()],                      # 2: leading blank — nothing above
            [T("Studio"), N(1), N(1), N(2), E(), E()],             # 3: group start
            [E(), E(), N(1), N(3), E(), E()],                      # 4: inherits
            [T("Garden"), E(), N(1), N(4), E(), E()],              # 5: explicit Location kept, Day inherited
            [E(), E(), N(1), N(5), E(), E()],                      # 6: inherits Garden
            [E(), E(), E(), E(), E(), N(500)],                     # 7: summary row → reset
            [E(), E(), N(2), N(6), E(), E()],                      # 8: nothing to inherit
            [E(), N(2), N(2), N(7), E(), E()],                     # 9: new Day, no Location
            [E(), E(), N(2), N(8), E(), E()],                      # 10: Day 2, Location NOT Garden
            [E(), E(), E(), E(), E(), E()],                        # 11: blank separator → reset
            [T("Location"), T("Day"), T("EPS"), T("Scene"), E(), E()],  # 12: repeated header → reset
            [E(), E(), N(3), N(9), E(), E()],                      # 13
        ]
        stats: dict = {}
        out = self.build(rows, stats=stats)
        self.assertEqual(out[2].get("day_name").state, pin.EMPTY)
        self.assertEqual(out[2].inherited, {})
        self.assertEqual((out[4].get("day_name").value, out[4].get("location").value), ("1", "Studio"))
        self.assertEqual(out[4].inherited["day_name"]["from"], "B3")
        self.assertEqual(out[4].inherited["location"]["how"], "fill")
        self.assertEqual(out[5].get("location").value, "Garden")
        self.assertNotIn("location", out[5].inherited)
        self.assertEqual(out[6].get("location").value, "Garden")
        self.assertEqual(out[8].get("day_name").state, pin.EMPTY, "summary row resets")
        self.assertEqual(out[10].get("day_name").value, "2")
        self.assertEqual(out[10].get("location").state, pin.EMPTY, "a new Day does not inherit the old Location")
        self.assertEqual(out[13].get("day_name").state, pin.EMPTY, "blank and repeated header rows reset")
        self.assertEqual(stats["header_repeats"], 1)
        self.assertGreaterEqual(stats["summary_rows"], 1)
        group = [
            [T("Garden"), N(1), N(1), N(1), E(), E()],
            [E(), N(2), N(1), N(2), E(), E()],
        ]
        self.assertEqual(self.build(group)[3].get("location").state, pin.EMPTY)
        across = self.build(group, across=True)
        self.assertEqual(across[3].get("location").value, "Garden", "only when explicitly enabled")

    def test_disabled_and_only_selected_fields(self):
        rows = [[T("Studio"), N(1), N(1), N(2), T("note"), E()], [E(), E(), E(), N(3), E(), E()]]
        off = self.build(rows, fill=())
        self.assertEqual(off[3].get("day_name").state, pin.EMPTY)
        self.assertEqual(off[3].get("episode").state, pin.EMPTY)
        day_only = self.build(rows, fill=("day_name",))
        self.assertEqual(day_only[3].get("day_name").value, "1")
        self.assertEqual(day_only[3].get("location").state, pin.EMPTY)
        self.assertEqual(day_only[3].get("episode").state, pin.EMPTY, "Episode is never filled")
        self.assertEqual(day_only[3].get("notes").state, pin.EMPTY)

    def test_merged_anchor_evidence_and_group_header_rows(self):
        rows = [
            [T("Studio"), N(1), N(1), N(2), E(), E()],     # 2 anchor of A2:A4
            [E(), E(), N(1), N(3), E(), E()],
            [E(), E(), N(1), N(4), E(), E()],
            [E(), N(2), E(), E(), E(), E()],               # 5: group header line (Day only)
            [T("Hall"), E(), N(2), N(5), E(), E()],
        ]
        merges = {(3, 1): (2, 1), (4, 1): (2, 1)}
        out = self.build(rows, merges=merges)
        self.assertEqual(out[3].inherited["location"], {"from": "A2", "how": "merged", "sheet": "S", "original": ""})
        self.assertNotIn(5, out, "a line with only a Day is a group header, not a scene row")
        self.assertEqual(out[6].get("day_name").value, "2")
        self.assertEqual(out[6].inherited["day_name"]["from"], "B5")

    def test_invalid_day_header_does_not_propagate(self):
        rows = [[T("Studio"), N(1), N(1), N(2), E(), E()], [E(), T("فركش"), E(), E(), E(), N(0)], [E(), E(), N(5), N(5), E(), E()]]
        out = self.build(rows)
        self.assertEqual(out[4].get("day_name").state, pin.EMPTY)


class TokenTests(unittest.TestCase):
    def test_field_scoped_meanings(self):
        o_yes = pin.ParseOptions.from_dict({"field_tokens": {"sync_done": {"o": "yes"}}}, is_tv=False, max_episode=1)
        self.assertEqual(pin.parse_field("sync_done", T("o"), o_yes).value, True)
        self.assertEqual(pin.parse_field("first_edit_done", T("o"), o_yes).state, pin.INVALID, "scoped to Sync only")
        o_no = pin.ParseOptions.from_dict({"field_tokens": {"sync_done": {"O": "no"}}}, is_tv=False, max_episode=1)
        no = pin.parse_field("sync_done", T("o"), o_no)
        self.assertEqual((no.state, no.value), (pin.VALUE, False))
        o_ign = pin.ParseOptions.from_dict({"field_tokens": {"sync_done": {"o": "ignore"}}}, is_tv=False, max_episode=1)
        self.assertEqual(pin.parse_field("sync_done", T("o"), o_ign).state, pin.EMPTY)
        default = pin.ParseOptions.from_dict({}, is_tv=False, max_episode=1)
        self.assertEqual(pin.parse_field("sync_done", T("o"), default).state, pin.INVALID, "o is never guessed")
        zero = pin.parse_field("sync_done", T("0"), default)
        self.assertEqual((zero.state, zero.value), (pin.VALUE, False), "explicit false is kept")


class SnapshotTests(unittest.TestCase):
    def test_formats_and_merges_round_trip_and_google_elapsed(self):
        sheet = pip.Sheet("S", [[C(timedelta(seconds=170), "duration", fmt="[h]:mm:ss")]], merges=[(1, 1, 3, 1)])
        _src, book = pip.decode_snapshot(pip.encode_snapshot({}, [sheet], []))
        self.assertEqual(book.sheets[0].rows[0][0].fmt, "[h]:mm:ss")
        self.assertEqual(book.sheets[0].merges, [(1, 1, 3, 1)])
        cell = gsc.to_cell({"effectiveValue": {"numberValue": 170 / 86400}, "formattedValue": "0:02:50",
                            "effectiveFormat": {"numberFormat": {"type": "TIME", "pattern": "[h]:mm:ss"}}})
        self.assertEqual((cell.kind, pin.excel_time_seconds(cell, "hmm")), ("duration", 170))
        tod = gsc.to_cell({"effectiveValue": {"numberValue": 40 / 86400}, "formattedValue": "0:00:40",
                           "effectiveFormat": {"numberFormat": {"type": "TIME", "pattern": "h:mm:ss"}}})
        self.assertEqual(tod.kind, "time")


class PreparationFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = tempfile.mkdtemp(prefix="tm_prep_")
        app.config["PRODUCTION_IMPORT_STORAGE_DIR"] = cls.storage
        with app.app_context():
            assert not str(db.engine.url).endswith("instance/app.db"), db.engine.url
            db.create_all()
            import machine_room_dashboard_support as mr_dash
            import machine_room_media_workflow_support as wf
            import material_registration_support as regs
            import google_sheets_service as gss

            now = datetime.utcnow
            mr_dash.ensure_machine_room_dashboard_tables(db, now)
            wf.ensure_machine_room_media_workflow_tables(db, now)
            regs.ensure_material_registration_table(db, now)
            pis.ensure_tables(db, now)
            gss.ensure_tables(db, now)

    @classmethod
    def tearDownClass(cls):
        app.config.pop("PRODUCTION_IMPORT_STORAGE_DIR", None)
        shutil.rmtree(cls.storage, ignore_errors=True)

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.svc = app.extensions["production_import"].service
        self.M = {**app.extensions["tm_test_models"], **self.svc.M}
        self._wipe()
        M = self.M
        self.acc = M["Account"](email="prep@test.local", password_hash="x", role="admin")
        db.session.add(self.acc)
        db.session.flush()
        db.session.add(M["User"](name="Prep", email="prep@test.local", account_id=self.acc.id))
        self.project = M["Project"](name="Prep Show", project_type="TV Series", number_of_episodes=40,
                                    production_house="T", director="T")
        db.session.add(self.project)
        db.session.flush()
        self.day = M["ShootingDay"](project_id=self.project.id, unit_number=1, day_name="Day 1",
                                    shooting_date=date(2026, 10, 1))
        db.session.add(self.day)
        db.session.commit()
        with self.client.session_transaction() as s:
            s["account_id"] = self.acc.id

    def tearDown(self):
        db.session.rollback()
        self._wipe()
        db.session.remove()
        self.ctx.pop()

    def _wipe(self):
        M = self.M
        for model in (self.svc.Session, self.svc.Preset, M["ProjectActivityLog"], M["Notification"],
                      M["ShootingDayScene"], M["ShootingDay"], M["Project"], M["User"], M["Account"]):
            db.session.query(model).delete()
        db.session.commit()

    def _base(self):
        return f"/projects/{self.project.id}/production/days/import"

    def _upload(self, data, name="ref.xlsx", day_id=None):
        url = self._base() + (f"?day_id={day_id}" if day_id else "")
        res = self.client.post(url, data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")
        return re.search(r"/import/([^/]+)/sheets", res.headers["Location"]).group(1)

    def _sheets(self, token, sheets=("Hadota Manseya",)):
        return self.client.post(f"{self._base()}/{token}/sheets",
                                data={"layout": "table", "sheets": list(sheets), "header_0": "1", "header_1": "1"})

    MAP = {"location": "location", "day": "day_name", "eps": "episode", "scene": "scene_label", "sync": "sync_done",
           "1st edit": "first_edit_done", "final edit": "", "notes": "notes", "duration": "duration", "duration all": ""}

    def _mapping(self, token, mapping=None, **extra):
        data = {f"map__{k}": v for k, v in (mapping or self.MAP).items()}
        data.update(action="continue", duration_format="auto", default__unit_number="1")
        data.update(extra)
        return self.client.post(f"{self._base()}/{token}/mapping", data=data)

    def _resolved(self, **over):
        data = {"excel_time_mode": "hmm", "tokname__sync_done__0": "o", "tok__sync_done__0": "yes",
                "tokname__first_edit_done__0": "aya", "tok__first_edit_done__0": "ignore",
                "fill_seen__0": "1", "fill_mode__0": "fill", "fill__0": ["day_name", "location"]}
        data.update(over)
        return data

    def _counts(self):
        M = self.M
        return (M["ShootingDay"].query.count(), M["ShootingDayScene"].query.count(),
                M["ProjectActivityLog"].query.count(), M["Notification"].query.count())

    def test_reference_like_workbook_needs_explicit_preparation(self):
        before = self._counts()
        token = self._upload(_xlsx(_reference_like))
        self.assertEqual(self.svc.options(self.svc.get_session(token))["sheets"], ["Hadota Manseya"],
                         "the summary worksheet is not selected automatically")
        self._sheets(token)
        page = self.client.get(f"{self._base()}/{token}/mapping").get_data(as_text=True)
        block = re.search(r'name="map__duration all".*?</select>', page, re.S).group(0)
        self.assertNotIn("selected", block, "Duration All stays unmapped by default")
        res = self._mapping(token)
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("time-of-day values", body)
        self.assertIn("Define these status values", body)
        self.assertIn("“o” (6)", body)
        self.assertIn("“aya” (1)", body)
        self.assertIn("Choose under “Fill down”", body)
        self.assertIn("Recommended", body)
        self.assertIn("I3", body)
        self.assertIn("170 s · 2:50", body)
        self.assertIn("30:05:00", body)
        res = self._mapping(token, **self._resolved())
        self.assertEqual(res.status_code, 302, res.get_data(as_text=True)[:3000])
        self.assertEqual(self.client.get(f"{self._base()}/{token}/preview").status_code, 200)
        sess = self.svc.get_session(token)
        db.session.refresh(sess)
        plan = json.loads(sess.plan_json)
        rows = {r["row_number"]: r for r in plan["rows"]}
        self.assertEqual(rows[4]["inherited"]["day_name"]["from"], "B3")
        self.assertEqual(rows[4]["inherited"]["day_name"]["how"], "merged")
        self.assertEqual(rows[4]["values"]["location"], "Beet Omar 1")
        self.assertNotIn("location", rows[9]["values"], "Day 2 does not inherit Beet Omar 1")
        self.assertEqual(rows[9]["inherited"]["day_name"]["from"], "B8")
        self.assertEqual(rows[3]["values"]["duration"], "0:02:50")
        self.assertNotIn("duration", rows[9]["values"], "-- is no information")
        self.assertEqual(rows[5]["status"], "new")
        self.assertNotIn("sync_done", rows[5]["values"])
        self.assertNotIn("first_edit_done", rows[8]["values"], "“aya” = Ignore → no information, nothing cleared")
        self.assertEqual(rows[6]["values"]["first_edit_done"], "1")
        self.assertEqual(plan["preparation"]["field_tokens"]["sync_done"], {"o": "yes"})
        self.assertEqual(self._counts(), before, "preparation and preview never mutate production data")

    def test_series_without_episode_count_is_reported_once(self):
        self.project.number_of_episodes = 0
        db.session.commit()
        token = self._upload(_xlsx(_reference_like))
        self._sheets(token)
        res = self._mapping(token, **self._resolved())
        self.assertIn("no number of episodes set", res.get_data(as_text=True))

    def test_fill_down_needs_an_explicit_choice(self):
        token = self._upload(_xlsx(_reference_like))
        self._sheets(token)
        res = self._mapping(token, **self._resolved(fill_mode__0="", fill__0=[]))
        self.assertIn("Choose under “Fill down”", res.get_data(as_text=True), "unticked boxes are not a decision")
        res = self._mapping(token, **self._resolved(fill_mode__0="fill", fill__0=[]))
        self.assertIn("tick the columns to fill down", res.get_data(as_text=True))
        res = self._mapping(token, **self._resolved(fill_mode__0="off", fill__0=[]))
        self.assertEqual(res.status_code, 302)
        self.client.get(f"{self._base()}/{token}/preview")
        rows = {r["row_number"]: r for r in json.loads(self.svc.get_session(token).plan_json)["rows"]}
        self.assertEqual(rows[4]["inherited"], {}, "fill-down disabled: nothing inherited")
        self.assertNotIn("day_name", rows[4]["values"])
        self.assertEqual(rows[4]["status"], "invalid")
        self.assertIn("turn on Fill down for Shooting day", rows[4]["reason"])

    def test_conflicting_and_field_scoped_tokens(self):
        token = self._upload(_xlsx(_reference_like))
        self._sheets(token)
        res = self._mapping(token, **self._resolved(**{"tokname__sync_done__1": "O", "tok__sync_done__1": "no"}))
        self.assertEqual(res.status_code, 200)
        self.assertIn("two different meanings", res.get_data(as_text=True))
        res = self._mapping(token, **self._resolved(**{"tok__first_edit_done__0": ""}))
        self.assertEqual(res.status_code, 200, "defining o for Sync does not define aya for First Edit")
        self.assertIn("First Edit: “aya”", res.get_data(as_text=True))
        mapping = dict(self.MAP, **{"1st edit": ""})
        res = self._mapping(token, mapping, **{k: v for k, v in self._resolved().items() if "first_edit" not in k})
        self.assertEqual(res.status_code, 302, "removing the column mapping instead of defining its tokens is allowed")

    def test_changes_rebuild_plan_and_reset_dependent_decisions(self):
        token = self._upload(_xlsx(_reference_like))
        self._sheets(token)
        self._mapping(token, **self._resolved())
        self.client.get(f"{self._base()}/{token}/preview")
        sess = self.svc.get_session(token)
        db.session.refresh(sess)
        plan = json.loads(sess.plan_json)
        rows = {r["row_number"]: r for r in plan["rows"]}
        dec = {rows[3]["id"]: {"action": "skip"}, rows[5]["id"]: {"action": "skip"}}
        self.client.post(f"{self._base()}/{token}/preview",
                         data={"action": "decisions", "plan_hash": sess.plan_hash, "decisions": json.dumps(dec)})
        old_hash = sess.plan_hash
        res = self._mapping(token, **self._resolved(**{"tok__sync_done__0": "no"}))
        self.assertEqual(res.status_code, 302)
        sess = self.svc.get_session(token)
        db.session.refresh(sess)
        self.assertEqual(sess.status, pis.STATUS_UPLOADED)
        self.assertEqual(self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": old_hash}).status_code, 302)
        self.client.get(f"{self._base()}/{token}/preview")
        db.session.refresh(sess)
        self.assertNotEqual(sess.plan_hash, old_hash)
        decisions = json.loads(sess.decisions_json)
        self.assertEqual(decisions[rows[3]["id"]]["action"], "add", "row 3 has Sync o → changed → back to default")
        self.assertEqual(decisions[rows[5]["id"]]["action"], "skip", "row 5 has no Sync value → choice kept")

    def test_preset_round_trip_and_interpretation_message(self):
        token = self._upload(_xlsx(_reference_like))
        self._sheets(token)
        data = {f"map__{k}": v for k, v in self.MAP.items()}
        data.update(self._resolved(), action="save_preset", preset_name="Hadota daily", default__unit_number="1")
        self.assertEqual(self.client.post(f"{self._base()}/{token}/mapping", data=data).status_code, 302)
        preset = self.svc.Preset.query.one()
        token2 = self._upload(_xlsx(_reference_like))
        self._sheets(token2)
        res = self.client.post(f"{self._base()}/{token2}/mapping", data={"action": "apply_preset", "preset_id": preset.id})
        opts = self.svc.options(self.svc.get_session(token2))
        self.assertEqual(opts["parse"]["excel_time_mode"], "hmm")
        self.assertEqual(opts["parse"]["field_tokens"], {"sync_done": {"o": "yes"}, "first_edit_done": {"aya": "ignore"}})
        self.assertEqual(opts["sheet_settings"]["Hadota Manseya"]["fill_down"], ["day_name", "location"])
        with self.client.session_transaction() as s:
            flashed = " ".join(m for _c, m in s.get("_flashes", []))
        self.assertIn("Excel times: As shown in Excel", flashed)
        self.assertIn("Sync: “o” = yes", flashed)
        self.assertIn("fill-down: Location, Shooting day", flashed)
        page = self.client.get(res.headers["Location"]).get_data(as_text=True)
        self.assertIn('value="hmm" checked', page)
        res = self.client.post(f"{self._base()}/{token2}/mapping", data={
            **{f"map__{k}": v for k, v in self.MAP.items()}, "action": "continue", "default__unit_number": "1",
            "excel_time_mode": "hmm", "fill_seen__0": "1", "fill_mode__0": "fill", "fill__0": ["day_name", "location"]})
        self.assertEqual(res.status_code, 302, "preset definitions satisfy the confirmations")

    def test_fixed_day_import_keeps_target_day(self):
        token = self._upload(_xlsx(_reference_like), day_id=self.day.id)
        self._sheets(token)
        page = self.client.get(f"{self._base()}/{token}/mapping").get_data(as_text=True)
        self.assertNotIn("Fill down", page.split("Preparation summary")[0].split("How values are read")[1])
        res = self._mapping(token, **{k: v for k, v in self._resolved().items() if not k.startswith("fill")})
        self.assertEqual(res.status_code, 302, res.get_data(as_text=True)[:2000])
        self.client.get(f"{self._base()}/{token}/preview")
        plan = json.loads(self.svc.get_session(token).plan_json)
        self.assertEqual([g["status"] for g in plan["days"]], ["fixed"])
        self.assertTrue(all(not r.get("inherited") for r in plan["rows"]))

    def test_csv_fill_down_and_tokens_work_the_same(self):
        csv = ("\ufeffLocation,Day,EPS,Scene,Sync,Duration\n"
               "Studio,1,1,10,o,1:00\n,,1,11,o,1:30\n,,,,,\n,2,1,12,,2:00\n").encode()
        token = self._upload(csv, name="log.csv")
        self.client.post(f"{self._base()}/{token}/sheets", data={"layout": "table", "sheets": ["CSV"], "header_0": "1",
                                                                  "csv_encoding": "utf-8-sig", "csv_delimiter": ","})
        mapping = {"location": "location", "day": "day_name", "eps": "episode", "scene": "scene_label",
                   "sync": "sync_done", "duration": "duration"}
        res = self._mapping(token, mapping)
        self.assertIn("Choose under “Fill down”", res.get_data(as_text=True))
        res = self._mapping(token, mapping, **{"tokname__sync_done__0": "o", "tok__sync_done__0": "yes",
                                               "fill_seen__0": "1", "fill_mode__0": "fill", "fill__0": ["day_name", "location"]})
        self.assertEqual(res.status_code, 302, res.get_data(as_text=True)[:2000])
        self.client.get(f"{self._base()}/{token}/preview")
        rows = {r["row_number"]: r for r in json.loads(self.svc.get_session(token).plan_json)["rows"]}
        self.assertEqual(rows[3]["inherited"]["day_name"], {"from": "B2", "how": "fill", "sheet": "CSV", "original": ""})
        self.assertNotIn("location", rows[5]["values"])


if __name__ == "__main__":
    unittest.main()
