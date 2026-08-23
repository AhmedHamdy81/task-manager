"""Player shots must overlap enemy torso hitboxes, not the full 256 frame."""

from __future__ import annotations

import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"


def aabb(a, b):
    return a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] and a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"]


class ProducerHuntCombatHitsTests(unittest.TestCase):
    def test_standing_muzzle_overlaps_torso_not_short_box(self):
        foot_y = 960
        hit_h = 20
        x = 800
        stand_muzzle_y = foot_y - 184
        shot = {"x": x, "y": stand_muzzle_y - hit_h / 2, "w": 32, "h": hit_h}
        old_client = {"x": x, "y": foot_y - 152, "w": 54, "h": 152}
        torso = {"x": x, "y": foot_y - 210, "w": 54, "h": 210}
        self.assertFalse(aabb(shot, old_client), "short 152px box sits below the barrel")
        self.assertTrue(aabb(shot, torso), "210px torso must catch standing shots")

        crouch_muzzle_y = foot_y - 128
        crouch_shot = {"x": x, "y": crouch_muzzle_y - hit_h / 2, "w": 32, "h": hit_h}
        self.assertTrue(aabb(crouch_shot, torso))

        old_pp = {"x": x, "y": foot_y - 170, "w": 88, "h": 170}
        self.assertFalse(aabb(shot, old_pp), "170px PP box missed the raised muzzle")
        pp = {"x": x, "y": foot_y - 210, "w": 88, "h": 210}
        self.assertTrue(aabb(shot, pp))

        colorist = {"x": x, "y": foot_y - 196 - hit_h / 2, "w": 32, "h": hit_h}
        self.assertTrue(aabb(colorist, torso), "colorist barrel at -196 must still overlap")

    def test_hit_path_uses_existing_aabb_not_phaser(self):
        game = (JS / "game.js").read_text()
        projectile = (JS / "projectile.js").read_text()
        enemy = (JS / "enemy.js").read_text()
        spec = (JS / "sprite-spec.js").read_text()
        player = (JS / "player.js").read_text()
        self.assertIn("handlePlayerProjectileHit", game)
        self.assertIn("travelBounds", game)
        self.assertIn("projectile.hasHit", game)
        self.assertIn("enemy.takeDamage", game)
        self.assertIn("if (!enemy.alive) continue", game)
        self.assertNotIn("physics.add.overlap", game)
        self.assertNotIn("arcade", game)
        self.assertIn("this.hasHit = false", projectile)
        self.assertIn("disable()", projectile)
        self.assertIn("takeDamage(amount)", enemy)
        self.assertIn("collisionHeight: 210", spec)
        self.assertIn("collisionHeight: 210", enemy)
        self.assertIn("muzzleByAnim", player)
        self.assertIn("renderWeaponOverlay", player)
        self.assertNotIn("if (this.character.id", player)
