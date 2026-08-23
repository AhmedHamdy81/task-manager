"""Studio 01 jump reach must be shared across playable characters."""

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


class ProducerHuntJumpReachTests(unittest.TestCase):
    def test_shared_body_and_jump_contract(self):
        spec = (JS / "sprite-spec.js").read_text()
        config = (JS / "config.js").read_text()
        player = (JS / "player.js").read_text()
        characters = (JS / "characters.js").read_text()
        studio = (JS / "levels" / "studio-01.js").read_text()

        self.assertIn("PLAYER_BODY", spec)
        self.assertIn("width: 80", spec)
        self.assertIn("height: 170", spec)
        self.assertIn("collisionWidth: PLAYER_BODY.width", spec)
        self.assertIn("this.collisionWidth = PLAYER_BODY.width", player)
        self.assertIn("this.standH = PLAYER_BODY.height", player)
        self.assertIn("BASE_JUMP_VELOCITY", player)
        self.assertIn("COYOTE_SEC", player)
        self.assertIn("JUMP_BUFFER_SEC", player)
        self.assertIn("this.vy = -this.baseJumpVelocity * this.jumpMultiplier", player)
        self.assertNotIn("jumpPower", player)
        self.assertIn("DEBUG_JUMP = false", config)
        self.assertIn("jumpStrength: SHARED_PLAYER.jumpStrength", characters)
        self.assertIn("jumpMultiplier: 1.08", characters)
        self.assertNotIn("jumpMultiplier: 0.95", characters)
        self.assertNotIn("jumpMultiplier: 0.88", characters)
        self.assertIn("G - t(4)", studio)

        gravity = _num(config, "GRAVITY")
        jump_speed = _num(config, "JUMP_SPEED")
        jump_scale = _num(config, "JUMP_SCALE")
        base = jump_speed * jump_scale
        height = (base * base) / (2 * gravity)
        required = 4 * 64
        margin = 64 / 4
        self.assertGreaterEqual(height, required + margin)
        for mul in (1.0, 1.08):
            h = ((base * mul) ** 2) / (2 * gravity)
            self.assertGreaterEqual(h, required + margin, f"mul={mul}")


if __name__ == "__main__":
    unittest.main()
