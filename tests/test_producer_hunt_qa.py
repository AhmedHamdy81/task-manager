"""Producer Hunt release QA: assets, registry, combat contracts, persistence, cleanup."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ASSET_ROOT = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "assets"
JS_ROOT = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"

PLAYER_ANIMS = {
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
POST_PRODUCER_ANIMS = {"idle": 6, "walk": 8, "attack": 4, "hit": 3, "death": 6}
CHARACTERS = ("editor", "assistant", "vfx_supervisor", "colorist")
WORLD_SHEETS = {
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


class ProducerHuntReleaseQaTests(unittest.TestCase):
    def test_world_sheet_dimensions(self):
        for rel, size in WORLD_SHEETS.items():
            path = ASSET_ROOT / rel
            self.assertTrue(path.is_file(), rel)
            with Image.open(path) as img:
                self.assertEqual(img.size, size, rel)

    def test_character_strips_and_portraits(self):
        for cid in CHARACTERS:
            portrait = ASSET_ROOT / "characters" / cid / "portrait.png"
            self.assertTrue(portrait.is_file(), cid)
            with Image.open(portrait) as img:
                self.assertEqual(img.size, (512, 512), cid)
            for anim, frames in PLAYER_ANIMS.items():
                rel = ASSET_ROOT / "characters" / cid / "sprites" / f"{cid}_{anim}.png"
                self.assertTrue(rel.is_file(), rel.name)
                with Image.open(rel) as img:
                    self.assertEqual(img.size, (256 * frames, 256), rel.name)
                    self.assertEqual(img.mode, "RGBA")

    def test_post_producer_strips(self):
        for anim, frames in POST_PRODUCER_ANIMS.items():
            path = ASSET_ROOT / "enemies" / "post_producer" / "sprites" / f"post_producer_{anim}.png"
            self.assertTrue(path.is_file(), path.name)
            with Image.open(path) as img:
                self.assertEqual(img.size, (256 * frames, 256), path.name)
                self.assertEqual(img.mode, "RGBA")
        self.assertFalse(list(ASSET_ROOT.rglob("*assistant_producer*")))

    def test_no_fully_transparent_player_frames(self):
        for cid in CHARACTERS:
            path = ASSET_ROOT / "characters" / cid / "sprites" / f"{cid}_idle.png"
            with Image.open(path) as img:
                frame = img.convert("RGBA").crop((0, 0, 256, 256))
                alpha = list(frame.getchannel("A").getdata())
                self.assertGreater(max(alpha), 0, cid)

    def test_character_registry_complete(self):
        characters = (JS_ROOT / "characters.js").read_text()
        spec = (JS_ROOT / "sprite-spec.js").read_text()
        for cid in CHARACTERS:
            self.assertIn(f'id: "{cid}"', characters)
        for anim in PLAYER_ANIMS:
            self.assertIn(f"{anim}:", spec)
        self.assertIn("SHARED_PLAYER", characters)
        self.assertIn("characterById", characters)

    def test_post_producer_factory_and_legacy_alias(self):
        enemy = (JS_ROOT / "enemy.js").read_text()
        combat = (JS_ROOT / "combat.js").read_text()
        self.assertIn("post_producer:", enemy)
        self.assertNotIn("ENEMY_TYPES.assistant_producer", enemy)
        self.assertIn("LEGACY_ENEMY_ALIASES", enemy)
        self.assertIn("migrateEnemyType", enemy)
        self.assertIn('post_producer: "deadline_projectile"', combat)
        self.assertIn("deadline_projectile", combat)

    def test_projectile_single_hit_and_ownership(self):
        projectile = (JS_ROOT / "projectile.js").read_text()
        game = (JS_ROOT / "game.js").read_text()
        self.assertIn("this.owner = owner", projectile)
        self.assertIn("this.spent = true", projectile)
        self.assertIn("shot.disable()", game)
        self.assertIn("travelBounds", projectile)
        self.assertIn("if (!enemy.alive) continue", game)

    def test_pickup_single_collection_and_health_bounds(self):
        pickups = (JS_ROOT / "pickups.js").read_text()
        player = (JS_ROOT / "player.js").read_text()
        self.assertIn("pickup.taken = true", pickups)
        self.assertIn("if (!canCollectPickup(pickup, player)) return false", pickups)
        self.assertIn("Math.min(this.maxHealth", player)
        self.assertIn("Number.isFinite(amt)", player)

    def test_checkpoint_persistence_and_doors(self):
        game = (JS_ROOT / "game.js").read_text()
        prog = (JS_ROOT / "progression.js").read_text()
        settings = (JS_ROOT / "settings.js").read_text()
        self.assertIn("stats: { ...this.stats", game)
        self.assertIn("applySnapshot", game)
        self.assertIn("snap.stats", game)
        self.assertIn("tryOpenDoor", prog)
        self.assertIn("requireEncounters", prog)
        self.assertIn("!Array.isArray(raw)", settings)
        self.assertIn("normalizeSettings", settings)
        self.assertIn("bigbangadmin.producer_hunt", settings)
        self.assertIn("producerHunt.settings", settings)

    def test_state_exclusivity_and_cleanup(self):
        game = (JS_ROOT / "game.js").read_text()
        state = (JS_ROOT / "game-state.js").read_text()
        loader = (JS_ROOT / "asset-loader.js").read_text()
        self.assertIn("this.current = next", state)
        self.assertIn("disposeLevel", game)
        self.assertIn("cancelAnimationFrame", game)
        self.assertIn("_listenersOn", game)
        self.assertIn("_onPreventScroll", game)
        self.assertIn("allowDebug", game)
        self.assertIn("_inflight", loader)
        self.assertIn("_safeRel", loader)
        self.assertIn("loadTimeoutMs", loader)
        self.assertIn("if (this.characterKits.has(config.id))", loader)
        self.assertIn("nextPlayableLevel", game)
        self.assertIn("NEXT LEVEL", game)
        self.assertIn("openPause", game)
        self.assertIn("_deathOverlay", game)
        main = (JS_ROOT / "main.js").read_text()
        self.assertIn("if (allowDebug) window.__producerHunt = game", main)
        self.assertIn("pagehide", main)

    def test_no_dev_filesystem_paths_in_catalog(self):
        catalog = (JS_ROOT / "asset-catalog.js").read_text()
        self.assertNotIn("/Users/", catalog)
        self.assertIn('src: "environment/studio/backgrounds/studio_background_far.png"', catalog)


_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_producer_hunt_qa.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db  # noqa: E402
from permissions import register_permission_models, seed_permissions  # noqa: E402


class ProducerHuntProductionStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        with app.app_context():
            db.create_all()
            M = app.extensions["tm_test_models"]
            seed_permissions(db, register_permission_models(db), M["JobTitle"])

    def setUp(self):
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        db.session.query(self.M["User"]).delete()
        db.session.query(self.M["Account"]).delete()
        db.session.commit()
        self.user = self.M["Account"](email="ph-qa@test.local", password_hash="x", role="user")
        db.session.add(self.user)
        db.session.flush()
        db.session.add(self.M["User"](name="QA", email="ph-qa@test.local", account_id=self.user.id))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def _auth(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id

    def test_cache_busted_asset_and_module_paths(self):
        self._auth()
        r = self.client.get("/producer-hunt")
        html = r.get_data(as_text=True)
        self.assertIn("ph-20260819-clientvis", html)
        self.assertIn('data-allow-debug="1"', html)
        r = self.client.get(
            "/producer-hunt/static/assets/environment/studio/backgrounds/studio_background_far.png?v=ph-20260819-clientvis"
        )
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.data), 100)
        r = self.client.get("/producer-hunt/static/js/levels/studio-01.js?v=ph-20260819-clientvis")
        self.assertEqual(r.status_code, 200)
        self.assertIn('id: "studio_01"', r.get_data(as_text=True))

    def test_missing_asset_is_404_not_app_500(self):
        self._auth()
        r = self.client.get("/producer-hunt/static/assets/does-not-exist.png")
        self.assertEqual(r.status_code, 404)
        r = self.client.get("/projects")
        self.assertIn(r.status_code, (200, 302))
