"""Producer Hunt Phase 6 — Studio 01 rescue characters and rewards."""

from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"
ASSETS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "assets"

IDS = (
    "studio_01_rescue_sound_engineer",
    "studio_01_rescue_camera_operator",
    "studio_01_rescue_stunt_performer",
    "studio_01_rescue_production_intern",
)

KINDS = ("camera_operator", "sound_engineer", "stunt_performer", "production_intern")
CONTAINERS = ("equipment_cage", "locked_sound_booth", "collapsed_set_debris", "security_barrier")
ANIMS = ("rescue_idle", "rescue_release", "rescue_celebrate", "rescue_run")
FRAMES = {"rescue_idle": 4, "rescue_release": 4, "rescue_celebrate": 4, "rescue_run": 6}


class ProducerHuntPhase6Tests(unittest.TestCase):
    def setUp(self):
        self.res = (JS / "rescues.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.s1 = (JS / "levels" / "studio-01.js").read_text()
        self.s2 = (JS / "levels" / "studio-02.js").read_text()
        self.world = (JS / "levels" / "world.js").read_text()
        self.hud = (JS / "hud.js").read_text()
        self.cfg = (JS / "config.js").read_text()
        self.player = (JS / "player.js").read_text()
        self.audio = (JS / "audio-catalog.js").read_text()
        self.brk = (JS / "destructibles.js").read_text()
        self.spec = (JS / "sprite-spec.js").read_text()

    def test_registry_and_state_machine(self):
        for kind in KINDS:
            self.assertIn(f"{kind}:", self.res)
        for state in ("trapped", "available", "rescuing", "celebrating", "escaping", "completed"):
            self.assertIn(f'"{state}"', self.res)
        self.assertIn("grantReward", self.res)
        self.assertIn('kind: "health"', self.res)
        self.assertIn('kind: "ammo"', self.res)
        self.assertIn('kind: "specialPowerEnergy"', self.res)
        self.assertIn('kind: "temporaryBuff"', self.res)
        self.assertIn("ALL_RESCUES_BONUS = 2000", self.res)
        self.assertIn("allRescuesAwarded", self.res)
        self.assertIn("RESCUE_ANIMATIONS", self.spec)

    def test_studio_01_placement_and_ids(self):
        for rid in IDS:
            self.assertIn(rid, self.s1)
        for kind in CONTAINERS:
            self.assertIn(f'kind: "{kind}"', self.s1)
            self.assertIn(f"{kind}:", self.brk)
        self.assertIn("rescues:", self.s1)
        self.assertNotIn("rescues:", self.s2)
        self.assertIn("instantiateRescue", self.world)
        self.assertIn("x: t(84) + 36", self.s1)
        self.assertIn("activateX: t(96)", self.s1)

    def test_wiring_hud_checkpoint_input(self):
        self.assertIn("tickRescues(this, dt)", self.game)
        self.assertIn("snapshotRescues(this.world)", self.game)
        self.assertIn("applyRescueSnapshot(this.world, snap.rescues)", self.game)
        self.assertIn("preloadRescueKits", self.game)
        self.assertIn("drawRescueHud", self.game)
        self.assertIn("Crew rescued", self.hud)
        self.assertIn("interact:", self.cfg)
        self.assertIn('consume("special")', self.player)
        self.assertIn("rescueBuff", self.player)
        self.assertIn("captions", (JS / "settings.js").read_text())

    def test_audio_and_placeholder_art(self):
        for key in ("rescue_prompt", "rescue_open", "rescue_celebrate", "rescue_reward", "rescue_escape"):
            self.assertIn(f"{key}:", self.audio)
        for kind in KINDS:
            for anim, frames in FRAMES.items():
                path = ASSETS / "characters" / "rescues" / kind / "sprites" / f"{anim}.png"
                self.assertTrue(path.is_file(), str(path))
                with Image.open(path) as img:
                    self.assertEqual(img.mode, "RGBA", anim)
                    self.assertEqual(img.size, (256 * frames, 256), str(path))
                    self.assertLess(img.getextrema()[3][0], 255)
        for name in CONTAINERS:
            path = ASSETS / "environment" / "studio_01" / "destructibles" / f"{name}.png"
            self.assertTrue(path.is_file(), name)
            with Image.open(path) as img:
                self.assertEqual(img.mode, "RGBA")

    def test_no_studio_02_or_assistant_producer(self):
        self.assertNotIn("assistant_producer", self.s1)
        self.assertNotIn("ENEMY_TYPES.assistant_producer", (JS / "enemy.js").read_text())
        self.assertIn('id: "studio_02"', self.s2)
        self.assertNotIn("sound_engineer", self.s2)


if __name__ == "__main__":
    unittest.main()
