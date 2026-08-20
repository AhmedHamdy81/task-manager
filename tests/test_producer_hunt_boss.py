"""Studio 01 Boss 1 (Essam Salama) encounter wiring (Producer Hunt only)."""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"
ASSETS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "assets"


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    i = data.find(b"IHDR")
    if i < 0:
        raise AssertionError(f"no IHDR in {path}")
    w, h = struct.unpack(">II", data[i + 4 : i + 12])
    return w, h


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
        self.spec = (JS / "sprite-spec.js").read_text()
        self.cine = (JS / "cinematic.js").read_text()
        self.loader = (JS / "asset-loader.js").read_text()
        self.proj = (JS / "projectile.js").read_text()

    def test_central_config_and_states(self):
        self.assertIn("export const BOSS_01", self.combat)
        self.assertIn('displayName: "ESSAM SALAMA"', self.combat)
        self.assertIn('title: "THE MASTER BARBER"', self.combat)
        self.assertIn("maxHealth: 50 * COMBAT.player.damage", self.combat)
        self.assertIn("contactDamage: 2 * COMBAT.player.damage", self.combat)
        self.assertIn("projectileDamage: 1 * COMBAT.player.damage", self.combat)
        self.assertIn("walkSpeed: 80", self.combat)
        self.assertIn("chargeSpeed: 360", self.combat)
        self.assertIn("attackCooldown: 1.8", self.combat)
        self.assertIn("hitInvuln: 0.18", self.combat)
        self.assertIn("phaseTwoHealthRatio: 0.5", self.combat)
        self.assertIn("scoreValue: 3000", self.combat)
        self.assertIn("walkSpeedMul: 1.2", self.combat)
        self.assertIn("attackCooldownMul: 0.72", self.combat)
        self.assertIn("chargeSpeedMul: 1.18", self.combat)
        for state in (
            "spawning",
            "idle",
            "approach",
            "throw_prepare",
            "throw_attack",
            "melee_attack",
            "charge_prepare",
            "charge",
            "charge_recovery",
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
        self.assertIn("throwReleaseFrame", self.boss)
        self.assertIn("meleeActive", self.boss)
        self.assertNotIn("executive_producer", self.boss)
        self.assertNotIn("assistant_producer/", self.boss)

    def test_sprite_specs_and_files(self):
        self.assertIn("export const BOSS_01_ANIMATIONS", self.spec)
        self.assertIn("throw: { frames: 6, fps: 12, loop: false }", self.spec)
        self.assertIn("death: { frames: 6, fps: 8, loop: false }", self.spec)
        self.assertIn("charge: { frames: 6, fps: 12, loop: true }", self.spec)
        self.assertIn("idle: { frames: 8, fps: 8, loop: true }", self.spec)
        self.assertIn('characterSpriteSrc("boss_01"', self.enemy)
        self.assertIn("BOSS_01_ANIMATIONS", self.enemy)
        expected = {
            "boss_01_idle.png": (2048, 256),
            "boss_01_walk.png": (2048, 256),
            "boss_01_throw.png": (1536, 256),
            "boss_01_melee.png": (1536, 256),
            "boss_01_charge.png": (1536, 256),
            "boss_01_hit.png": (1024, 256),
            "boss_01_phase_transition.png": (2048, 256),
            "boss_01_death.png": (1536, 256),
        }
        folder = ASSETS / "characters" / "boss_01" / "sprites"
        for name, size in expected.items():
            path = folder / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(png_size(path), size, name)
        for name in (
            "boss_01_razor.png",
            "boss_01_scissors.png",
            "boss_01_clippers.png",
            "boss_01_brush.png",
        ):
            path = ASSETS / "projectiles" / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(png_size(path), (1024, 256), name)
        self.assertIn("_fillNearestAnims", self.loader)
        self.assertIn("animFrames", self.proj)
        self.assertIn("interruptMove", self.proj)

    def test_studio_01_starts_boss_after_waves(self):
        self.assertIn("boss: BOSS_01", self.level)
        self.assertIn("studio_01_boss", self.level)
        self.assertIn("boss: true", self.level)
        self.assertIn("playerInArena", self.boss)
        self.assertIn("playBossIntro", self.boss)
        self.assertIn("afterIntro", self.boss)
        self.assertIn("placePlayerCombatStart", self.boss)
        self.assertIn("blocksInput", self.boss)
        self.assertIn("BOSS DEFEATED", self.boss)
        self.assertIn("finishWaves", self.waves)
        self.assertIn("onStudioWavesCleared", self.waves)
        self.assertIn("Studio 01 completed", self.waves)
        self.assertIn("onStudioWavesCleared", self.game)
        self.assertIn("attachBossEncounter", self.game)
        self.assertIn("restartCombat", self.game)
        self.assertIn("drawBossHud", self.game)
        self.assertIn("bossEncounter?.blocksInput", self.game)
        self.assertNotIn("class WaveController", self.game)
        self.assertIn('if (this._completed) return', self.cine)

    def test_combat_and_restart_hooks(self):
        self.assertIn("hostileProjectiles", self.game)
        self.assertIn("acquireHostileShot", self.game)
        self.assertIn('faction === "boss"', self.game)
        self.assertIn("playBossMusic", self.game)
        self.assertIn("music/boss_01_theme", self.audio)
        self.assertIn('boss_01_theme: "music_boss_01"', self.audio)
        self.assertIn("boss_01:", self.enemy)
        self.assertIn("collisionWidth: 92", self.enemy)
        self.assertIn("collisionHeight: 198", self.enemy)
        self.assertIn("hitboxEnabled", self.enemy)
        self.assertIn("loadEnemyKit(ENEMY_TYPES.boss_01.sprite)", self.game)
        self.assertEqual(self.level.count('type: "post_producer"'), 3)
        self.assertNotIn('type: "executive_producer"', self.level)
        self.assertNotIn('type: "boss_01"', self.level)
        self.assertIn("meleeHitOnce", self.game)
        self.assertIn("skipIntro", self.boss)
        self.assertIn("bossIntroWatched", self.boss)


if __name__ == "__main__":
    unittest.main()
