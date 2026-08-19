"""Player weapon overlay and per-character muzzle configuration."""

from __future__ import annotations

import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"


class ProducerHuntWeaponOverlayTests(unittest.TestCase):
    def test_assistant_disables_overlay_and_has_anim_muzzles(self):
        chars = (JS / "characters.js").read_text()
        player = (JS / "player.js").read_text()
        catalog = (JS / "asset-catalog.js").read_text()
        self.assertIn("renderWeaponOverlay: false", chars)
        self.assertIn('id: "assistant"', chars)
        self.assertIn("shoot: { x: 52, y: -184 }", chars)
        self.assertIn("crouch_shoot: { x: 66, y: -128 }", chars)
        self.assertIn("anchorX: 0.5", chars)
        self.assertIn("anchorY: 1.0", chars)
        self.assertIn("if (!this.character.renderWeaponOverlay) return", player)
        self.assertIn("renderScale()", player)
        self.assertIn("this.footX + this.facing * sx", player)
        self.assertIn("this.footY + sy", player)
        self.assertIn("fireFrameByAnim", player)
        self.assertNotIn('this.character.id === "assistant"', player)
        self.assertIn("weapons/player_weapons.png", catalog)
        self.assertIn("shoot: { x: 71, y: -186 }", chars)
        self.assertIn("shoot: { x: 62, y: -176 }", chars)
        self.assertIn("shoot: { x: 58, y: -196 }", chars)


if __name__ == "__main__":
    unittest.main()
