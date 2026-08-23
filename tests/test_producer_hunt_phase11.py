"""Producer Hunt Phase 11 — Studio 01 release candidate."""

from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"
ASSETS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "assets"

PLAYER = {
    "idle": 6,
    "run": 8,
    "jump": 4,
    "fall": 2,
    "crouch": 2,
    "shoot": 4,
    "crouch_shoot": 4,
    "hit": 3,
    "death": 8,
}

REQUIRED_MUSIC = [
    "audio/music/menu_theme.mp3",
    "audio/music/studio_01_theme.mp3",
    "audio/music/boss_01_theme.mp3",
]

REQUIRED_VIDEO = [
    "videos/boss_01_intro.mp4",
    "videos/boss_01_defeat.mp4",
]


class ProducerHuntPhase11Tests(unittest.TestCase):
    def setUp(self):
        self.characters = (JS / "characters.js").read_text()
        self.diff = (JS / "difficulty.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.enemy = (JS / "enemy.js").read_text()
        self.enc = (JS / "encounters.js").read_text()
        self.world = (JS / "levels" / "world.js").read_text()
        self.progress = (JS / "progression.js").read_text()
        self.validate = (JS / "studio-01-validate.js").read_text()
        self.player = (JS / "player.js").read_text()
        self.s2 = (JS / "levels" / "studio-02.js").read_text()
        self.ui = (JS / "ui.js").read_text()
        self.css = (ROOT / "producer_hunt" / "static" / "producer_hunt" / "css" / "game.css").read_text()

    def test_character_hearts_and_multipliers(self):
        self.assertIn("HEART_HP = 12.5", self.characters)
        self.assertIn("editor: 8", self.characters)
        self.assertIn("assistant: 6", self.characters)
        self.assertIn("colorist: 8", self.characters)
        self.assertIn("vfx_supervisor: 11", self.characters)
        self.assertIn("damageMultiplier: 1.3", self.characters)
        self.assertIn("damageMultiplier: 1.05", self.characters)
        self.assertIn("moveSpeedMultiplier: 1.18", self.characters)
        self.assertIn("fireRateMultiplier: 1.2", self.characters)
        self.assertIn("fireRateMultiplier: 0.88", self.characters)
        self.assertIn("jumpMultiplier: 1.08", self.characters)

    def test_difficulty_profiles_do_not_scale_everything(self):
        self.assertIn("health: 0.8", self.diff)
        self.assertIn("health: 1.25", self.diff)
        self.assertIn("playerInvuln: 1.15", self.diff)
        self.assertIn("playerInvuln: 0.85", self.diff)
        self.assertIn("playerInvuln: 0.72", self.diff)
        self.assertIn("maxClose: 2", self.diff)
        self.assertIn("reaction: 1.4", self.diff)
        self.assertIn("reaction: 0.82", self.diff)
        self.assertEqual(self.diff.count("interval: 1,"), 3)

    def test_validation_module_and_level_checks(self):
        self.assertIn("validateStudio01Release", self.validate)
        self.assertIn("validateCharacterConfigs", self.validate)
        self.assertIn("standing muzzle is invalid", self.validate)
        self.assertIn("Duplicate", self.validate)
        self.assertIn("Boss arena", self.validate)
        self.assertIn("validateStudio01Release", self.game)
        self.assertIn("Duplicate rescue id", self.world)
        self.assertIn("Boss arena bounds are invalid", self.world)
        self.assertIn("references missing container", self.world)

    def test_progression_recovery(self):
        self.assertIn("telegraphHold", self.enemy)
        self.assertIn("hitboxEnabled = false", self.game)
        self.assertIn('notifyWaveExit?.("invalid")', self.game)
        self.assertIn("dropped remaining queued spawns", self.enc)
        self.assertIn("world.ground?.y ?? 960", self.enc)
        self.assertIn("playerInvulnSec", self.game)
        self.assertIn("this.host?.playerInvulnSec", self.player)
        self.assertIn("this.cinematic?.cancel()", self.game)
        self.assertIn("combatTimeScale(entity)", self.game)

    def test_all_four_characters_playable(self):
        self.assertGreaterEqual(self.progress.count("always: true"), 4)
        self.assertIn('label: "Defeat Boss 1"', self.progress)
        self.assertIn('label: "Complete Studio 02"', self.progress)

    def test_studio_02_not_started(self):
        self.assertIn('id: "studio_02"', self.s2)
        self.assertIn("CONTINUE — COMING SOON", self.game)
        self.assertNotIn("studio-01-validate", self.s2)

    def test_no_horizontal_page_scroll(self):
        self.assertIn("overflow-x: hidden", self.css)
        self.assertIn("object-fit: contain", self.css)

    def test_required_music_and_video_present(self):
        for rel in REQUIRED_MUSIC + REQUIRED_VIDEO:
            path = ASSETS / rel
            self.assertTrue(path.is_file(), f"missing production-critical asset {rel}")

    def test_player_sheets_dimensions_and_transparency(self):
        for cid in ("editor", "assistant", "colorist", "vfx_supervisor"):
            for anim, frames in PLAYER.items():
                path = ASSETS / "characters" / cid / "sprites" / f"{cid}_{anim}.png"
                self.assertTrue(path.is_file(), str(path))
                with Image.open(path) as img:
                    self.assertEqual(img.size, (256 * frames, 256), path.name)
                    self.assertIn(img.mode, ("RGBA", "LA", "P"), f"{path.name} mode={img.mode}")

    def test_unused_duplicate_defeat_video_reported(self):
        duplicate = ASSETS / "videos" / "boss_01_defeat.mp4.mp4"
        self.assertTrue(duplicate.is_file(), "expected unused duplicate video to remain until explicitly deleted")


if __name__ == "__main__":
    unittest.main()
