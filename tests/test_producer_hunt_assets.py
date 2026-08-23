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

POST_PRODUCER = {
    "idle": 6,
    "walk": 8,
    "attack": 4,
    "hit": 3,
    "death": 6,
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
            with Image.open(portrait) as img:
                self.assertEqual(img.size, (512, 512), msg=f"{cid} portrait")
            for anim, frames in PLAYER.items():
                path = ROOT / "characters" / cid / "sprites" / f"{cid}_{anim}.png"
                self.assertTrue(path.is_file(), str(path))
                with Image.open(path) as img:
                    self.assertEqual(img.size, (256 * frames, 256), msg=path.name)

    def test_character_registry_and_select_menu(self):
        js_root = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"
        characters = (js_root / "characters.js").read_text()
        self.assertIn('id: "editor"', characters)
        self.assertIn('displayName: "The Editor"', characters)
        self.assertIn('displayName: "The Assistant"', characters)
        self.assertIn('displayName: "The VFX Supervisor"', characters)
        self.assertIn('displayName: "The Colorist"', characters)
        self.assertIn("SHARED_PLAYER", characters)
        self.assertIn("Unknown character", characters)
        self.assertIn('DEFAULT_CHARACTER_ID = "editor"', characters)
        select = (js_root / "character-select.js").read_text()
        self.assertIn("CONFIRM", select)
        self.assertIn("BACK", select)
        self.assertIn("drawContainedImage", select)
        self.assertIn("SELECT CHARACTER", select)
        self.assertIn("SPECIAL POWER", select)
        self.assertIn("STATISTICS", select)
        self.assertIn("LOCKED", select)
        self.assertIn("COMING SOON", select)
        self.assertIn("previewAnimation", select)
        self.assertIn("loadOptionalImage", select)
        self.assertIn("isCharacterUnlocked", select)
        settings = (js_root / "settings.js").read_text()
        self.assertIn("bigbangadmin.producer_hunt", settings)
        self.assertIn("LEGACY_SETTINGS_KEY", settings)
        player = (js_root / "player.js").read_text()
        self.assertIn("_canStand", player)
        game = (js_root / "game.js").read_text()
        self.assertIn("confirmCharacter", game)
        self.assertIn("ENEMY_TYPES.post_producer", game)

    def test_post_producer_strips_match_spec(self):
        root = ROOT / "enemies" / "post_producer"
        for anim, frames in POST_PRODUCER.items():
            path = root / "sprites" / f"post_producer_{anim}.png"
            self.assertTrue(path.is_file(), str(path))
            with Image.open(path) as img:
                self.assertEqual(img.size, (256 * frames, 256), msg=path.name)
        impact = root / "effects" / "post_producer_attack_impact.png"
        self.assertTrue(impact.is_file(), str(impact))
        with Image.open(impact) as img:
            self.assertEqual(img.size, (512, 128))

    def test_active_level_spawns_post_producer_not_assistant(self):
        level = (
            Path(__file__).resolve().parents[1]
            / "producer_hunt"
            / "static"
            / "producer_hunt"
            / "js"
            / "levels"
            / "studio-01.js"
        ).read_text()
        self.assertIn('id: "studio_01"', level)
        self.assertIn("The Post Suite", level)
        self.assertIn('type: "post_producer"', level)
        self.assertNotIn("assistant_producer", level)
        self.assertGreaterEqual(level.count('type: "post_producer"'), 5)
        self.assertIn("STUDIO_01_WAVES", level)
        self.assertIn("STUDIO_01_ENCOUNTERS", level)
        self.assertIn("enc_final", level)
        self.assertIn("studio_01_gate", level)
        self.assertIn("studio_01_exit", level)
        self.assertIn("studio_01_mid", level)
        self.assertIn("studio_01_key", level)

        reexport = (
            Path(__file__).resolve().parents[1]
            / "producer_hunt"
            / "static"
            / "producer_hunt"
            / "js"
            / "levels"
            / "level-01.js"
        ).read_text()
        self.assertIn("STUDIO_01", reexport)
        self.assertIn("validateLevel", reexport)

    def test_legacy_assistant_producer_alias_exists(self):
        enemy = (
            Path(__file__).resolve().parents[1]
            / "producer_hunt"
            / "static"
            / "producer_hunt"
            / "js"
            / "enemy.js"
        ).read_text()
        self.assertIn("LEGACY_ENEMY_ALIASES", enemy)
        self.assertIn("assistant_producer", enemy)
        self.assertIn(
            '[Producer Hunt] Migrated legacy enemy type "assistant_producer" to "post_producer".',
            enemy,
        )
        self.assertIn("post_producer", enemy)
        game = (
            Path(__file__).resolve().parents[1]
            / "producer_hunt"
            / "static"
            / "producer_hunt"
            / "js"
            / "game.js"
        ).read_text()
        self.assertIn("ENEMY_TYPES.post_producer", game)
        self.assertNotIn("ENEMY_TYPES.assistant_producer", game)

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
            "weapons/player_weapons.png": (1024, 256),
            "enemies/post_producer/effects/post_producer_attack_impact.png": (512, 128),
            "enemies/client/effects/client_attack_impact.png": (512, 128),
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
            "weapons/player_weapons.png",
            "enemies/post_producer/effects/post_producer_attack_impact.png",
            "enemies/client/effects/client_attack_impact.png",
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

    def test_weapon_and_projectile_integration(self):
        js_root = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"
        combat = (js_root / "combat.js").read_text()
        self.assertIn("weaponDefForCharacter", combat)
        self.assertIn('editor: "editor_pulse"', combat)
        self.assertIn('assistant: "assistant_scan_bolt"', combat)
        self.assertIn('vfx_supervisor: "vfx_orb"', combat)
        self.assertIn('colorist: "colorist_chroma_bolt"', combat)
        self.assertIn('post_producer: "deadline_projectile"', combat)
        self.assertIn('client: "client_revision_pulse"', combat)
        self.assertIn("damage: 10", combat)
        self.assertIn("cooldown: 0.25", combat)
        self.assertIn("lifetime: 2", combat)
        self.assertIn("speed: 650", combat)
        self.assertIn("speed: 360", combat)
        self.assertIn("lifetime: 2.5", combat)
        self.assertIn("x: 42", combat)
        self.assertIn("y: -104", combat)
        self.assertIn("x: 48", combat)
        self.assertIn("y: -63", combat)
        self.assertIn("hitW: 32", combat)
        self.assertIn("hitH: 20", combat)
        self.assertIn("hitW: 36", combat)
        self.assertIn("hitH: 36", combat)
        self.assertIn("hitW: 34", combat)
        self.assertIn("hitH: 24", combat)
        self.assertIn("spawnFrame: 1", combat)
        self.assertIn("spawnFrame: 2", combat)
        self.assertIn('sheetKey: "post_producer_impact"', combat)

        player = (js_root / "player.js").read_text()
        self.assertIn("crouch_shoot", player)
        self.assertIn("_trySpawnShot", player)
        self.assertIn("COMBAT.player.muzzle", player)
        self.assertIn("renderWeaponOverlay", player)
        self.assertIn("muzzleByAnim", player)
        self.assertNotIn("if (this.character.id", player)

        projectile = (js_root / "projectile.js").read_text()
        self.assertIn("flipArt", projectile)
        self.assertIn("disable()", projectile)
        self.assertNotIn("character.id", projectile)

        enemy = (js_root / "enemy.js").read_text()
        self.assertIn("_trySpawnShot", enemy)
        self.assertIn("lineBlocked", enemy)
        self.assertNotIn("tryAttack", enemy)
        self.assertNotIn("assistant_producer/", enemy)

        game = (js_root / "game.js").read_text()
        self.assertIn('shot.owner === "enemy"', game)
        self.assertIn("spawnImpact", game)
        self.assertIn("this.fx.spawn", game)
        self.assertIn("export class FxPool", (js_root / "fx.js").read_text())
        self.assertNotIn("ENEMY_TYPES.assistant_producer", game)

        catalog = (js_root / "asset-catalog.js").read_text()
        self.assertIn("weapons/player_weapons.png", catalog)

        weapons = ROOT / "weapons" / "player_weapons.png"
        self.assertTrue(weapons.is_file(), str(weapons))
        with Image.open(weapons) as img:
            self.assertEqual(img.size, (1024, 256))

    def test_pickups_and_hud_integration(self):
        js_root = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"
        pickups = (js_root / "pickups.js").read_text()
        self.assertIn('id: "health"', pickups)
        self.assertIn('id: "energy"', pickups)
        self.assertIn('id: "production_token"', pickups)
        self.assertIn('id: "access_key"', pickups)
        self.assertIn('id: "bonus"', pickups)
        self.assertIn("reserved: true", pickups)
        self.assertIn("data_card", pickups)
        self.assertIn("headset", pickups)
        self.assertIn("value: PICKUP_VALUES.health", pickups)
        self.assertIn("PICKUP_HIT = 36", pickups)
        self.assertIn("canCollectPickup", pickups)
        self.assertIn("applyPickup", pickups)
        self.assertIn('effect: "energy"', pickups)
        self.assertIn('pickup.effect === "ammo"', pickups)

        hud = (js_root / "hud.js").read_text()
        self.assertIn("portraitImage", hud)
        self.assertIn("invalidate", hud)
        self.assertIn("signature", hud)
        self.assertIn("HUD_FRAMES.health", hud)
        self.assertIn("HUD_FRAMES.ammo", hud)
        self.assertIn("HUD_FRAMES.score", hud)
        self.assertIn("HUD_FRAMES.objective", hud)
        self.assertIn("placeholder", hud)
        self.assertNotIn("energy /", hud)

        player = (js_root / "player.js").read_text()
        self.assertIn("heal(", player)
        self.assertIn("this.keys = 0", player)
        self.assertIn("Math.max(0", player)

        game = (js_root / "game.js").read_text()
        self.assertIn("captureCheckpoint", game)
        self.assertIn("applySnapshot", game)
        self.assertIn("applyPickup", game)
        self.assertNotIn("assistant_producer/", game)

        level = (js_root / "levels" / "studio-01.js").read_text()
        self.assertIn("studio_01_health_post", level)
        self.assertIn("studio_01_health_pre_boss", level)
        self.assertIn("studio_01_key", level)
        self.assertIn('kind: "energy"', level)
        self.assertIn('kind: "production_token"', level)

        world = (js_root / "levels" / "world.js").read_text()
        self.assertIn("instantiatePickup", world)
        self.assertIn("validateLevel", world)

        portraits = [
            "characters/editor/portrait.png",
            "characters/assistant/portrait.png",
            "characters/vfx_supervisor/portrait.png",
            "characters/colorist/portrait.png",
        ]
        for rel in portraits:
            path = ROOT / rel
            self.assertTrue(path.is_file(), str(path))
            with Image.open(path) as img:
                self.assertEqual(img.size, (512, 512), msg=rel)

    def test_hazards_doors_and_progression(self):
        js_root = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"
        prog = (js_root / "progression.js").read_text()
        self.assertIn("HAZARD_DEFS", prog)
        self.assertIn("live_cable", prog)
        self.assertIn("cable_coil", prog)
        self.assertIn("reserved: true", prog)
        self.assertIn("HAZARD_DAMAGE = 10", prog)
        self.assertIn("HAZARD_COOLDOWN = 0.75", prog)
        self.assertIn("DOOR_DEFS", prog)
        self.assertIn("CHECKPOINT_FRAMES", prog)
        self.assertIn("tryOpenDoor", prog)
        self.assertIn("findSafeSpawn", prog)
        self.assertIn("canCompleteLevel", prog)

        self.assertIn("requireEncounters", prog)
        self.assertIn("encountersCleared", prog)
        self.assertIn('d.state !== "open"', prog)

        game = (js_root / "game.js").read_text()
        self.assertIn("updateHazards", game)
        self.assertIn("beginRespawn", game)
        self.assertIn("completeLevel", game)
        self.assertIn("updateEncounters", game)
        self.assertIn("STUDIO_01", game)
        self.assertIn("LevelDataError", game)
        self.assertIn("RESPAWNING", game)
        self.assertNotIn("assistant_producer/", game)

        player = (js_root / "player.js").read_text()
        self.assertIn("knockbackX", player)
        self.assertIn("inputLocked", player)
        self.assertNotIn("studio_01_gate", player)

        level = (js_root / "levels" / "studio-01.js").read_text()
        self.assertIn("studio_01_gate", level)
        self.assertIn("studio_01_exit", level)
        self.assertIn("studio_01_cable_intro", level)
        self.assertIn('kind: "live_cable"', level)
        self.assertIn("CAMERA", (js_root / "config.js").read_text())
        self.assertIn("followY: 5.8", (js_root / "config.js").read_text())
        catalog = (js_root / "asset-catalog.js").read_text()
        self.assertIn("factor: 0.1", catalog)
        self.assertIn("factor: 0.3", catalog)
        self.assertIn("factor: 0.55", catalog)

        expected = {
            "environment/studio/hazards/studio_hazards.png": (768, 128),
            "environment/studio/progression/progression_objects.png": (1536, 256),
            "environment/studio/props/studio_props.png": (1024, 128),
            "environment/studio/tiles/studio_platform_tiles.png": (512, 64),
        }
        for rel, size in expected.items():
            path = ROOT / rel
            self.assertTrue(path.is_file(), str(path))
            with Image.open(path) as img:
                self.assertEqual(img.size, size, msg=rel)

    def test_special_power_images(self):
        names = (
            "editor_timeline_freeze.png",
            "assistant_production_rush.png",
            "colorist_color_blast.png",
            "vfx_supervisor_particle_storm.png",
        )
        for name in names:
            path = ROOT / "abilities" / name
            self.assertTrue(path.is_file(), str(path))
            with Image.open(path) as img:
                self.assertEqual(img.size, (256, 256), msg=name)
                self.assertEqual(img.mode, "RGBA", msg=name)

    def test_pause_death_completion_and_settings(self):
        js_root = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"
        settings = (js_root / "settings.js").read_text()
        self.assertIn("SETTINGS_DEFAULTS", settings)
        self.assertIn("masterVolume: MIX.masterVolume", settings)
        self.assertIn("musicVolume: MIX.musicVolume", settings)
        self.assertIn("effectsVolume: MIX.effectsVolume", settings)
        self.assertIn("voiceVolume: MIX.voiceVolume", settings)
        self.assertIn('screenShake: "full"', settings)
        self.assertIn('particleDensity: "medium"', settings)
        self.assertIn("reducedMotion: false", settings)
        self.assertIn("bigbangadmin.producer_hunt", settings)
        self.assertIn("LEGACY_SETTINGS_KEY", settings)
        self.assertIn("normalizeSettings", settings)

        ui = (js_root / "ui.js").read_text()
        self.assertIn("drawSettings", ui)
        self.assertIn("drawConfirm", ui)
        self.assertIn("▸", ui)

        game = (js_root / "game.js").read_text()
        self.assertIn("RESTART FROM CHECKPOINT", game)
        self.assertIn("RETURN TO MAIN MENU", game)
        self.assertIn("RESUME FROM CHECKPOINT", game)
        self.assertIn("REPLAY LEVEL", game)
        self.assertIn("CHARACTER SELECTION", game)
        self.assertIn("openPause", game)
        self.assertIn("disposeLevel", game)
        self.assertIn("_deathOverlay", game)
        self.assertIn("onVisibility", game)
        self.assertIn("clearTransient", game)
        self.assertIn("toggleFullscreen", game)
        self.assertIn("STUDIO 01 COMPLETE", (js_root / "results.js").read_text())
        self.assertIn("The Post Suite", (js_root / "levels" / "studio-01.js").read_text())
        self.assertIn("NEXT LEVEL", game)
        self.assertIn("nextPlayableLevel", game)
        self.assertNotIn("assistant_producer/", game)

        audio = (js_root / "audio.js").read_text()
        self.assertIn("applyMix", audio)

        title = ROOT / "ui" / "menu" / "title_background.png"
        logo = ROOT / "ui" / "menu" / "logo.png"
        self.assertTrue(title.is_file())
        self.assertTrue(logo.is_file())
        with Image.open(title) as img:
            self.assertEqual(img.size, (1920, 1080))
        with Image.open(logo) as img:
            self.assertEqual(img.size, (1200, 500))
