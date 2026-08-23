"""Studio 01 enemy-wave system wiring (Producer Hunt only)."""

from __future__ import annotations

import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"


class ProducerHuntWaveTests(unittest.TestCase):
    def test_studio_01_wave_data(self):
        level = (JS / "levels" / "studio-01.js").read_text()
        self.assertIn("export const STUDIO_01_WAVES", level)
        self.assertIn("export const STUDIO_01_ENCOUNTERS", level)
        self.assertIn('id: "enc_intro"', level)
        self.assertIn('id: "enc_pressure"', level)
        self.assertIn('id: "enc_vertical"', level)
        self.assertIn('id: "enc_client"', level)
        self.assertIn('id: "enc_gauntlet"', level)
        self.assertIn("unlockBoss: true", level)
        self.assertIn("spawnZones", level)
        self.assertIn("waves: STUDIO_01_WAVES", level)
        self.assertIn("enemySpawns: []", level)
        self.assertNotIn("assistant_producer", level)
        self.assertIn('type: "client"', level)
        self.assertIn('type: "post_producer"', level)
        self.assertIn('type: "colorist"', level)
        self.assertIn('type: "vfx_supervisor"', level)

    def test_wave_controller_architecture(self):
        waves = (JS / "waves.js").read_text()
        game = (JS / "game.js").read_text()
        enemy = (JS / "enemy.js").read_text()
        player = (JS / "player.js").read_text()
        hud = (JS / "hud.js").read_text()
        world = (JS / "levels" / "world.js").read_text()
        self.assertIn("export class WaveController", waves)
        self.assertIn('waiting: "waiting"', waves)
        self.assertIn('spawning: "spawning"', waves)
        self.assertIn('active: "active"', waves)
        self.assertIn('cleared: "cleared"', waves)
        self.assertIn('complete: "complete"', waves)
        self.assertIn("WAVE_MIN_PLAYER_DX = 500", waves)
        self.assertIn("pickWaveSpawn", waves)
        self.assertIn("allEnemiesSpawned", waves)
        self.assertIn("livingEnemyCount", waves)
        self.assertIn("Wave started", waves)
        self.assertIn("Studio 01 completed", waves)
        self.assertIn("WaveController", game)
        self.assertIn("EncounterDirector", game)
        self.assertIn("attachWaves", game)
        self.assertIn("destroyWaves", game)
        self.assertIn("spawnWaveEnemy", game)
        self.assertIn("awardStudioClear", game)
        self.assertIn("syncWaveCheckpoint", game)
        self.assertIn("notifyWaveExit", enemy)
        self.assertIn("applyWaveModifiers", enemy)
        self.assertIn("this.elite", enemy)
        self.assertNotIn("STUDIO_01_WAVES", player)
        self.assertNotIn("WaveController", player)
        self.assertIn("WAVE ${wave.index}", hud)
        self.assertIn("ENEMIES ${wave.living}", hud)
        self.assertIn("level.waves", world)
        self.assertNotIn("class WaveController", game)
        self.assertEqual(game.count("new WaveController"), 1)

    def test_no_assistant_producer_type(self):
        enemy = (JS / "enemy.js").read_text()
        game = (JS / "game.js").read_text()
        waves = (JS / "waves.js").read_text()
        self.assertNotIn("ENEMY_TYPES.assistant_producer", enemy)
        self.assertNotIn("ENEMY_TYPES.assistant_producer", game)
        self.assertNotIn("ENEMY_TYPES.assistant_producer", waves)
        self.assertNotIn("enemies/assistant_producer", waves)


if __name__ == "__main__":
    unittest.main()
