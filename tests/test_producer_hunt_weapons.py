"""Producer Hunt phase-2 weapons system contracts."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"


def _block(src: str, weapon_id: str) -> str:
    match = re.search(rf"  {weapon_id}: \{{(.*?)\n  \}},", src, re.S)
    if not match:
        raise AssertionError(f"missing weapon {weapon_id}")
    return match.group(1)


class ProducerHuntWeaponsTests(unittest.TestCase):
    def setUp(self):
        self.registry = (JS / "player-weapons.js").read_text()
        self.player = (JS / "player.js").read_text()
        self.weapon = (JS / "weapon.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.hud = (JS / "hud.js").read_text()
        self.pickups = (JS / "pickups.js").read_text()
        self.input = (JS / "config.js").read_text()
        self.guide = (JS / "how-to-play.js").read_text()

    def test_four_weapons_registered(self):
        for weapon_id in ("pistol", "machine_gun", "shotgun", "heavy_blaster"):
            self.assertIn(f"{weapon_id}:", self.registry)
        pistol = _block(self.registry, "pistol")
        self.assertIn('ammoType: "unlimited"', pistol)
        self.assertIn("damage: 10", pistol)
        self.assertIn("fireInterval: 0.24", pistol)
        mg = _block(self.registry, "machine_gun")
        self.assertIn("automatic: true", mg)
        self.assertIn("fireInterval: 0.085", mg)
        shotgun = _block(self.registry, "shotgun")
        self.assertIn("pelletCount: 6", shotgun)
        self.assertIn("bossDamageMul: 0.45", shotgun)
        heavy = _block(self.registry, "heavy_blaster")
        self.assertIn("splashRadius: 75", heavy)
        self.assertIn("splashDamage: 10", heavy)
        self.assertIn("damage: 25", heavy)

    def test_player_uses_loadout_not_per_weapon_shooters(self):
        self.assertIn("class WeaponLoadout", self.registry)
        self.assertIn("tryAttack(", self.registry)
        self.assertIn("this.loadout.tryAttack", self.player)
        self.assertNotIn("if (this.weapon.id === \"shotgun\")", self.player)
        self.assertNotIn("if (this.character.id", self.player)
        self.assertIn("weaponShots", self.weapon)
        self.assertIn("pelletCount", self.weapon)

    def test_input_does_not_steal_special(self):
        self.assertIn('special: ["KeyQ"]', self.input)
        self.assertIn('weapon1: ["Digit1"]', self.input)
        self.assertIn('weaponCycle: ["KeyE"]', self.input)
        self.assertNotIn("weaponCycle: [\"KeyQ\"]", self.input)
        self.assertIn("weaponCycle", self.player)
        self.assertIn('input.consume("special")', self.player)

    def test_hud_ammo_and_empty(self):
        self.assertIn('"∞"', self.hud)
        self.assertIn("displayName", self.hud)
        self.assertIn("EMPTY", self.player)
        self.assertIn("EMPTY_SWAP_SEC", self.player)
        self.assertIn("weapon_empty", self.player)

    def test_pickups_and_factions(self):
        for kind in ("machine_gun", "shotgun", "heavy_blaster", "ammo"):
            self.assertIn(f'id: "{kind}"', self.pickups)
        self.assertIn('effect: "weapon"', self.pickups)
        self.assertNotIn('ammo: "energy"', self.pickups)
        self.assertIn("_applySplash", self.game)
        self.assertIn("bossDamageMul", self.game)
        self.assertIn('shot.faction = "player"', self.player)
        self.assertIn("if (enemy === this.player) return false", self.game)
        self.assertIn("loadout: this.player.loadout?.snapshot", self.game)

    def test_muzzle_and_levels(self):
        self.assertIn("_drawMuzzleMarker", self.player)
        self.assertIn("muzzleByAnim", self.player)
        studio = (JS / "levels" / "studio-01.js").read_text()
        self.assertIn('kind: "machine_gun"', studio)
        self.assertIn('kind: "shotgun"', studio)
        self.assertIn('kind: "heavy_blaster"', studio)
        self.assertIn('kind: "ammo"', studio)
        self.assertIn("PLAYER_WEAPON_DEFS", self.guide)
