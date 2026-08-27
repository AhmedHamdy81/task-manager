"""Bridge logic between /projects/<id>/vfx and /vfx-department/<id>.

Covers:
  - State-machine guard (`_vfx_mgmt_transition_allowed`)
  - Dependency cycle detection
  - Editor sync rules (vendor flip, blocked round-trip, approved vs client_review)
  - Editor route forbidden-keys gate
  - Recall endpoint (gating + side effects)
  - Editor versions route locked down once a shot is in the department
"""
from __future__ import annotations

import os
import tempfile
import unittest

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_vfx_workflow.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from werkzeug.security import generate_password_hash

from app import app, db
from permissions import register_permission_models, seed_permissions


def _hash(pw: str) -> str:
    return generate_password_hash(pw, method="pbkdf2:sha256")


class VfxWorkflowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = app
        with app.app_context():
            db.drop_all()
            db.create_all()
            M = app.extensions["tm_test_models"]
            seed_permissions(db, register_permission_models(db), M["JobTitle"])

    def setUp(self) -> None:
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        self.H = app.extensions["tm_test_helpers"]
        # Tables we touch in these tests, deepest-first to satisfy FKs.
        for tbl in (
            self.M["VfxMgmtActivity"],
            self.M["VfxVersion"],
            self.M["VfxProjectDiscussion"],
            self.M["VfxShot"],
            self.M["ShootingDayScene"],
            self.M["ShootingDay"],
            self.M["Notification"],
            self.M["ProjectMember"],
            self.M["Project"],
            self.M["User"],
            self.M["JobTitle"],
            self.M["Account"],
        ):
            db.session.query(tbl).delete()
        db.session.commit()

    def tearDown(self) -> None:
        db.session.remove()
        self.ctx.pop()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_account(
        self, email: str, *, is_admin: bool = False, role: str = "user"
    ):
        # `is_admin` is derived from the role column ("admin" and "super_user" -> True),
        # not a stored field — see Account.is_admin in app.py.
        effective_role = "admin" if is_admin else role
        acc = self.M["Account"](
            email=email,
            username=email.split("@", 1)[0],
            password_hash=_hash("pw"),
            role=effective_role,
        )
        db.session.add(acc)
        db.session.flush()
        return acc

    def _make_user(self, name: str, *, account, job_title=None):
        u = self.M["User"](
            name=name,
            email=account.email,
            account_id=account.id,
            job_title_id=(job_title.id if job_title else None),
        )
        db.session.add(u)
        db.session.flush()
        return u

    def _make_project(self, name: str = "Project Bridge"):
        from datetime import date

        p = self.M["Project"](
            name=name,
            project_type="Feature",
            production_house="H",
            director="D",
        )
        db.session.add(p)
        db.session.flush()
        # Every VfxShot needs a ShootingDayScene parent (NOT NULL FK).
        day = self.M["ShootingDay"](
            project_id=p.id,
            unit_number=1,
            day_name="D1",
            shooting_date=date(2026, 1, 1),
        )
        db.session.add(day)
        db.session.flush()
        scene = self.M["ShootingDayScene"](
            shooting_day_id=day.id,
            scene_id=1,
            episode_number=1,
            scene_label="Scene 1",
            scene_number=1,
        )
        db.session.add(scene)
        db.session.flush()
        self._scene_for_project = scene
        return p

    def _make_shot(
        self,
        *,
        project,
        code: str,
        vendor: str = "in_house",
        sent: bool = False,
        mgmt_status: str = "pending",
        editor_status: str = "pending",
        shot_number: int | None = None,
    ):
        from datetime import datetime

        # Ensure each shot has a unique shot_number within its scene
        if shot_number is None:
            existing = (
                db.session.query(self.M["VfxShot"])
                .filter_by(scene_id=self._scene_for_project.id)
                .count()
            )
            shot_number = existing + 1
        sh = self.M["VfxShot"](
            project_id=project.id,
            scene_id=self._scene_for_project.id,
            shot_number=shot_number,
            shot_code=code,
            vendor=vendor,
            status=editor_status,
            mgmt_status=mgmt_status,
            sent_at=datetime(2026, 1, 1, 12, 0, 0) if sent else None,
            shot_briefing="",
            priority="medium",
        )
        db.session.add(sh)
        db.session.flush()
        return sh

    def _login(self, account) -> None:
        with self.client.session_transaction() as sess:
            sess["account_id"] = account.id

    # ------------------------------------------------------------------
    # State-machine matrix
    # ------------------------------------------------------------------

    def test_transition_self_is_noop_allowed(self) -> None:
        for st in (
            "pending",
            "assigned",
            "in_progress",
            "review",
            "client_review",
            "approved",
            "delivered",
            "blocked",
        ):
            self.assertTrue(
                self.H["_vfx_mgmt_transition_allowed"](st, st),
                f"self-transition {st}→{st} should be allowed",
            )

    def test_transition_pending_to_delivered_blocked(self) -> None:
        self.assertFalse(
            self.H["_vfx_mgmt_transition_allowed"]("pending", "delivered")
        )

    def test_transition_pending_to_delivered_allowed_with_force(self) -> None:
        self.assertTrue(
            self.H["_vfx_mgmt_transition_allowed"](
                "pending", "delivered", force=True
            )
        )

    def test_transition_unknown_target_rejected(self) -> None:
        self.assertFalse(
            self.H["_vfx_mgmt_transition_allowed"]("pending", "garbage")
        )

    def test_transition_delivered_locked_except_admin(self) -> None:
        self.assertFalse(
            self.H["_vfx_mgmt_transition_allowed"]("delivered", "review")
        )
        self.assertTrue(
            self.H["_vfx_mgmt_transition_allowed"](
                "delivered", "review", force=True
            )
        )

    # ------------------------------------------------------------------
    # Dependency cycles
    # ------------------------------------------------------------------

    def test_dependency_cycle_self(self) -> None:
        proj = self._make_project()
        sh = self._make_shot(project=proj, code="SH001", sent=True)
        db.session.commit()
        self.assertTrue(
            self.H["_vfx_dependency_creates_cycle"](proj.id, sh.id, sh.id)
        )

    def test_dependency_cycle_two_hop(self) -> None:
        proj = self._make_project()
        a = self._make_shot(project=proj, code="A", sent=True)
        b = self._make_shot(project=proj, code="B", sent=True)
        a.depends_on_shot_id = b.id
        db.session.commit()
        # Now setting B.depends_on = A would close a 2-hop cycle.
        self.assertTrue(
            self.H["_vfx_dependency_creates_cycle"](proj.id, b.id, a.id)
        )

    def test_dependency_no_cycle(self) -> None:
        proj = self._make_project()
        a = self._make_shot(project=proj, code="A", sent=True)
        b = self._make_shot(project=proj, code="B", sent=True)
        db.session.commit()
        self.assertFalse(
            self.H["_vfx_dependency_creates_cycle"](proj.id, a.id, b.id)
        )

    # ------------------------------------------------------------------
    # Sync function
    # ------------------------------------------------------------------

    def test_sync_external_vendor_clears_dept_state_and_sent_at(self) -> None:
        proj = self._make_project()
        sh = self._make_shot(
            project=proj,
            code="SH-EXT",
            sent=True,
            mgmt_status="in_progress",
            editor_status="sent",
        )
        sh.due_date = None
        sh.delivery_notes = "draft"
        db.session.commit()

        sh.vendor = "external"
        self.H["_vfx_sync_editor_shot_to_department"](sh)
        db.session.commit()

        self.assertEqual(sh.mgmt_status, "pending")
        self.assertIsNone(sh.assigned_artist_user_id)
        self.assertIsNone(sh.sent_at, "external vendor must clear sent_at")
        self.assertEqual(sh.delivery_notes or "", "")

    def test_sync_approved_overrides_client_review(self) -> None:
        """Editor 'approved' is an explicit producer override and propagates from client_review.

        Producers/admins clicking Approve on the editor are deliberately
        bypassing the client step; the activity log captures the action.
        """
        proj = self._make_project()
        sh = self._make_shot(
            project=proj,
            code="SH-CR",
            sent=True,
            mgmt_status="client_review",
            editor_status="approved",
        )
        db.session.commit()

        self.H["_vfx_sync_editor_shot_to_department"](sh)
        db.session.commit()

        self.assertEqual(sh.mgmt_status, "approved")

    def test_sync_approved_promotes_in_review(self) -> None:
        proj = self._make_project()
        sh = self._make_shot(
            project=proj,
            code="SH-RV",
            sent=True,
            mgmt_status="review",
            editor_status="approved",
        )
        db.session.commit()
        self.H["_vfx_sync_editor_shot_to_department"](sh)
        db.session.commit()
        self.assertEqual(sh.mgmt_status, "approved")

    def test_sync_blocked_round_trip_back_to_assigned(self) -> None:
        proj = self._make_project()
        u_acc = self._make_account("artist@example.com")
        u = self._make_user("Artist", account=u_acc)
        sh = self._make_shot(
            project=proj,
            code="SH-BL",
            sent=True,
            mgmt_status="blocked",
            editor_status="sent",
        )
        sh.assigned_artist_user_id = u.id
        db.session.commit()

        self.H["_vfx_sync_editor_shot_to_department"](sh)
        db.session.commit()

        self.assertEqual(sh.mgmt_status, "assigned")

    def test_editor_block_then_unblock_restores_assigned(self) -> None:
        """Block / Unblock via editor status actions round-trips mgmt_status."""
        admin_acc, proj = self._team_admin_setup()
        artist_acc = self._make_account("artist-blk@example.com")
        artist = self._make_user("Artist Blk", account=artist_acc)
        sh = self._make_shot(
            project=proj,
            code="SH-BLK-UI",
            sent=True,
            mgmt_status="assigned",
            editor_status="sent",
        )
        sh.assigned_artist_user_id = artist.id
        db.session.commit()

        self._login(admin_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}",
            json={"status": "blocked"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        db.session.refresh(sh)
        self.assertEqual(sh.status, "blocked")
        self.assertEqual(sh.mgmt_status, "blocked")

        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}",
            json={"status": "sent"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        db.session.refresh(sh)
        self.assertEqual(sh.status, "sent")
        self.assertEqual(sh.mgmt_status, "assigned")

    def test_sync_does_not_clobber_delivered(self) -> None:
        proj = self._make_project()
        sh = self._make_shot(
            project=proj,
            code="SH-DL",
            sent=True,
            mgmt_status="delivered",
            editor_status="approved",
        )
        db.session.commit()

        sh.status = "review"
        self.H["_vfx_sync_editor_shot_to_department"](sh)
        db.session.commit()

        self.assertEqual(sh.mgmt_status, "delivered")

    # ------------------------------------------------------------------
    # Editor route guards (HTTP)
    # ------------------------------------------------------------------

    def _team_admin_setup(self):
        admin_acc = self._make_account("admin@example.com", is_admin=True)
        admin_user = self._make_user("Admin", account=admin_acc)
        proj = self._make_project()
        db.session.add(
            self.M["ProjectMember"](project_id=proj.id, user_id=admin_user.id)
        )
        db.session.commit()
        return admin_acc, proj

    def test_editor_route_rejects_mgmt_status_for_non_admin(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        # Make a non-admin team member.
        member_acc = self._make_account("member@example.com")
        member_user = self._make_user("Member", account=member_acc)
        db.session.add(
            self.M["ProjectMember"](
                project_id=proj.id, user_id=member_user.id
            )
        )
        sh = self._make_shot(project=proj, code="SH-EDIT", sent=True)
        db.session.commit()

        self._login(member_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}",
            json={"mgmt_status": "delivered"},
        )
        self.assertEqual(res.status_code, 400, res.get_data(as_text=True))
        body = res.get_json()
        self.assertEqual(body.get("error"), "field_owned_by_department")

    def test_editor_route_saves_shot_duration(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        sh = self._make_shot(project=proj, code="Eps01_Scene01_Shot03")
        db.session.commit()

        self._login(admin_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}",
            json={"duration_seconds": 75},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        db.session.refresh(sh)
        self.assertEqual(sh.duration_seconds, 75)

        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}",
            json={"duration_seconds": ""},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        db.session.refresh(sh)
        self.assertEqual(sh.duration_seconds, 0)

    def test_editor_route_admin_can_force_mgmt_status(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        sh = self._make_shot(project=proj, code="SH-ADM", sent=True)
        db.session.commit()

        self._login(admin_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}",
            json={"mgmt_status": "delivered"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        db.session.refresh(sh)
        self.assertEqual(sh.mgmt_status, "delivered")

    def test_editor_route_locks_shot_code_after_send(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        member_acc = self._make_account("member2@example.com")
        member_user = self._make_user("Member 2", account=member_acc)
        db.session.add(
            self.M["ProjectMember"](
                project_id=proj.id, user_id=member_user.id
            )
        )
        sh = self._make_shot(project=proj, code="SH-LOCK", sent=True)
        db.session.commit()

        self._login(member_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}",
            json={"shot_code": "SH-LOCK-RENAMED"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(
            res.get_json().get("error"), "shot_code_locked_after_send"
        )

    def test_editor_route_refuses_to_unsend_via_pending(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        member_acc = self._make_account("member3@example.com")
        member_user = self._make_user("Member 3", account=member_acc)
        db.session.add(
            self.M["ProjectMember"](
                project_id=proj.id, user_id=member_user.id
            )
        )
        sh = self._make_shot(
            project=proj,
            code="SH-UNS",
            sent=True,
            editor_status="sent",
        )
        db.session.commit()

        self._login(member_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}",
            json={"status": "pending"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(
            res.get_json().get("error"), "use_recall_to_unsend"
        )

    # ------------------------------------------------------------------
    # Recall endpoint
    # ------------------------------------------------------------------

    def test_recall_admin_succeeds_and_clears_state(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        sh = self._make_shot(
            project=proj,
            code="SH-REC",
            sent=True,
            mgmt_status="assigned",
            editor_status="sent",
        )
        artist_acc = self._make_account("artist2@example.com")
        artist_user = self._make_user("Artist 2", account=artist_acc)
        sh.assigned_artist_user_id = artist_user.id
        db.session.commit()

        self._login(admin_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}/recall"
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        db.session.refresh(sh)
        self.assertIsNone(sh.sent_at)
        self.assertIsNone(sh.assigned_artist_user_id)
        self.assertEqual(sh.mgmt_status, "pending")
        self.assertEqual(sh.status, "pending")

    def test_recall_blocked_in_active_production_for_non_admin(self) -> None:
        # Make a VFX Supervisor who can recall pending/assigned/blocked but not in_progress.
        admin_acc, proj = self._team_admin_setup()
        sup_jt = self.M["JobTitle"](name="VFX supervisor")
        db.session.add(sup_jt)
        db.session.flush()
        sup_acc = self._make_account("sup@example.com")
        sup_user = self._make_user("Sup", account=sup_acc, job_title=sup_jt)
        db.session.add(
            self.M["ProjectMember"](project_id=proj.id, user_id=sup_user.id)
        )
        sh = self._make_shot(
            project=proj,
            code="SH-IP",
            sent=True,
            mgmt_status="in_progress",
            editor_status="sent",
        )
        db.session.commit()

        self._login(sup_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}/recall"
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(
            res.get_json().get("error"), "recall_not_allowed"
        )

    def test_recall_rejects_unsent_shot(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        sh = self._make_shot(project=proj, code="SH-NS", sent=False)
        db.session.commit()
        self._login(admin_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}/recall"
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("error"), "not_sent")

    # ------------------------------------------------------------------
    # Sent-marker editor actions (delete / block)
    # ------------------------------------------------------------------

    def test_sent_action_delete_clears_mgmt_activity_and_notifies_vfx(self) -> None:
        """Delete shot from editor while pending must remove dept row + activity.

        Regression: deleting a shot that had ``vfx_mgmt_activity`` rows used to
        500 with NOT NULL on ``shot_id`` because SQLAlchemy tried to null the FK.
        Requires Safe Delete challenge (same flow as the UI).
        """
        admin_acc, proj = self._team_admin_setup()
        vfx_jt = self.M["JobTitle"](name="VFX Artist")
        db.session.add(vfx_jt)
        db.session.flush()
        vfx_acc = self._make_account("vfx-team@example.com")
        vfx_user = self._make_user("VFX Team", account=vfx_acc, job_title=vfx_jt)
        sh = self._make_shot(
            project=proj,
            code="SH-DEL-SENT",
            sent=True,
            mgmt_status="pending",
            editor_status="sent",
        )
        db.session.add(
            self.M["VfxMgmtActivity"](
                project_id=proj.id,
                shot_id=sh.id,
                user_id=vfx_user.id,
                action="sent",
                detail="{}",
            )
        )
        db.session.commit()
        shot_id = int(sh.id)

        self._login(admin_acc)
        bare = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{shot_id}/sent-action",
            json={"action": "delete"},
        )
        self.assertEqual(bare.status_code, 400)
        self.assertEqual(bare.get_json().get("error"), "safe_delete_required")

        ch = self.client.post(
            "/safe-delete/challenge",
            json={
                "entity_type": "vfx_shot",
                "entity_id": shot_id,
                "project_id": proj.id,
            },
        )
        self.assertEqual(ch.status_code, 200, ch.get_data(as_text=True))
        ch_body = ch.get_json()
        self.assertTrue(ch_body.get("ok"))

        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{shot_id}/sent-action",
            json={
                "action": "delete",
                "challenge_token": ch_body["challenge_token"],
                "entered_code": ch_body["display_code"],
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("action"), "delete")
        self.assertIsNone(db.session.get(self.M["VfxShot"], shot_id))
        self.assertEqual(
            db.session.query(self.M["VfxMgmtActivity"])
            .filter_by(shot_id=shot_id)
            .count(),
            0,
        )
        notes = (
            db.session.query(self.M["Notification"])
            .filter_by(user_id=vfx_user.id)
            .all()
        )
        self.assertTrue(
            any("deleted" in ((n.title or "") + (n.message or "")).lower() for n in notes),
            "VFX team user should get a delete notification",
        )

    def test_sent_action_delete_refuses_in_progress(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        sh = self._make_shot(
            project=proj,
            code="SH-DEL-IP",
            sent=True,
            mgmt_status="in_progress",
            editor_status="sent",
        )
        db.session.commit()
        self._login(admin_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}/sent-action",
            json={"action": "delete"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("error"), "delete_not_allowed")

    # ------------------------------------------------------------------
    # Assignment notification: only the new artist is notified
    # ------------------------------------------------------------------

    def test_assignment_notifies_only_the_new_artist(self) -> None:
        """A assigns a shot to B → only B gets a notification.

        Locks in the rule that the assignor (A) and any in-house post
        producers / supervisors do NOT receive a notification on a
        single-shot assignment.
        """
        admin_acc, proj = self._team_admin_setup()
        admin_user = (
            db.session.query(self.M["User"])
            .filter_by(account_id=admin_acc.id)
            .first()
        )
        # Artist B (new assignee).
        artist_jt = self.M["JobTitle"](name="VFX Artist")
        db.session.add(artist_jt)
        db.session.flush()
        b_acc = self._make_account("artist-b@example.com")
        b_user = self._make_user("Artist B", account=b_acc, job_title=artist_jt)
        db.session.add(
            self.M["ProjectMember"](project_id=proj.id, user_id=b_user.id)
        )
        # An in-house post producer who used to receive these — must NOT
        # be notified after this change.
        pp_jt = self.M["JobTitle"](name="In-House Post Producer")
        db.session.add(pp_jt)
        db.session.flush()
        pp_acc = self._make_account("postprod@example.com")
        pp_user = self._make_user(
            "Post Producer", account=pp_acc, job_title=pp_jt
        )
        db.session.add(
            self.M["ProjectMember"](project_id=proj.id, user_id=pp_user.id)
        )
        sh = self._make_shot(
            project=proj,
            code="SH-ASN",
            sent=True,
            mgmt_status="pending",
            editor_status="sent",
        )
        db.session.commit()

        # Admin (A) assigns to Artist B via the dept API.
        self._login(admin_acc)
        res = self.client.post(
            f"/vfx-department/{proj.id}/api/shots/{sh.id}",
            json={"assigned_artist_user_id": b_user.id},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))

        notifs = (
            db.session.query(self.M["Notification"])
            .filter_by(entity_type="vfx_shot", entity_id=sh.id)
            .all()
        )
        notified_user_ids = sorted(int(n.user_id) for n in notifs)
        self.assertEqual(
            notified_user_ids,
            [int(b_user.id)],
            f"Only the new artist should be notified, got {notified_user_ids}",
        )

    def test_editor_approve_notifies_artist_and_supervisor(self) -> None:
        """Approve on /projects/<id>/vfx → notify assigned artist + supervisor only."""
        admin_acc, proj = self._team_admin_setup()
        # Artist + supervisor on team.
        artist_jt = self.M["JobTitle"](name="VFX Artist")
        sup_jt = self.M["JobTitle"](name="VFX Supervisor")
        db.session.add_all([artist_jt, sup_jt])
        db.session.flush()
        a_acc = self._make_account("artist-x@example.com")
        a_user = self._make_user("Artist X", account=a_acc, job_title=artist_jt)
        s_acc = self._make_account("sup-x@example.com")
        s_user = self._make_user(
            "Sup X", account=s_acc, job_title=sup_jt
        )
        # An unrelated team member who must NOT be notified anymore.
        other_acc = self._make_account("other@example.com")
        other_user = self._make_user("Other", account=other_acc)
        for u in (a_user, s_user, other_user):
            db.session.add(
                self.M["ProjectMember"](project_id=proj.id, user_id=u.id)
            )
        sh = self._make_shot(
            project=proj,
            code="SH-APR",
            sent=True,
            mgmt_status="review",
            editor_status="review",
        )
        sh.assigned_artist_user_id = a_user.id
        sh.assigned_supervisor_user_id = s_user.id
        db.session.commit()

        self._login(admin_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}",
            json={"status": "approved"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))

        notifs = (
            db.session.query(self.M["Notification"])
            .filter_by(entity_type="vfx_shot", entity_id=sh.id)
            .all()
        )
        notified_user_ids = sorted(int(n.user_id) for n in notifs)
        self.assertEqual(
            notified_user_ids,
            sorted([int(a_user.id), int(s_user.id)]),
            f"Only artist + supervisor should be notified, got {notified_user_ids}",
        )

    def test_editor_approve_skips_actor_self_notification(self) -> None:
        """The actor who clicks Approve is never notified about their own action."""
        admin_acc, proj = self._team_admin_setup()
        admin_user = (
            db.session.query(self.M["User"])
            .filter_by(account_id=admin_acc.id)
            .first()
        )
        # Admin is the assigned supervisor → as actor they must be skipped.
        artist_acc = self._make_account("artist-y@example.com")
        artist_user = self._make_user("Artist Y", account=artist_acc)
        db.session.add(
            self.M["ProjectMember"](project_id=proj.id, user_id=artist_user.id)
        )
        sh = self._make_shot(
            project=proj,
            code="SH-SELF-APR",
            sent=True,
            mgmt_status="review",
            editor_status="review",
        )
        sh.assigned_artist_user_id = artist_user.id
        sh.assigned_supervisor_user_id = admin_user.id
        db.session.commit()

        self._login(admin_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}",
            json={"status": "approved"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))

        notifs = (
            db.session.query(self.M["Notification"])
            .filter_by(entity_type="vfx_shot", entity_id=sh.id)
            .all()
        )
        notified_user_ids = sorted(int(n.user_id) for n in notifs)
        self.assertEqual(
            notified_user_ids,
            [int(artist_user.id)],
            "Actor (admin = supervisor) must be excluded; only artist gets notified.",
        )

    def test_self_assignment_creates_no_notification(self) -> None:
        """User A assigning a shot to themselves produces zero notifications."""
        admin_acc, proj = self._team_admin_setup()
        # Make the admin a directory user too (already via _team_admin_setup).
        admin_user = (
            db.session.query(self.M["User"])
            .filter_by(account_id=admin_acc.id)
            .first()
        )
        sh = self._make_shot(
            project=proj,
            code="SH-SELF",
            sent=True,
            mgmt_status="pending",
            editor_status="sent",
        )
        db.session.commit()

        self._login(admin_acc)
        res = self.client.post(
            f"/vfx-department/{proj.id}/api/shots/{sh.id}",
            json={"assigned_artist_user_id": admin_user.id},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))

        n = (
            db.session.query(self.M["Notification"])
            .filter_by(entity_type="vfx_shot", entity_id=sh.id)
            .count()
        )
        self.assertEqual(n, 0, "Self-assignment must not create any notification")

    # ------------------------------------------------------------------
    # Editor versions route locked down for sent shots
    # ------------------------------------------------------------------

    def test_editor_versions_rejects_unrelated_artist_for_sent_shot(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        artist_jt = self.M["JobTitle"](name="VFX Artist")
        db.session.add(artist_jt)
        db.session.flush()
        # Two artists, both on team.
        a1_acc = self._make_account("a1@example.com")
        a1_user = self._make_user("A1", account=a1_acc, job_title=artist_jt)
        a2_acc = self._make_account("a2@example.com")
        a2_user = self._make_user("A2", account=a2_acc, job_title=artist_jt)
        for u in (a1_user, a2_user):
            db.session.add(
                self.M["ProjectMember"](project_id=proj.id, user_id=u.id)
            )
        sh = self._make_shot(
            project=proj,
            code="SH-V",
            sent=True,
            mgmt_status="assigned",
            editor_status="sent",
        )
        sh.assigned_artist_user_id = a1_user.id
        db.session.commit()

        # Artist A2 (not assigned) tries to upload a version through the
        # editor route — must be rejected by the new dept-permission check.
        self._login(a2_acc)
        res = self.client.post(
            f"/projects/{proj.id}/vfx/api/shots/{sh.id}/versions",
            data={"comment": "sneak"},
        )
        self.assertEqual(res.status_code, 403, res.get_data(as_text=True))
        self.assertEqual(res.get_json().get("error"), "forbidden")

    # ------------------------------------------------------------------
    # Project-wide VFX discussion (separate Discussion section on /projects/<id>/vfx)
    # ------------------------------------------------------------------

    def test_project_discussion_post_and_list_round_trip(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        self._login(admin_acc)

        # Empty by default.
        r0 = self.client.get(f"/projects/{proj.id}/vfx/api/discussion")
        self.assertEqual(r0.status_code, 200)
        self.assertEqual(r0.get_json(), {"ok": True, "messages": []})

        # Post a message.
        r1 = self.client.post(
            f"/projects/{proj.id}/vfx/api/discussion",
            json={"body": "Kickoff thread — hello team."},
        )
        self.assertEqual(r1.status_code, 200, r1.get_data(as_text=True))
        body = r1.get_json()
        self.assertTrue(body.get("ok"))
        msg = body.get("message") or {}
        self.assertGreater(int(msg.get("id") or 0), 0)
        self.assertEqual(msg.get("body"), "Kickoff thread — hello team.")
        self.assertTrue(msg.get("userName"))

        # And it shows up on subsequent GETs.
        r2 = self.client.get(f"/projects/{proj.id}/vfx/api/discussion")
        self.assertEqual(r2.status_code, 200)
        msgs = r2.get_json().get("messages") or []
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].get("body"), "Kickoff thread — hello team.")

    def test_project_discussion_rejects_empty_and_oversized_body(self) -> None:
        admin_acc, proj = self._team_admin_setup()
        self._login(admin_acc)

        r_empty = self.client.post(
            f"/projects/{proj.id}/vfx/api/discussion", json={"body": "   "}
        )
        self.assertEqual(r_empty.status_code, 400)
        self.assertEqual(r_empty.get_json().get("error"), "empty_body")

        # 20_001 chars is over the cap.
        r_big = self.client.post(
            f"/projects/{proj.id}/vfx/api/discussion",
            json={"body": "a" * 20_001},
        )
        self.assertEqual(r_big.status_code, 400)
        self.assertEqual(r_big.get_json().get("error"), "body_too_long")

    def test_project_discussion_forbidden_for_non_member(self) -> None:
        # Set up a project — admin is a member via _team_admin_setup.
        _admin_acc, proj = self._team_admin_setup()
        # An outsider account with no team membership and no admin role.
        outsider_acc = self._make_account("outsider@example.com")
        # No User row + no ProjectMember row => not a member.
        self._login(outsider_acc)

        r_get = self.client.get(f"/projects/{proj.id}/vfx/api/discussion")
        self.assertEqual(r_get.status_code, 403)

        r_post = self.client.post(
            f"/projects/{proj.id}/vfx/api/discussion",
            json={"body": "Sneak"},
        )
        self.assertEqual(r_post.status_code, 403)

    def test_project_discussion_in_editor_payload(self) -> None:
        """Bootstrap payload exposes the latest messages for the editor page."""
        admin_acc, proj = self._team_admin_setup()
        self._login(admin_acc)
        # Seed two messages directly.
        for body in ("first message", "second message"):
            r = self.client.post(
                f"/projects/{proj.id}/vfx/api/discussion",
                json={"body": body},
            )
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

        payload = self.H["build_vfx_editor_payload"](proj)
        msgs = payload.get("discussion") or []
        self.assertEqual(len(msgs), 2)
        # Sorted oldest -> newest, so the kickoff message comes first.
        self.assertEqual(msgs[0].get("body"), "first message")
        self.assertEqual(msgs[-1].get("body"), "second message")


if __name__ == "__main__":
    unittest.main()
