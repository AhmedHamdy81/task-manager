"""Access Control admin UI and API."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_access_control_unittest.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db
from permissions import register_permission_models, seed_permissions


class AccessControlPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        with app.app_context():
            db.drop_all()
            db.create_all()
            M = app.extensions["tm_test_models"]
            seed_permissions(db, register_permission_models(db), M["JobTitle"])

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        db.session.query(self.M["UserPermissionOverride"]).delete()
        db.session.query(self.M["User"]).delete()
        db.session.query(self.M["Account"]).delete()
        db.session.commit()
        self.admin = self.M["Account"](
            email="admin-ac@test.local", password_hash="x", role="admin"
        )
        db.session.add(self.admin)
        db.session.flush()
        db.session.add(
            self.M["User"](
                name="Admin",
                email="admin-ac@test.local",
                account_id=self.admin.id,
            )
        )
        db.session.commit()

    def tearDown(self):
        self.ctx.pop()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.admin.id

    def test_pages_api_returns_catalog(self):
        self._login()
        r = self.client.get("/admin/api/permissions")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertGreater(len(data.get("pages", [])), 0)
        self.assertGreater(len(data.get("actions", [])), 0)

    def test_access_control_html_bootstraps_pages(self):
        self._login()
        r = self.client.get("/admin/access-control")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("ac-pages-list", body)
        self.assertIn("Help", body)
        m = re.search(r"initialCatalog:\s*(\{.*?\})\s*\n\s*\};", body, re.S)
        self.assertIsNotNone(m, "ACCESS_CONTROL_BOOT.initialCatalog missing")
        catalog = json.loads(m.group(1))
        self.assertGreater(len(catalog.get("pages", [])), 0)

    def test_access_control_help_page(self):
        self._login()
        r = self.client.get("/admin/access-control/help")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("Access Control Help", body)
        self.assertIn("How access is decided", body)
        self.assertIn("ac-help-overview.png", body)

    def test_access_control_tour_help_page(self):
        self._login()
        r = self.client.get("/tour/help/access-control")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("How access is decided", body)
        self.assertIn("ac-help-pages.png", body)
        self.assertIn("Open Access Control Help", body)


if __name__ == "__main__":
    unittest.main()
