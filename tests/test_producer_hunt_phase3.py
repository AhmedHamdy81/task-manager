"""Producer Hunt Phase 3 — enemy roster, AI, encounters, difficulty."""

from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"
ASSETS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "assets"

CLIENT_ANIMS = {"idle": 6, "walk": 8, "attack": 4, "hit": 3, "death": 6}


class ProducerHuntPhase3Tests(unittest.TestCase):
    def setUp(self):
        self.enemy = (JS / "enemy.js").read_text()
        self.ai = (JS / "enemy-ai.js").read_text()
        self.enc = (JS / "encounters.js").read_text()
        self.diff = (JS / "difficulty.js").read_text()
        self.s1 = (JS / "levels" / "studio-01.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.combat = (JS / "combat.js").read_text()
        self.settings = (JS / "settings.js").read_text()
        self.guide = (JS / "how-to-play.js").read_text()
        self.audio = (JS / "audio-catalog.js").read_text()

    def test_roster_types_and_balance(self):
        for key in ("post_producer:", "colorist:", "vfx_supervisor:", "client:", "boss_01:"):
            self.assertIn(key, self.enemy)
        self.assertIn('name: "Assistant Producer"', self.enemy)
        self.assertIn("health: 50", self.enemy)
        self.assertIn("health: 90", self.enemy)
        self.assertIn("health: 130", self.enemy)
        self.assertIn("health: 100", self.enemy)
        self.assertIn("chargeSpeed: 260", self.enemy)
        self.assertNotIn("ENEMY_TYPES.assistant_producer", self.enemy)
        self.assertNotIn("assistant_producer/", self.enemy)
        self.assertIn("crewEnemySpriteSrc", self.enemy)
        self.assertIn('behavior: "elite"', self.enemy)

    def test_shared_ai_states(self):
        for state in (
            "spawn",
            "idle",
            "patrol",
            "alert",
            "chase",
            "position",
            "telegraph",
            "attack",
            "recover",
            "hit",
            "retreat",
            "death",
        ):
            self.assertIn(f'"{state}"', self.ai)
        self.assertIn("export class AttackCoordinator", self.ai)
        self.assertIn("maxRanged", self.ai)
        self.assertIn("detected", self.ai)
        self.assertIn("aimAtTorso", self.ai)
        self.assertIn("_aiRanged", self.enemy)
        self.assertIn("_aiClose", self.enemy)
        self.assertIn("_aiArea", self.enemy)

    def test_encounter_director_and_studio_01(self):
        self.assertIn("export class EncounterDirector", self.enc)
        self.assertIn("pickEncounterSpawn", self.enc)
        self.assertIn("lockArena", self.enc)
        self.assertIn("SAFETY", self.enc)
        self.assertIn("EncounterDirector", self.game)
        self.assertIn("spawnEncounterEnemy", self.game)
        self.assertIn("unlockBoss: true", self.s1)
        self.assertIn('id: "enc_final"', self.s1)
        self.assertIn("activateX: t(96)", self.s1)
        self.assertIn("onStudioWavesCleared", self.game)
        self.assertNotIn("assistant_producer", self.s1)
        self.assertEqual(self.s1.count("0,0"), 0)

    def test_client_assets_live_under_enemies(self):
        expected = ASSETS / "characters" / "client" / "sprites" / "client_idle.png"
        actual_root = ASSETS / "enemies" / "client" / "sprites"
        self.assertFalse(expected.is_file())
        for anim, frames in CLIENT_ANIMS.items():
            path = actual_root / f"client_{anim}.png"
            self.assertTrue(path.is_file(), str(path))
            with Image.open(path) as img:
                self.assertEqual(img.size, (256 * frames, 256), path.name)
        self.assertIn("characters/client/sprites/", self.game)
        self.assertIn("using enemies/client/sprites/", self.game)

    def test_difficulty_and_settings(self):
        for key in ("easy:", "normal:", "hard:"):
            self.assertIn(key, self.diff)
        self.assertIn("difficulty: \"normal\"", self.settings)
        self.assertIn("cycleDifficulty", self.game)
        self.assertIn('kind: "cycle"', (JS / "ui.js").read_text())
        self.assertIn("encounter_start", self.audio)
        self.assertIn("enemy_telegraph", self.audio)

    def test_phase2_weapons_untouched(self):
        weapons = (JS / "player-weapons.js").read_text()
        self.assertIn("PLAYER_WEAPON_IDS", weapons)
        self.assertIn("shotgun", weapons)
        self.assertIn("heavy_blaster", weapons)
        self.assertIn("WeaponLoadout", weapons)
        player = (JS / "player.js").read_text()
        self.assertIn('consume("special")', player)

    def test_guide_covers_roster(self):
        for name in ("post_producer", "colorist", "vfx_supervisor", "client"):
            self.assertIn(name, self.guide)
        self.assertNotIn("assistant_producer", self.guide)


if __name__ == "__main__":
    unittest.main()
