"""Guided Machine Room media workflow — state machine and route tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_mr_media_wf_unittest.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db


class MachineRoomMediaWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        with app.app_context():
            db.create_all()
            import machine_room_dashboard_support as mr_dash
            import machine_room_media_workflow_support as wf

            mr_dash.ensure_machine_room_dashboard_tables(db, lambda: __import__("datetime").datetime.utcnow())
            wf.ensure_machine_room_media_workflow_tables(db, lambda: __import__("datetime").datetime.utcnow())

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        import machine_room_media_workflow_support as wf
        import machine_room_dashboard_support as mr_dash

        self.wf = wf
        self.models = wf.register_machine_room_media_workflow_models(
            db, lambda: __import__("datetime").datetime.utcnow()
        )
        self.StorageVolume = mr_dash.register_machine_room_dashboard_models(
            db, lambda: __import__("datetime").datetime.utcnow()
        ).StorageVolume

        for table in (
            self.models.MachineRoomMediaWorkflowOverride,
            self.models.MachineRoomMediaWorkflowIssue,
            self.models.MachineRoomMediaWorkflowEvent,
            self.models.MachineRoomMediaWorkflowDay,
            self.models.MachineRoomMediaWorkflow,
        ):
            db.session.query(table).delete()
        db.session.query(self.StorageVolume).delete()
        db.session.query(self.M["ShootingDay"]).delete()
        db.session.query(self.M["Project"]).delete()
        db.session.query(self.M["User"]).delete()
        db.session.query(self.M["Account"]).delete()
        db.session.commit()

        self.mr_acc = self.M["Account"](
            email="mr-op@test.local", password_hash="x", role="machine_room"
        )
        self.admin = self.M["Account"](
            email="mr-admin-wf@test.local", password_hash="x", role="admin"
        )
        db.session.add_all([self.mr_acc, self.admin])
        db.session.flush()
        self.mr_user = self.M["User"](
            name="MR Operator", email="mr-op@test.local", account_id=self.mr_acc.id
        )
        self.admin_user = self.M["User"](
            name="Admin", email="mr-admin-wf@test.local", account_id=self.admin.id
        )
        db.session.add_all([self.mr_user, self.admin_user])
        self.project = self.M["Project"](
            name="Ras Al Afaa",
            project_type="TV series",
            production_house="Test",
            director="Test",
            number_of_episodes=10,
        )
        db.session.add(self.project)
        db.session.flush()
        from datetime import date

        self.day = self.M["ShootingDay"](
            project_id=self.project.id,
            unit_number=1,
            day_name="24",
            shooting_date=date(2026, 10, 17),
        )
        db.session.add(self.day)
        db.session.flush()

        self.shuttle = self.StorageVolume(
            name="Amino",
            display_name="Amino",
            mount_path="/Volumes/Amino",
            storage_role="transfer",
            mounted_status="mounted",
            is_mounted=True,
        )
        self.backup = self.StorageVolume(
            name="G-Raid",
            display_name="G-Raid 001",
            mount_path="/Volumes/GRaid",
            storage_role="project_backup",
            mounted_status="mounted",
            is_mounted=True,
        )
        self.inhouse = self.StorageVolume(
            name="Nucleus1",
            display_name="Nucleus1",
            mount_path="/Volumes/Nucleus1",
            storage_role="working_storage",
            mounted_status="mounted",
            is_mounted=True,
        )
        db.session.add_all([self.shuttle, self.backup, self.inhouse])
        db.session.flush()
        self.Link = mr_dash.register_machine_room_dashboard_models(
            db, lambda: __import__("datetime").datetime.utcnow()
        ).StorageVolumeProjectLink
        db.session.query(self.Link).delete()
        db.session.add(self.Link(volume_id=self.shuttle.id, project_id=self.project.id))
        db.session.commit()

    def tearDown(self):
        self.ctx.pop()

    def _login_mr(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.mr_acc.id

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.admin.id

    def _csrf_headers(self):
        # App may use cookie CSRF; session login is enough for many tests.
        return {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}

    def _create_workflow(self):
        self._login_mr()
        r = self.client.post(
            "/machine-room/workflows",
            data=json.dumps(
                {"project_id": self.project.id, "shooting_day_id": self.day.id}
            ),
            headers=self._csrf_headers(),
        )
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:800])
        data = r.get_json()
        self.assertTrue(data.get("ok"))
        return data["workflow_id"]

    def test_progress_page_renders_mission_control(self):
        self._login_mr()
        r = self.client.get("/machine-room/tasks/progress")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:500])
        body = r.get_data(as_text=True)
        self.assertIn("Daily Media Processing", body)
        self.assertIn("Pending", body)

    def test_create_and_duplicate_reopens(self):
        wid = self._create_workflow()
        r2 = self.client.post(
            "/machine-room/workflows",
            data=json.dumps(
                {"project_id": self.project.id, "shooting_day_id": self.day.id}
            ),
            headers=self._csrf_headers(),
        )
        data = r2.get_json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("created"))
        self.assertEqual(data["workflow_id"], wid)

    def test_cannot_skip_backup_to_transcode(self):
        wid = self._create_workflow()
        # Try start transcode without receive/backup
        r = self.client.post(
            f"/machine-room/workflows/{wid}/transcode",
            data=json.dumps({"action": "start"}),
            headers=self._csrf_headers(),
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("Backup", r.get_json().get("error", ""))

    def test_full_happy_path_operator_confirmed(self):
        wid = self._create_workflow()
        # Receive — no separate "connected" confirmation needed
        r = self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps(
                {
                    "action": "continue",
                    "project_id": self.project.id,
                    "shooting_day_id": self.day.id,
                    "shuttle_volume_id": self.shuttle.id,
                }
            ),
            headers=self._csrf_headers(),
        )
        self.assertTrue(r.get_json().get("ok"), r.get_data(as_text=True)[:800])

        # Backup
        r = self.client.post(
            f"/machine-room/workflows/{wid}/backup",
            data=json.dumps(
                {"action": "start", "backup_destination_id": self.backup.id}
            ),
            headers=self._csrf_headers(),
        )
        body = r.get_json()
        self.assertTrue(body.get("ok"), r.get_data(as_text=True)[:800])
        self.assertFalse(body.get("automation"))
        self.assertIn("not copying", (body.get("note") or "").lower())

        self.client.post(
            f"/machine-room/workflows/{wid}/backup",
            data=json.dumps({"action": "finish_copy"}),
            headers=self._csrf_headers(),
        )
        r = self.client.post(
            f"/machine-room/workflows/{wid}/backup",
            data=json.dumps(
                {
                    "action": "verify",
                    "checks": list(self.wf.BACKUP_CHECKS),
                    "verification_method": "operator_confirmed",
                }
            ),
            headers=self._csrf_headers(),
        )
        self.assertTrue(r.get_json().get("ok"), r.get_data(as_text=True)[:800])

        # Try mark ready early — blocked
        r = self.client.post(
            f"/machine-room/workflows/{wid}/complete",
            data=json.dumps({"action": "mark_ready", "checks": list(self.wf.COMPLETE_CHECKS)}),
            headers=self._csrf_headers(),
        )
        self.assertEqual(r.status_code, 400)

        # Transcode
        r = self.client.post(
            f"/machine-room/workflows/{wid}/transcode",
            data=json.dumps(
                {
                    "action": "start",
                    "proxy_destination_id": self.inhouse.id,
                    "proxy_preset": "Premiere Editing Proxy",
                    "pre_checks": list(self.wf.TRANSCODE_PRE_CHECKS),
                }
            ),
            headers=self._csrf_headers(),
        )
        body = r.get_json()
        self.assertTrue(body.get("ok"), r.get_data(as_text=True)[:800])
        self.assertFalse(body.get("automation"))

        self.client.post(
            f"/machine-room/workflows/{wid}/transcode",
            data=json.dumps({"action": "finish"}),
            headers=self._csrf_headers(),
        )
        r = self.client.post(
            f"/machine-room/workflows/{wid}/transcode",
            data=json.dumps(
                {
                    "action": "verify",
                    "post_checks": list(self.wf.TRANSCODE_POST_CHECKS),
                }
            ),
            headers=self._csrf_headers(),
        )
        self.assertTrue(r.get_json().get("ok"), r.get_data(as_text=True)[:800])

        r = self.client.post(
            f"/machine-room/workflows/{wid}/complete",
            data=json.dumps(
                {"action": "mark_ready", "checks": list(self.wf.COMPLETE_CHECKS)}
            ),
            headers=self._csrf_headers(),
        )
        data = r.get_json()
        self.assertTrue(data.get("ok"), r.get_data(as_text=True)[:800])
        self.assertEqual(data["workflow"]["status"], "ready")

        # Resume: reopen page with workflow_id
        page = self.client.get(f"/machine-room/tasks/progress?workflow_id={wid}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Shooting day ready", page.get_data(as_text=True))

    def test_critical_issue_blocks(self):
        wid = self._create_workflow()
        r = self.client.post(
            f"/machine-room/workflows/{wid}/issues",
            data=json.dumps(
                {
                    "category": "backup_failed",
                    "description": "Copy aborted mid-way",
                    "is_critical": True,
                }
            ),
            headers=self._csrf_headers(),
        )
        self.assertTrue(r.get_json().get("ok"))
        w = db.session.get(self.models.MachineRoomMediaWorkflow, wid)
        self.assertTrue(w.blocked_by_issue)
        self.assertEqual(w.status, "problem")

        # Operator cannot resolve
        issue_id = r.get_json()["issue_id"]
        r2 = self.client.post(
            f"/machine-room/workflows/{wid}/issues/{issue_id}/resolve",
            data=json.dumps({"resolution_note": "fixed"}),
            headers=self._csrf_headers(),
        )
        self.assertEqual(r2.status_code, 403)

        # Supervisor can
        self._login_admin()
        r3 = self.client.post(
            f"/machine-room/workflows/{wid}/issues/{issue_id}/resolve",
            data=json.dumps({"resolution_note": "Re-copied successfully"}),
            headers=self._csrf_headers(),
        )
        self.assertTrue(r3.get_json().get("ok"), r3.get_data(as_text=True)[:800])

    def test_same_source_dest_rejected(self):
        wid = self._create_workflow()
        self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "set_connected", "connected": True}),
            headers=self._csrf_headers(),
        )
        self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps(
                {
                    "action": "continue",
                    "project_id": self.project.id,
                    "shooting_day_id": self.day.id,
                    "shuttle_volume_id": self.shuttle.id,
                }
            ),
            headers=self._csrf_headers(),
        )
        # Force same id by using shuttle as backup — role check should fail first
        r = self.client.post(
            f"/machine-room/workflows/{wid}/backup",
            data=json.dumps(
                {"action": "start", "backup_destination_id": self.shuttle.id}
            ),
            headers=self._csrf_headers(),
        )
        self.assertEqual(r.status_code, 400)

    def test_stage_volumes_prefer_project_links(self):
        import machine_room_dashboard_support as mr_dash

        Link = mr_dash.register_machine_room_dashboard_models(
            db, lambda: __import__("datetime").datetime.utcnow()
        ).StorageVolumeProjectLink
        other_backup = self.StorageVolume(
            name="Other Backup",
            display_name="Other Backup",
            mount_path="/Volumes/OtherBackup",
            storage_role="project_backup",
        )
        db.session.add(other_backup)
        db.session.flush()
        db.session.add(Link(volume_id=self.backup.id, project_id=self.project.id))
        db.session.commit()

        wid = self._create_workflow()
        detail = self.client.get(f"/machine-room/workflows/{wid}").get_json()["workflow"]
        backup_group = detail["stage_volumes"]["backup"]
        self.assertTrue(backup_group["linked_only"])
        self.assertEqual([v["id"] for v in backup_group["volumes"]], [self.backup.id])
        self.assertTrue(backup_group["volumes"][0]["linked"])

        # Receive only ever lists volumes linked to the project
        receive_group = detail["stage_volumes"]["receive"]
        self.assertTrue(receive_group["strict"])
        self.assertEqual([v["id"] for v in receive_group["volumes"]], [self.shuttle.id])

        # Transcode has no linked In-house volume: falls back to all of that role
        transcode_group = detail["stage_volumes"]["transcode"]
        self.assertFalse(transcode_group["linked_only"])
        self.assertIn(self.inhouse.id, [v["id"] for v in transcode_group["volumes"]])

    def test_receive_rejects_shuttle_not_linked_to_project(self):
        stray = self.StorageVolume(
            name="Stray", display_name="Stray SSD", mount_path="/Volumes/Stray", storage_role="transfer"
        )
        db.session.add(stray)
        db.session.commit()
        wid = self._create_workflow()
        detail = self.client.get(f"/machine-room/workflows/{wid}").get_json()["workflow"]
        self.assertNotIn(stray.id, [v["id"] for v in detail["stage_volumes"]["receive"]["volumes"]])

        r = self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "save", "shuttle_volume_id": stray.id}),
            headers=self._csrf_headers(),
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("not linked", r.get_json()["error"])

        # A volume chosen earlier that is no longer linked blocks Continue
        w = db.session.get(self.models.MachineRoomMediaWorkflow, wid)
        w.shuttle_volume_id = stray.id
        db.session.commit()
        r = self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue"}),
            headers=self._csrf_headers(),
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("not linked", r.get_json()["error"])

    def _add_day(self, name, iso_date):
        from datetime import date

        d = self.M["ShootingDay"](
            project_id=self.project.id,
            unit_number=1,
            day_name=name,
            shooting_date=date.fromisoformat(iso_date),
        )
        db.session.add(d)
        db.session.commit()
        return d

    def test_multi_day_workflow_and_overlap_conflict(self):
        day23 = self._add_day("23", "2026-10-16")
        day25 = self._add_day("25", "2026-10-18")
        self._login_mr()
        r = self.client.post(
            "/machine-room/workflows",
            data=json.dumps(
                {
                    "project_id": self.project.id,
                    "shooting_day_ids": [self.day.id, day23.id],
                }
            ),
            headers=self._csrf_headers(),
        )
        body = r.get_json()
        self.assertTrue(body.get("ok"), r.get_data(as_text=True)[:800])
        self.assertTrue(body.get("created"))
        wid = body["workflow_id"]
        w = db.session.get(self.models.MachineRoomMediaWorkflow, wid)
        self.assertEqual(w.day_ids, [day23.id, self.day.id])
        self.assertEqual(w.shooting_day_id, day23.id)
        self.assertIn("Day 23 + Day 24", self.wf.format_days_label(w.days))

        # Same set again reopens; a single day from the set also reopens
        again = self.client.post(
            "/machine-room/workflows",
            data=json.dumps({"project_id": self.project.id, "shooting_day_id": self.day.id}),
            headers=self._csrf_headers(),
        ).get_json()
        self.assertFalse(again.get("created"))
        self.assertEqual(again["workflow_id"], wid)

        # Overlapping set (one taken + one free) is refused, nothing split
        clash = self.client.post(
            "/machine-room/workflows",
            data=json.dumps(
                {"project_id": self.project.id, "shooting_day_ids": [self.day.id, day25.id]}
            ),
            headers=self._csrf_headers(),
        )
        self.assertEqual(clash.status_code, 409)
        self.assertEqual(clash.get_json()["conflict_workflow_id"], wid)
        self.assertIsNone(self.wf.find_workflow_for_day(self.models, self.project.id, day25.id))

    def test_receive_can_add_and_remove_days(self):
        day25 = self._add_day("25", "2026-10-18")
        wid = self._create_workflow()
        url = f"/machine-room/workflows/{wid}/receive"
        r = self.client.post(
            url,
            data=json.dumps({"action": "save", "shooting_day_ids": [self.day.id, day25.id]}),
            headers=self._csrf_headers(),
        )
        self.assertTrue(r.get_json().get("ok"), r.get_data(as_text=True)[:800])
        self.assertEqual(r.get_json()["workflow"]["day_count"], 2)

        empty = self.client.post(
            url,
            data=json.dumps({"action": "save", "shooting_day_ids": []}),
            headers=self._csrf_headers(),
        )
        self.assertEqual(empty.status_code, 400)

        r = self.client.post(
            url,
            data=json.dumps({"action": "save", "shooting_day_ids": [day25.id]}),
            headers=self._csrf_headers(),
        )
        w = db.session.get(self.models.MachineRoomMediaWorkflow, wid)
        self.assertEqual(w.day_ids, [day25.id])
        self.assertEqual(w.shooting_day_id, day25.id)

    def test_receive_checklist_is_optional_but_reported(self):
        wid = self._create_workflow()
        r = self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps(
                {
                    "action": "continue",
                    "shooting_day_ids": [self.day.id],
                    "shuttle_volume_id": self.shuttle.id,
                    "checks": ["correct_project"],
                }
            ),
            headers=self._csrf_headers(),
        )
        body = r.get_json()
        self.assertTrue(body.get("ok"), r.get_data(as_text=True)[:800])
        self.assertEqual(body["workflow"]["current_stage"], "backup")
        self.assertTrue(body["workflow"]["receive_checks_summary"].startswith("1 of 4 checks ticked"))
        messages = [e["message"] for e in body["workflow"]["events"]]
        self.assertTrue(any("1 of 4 checks ticked" in m for m in messages))

    def test_backup_checklist_is_optional_but_reported(self):
        wid = self._create_workflow()
        h = self._csrf_headers()
        self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps(
                {"action": "continue", "shooting_day_ids": [self.day.id], "shuttle_volume_id": self.shuttle.id}
            ),
            headers=h,
        )
        self.client.post(
            f"/machine-room/workflows/{wid}/backup",
            data=json.dumps({"action": "start", "backup_destination_id": self.backup.id}),
            headers=h,
        )
        self.client.post(
            f"/machine-room/workflows/{wid}/backup",
            data=json.dumps({"action": "finish_copy"}),
            headers=h,
        )
        r = self.client.post(
            f"/machine-room/workflows/{wid}/backup",
            data=json.dumps({"action": "verify", "checks": ["copy_finished", "camera_folders_copied"]}),
            headers=h,
        )
        body = r.get_json()
        self.assertTrue(body.get("ok"), r.get_data(as_text=True)[:800])
        self.assertEqual(body["workflow"]["current_stage"], "transcode")
        self.assertTrue(body["workflow"]["backup_checks_summary"].startswith("2 of 6 checks ticked"))
        messages = [e["message"] for e in body["workflow"]["events"]]
        self.assertTrue(any("2 of 6 checks ticked" in m for m in messages))

    def test_end_blocks_actions_and_resume_restores(self):
        wid = self._create_workflow()
        h = self._csrf_headers()
        no_reason = self.client.post(f"/machine-room/workflows/{wid}/end", data=json.dumps({}), headers=h)
        self.assertEqual(no_reason.status_code, 400)

        r = self.client.post(
            f"/machine-room/workflows/{wid}/end",
            data=json.dumps({"reason": "Backup only for this day"}),
            headers=h,
        )
        body = r.get_json()
        self.assertTrue(body.get("ok"), r.get_data(as_text=True)[:800])
        self.assertEqual(body["workflow"]["status"], "ended")
        self.assertEqual(body["workflow"]["media_prep"], "ENDED AT RECEIVE")
        self.assertEqual(
            [s["state"] for s in body["workflow"]["stages"]],
            ["ended", "skipped", "skipped", "skipped"],
        )

        blocked = self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue", "shuttle_volume_id": self.shuttle.id}),
            headers=h,
        )
        self.assertEqual(blocked.status_code, 409)

        r = self.client.post(f"/machine-room/workflows/{wid}/resume", data=json.dumps({}), headers=h)
        self.assertEqual(r.get_json()["workflow"]["status"], "pending")
        r = self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue", "shuttle_volume_id": self.shuttle.id}),
            headers=h,
        )
        self.assertTrue(r.get_json().get("ok"), r.get_data(as_text=True)[:800])

    def test_delete_requires_safe_delete_and_frees_days(self):
        wid = self._create_workflow()
        h = self._csrf_headers()
        bare = self.client.post(f"/machine-room/workflows/{wid}/remove", data=json.dumps({}), headers=h)
        self.assertEqual(bare.status_code, 400)
        self.assertEqual(bare.get_json()["error"], "safe_delete_required")

        ch = self.client.post(
            "/safe-delete/challenge",
            json={"entity_type": "mr_media_workflow", "entity_id": wid},
        )
        self.assertEqual(ch.status_code, 200, ch.get_data(as_text=True))
        ch_body = ch.get_json()
        r = self.client.post(
            f"/machine-room/workflows/{wid}/remove",
            json={"challenge_token": ch_body["challenge_token"], "entered_code": ch_body["display_code"]},
        )
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:800])
        self.assertIsNone(db.session.get(self.models.MachineRoomMediaWorkflow, wid))
        self.assertIsNone(self.wf.find_workflow_for_day(self.models, self.project.id, self.day.id))

        again = self.client.post(
            "/machine-room/workflows",
            data=json.dumps({"project_id": self.project.id, "shooting_day_id": self.day.id}),
            headers=h,
        ).get_json()
        self.assertTrue(again.get("created"))

    def test_receive_requires_shuttle_volume(self):
        wid = self._create_workflow()
        r = self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue"}),
            headers=self._csrf_headers(),
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("Transfer / Shuttle", r.get_json().get("error", ""))

    def test_add_missing_shooting_day(self):
        self._login_mr()
        payload = {
            "project_id": self.project.id,
            "unit_number": 1,
            "day_name": "25",
            "shooting_date": "2026-10-18",
        }
        r = self.client.post(
            "/machine-room/workflows/shooting-days",
            data=json.dumps(payload),
            headers=self._csrf_headers(),
        )
        data = r.get_json()
        self.assertTrue(data.get("ok"), r.get_data(as_text=True)[:800])
        self.assertTrue(data.get("created"))
        new_id = data["day"]["id"]
        day = db.session.get(self.M["ShootingDay"], new_id)
        self.assertEqual(day.project_id, self.project.id)
        self.assertEqual(day.day_name, "25")

        again = self.client.post(
            "/machine-room/workflows/shooting-days",
            data=json.dumps(payload),
            headers=self._csrf_headers(),
        ).get_json()
        self.assertFalse(again.get("created"))
        self.assertEqual(again["day"]["id"], new_id)

        bad = self.client.post(
            "/machine-room/workflows/shooting-days",
            data=json.dumps({**payload, "day_name": "26", "shooting_date": "not-a-date"}),
            headers=self._csrf_headers(),
        )
        self.assertEqual(bad.status_code, 400)

    def test_operator_denied_supervisor_reopen(self):
        wid = self._create_workflow()
        r = self.client.post(
            f"/machine-room/workflows/{wid}/reopen",
            data=json.dumps({"reason": "redo", "stage": "receive"}),
            headers=self._csrf_headers(),
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
