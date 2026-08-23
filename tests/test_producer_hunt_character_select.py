"""Producer Hunt cinematic character-select menu wiring."""

from __future__ import annotations

import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"


class ProducerHuntCharacterSelectTests(unittest.TestCase):
    def setUp(self):
        self.select = (JS / "character-select.js").read_text()
        self.characters = (JS / "characters.js").read_text()
        self.abilities = (JS / "abilities.js").read_text()
        self.combat = (JS / "combat.js").read_text()
        self.progress = (JS / "progression.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.loader = (JS / "asset-loader.js").read_text()

    def test_select_layout_and_data_hooks(self):
        self.assertIn("SELECT CHARACTER", self.select)
        self.assertIn("WEAPON", self.select)
        self.assertIn("SPECIAL POWER", self.select)
        self.assertIn("STATISTICS", self.select)
        self.assertIn("LOCKED", self.select)
        self.assertIn("COMING SOON", self.select)
        self.assertIn("SpriteAnimator", self.select)
        self.assertIn("previewAnimation", self.select)
        self.assertIn("characterSelectStats", self.select)
        self.assertIn("weaponSelectCopy", self.select)
        self.assertIn("abilityMenuInfo", self.select)
        self.assertIn("isCharacterUnlocked", self.select)
        self.assertIn("notifyLocked", self.select)
        self.assertIn("loadOptionalImage", self.select)
        self.assertIn("NO IMAGE", self.select)
        self.assertIn("wrapText", self.select)
        self.assertIn("ctx.clip()", self.select)
        self.assertIn("enter(", self.select)
        self.assertIn("leave(", self.select)
        self.assertNotIn("document.createElement", self.select)

    def test_character_config_and_unlocks(self):
        self.assertIn('role: "Balanced Fighter"', self.characters)
        self.assertIn('role: "Mobile Support"', self.characters)
        self.assertIn("previewAnimation: \"idle\"", self.characters)
        self.assertIn("export function rateStat", self.characters)
        self.assertIn("export function weaponSelectCopy", self.characters)
        self.assertIn("export const CHARACTER_UNLOCKS", self.progress)
        self.assertIn('label: "Defeat Boss 1"', self.progress)
        self.assertIn('label: "Complete Studio 02"', self.progress)
        self.assertIn("always: true", self.progress)
        self.assertIn("abilityImplemented", self.abilities)
        self.assertIn("SPECIAL_POWERS", self.abilities)
        self.assertIn("timeline_freeze", self.abilities)
        self.assertIn("production_rush", self.abilities)
        self.assertIn("color_blast", self.abilities)
        self.assertIn("particle_storm", self.abilities)
        self.assertIn("Cooldown", self.abilities)
        self.assertIn("weaponDefForCharacter", self.combat)
        self.assertIn("select.enter", self.game)
        self.assertIn("select.leave", self.game)
        self.assertIn("select.isUnlocked", self.game)
        self.assertIn("consume(\"shoot\")", self.game)
        self.assertIn("loadOptionalImage", self.loader)
        self.assertIn("NOT ENOUGH ENERGY", self.game)
        self.assertIn("cancelActivePowers", self.game)
        self.assertIn('special: ["KeyQ"]', (JS / "config.js").read_text())
        self.assertIn("CHARACTER_STATS", self.characters)
        self.assertIn("specialPowerId", self.characters)
        self.assertIn("ENEMY_MUZZLE", self.combat)
        self.assertIn("playerTorsoAim", self.combat)
        self.assertIn("CHARACTER_RENDER_SCALE", (JS / "sprite-spec.js").read_text())
        self.assertIn("PLAYER_BODY", (JS / "sprite-spec.js").read_text())
        self.assertNotIn("edit_blaster", self.characters)


if __name__ == "__main__":
    unittest.main()
