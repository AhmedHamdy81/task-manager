"""VFX portal must follow a scene's effective editorial episode.

The VFX portal groups scenes/shots by::

    effective_editorial_episode =
        active_primary_editorial_assignment.target_episode
        if one exists
        else production_episode

while the production origin (ShootingDayScene.episode_number) stays immutable
and no VFX shots/versions are duplicated or lost when a scene moves.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_vfx_editorial.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db  # noqa: E402


class VfxEditorialMembershipTests(unittest.TestCase):
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
            "VfxVersion",
            "VfxShot",
            "VfxSceneItemSource",
            "VfxSceneItem",
            "SceneEditorialAssignment",
            "ShootingDayScene",
            "ShootingDay",
            "Project",
        ):
            db.session.query(M[name]).delete()
        db.session.commit()

        self.move = self.H["move_scene_to_editorial_episode"]
        self.eff = self.H["get_effective_editorial_episode"]
        self.build_payload = self.H["build_vfx_editor_payload"]
        self.build_stats = self.H["build_editorial_episode_statistics"]
        self.diagnose = self.H["diagnose_vfx_editorial_consistency"]

        p = M["Project"](
            name="VFX Editorial",
            project_type="tv_series",
            production_house="H",
            director="D",
            number_of_episodes=6,
        )
        db.session.add(p)
        db.session.flush()
        self.project = p
        self.day = M["ShootingDay"](
            project_id=p.id,
            unit_number=1,
            shooting_date=dt.date(2026, 1, 1),
        )
        db.session.add(self.day)
        db.session.flush()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    # ---- builders ----------------------------------------------------
    def _scene(self, ep, num, label=None):
        sc = self.M["ShootingDayScene"](
            shooting_day_id=self.day.id,
            episode_number=ep,
            scene_label=label or f"Scene {num}",
            scene_number=num,
            duration_seconds=60,
            runtime_selected=True,
            needs_vfx=True,
        )
        db.session.add(sc)
        db.session.flush()
        return sc

    def _vfx_item(self, scenes, *, episode_number, n_shots=0, name="VFX Item"):
        if not isinstance(scenes, (list, tuple)):
            scenes = [scenes]
        item = self.M["VfxSceneItem"](
            project_id=self.project.id,
            episode_number=episode_number,
            display_name=name,
            item_type="scene",
            status="pending",
            is_active=True,
        )
        db.session.add(item)
        db.session.flush()
        for sc in scenes:
            db.session.add(
                self.M["VfxSceneItemSource"](
                    vfx_scene_item_id=item.id,
                    shooting_day_scene_id=sc.id,
                    is_active=True,
                )
            )
        shot_ids, version_ids = [], []
        primary = scenes[0]
        for i in range(1, n_shots + 1):
            sh = self.M["VfxShot"](
                project_id=self.project.id,
                scene_id=primary.id,
                vfx_scene_item_id=item.id,
                shot_number=i,
                shot_code=f"E{primary.episode_number}_SC{primary.scene_number:02d}_SH{i*10:03d}",
                status="in_progress",
                mgmt_status="pending",
                priority="medium",
                shot_briefing="",
            )
            db.session.add(sh)
            db.session.flush()
            shot_ids.append(int(sh.id))
            v = self.M["VfxVersion"](shot_id=sh.id, version_number=1, image="", comment="")
            db.session.add(v)
            db.session.flush()
            version_ids.append(int(v.id))
        db.session.commit()
        return item, shot_ids, version_ids

    # ---- payload helpers --------------------------------------------
    def _payload_scene(self, scene_id):
        payload = self.build_payload(self.project)
        for s in payload["scenes"]:
            if int(s["id"]) == int(scene_id):
                return s, payload
        return None, payload

    def _group_key(self, scene_id):
        s, _ = self._payload_scene(scene_id)
        return None if s is None else int(s["groupKey"])

    def _scene_ids_in_group(self, payload, key):
        for g in payload["groups"]:
            if int(g["key"]) == int(key):
                return {int(s["id"]) for s in g["scenes"]}
        return set()

    # ---- tests -------------------------------------------------------
    # 1. Scene with VFX and no editorial assignment: under production episode.
    def test_no_assignment_under_production_episode(self):
        sc = self._scene(2, 1)
        self._vfx_item(sc, episode_number=2, n_shots=3)
        s, _ = self._payload_scene(sc.id)
        self.assertEqual(int(s["groupKey"]), 2)
        self.assertEqual(int(s["originalEpisodeNumber"]), 2)
        self.assertFalse(s["movedFromOriginalEpisode"])

    # 2. Scene moved 2 -> 6: only under Episode 6, origin stays 2.
    def test_moved_2_to_6(self):
        sc = self._scene(2, 1)
        self._vfx_item(sc, episode_number=2, n_shots=3)
        self.move(self.project.id, sc.id, 6)
        s, payload = self._payload_scene(sc.id)
        self.assertEqual(int(s["groupKey"]), 6)
        self.assertEqual(int(s["originalEpisodeNumber"]), 2)
        self.assertTrue(s["movedFromOriginalEpisode"])
        self.assertIn(sc.id, self._scene_ids_in_group(payload, 6))
        self.assertNotIn(sc.id, self._scene_ids_in_group(payload, 2))
        # Production origin untouched.
        db.session.refresh(sc)
        self.assertEqual(sc.episode_number, 2)

    # 3. Scene moved again 6 -> 5: disappears from 6, appears in 5.
    def test_moved_6_then_5(self):
        sc = self._scene(2, 1)
        self._vfx_item(sc, episode_number=2, n_shots=2)
        self.move(self.project.id, sc.id, 6)
        self.move(self.project.id, sc.id, 5)
        self.assertEqual(self._group_key(sc.id), 5)
        _, payload = self._payload_scene(sc.id)
        self.assertNotIn(sc.id, self._scene_ids_in_group(payload, 6))
        self.assertIn(sc.id, self._scene_ids_in_group(payload, 5))

    # 4. Scene moved back to 2: appears under 2 again, origin unchanged.
    def test_moved_back_to_2(self):
        sc = self._scene(2, 1)
        self._vfx_item(sc, episode_number=2, n_shots=2)
        self.move(self.project.id, sc.id, 6)
        self.move(self.project.id, sc.id, 2)
        s, _ = self._payload_scene(sc.id)
        self.assertEqual(int(s["groupKey"]), 2)
        self.assertFalse(s["movedFromOriginalEpisode"])

    # 5. 8 shots move with the scene; shot + version IDs stay stable.
    def test_eight_shots_move_with_scene(self):
        sc = self._scene(2, 1)
        _, shot_ids, version_ids = self._vfx_item(sc, episode_number=2, n_shots=8)
        before, _ = self._payload_scene(sc.id)
        self.assertEqual(before["shotCount"], 8)
        ids_before = sorted(int(x["id"]) for x in before["shots"])
        vids_before = sorted(int(v["id"]) for sh in before["shots"] for v in sh["versions"])

        self.move(self.project.id, sc.id, 6)
        after, _ = self._payload_scene(sc.id)
        self.assertEqual(int(after["groupKey"]), 6)
        self.assertEqual(after["shotCount"], 8)
        self.assertEqual(sorted(int(x["id"]) for x in after["shots"]), ids_before)
        self.assertEqual(sorted(shot_ids), ids_before)
        vids_after = sorted(int(v["id"]) for sh in after["shots"] for v in sh["versions"])
        self.assertEqual(vids_after, vids_before)
        self.assertEqual(vids_after, sorted(version_ids))

    # 6. One VFX item with two scenes moved to different episodes = mixed,
    #    no DB duplication, unique totals preserved.
    def test_multi_scene_item_mixed(self):
        a = self._scene(2, 1)
        b = self._scene(2, 2)
        item, shot_ids, _ = self._vfx_item([a, b], episode_number=2, n_shots=4)
        items_before = self.M["VfxSceneItem"].query.filter_by(
            project_id=self.project.id, is_active=True
        ).count()
        # Move only scene A to Episode 6 -> sources resolve to {6, 2} = mixed.
        self.move(self.project.id, a.id, 6)
        s, _ = self._payload_scene(a.id)
        self.assertTrue(s["mixedSourceEpisodes"])
        # No duplication of the underlying item.
        self.assertEqual(
            self.M["VfxSceneItem"].query.filter_by(
                project_id=self.project.id, is_active=True
            ).count(),
            items_before,
        )
        # Shots are not duplicated.
        self.assertEqual(
            self.M["VfxShot"].query.filter_by(project_id=self.project.id).count(),
            len(shot_ids),
        )

    # 6b. Both scenes moved together -> whole item under Episode 6, not mixed.
    def test_multi_scene_item_moved_together(self):
        a = self._scene(2, 1)
        b = self._scene(2, 2)
        self._vfx_item([a, b], episode_number=2, n_shots=2)
        self.move(self.project.id, a.id, 6)
        self.move(self.project.id, b.id, 6)
        s, _ = self._payload_scene(a.id)
        self.assertEqual(int(s["groupKey"]), 6)
        self.assertFalse(s["mixedSourceEpisodes"])

    # 7. Episode detail and VFX portal resolve the same effective episode.
    def test_detail_and_portal_agree(self):
        sc = self._scene(2, 1)
        self._vfx_item(sc, episode_number=2, n_shots=8)
        self.move(self.project.id, sc.id, 6)
        self.assertEqual(self.eff(sc), 6)
        self.assertEqual(self._group_key(sc.id), 6)
        stats6 = self.build_stats(self.project, 6)
        self.assertIn(sc.id, stats6["scene_ids"])
        stats2 = self.build_stats(self.project, 2)
        self.assertNotIn(sc.id, stats2["scene_ids"])

    # 8. VFX stats match the portal shot counts per episode.
    def test_stats_match_portal_counts(self):
        sc = self._scene(2, 1)
        self._vfx_item(sc, episode_number=2, n_shots=8)
        self.move(self.project.id, sc.id, 6)
        stats2 = self.build_stats(self.project, 2)
        stats6 = self.build_stats(self.project, 6)
        self.assertEqual(stats2["vfx_shot_count"], 0)
        self.assertEqual(stats2["vfx_item_count"], 0)
        self.assertEqual(stats6["vfx_shot_count"], 8)
        s, _ = self._payload_scene(sc.id)
        self.assertEqual(s["shotCount"], stats6["vfx_shot_count"])

    # Diagnostic surfaces a stale VfxSceneItem.episode_number cache.
    def test_diagnostic_reports_stale_cache(self):
        sc = self._scene(2, 1)
        self._vfx_item(sc, episode_number=2, n_shots=1)
        self.move(self.project.id, sc.id, 6)  # cache stays 2, editorial is 6
        report = self.diagnose(self.project.id)
        self.assertFalse(report["clean"])
        stale = {r["item_id"]: r for r in report["stale_episode_cache"]}
        self.assertTrue(stale)
        any_row = next(iter(stale.values()))
        self.assertEqual(any_row["cached_episode_number"], 2)
        self.assertEqual(any_row["resolved_editorial_episode"], 6)


if __name__ == "__main__":
    unittest.main()
