"""Placeholder sprite sheets match the production 256px strip contract."""

from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "assets"

PLAYER = {
    "idle": 6,
    "run": 8,
    "jump": 4,
    "fall": 2,
    "crouch": 2,
    "shoot": 4,
    "crouch_shoot": 4,
    "hit": 3,
    "death": 8,
}

ENEMY = {
    "idle": 6,
    "walk": 8,
    "run": 8,
    "attack": 6,
    "hit": 3,
    "death": 8,
}


class ProducerHuntAssetPipelineTests(unittest.TestCase):
    def test_editor_idle_production_slot(self):
        path = ROOT / "characters" / "editor" / "sprites" / "editor_idle.png"
        with Image.open(path) as img:
            self.assertEqual(img.size, (1536, 256))
            self.assertEqual(img.size[0] // 256, 6)
        for anim, frames in PLAYER.items():
            path = ROOT / "characters" / "editor" / "sprites" / f"editor_{anim}.png"
            self.assertTrue(path.is_file(), str(path))
            with Image.open(path) as img:
                self.assertEqual(img.size, (256 * frames, 256), msg=path.name)

    def test_all_player_ids_have_full_sets(self):
        for cid in ("editor", "assistant", "vfx_supervisor", "colorist"):
            portrait = ROOT / "characters" / cid / "portrait.png"
            self.assertTrue(portrait.is_file(), str(portrait))
            for anim, frames in PLAYER.items():
                path = ROOT / "characters" / cid / "sprites" / f"{cid}_{anim}.png"
                self.assertTrue(path.is_file(), str(path))
                with Image.open(path) as img:
                    self.assertEqual(img.size, (256 * frames, 256), msg=path.name)

    def test_assistant_producer_strips_match_spec(self):
        for anim, frames in ENEMY.items():
            path = ROOT / "enemies" / "assistant_producer" / f"assistant_producer_{anim}.png"
            self.assertTrue(path.is_file(), str(path))
            with Image.open(path) as img:
                self.assertEqual(img.size, (256 * frames, 256), msg=path.name)

    def test_world_production_assets_match_expected_sizes(self):
        expected = {
            "environment/studio/backgrounds/studio_background_far.png": (1920, 1080),
            "environment/studio/backgrounds/studio_background_mid.png": (1920, 1080),
            "environment/studio/backgrounds/studio_background_near.png": (1920, 1080),
            "environment/studio/tiles/studio_platform_tiles.png": (512, 64),
            "environment/studio/props/studio_props.png": (1024, 128),
            "environment/studio/hazards/studio_hazards.png": (768, 128),
            "environment/studio/progression/progression_objects.png": (1536, 256),
            "pickups/pickups.png": (512, 64),
            "projectiles/projectiles.png": (1024, 128),
            "effects/gameplay_effects.png": (1024, 128),
            "ui/hud/hud_icons.png": (512, 64),
            "ui/menu/title_background.png": (1920, 1080),
            "ui/menu/logo.png": (1200, 500),
        }
        for rel, size in expected.items():
            path = ROOT / rel
            self.assertTrue(path.is_file(), str(path))
            with Image.open(path) as img:
                self.assertEqual(img.size, size, msg=rel)

    def test_catalog_registers_world_asset_paths(self):
        catalog = (
            Path(__file__).resolve().parents[1]
            / "producer_hunt"
            / "static"
            / "producer_hunt"
            / "js"
            / "asset-catalog.js"
        ).read_text()
        for rel in (
            "environment/studio/backgrounds/studio_background_far.png",
            "pickups/pickups.png",
            "projectiles/projectiles.png",
            "effects/gameplay_effects.png",
            "ui/hud/hud_icons.png",
            "ui/menu/title_background.png",
            "ui/menu/logo.png",
        ):
            self.assertIn(rel, catalog)

    def test_loader_logs_dimension_errors(self):
        text = (
            Path(__file__).resolve().parents[1]
            / "producer_hunt"
            / "static"
            / "producer_hunt"
            / "js"
            / "asset-loader.js"
        ).read_text()
        self.assertIn("[Producer Hunt Asset Validation]", text)
        self.assertIn("Using placeholder fallback.", text)
        self.assertIn("Expected:", text)
        self.assertIn("Actual:", text)
        self.assertIn("validateImageSize", text)
        self.assertIn("loadCatalog", text)
