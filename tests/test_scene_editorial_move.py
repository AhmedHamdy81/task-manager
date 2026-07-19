"""Regression tests for Scene Editorial MOVE membership (primary-only).

A scene's effective editorial episode is decided ONLY by its active PRIMARY
assignment::

    effective_editorial_episode =
        active_primary_assignment.editorial_episode_number
        if an active primary assignment exists
        else production_episode

The production origin (ShootingDayScene.episode_number) never changes.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_editorial_move.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db  # noqa: E402


class SceneEditorialMoveTests(unittest.TestCase):
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

        self.move = self.H["move_scene_to_editorial_episode"]
        self.repair = self.H["repair_scene_editorial_primary_assignments"]
        self.build_stats = self.H["build_editorial_episode_statistics"]
        self.SEA = M["SceneEditorialAssignment"]

        p = M["Project"](
            name="Move Project",
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

        # Five scenes shot for production episode 2 (60s each).
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
        # One scene shot for production episode 6.
        self.scene_ep6 = M["ShootingDayScene"](
            shooting_day_id=day.id,
            episode_number=6,
            scene_label="S6",
            scene_number=6,
            duration_seconds=60,
            runtime_selected=True,
        )
        db.session.add(self.scene_ep6)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def _ids(self, ep):
        return set(self.build_stats(self.project, ep)["scene_ids"])

    def _add_primary(self, scene_id, ep, *, active=True, added_at=None):
        row = self.SEA(
            project_id=self.project.id,
            scene_id=int(scene_id),
            editorial_episode_number=int(ep),
            is_primary=True,
            display_order=0,
            added_at=added_at or dt.datetime(2026, 1, 1, 0, 0, 0),
            reason="",
            notes="",
            is_active=bool(active),
        )
        db.session.add(row)
        db.session.commit()
        return row

    # 1. Scene with no assignment appears in its production episode.
    def test_no_assignment_appears_in_production_episode(self):
        self.assertEqual(
            self._ids(2), {sc.id for sc in self.scenes}
        )
        self.assertEqual(self._ids(6), {self.scene_ep6.id})

    # 2. Scene moved from Episode 2 to Episode 6 appears only in Episode 6.
    def test_move_2_to_6(self):
        moved = self.scenes[0]
        self.move(self.project.id, moved.id, 6)
        self.assertNotIn(moved.id, self._ids(2))
        self.assertIn(moved.id, self._ids(6))
        self.assertEqual(len(self._ids(2)), 4)
        # Production origin unchanged.
        db.session.refresh(moved)
        self.assertEqual(moved.episode_number, 2)

    # 3. Scene moved 6 -> 5 deactivates the old Episode-6 assignment.
    def test_move_6_then_5_deactivates_old(self):
        sc = self.scenes[1]
        self.move(self.project.id, sc.id, 6)
        self.move(self.project.id, sc.id, 5)
        row6 = self.SEA.query.filter_by(scene_id=sc.id, editorial_episode_number=6).first()
        row5 = self.SEA.query.filter_by(scene_id=sc.id, editorial_episode_number=5).first()
        self.assertIsNotNone(row6)
        self.assertFalse(row6.is_active)
        self.assertTrue(row5.is_active)
        self.assertTrue(row5.is_primary)
        self.assertIn(sc.id, self._ids(5))
        self.assertNotIn(sc.id, self._ids(6))
        self.assertNotIn(sc.id, self._ids(2))
        # Exactly one active primary for this scene.
        self.assertEqual(
            self.SEA.query.filter_by(scene_id=sc.id, is_active=True, is_primary=True).count(),
            1,
        )

    # 4. Scene moved back to Episode 2 deactivates all primaries.
    def test_move_back_to_origin(self):
        sc = self.scenes[2]
        self.move(self.project.id, sc.id, 6)
        self.assertNotIn(sc.id, self._ids(2))
        # Move back to production origin (episode 2).
        self.move(self.project.id, sc.id, 2)
        self.assertEqual(
            self.SEA.query.filter_by(scene_id=sc.id, is_active=True, is_primary=True).count(),
            0,
        )
        self.assertIn(sc.id, self._ids(2))
        self.assertNotIn(sc.id, self._ids(6))

    # 5. A primary assignment to the scene's OWN production episode must not
    #    make it disappear.
    def test_primary_to_own_production_episode_keeps_scene(self):
        sc = self.scenes[3]
        self._add_primary(sc.id, 2)  # points at its own origin
        self.assertIn(sc.id, self._ids(2))
        self.assertEqual(len(self._ids(2)), 5)

    # 6. Multiple stale active primaries -> repair keeps only the newest.
    def test_repair_keeps_newest_primary(self):
        sc = self.scenes[4]
        self._add_primary(sc.id, 5, added_at=dt.datetime(2026, 1, 1, 10, 0, 0))
        self._add_primary(sc.id, 6, added_at=dt.datetime(2026, 1, 2, 10, 0, 0))  # newer
        report = self.repair(self.project.id)
        self.assertGreaterEqual(report["repaired_rows"], 1)
        active = self.SEA.query.filter_by(
            scene_id=sc.id, is_active=True, is_primary=True
        ).all()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].editorial_episode_number, 6)
        self.assertIn(sc.id, self._ids(6))
        self.assertNotIn(sc.id, self._ids(5))
        self.assertNotIn(sc.id, self._ids(2))

    # 6b. Repair deactivates primaries pointing at the scene's own origin.
    def test_repair_drops_origin_primary(self):
        sc = self.scenes[0]
        self._add_primary(sc.id, 2)  # origin primary (redundant)
        self.repair(self.project.id)
        self.assertEqual(
            self.SEA.query.filter_by(scene_id=sc.id, is_active=True, is_primary=True).count(),
            0,
        )
        self.assertIn(sc.id, self._ids(2))

    # 7. Episode List and Episode Detail return identical scene IDs and runtime.
    def test_list_and_detail_identical(self):
        self.move(self.project.id, self.scenes[0].id, 6)
        self.move(self.project.id, self.scenes[1].id, 6)
        self.move(self.project.id, self.scene_ep6.id, 5)

        M = self.M
        for ep in range(1, 7):
            prod_rows = (
                M["ShootingDayScene"].query.join(
                    M["ShootingDay"],
                    M["ShootingDayScene"].shooting_day_id == M["ShootingDay"].id,
                )
                .filter(
                    M["ShootingDay"].project_id == self.project.id,
                    M["ShootingDayScene"].episode_number == ep,
                )
                .all()
            )
            list_side = self.build_stats(self.project, ep, production_rows=prod_rows)
            detail_side = self.build_stats(self.project, ep)
            self.assertEqual(
                sorted(list_side["scene_ids"]),
                sorted(detail_side["scene_ids"]),
                f"scene id mismatch for episode {ep}",
            )
            self.assertEqual(
                list_side["runtime_seconds"],
                detail_side["runtime_seconds"],
                f"runtime mismatch for episode {ep}",
            )

    # Extra: the five-scenes-to-Episode-6 scenario zeroes out Episode 2.
    def test_all_five_moved_to_six(self):
        for sc in self.scenes:
            self.move(self.project.id, sc.id, 6)
        s2 = self.build_stats(self.project, 2)
        self.assertEqual(s2["scene_count"], 0)
        self.assertEqual(s2["runtime_seconds"], 0)
        self.assertEqual(s2["runtime_display"], "0:00")
        self.assertEqual(s2["original_scene_count"], 0)
        self.assertEqual(s2["assigned_scene_count"], 0)
        s6 = self.build_stats(self.project, 6)
        # Episode 6 keeps its own origin scene plus the five moved in.
        self.assertEqual(s6["scene_count"], 6)
        self.assertEqual(
            set(s6["scene_ids"]),
            {sc.id for sc in self.scenes} | {self.scene_ep6.id},
        )
        # Split counts: 1 original (S6) + 5 assigned-in (moved from Ep2).
        self.assertEqual(s6["original_scene_count"], 1)
        self.assertEqual(s6["assigned_scene_count"], 5)


if __name__ == "__main__":
    unittest.main()
