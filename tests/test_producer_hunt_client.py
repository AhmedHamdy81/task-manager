"""The Client enemy is a second type; studio_01 stays Post Producer only."""

from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "assets"
JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"

CLIENT_ANIMS = {
    "idle": 6,
    "walk": 8,
    "attack": 4,
    "hit": 3,
    "death": 6,
}


class ProducerHuntClientTests(unittest.TestCase):
    def test_client_strips_match_spec(self):
        root = ROOT / "enemies" / "client"
        for anim, frames in CLIENT_ANIMS.items():
            path = root / "sprites" / f"client_{anim}.png"
            self.assertTrue(path.is_file(), str(path))
            with Image.open(path) as img:
                self.assertEqual(img.size, (256 * frames, 256), msg=path.name)
        impact = root / "effects" / "client_attack_impact.png"
        self.assertTrue(impact.is_file(), str(impact))
        with Image.open(impact) as img:
            self.assertEqual(img.size, (512, 128))

    def test_registry_behavior_and_projectile(self):
        enemy = (JS / "enemy.js").read_text()
        combat = (JS / "combat.js").read_text()
        catalog = (JS / "asset-catalog.js").read_text()
        self.assertIn("client:", enemy)
        self.assertIn('name: "The Client"', enemy)
        self.assertIn('behavior: "cautious_ranged"', enemy)
        self.assertIn("artFacing: -1", enemy)
        self.assertIn("preferredRange: 380", enemy)
        self.assertIn("minRetreatRange: 190", enemy)
        self.assertIn("collisionWidth: 54", enemy)
        self.assertIn("collisionHeight: 152", enemy)
        self.assertIn("_updateCautiousRanged", enemy)
        self.assertIn("_canStep", enemy)
        self.assertIn("_applyFacingFlip", enemy)
        self.assertNotIn('client: "post_producer"', enemy)
        self.assertIn('client: "client_revision_pulse"', combat)
        self.assertIn("client_revision_pulse:", combat)
        self.assertIn("hitH: 18", combat)
        self.assertIn("speed: 420", combat)
        self.assertIn("cooldown: 1.5", combat)
        self.assertIn('sheetKey: "client_impact"', combat)
        self.assertIn("enemies/client/effects/client_attack_impact.png", catalog)
        self.assertNotIn("assistant_producer/", enemy)
        self.assertNotIn("enemies/assistant_producer", catalog)

    def test_studio_01_client_test_and_studio_02_mixed(self):
        s1 = (JS / "levels" / "studio-01.js").read_text()
        s2 = (JS / "levels" / "studio-02.js").read_text()
        index = (JS / "levels" / "level-01.js").read_text()
        game = (JS / "game.js").read_text()
        self.assertIn('id: "studio_01_client_test_01"', s1)
        self.assertIn('type: "client"', s1)
        self.assertIn("enc_client_test", s1)
        self.assertEqual(s1.count('type: "post_producer"'), 5)
        self.assertIn('id: "studio_02"', s2)
        self.assertIn('name: "Client Review"', s2)
        self.assertIn('type: "client"', s2)
        self.assertIn('type: "post_producer"', s2)
        self.assertIn("enc_intro_client", s2)
        self.assertIn("enc_mixed_early", s2)
        self.assertIn("enc_final", s2)
        self.assertIn("STUDIO_02", index)
        self.assertIn("nextLevelId", index)
        self.assertIn("resolveLevel", game)
        self.assertIn("loadEnemyKit(ENEMY_TYPES.client.sprite)", game)
        self.assertIn("advanceToNextLevel", game)
        self.assertIn("ENEMY_TYPES.post_producer", game)
        self.assertIn("[Producer Hunt] Spawned enemy:", game)
        self.assertNotIn("the_client", (JS / "enemy.js").read_text())
        self.assertNotIn("client_enemy", (JS / "enemy.js").read_text())


if __name__ == "__main__":
    unittest.main()
