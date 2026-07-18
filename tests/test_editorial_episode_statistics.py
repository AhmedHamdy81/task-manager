"""Regression tests for the single authoritative editorial episode statistics.

`build_editorial_episode_statistics` is the ONE calculation consumed by both the
Episode List cards (`project_episodes`) and the Episode Detail page
(`_build_episode_detail_context`). These tests lock in that:

* an episode whose scenes are all editorially assigned elsewhere reports zero
  scene count / runtime / VFX (no stale production values),
* the target editorial episode inherits those scenes' runtime + VFX,
* production origin (`ShootingDayScene.episode_number`) is never mutated,
* results are stable across a fresh DB session (no cached browser/aggregate),
* VFX totals follow the active source links of the CURRENT editorial scenes,
  not the (stale) `VfxSceneItem.episode_number`.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_editorial_stats.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db  # noqa: E402


class EditorialEpisodeStatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()
        cls.M = app.extensions["tm_test_models"]
        cls.H = app.extensions["tm_test_helpers"]

    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        M = self.M
        for name in (
            "VfxSceneItemSource",
            "VfxShot",
            "VfxSceneItem",
            "SceneEditorialAssignment",
            "ShootingDayScene",
            "ShootingDay",
            "Project",
        ):
            db.session.query(M[name]).delete()
        db.session.commit()

        self.build_stats = self.H["build_editorial_episode_statistics"]
        self.assign = self.H["_assign_scene_editorial"]
        self.unassign = self.H["_unassign_scene_editorial"]
        self.origin_key = self.H["_scene_production_episode_key"]

        p = M["Project"](
            name="Editorial Stats Project",
            project_type="tv_series",
            production_house="House",
            director="Dir",
            number_of_episodes=6,
        )
        db.session.add(p)
        db.session.flush()
        self.project = p

        day = M["ShootingDay"](
            project_id=p.id,
            unit_number=1,
            shooting_date=dt.date(2026, 1, 1),
            location="Stage A",
        )
        db.session.add(day)
        db.session.flush()
        self.day = day

        # Five scenes shot for PRODUCTION episode 2, 60s each -> 300s runtime.
        self.scenes = []
        for i in range(1, 6):
            sc = M["ShootingDayScene"](
                shooting_day_id=day.id,
                episode_number=2,
                scene_label=f"S{i}",
                scene_number=i,
                duration_seconds=60,
                runtime_selected=True,
            )
            db.session.add(sc)
            self.scenes.append(sc)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    # ---- helpers --------------------------------------------------------
    def _stats(self, episode_number):
        # No production_rows passed -> the function re-queries membership itself
        # (exactly what the Episode List / Detail call sites do).
        return self.build_stats(self.project, episode_number)

    def _add_vfx(self, scene, *, item_episode_number, mgmt_status="pending"):
        M = self.M
        item = M["VfxSceneItem"](
            project_id=self.project.id,
            episode_number=item_episode_number,
            display_name="VFX A",
            is_active=True,
        )
        db.session.add(item)
        db.session.flush()
        db.session.add(
            M["VfxSceneItemSource"](
                vfx_scene_item_id=item.id,
                shooting_day_scene_id=scene.id,
                is_active=True,
            )
        )
        db.session.add(
            M["VfxShot"](
                project_id=self.project.id,
                scene_id=scene.id,
                vfx_scene_item_id=item.id,
                shot_number=1,
                shot_code=f"SH-{scene.id}",
                mgmt_status=mgmt_status,
            )
        )
        db.session.commit()
        return item

    def _assign_all_to(self, target_ep):
        for sc in self.scenes:
            self.assign(
                sc,
                target_ep,
                project=self.project,
                actor=None,
                reason="Director's cut",
                notify=False,
            )
        db.session.commit()

    # ---- tests ----------------------------------------------------------
    def test_baseline_all_scenes_in_origin_episode(self):
        s = self._stats(2)
        self.assertEqual(s["scene_count"], 5)
        self.assertEqual(s["runtime_seconds"], 300)
        self.assertEqual(s["runtime_display"], "5:00")
        self.assertEqual(sorted(s["scene_ids"]), sorted(sc.id for sc in self.scenes))

    def test_all_scenes_assigned_away_zero_out_origin(self):
        self._assign_all_to(6)

        origin = self._stats(2)
        self.assertEqual(origin["scene_count"], 0)
        self.assertEqual(origin["runtime_seconds"], 0)
        self.assertEqual(origin["runtime_display"], "0:00")
        self.assertEqual(origin["scene_ids"], [])
        self.assertEqual(origin["vfx_item_count"], 0)
        self.assertEqual(origin["scenes_with_vfx"], 0)
        self.assertEqual(origin["vfx_shot_count"], 0)
        self.assertEqual(origin["pending_vfx_count"], 0)

        target = self._stats(6)
        self.assertEqual(target["scene_count"], 5)
        self.assertEqual(target["runtime_seconds"], 300)
        self.assertEqual(sorted(target["scene_ids"]), sorted(sc.id for sc in self.scenes))

        # Production origin is immutable.
        for sc in self.scenes:
            db.session.refresh(sc)
            self.assertEqual(sc.episode_number, 2)
            self.assertEqual(self.origin_key(sc), 2)

    def test_move_one_scene_back_matches_between_recomputations(self):
        self._assign_all_to(6)
        # Move exactly one scene back to episode 2.
        self.unassign(
            self.scenes[0], 6, project=self.project, actor=None, reason="", notify=False
        )
        db.session.commit()

        origin = self._stats(2)
        self.assertEqual(origin["scene_count"], 1)
        self.assertEqual(origin["runtime_seconds"], 60)
        self.assertEqual(origin["scene_ids"], [self.scenes[0].id])

        target = self._stats(6)
        self.assertEqual(target["scene_count"], 4)
        self.assertEqual(target["runtime_seconds"], 240)

        # The "list" call site passes explicit production_rows; the "detail" call
        # site lets the function query. Both must yield identical membership.
        M = self.M
        prod_rows_ep2 = (
            M["ShootingDayScene"].query.join(
                M["ShootingDay"],
                M["ShootingDayScene"].shooting_day_id == M["ShootingDay"].id,
            )
            .filter(
                M["ShootingDay"].project_id == self.project.id,
                M["ShootingDayScene"].episode_number == 2,
            )
            .all()
        )
        list_side = self.build_stats(self.project, 2, production_rows=prod_rows_ep2)
        detail_side = self.build_stats(self.project, 2)
        self.assertEqual(
            sorted(list_side["scene_ids"]), sorted(detail_side["scene_ids"])
        )
        self.assertEqual(
            list_side["runtime_seconds"], detail_side["runtime_seconds"]
        )

    def test_stable_after_fresh_session(self):
        self._assign_all_to(6)
        project_id = self.project.id
        db.session.remove()  # drop the identity map / cached state
        self.project = db.session.get(self.M["Project"], project_id)
        origin = self._stats(2)
        target = self._stats(6)
        self.assertEqual(origin["scene_count"], 0)
        self.assertEqual(origin["runtime_seconds"], 0)
        self.assertEqual(target["scene_count"], 5)
        self.assertEqual(target["runtime_seconds"], 300)

    def test_vfx_follows_editorial_membership_not_stale_item_episode(self):
        # VFX item is stamped episode_number=2 (stale) but the scene is moved to 6.
        scene = self.scenes[0]
        self._add_vfx(scene, item_episode_number=2, mgmt_status="pending")

        before = self._stats(2)
        self.assertEqual(before["vfx_item_count"], 1)
        self.assertEqual(before["scenes_with_vfx"], 1)
        self.assertEqual(before["vfx_shot_count"], 1)
        self.assertEqual(before["pending_vfx_count"], 1)
        self.assertEqual(before["completed_vfx_count"], 0)

        self.assign(
            scene, 6, project=self.project, actor=None, reason="", notify=False
        )
        db.session.commit()

        origin = self._stats(2)
        self.assertEqual(origin["vfx_item_count"], 0)
        self.assertEqual(origin["scenes_with_vfx"], 0)
        self.assertEqual(origin["vfx_shot_count"], 0)
        self.assertEqual(origin["pending_vfx_count"], 0)

        # Episode 6 now owns the scene, so the VFX follows it even though the
        # VfxSceneItem.episode_number still says 2.
        target = self._stats(6)
        self.assertEqual(target["vfx_item_count"], 1)
        self.assertEqual(target["scenes_with_vfx"], 1)
        self.assertEqual(target["vfx_shot_count"], 1)
        self.assertEqual(target["pending_vfx_count"], 1)


if __name__ == "__main__":
    unittest.main()
