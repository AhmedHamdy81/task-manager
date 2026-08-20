"""Studio 01 Executive Producer boss encounter wiring (Producer Hunt only)."""

from __future__ import annotations

import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"


class ProducerHuntBossTests(unittest.TestCase):
    def setUp(self):
        self.boss = (JS / "boss.js").read_text()
        self.combat = (JS / "combat.js").read_text()
        self.enemy = (JS / "enemy.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.waves = (JS / "waves.js").read_text()
        self.level = (JS / "levels" / "studio-01.js").read_text()
        self.hud = (JS / "hud.js").read_text()
        self.audio = (JS / "audio-catalog.js").read_text()

    def test_central_config_and_states(self):
        self.assertIn("export const EXECUTIVE_PRODUCER_BOSS", self.combat)
        self.assertIn('displayName: "THE EXECUTIVE PRODUCER"', self.combat)
        self.assertIn("maxHealth: 40 * COMBAT.player.damage", self.combat)
        self.assertIn("contactDamage: 2 * COMBAT.player.damage", self.combat)
        self.assertIn("projectileDamage: 1 * COMBAT.player.damage", self.combat)
        self.assertIn("moveSpeed: 90", self.combat)
        self.assertIn("phaseTwoHealthRatio: 0.5", self.combat)
        self.assertIn("scoreValue: 2500", self.combat)
        for state in (
            "entrance",
            "idle",
            "move",
            "ranged_attack",
            "charge_prepare",
            "charge",
            "recovery",
            "hit",
            "phase_transition",
            "death",
            "complete",
        ):
            self.assertIn(f'{state}: "{state}"', self.boss)
        self.assertIn("export class BossEnemy", self.boss)
        self.assertIn("export class BossEncounter", self.boss)
        self.assertIn("export class HostileProjectilePool", self.boss)
        self.assertIn("phaseShifted", self.boss)
        self.assertIn("ATTACK_LOCK", self.boss)

    def test_studio_01_starts_boss_after_waves(self):
        self.assertIn("boss: EXECUTIVE_PRODUCER_BOSS", self.level)
        self.assertIn("studio_01_boss", self.level)
        self.assertIn("boss: true", self.level)
        self.assertIn("EXECUTIVE PRODUCER INCOMING", self.boss)
        self.assertIn("finishWaves", self.waves)
        self.assertIn("onStudioWavesCleared", self.waves)
        self.assertIn("Studio 01 completed", self.waves)
        self.assertIn("onStudioWavesCleared", self.game)
        self.assertIn("attachBossEncounter", self.game)
        self.assertIn("restartCombat", self.game)
        self.assertIn("drawBossHud", self.game)
        self.assertNotIn("class WaveController", self.game)
        self.assertNotIn("assistant_producer/", self.boss)

    def test_combat_and_restart_hooks(self):
        self.assertIn("hostileProjectiles", self.game)
        self.assertIn("acquireHostileShot", self.game)
        self.assertIn("faction === \"boss\"", self.game)
        self.assertIn("playBossMusic", self.game)
        self.assertIn('playMusic("music_boss")', self.game)
        self.assertIn("music/boss_01_theme", self.audio)
        self.assertIn('boss_01_theme: "music_boss_01"', self.audio)
        self.assertIn("executive_producer:", self.enemy)
        self.assertIn("collisionWidth: 96", self.enemy)
        self.assertIn("collisionHeight: 210", self.enemy)
        self.assertIn("hitboxEnabled", self.enemy)
        self.assertIn("loadEnemyKit(ENEMY_TYPES.executive_producer.sprite)", self.game)
        self.assertEqual(self.level.count('type: "post_producer"'), 3)
        self.assertNotIn('type: "executive_producer"', self.level)


if __name__ == "__main__":
    unittest.main()
