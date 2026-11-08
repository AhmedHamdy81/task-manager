"""Tests for centralized permission service."""

from __future__ import annotations

import os
import tempfile
import unittest

# conftest.py sets TASK_MANAGER_TEST_DATABASE before app import; keep a local fallback.
_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_permissions_unittest.db")
os.close(_fd)
if not (os.environ.get("TASK_MANAGER_TEST_DATABASE") or "").strip():
    os.environ["TASK_MANAGER_TEST_DATABASE"] = f"sqlite:///{_TEST_DB_PATH}"

from app import app, db
from flask import request
from permissions import register_permission_models, seed_permissions


class PermissionServiceTests(unittest.TestCase):
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
        self.perm = app.extensions["permissions"]
        db.session.query(self.M["UserPermissionOverride"]).delete()
        db.session.query(self.M["User"]).delete()
        db.session.query(self.M["Account"]).delete()
        db.session.query(self.M["ProjectMember"]).delete()
        db.session.query(self.M["Project"]).delete()
        db.session.commit()

        self.admin = self.M["Account"](email="admin@test.local", password_hash="x", role="admin")
        db.session.add(self.admin)
        db.session.flush()
        db.session.add(self.M["User"](name="Admin", email="admin@test.local", account_id=self.admin.id))
        db.session.commit()

    def tearDown(self):
        self.ctx.pop()

    def test_admin_has_full_access(self):
        self.assertTrue(self.perm.can(self.admin, "users", "delete"))
        self.assertTrue(self.perm.can(self.admin, "control_panel", "manage_permissions"))

    def test_super_user_has_same_access_as_admin(self):
        su = self.M["Account"](email="su@test.local", password_hash="x", role="super_user")
        db.session.add(su)
        db.session.flush()
        db.session.add(self.M["User"](name="Super", email="su@test.local", account_id=su.id))
        db.session.commit()
        self.assertTrue(su.is_admin)
        self.assertTrue(self.perm.can(su, "users", "delete"))
        self.assertTrue(self.perm.can(su, "control_panel", "manage_permissions"))
        self.assertTrue(self.perm.can(su, "users", "view"))

    def test_admin_directory_user_ids_includes_super_user(self):
        import account_approval_support as aas
        from app import ROLE_ADMIN, ROLE_SUPER_USER

        su = self.M["Account"](email="su-notify@test.local", password_hash="x", role="super_user")
        regular = self.M["Account"](email="user-notify@test.local", password_hash="x", role="user")
        db.session.add_all([su, regular])
        db.session.flush()
        su_u = self.M["User"](name="Super Notify", email="su-notify@test.local", account_id=su.id)
        user_u = self.M["User"](name="User Notify", email="user-notify@test.local", account_id=regular.id)
        db.session.add_all([su_u, user_u])
        db.session.commit()
        admin_u = self.M["User"].query.filter_by(account_id=self.admin.id).first()
        ids = aas.admin_directory_user_ids(
            db, self.M["Account"], self.M["User"], ROLE_ADMIN, ROLE_SUPER_USER
        )
        self.assertIn(int(admin_u.id), ids)
        self.assertIn(int(su_u.id), ids)
        self.assertNotIn(int(user_u.id), ids)

    def test_admins_recipient_preset_includes_access_roles(self):
        from notification_events import _expand_recipients

        cfg = _expand_recipients({"preset": "admins"})
        self.assertIn("admin", cfg.get("access_roles") or [])
        self.assertIn("Security / Access Control Admin", cfg.get("job_titles") or [])

    # Decided policy (Super User areas): "hidden only". The sidebar hides Projects, Tasks,
    # Booking, VFX and Color for Super Users, but they keep administrator access, so direct
    # URLs work. The old `request_path_blocked_for_super_user` blocklist never existed in this
    # repository's history; these HTTP tests replace it.

    def _super_user_client(self):
        su = self.M["Account"](email="su-block@test.local", password_hash="x", role="super_user")
        db.session.add(su)
        db.session.flush()
        db.session.add(self.M["User"](name="SU Block", email="su-block@test.local", account_id=su.id))
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["account_id"] = su.id
        return client

    def test_super_user_reaches_admin_tools_and_users(self):
        """Current, decided behaviour: Super Users have administrator access."""
        client = self._super_user_client()
        for path in ("/", "/users", "/control/system-setup/email"):
            self.assertEqual(client.get(path, follow_redirects=False).status_code, 200, path)

    def test_super_user_sidebar_hides_areas_but_urls_stay_reachable(self):
        client = self._super_user_client()
        home = client.get("/").get_data(as_text=True)
        for nav in ("projects", "booking", "vfx", "color_dept"):
            self.assertNotIn(f'data-nav="{nav}"', home, f"{nav} is hidden in the Super User sidebar")
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.admin.id
        admin_home = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-nav="projects"', admin_home, "admins still see the areas")
        for path in ("/projects", "/tasks", "/booking", "/vfx-department", "/color-department",
                     "/criticals", "/requests"):
            res = client.get(path, follow_redirects=False)
            self.assertEqual(res.status_code, 200, f"hidden-only: {path} stays reachable for Super Users")

    def test_super_user_hidden_area_actions_behave_like_admin(self):
        su_client = self._super_user_client()
        admin_client = app.test_client()
        with admin_client.session_transaction() as sess:
            sess["account_id"] = self.admin.id
        for path in ("/projects", "/tasks", "/booking", "/vfx-department", "/color-department",
                     "/machine-room/dashboard", "/criticals", "/missing-information", "/requests"):
            su = su_client.get(path, follow_redirects=False)
            admin = admin_client.get(path, follow_redirects=False)
            self.assertEqual((su.status_code, su.headers.get("Location")),
                             (admin.status_code, admin.headers.get("Location")), path)
        for path in ("/api/work-session/active",):
            su = su_client.get(path, headers={"Accept": "application/json"})
            admin = admin_client.get(path, headers={"Accept": "application/json"})
            self.assertEqual(su.status_code, admin.status_code, path)

    def test_admin_still_opens_projects_and_booking(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.admin.id
        projects = self.client.get("/projects", follow_redirects=False)
        self.assertEqual(projects.status_code, 200)
        booking = self.client.get("/booking", follow_redirects=False)
        self.assertEqual(booking.status_code, 200)

    def test_default_user_denied_users_page(self):
        user_acc = self.M["Account"](email="user@test.local", password_hash="x", role="user")
        db.session.add(user_acc)
        db.session.flush()
        db.session.add(self.M["User"](name="User", email="user@test.local", account_id=user_acc.id))
        db.session.commit()
        self.assertTrue(self.perm.can(user_acc, "dashboard", "view"))
        self.assertFalse(self.perm.can(user_acc, "users", "view"))
        with self.app.test_request_context("/users/1/avatar"):
            decision = self.perm.check_request(user_acc)
        self.assertTrue(decision is None or decision.allowed)

    def test_machine_room_role_denied_music_library(self):
        mr = self.M["Account"](email="mr@test.local", password_hash="x", role="machine_room")
        db.session.add(mr)
        db.session.flush()
        db.session.add(self.M["User"](name="MR", email="mr@test.local", account_id=mr.id))
        db.session.commit()
        self.assertTrue(self.perm.can(mr, "machine_room", "view"))
        self.assertFalse(self.perm.can(mr, "music_library", "view"))

    def test_producer_role_can_use_storage_machine_room(self):
        """Access role Producer may open Storage (machine_room) nav and workflows."""
        producer = self.M["Account"](
            email="producer-mr@test.local", password_hash="x", role="producer"
        )
        db.session.add(producer)
        db.session.flush()
        db.session.add(
            self.M["User"](
                name="Producer MR", email="producer-mr@test.local", account_id=producer.id
            )
        )
        db.session.commit()
        for action in ("view", "create", "edit", "start_copy", "manage_hdd", "scan"):
            self.assertTrue(
                self.perm.can(producer, "machine_room", action),
                msg=f"producer should have machine_room/{action}",
            )

    def test_editing_team_can_view_music_library(self):
        editor_title = self.M["JobTitle"].query.filter_by(name="Senior Editor").first()
        if editor_title is None:
            editor_title = self.M["JobTitle"](
                name="Senior Editor",
                department_code="editing",
                default_role="editor",
            )
            db.session.add(editor_title)
            db.session.flush()
        else:
            editor_title.department_code = "editing"
        acc = self.M["Account"](email="editor@test.local", password_hash="x", role="user")
        db.session.add(acc)
        db.session.flush()
        db.session.add(
            self.M["User"](
                name="Senior Editor User",
                email="editor@test.local",
                account_id=acc.id,
                job_title_id=editor_title.id,
            )
        )
        db.session.commit()
        self.assertTrue(self.perm.can(acc, "music_library", "view"))
        self.assertTrue(self.perm.can(acc, "music_library", "add_to_project"))
        self.assertFalse(self.perm.can(acc, "music_library", "mount"))
        self.assertFalse(self.perm.can(acc, "music_library", "scan"))

    def test_non_editing_user_denied_music_library(self):
        acc = self.M["Account"](email="plain@test.local", password_hash="x", role="user")
        db.session.add(acc)
        db.session.flush()
        db.session.add(self.M["User"](name="Plain", email="plain@test.local", account_id=acc.id))
        db.session.commit()
        self.assertFalse(self.perm.can(acc, "music_library", "view"))

    def _make_editor_account(self, email: str):
        editor_title = self.M["JobTitle"].query.filter_by(name="Film Editor Access").first()
        if editor_title is None:
            editor_title = self.M["JobTitle"](
                name="Film Editor Access",
                department_code="editing",
                default_role="editor",
            )
            db.session.add(editor_title)
            db.session.flush()
        acc = self.M["Account"](email=email, password_hash="x", role="user")
        db.session.add(acc)
        db.session.flush()
        db.session.add(
            self.M["User"](
                name="Editor User",
                email=email,
                account_id=acc.id,
                job_title_id=editor_title.id,
            )
        )
        db.session.commit()
        self.perm.invalidate_cache()
        return acc

    def test_editor_has_full_control_of_production_day(self):
        acc = self._make_editor_account("day-editor@test.local")
        guest = app.extensions["guest_access"]
        for action in ("view", "create", "edit", "delete", "upload", "assign"):
            self.assertTrue(
                self.perm.can(acc, "production_day", action),
                msg=f"editor should have production_day/{action}",
            )
        self.assertFalse(self.perm.can(acc, "project_detail", "edit"))
        self.assertTrue(guest["account_may_edit_production"](acc, 5))
        with self.app.test_request_context("/projects/5/production/day/96", method="POST"):
            self.assertEqual(self.perm.resolve_page_key(request.path), "production_day")
            decision = self.perm.check_request(acc)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.allowed)
        with self.app.test_request_context(
            "/projects/5/shooting-day-scenes/12/update", method="POST"
        ):
            decision = self.perm.check_request(acc)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.allowed)

    def test_plain_user_cannot_edit_production_day(self):
        acc = self.M["Account"](email="plain-day@test.local", password_hash="x", role="user")
        db.session.add(acc)
        db.session.flush()
        db.session.add(self.M["User"](name="Plain Day", email="plain-day@test.local", account_id=acc.id))
        db.session.commit()
        guest = app.extensions["guest_access"]
        self.assertTrue(self.perm.can(acc, "production_day", "view"))
        self.assertFalse(self.perm.can(acc, "production_day", "edit"))
        self.assertFalse(guest["account_may_edit_production"](acc, 5))
        with self.app.test_request_context("/projects/5/production/day/96/meta", method="POST"):
            decision = self.perm.check_request(acc)
        self.assertIsNotNone(decision)
        self.assertFalse(decision.allowed)

    def test_editor_has_full_control_of_post_pipeline(self):
        acc = self._make_editor_account("pipeline-editor@test.local")
        guest = app.extensions["guest_access"]
        for action in (
            "view",
            "create",
            "edit",
            "delete",
            "manage_departments",
            "upload_versions",
            "link_scenes",
            "add_notes",
            "deliver",
            "approve",
        ):
            self.assertTrue(
                self.perm.can(acc, "editing_items", action),
                msg=f"editor should have editing_items/{action}",
            )
        self.assertTrue(guest["account_may_create_pipeline"](acc, 5))
        self.assertTrue(guest["account_may_edit_pipeline"](acc, 5))
        self.assertTrue(guest["account_may_archive_pipeline"](acc, 5))
        self.assertTrue(guest["pipeline_template_flags"](acc, 5)["may_create"])
        with self.app.test_request_context("/projects/5/post-pipeline"):
            self.assertEqual(self.perm.resolve_page_key(request.path), "editing_items")
            decision = self.perm.check_request(acc)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.allowed)
        with self.app.test_request_context(
            "/projects/5/editing-items/create", method="POST"
        ):
            decision = self.perm.check_request(acc)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.allowed)

    # Decided policy (Lead members): a project member with a Supervisor ("Lead") job title may
    # create project notes, and may add/remove team members within their own scopes. The
    # scope rules are enforced by the team routes (see test_route_authorization.py).

    def test_lead_project_team_member_can_create_project_notes(self):
        jt = self.M["JobTitle"](
            name="Lead Supervisor Title",
            department_code="editing",
            default_role="editor",
            is_supervisor_title=True,
        )
        db.session.add(jt)
        db.session.flush()

        acc = self.M["Account"](email="lead-note@test.local", password_hash="x", role="user")
        db.session.add(acc)
        db.session.flush()

        du = self.M["User"](
            name="Lead Note User",
            email="lead-note@test.local",
            account_id=acc.id,
            job_title_id=jt.id,
        )
        db.session.add(du)
        db.session.flush()

        p = self.M["Project"](
            name="Test Project Notes",
            project_type="test",
            production_house="Test House",
            director="Test Director",
        )
        db.session.add(p)
        db.session.flush()

        db.session.add(self.M["ProjectMember"](project_id=p.id, user_id=du.id))
        db.session.commit()
        self.perm.invalidate_cache()

        with self.app.test_request_context(f"/projects/{p.id}/actions/create", method="POST"):
            decision = self.perm.check_request(acc)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.allowed)

    def test_non_lead_project_team_member_cannot_create_project_notes(self):
        jt = self.M["JobTitle"](
            name="Non Lead Title",
            department_code="editing",
            default_role="editor",
            is_supervisor_title=False,
        )
        db.session.add(jt)
        db.session.flush()

        acc = self.M["Account"](
            email="nonlead-note@test.local",
            password_hash="x",
            role="user",
        )
        db.session.add(acc)
        db.session.flush()

        du = self.M["User"](
            name="Non Lead Note User",
            email="nonlead-note@test.local",
            account_id=acc.id,
            job_title_id=jt.id,
        )
        db.session.add(du)
        db.session.flush()

        p = self.M["Project"](
            name="Test Project Notes 2",
            project_type="test",
            production_house="Test House 2",
            director="Test Director 2",
        )
        db.session.add(p)
        db.session.flush()

        db.session.add(self.M["ProjectMember"](project_id=p.id, user_id=du.id))
        db.session.commit()
        self.perm.invalidate_cache()

        with self.app.test_request_context(f"/projects/{p.id}/actions/create", method="POST"):
            decision = self.perm.check_request(acc)
        self.assertIsNotNone(decision)
        self.assertFalse(decision.allowed)

    def test_lead_project_team_member_can_manage_team_members(self):
        jt = self.M["JobTitle"](
            name="Lead Team Title",
            department_code="editing",
            default_role="editor",
            is_supervisor_title=True,
        )
        db.session.add(jt)
        db.session.flush()

        acc = self.M["Account"](email="lead-team@test.local", password_hash="x", role="user")
        db.session.add(acc)
        db.session.flush()

        du = self.M["User"](
            name="Lead Team User",
            email="lead-team@test.local",
            account_id=acc.id,
            job_title_id=jt.id,
        )
        db.session.add(du)
        db.session.flush()

        p = self.M["Project"](
            name="Test Project Team",
            project_type="test",
            production_house="Test House",
            director="Test Director",
        )
        db.session.add(p)
        db.session.flush()
        db.session.add(self.M["ProjectMember"](project_id=p.id, user_id=du.id,
                                               assigned_post_scope_code="needs_offline_editing"))
        db.session.commit()
        self.perm.invalidate_cache()

        self.assertTrue(self.perm.may_manage_project_team(acc, p.id))
        with self.app.test_request_context(f"/projects/{p.id}/members/add", method="POST"):
            decision = self.perm.check_request(acc)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.allowed)

    def test_non_lead_project_team_member_cannot_manage_team_members(self):
        jt = self.M["JobTitle"](
            name="Non Lead Team Title",
            department_code="editing",
            default_role="editor",
            is_supervisor_title=False,
        )
        db.session.add(jt)
        db.session.flush()

        acc = self.M["Account"](
            email="nonlead-team@test.local",
            password_hash="x",
            role="user",
        )
        db.session.add(acc)
        db.session.flush()

        du = self.M["User"](
            name="Non Lead Team User",
            email="nonlead-team@test.local",
            account_id=acc.id,
            job_title_id=jt.id,
        )
        db.session.add(du)
        db.session.flush()

        p = self.M["Project"](
            name="Test Project Team 2",
            project_type="test",
            production_house="Test House 2",
            director="Test Director 2",
        )
        db.session.add(p)
        db.session.flush()
        db.session.add(self.M["ProjectMember"](project_id=p.id, user_id=du.id))
        target = self.M["User"](name="Target", email="target-team@test.local")
        db.session.add(target)
        db.session.commit()
        self.perm.invalidate_cache()

        # `may_manage_project_team` is not wired in app.py; test the real routes instead.
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["account_id"] = acc.id
        res = client.post(f"/projects/{p.id}/members/add", data={"user_id": str(target.id)})
        self.assertIn(res.status_code, (302, 403))
        self.assertIsNone(self.M["ProjectMember"].query.filter_by(project_id=p.id, user_id=target.id).first())
        res = client.post(f"/projects/{p.id}/members/{du.id}/remove")
        self.assertIn(res.status_code, (302, 403))
        self.assertIsNotNone(self.M["ProjectMember"].query.filter_by(project_id=p.id, user_id=du.id).first())
        with self.app.test_request_context(f"/projects/{p.id}/members/add", method="POST"):
            decision = self.perm.check_request(acc)
        self.assertIsNotNone(decision)
        self.assertFalse(decision.allowed)

    def test_machine_room_volume_assign_uses_edit_permission(self):
        mr = self.M["Account"](email="mr-assign@test.local", password_hash="x", role="machine_room")
        db.session.add(mr)
        db.session.flush()
        db.session.add(self.M["User"](name="MR Assign", email="mr-assign@test.local", account_id=mr.id))
        db.session.commit()
        with self.app.test_request_context("/machine-room/volumes/5/assign", method="POST"):
            action = self.perm.infer_action("POST", request.path, "machine_room_volume_assign")
            mapped = self.perm.map_action_for_page("machine_room", action)
        self.assertEqual(action, "assign")
        self.assertEqual(mapped, "edit")
        self.assertTrue(self.perm.can(mr, "machine_room", mapped))

    def test_episode_script_management_uses_episode_upload_permission(self):
        with self.app.test_request_context(
            "/projects/4/episodes/1/script",
            method="POST",
        ):
            action = self.perm.infer_action(
                "POST",
                request.path,
                "project_episode_script_upload",
            )
            mapped = self.perm.map_action_for_page("episode_detail", action)
        self.assertEqual(action, "upload")
        self.assertEqual(mapped, "upload_episode_version")

        with self.app.test_request_context(
            "/projects/4/episodes/1/script/remove",
            method="POST",
        ):
            action = self.perm.infer_action(
                "POST",
                request.path,
                "project_episode_script_remove",
            )
            mapped = self.perm.map_action_for_page("episode_detail", action)
        self.assertEqual(mapped, "upload_episode_version")

    def test_user_override(self):
        user_acc = self.M["Account"](email="u2@test.local", password_hash="x", role="user")
        db.session.add(user_acc)
        db.session.flush()
        du = self.M["User"](name="U2", email="u2@test.local", account_id=user_acc.id)
        db.session.add(du)
        db.session.commit()
        self.assertFalse(self.perm.can(user_acc, "vfx_department", "view"))
        self.perm.set_user_override(
            admin_user_id=None,
            user_id=du.id,
            page_key="vfx_department",
            action_key="view",
            is_allowed=True,
        )
        db.session.commit()
        self.perm.invalidate_cache()
        self.assertTrue(self.perm.can(user_acc, "vfx_department", "view"))

    def test_vfx_job_title_grants_department_view(self):
        user_acc = self.M["Account"](email="vfx@test.local", password_hash="x", role="user")
        db.session.add(user_acc)
        db.session.flush()
        jt = self.M["JobTitle"](name="VFX Supervisor")
        db.session.add(jt)
        db.session.flush()
        du = self.M["User"](name="VFX Sup", email="vfx@test.local", account_id=user_acc.id, job_title_id=jt.id)
        db.session.add(du)
        db.session.commit()
        self.perm.invalidate_cache()
        self.assertTrue(self.perm.can(user_acc, "vfx_department", "view"))

    def test_fx_artist_job_title_grants_department_view(self):
        user_acc = self.M["Account"](email="fx@test.local", password_hash="x", role="user")
        db.session.add(user_acc)
        db.session.flush()
        jt = self.M["JobTitle"](name="FX Artist")
        db.session.add(jt)
        db.session.flush()
        du = self.M["User"](name="FX", email="fx@test.local", account_id=user_acc.id, job_title_id=jt.id)
        db.session.add(du)
        db.session.commit()
        from permissions import register_permission_models, seed_permissions

        seed_permissions(db, register_permission_models(db), self.M["JobTitle"])
        self.perm.invalidate_cache()
        self.assertTrue(self.perm.can(user_acc, "vfx_department", "view"))
        self.assertTrue(self.perm.can(user_acc, "vfx_department", "upload_version"))


if __name__ == "__main__":
    unittest.main()
