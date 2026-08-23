"""Producer Hunt Phase 7 — Studio 01 Battle Dolly vehicle set-piece."""

from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"
ASSETS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "assets"

ANIMS = {
    "idle": 4,
    "drive": 6,
    "hop": 2,
    "fire": 3,
    "special": 4,
    "hit": 2,
    "destroyed": 4,
}

SFX = (
    "vehicle_engine_loop",
    "vehicle_enter",
    "vehicle_exit",
    "vehicle_hop",
    "vehicle_cannon",
    "vehicle_spotlight_charge",
    "vehicle_spotlight_fire",
    "vehicle_hit",
    "vehicle_warning",
    "vehicle_explosion",
    "vehicle_repair",
)


class ProducerHuntPhase7Tests(unittest.TestCase):
    def setUp(self):
        self.veh = (JS / "vehicles.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.s1 = (JS / "levels" / "studio-01.js").read_text()
        self.s2 = (JS / "levels" / "studio-02.js").read_text()
        self.world = (JS / "levels" / "world.js").read_text()
        self.player = (JS / "player.js").read_text()
        self.hud = (JS / "hud.js").read_text()
        self.audio = (JS / "audio-catalog.js").read_text()
        self.enc = (JS / "encounters.js").read_text()
        self.env = (JS / "studio-env.js").read_text()
        self.cfg = (JS / "config.js").read_text()
        self.spec = (JS / "sprite-spec.js").read_text()
        self.pick = (JS / "pickups.js").read_text()
        self.brk = (JS / "destructibles.js").read_text()

    def test_registry_and_controls(self):
        self.assertIn("battle_dolly:", self.veh)
        self.assertIn("VEHICLE_SEQUENCE_ID", self.veh)
        self.assertIn("studio_01_battle_dolly", self.veh)
        self.assertIn("maxHealth: 20 * HP", self.veh)
        self.assertIn("cannonDamage: 2 * HP", self.veh)
        self.assertIn("cannonInterval: 0.11", self.veh)
        self.assertIn("cannonSpeed: 1100", self.veh)
        self.assertIn("spotlightDamage: 6 * HP", self.veh)
        self.assertIn("spotlightCooldown: 8", self.veh)
        self.assertIn("hopVelocity: 1240", self.veh)
        self.assertIn("maxSpeed: 230", self.veh)
        self.assertIn("VEHICLE_ANIMATIONS", self.spec)
        self.assertIn('consume("special")', self.veh)
        self.assertIn('consume("interact")', self.veh)
        self.assertIn('consume("special")', self.player)
        self.assertIn("interact:", self.cfg)
        self.assertIn("this.mounted", self.player)

    def test_studio_01_placement(self):
        self.assertIn("studio_01_battle_dolly", self.s1)
        self.assertIn("studio_01_vehicle", self.s1)
        self.assertIn("studio_01_dolly_barricade_a", self.s1)
        self.assertIn("studio_01_dolly_repair_a", self.s1)
        self.assertIn("dolly_barricade:", self.brk)
        self.assertIn('kind: "vehicle_repair"', self.s1)
        self.assertIn("effect === \"vehicle_repair\"", self.pick)
        self.assertIn("x: t(63)", self.s1)
        self.assertIn("stopX: t(79)", self.s1)
        self.assertIn("activateX: t(96)", self.s1)
        self.assertIn("instantiateVehicle", self.world)
        self.assertNotIn("vehicles:", self.s2)
        self.assertNotIn("battle_dolly", self.s2)

    def test_wiring_checkpoint_camera_boss_safety(self):
        self.assertIn("bindVehicle(this)", self.game)
        self.assertIn("tickVehicles(this, dt)", self.game)
        self.assertIn("restoreAfterDeath", self.game)
        self.assertIn("snapshotVehicles(this.world)", self.game)
        self.assertIn("applyVehicleSnapshot(this, snap.vehicles)", self.game)
        self.assertIn("preloadVehicleKits", self.game)
        self.assertIn("forceVehicleSafeRestore(this)", self.game)
        self.assertIn("vehicleFollowTarget", self.game)
        self.assertIn("vehicleCameraLock", self.game)
        self.assertIn("lookScale", (JS / "camera.js").read_text())
        self.assertIn('enc.id === "enc_client"', self.enc)
        self.assertIn("game.player?.mounted", self.env)
        self.assertIn("drawVehicleHud", self.game)
        self.assertIn("drawVehicleDebug", self.game)
        self.assertIn("BATTLE DOLLY", self.hud)

    def test_no_duplicate_input_or_assistant_producer(self):
        self.assertNotIn("assistant_producer", self.s1)
        self.assertNotIn("ENEMY_TYPES.assistant_producer", (JS / "enemy.js").read_text())
        self.assertEqual(self.game.count("new Input("), 1)
        self.assertIn('id: "studio_02"', self.s2)

    def test_audio_and_placeholder_art(self):
        for key in SFX:
            self.assertIn(f"{key}:", self.audio)
        for anim, frames in ANIMS.items():
            path = ASSETS / "vehicles" / "battle_dolly" / f"battle_dolly_{anim}.png"
            self.assertTrue(path.is_file(), str(path))
            with Image.open(path) as img:
                self.assertEqual(img.mode, "RGBA", anim)
                self.assertEqual(img.size, (256 * frames, 256), str(path))
                self.assertLess(img.getextrema()[3][0], 255)
        icon = ASSETS / "hud" / "vehicles" / "battle_dolly_icon.png"
        self.assertTrue(icon.is_file())
        with Image.open(icon) as img:
            self.assertEqual(img.mode, "RGBA")
            self.assertLess(img.getextrema()[3][0], 255)


if __name__ == "__main__":
    unittest.main()
