"""Task create only allows post-production scopes enabled on the project."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from werkzeug.security import generate_password_hash

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_task_create_scopes.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db  # noqa: E402
from project_settings import POST_SCOPE_FIELDS, project_enabled_post_scope_fields  # noqa: E402


class TaskCreateProjectScopesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        for name in ("Task", "TaskGroupTitle", "TaskGroup", "ProjectMember", "Project", "User", "Account"):
            if name in self.M:
                db.session.query(self.M[name]).delete()
        db.session.commit()

        self.admin = self.M["Account"](
            email="scope-task-admin@test.local",
            password_hash=generate_password_hash("pw", method="pbkdf2:sha256"),
            role="admin",
            status="active",
            is_active=True,
        )
        db.session.add(self.admin)
        db.session.flush()
        self.user = self.M["User"](
            name="Admin",
            email="scope-task-admin@test.local",
            account_id=self.admin.id,
        )
        db.session.add(self.user)
        self.project = self.M["Project"](
            name="Scoped Film",
            project_type="Feature film",
            production_house="Test",
            director="Test",
            needs_offline_editing=True,
            needs_vfx=True,
            needs_online_editing=False,
            needs_sound_design=False,
        )
        db.session.add(self.project)
        db.session.flush()
        db.session.add(self.M["ProjectMember"](project_id=self.project.id, user_id=self.user.id))
        group = self.M["TaskGroup"](
            name="Online Editing",
            sort_order=1,
            post_scope_key="needs_online_editing",
        )
        db.session.add(group)
        db.session.flush()
        title = self.M["TaskGroupTitle"](group_id=group.id, title="Conform", sort_order=0)
        db.session.add(title)
        db.session.commit()
        self.preset_id = title.id

    def tearDown(self):
        self.ctx.pop()

    def test_helper_lists_only_enabled_flags(self):
        flags = {key: False for key, _, _ in POST_SCOPE_FIELDS}
        flags["needs_offline_editing"] = True
        flags["needs_vfx"] = True
        keys = [k for k, _, _ in project_enabled_post_scope_fields(SimpleNamespace(**flags))]
        self.assertEqual(keys, ["needs_offline_editing", "needs_vfx"])

    def test_tasks_page_embeds_enabled_scopes_on_project_options(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.admin.id
        r = self.client.get("/tasks")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn(f'value="{self.project.id}"', body)
        self.assertIn("data-scopes=", body)
        self.assertIn("needs_offline_editing", body)
        self.assertIn("needs_vfx", body)

    def test_create_rejects_scope_not_enabled_on_project(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.admin.id
        r = self.client.post(
            "/tasks/new",
            data={
                "preset_id": str(self.preset_id),
                "post_scope_key": "needs_online_editing",
                "project_id": str(self.project.id),
                "user_id": str(self.user.id),
                "priority": "medium",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("not enabled on this project", r.get_data(as_text=True))
        self.assertEqual(db.session.query(self.M["Task"]).count(), 0)


if __name__ == "__main__":
    unittest.main()
