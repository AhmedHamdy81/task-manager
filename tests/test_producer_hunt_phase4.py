"""Producer Hunt Phase 4 — Studio 01 environment and hazards."""

from __future__ import annotations

import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"


class ProducerHuntPhase4Tests(unittest.TestCase):
    def setUp(self):
        self.env = (JS / "studio-env.js").read_text()
        self.prog = (JS / "progression.js").read_text()
        self.s1 = (JS / "levels" / "studio-01.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.cam = (JS / "camera.js").read_text()
        self.settings = (JS / "settings.js").read_text()
        self.audio = (JS / "audio-catalog.js").read_text()
        self.s2 = (JS / "levels" / "studio-02.js").read_text()

    def test_hazard_defs_and_director(self):
        for kind in ("steam_vent", "electrical_floor", "falling_light", "camera_rig", "rolling_cart"):
            self.assertIn(f"{kind}:", self.prog)
            self.assertIn(f'kind: "{kind}"', self.s1)
        self.assertIn("telegraphDuration: 0.8", self.prog)
        self.assertIn("tickHazards", self.env)
        self.assertIn("tickMovers", self.env)
        self.assertIn("snapshotHazards", self.env)
        self.assertIn("isHazardDamaging", self.env)
        self.assertIn("tickHazards(this, dt)", self.game)
        self.assertIn("studio-env.js", self.game)

    def test_studio_01_sections_and_boss_clear(self):
        self.assertIn("A  ENTRANCE", self.s1)
        self.assertIn("F  BOSS APPROACH", self.s1)
        self.assertIn("hazardQuietX: t(96)", self.s1)
        self.assertIn("studio_01_steam_demo", self.s1)
        self.assertIn("studio_01_cable_intro", self.s1)
        self.assertIn('kind: "live_cable"', self.s1)
        self.assertIn("enc_final", self.s1)
        self.assertIn("activateX: t(96)", self.s1)
        self.assertIn("barber_light", self.s1)
        self.assertIn("studio_01_barber_approach", self.s1)

    def test_camera_audio_comfort(self):
        self.assertIn("airFocusY", self.cam)
        self.assertIn("lock.left", self.cam)
        self.assertIn("env_ambience", self.audio)
        self.assertIn("env_steam", self.audio)
        self.assertIn("reducedFlashes", self.settings)
        self.assertIn("hazardSymbols", self.settings)
        self.assertIn("ensureLoop", (JS / "audio.js").read_text())
        self.assertIn("stopSound", (JS / "audio.js").read_text())

    def test_does_not_modify_studio_02_layout(self):
        self.assertIn('id: "studio_02"', self.s2)
        self.assertIn("studio_02_cable_intro", self.s2)
        self.assertNotIn("steam_vent", self.s2)
        self.assertNotIn("studio-env.js", self.s2)

    def test_q_special_untouched(self):
        player = (JS / "player.js").read_text()
        self.assertIn('consume("special")', player)
        self.assertIn("onStudioWavesCleared", self.game)


if __name__ == "__main__":
    unittest.main()
