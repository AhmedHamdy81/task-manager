"""
Verify the global Notifications panel data source: GET /notifications returns rows
visible to the signed-in directory user (same JSON the sidebar panel consumes).
"""
from __future__ import annotations

import os
import tempfile
import unittest

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_notifications_unittest.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from werkzeug.security import generate_password_hash

from app import app, db

_HASH = lambda pw: generate_password_hash(pw, method="pbkdf2:sha256")


class TestNotificationsPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = app
        with app.app_context():
            db.drop_all()
            db.create_all()

    def setUp(self) -> None:
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        db.session.query(self.M["Notification"]).delete()
        db.session.query(self.M["ProjectMember"]).delete()
        db.session.query(self.M["Project"]).delete()
        db.session.query(self.M["User"]).delete()
        db.session.query(self.M["Account"]).delete()
        db.session.commit()

    def tearDown(self) -> None:
        db.session.remove()
        self.ctx.pop()

    def test_notifications_appear_for_project_member(self) -> None:
        M = self.M
        acc = M["Account"](
            email="notif-panel-test@example.com",
            username="notifpaneltest",
            password_hash=_HASH("test-password-1"),
            role="user",
        )
        db.session.add(acc)
        db.session.flush()
        user = M["User"](
            name="Notif Panel User",
            email="notif-panel-test@example.com",
            account_id=acc.id,
        )
        db.session.add(user)
        db.session.flush()
        proj = M["Project"](
            name="Notif Test Project",
            project_type="Feature",
            production_house="Test House",
            director="Test Director",
        )
        db.session.add(proj)
        db.session.flush()
        db.session.add(M["ProjectMember"](project_id=proj.id, user_id=user.id))
        db.session.add(
            M["Notification"](
                user_id=user.id,
                type="activity",
                severity="info",
                title="Global panel test",
                message="Seeded for unittest.",
                entity_type="project",
                entity_id=proj.id,
                project_id=proj.id,
                is_read=False,
                is_acknowledged=False,
                is_resolved=False,
                rule_key="unittest:panel:1:" + str(user.id),
            )
        )
        db.session.commit()

        login = self.client.post(
            "/login",
            data={
                "login": "notif-panel-test@example.com",
                "password": "test-password-1",
                "next": "/",
            },
            follow_redirects=True,
        )
        self.assertEqual(login.status_code, 200)

        res = self.client.get("/notifications", headers={"Accept": "application/json"})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        payload = res.get_json()
        self.assertIsInstance(payload, dict)
        self.assertTrue(payload.get("ok"), payload)
        items = payload.get("notifications") or []
        self.assertEqual(len(items), 1, items)
        self.assertEqual(items[0].get("title"), "Global panel test")
        self.assertEqual(items[0].get("message"), "Seeded for unittest.")
        self.assertEqual(items[0].get("project_id"), proj.id)
        self.assertFalse(items[0].get("is_read"))

    def test_notifications_empty_for_other_user(self) -> None:
        """Same rule_key pattern but different user_id must not leak to wrong account."""
        M = self.M
        acc_a = M["Account"](
            email="user-a@example.com",
            username="usera",
            password_hash=_HASH("pw-a"),
            role="user",
        )
        acc_b = M["Account"](
            email="user-b@example.com",
            username="userb",
            password_hash=_HASH("pw-b"),
            role="user",
        )
        db.session.add_all([acc_a, acc_b])
        db.session.flush()
        ua = M["User"](name="User A", email="user-a@example.com", account_id=acc_a.id)
        ub = M["User"](name="User B", email="user-b@example.com", account_id=acc_b.id)
        db.session.add_all([ua, ub])
        db.session.flush()
        proj = M["Project"](
            name="Two User Project",
            project_type="Feature",
            production_house="H",
            director="D",
        )
        db.session.add(proj)
        db.session.flush()
        db.session.add(M["ProjectMember"](project_id=proj.id, user_id=ua.id))
        db.session.add(M["ProjectMember"](project_id=proj.id, user_id=ub.id))
        db.session.add(
            M["Notification"](
                user_id=ua.id,
                type="activity",
                severity="info",
                title="Only for A",
                message="Private",
                entity_type="project",
                entity_id=proj.id,
                project_id=proj.id,
                is_read=False,
                is_acknowledged=False,
                is_resolved=False,
                rule_key="unittest:private:1:" + str(ua.id),
            )
        )
        db.session.commit()

        self.client.post(
            "/login",
            data={"login": "user-b@example.com", "password": "pw-b", "next": "/"},
            follow_redirects=True,
        )
        res = self.client.get("/notifications", headers={"Accept": "application/json"})
        self.assertEqual(res.status_code, 200)
        items = (res.get_json() or {}).get("notifications") or []
        self.assertEqual(len(items), 0, "User B must not see User A's notification row")

    def test_approval_notification_href_points_to_approval_center(self) -> None:
        M = self.M
        acc = M["Account"](
            email="approval-href@example.com",
            username="approvalhref",
            password_hash=_HASH("pw"),
            role="admin",
        )
        db.session.add(acc)
        db.session.flush()
        user = M["User"](
            name="Approval Href User",
            email="approval-href@example.com",
            account_id=acc.id,
        )
        db.session.add(user)
        db.session.flush()
        note = M["Notification"](
            user_id=user.id,
            type="activity",
            severity="info",
            title="New user registration (awaiting approval)",
            message="Review it in the Reactivation Requests tab.",
            entity_type="user_registered",
            entity_id=0,
            project_id=None,
            is_read=False,
            is_acknowledged=False,
            is_resolved=False,
            rule_key="managed:user_registered:1:0:0:" + str(user.id) + ":live:",
        )
        db.session.add(note)
        db.session.commit()

        self.client.post(
            "/login",
            data={"login": "approval-href@example.com", "password": "pw", "next": "/"},
            follow_redirects=True,
        )
        res = self.client.get("/notifications", headers={"Accept": "application/json"})
        items = (res.get_json() or {}).get("notifications") or []
        self.assertEqual(len(items), 1)
        self.assertTrue((items[0].get("href") or "").endswith("/admin/approvals"))


if __name__ == "__main__":
    unittest.main()
