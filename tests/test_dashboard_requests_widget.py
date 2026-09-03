"""Dashboard Requests widget links to the Requests page."""

from __future__ import annotations

import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_dash_requests.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db  # noqa: E402


class DashboardRequestsWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        for name in ("WorkRequest", "WorkRequestEvent", "Task", "ProjectMember", "Project", "User", "Account"):
            if name in self.M:
                db.session.query(self.M[name]).delete()
        db.session.commit()

        self.admin = self.M["Account"](
            email="dash-req-admin@test.local",
            password_hash=generate_password_hash("pw", method="pbkdf2:sha256"),
            role="admin",
            status="active",
            is_active=True,
        )
        db.session.add(self.admin)
        db.session.flush()
        db.session.add(
            self.M["User"](
                name="Admin",
                email="dash-req-admin@test.local",
                account_id=self.admin.id,
            )
        )
        db.session.commit()

    def tearDown(self):
        self.ctx.pop()

    def test_dashboard_requests_card_links_to_requests_page(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.admin.id
        dash = self.client.get("/")
        self.assertEqual(dash.status_code, 200)
        html = dash.get_data(as_text=True)
        self.assertIn('href="/requests"', html)
        self.assertNotIn("Requests coming soon", html)
        self.assertNotIn("shell-widget--disabled", html)
        page = self.client.get("/requests")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Requests", page.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
