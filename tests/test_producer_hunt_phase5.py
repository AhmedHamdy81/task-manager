"""Producer Hunt Phase 5 — Studio 01 destructible props and explosions."""

from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"
ASSETS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "assets"

PLACEHOLDERS = [
    "environment/studio_01/destructibles/equipment_crate.png",
    "environment/studio_01/destructibles/production_monitor.png",
    "environment/studio_01/destructibles/studio_light_stand.png",
    "environment/studio_01/destructibles/film_reel_container.png",
    "environment/studio_01/destructibles/electrical_control_box.png",
    "environment/studio_01/destructibles/compressed_air_canister.png",
    "environment/studio_01/destructibles/barber_supply_case.png",
    "effects/destruction/debris.png",
    "effects/explosions/blast.png",
]

TYPES = (
    "equipment_crate",
    "production_monitor",
    "studio_light_stand",
    "film_reel_container",
    "electrical_control_box",
    "compressed_air_canister",
    "barber_supply_case",
)


class ProducerHuntPhase5Tests(unittest.TestCase):
    def setUp(self):
        self.brk = (JS / "destructibles.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.s1 = (JS / "levels" / "studio-01.js").read_text()
        self.s2 = (JS / "levels" / "studio-02.js").read_text()
        self.world = (JS / "levels" / "world.js").read_text()
        self.abilities = (JS / "abilities.js").read_text()
        self.player = (JS / "player.js").read_text()
        self.audio = (JS / "audio-catalog.js").read_text()
        self.enemy = (JS / "enemy.js").read_text()

    def test_registry_fields_and_types(self):
        for field in (
            "id",
            "displayName",
            "maxHealth",
            "collisionSize",
            "collisionOffset",
            "damagedAsset",
            "destroyedAsset",
            "hitEffect",
            "destroyEffect",
            "hitSfx",
            "destroySfx",
            "explosive",
            "explosionDamage",
            "explosionRadius",
            "explosionDelay",
            "knockback",
            "dropTable",
            "persistent",
            "blocksMovement",
        ):
            self.assertIn(field, self.brk)
        for kind in TYPES:
            self.assertIn(f"{kind}:", self.brk)
        self.assertIn("maxHealth: 4 * HP", self.brk)
        self.assertIn("maxHealth: 3 * HP", self.brk)
        self.assertIn("maxHealth: 5 * HP", self.brk)
        self.assertIn("maxHealth: 6 * HP", self.brk)
        self.assertIn("explosionDamage: 3 * HP", self.brk)
        self.assertIn("explosionRadius: 90", self.brk)
        self.assertIn("explosionDelay: 0.45", self.brk)
        self.assertIn("explosionDamage: 4 * HP", self.brk)
        self.assertIn("explosionRadius: 110", self.brk)
        self.assertIn("explosionDelay: 0.65", self.brk)
        self.assertIn("bossMul: 0.15", self.brk)
        self.assertIn("applyExplosion", self.brk)
        self.assertIn("tryHitDestructible", self.brk)
        self.assertIn("DESTRUCTIBLE_DEFS", self.brk)

    def test_damage_pipeline_not_duplicated(self):
        self.assertIn("tryHitDestructible(this, shot)", self.game)
        self.assertIn("splashDestructibles(this, shot, exclude)", self.game)
        self.assertIn("tickDestructibles(this, dt)", self.game)
        self.assertIn("snapshotDestructibles(this.world)", self.game)
        self.assertIn("applyDestructibleSnapshot(this.world, snap.destructibles)", self.game)
        self.assertIn("cancelPendingExplosions(this)", self.game)
        self.assertIn("!s.destructibleId", self.game)
        self.assertIn("damageDestructiblesInRadius(ctx", self.abilities)
        storm = self.abilities.split("particle_storm: {", 1)[-1][:1600]
        self.assertNotIn("damageDestructiblesInRadius", storm)
        self.assertIn('consume("special")', self.player)

    def test_studio_01_placement(self):
        for obj_id in (
            "studio_01_crate_entrance",
            "studio_01_monitor_edit",
            "studio_01_crate_edit",
            "studio_01_film_edit",
            "studio_01_light_lighting",
            "studio_01_crate_lighting",
            "studio_01_ebox_vfx",
            "studio_01_monitor_client",
            "studio_01_crate_client",
            "studio_01_canister_client",
            "studio_01_barber_approach",
        ):
            self.assertIn(obj_id, self.s1)
        self.assertIn('kind: "compressed_air_canister"', self.s1)
        self.assertIn('kind: "electrical_control_box"', self.s1)
        self.assertIn('kind: "barber_supply_case"', self.s1)
        self.assertIn("x: t(92)", self.s1)
        self.assertIn("activateX: t(96)", self.s1)
        self.assertNotIn("destructibles:", self.s2)

    def test_drops_and_checkpoint_rules(self):
        self.assertIn("{ kind: null, weight: 45 }", self.brk)
        self.assertIn('{ kind: "ammo", weight: 25 }', self.brk)
        self.assertIn('{ kind: "health", weight: 15 }', self.brk)
        self.assertIn("d.dropped = true", self.brk)
        self.assertIn('state: pending ? "damaged" : d.state', self.brk)
        self.assertIn("restoreDrop", self.brk)
        self.assertIn("instantiateDestructible", self.world)
        self.assertIn("injectDestructibleSolids", self.world)

    def test_audio_and_assets(self):
        for key in (
            "destruct_metal",
            "destruct_wood",
            "destruct_glass",
            "destruct_overload",
            "destruct_hiss",
            "destruct_boom",
            "destruct_debris",
            "destruct_drop",
        ):
            self.assertIn(f"{key}:", self.audio)
            self.assertIn(f'sound("{key}"', self.audio)
        self.assertIn("sfx/destructibles/", self.audio)
        for rel in PLACEHOLDERS:
            path = ASSETS / rel
            self.assertTrue(path.is_file(), rel)
            with Image.open(path) as img:
                self.assertEqual(img.mode, "RGBA", rel)
                extrema = img.getextrema()
                self.assertLess(extrema[3][0], 255, msg=f"{rel} should have transparency")

    def test_no_assistant_producer_and_studio_02_untouched(self):
        self.assertNotIn("ENEMY_TYPES.assistant_producer", self.enemy)
        self.assertNotIn("assistant_producer", self.s1)
        self.assertIn('id: "studio_02"', self.s2)
        self.assertNotIn("electrical_control_box", self.s2)
        self.assertNotIn("compressed_air_canister", self.s2)


if __name__ == "__main__":
    unittest.main()
