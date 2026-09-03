"""Request Management: create, transitions, auth, filters, notifications."""

from __future__ import annotations

import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_work_requests.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db  # noqa: E402
import work_request_support as wrs  # noqa: E402


class WorkRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        for name in (
            "WorkRequestEvent",
            "WorkRequest",
            "Notification",
            "Task",
            "ProjectMember",
            "Project",
            "User",
            "Account",
        ):
            if name in self.M:
                db.session.query(self.M[name]).delete()
        db.session.commit()

        self.admin = self.M["Account"](
            email="wr-admin@test.local",
            password_hash=generate_password_hash("pw", method="pbkdf2:sha256"),
            role="admin",
            status="active",
            is_active=True,
        )
        self.other_acc = self.M["Account"](
            email="wr-other@test.local",
            password_hash=generate_password_hash("pw", method="pbkdf2:sha256"),
            role="user",
            status="active",
            is_active=True,
        )
        db.session.add_all([self.admin, self.other_acc])
        db.session.flush()
        self.admin_user = self.M["User"](
            name="Admin",
            email="wr-admin@test.local",
            account_id=self.admin.id,
        )
        self.other_user = self.M["User"](
            name="Other",
            email="wr-other@test.local",
            account_id=self.other_acc.id,
        )
        self.project = self.M["Project"](
            name="WR Film",
            project_type="Feature film",
            production_house="Test",
            director="Test",
        )
        self.hidden = self.M["Project"](
            name="Hidden Film",
            project_type="Feature film",
            production_house="Test",
            director="Test",
        )
        db.session.add_all([self.admin_user, self.other_user, self.project, self.hidden])
        db.session.flush()
        db.session.add(
            self.M["ProjectMember"](project_id=self.project.id, user_id=self.admin_user.id)
        )
        db.session.add(
            self.M["ProjectMember"](project_id=self.project.id, user_id=self.other_user.id)
        )
        db.session.commit()

    def tearDown(self):
        self.ctx.pop()

    def _login(self, acc):
        with self.client.session_transaction() as sess:
            sess["account_id"] = acc.id

    def _create(self, **overrides):
        data = {
            "title": "Need a conform",
            "description": "Please conform ep 1",
            "request_type": "color",
            "priority": "high",
            "project_id": str(self.project.id),
            "user_id": str(self.other_user.id),
        }
        data.update(overrides)
        return self.client.post("/requests/new", data=data, follow_redirects=False)

    def test_create_defaults_to_pending(self):
        self._login(self.admin)
        r = self._create()
        self.assertIn(r.status_code, (302, 303))
        row = self.M["WorkRequest"].query.first()
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.requested_by_id, self.admin_user.id)
        self.assertIsNone(row.started_at)
        self.assertIsNone(row.finished_at)
        self.assertIsNone(row.failed_at)
        self.assertEqual(row.title, "Need a conform")
        hist = self.M["WorkRequestEvent"].query.filter_by(request_id=row.id).all()
        self.assertTrue(any(e.event_type == "created" for e in hist))

    def test_create_ignores_client_status(self):
        self._login(self.admin)
        self._create(status="finished", started_at="2020-01-01")
        row = self.M["WorkRequest"].query.first()
        self.assertEqual(row.status, "pending")
        self.assertIsNone(row.started_at)

    def test_title_required(self):
        self._login(self.admin)
        r = self._create(title="")
        self.assertEqual(self.M["WorkRequest"].query.count(), 0)
        follow = self.client.post(
            "/requests/new",
            data={
                "title": "",
                "project_id": str(self.project.id),
                "request_type": "general",
                "priority": "medium",
            },
            follow_redirects=True,
        )
        self.assertIn("title", follow.get_data(as_text=True).lower())

    def test_outsider_cannot_view_other_project_request(self):
        self._login(self.admin)
        self._create()
        row = self.M["WorkRequest"].query.first()
        stranger = self.M["Account"](
            email="wr-stranger@test.local",
            password_hash=generate_password_hash("pw", method="pbkdf2:sha256"),
            role="user",
            status="active",
            is_active=True,
        )
        db.session.add(stranger)
        db.session.flush()
        su = self.M["User"](
            name="Stranger", email="wr-stranger@test.local", account_id=stranger.id
        )
        db.session.add(su)
        db.session.commit()
        self._login(stranger)
        r = self.client.get(f"/requests/{row.id}")
        self.assertEqual(r.status_code, 404)

    def test_valid_transitions_and_timestamps(self):
        self._login(self.admin)
        self._create()
        row = self.M["WorkRequest"].query.first()
        rid = row.id
        start = self.client.post(
            f"/requests/{rid}/start",
            data={"version": str(row.version), "estimated_duration_minutes": "45"},
        )
        self.assertIn(start.status_code, (302, 303))
        row = db.session.get(self.M["WorkRequest"], rid)
        self.assertEqual(row.status, "started")
        self.assertIsNotNone(row.started_at)
        self.assertEqual(row.estimated_duration_minutes, 45)
        self.assertEqual(row.started_by_id, self.admin_user.id)

        finish = self.client.post(
            f"/requests/{rid}/finish",
            data={"version": str(row.version), "comment": "All done"},
        )
        self.assertIn(finish.status_code, (302, 303))
        row = db.session.get(self.M["WorkRequest"], rid)
        self.assertEqual(row.status, "finished")
        self.assertIsNotNone(row.finished_at)
        bodies = [e.body for e in self.M["WorkRequestEvent"].query.filter_by(request_id=rid).all()]
        self.assertTrue(any("All done" in (b or "") for b in bodies))

    def test_fail_requires_comment(self):
        self._login(self.admin)
        self._create()
        row = self.M["WorkRequest"].query.first()
        r = self.client.post(
            f"/requests/{row.id}/fail",
            data={"version": str(row.version), "comment": ""},
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("failure reason", r.get_data(as_text=True).lower())
        row = db.session.get(self.M["WorkRequest"], row.id)
        self.assertEqual(row.status, "pending")
        self.assertIsNone(row.failed_at)

    def test_pending_to_failed(self):
        self._login(self.admin)
        self._create()
        row = self.M["WorkRequest"].query.first()
        self.client.post(
            f"/requests/{row.id}/fail",
            data={"version": str(row.version), "comment": "Blocked"},
        )
        row = db.session.get(self.M["WorkRequest"], row.id)
        self.assertEqual(row.status, "failed")
        self.assertIsNotNone(row.failed_at)

    def test_invalid_finished_from_pending(self):
        self._login(self.admin)
        self._create()
        row = self.M["WorkRequest"].query.first()
        self.client.post(
            f"/requests/{row.id}/finish",
            data={"version": str(row.version), "comment": "nope"},
            follow_redirects=True,
        )
        row = db.session.get(self.M["WorkRequest"], row.id)
        self.assertEqual(row.status, "pending")
        self.assertIsNone(row.finished_at)

    def test_stale_version_rejected(self):
        self._login(self.admin)
        self._create()
        row = self.M["WorkRequest"].query.first()
        stale = int(row.version)
        self.client.post(
            f"/requests/{row.id}/start",
            data={"version": str(stale), "estimated_duration_minutes": "10"},
        )
        again = self.client.post(
            f"/requests/{row.id}/start",
            data={"version": str(stale), "estimated_duration_minutes": "10"},
            follow_redirects=True,
        )
        html = again.get_data(as_text=True).lower()
        self.assertTrue(
            "someone else" in html or "already set" in html,
        )
        row = self.M["WorkRequest"].query.first()
        self.assertEqual(row.status, "started")

    def test_notification_dedupes_actor(self):
        self._login(self.admin)
        self._create()
        row = self.M["WorkRequest"].query.first()
        ids = wrs.recipient_user_ids(row, self.admin_user.id)
        self.assertEqual(ids, [self.other_user.id])
        self.assertEqual(row.assigned_to_id, self.other_user.id)

    def test_reopen_records_history(self):
        self._login(self.admin)
        self._create()
        row = self.M["WorkRequest"].query.first()
        self.client.post(f"/requests/{row.id}/fail", data={"version": str(row.version), "comment": "x"})
        row = db.session.get(self.M["WorkRequest"], row.id)
        self.client.post(f"/requests/{row.id}/reopen", data={"version": str(row.version), "comment": "try again"})
        row = db.session.get(self.M["WorkRequest"], row.id)
        self.assertEqual(row.status, "pending")
        self.assertIsNone(row.failed_at)
        types = [e.event_type for e in self.M["WorkRequestEvent"].query.filter_by(request_id=row.id)]
        self.assertIn("reopened", types)

    def test_list_filters_and_search(self):
        self._login(self.admin)
        self._create(title="Alpha conform")
        self._create(title="Beta sound", request_type="sound", priority="low", user_id="")
        html = self.client.get("/requests?q=Alpha").get_data(as_text=True)
        self.assertIn("Alpha conform", html)
        self.assertNotIn("Beta sound", html)
        html = self.client.get("/requests?priority=low").get_data(as_text=True)
        self.assertIn("Beta sound", html)
        self.assertNotIn("Alpha conform", html)
        html = self.client.get("/requests?status=pending&sort=title&dir=asc").get_data(as_text=True)
        self.assertIn("Create request", html)

    def test_escaped_description_on_detail(self):
        self._login(self.admin)
        self._create(description="<script>alert(1)</script>xss")
        row = self.M["WorkRequest"].query.first()
        html = self.client.get(f"/requests/{row.id}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_transition_helpers(self):
        self.assertTrue(wrs.transition_allowed("pending", "started"))
        self.assertTrue(wrs.transition_allowed("pending", "failed"))
        self.assertTrue(wrs.transition_allowed("started", "finished"))
        self.assertTrue(wrs.transition_allowed("started", "failed"))
        self.assertFalse(wrs.transition_allowed("pending", "finished"))
        self.assertFalse(wrs.transition_allowed("finished", "started"))
        self.assertTrue(wrs.transition_allowed("failed", "pending"))
        self.assertTrue(wrs.transition_allowed("finished", "pending"))

    def test_apply_transition_rollback_fields_on_invalid(self):
        row = type("R", (), {})()
        row.status = "pending"
        row.version = 1
        row.started_at = None
        row.finished_at = None
        row.failed_at = None
        err = wrs.apply_status_transition(
            row, target="finished", actor_user_id=1, now=None, comment="x"
        )
        self.assertIsNotNone(err)
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.version, 1)

    def test_dashboard_widget_links(self):
        self._login(self.admin)
        self._create()
        dash = self.client.get("/")
        html = dash.get_data(as_text=True)
        self.assertIn('href="/requests"', html)
        self.assertNotIn("Requests coming soon", html)


if __name__ == "__main__":
    unittest.main()
