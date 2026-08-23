"""Producer Hunt Phase 8 — Boss 1 complete three-phase combat (Studio 01 only)."""

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


class ProducerHuntPhase8Tests(unittest.TestCase):
    def setUp(self):
        self.boss = (JS / "boss.js").read_text()
        self.brain = (JS / "boss-brain.js").read_text()
        self.combat = (JS / "combat.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.level = (JS / "levels" / "studio-01.js").read_text()
        self.env = (JS / "studio-env.js").read_text()
        self.abilities = (JS / "abilities.js").read_text()
        self.diff = (JS / "difficulty.js").read_text()
        self.catalog = (JS / "asset-catalog.js").read_text()
        self.cine = (JS / "cinematic.js").read_text()

    def test_three_phase_attacks_and_score_once(self):
        for attack in (
            "razor_throw",
            "scissor_spread",
            "brush_melee",
            "clipper_burst",
            "barber_charge",
            "falling_tools",
            "double_charge",
            "tool_storm",
            "ground_slam",
        ):
            self.assertIn(f'"{attack}"', self.brain)
        self.assertIn("scoreValue: 10000", self.combat)
        self.assertIn("awardBoss", self.boss)
        self.assertIn("afterDefeatCinematic", self.boss)
        self.assertIn("if (!this.scoreAwarded)", self.boss)
        self.assertIn("notifyEnemyDamage", self.game)
        self.assertIn("if (enemy.isBoss)", self.game)
        self.assertIn("specialBossCap", self.abilities)
        self.assertIn("shotgunBossCap", self.brain)
        self.assertIn("chargeArmor", self.brain)
        self.assertIn("_splashDone", self.game)

    def test_arena_before_exit_door(self):
        self.assertIn("bossArena: { left: t(96), right: t(111)", self.level)
        self.assertIn("activateX: t(96)", self.level)
        self.assertIn("x: t(112)", self.level)
        self.assertIn("x: t(114)", self.level)
        self.assertIn("be?.arenaLocked", self.env)
        self.assertIn("lockArena", self.boss)
        self.assertIn("unlockArena", self.boss)

    def test_videos_music_and_projectiles(self):
        self.assertIn("playBossIntro", self.boss)
        self.assertIn("playBossDefeat", self.boss)
        self.assertIn("playBossMusic", self.boss)
        self.assertIn("_fadeBossMusic", self.boss)
        self.assertIn("playBossIntro", self.cine)
        self.assertIn("playBossDefeat", self.cine)
        folder = ASSETS / "projectiles" / "boss_01"
        for name in (
            "straight_razor.png",
            "barber_scissors.png",
            "electric_clipper_energy.png",
            "falling_barber_tool.png",
            "ground_wave.png",
        ):
            path = folder / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(png_size(path), (1024, 256), name)
            self.assertIn(f"projectiles/boss_01/{name}", self.catalog)
        self.assertIn("scaleBossConfig", self.brain)
        self.assertIn("drawBossDebug", self.brain)
        self.assertIn("DEBUG_COMBAT", self.brain)
        self.assertIn("PHASE ${view.phase", self.game)

    def test_does_not_expand_studio_02_results(self):
        s2 = (JS / "levels" / "studio-02.js").read_text()
        self.assertNotIn("boss_01", s2)
        self.assertNotIn("ESSAM SALAMA", s2)


if __name__ == "__main__":
    unittest.main()
