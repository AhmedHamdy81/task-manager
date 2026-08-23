"""Producer Hunt How to Play guide wiring and registry coverage."""

from __future__ import annotations

import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"


class ProducerHuntHowToPlayTests(unittest.TestCase):
    def setUp(self):
        self.guide = (JS / "how-to-play.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.pickups = (JS / "pickups.js").read_text()
        self.abilities = (JS / "abilities.js").read_text()
        self.characters = (JS / "characters.js").read_text()
        self.enemy = (JS / "enemy.js").read_text()
        self.progress = (JS / "progression.js").read_text()

    def test_menu_and_pause_buttons(self):
        self.assertIn('"START GAME", "HOW TO PLAY", "SETTINGS"', self.game)
        self.assertIn('"RESUME", "HOW TO PLAY", "RESTART FROM CHECKPOINT"', self.game)
        self.assertIn("openHowToPlay", self.game)
        self.assertIn("closeHowToPlay", self.game)
        self.assertIn('overlay === "howto"', self.game)
        self.assertIn("this.guide = new HowToPlay()", self.game)
        self.assertNotIn("beginLevel", self.guide)

    def test_guide_sections(self):
        for title in (
            "Basics",
            "Controls",
            "Characters",
            "Weapons",
            "Special Powers",
            "Pickups",
            "Enemies",
            "Boss Battles",
            "Hazards",
            "HUD",
            "Checkpoints and Death",
            "Winning a Level",
        ):
            self.assertIn(title, self.guide)
        self.assertIn("PREVIOUS", self.guide)
        self.assertIn("NEXT", self.guide)
        self.assertIn("BACK TO MENU", self.guide)
        self.assertIn("Page ${this.page + 1}", self.guide)

    def test_reads_live_registries(self):
        self.assertIn("CHARACTERS", self.guide)
        self.assertIn("characterSelectStats", self.guide)
        self.assertIn("weaponSelectCopy", self.guide)
        self.assertIn("abilityMenuInfo", self.guide)
        self.assertIn("PICKUP_DEFS", self.guide)
        self.assertIn("ENEMY_TYPES", self.guide)
        self.assertIn("HAZARD_DEFS", self.guide)
        self.assertIn("BOSS_01", self.guide)
        self.assertIn("DEFAULT_KEYMAP", self.guide)
        self.assertIn("drawSheetFrame", self.guide)
        self.assertIn("NO IMAGE", self.guide)
        self.assertNotIn("assistant_producer", self.guide)
        self.assertIn("post_producer", self.guide)
        self.assertIn("client", self.guide)

    def test_documented_gameplay_ids(self):
        for name in ("editor", "assistant", "colorist", "vfx_supervisor"):
            self.assertIn(name, self.guide)
        self.assertIn("timeline_freeze", self.abilities)
        self.assertIn("production_rush", self.abilities)
        self.assertIn("color_blast", self.abilities)
        self.assertIn("particle_storm", self.abilities)
        self.assertIn("post_producer", self.guide)
        self.assertIn("BOSS_01.displayName", self.guide)
        self.assertIn("BOSS_01.title", self.guide)
        for pickup in ("health", "energy", "production_token", "access_key", "bonus", "ability_charge"):
            self.assertIn(pickup, self.guide)
        self.assertNotIn("Rapid Fire", self.guide)
        self.assertNotIn("Damage Boost", self.guide)
        self.assertIn("live_cable", self.guide)
        self.assertIn("falling_cases", self.guide)

    def test_frame_not_full_strip(self):
        self.assertIn("drawClipFrame", self.guide)
        self.assertIn("frameWidth", self.guide)
        self.assertIn("ctx.drawImage(clip.image, 0, 0, fw, fh", self.guide)

    def test_pause_keeps_gameplay_paused(self):
        self.assertIn('openHowToPlay("pause")', self.game)
        self.assertNotIn("this.guide = new HowToPlay()", self.game.split("openHowToPlay")[1][:200])
