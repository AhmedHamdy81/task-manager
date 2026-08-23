"""Producer Hunt Phase 10 — Studio 01 presentation polish."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"


class ProducerHuntPhase10Tests(unittest.TestCase):
    def setUp(self):
        self.pres = (JS / "presentation.js").read_text()
        self.config = (JS / "config.js").read_text()
        self.player = (JS / "player.js").read_text()
        self.anim = (JS / "animation.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.audio = (JS / "audio.js").read_text()
        self.catalog = (JS / "audio-catalog.js").read_text()
        self.settings = (JS / "settings.js").read_text()
        self.ui = (JS / "ui.js").read_text()
        self.fx = (JS / "fx.js").read_text()
        self.cam = (JS / "camera.js").read_text()
        self.enemy = (JS / "enemy.js").read_text()
        self.s2 = (JS / "levels" / "studio-02.js").read_text()

    def test_mix_hitstop_camera_and_pool(self):
        self.assertIn("musicVolume: 0.65", self.pres)
        self.assertIn("effectsVolume: 0.8", self.pres)
        self.assertIn("voiceVolume: 0.9", self.pres)
        self.assertIn("ambienceVolume: 0.35", self.pres)
        self.assertIn("HITSTOP_HEAVY_SEC = 0.07", self.config)
        self.assertIn("look: 110", self.config)
        self.assertIn("export class FxPool", self.fx)
        self.assertIn("this.fx.spawn", self.game)
        self.assertIn("applyConfirmedHit", self.game)
        self.assertNotIn("else if (enemy.isBoss) this.beginHitStop", self.game)

    def test_player_anim_aliases_and_run_shoot(self):
        self.assertIn('run_shoot: "run"', self.anim)
        self.assertIn('land: "crouch"', self.anim)
        self.assertIn('return "run_shoot"', self.player)
        self.assertIn('return "land"', self.player)
        self.assertIn("landTimer", self.player)
        self.assertIn("kind: \"muzzle\"", self.player)

    def test_audio_buses_and_settings(self):
        self.assertIn("ambience: 1", self.audio)
        self.assertIn("voice: 1", self.audio)
        self.assertIn("_stealLowestPriority", self.audio)
        self.assertIn('category === "ambience"', self.catalog)
        self.assertIn('screenShake: "full"', self.settings)
        self.assertIn("particleDensity", self.settings)
        self.assertIn("Voice / video volume", self.ui)
        self.assertIn("Particle density", self.ui)
        self.assertIn("SHAKE_CYCLE", self.ui)

    def test_enemy_telegraph_not_color_only(self):
        self.assertIn("_drawTelegraph", self.enemy)
        self.assertIn('"!"', self.enemy)
        self.assertIn("strokeRect(origin.x - 28", self.enemy)

    def test_studio_02_untouched(self):
        self.assertIn('id: "studio_02"', self.s2)
        self.assertNotIn("ScoreManager", self.s2)
        self.assertNotIn("FxPool", self.s2)


if __name__ == "__main__":
    unittest.main()
