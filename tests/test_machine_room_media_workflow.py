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
        db.session.query(self.M["Notification"]).delete()
        db.session.query(self.M["ProjectMember"]).delete()
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
        r = self.client.get("/machine-room/workflow")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:500])
        body = r.get_data(as_text=True)
        self.assertIn("Daily Media Processing", body)
        self.assertIn("Pending", body)

        tasks = self.client.get("/machine-room/tasks/progress").get_data(as_text=True)
        self.assertIn("Machine Room Tasks", tasks)
        self.assertNotIn("data-mr-wf-root", tasks)

        old_link = self.client.get("/machine-room/tasks/progress?workflow_id=5")
        self.assertEqual(old_link.status_code, 302)
        self.assertTrue(old_link.headers["Location"].endswith("/machine-room/workflow?workflow_id=5"))

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

    def test_status_change_pushes_to_production_page(self):
        from unittest import mock

        from app import socketio

        with mock.patch.object(socketio, "emit") as emit:
            wid = self._create_workflow()
        pushed = [c for c in emit.call_args_list if c.args and c.args[0] == "mr_workflow_changed"]
        self.assertTrue(pushed)
        self.assertEqual(pushed[-1].args[1], {"project_ids": [self.project.id]})
        self.assertEqual(pushed[-1].kwargs.get("room"), "tasks_feed")

        self._login_admin()
        r = self.client.get(f"/projects/{self.project.id}/production/workflow-statuses")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:500])
        day = r.get_json()["days"][str(self.day.id)]
        w = db.session.get(self.models.MachineRoomMediaWorkflow, wid)
        self.assertEqual(day, {"label": w.media_prep_label(), "status": w.status})

        outsider = self.M["Account"](email="outsider-wf@test.local", password_hash="x", role="user")
        db.session.add(outsider)
        db.session.commit()
        with self.client.session_transaction() as sess:
            sess["account_id"] = outsider.id
        denied = self.client.get(f"/projects/{self.project.id}/production/workflow-statuses")
        self.assertIn(denied.status_code, (302, 403))

    def test_start_with_shuttle_records_material_received(self):
        self._login_mr()
        h = self._csrf_headers()
        other = self.StorageVolume(
            name="Loose", display_name="Loose SSD", mount_path="/Volumes/Loose",
            storage_role="transfer", mounted_status="mounted", is_mounted=True,
        )
        db.session.add(other)
        db.session.commit()
        bad = self.client.post(
            "/machine-room/workflows",
            data=json.dumps({
                "project_id": self.project.id,
                "shooting_day_id": self.day.id,
                "shuttle_volume_id": other.id,
            }),
            headers=h,
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("not linked", bad.get_json()["error"])
        self.assertEqual(self.models.MachineRoomMediaWorkflow.query.count(), 0)

        r = self.client.post(
            "/machine-room/workflows",
            data=json.dumps({
                "project_id": self.project.id,
                "shooting_day_id": self.day.id,
                "shuttle_volume_id": self.shuttle.id,
                "receive_notes": "Card A001 to A004",
            }),
            headers=h,
        ).get_json()
        self.assertTrue(r.get("ok"), r)
        w = db.session.get(self.models.MachineRoomMediaWorkflow, r["workflow_id"])
        self.assertEqual(w.current_stage, self.wf.STAGE_BACKUP)
        self.assertIsNotNone(w.received_at)
        self.assertEqual(w.shuttle_volume_id, self.shuttle.id)
        self.assertEqual(w.receive_notes, "Card A001 to A004")
        events = [
            e.event_type
            for e in self.models.MachineRoomMediaWorkflowEvent.query.filter_by(workflow_id=w.id).all()
        ]
        self.assertIn("material_received", events)

    def test_find_and_add_connected_shuttle_drive(self):
        from unittest.mock import patch

        self._login_mr()
        h = self._csrf_headers()
        loose = self.StorageVolume(
            name="Card Reader", display_name="Card Reader", mount_path="/Volumes/CardReader",
            storage_role="transfer", mounted_status="mounted", is_mounted=True,
        )
        db.session.add(loose)
        db.session.commit()
        new_row = {
            "name": "SANDISK_A", "display_name": "SANDISK_A",
            "mount_path": "/Volumes/SANDISK_A", "expected_mount_path": "/Volumes/SANDISK_A",
            "filesystem_source": "/dev/disk9s1", "filesystem_type": "exfat",
            "drive_type": "external_ssd", "connection_type": "usb",
            "capacity_tb": 2.0, "used_tb": 0.5, "free_tb": 1.5, "free_percentage": 75.0,
            "capacity_bytes": 2.0, "used_bytes": 0.5, "free_bytes": 1.5,
            "volume_uuid": "UUID-SANDISK-A",
            "already_added": False, "existing_volume_id": None, "existing_volume_name": "", "debug": {},
        }
        known_row = {**new_row, "name": "Card Reader", "display_name": "Card Reader",
                     "mount_path": "/Volumes/CardReader", "volume_uuid": "UUID-CR",
                     "already_added": True, "existing_volume_id": loose.id}
        with patch("machine_room_storage_scan.discover_mounted_volumes", return_value=[new_row, known_row]):
            found = self.client.get(
                f"/machine-room/workflows/connected-drives?project_id={self.project.id}"
            ).get_json()
            self.assertEqual([d["mount_path"] for d in found["new"]], ["/Volumes/SANDISK_A"])
            self.assertEqual([d["volume_id"] for d in found["linkable"]], [loose.id])

            added = self.client.post(
                "/machine-room/workflows/connected-drives/add",
                data=json.dumps({"project_id": self.project.id, "mount_path": "/Volumes/SANDISK_A"}),
                headers=h,
            ).get_json()
        self.assertTrue(added.get("ok"), added)
        vol = db.session.get(self.StorageVolume, added["volume"]["id"])
        self.assertEqual(vol.storage_role, "transfer")
        self.assertEqual(vol.mount_path, "/Volumes/SANDISK_A")
        linked = self.client.post(
            "/machine-room/workflows/connected-drives/add",
            data=json.dumps({"project_id": self.project.id, "volume_id": loose.id}),
            headers=h,
        ).get_json()
        self.assertTrue(linked.get("ok"), linked)
        links = {
            l.volume_id for l in self.Link.query.filter_by(project_id=self.project.id).all()
        }
        self.assertTrue({vol.id, loose.id} <= links)

    def test_transcoding_finish_can_go_straight_to_ready(self):
        self._login_mr()
        h = self._csrf_headers()
        wid = self.client.post(
            "/machine-room/workflows",
            data=json.dumps({
                "project_id": self.project.id,
                "shooting_day_id": self.day.id,
                "shuttle_volume_id": self.shuttle.id,
            }),
            headers=h,
        ).get_json()["workflow_id"]
        backup = f"/machine-room/workflows/{wid}/backup"
        transcode = f"/machine-room/workflows/{wid}/transcode"
        steps = [
            (backup, {"action": "start", "backup_destination_id": self.backup.id, "backup_estimated_minutes": 30}),
            (backup, {"action": "finish_copy", "checks": []}),
            (backup, {"action": "verify", "checks": [], "verification_method": "operator_confirmed"}),
            (transcode, {"action": "start", "proxy_destination_id": self.inhouse.id, "transcode_estimated_minutes": 20}),
            (transcode, {"action": "finish", "post_checks": []}),
            (transcode, {"action": "verify", "post_checks": []}),
            (f"/machine-room/workflows/{wid}/complete", {"action": "mark_ready", "checks": []}),
        ]
        for url, body in steps:
            res = self.client.post(url, data=json.dumps(body), headers=h).get_json()
            self.assertTrue(res.get("ok"), (body, res))
        self.assertEqual(res["workflow"]["status"], "ready")

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
                {"action": "start", "backup_destination_id": self.backup.id, "backup_estimated_minutes": 90}
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
                    "transcode_estimated_minutes": 45,
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
            data=json.dumps({"action": "mark_ready"}),
            headers=self._csrf_headers(),
        )
        data = r.get_json()
        self.assertTrue(data.get("ok"), r.get_data(as_text=True)[:800])
        self.assertEqual(data["workflow"]["status"], "ready")

        # Resume: reopen page with workflow_id
        page = self.client.get(f"/machine-room/workflow?workflow_id={wid}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Shooting day ready", page.get_data(as_text=True))

        # Ready workflows move from the card grid to the Ready for editing list
        bundle = app.extensions["mr_media_workflow_bundle"]
        with app.test_request_context("/machine-room/workflow"):
            ctx = bundle(self.mr_acc)
        self.assertEqual([r["id"] for r in ctx["mr_wf_ready_rows"]], [wid])
        self.assertNotIn(wid, [c["id"] for c in ctx["mr_wf_cards"]])
        self.assertEqual(ctx["mr_wf_ready_rows"][0]["completed_by"], "MR Operator")
        list_page = self.client.get("/machine-room/workflow").get_data(as_text=True)
        self.assertIn("mr-mc__ready-table", list_page)

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
            data=json.dumps({"action": "start", "backup_destination_id": self.backup.id, "backup_estimated_minutes": 90}),
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

        # Proxy preset and pre-transcode checklist are optional; only the destination is required.
        r = self.client.post(
            f"/machine-room/workflows/{wid}/transcode",
            data=json.dumps({"action": "start"}),
            headers=h,
        )
        if self.inhouse.id != body["workflow"].get("proxy_destination_id"):
            self.assertEqual(r.status_code, 400)
            self.assertIn("In-house Storage", r.get_json()["error"])
        r = self.client.post(
            f"/machine-room/workflows/{wid}/transcode",
            data=json.dumps(
                {"action": "start", "proxy_destination_id": self.inhouse.id, "transcode_estimated_minutes": 20}
            ),
            headers=h,
        )
        started = r.get_json()
        self.assertTrue(started.get("ok"), r.get_data(as_text=True)[:800])
        self.assertTrue(started["workflow"]["transcode_pre_checks_summary"].startswith("0 of 6"))
        messages = [e["message"] for e in started["workflow"]["events"]]
        self.assertTrue(any("preset: not recorded" in m for m in messages))

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

    def test_each_step_notifies_project_team(self):
        editor_acc = self.M["Account"](email="editor-wf@test.local", password_hash="x", role="user")
        db.session.add(editor_acc)
        db.session.flush()
        editor = self.M["User"](name="Editor", email="editor-wf@test.local", account_id=editor_acc.id)
        outsider = self.M["User"](name="Outsider", email="outsider-wf@test.local")
        db.session.add_all([editor, outsider])
        db.session.flush()
        db.session.add(self.M["ProjectMember"](project_id=self.project.id, user_id=editor.id))
        db.session.add(self.M["ProjectMember"](project_id=self.project.id, user_id=self.mr_user.id))
        db.session.commit()

        wid = self._create_workflow()
        h = self._csrf_headers()
        self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue", "shuttle_volume_id": self.shuttle.id}),
            headers=h,
        )
        self.client.post(
            f"/machine-room/workflows/{wid}/backup",
            data=json.dumps({"action": "start", "backup_destination_id": self.backup.id, "backup_estimated_minutes": 90}),
            headers=h,
        )

        backup_url = f"/machine-room/workflows/{wid}/backup"
        self.client.post(f"{backup_url}/estimate", data=json.dumps({"remaining_minutes": 40}), headers=h)
        self.client.post(backup_url, data=json.dumps({"action": "finish_copy"}), headers=h)

        Notification = self.M["Notification"]
        rows = (
            Notification.query.filter_by(user_id=editor.id, project_id=self.project.id)
            .order_by(Notification.id)
            .all()
        )
        titles = [n.title for n in rows]
        self.assertTrue(any(t.endswith(": Workflow started") for t in titles), titles)
        self.assertTrue(any(t.endswith(": Material received") for t in titles), titles)
        self.assertTrue(all(t.startswith("Ras Al Afaa · ") for t in titles), titles)

        w = db.session.get(self.models.MachineRoomMediaWorkflow, wid)
        db.session.refresh(w)
        live = {n.title.rsplit(": ", 1)[-1] for n in rows if n.entity_type == "task" and n.entity_id == w.backup_copy_task_id}
        self.assertEqual(live, {"Backup started", "Backup time left updated", "Backup copy finished"})
        task = db.session.get(self.M["Task"], w.backup_copy_task_id)
        self.assertEqual(task.status, "done")
        self.assertEqual(task.completed_at, w.backup_finished_at)
        self.assertEqual(Notification.query.filter_by(user_id=outsider.id).count(), 0)

        operator_titles = {
            n.title.rsplit(": ", 1)[-1]
            for n in Notification.query.filter_by(user_id=self.mr_user.id, project_id=self.project.id).all()
        }
        self.assertTrue(
            {"Workflow started", "Material received", "Backup started", "Backup copy finished"} <= operator_titles,
            operator_titles,
        )

    def test_backup_start_requires_estimate(self):
        wid = self._create_workflow()
        h = self._csrf_headers()
        self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue", "shuttle_volume_id": self.shuttle.id}),
            headers=h,
        )
        url = f"/machine-room/workflows/{wid}/backup"
        for bad in (None, 0, "abc", 49 * 60 + 1):
            r = self.client.post(
                url,
                data=json.dumps(
                    {"action": "start", "backup_destination_id": self.backup.id, "backup_estimated_minutes": bad}
                ),
                headers=h,
            )
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn("estimated copy time", r.get_json()["error"])

        saved = self.client.post(
            url, data=json.dumps({"action": "save", "backup_estimated_minutes": 95}), headers=h
        ).get_json()
        self.assertTrue(saved["workflow"]["gates"]["backup_start"]["ok"])
        self.assertEqual(saved["workflow"]["backup_estimate_hhmm"], "01:35")

        started = self.client.post(url, data=json.dumps({"action": "start"}), headers=h).get_json()
        self.assertTrue(started.get("ok"))
        self.assertTrue(started["workflow"]["backup_expected_finish"])
        w = db.session.get(self.models.MachineRoomMediaWorkflow, wid)
        task = db.session.get(self.M["Task"], w.backup_copy_task_id)
        self.assertEqual(task.copy_estimated_minutes, 95)
        messages = [e["message"] for e in started["workflow"]["events"]]
        self.assertTrue(any("estimated 01:35" in m for m in messages))

    def test_backup_start_records_copy_details(self):
        wid = self._create_workflow()
        h = self._csrf_headers()
        self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue", "shuttle_volume_id": self.shuttle.id}),
            headers=h,
        )
        url = f"/machine-room/workflows/{wid}/backup"
        saved = self.client.post(
            url, data=json.dumps({"action": "save", "backup_destination_id": self.backup.id}), headers=h
        ).get_json()
        self.assertTrue(saved["workflow"]["gates"]["backup_start"]["ok"])

        base = {"action": "start", "backup_estimated_minutes": 30}
        outside = self.client.post(
            url, data=json.dumps({**base, "destination_path": "/Volumes/Other/Day24"}), headers=h
        )
        self.assertEqual(outside.status_code, 400)
        self.assertIn("inside the Projects Backup volume", outside.get_json()["error"])

        no_note = self.client.post(url, data=json.dumps({**base, "make_critical": True}), headers=h)
        self.assertEqual(no_note.status_code, 400)

        started = self.client.post(
            url,
            data=json.dumps(
                {
                    **base,
                    "destination_path": "/Volumes/GRaid/RasAlAfaa/Day24",
                    "video_size_tb": "1.5",
                    "audio_size_gb": "20",
                    "checksum_method": "xxhash",
                    "checksum_status": "pending",
                    "notes": "Card A012 corrupted",
                    "make_critical": True,
                }
            ),
            headers=h,
        ).get_json()
        self.assertTrue(started.get("ok"))
        copy = started["workflow"]["backup_copy"]
        self.assertEqual(copy["destination_path"], "/Volumes/GRaid/RasAlAfaa/Day24")
        self.assertEqual(copy["video_size_tb"], 1.5)
        self.assertEqual(copy["audio_size_gb"], 20)
        self.assertEqual(copy["checksum_method"], "Xxhash")
        self.assertTrue(copy["critical"])
        from sqlalchemy import text

        notes = db.session.execute(
            text("SELECT body FROM shooting_day_critical_notes WHERE shooting_day_id = :d"),
            {"d": self.day.id},
        ).scalars().all()
        self.assertIn("Card A012 corrupted", notes)
        messages = [e["message"] for e in started["workflow"]["events"]]
        self.assertTrue(any("Path: /Volumes/GRaid/RasAlAfaa/Day24" in m for m in messages))

    def test_backup_destination_can_be_cleared_until_started(self):
        wid = self._create_workflow()
        h = self._csrf_headers()
        self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue", "shuttle_volume_id": self.shuttle.id}),
            headers=h,
        )
        url = f"/machine-room/workflows/{wid}/backup"
        self.client.post(url, data=json.dumps({"action": "save", "backup_destination_id": self.backup.id}), headers=h)
        cleared = self.client.post(
            url, data=json.dumps({"action": "save", "backup_destination_id": None}), headers=h
        ).get_json()
        self.assertIsNone(cleared["workflow"]["backup_destination_id"])
        self.assertFalse(cleared["workflow"]["gates"]["backup_start"]["ok"])

        self.client.post(
            url,
            data=json.dumps(
                {"action": "start", "backup_destination_id": self.backup.id, "backup_estimated_minutes": 30}
            ),
            headers=h,
        )
        locked = self.client.post(
            url, data=json.dumps({"action": "save", "backup_destination_id": None}), headers=h
        )
        self.assertEqual(locked.status_code, 400)
        w = db.session.get(self.models.MachineRoomMediaWorkflow, wid)
        db.session.refresh(w)
        self.assertEqual(w.backup_destination_id, self.backup.id)

    def test_backup_time_left_can_be_edited_while_running(self):
        wid = self._create_workflow()
        h = self._csrf_headers()
        self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue", "shuttle_volume_id": self.shuttle.id}),
            headers=h,
        )
        url = f"/machine-room/workflows/{wid}/backup"
        self.client.post(
            url,
            data=json.dumps(
                {"action": "start", "backup_destination_id": self.backup.id, "backup_estimated_minutes": 30}
            ),
            headers=h,
        )
        r = self.client.post(f"{url}/estimate", data=json.dumps({"remaining_minutes": 45}), headers=h)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(body["estimated_minutes"], 45)
        self.assertTrue(body["started_ms"])
        w = db.session.get(self.models.MachineRoomMediaWorkflow, wid)
        db.session.refresh(w)
        self.assertEqual(w.backup_estimated_minutes, body["estimated_minutes"])
        task = db.session.get(self.M["Task"], w.backup_copy_task_id)
        self.assertEqual(task.copy_estimated_minutes, body["estimated_minutes"])

        bad = self.client.post(f"{url}/estimate", data=json.dumps({"remaining_minutes": 0}), headers=h)
        self.assertEqual(bad.status_code, 400)
        self.client.post(url, data=json.dumps({"action": "finish_copy"}), headers=h)
        done = self.client.post(f"{url}/estimate", data=json.dumps({"remaining_minutes": 10}), headers=h)
        self.assertEqual(done.status_code, 400)

    def test_transcode_start_dialog_eta_and_live_task(self):
        editor = self.M["User"](name="Editor T", email="editor-t@test.local")
        db.session.add(editor)
        db.session.flush()
        db.session.add(self.M["ProjectMember"](project_id=self.project.id, user_id=editor.id))
        db.session.commit()
        wid = self._create_workflow()
        h = self._csrf_headers()
        self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue", "shuttle_volume_id": self.shuttle.id}),
            headers=h,
        )
        backup_url = f"/machine-room/workflows/{wid}/backup"
        self.client.post(
            backup_url,
            data=json.dumps(
                {"action": "start", "backup_destination_id": self.backup.id, "backup_estimated_minutes": 30}
            ),
            headers=h,
        )
        self.client.post(backup_url, data=json.dumps({"action": "finish_copy"}), headers=h)
        self.client.post(
            backup_url,
            data=json.dumps({"action": "verify", "verification_method": "operator_confirmed"}),
            headers=h,
        )
        url = f"/machine-room/workflows/{wid}/transcode"
        saved = self.client.post(
            url, data=json.dumps({"action": "save", "proxy_destination_id": self.inhouse.id}), headers=h
        ).get_json()
        self.assertTrue(saved["workflow"]["gates"]["transcode_start"]["ok"])

        no_eta = self.client.post(url, data=json.dumps({"action": "start"}), headers=h)
        self.assertEqual(no_eta.status_code, 400)
        self.assertIn("estimated transcoding time", no_eta.get_json()["error"])
        outside = self.client.post(
            url,
            data=json.dumps(
                {"action": "start", "transcode_estimated_minutes": 25, "destination_path": "/Volumes/Other/x"}
            ),
            headers=h,
        )
        self.assertEqual(outside.status_code, 400)
        self.assertIn("In-house Storage", outside.get_json()["error"])

        started = self.client.post(
            url,
            data=json.dumps(
                {
                    "action": "start",
                    "transcode_estimated_minutes": 25,
                    "destination_path": "/Volumes/Nucleus1/Proxies/Day24",
                    "proxy_preset": "Premiere Editing Proxy",
                    "notes": "Use LUT A",
                }
            ),
            headers=h,
        ).get_json()
        self.assertTrue(started.get("ok"))
        detail = started["workflow"]
        self.assertEqual(detail["transcode_estimated_minutes"], 25)
        self.assertEqual(detail["proxy_destination_path"], "/Volumes/Nucleus1/Proxies/Day24")
        self.assertEqual(detail["transcode_notes"], "Use LUT A")
        task = db.session.get(self.M["Task"], detail["convert_task_id"])
        self.assertEqual(task.copy_estimated_minutes, 25)

        edited = self.client.post(f"{url}/estimate", data=json.dumps({"remaining_minutes": 50}), headers=h).get_json()
        self.assertTrue(edited["ok"])
        db.session.refresh(task)
        self.assertEqual(task.copy_estimated_minutes, edited["estimated_minutes"])

        self.client.post(url, data=json.dumps({"action": "finish"}), headers=h)
        db.session.refresh(task)
        self.assertEqual(task.status, "done")
        verified = self.client.post(url, data=json.dumps({"action": "verify"}), headers=h).get_json()
        self.assertTrue(verified.get("ok"), verified)
        self.assertTrue(verified["workflow"]["transcode_verified_at"])
        Notification = self.M["Notification"]
        linked = {
            n.title.rsplit(": ", 1)[-1]
            for n in Notification.query.filter_by(user_id=editor.id, entity_type="task", entity_id=task.id).all()
        }
        self.assertEqual(linked, {"Transcoding started", "Transcoding time left updated", "Transcoding finished"})

    def test_backup_pause_and_continue_excludes_paused_time(self):
        from datetime import timedelta

        wid = self._create_workflow()
        h = self._csrf_headers()
        self.client.post(
            f"/machine-room/workflows/{wid}/receive",
            data=json.dumps({"action": "continue", "shuttle_volume_id": self.shuttle.id}),
            headers=h,
        )
        url = f"/machine-room/workflows/{wid}/backup"
        self.client.post(
            url,
            data=json.dumps(
                {"action": "start", "backup_destination_id": self.backup.id, "backup_estimated_minutes": 60}
            ),
            headers=h,
        )
        not_paused = self.client.post(url, data=json.dumps({"action": "resume"}), headers=h)
        self.assertEqual(not_paused.status_code, 400)

        paused = self.client.post(url, data=json.dumps({"action": "pause"}), headers=h).get_json()
        self.assertTrue(paused["workflow"]["backup_paused"])
        twice = self.client.post(url, data=json.dumps({"action": "pause"}), headers=h)
        self.assertEqual(twice.status_code, 400)

        w = db.session.get(self.models.MachineRoomMediaWorkflow, wid)
        db.session.refresh(w)
        task = db.session.get(self.M["Task"], w.backup_copy_task_id)
        original_start = w.backup_started_at
        w.backup_paused_at = w.backup_paused_at - timedelta(minutes=10)
        db.session.commit()

        resumed = self.client.post(url, data=json.dumps({"action": "resume"}), headers=h).get_json()
        self.assertFalse(resumed["workflow"]["backup_paused"])
        db.session.refresh(w)
        db.session.refresh(task)
        self.assertGreaterEqual(w.backup_paused_seconds, 600)
        self.assertEqual(w.backup_started_at, original_start)
        self.assertEqual(task.copy_started_at, original_start + timedelta(seconds=w.backup_paused_seconds))
        messages = [e["message"] for e in resumed["workflow"]["events"]]
        self.assertTrue(any("Backup paused" in m for m in messages))
        self.assertTrue(any("Backup continued" in m for m in messages))

        self.client.post(url, data=json.dumps({"action": "pause"}), headers=h)
        self.client.post(url, data=json.dumps({"action": "finish_copy"}), headers=h)
        db.session.refresh(w)
        db.session.refresh(task)
        self.assertIsNone(w.backup_paused_at)
        self.assertEqual(task.status, "done")

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
        self.assertEqual(day.day_name, "Day 25")

        again = self.client.post(
            "/machine-room/workflows/shooting-days",
            data=json.dumps({**payload, "day_name": "Day 25"}),
            headers=self._csrf_headers(),
        ).get_json()
        self.assertFalse(again.get("created"))
        self.assertEqual(again["day"]["id"], new_id)

        legacy = self.client.post(
            "/machine-room/workflows/shooting-days",
            data=json.dumps({**payload, "day_name": "24"}),
            headers=self._csrf_headers(),
        ).get_json()
        self.assertFalse(legacy.get("created"))
        self.assertEqual(legacy["day"]["id"], self.day.id)

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
