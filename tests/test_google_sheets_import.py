"""Google Sheets source for Import & Compare (all Google traffic is faked)."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from unittest import mock
from urllib.parse import parse_qs, urlsplit

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_google_sheets_import.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db
import google_sheets_client as gsc
import google_sheets_service as gss
import production_import_matching as pim
import production_import_normalize as pin
import production_import_parsing as pip
import production_import_service as pis

SID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abc"
URL = f"https://docs.google.com/spreadsheets/d/{SID}/edit#gid=222"


def S(v):
    return {"effectiveValue": {"stringValue": v}, "formattedValue": v}


def N(v, fmt="NUMBER", shown=None):
    return {"effectiveValue": {"numberValue": v}, "formattedValue": shown if shown is not None else str(v),
            "effectiveFormat": {"numberFormat": {"type": fmt}}}


def B(v):
    return {"effectiveValue": {"boolValue": v}, "formattedValue": "TRUE" if v else "FALSE"}


def ERR(text="#REF!"):
    return {"effectiveValue": {"errorValue": {"type": "REF", "message": "x"}}, "formattedValue": text}


class FakeGoogle:
    """In-memory Google: OAuth token/userinfo/revoke + read-only Sheets API."""

    def __init__(self):
        self.requests: list[tuple[str, str, Any]] = []
        self.sheets: dict[str, dict] = {}
        self.fail: dict[str, Any] = {}
        self.scope = f"openid email {gsc.SHEETS_SCOPE}"
        self.refresh_ok = True
        self.issued = 0
        self.revoked: list[str] = []

    def __call__(self, method, url, *, params=None, data=None, headers=None, max_bytes=gsc.MAX_RESPONSE_BYTES):
        self.requests.append((method, url, params or data))
        host = urlsplit(url).hostname
        assert host in ("oauth2.googleapis.com", "sheets.googleapis.com", "openidconnect.googleapis.com"), url
        if url == gsc.TOKEN_URL:
            if data["grant_type"] == "authorization_code":
                assert data.get("code_verifier"), "PKCE verifier must be sent"
                if data["code"] == "bad":
                    return gsc.HttpResult(400, {"error": "invalid_grant"})
                self.issued += 1
                return gsc.HttpResult(200, {"access_token": f"AT-{self.issued}", "refresh_token": "RT-secret",
                                            "expires_in": 3600, "scope": self.scope})
            if not self.refresh_ok:
                return gsc.HttpResult(400, {"error": "invalid_grant"})
            self.issued += 1
            return gsc.HttpResult(200, {"access_token": f"AT-{self.issued}", "expires_in": 3600, "scope": self.scope})
        if url == gsc.REVOKE_URL:
            self.revoked.append(data["token"])
            return gsc.HttpResult(200, {})
        if url == gsc.USERINFO_URL:
            return gsc.HttpResult(200, {"sub": "g-123", "email": "Editor@Example.com"})
        assert method == "GET", "Sheets must only be read"
        failure = self.fail.get("sheets")
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        sid = url.rsplit("/", 1)[1]
        book = self.sheets.get(sid)
        if book is None:
            return gsc.HttpResult(404, {"error": {"code": 404, "status": "NOT_FOUND", "message": "nope"}})
        p = dict(params or [])
        if "includeGridData" not in p:
            return gsc.HttpResult(200, {
                "spreadsheetId": sid,
                "properties": {"title": book["title"], "locale": "ar_EG", "timeZone": "Africa/Cairo"},
                "sheets": [{"properties": {"sheetId": s["id"], "title": s["title"], "index": i, "sheetType": "GRID",
                                           "gridProperties": {"rowCount": s.get("rowCount", max(len(s["rows"]), 1)),
                                                              "columnCount": s.get("colCount", 26)}}}
                           for i, s in enumerate(book["sheets"])],
            })
        out = []
        for rng in [v for k, v in (params or []) if k == "ranges"]:
            m = re.fullmatch(r"'(.*)'!A1:([A-Z]+)(\d+)", rng)
            title = m.group(1).replace("''", "'")
            last_row = int(m.group(3))
            s = next(x for x in book["sheets"] if x["title"] == title)
            out.append({"properties": {"sheetId": s["id"], "title": title},
                        "data": [{"rowData": [{"values": r} for r in s["rows"][:last_row]]}]})
        return gsc.HttpResult(200, {"sheets": out})


from typing import Any  # noqa: E402


class LinkAndCellTests(unittest.TestCase):
    def test_accepts_only_google_sheets_links(self):
        ok = [
            (URL, 222),
            (f"https://docs.google.com/spreadsheets/d/{SID}", None),
            (f"https://docs.google.com/spreadsheets/d/{SID}/", None),
            (f"https://docs.google.com/spreadsheets/u/1/d/{SID}/edit?usp=sharing", None),
            (f"https://docs.google.com/spreadsheets/d/{SID}/view?gid=7", 7),
            (f"https://docs.google.com/spreadsheets/d/{SID}/edit?gid=7#gid=9", 9),
        ]
        for raw, gid in ok:
            link = gsc.parse_sheets_link(raw)
            self.assertEqual((link.spreadsheet_id, link.gid), (SID, gid), raw)
        bad = {
            f"http://docs.google.com/spreadsheets/d/{SID}/edit": "invalid_link",
            f"https://docs.google.com.evil.test/spreadsheets/d/{SID}/edit": "invalid_link",
            f"https://evil.test/?u=https://docs.google.com/spreadsheets/d/{SID}": "invalid_link",
            f"https://user@docs.google.com/spreadsheets/d/{SID}/edit": "invalid_link",
            f"https://docs.google.com:8443/spreadsheets/d/{SID}/edit": "invalid_link",
            f"https://drive.google.com/file/d/{SID}/view": "unsupported_document",
            f"https://docs.google.com/document/d/{SID}/edit": "unsupported_document",
            "https://docs.google.com/spreadsheets/d/e/2PACX-1vQabcdefghijklmnopqrstuvwxyz/pubhtml": "unsupported_document",
            f"https://docs.google.com/spreadsheets/d/{SID}/edit#gid=abc": "invalid_link",
            f"https://docs.google.com/spreadsheets/d/{SID}/../../admin": "invalid_link",
            "https://docs.google.com/spreadsheets/d/short/edit": "invalid_link",
            "http://169.254.169.254/latest/meta-data/": "invalid_link",
            "file:///etc/passwd": "invalid_link",
            "javascript:alert(1)": "invalid_link",
            "": "invalid_link",
            f"https://docs.google.com/spreadsheets/d/{SID}/edit x": "invalid_link",
        }
        for raw, code in bad.items():
            with self.assertRaises(gsc.GoogleSheetsError, msg=raw) as cm:
                gsc.parse_sheets_link(raw)
            self.assertEqual(cm.exception.code, code, raw)

    def test_transport_refuses_other_hosts(self):
        with self.assertRaises(gsc.GoogleSheetsError):
            gsc.default_transport("GET", "http://169.254.169.254/")
        with self.assertRaises(gsc.GoogleSheetsError):
            gsc.default_transport("GET", "https://docs.google.com/spreadsheets/d/x")

    def test_authorize_url_is_read_only_with_pkce(self):
        verifier, challenge = gsc.new_pkce()
        url = gsc.authorize_url(client_id="cid", redirect_uri="https://bb.test/cb", state="st", code_challenge=challenge)
        q = parse_qs(urlsplit(url).query)
        self.assertEqual(q["scope"][0].split(), ["openid", "email", gsc.SHEETS_SCOPE])
        self.assertNotIn("drive", q["scope"][0])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["access_type"], ["offline"])
        self.assertEqual(q["include_granted_scopes"], ["true"])
        self.assertNotIn(verifier, url)

    def test_cells_keep_types_identifiers_and_errors(self):
        c = gsc.to_cell
        self.assertEqual((c(S("001")).kind, c(S("001")).value), ("text", "001"))
        num = c(N(1, shown="001"))
        self.assertEqual((num.kind, num.value, num.display), ("number", 1, "001"))
        self.assertEqual(pin.parse_scene(num).value, "001")
        self.assertEqual(pin.parse_scene(c(S("12A"))).value, "12A")
        self.assertEqual(c(B(True)).kind, "bool")
        self.assertEqual(c(N(46296, "DATE", "01/10/2026")).value, date(2026, 10, 1))
        self.assertEqual(c(N(46296.5, "DATE_TIME")).value, datetime(2026, 10, 1, 12, 0))
        tod = c(N(3.25 / 24, "TIME", "03:15"))
        self.assertEqual((tod.kind, tod.value), ("time", time(3, 15)))
        self.assertEqual(c(N(1.5, "TIME", "36:00:00")).kind, "duration")
        err = c(ERR())
        self.assertEqual((err.kind, err.display), ("error", "#REF!"))
        self.assertEqual(pin.parse_field("notes", err, pin.ParseOptions()).state, pin.INVALID)
        self.assertEqual(c({}).kind, "empty")
        self.assertEqual(c(S("   ")).kind, "empty")

    def test_snapshot_round_trip_and_hash(self):
        sheet = pip.Sheet("Day 1", [[gsc.to_cell(S("Scene")), gsc.to_cell(N(1, shown="001"))],
                                    [gsc.to_cell(N(46296, "DATE")), gsc.to_cell(N(1.5, "TIME"))]])
        data = pip.encode_snapshot({"type": "google_sheets"}, [sheet], ["w"])
        source, book = pip.decode_snapshot(data)
        self.assertEqual(source["type"], "google_sheets")
        back = book.sheets[0]
        self.assertEqual(back.rows[0][1].display, "001")
        self.assertEqual(back.rows[1][0].value, date(2026, 10, 1))
        self.assertEqual(back.rows[1][1].value, timedelta(days=1.5))
        self.assertEqual(pip.sheet_content_hash(back), pip.sheet_content_hash(sheet))
        self.assertEqual(pip.encode_snapshot({"type": "google_sheets"}, [sheet], ["w"]), data)
        with self.assertRaises(pip.ImportFileError):
            pip.decode_snapshot(b"not gzip")


class GoogleFlowBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = tempfile.mkdtemp(prefix="tm_gsi_")
        app.config["PRODUCTION_IMPORT_STORAGE_DIR"] = cls.storage
        with app.app_context():
            assert not str(db.engine.url).endswith("instance/app.db"), db.engine.url
            db.create_all()
            import machine_room_dashboard_support as mr_dash
            import machine_room_media_workflow_support as wf
            import material_registration_support as regs

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
        self.imp = app.extensions["production_import"].service
        self.gs = app.extensions["google_sheets"].service
        self.M = {**app.extensions["tm_test_models"], **self.imp.M}
        self.fake = FakeGoogle()
        self._orig = (self.gs.http, self.gs.client_config)
        self.gs.http = self.fake
        self.gs.client_config = lambda: ("client-id.apps.googleusercontent.com", "client-secret")
        self._wipe()
        M = self.M
        self.acc, self.user = self._account("gs-a@test.local", "admin", "Alice")
        self.other, _ = self._account("gs-b@test.local", "admin", "Bob")
        self.member, self.member_user = self._account("gs-m@test.local", "producer", "Member")
        self.project = M["Project"](name="GS Show", project_type="TV Series", number_of_episodes=10,
                                    production_house="T", director="T")
        db.session.add(self.project)
        db.session.flush()
        db.session.add(M["ProjectMember"](project_id=self.project.id, user_id=self.member_user.id))
        self.day1 = M["ShootingDay"](project_id=self.project.id, unit_number=1, day_name="Day 1",
                                     shooting_date=date(2026, 10, 1))
        db.session.add(self.day1)
        db.session.flush()
        SDS = M["ShootingDayScene"]
        self.row7 = SDS(shooting_day_id=self.day1.id, scene_id=1, episode_number=1, scene_label="7",
                        shooting_item_type="Scene", duration_seconds=60, duration=1, actual_duration_minutes=1,
                        runtime_selected=True)
        db.session.add(self.row7)
        db.session.commit()
        self.fake.sheets[SID] = {"title": "Shoot log", "sheets": [
            {"id": 0, "title": "Notes", "rows": [[S("anything")]]},
            {"id": 222, "title": "Log", "rows": self._log_rows()},
        ]}
        self._login(self.acc)

    def tearDown(self):
        self.gs.http, self.gs.client_config = self._orig
        db.session.rollback()
        self._wipe()
        db.session.remove()
        self.ctx.pop()

    def _wipe(self):
        M = self.M
        for model in (self.imp.Session, self.imp.Preset, self.gs.OAuthState, self.gs.Connection,
                      M["ProjectActivityLog"], M["Notification"], M["SceneRow"], M["ShootingDayScene"],
                      M["ShootingDay"], M["ProjectMember"], M["Project"], M["User"], M["Account"]):
            db.session.query(model).delete()
        reg = app.extensions.get("material_registration")
        if reg is not None:
            db.session.query(reg.Registration).delete()
        db.session.commit()

    def _account(self, email, role, name):
        acc = self.M["Account"](email=email, password_hash="pbkdf2:sha256:1$x$y", role=role)
        db.session.add(acc)
        db.session.flush()
        user = self.M["User"](name=name, email=email, account_id=acc.id)
        db.session.add(user)
        db.session.flush()
        return acc, user

    def _login(self, acc, client=None):
        with (client or self.client).session_transaction() as s:
            s["account_id"] = acc.id

    @staticmethod
    def _log_rows():
        return [
            [S("Shooting log")],
            [],
            [S("اليوم"), S("الوحدة"), S("التاريخ"), S("الحلقة"), S("المشهد"), S("النوع"), S("المدة"), S("سينك"), S("Camera")],
            [S("Day 1"), N(1), N(46296, "DATE", "01/10/2026"), N(1), S("7"), S("Scene"), S("2:00"), B(True), S("A")],
            [S("يوم ٢"), N(1), N(46297, "DATE", "02/10/2026"), N(2), N(1, shown="001"), S("Scene"), S("1:30"), {}, S("A")],
            [S("Day 1"), N(1), N(46296, "DATE"), N(1), S("12A"), S("Reshoot"), S("0:40"), B(False), S("B")],
            [S("Day 1"), N(1), N(46296, "DATE"), N(1), S("99"), S("Scene"), ERR(), {}, S("A")],
        ]

    # -- helpers --

    def _connect(self):
        res = self.client.get(f"/integrations/google-sheets/connect?project_id={self.project.id}")
        self.assertEqual(res.status_code, 302)
        q = parse_qs(urlsplit(res.headers["Location"]).query)
        res = self.client.get(f"/integrations/google-sheets/callback?state={q['state'][0]}&code=good")
        self.assertEqual(res.status_code, 302, res.data[:300])
        return res

    def _base(self):
        return f"/projects/{self.project.id}/production/days/import"

    def _start_import(self, link=URL, day_id=None):
        data = {"link": link}
        if day_id:
            data["day_id"] = day_id
        res = self.client.post(f"{self._base()}/google", data=data)
        m = re.search(r"/import/([^/]+)/sheets", res.headers.get("Location", ""))
        return res, (m.group(1) if m else None)

    def _to_preview(self, token, mapping=None):
        sess = self.imp.get_session(token)
        opts = self.imp.options(sess)
        res = self.client.post(f"{self._base()}/{token}/sheets",
                               data={"layout": "table", "sheets": opts["sheets"], "header_0": "3", "header_1": "3"})
        self.assertEqual(res.status_code, 302, res.data[:500])
        m = mapping or {"اليوم": "day_name", "الوحده": "unit_number", "التاريخ": "shooting_date", "الحلقه": "episode",
                        "المشهد": "scene_label", "النوع": "item_type", "المده": "duration", "سينك": "sync_done", "camera": ""}
        data = {f"map__{k}": v for k, v in m.items()}
        data.update(action="continue", default__unit_number="1", duration_format="auto")
        res = self.client.post(f"{self._base()}/{token}/mapping", data=data)
        self.assertEqual(res.status_code, 302, res.data[:3000])
        self.assertEqual(self.client.get(f"{self._base()}/{token}/preview").status_code, 200)
        sess = self.imp.get_session(token)
        db.session.refresh(sess)
        return json.loads(sess.plan_json)

    def _decide(self, token, decisions):
        sess = self.imp.get_session(token)
        db.session.refresh(sess)
        return self.client.post(f"{self._base()}/{token}/preview",
                                data={"action": "decisions", "plan_hash": sess.plan_hash, "decisions": json.dumps(decisions)})

    def _counts(self):
        M = self.M
        return (M["ShootingDay"].query.count(), M["ShootingDayScene"].query.count(),
                M["ProjectActivityLog"].query.count(), M["Notification"].query.count(),
                tuple((r.id, r.duration_seconds, r.sync_done) for r in M["ShootingDayScene"].query.order_by("id")))


class GoogleConnectionTests(GoogleFlowBase):
    def test_web_connect_stores_encrypted_tokens_and_keeps_login(self):
        res = self.client.get(f"/integrations/google-sheets/connect?project_id={self.project.id}&link={URL}")
        self.assertEqual(res.status_code, 302)
        loc = res.headers["Location"]
        self.assertTrue(loc.startswith(gsc.AUTH_URL))
        q = parse_qs(urlsplit(loc).query)
        self.assertIn("code_challenge", q)
        cookie = res.headers.get("Set-Cookie", "")
        self.assertIn(gss.BINDING_COOKIE, cookie)
        self.assertIn("HttpOnly", cookie)
        row = self.gs.OAuthState.query.one()
        self.assertNotEqual(row.state_hash, q["state"][0])
        self.assertNotIn(q["state"][0], json.dumps({c.name: str(getattr(row, c.name)) for c in row.__table__.columns}))
        res = self.client.get(f"/integrations/google-sheets/callback?state={q['state'][0]}&code=good")
        self.assertEqual(res.status_code, 302)
        self.assertIn("source=google", res.headers["Location"])
        self.assertIn("link=", res.headers["Location"])
        conn = self.gs.Connection.query.one()
        self.assertEqual((conn.account_id, conn.google_email), (self.acc.id, "editor@example.com"))
        dumped = json.dumps({c.name: str(getattr(conn, c.name)) for c in conn.__table__.columns})
        self.assertNotIn("RT-secret", dumped)
        self.assertNotIn("AT-1", dumped)
        self.assertEqual(self.gs.access_token(self.acc.id), "AT-1")
        with self.client.session_transaction() as s:
            self.assertEqual(s["account_id"], self.acc.id)
            self.assertFalse(any("token" in k.lower() for k in s.keys()))
        self.assertNotIn("AT-1", res.headers["Location"])
        res = self.client.get(f"/integrations/google-sheets/callback?state={q['state'][0]}&code=good")
        self.assertIn("/production/days/import", res.headers.get("Location", ""))
        self.assertEqual(self.fake.issued, 1, "replayed state must not exchange a second code")

    def test_callback_rejects_wrong_browser_account_expiry_cancel_and_scope(self):
        def start(client=None):
            client = client or self.client
            res = client.get(f"/integrations/google-sheets/connect?project_id={self.project.id}")
            return parse_qs(urlsplit(res.headers["Location"]).query)["state"][0]

        st = start()
        other_browser = app.test_client()
        self._login(self.acc, other_browser)
        res = other_browser.get(f"/integrations/google-sheets/callback?state={st}&code=good")
        self.assertIn(res.status_code, (302, 400))
        self.assertEqual(self.gs.Connection.query.count(), 0)

        st = start()
        self._login(self.other)
        self.client.get(f"/integrations/google-sheets/callback?state={st}&code=good")
        self.assertEqual(self.gs.Connection.query.count(), 0)
        self._login(self.acc)

        st = start()
        row = self.gs.OAuthState.query.filter_by(state_hash=gss._sha(st)).one()
        row.expires_at = datetime.now() - timedelta(seconds=1)
        db.session.commit()
        self.client.get(f"/integrations/google-sheets/callback?state={st}&code=good")
        self.assertEqual(self.gs.Connection.query.count(), 0)

        st = start()
        res = self.client.get(f"/integrations/google-sheets/callback?state={st}&error=access_denied")
        self.assertEqual(self.gs.Connection.query.count(), 0)
        page = self.client.get(res.headers["Location"])
        self.assertIn(b"cancelled", page.data)

        self.fake.scope = "openid email"
        st = start()
        self.client.get(f"/integrations/google-sheets/callback?state={st}&code=good")
        self.assertEqual(self.gs.Connection.query.count(), 0)
        self.assertEqual(self.client.get("/integrations/google-sheets/callback?state=forged&code=x").status_code, 400)

    def test_desktop_handoff_is_single_use_and_does_not_sign_in_the_browser(self):
        res = self.client.get(f"/integrations/google-sheets/connect?project_id={self.project.id}",
                              headers={"User-Agent": "Mozilla/5.0 BigBang Electron/33.4.11"})
        self.assertEqual(res.status_code, 200)
        m = re.search(rb'href="(http://localhost/integrations/google-sheets/browser/[^"]+)"', res.data)
        self.assertIsNotNone(m)
        handoff = m.group(1).decode()
        status_url = re.search(rb'data-status-url="([^"]+)"', res.data).group(1).decode()
        self.assertEqual(self.client.get(status_url).get_json()["result"], "waiting")

        browser = app.test_client()
        res = browser.get(handoff)
        self.assertEqual(res.status_code, 302)
        state = parse_qs(urlsplit(res.headers["Location"]).query)["state"][0]
        self.assertEqual(browser.get(handoff).status_code, 400, "handoff is single use")
        res = browser.get(f"/integrations/google-sheets/callback?state={state}&code=good")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Return to BigBang Desktop", res.data)
        with browser.session_transaction() as s:
            self.assertNotIn("account_id", s)
        self.assertEqual(self.gs.Connection.query.one().account_id, self.acc.id)
        self.assertEqual(self.client.get(status_url).get_json()["result"], "connected")
        self._login(self.other)
        self.assertEqual(self.client.get(status_url).status_code, 404)

    def test_refresh_revocation_and_disconnect(self):
        self._connect()
        conn = self.gs.Connection.query.one()
        conn.access_expires_at = datetime.now() - timedelta(minutes=1)
        db.session.commit()
        self.assertEqual(self.gs.access_token(self.acc.id), "AT-2")
        conn.access_expires_at = datetime.now() - timedelta(minutes=1)
        db.session.commit()
        self.fake.refresh_ok = False
        res, token = self._start_import()
        self.assertIsNone(token)
        page = self.client.get(res.headers["Location"])
        self.assertIn(b"revoked", page.data)
        self.assertEqual(self.gs.Connection.query.count(), 0)
        self.fake.refresh_ok = True
        self._connect()
        res = self.client.post("/integrations/google-sheets/disconnect", data={"project_id": self.project.id})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.gs.Connection.query.count(), 0)
        self.assertEqual(self.fake.revoked, ["RT-secret"])
        self._login(self.other)
        self.client.post("/integrations/google-sheets/disconnect")
        self.assertEqual(self.fake.revoked, ["RT-secret"])


class GoogleImportTests(GoogleFlowBase):
    def setUp(self):
        super().setUp()
        self._connect()

    def test_not_connected_link_goes_to_connect_and_invalid_link_makes_no_request(self):
        self.client.post("/integrations/google-sheets/disconnect")
        res, token = self._start_import()
        self.assertIsNone(token)
        self.assertIn("/integrations/google-sheets/connect", res.headers["Location"])
        n = len(self.fake.requests)
        res, token = self._start_import(link="https://evil.test/spreadsheets/d/" + SID)
        self.assertIsNone(token)
        self.assertEqual(len(self.fake.requests), n)

    def test_google_rows_match_like_equivalent_csv(self):
        before = self._counts()
        res, token = self._start_import()
        self.assertIsNotNone(token, res.headers.get("Location"))
        sess = self.imp.get_session(token)
        self.assertEqual(sess.file_kind, pip.GSHEET)
        opts = self.imp.options(sess)
        self.assertEqual(opts["sheets"], ["Log"], "gid preselects its worksheet")
        page = self.client.get(f"{self._base()}/{token}/sheets")
        self.assertIn(b"Notes", page.data)
        self.assertIn(b"Shoot log", page.data)
        plan = self._to_preview(token)
        rows = {r["row_number"]: r for r in plan["rows"]}
        self.assertEqual(rows[4]["status"], pim.STATUS_CHANGED)
        self.assertEqual({d["field"] for d in rows[4]["diffs"]}, {"duration", "sync_done"})
        self.assertEqual(rows[5]["status"], pim.STATUS_NEW)
        self.assertIn("001", rows[5]["identity"])
        self.assertEqual(rows[6]["status"], pim.STATUS_NEW)
        self.assertEqual(rows[7]["status"], pim.STATUS_INVALID)
        self.assertIn("#REF!", json.dumps(rows[7]["errors"]))
        self.assertEqual(self._counts(), before, "fetch + preview never mutate production data")
        self.assertTrue(all(m == "GET" for m, u, _ in self.fake.requests if "sheets.googleapis" in u))

        csv = ("\ufeffاليوم,الوحدة,التاريخ,الحلقة,المشهد,النوع,المدة,سينك,Camera\n"
               "Day 1,1,2026-10-01,1,7,Scene,2:00,yes,A\n"
               "يوم ٢,1,2026-10-02,2,001,Scene,1:30,,A\n"
               "Day 1,1,2026-10-01,1,12A,Reshoot,0:40,no,B\n")
        res = self.client.post(self._base(), data={"file": (io.BytesIO(csv.encode()), "log.csv")},
                               content_type="multipart/form-data")
        ctoken = re.search(r"/import/([^/]+)/sheets", res.headers["Location"]).group(1)
        self.client.post(f"{self._base()}/{ctoken}/sheets", data={
            "layout": "table", "sheets": ["CSV"], "header_0": "1",
            "csv_encoding": "utf-8-sig", "csv_delimiter": ","})
        data = {f"map__{k}": v for k, v in {"اليوم": "day_name", "الوحده": "unit_number", "التاريخ": "shooting_date",
                                              "الحلقه": "episode", "المشهد": "scene_label", "النوع": "item_type",
                                              "المده": "duration", "سينك": "sync_done", "camera": ""}.items()}
        data.update(action="continue", default__unit_number="1")
        self.client.post(f"{self._base()}/{ctoken}/mapping", data=data)
        self.client.get(f"{self._base()}/{ctoken}/preview")
        cplan = json.loads(self.imp.get_session(ctoken).plan_json)
        g = [(r["status"], r["identity"], sorted(d["field"] for d in r["diffs"])) for r in plan["rows"] if r["row_number"] < 7]
        c = [(r["status"], r["identity"], sorted(d["field"] for d in r["diffs"])) for r in cplan["rows"]]
        self.assertEqual(g, c)

    def test_api_failures_are_reported_without_sessions(self):
        cases = [
            (gsc.HttpResult(403, {"error": {"status": "PERMISSION_DENIED", "message": "denied"}}), b"cannot open this spreadsheet"),
            (gsc.HttpResult(403, {"error": {"status": "PERMISSION_DENIED", "message": "Request had insufficient authentication scopes.",
                                            "details": [{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]}}), b"read access was not granted"),
            (gsc.HttpResult(403, {"error": {"status": "PERMISSION_DENIED", "message": "Google Sheets API has not been used in project 1",
                                            "details": [{"reason": "SERVICE_DISABLED"}]}}), b"not enabled"),
            (gsc.HttpResult(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}), b"usage limit"),
            (gsc.HttpResult(400, {"error": {"status": "FAILED_PRECONDITION", "message": "This operation is not supported for this document"}}), b"Excel file stored in Drive"),
            (gsc.HttpResult(503, {"error": {"status": "UNAVAILABLE"}}), b"temporarily unavailable"),
            (gsc.GoogleSheetsError("timeout", "Google Sheets did not respond in time. Try again."), b"did not respond in time"),
            (gsc.GoogleSheetsError("network", "Could not reach Google."), b"Could not reach Google"),
        ]
        for failure, text in cases:
            self.fake.fail["sheets"] = failure
            res, token = self._start_import()
            self.assertIsNone(token)
            page = self.client.get(res.headers["Location"])
            self.assertIn(text, page.data, text)
        self.fake.fail.clear()
        res, token = self._start_import(link=f"https://docs.google.com/spreadsheets/d/{'Z' * 44}/edit")
        self.assertIn(b"not found", self.client.get(res.headers["Location"]).data)
        self.assertEqual(self.imp.Session.query.count(), 0)

    def test_resource_limits_and_empty_sheets(self):
        self.fake.sheets[SID]["sheets"][1]["rowCount"] = 4000
        self.fake.sheets[SID]["sheets"][1]["colCount"] = 60
        with mock.patch.dict(gsc.GOOGLE_LIMITS, {"max_cells": 1000}):
            res, token = self._start_import()
            self.assertIsNone(token)
            self.assertIn(b"too large", self.client.get(res.headers["Location"]).data)
        self.fake.sheets[SID]["sheets"][1]["rows"] = []
        self.fake.sheets[SID]["sheets"][1]["rowCount"] = 10
        self.fake.sheets[SID]["sheets"][0]["rows"] = []
        res, token = self._start_import()
        self.assertIsNone(token)
        self.assertIn(b"empty", self.client.get(res.headers["Location"]).data)

    def test_snapshot_is_stable_and_source_change_needs_explicit_choice(self):
        res, token = self._start_import()
        plan = self._to_preview(token)
        rows = {r["row_number"]: r for r in plan["rows"]}
        self._decide(token, {rows[4]["id"]: {"action": "update", "target_id": self.row7.id, "fields": ["duration"]},
                             rows[5]["id"]: {"action": "add"}})
        self.fake.sheets[SID]["sheets"][1]["rows"][3][6] = S("9:00")
        page = self.client.get(f"{self._base()}/{token}/confirm")
        self.assertIn(b"The source changed after your snapshot", page.data)
        self.assertIn(b"Log", page.data)
        before = self._counts()
        sess = self.imp.get_session(token)
        res = self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": sess.plan_hash})
        self.assertIn("/confirm", res.headers["Location"])
        self.assertEqual(self._counts(), before)
        grid_calls = sum(1 for _m, u, p in self.fake.requests if "sheets.googleapis" in u and "includeGridData" in dict(p or []))
        res = self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": sess.plan_hash, "ack_source": "1"})
        self.assertIn("/results", res.headers["Location"])
        self.assertEqual(sum(1 for _m, u, p in self.fake.requests if "sheets.googleapis" in u and "includeGridData" in dict(p or [])),
                         grid_calls, "execution never fetches from Google")
        db.session.expire_all()
        self.assertEqual(db.session.get(self.M["ShootingDayScene"], self.row7.id).duration_seconds, 120,
                         "the reviewed snapshot (2:00), not the newer 9:00, is imported")
        log = self.M["ProjectActivityLog"].query.filter_by(event_type="shooting_day.import.completed").one()
        meta = json.loads(log.metadata_json)
        self.assertEqual(meta["source"]["type"], "google_sheets")
        self.assertEqual(meta["source"]["spreadsheet_id"], SID)
        self.assertEqual(meta["source"]["title"], "Shoot log")
        self.assertEqual(meta["source"]["worksheets"][0]["title"], "Log")
        self.assertEqual(meta["source"]["freshness"], "changed")
        self.assertTrue(meta["source"]["fetched_at"])
        notes = self.M["Notification"].query.all()
        self.assertTrue(notes)
        self.assertTrue(all("(Google Sheets)" in (getattr(n, "message", "") or "") for n in notes))
        res = self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": sess.plan_hash, "ack_source": "1"})
        self.assertIn("/results", res.headers["Location"])
        self.assertEqual(db.session.get(self.M["ShootingDayScene"], self.row7.id).duration_seconds, 120)

    def test_unchanged_source_imports_without_ack_and_failed_check_requires_it(self):
        res, token = self._start_import()
        plan = self._to_preview(token)
        rows = {r["row_number"]: r for r in plan["rows"]}
        self._decide(token, {rows[5]["id"]: {"action": "add"}})
        page = self.client.get(f"{self._base()}/{token}/confirm")
        self.assertIn(b"Source unchanged", page.data)
        self.fake.fail["sheets"] = gsc.GoogleSheetsError("network", "Could not reach Google.")
        page = self.client.get(f"{self._base()}/{token}/confirm")
        self.assertIn(b"Could not check the source", page.data)
        self.assertNotIn(b"Source unchanged", page.data)
        sess = self.imp.get_session(token)
        res = self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": sess.plan_hash})
        self.assertIn("/confirm", res.headers["Location"])
        self.fake.fail.clear()
        self.client.get(f"{self._base()}/{token}/confirm")
        res = self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": sess.plan_hash})
        self.assertIn("/results", res.headers["Location"])

    def test_refresh_source_rebuilds_preview_and_resets_changed_decisions(self):
        res, token = self._start_import()
        plan = self._to_preview(token)
        rows = {r["row_number"]: r for r in plan["rows"]}
        self._decide(token, {rows[4]["id"]: {"action": "update", "target_id": self.row7.id, "fields": ["duration"]},
                             rows[5]["id"]: {"action": "add"}})
        old_sha = self.imp.get_session(token).file_sha256
        self.fake.sheets[SID]["sheets"][1]["rows"][3][6] = S("9:00")
        res = self.client.post(f"{self._base()}/{token}/source", data={"action": "refresh", "back": "preview"})
        self.assertIn("/preview", res.headers["Location"])
        sess = self.imp.get_session(token)
        db.session.refresh(sess)
        self.assertNotEqual(sess.file_sha256, old_sha)
        decisions = json.loads(sess.decisions_json)
        self.assertEqual(decisions[rows[4]["id"]]["action"], "skip", "changed row must be reviewed again")
        self.assertEqual(decisions[rows[5]["id"]]["action"], "add", "unchanged row keeps its choice")
        new_plan = json.loads(sess.plan_json)
        r4 = next(r for r in new_plan["rows"] if r["row_number"] == 4)
        self.assertIn("9:00", json.dumps(r4["diffs"]))
        self.fake.fail["sheets"] = gsc.HttpResult(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})
        res = self.client.post(f"{self._base()}/{token}/source", data={"action": "refresh", "back": "preview"})
        self.assertEqual(self.imp.get_session(token).file_sha256, sess.file_sha256, "failed refresh keeps the snapshot")

    def test_load_more_worksheets_and_day_sheet_layout(self):
        self.fake.sheets[SID]["sheets"][0]["rowCount"] = 4000
        self.fake.sheets[SID]["sheets"][0]["colCount"] = 60
        with mock.patch.dict(gsc.GOOGLE_LIMITS, {"max_cells": 3000}):
            res, token = self._start_import()
            source = self.imp.options(self.imp.get_session(token))["source"]
            self.assertEqual([s["title"] for s in source["loaded"]], ["Log"], "too large: only the gid worksheet is loaded")
            page = self.client.get(f"{self._base()}/{token}/sheets")
            self.assertIn(b"Other worksheets in this spreadsheet", page.data)
        self.fake.sheets[SID]["sheets"][0].update(rowCount=1, colCount=1)
        self.client.post(f"{self._base()}/{token}/source", data={"action": "load", "sheet_ids": ["0"], "back": "sheets"})
        source = self.imp.options(self.imp.get_session(token))["source"]
        self.assertEqual(sorted(s["title"] for s in source["loaded"]), ["Log", "Notes"])

    def test_cross_account_and_permissions(self):
        res, token = self._start_import()
        self._login(self.other)
        for path in ("sheets", "mapping", "preview", "confirm", "results", "results.csv"):
            self.assertEqual(self.client.get(f"{self._base()}/{token}/{path}").status_code, 404, path)
        self.assertEqual(self.client.post(f"{self._base()}/{token}/source", data={"action": "refresh"}).status_code, 404)
        res, other_token = self._start_import()
        self.assertIsNone(other_token, "Bob has no Google connection; Alice's is never used")
        self.assertIn("/integrations/google-sheets/connect", res.headers["Location"])
        self._login(self.acc)
        with mock.patch.dict(app.extensions["guest_access"], {"account_may_edit_production": lambda _a, _p: False}):
            res = self.client.post(f"{self._base()}/google", data={"link": URL})
            self.assertIn(res.status_code, (302, 403))
            self.assertNotIn("/sheets", res.headers.get("Location", ""))

    def test_existing_record_change_duplicate_confirm_reimport_and_rollback(self):
        res, token = self._start_import()
        plan = self._to_preview(token)
        rows = {r["row_number"]: r for r in plan["rows"]}
        self._decide(token, {rows[4]["id"]: {"action": "update", "target_id": self.row7.id, "fields": ["duration"]},
                             rows[5]["id"]: {"action": "add"}, rows[6]["id"]: {"action": "add"}})
        self.client.get(f"{self._base()}/{token}/confirm")
        r7 = db.session.get(self.M["ShootingDayScene"], self.row7.id)
        r7.duration_seconds = 75
        db.session.commit()
        sess = self.imp.get_session(token)
        res = self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": sess.plan_hash})
        self.assertIn("/preview", res.headers["Location"])
        plan = json.loads(self.imp.get_session(token).plan_json)
        rows = {r["row_number"]: r for r in plan["rows"]}
        self._decide(token, {rows[5]["id"]: {"action": "add"}, rows[6]["id"]: {"action": "add"}})
        self.client.get(f"{self._base()}/{token}/confirm")
        before = self._counts()
        real = pis._add_row
        calls = {"n": 0}

        def flaky(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real(*a, **kw)

        sess = self.imp.get_session(token)
        with mock.patch.object(pis, "_add_row", side_effect=flaky):
            self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": sess.plan_hash})
        db.session.expire_all()
        self.assertEqual(self._counts(), before)
        res = self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": sess.plan_hash})
        self.assertIn("/results", res.headers["Location"])
        after = self._counts()
        res = self.client.post(f"{self._base()}/{token}/confirm", data={"plan_hash": sess.plan_hash})
        self.assertIn("/results", res.headers["Location"])
        self.assertEqual(self._counts(), after)
        _res, token2 = self._start_import()
        plan2 = self._to_preview(token2)
        statuses = {r["row_number"]: r["status"] for r in plan2["rows"]}
        self.assertEqual((statuses[5], statuses[6]), (pim.STATUS_IDENTICAL, pim.STATUS_IDENTICAL))

    def test_upload_page_shows_both_sources(self):
        page = self.client.get(self._base())
        self.assertIn(b"Upload Excel / CSV", page.data)
        self.assertIn(b"Google Sheets link", page.data)
        page = self.client.get(f"{self._base()}?source=google")
        self.assertIn(b"Connected as", page.data)
        self.assertIn(b"editor@example.com", page.data)
        self.assertNotIn(b"AT-", page.data)


if __name__ == "__main__":
    unittest.main()
