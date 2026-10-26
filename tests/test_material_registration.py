"""Shooting-day material registration — shared status, modal API and page consistency."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_material_registration.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from sqlalchemy.exc import IntegrityError

from app import app, db
from time_utils import today_cairo


class MaterialRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            assert not str(db.engine.url).endswith("instance/app.db"), db.engine.url
            db.create_all()
            import machine_room_dashboard_support as mr_dash
            import machine_room_media_workflow_support as wf
            import material_registration_support as regs

            now = lambda: __import__("datetime").datetime.utcnow()  # noqa: E731
            mr_dash.ensure_machine_room_dashboard_tables(db, now)
            wf.ensure_machine_room_media_workflow_tables(db, now)
            regs.ensure_material_registration_table(db, now)

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        import machine_room_dashboard_support as mr_dash
        import machine_room_media_workflow_support as wf

        now = lambda: __import__("datetime").datetime.utcnow()  # noqa: E731
        self.wf = wf
        self.wfm = wf.register_machine_room_media_workflow_models(db, now)
        self.mr = mr_dash.register_machine_room_dashboard_models(db, now)
        self.api = app.extensions["material_registration"]
        self.Reg = self.api.Registration
        self._wipe()

        self.mr_acc, self.mr_user = self._make_account("reg-mr@test.local", "machine_room", "MR Operator")
        self.admin, self.admin_user = self._make_account("reg-admin@test.local", "admin", "Admin")
        self.producer, self.producer_user = self._make_account("reg-prod@test.local", "producer", "Producer")
        self.outsider, _ = self._make_account("reg-out@test.local", "producer", "Outside Producer")
        self.editor, self.editor_user = self._make_account("reg-ed@test.local", "editor", "Editor")

        self.project = self.M["Project"](
            name="Reg Project", project_type="Feature Film", production_house="T", director="T"
        )
        db.session.add(self.project)
        db.session.flush()
        for u in (self.mr_user, self.producer_user, self.editor_user):
            db.session.add(self.M["ProjectMember"](project_id=self.project.id, user_id=u.id))

        today = today_cairo()
        SD = self.M["ShootingDay"]
        self.day = SD(project_id=self.project.id, unit_number=1, day_name="Day 1",
                      shooting_date=today - timedelta(days=2))
        self.future = SD(project_id=self.project.id, unit_number=1, day_name="Day 9",
                         shooting_date=today + timedelta(days=5))
        db.session.add_all([self.day, self.future])
        db.session.flush()

        self.shuttle = self.mr.StorageVolume(
            name="Shuttle", display_name="Shuttle A", mount_path="/Volumes/ShuttleA",
            storage_role="transfer", mounted_status="mounted", is_mounted=True,
        )
        db.session.add(self.shuttle)
        db.session.flush()
        db.session.add(self.mr.StorageVolumeProjectLink(volume_id=self.shuttle.id, project_id=self.project.id))
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self._wipe()
        db.session.remove()
        self.ctx.pop()

    def _wipe(self):
        """Other suites share this test database, so leave nothing behind."""
        for model in (
            self.Reg,
            self.wfm.MachineRoomMediaWorkflowEvent,
            self.wfm.MachineRoomMediaWorkflowIssue,
            self.wfm.MachineRoomMediaWorkflowOverride,
            self.wfm.MachineRoomMediaWorkflowDay,
            self.wfm.MachineRoomMediaWorkflow,
            self.mr.MediaIngestBatch,
            self.mr.StorageVolumeShootingDayUsage,
            self.mr.StorageVolumeProjectLink,
            self.mr.MachineRoomAuditLog,
            self.mr.StorageVolume,
            self.M["ProjectActivityLog"],
            self.M["Notification"],
            self.M["Task"],
            self.M["ProjectMember"],
            self.M["ShootingDay"],
            self.M["Project"],
            self.M["User"],
            self.M["Account"],
        ):
            db.session.query(model).delete()
        db.session.commit()

    def _make_account(self, email, role, name):
        acc = self.M["Account"](email=email, password_hash="x", role=role)
        db.session.add(acc)
        db.session.flush()
        user = self.M["User"](name=name, email=email, account_id=acc.id)
        db.session.add(user)
        db.session.flush()
        return acc, user

    # --- helpers ------------------------------------------------------------

    def _login(self, acc):
        with self.client.session_transaction() as sess:
            sess["account_id"] = acc.id

    def _post(self, day_id, **body):
        return self.client.post(
            f"/machine-room/material-registration/{day_id}",
            data=json.dumps(body),
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )

    def _full(self, **overrides):
        body = {
            "action": "save",
            "video_state": "present",
            "video_size_tb": "1.5",
            "audio_state": "present",
            "audio_size_gb": "120",
            "material_source": "transfer_shuttle",
            "source_volume_id": str(self.shuttle.id),
            "source_path": "/Volumes/ShuttleA/DAY01",
            "responsible_user_id": str(self.mr_user.id),
            "notes": "Two mags",
        }
        body.update(overrides)
        return body

    def _row(self, day_id):
        return self.api.service.status_for_day(day_id)

    # --- tests --------------------------------------------------------------

    def test_day_without_workflow_appears_once_in_each_view_with_matching_counts(self):
        self._login(self.mr_acc)
        rows = self.api.rows_for_account(self.mr_acc)
        summary = self.api.summarize(rows)
        self.assertEqual(summary["needs_registration"], 2)
        self.assertEqual(summary["upcoming"], 1)

        backups = self.client.get("/machine-room/dashboard/backups").get_data(as_text=True)
        tasks = self.client.get("/machine-room/tasks/progress").get_data(as_text=True)
        missing = self.client.get("/missing-information").get_data(as_text=True)
        # Machine Room accounts keep their existing block on /projects/...; their project
        # view of shooting days is the Machine Room "Shooting Day Storage" page.
        storage = self.client.get(f"/projects/{self.project.id}/machine-room/hdd-media").get_data(as_text=True)
        blocked = self.client.get(f"/projects/{self.project.id}/production")
        self.assertEqual(blocked.status_code, 302)

        for html in (backups, tasks, storage):
            self.assertEqual(html.count(f'data-mr-reg-row="{self.day.id}"'), 1)
            self.assertEqual(len(re.findall(r'data-mr-reg-row="\d+"', html)), summary["needs_registration"])
            self.assertIn(f'data-mr-reg-count="{summary["needs_registration"]}"', html)
        self.assertIn("Unknown — material receipt not registered", backups)
        self.assertEqual(missing.count(f'data-mr-reg-open data-day-id="{self.day.id}"'), 1)
        self.assertEqual(len(re.findall(r"data-mr-reg-open data-day-id=", missing)), summary["needs_registration"])

        self._login(self.producer)
        production = self.client.get(f"/projects/{self.project.id}/production").get_data(as_text=True)
        self.assertEqual(production.count(f'data-mr-reg-open data-day-id="{self.day.id}"'), 1)
        self.assertIn("Awaiting material registration", production)
        self.assertIn("2 shooting days</strong>", production)
        self.assertEqual(self.api.summarize(self.api.rows_for_account(self.producer)), summary)

    def test_multi_day_and_direct_workflow_links_are_recognized(self):
        SD = self.M["ShootingDay"]
        extra = SD(project_id=self.project.id, unit_number=1, day_name="Day 2",
                   shooting_date=self.day.shooting_date)
        direct_only = SD(project_id=self.project.id, unit_number=1, day_name="Day 3",
                         shooting_date=self.day.shooting_date)
        db.session.add_all([extra, direct_only])
        db.session.flush()
        WF = self.wfm.MachineRoomMediaWorkflow
        w, _ = self.wf.get_or_create_workflow(
            db, self.wfm, project_id=self.project.id, shooting_days=[self.day, extra],
            operator_user_id=None, now_fn=lambda: __import__("datetime").datetime.utcnow(),
        )
        legacy = WF(project_id=self.project.id, shooting_day_id=direct_only.id)
        db.session.add(legacy)
        db.session.commit()
        self.assertEqual(self._row(extra.id)["workflow_id"], w.id)
        self.assertEqual(self._row(direct_only.id)["workflow_id"], legacy.id)
        # A linked workflow does not make registration complete.
        self.assertTrue(self._row(extra.id)["needs_registration"])

    def test_existing_shooting_date_is_never_reported_missing(self):
        self._login(self.mr_acc)
        row = self._row(self.day.id)
        self.assertNotIn("Shooting date", row["missing_labels"])
        missing = self.client.get("/missing-information").get_data(as_text=True)
        self.assertNotIn("Missing: Shooting date", missing)
        self.assertIn("Missing: Video size, Audio size, Material source, Source disk / volume, Responsible operator", missing)

    def test_unknown_size_stays_distinct_from_no_media(self):
        self._login(self.mr_acc)
        r = self._post(self.day.id, **self._full(video_state="unknown", video_size_tb="", audio_state="none", audio_size_gb=""))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        reg = self.Reg.query.filter_by(shooting_day_id=self.day.id).one()
        self.assertEqual((reg.video_state, reg.video_size_tb), ("unknown", None))
        self.assertEqual((reg.audio_state, reg.audio_size_gb), ("none", None))
        row = self._row(self.day.id)
        self.assertIn("Video size", row["missing_labels"])
        self.assertNotIn("Audio size", row["missing_labels"])

        empty = self._post(self.day.id, **self._full(video_state="present", video_size_tb=""))
        self.assertEqual(empty.status_code, 400)
        zero = self._post(self.day.id, **self._full(video_state="present", video_size_tb="0"))
        self.assertEqual(zero.status_code, 400)
        db.session.expire_all()
        self.assertIsNone(self.Reg.query.filter_by(shooting_day_id=self.day.id).one().video_size_tb)

    def test_save_registration_only_does_not_start_copy_or_protect(self):
        self._login(self.mr_acc)
        before_batches = self.mr.MediaIngestBatch.query.count()
        r = self._post(self.day.id, **self._full())
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        body = r.get_json()
        self.assertTrue(body["completed_now"])
        self.assertEqual(body["status"]["label"], "Registered — copy not started")
        self.assertIsNone(body["workflow_id"])
        self.assertEqual(self.wfm.MachineRoomMediaWorkflow.query.count(), 0)
        self.assertEqual(self.mr.MediaIngestBatch.query.count(), before_batches)
        self.assertEqual(self.M["Task"].query.count(), 0)

        backups = self.client.get("/machine-room/dashboard/backups").get_data(as_text=True)
        row_html = backups.split(f'data-mr-reg-row="{self.day.id}"', 1)[1].split("</tr>", 1)[0]
        self.assertIn("Not protected — no copy recorded", row_html)
        self.assertNotIn("Protected<", row_html)
        self.assertNotIn("mr-pill--protected", backups)
        missing = self.client.get("/missing-information").get_data(as_text=True)
        self.assertNotIn(f'data-day-id="{self.day.id}"', missing)

        reg = self.Reg.query.filter_by(shooting_day_id=self.day.id).one()
        self.assertEqual(reg.completed_by_user_id, self.mr_user.id)
        self.assertIsNotNone(reg.completed_at)
        self.assertEqual(
            self.mr.MachineRoomAuditLog.query.filter_by(action="material_registration_completed").count(), 1
        )
        log = self.M["ProjectActivityLog"].query.filter_by(event_type="media.registration.completed").all()
        self.assertEqual(len(log), 1)

    def test_completion_notifies_once_and_page_views_never_notify(self):
        self._login(self.mr_acc)
        N = self.M["Notification"]
        for url in ("/machine-room/dashboard/backups", "/missing-information", "/machine-room/tasks/progress"):
            self.client.get(url)
        self.assertEqual(N.query.count(), 0)
        self._post(self.day.id, **self._full())
        first = N.query.count()
        self.assertGreater(first, 0)
        self.assertTrue(all("Material registered" in n.title for n in N.query.all()))
        self._post(self.day.id, **self._full(notes="Changed note"))
        self._post(self.day.id, **self._full(notes="Changed note"))
        self.assertEqual(N.query.count(), first)
        self.assertEqual(N.query.filter(N.title.contains("Ready for editing")).count(), 0)

    def test_start_workflow_reuses_day_and_prevents_duplicates(self):
        self._login(self.mr_acc)
        days_before = self.M["ShootingDay"].query.count()
        first = self._post(self.day.id, **self._full(action="start"))
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        first_body = first.get_json()
        self.assertTrue(first_body["workflow_created"])
        again = self._post(self.day.id, **self._full(action="start")).get_json()
        self.assertFalse(again["workflow_created"])
        self.assertEqual(again["workflow_id"], first_body["workflow_id"])
        WF = self.wfm.MachineRoomMediaWorkflow
        self.assertEqual(WF.query.count(), 1)
        w = WF.query.one()
        self.assertEqual(w.shooting_day_id, self.day.id)
        self.assertIsNone(w.backup_started_at)
        self.assertEqual(self.M["ShootingDay"].query.count(), days_before)
        self.assertEqual(self._row(self.day.id)["status"], "registered")

    def test_concurrent_start_returns_the_workflow_that_won(self):
        self._login(self.mr_acc)
        self._post(self.day.id, **self._full())
        real = self.wf.get_or_create_workflow

        def other_request_wins(*args, **kwargs):
            real(*args, **kwargs)
            db.session.commit()
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

        with mock.patch.object(self.wf, "get_or_create_workflow", side_effect=other_request_wins):
            r = self._post(self.day.id, **self._full(action="start"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertFalse(r.get_json()["workflow_created"])
        self.assertEqual(self.wfm.MachineRoomMediaWorkflow.query.count(), 1)

    def test_existing_workflow_is_opened_not_recreated(self):
        self._login(self.mr_acc)
        created = self.client.post(
            "/machine-room/workflows",
            data=json.dumps({"project_id": self.project.id, "shooting_day_id": self.day.id}),
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
        ).get_json()
        r = self._post(self.day.id, **self._full(action="start")).get_json()
        self.assertEqual(r["workflow_id"], created["workflow_id"])
        self.assertFalse(r["workflow_created"])
        self.assertEqual(self.wfm.MachineRoomMediaWorkflow.query.count(), 1)

    def test_permissions_and_project_visibility(self):
        url = f"/machine-room/material-registration/{self.day.id}"
        self._login(self.editor)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.api.rows_for_account(self.editor), [])
        self._login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.api.rows_for_account(self.outsider), [])

        self._login(self.producer)
        detail = self.client.get(url).get_json()
        self.assertTrue(detail["can_edit_date"])

        self._login(self.mr_acc)
        detail = self.client.get(url).get_json()
        self.assertFalse(detail["can_edit_date"])
        new_date = (self.day.shooting_date - timedelta(days=1)).isoformat()
        denied = self._post(self.day.id, **self._full(shooting_date=new_date))
        self.assertEqual(denied.status_code, 403)
        db.session.expire_all()
        self.assertNotEqual(self.M["ShootingDay"].query.get(self.day.id).shooting_date.isoformat(), new_date)

        self._login(self.producer)
        ok = self._post(self.day.id, **self._full(shooting_date=new_date))
        self.assertEqual(ok.status_code, 200, ok.get_data(as_text=True))
        db.session.expire_all()
        self.assertEqual(self.M["ShootingDay"].query.get(self.day.id).shooting_date.isoformat(), new_date)

    def test_upcoming_day_is_awaiting_material_not_urgent(self):
        self._login(self.mr_acc)
        row = self._row(self.future.id)
        self.assertEqual(row["display_status"], "upcoming")
        missing = self.client.get("/missing-information?category=machine_room").get_data(as_text=True)
        item = missing.split(f'data-day-id="{self.future.id}"', 1)[0].rsplit("<li", 1)[1]
        self.assertIn("dash-severity-low", item)

    # --- Regression: shared workflow totals / copy-step defaults -----------------

    def _second_day(self, name="Day 2"):
        d = self.M["ShootingDay"](project_id=self.project.id, unit_number=1, day_name=name,
                                  shooting_date=self.day.shooting_date)
        db.session.add(d)
        db.session.flush()
        return d

    def _workflow_for(self, days, **sizes):
        w, _ = self.wf.get_or_create_workflow(
            db, self.wfm, project_id=self.project.id, shooting_days=days, operator_user_id=None,
            now_fn=lambda: __import__("datetime").datetime.utcnow(),
        )
        for key, value in sizes.items():
            setattr(w, key, value)
        db.session.commit()
        return w

    def _defaults(self, workflow_id):
        r = self.client.get(f"/machine-room/workflows/{workflow_id}")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        return r.get_json()["workflow"]["copy_size_defaults"]

    def test_shared_workflow_totals_are_not_assigned_to_each_member_day(self):
        day2 = self._second_day()
        self._workflow_for([self.day, day2], backup_video_size_tb=2.5, backup_audio_size_gb=80.0)
        for d in (self.day, day2):
            row = self._row(d.id)
            self.assertFalse(row["fields"]["video"]["known"], d.day_name)
            self.assertFalse(row["fields"]["audio"]["known"], d.day_name)
            self.assertIsNone(row["fields"]["video"]["size"])
            self.assertIn("Video size", row["missing_labels"])
            self.assertIn("Audio size", row["missing_labels"])
            self.assertTrue(row["needs_registration"])
        # The same answer when every page loads its rows in one batch.
        batch = {r["shooting_day_id"]: r for r in self.api.service.statuses(project_ids=[self.project.id])}
        self.assertFalse(batch[day2.id]["fields"]["video"]["known"])
        self._login(self.mr_acc)
        missing = self.client.get("/missing-information?category=machine_room").get_data(as_text=True)
        for d in (self.day, day2):
            item = missing.split(f'data-day-id="{d.id}"', 1)[0].rsplit("<li", 1)[1]
            self.assertIn("Missing: Video size, Audio size", item)

    def test_single_day_workflow_totals_still_count_for_that_day(self):
        self._workflow_for([self.day], backup_video_size_tb=1.2, backup_audio_size_gb=50.0)
        row = self._row(self.day.id)
        self.assertEqual(row["fields"]["video"]["size"], 1.2)
        self.assertEqual(row["fields"]["audio"]["size"], 50.0)

    def test_direct_and_association_links_both_count_as_membership(self):
        WF, Link = self.wfm.MachineRoomMediaWorkflow, self.wfm.MachineRoomMediaWorkflowDay
        day2 = self._second_day()
        # Legacy row: day 1 only through shooting_day_id, day 2 only through the association table.
        legacy = WF(project_id=self.project.id, shooting_day_id=self.day.id,
                    backup_video_size_tb=4.0, backup_audio_size_gb=90.0)
        db.session.add(legacy)
        db.session.flush()
        db.session.add(Link(workflow_id=legacy.id, shooting_day_id=day2.id))
        db.session.commit()
        self.assertEqual(self.api.service.workflow_member_counts([legacy]), {legacy.id: 2})
        for d in (self.day, day2):
            row = self._row(d.id)
            self.assertEqual(row["workflow_id"], legacy.id)
            self.assertFalse(row["fields"]["video"]["known"])

        direct_only = self._second_day("Day 3")
        solo = WF(project_id=self.project.id, shooting_day_id=direct_only.id, backup_video_size_tb=0.7)
        db.session.add(solo)
        db.session.commit()
        self.assertEqual(self.api.service.workflow_member_counts([solo]), {solo.id: 1})
        self.assertEqual(self._row(direct_only.id)["fields"]["video"]["size"], 0.7)

    def test_single_day_registration_prefills_the_copy_form(self):
        self._login(self.mr_acc)
        body = self._post(self.day.id, **self._full(action="start")).get_json()
        wid = body["workflow_id"]
        defaults = self._defaults(wid)
        self.assertEqual((defaults["video"]["value"], defaults["video"]["source"]), (1.5, "registration"))
        self.assertEqual((defaults["audio"]["value"], defaults["audio"]["source"]), (120.0, "registration"))
        page = self.client.get(f"/machine-room/workflow?workflow_id={wid}").get_data(as_text=True)
        self.assertRegex(page, r'name="video_size_tb"[^>]*value="1\.5"')
        self.assertRegex(page, r'name="audio_size_gb"[^>]*value="120"')
        w = db.session.get(self.wfm.MachineRoomMediaWorkflow, wid)
        # Defaults are derived, not copied: the workflow keeps no competing size until the copy starts.
        self.assertIsNone(w.backup_video_size_tb)
        self.assertIsNone(w.backup_audio_size_gb)

    def test_explicitly_absent_media_stays_distinct_from_unknown(self):
        self._login(self.mr_acc)
        self._post(self.day.id, **self._full(audio_state="none", audio_size_gb=""))
        defaults = self._defaults(self._workflow_for([self.day]).id)
        self.assertEqual(defaults["audio"]["value"], 0.0)
        self.assertEqual(defaults["audio"]["source"], "registration")
        self.assertIn("No audio", defaults["audio"]["hint"])

        day2 = self._second_day()
        self._post(day2.id, **self._full(audio_state="unknown", audio_size_gb=""))
        defaults = self._defaults(self._workflow_for([day2]).id)
        self.assertIsNone(defaults["audio"]["value"])
        self.assertEqual(defaults["audio"]["source"], "incomplete")

    def test_multi_day_total_when_every_day_is_known(self):
        self._login(self.mr_acc)
        day2 = self._second_day()
        self._post(self.day.id, **self._full(video_size_tb="1.5", audio_size_gb="120"))
        self._post(day2.id, **self._full(video_size_tb="2", audio_state="none", audio_size_gb=""))
        defaults = self._defaults(self._workflow_for([self.day, day2]).id)
        self.assertEqual(defaults["video"]["value"], 3.5)
        self.assertEqual(defaults["audio"]["value"], 120.0)
        self.assertEqual(defaults["video"]["day_count"], 2)
        self.assertIn("Combined from 2 registered days", defaults["video"]["hint"])
        # Per-day amounts stay per day.
        self.assertEqual(self._row(day2.id)["fields"]["video"]["size"], 2.0)

    def test_partial_information_gives_an_incomplete_total(self):
        self._login(self.mr_acc)
        day2 = self._second_day()
        self._post(self.day.id, **self._full(video_size_tb="1.5"))
        self._post(day2.id, **self._full(video_state="unknown", video_size_tb=""))
        w = self._workflow_for([self.day, day2])
        defaults = self._defaults(w.id)
        self.assertIsNone(defaults["video"]["value"])
        self.assertEqual(defaults["video"]["source"], "incomplete")
        self.assertIn("Day 2", defaults["video"]["hint"])
        self.assertEqual(defaults["audio"]["value"], 240.0)
        page = self.client.get(f"/machine-room/workflow?workflow_id={w.id}").get_data(as_text=True)
        self.assertRegex(page, r'name="video_size_tb"[^>]*value=""')
        self.assertIn("Total incomplete", page)

    def test_existing_operation_values_are_preserved(self):
        self._login(self.mr_acc)
        self._post(self.day.id, **self._full(video_size_tb="1.5", audio_size_gb="120"))
        w = self._workflow_for([self.day], backup_video_size_tb=3.0)
        defaults = self._defaults(w.id)
        self.assertEqual((defaults["video"]["value"], defaults["video"]["source"]), (3.0, "workflow"))
        self.assertEqual((defaults["audio"]["value"], defaults["audio"]["source"]), (120.0, "registration"))
        db.session.refresh(w)
        self.assertEqual(w.backup_video_size_tb, 3.0)
        self.assertIsNone(w.backup_audio_size_gb)
        # The registration keeps its own per-day amount.
        self.assertEqual(self.Reg.query.filter_by(shooting_day_id=self.day.id).one().video_size_tb, 1.5)

    def test_reopening_an_existing_workflow_uses_the_same_rules(self):
        self._login(self.mr_acc)
        headers = {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}
        created = self.client.post(
            "/machine-room/workflows",
            data=json.dumps({"project_id": self.project.id, "shooting_day_id": self.day.id}),
            headers=headers,
        ).get_json()
        self.assertIsNone(self._defaults(created["workflow_id"])["video"]["value"])
        reopened = self._post(self.day.id, **self._full(action="start")).get_json()
        self.assertEqual(reopened["workflow_id"], created["workflow_id"])
        self.assertFalse(reopened["workflow_created"])
        self.assertEqual(self._defaults(created["workflow_id"])["video"]["value"], 1.5)
        again = self.client.post(
            "/machine-room/workflows",
            data=json.dumps({"project_id": self.project.id, "shooting_day_id": self.day.id}),
            headers=headers,
        ).get_json()
        self.assertEqual(again["workflow_id"], created["workflow_id"])
        self.assertEqual(self._defaults(again["workflow_id"])["audio"]["value"], 120.0)

    def test_size_defaults_do_not_change_protection_or_workflow_stage(self):
        self._login(self.mr_acc)
        wid = self._post(self.day.id, **self._full(action="start")).get_json()["workflow_id"]
        WF = self.wfm.MachineRoomMediaWorkflow
        fields = ("status", "current_stage", "received_at", "backup_started_at", "backup_finished_at",
                  "backup_verified_at", "backup_verification_method", "backup_video_size_tb",
                  "backup_audio_size_gb", "completed_at")
        w = db.session.get(WF, wid)
        before = {f: getattr(w, f) for f in fields}
        status_before = self._row(self.day.id)["status"]
        self._defaults(wid)
        self.client.get(f"/machine-room/workflow?workflow_id={wid}")
        backups = self.client.get("/machine-room/dashboard/backups").get_data(as_text=True)
        db.session.expire_all()
        w = db.session.get(WF, wid)
        self.assertEqual({f: getattr(w, f) for f in fields}, before)
        self.assertEqual(self._row(self.day.id)["status"], status_before)
        self.assertEqual(status_before, "registered")
        self.assertNotIn("mr-pill--protected", backups)
        self.assertNotIn("mr-pill--safe", backups)

    def test_registration_status_uses_recorded_sizes_without_inventing_them(self):
        usage = self.mr.StorageVolumeShootingDayUsage(
            volume_id=self.shuttle.id, shooting_day_id=self.day.id, video_size_tb=2.0, audio_size_tb=0.0
        )
        db.session.add(usage)
        db.session.commit()
        row = self._row(self.day.id)
        self.assertTrue(row["fields"]["video"]["known"])
        self.assertEqual(row["fields"]["video"]["size"], 2.0)
        # A stored 0 is not evidence of "no audio".
        self.assertFalse(row["fields"]["audio"]["known"])
        self.assertEqual(self.Reg.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
