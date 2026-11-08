"""Route-level authorization matrix over real HTTP requests (isolated test database).

Decided policy: Leads (Supervisor job title, on the project) may create project notes and
add/remove members within their own scopes; Super Users keep administrator access to areas
their sidebar hides.
"""

from __future__ import annotations

import os
import tempfile
import unittest

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_route_authz.db")
os.close(_fd)
if not (os.environ.get("TASK_MANAGER_TEST_DATABASE") or "").strip():
    os.environ["TASK_MANAGER_TEST_DATABASE"] = f"sqlite:///{_TEST_DB_PATH}"

from app import app, db  # noqa: E402
from permissions import register_permission_models, seed_permissions  # noqa: E402

ALLOWED_TEAM_EDITORS = {"admin", "super_user"}  # producer below is not on the project


class RouteAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()
            seed_permissions(db, register_permission_models(db), app.extensions["tm_test_models"]["JobTitle"])

    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        self._wipe()
        M = self.M
        title = M["JobTitle"](name="Route Editor", department_code="editing", default_role="editor")
        db.session.add(title)
        self.project = M["Project"](name="Authz", project_type="test", production_house="h", director="d")
        db.session.add(self.project)
        db.session.flush()
        self.accounts: dict[str, int] = {}
        self.users: dict[str, int] = {}
        for key, role, member, status in (
            ("plain_member", "user", True, "active"),
            ("non_member", "user", False, "active"),
            ("producer", "producer", False, "active"),
            ("machine_room", "machine_room", False, "active"),
            ("admin", "admin", False, "active"),
            ("super_user", "super_user", False, "active"),
            ("guest", "guest", True, "active"),
            ("pending", "user", True, "pending_approval"),
            ("suspended", "user", True, "suspended"),
        ):
            acc = M["Account"](email=f"{key}@authz.local", password_hash="x", role=role, status=status,
                               is_active=status == "active")
            db.session.add(acc)
            db.session.flush()
            user = M["User"](name=key, email=f"{key}@authz.local", account_id=acc.id, job_title_id=title.id)
            db.session.add(user)
            db.session.flush()
            if member:
                db.session.add(M["ProjectMember"](project_id=self.project.id, user_id=user.id))
            self.accounts[key], self.users[key] = acc.id, user.id
        self.outsider = M["User"](name="Outsider", email="outsider@authz.local")
        db.session.add(self.outsider)
        db.session.commit()
        app.extensions["permissions"].invalidate_cache()

    def tearDown(self):
        self._wipe()
        self.ctx.pop()

    def _wipe(self):
        M = self.M
        for model in ("UserPermissionOverride", "ProjectMember", "User", "Account", "Project"):
            db.session.query(M[model]).delete()
        db.session.query(M["JobTitle"]).filter(
            (M["JobTitle"].name == "Route Editor") | (M["JobTitle"].name.like("Route Lead %"))
        ).delete(synchronize_session=False)
        db.session.commit()

    def _client(self, key):
        client = app.test_client()
        if key:
            with client.session_transaction() as s:
                s["account_id"] = self.accounts[key]
        return client

    def _member(self, user_id) -> bool:
        return self.M["ProjectMember"].query.filter_by(project_id=self.project.id, user_id=user_id).first() is not None

    def test_unauthenticated_requests_go_to_login(self):
        client = self._client(None)
        pid = self.project.id
        for method, path in (("get", "/projects"), ("get", f"/projects/{pid}"), ("post", f"/projects/{pid}/actions/create"),
                             ("post", f"/projects/{pid}/members/add"), ("get", "/users"), ("get", "/control/system-setup")):
            res = getattr(client, method)(path)
            self.assertEqual(res.status_code, 302, path)
            self.assertIn("/login", res.headers["Location"], path)

    def test_pending_and_suspended_accounts_only_reach_the_pending_page(self):
        for key in ("pending", "suspended"):
            client = self._client(key)
            for path in ("/projects", f"/projects/{self.project.id}", "/tasks"):
                res = client.get(path)
                self.assertEqual(res.status_code, 302, (key, path))
                self.assertIn("/account/pending", res.headers["Location"], (key, path))
            res = client.post(f"/projects/{self.project.id}/actions/create", json={"title": "x"})
            self.assertNotEqual(res.status_code, 200, key)

    def test_project_notes_creation(self):
        pid = self.project.id
        for key in self.accounts:
            res = self._client(key).post(f"/projects/{pid}/actions/create", json={"title": f"note {key}", "body": "b"})
            if key in ("admin", "super_user"):
                self.assertEqual(res.status_code, 200, key)
            else:
                self.assertNotEqual(res.status_code, 200, key)

    def test_team_membership_changes_are_enforced_at_the_route(self):
        pid = self.project.id
        for key in self.accounts:
            client = self._client(key)
            client.post(f"/projects/{pid}/members/add", data={"user_id": str(self.outsider.id)})
            added = self._member(self.outsider.id)
            self.assertEqual(added, key in ALLOWED_TEAM_EDITORS, f"{key} add")
            if added:
                self.M["ProjectMember"].query.filter_by(project_id=pid, user_id=self.outsider.id).delete()
                db.session.commit()
            victim = self.users["plain_member"]
            client.post(f"/projects/{pid}/members/{victim}/remove")
            removed = not self._member(victim)
            self.assertEqual(removed, key in ALLOWED_TEAM_EDITORS, f"{key} remove")
            if removed:
                db.session.add(self.M["ProjectMember"](project_id=pid, user_id=victim))
                db.session.commit()

    def test_admin_only_areas_refuse_direct_requests(self):
        for key in ("plain_member", "non_member", "producer", "machine_room", "guest"):
            client = self._client(key)
            for path in ("/users", "/control/system-setup/email", "/admin/approvals"):
                res = client.get(path)
                self.assertNotEqual(res.status_code, 200, (key, path))
        for key in ("admin", "super_user"):
            client = self._client(key)
            for path in ("/users", "/control/system-setup/email"):
                self.assertEqual(client.get(path).status_code, 200, (key, path))

    def test_machine_room_and_guest_area_limits(self):
        res = self._client("machine_room").get(f"/projects/{self.project.id}")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/machine-room", res.headers["Location"])
        for path in ("/tasks", "/booking", "/requests"):
            self.assertEqual(self._client("guest").get(path).status_code, 302, path)

    # -- Leads (Supervisor job title): notes + team changes within their own scopes --

    def _lead(self, scope="needs_offline_editing", supervisor=True, project=None):
        M = self.M
        title = M["JobTitle"](name=f"Route Lead {scope} {supervisor}", department_code="editing",
                              default_role="editor", is_supervisor_title=supervisor)
        db.session.add(title)
        acc = M["Account"](email=f"lead-{scope}-{supervisor}@authz.local", password_hash="x", role="user",
                           status="active", is_active=True)
        db.session.add(acc)
        db.session.flush()
        user = M["User"](name="Lead", email=acc.email, account_id=acc.id, job_title_id=title.id)
        db.session.add(user)
        db.session.flush()
        db.session.add(M["ProjectMember"](project_id=(project or self.project).id, user_id=user.id,
                                          assigned_post_scope_code=scope))
        db.session.commit()
        self.accounts["lead"], self.users["lead"] = acc.id, user.id
        return self._client("lead")

    def _scoped_member(self, name, scope):
        user = self.M["User"](name=name, email=f"{name}@authz.local")
        db.session.add(user)
        db.session.flush()
        db.session.add(self.M["ProjectMember"](project_id=self.project.id, user_id=user.id,
                                               assigned_post_scope_code=scope))
        db.session.commit()
        return user.id

    def _flashes(self, client):
        with client.session_transaction() as s:
            return [m for _c, m in s.get("_flashes", [])]

    def test_lead_creates_project_notes_but_a_plain_supervisor_title_elsewhere_does_not(self):
        lead = self._lead()
        res = lead.post(f"/projects/{self.project.id}/actions/create", json={"title": "Lead note", "body": "b"})
        self.assertEqual(res.status_code, 200)
        other = self.M["Project"](name="Elsewhere", project_type="test", production_house="h", director="d")
        db.session.add(other)
        db.session.commit()
        res = lead.post(f"/projects/{other.id}/actions/create", json={"title": "x"})
        self.assertNotEqual(res.status_code, 200, "Lead powers apply only on projects they are on")

    def test_lead_adds_only_within_own_scopes_and_cannot_use_overrides(self):
        lead = self._lead()
        pid = self.project.id
        lead.post(f"/projects/{pid}/members/add", data={"user_id": str(self.outsider.id),
                                                         "assigned_post_scope_code": "needs_vfx"})
        self.assertFalse(self._member(self.outsider.id))
        self.assertTrue(any("only to your own scopes" in m for m in self._flashes(lead)))
        lead.post(f"/projects/{pid}/members/add", data={"user_id": str(self.outsider.id)})
        self.assertFalse(self._member(self.outsider.id), "a Lead must pick one of their scopes")
        lead.post(f"/projects/{pid}/members/add", data={
            "user_id": str(self.outsider.id), "assigned_post_scope_code": "needs_offline_editing",
            "eligibility_override": "1", "employment_override": "1", "eligibility_override_reason": "trust me"})
        self.assertFalse(self._member(self.outsider.id), "admin overrides are ignored for Leads")
        self.assertFalse(any("Only administrators" in m for m in self._flashes(lead)), "the request was authorized")
        admin = self._client("admin")
        admin.post(f"/projects/{pid}/members/add", data={
            "user_id": str(self.outsider.id), "assigned_post_scope_code": "needs_offline_editing",
            "eligibility_override": "1", "employment_override": "1", "eligibility_override_reason": "admin"})
        self.assertTrue(self._member(self.outsider.id), "the same request with full control succeeds")

    def test_lead_cannot_move_a_member_out_of_another_scope(self):
        lead = self._lead()
        vfx = self._scoped_member("vfx-artist", "needs_vfx")
        lead.post(f"/projects/{self.project.id}/members/add", data={
            "user_id": str(vfx), "assigned_post_scope_code": "needs_offline_editing"})
        row = self.M["ProjectMember"].query.filter_by(project_id=self.project.id, user_id=vfx).one()
        self.assertEqual(row.assigned_post_scope_code, "needs_vfx")

    def test_lead_removes_only_members_of_their_scopes(self):
        lead = self._lead()
        pid = self.project.id
        mine = self._scoped_member("editor-in-scope", "needs_offline_editing")
        theirs = self._scoped_member("vfx-out-of-scope", "needs_vfx")
        lead.post(f"/projects/{pid}/members/{theirs}/remove")
        self.assertTrue(self._member(theirs))
        lead.post(f"/projects/{pid}/members/{self.users['plain_member']}/remove")
        self.assertTrue(self._member(self.users["plain_member"]), "no scope at all: not the Lead's to remove")
        lead.post(f"/projects/{pid}/members/{mine}/remove")
        self.assertFalse(self._member(mine))

    def test_supervisor_title_without_membership_or_without_scope_grants_nothing(self):
        lead = self._lead(scope=None)
        pid = self.project.id
        mine = self._scoped_member("editor-x", "needs_offline_editing")
        lead.post(f"/projects/{pid}/members/{mine}/remove")
        self.assertTrue(self._member(mine), "a Lead with no scopes cannot manage anyone")
        plain = self._lead(scope="needs_offline_editing", supervisor=False)
        plain.post(f"/projects/{pid}/members/{mine}/remove")
        self.assertTrue(self._member(mine), "without a Supervisor title there are no Lead powers")

    def test_team_page_shows_lead_controls_only_for_their_scope(self):
        for flag in ("needs_offline_editing", "needs_vfx"):
            self.assertTrue(hasattr(self.project, flag), flag)
            setattr(self.project, flag, True)
        db.session.commit()
        lead = self._lead()
        self._scoped_member("vfx-out-of-scope", "needs_vfx")
        page = lead.get(f"/projects/{self.project.id}/team").get_data(as_text=True)
        self.assertIn('data-scope-manage="needs_offline_editing"', page)
        self.assertNotIn('data-scope-manage="needs_vfx"', page)
        self.assertNotIn('name="eligibility_override"', page)

    def test_non_member_cannot_open_the_project(self):
        res = self._client("non_member").get(f"/projects/{self.project.id}")
        self.assertNotEqual(res.status_code, 200)
        self.assertEqual(self._client("plain_member").get(f"/projects/{self.project.id}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
