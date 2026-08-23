"""Producer Hunt phase-1 combat feel contracts."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"


def _num(src: str, name: str) -> float:
    match = re.search(rf"export const {name} = ([0-9.]+)", src)
    if not match:
        raise AssertionError(f"missing {name}")
    return float(match.group(1))


class ProducerHuntCombatFeelTests(unittest.TestCase):
    def test_movement_and_hitstop_constants(self):
        config = (JS / "config.js").read_text()
        self.assertGreater(_num(config, "MOVE_ACCEL"), 4000)
        self.assertGreater(_num(config, "MOVE_DECEL"), _num(config, "MOVE_ACCEL"))
        self.assertGreater(_num(config, "MOVE_REVERSE"), _num(config, "MOVE_ACCEL"))
        self.assertAlmostEqual(_num(config, "AIR_CONTROL"), 0.8)
        self.assertAlmostEqual(_num(config, "COYOTE_SEC"), 0.12)
        self.assertAlmostEqual(_num(config, "JUMP_BUFFER_SEC"), 0.14)
        self.assertLess(_num(config, "JUMP_CUT_MUL"), 1)
        self.assertGreaterEqual(_num(config, "HITSTOP_LIGHT_SEC"), 0.035)
        self.assertLessEqual(_num(config, "HITSTOP_LIGHT_SEC"), 0.055)
        self.assertGreaterEqual(_num(config, "HITSTOP_HEAVY_SEC"), 0.07)
        self.assertLessEqual(_num(config, "HITSTOP_HEAVY_SEC"), 0.1)
        self.assertIn("DEBUG_COMBAT = false", config)

    def test_player_fires_without_waiting_for_anim_frame(self):
        player = (JS / "player.js").read_text()
        self.assertIn("JUMP_CUT_MUL", player)
        self.assertIn("MOVE_REVERSE", player)
        self.assertIn("AIR_CONTROL", player)
        self.assertIn("this.loadout.tryAttack", player)
        self.assertNotIn('clip !== "shoot"', player)
        self.assertIn("PLAYER_BODY.width", player)

    def test_restart_clears_combat_feel(self):
        game = (JS / "game.js").read_text()
        self.assertIn("resetCombatFeel", game)
        self.assertIn("beginHitStop", game)
        self.assertIn("resolveKnockback", game)
        self.assertIn("travelBounds", game)
        self.assertNotIn("physics.add.overlap", game)

    def test_character_muzzle_stances(self):
        characters = (JS / "characters.js").read_text()
        self.assertIn("idle:", characters)
        self.assertIn("run:", characters)
        self.assertIn("jump:", characters)
        self.assertIn("crouch_shoot:", characters)
        self.assertIn("renderWeaponOverlay: false", characters)
        stats = (JS / "characters.js").read_text()
        self.assertIn("jumpMultiplier: 1.08", stats)
        self.assertIn("moveSpeedMultiplier: 1.18", stats)
        self.assertIn("defenseMultiplier: 1.25", stats)
