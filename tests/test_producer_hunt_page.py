"""Producer Hunt page is isolated and login-gated."""

from __future__ import annotations

import os
import tempfile
import unittest

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_producer_hunt_unittest.db")
os.close(_fd)
os.environ.setdefault("TASK_MANAGER_TEST_DATABASE", f"sqlite:///{_TEST_DB_PATH}")

from app import app, db
from permissions import register_permission_models, seed_permissions


class ProducerHuntPageTests(unittest.TestCase):
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
        self.user = self.M["Account"](
            email="ph-user@test.local", password_hash="x", role="user"
        )
        db.session.add(self.user)
        db.session.flush()
        db.session.add(
            self.M["User"](
                name="PH User",
                email="ph-user@test.local",
                account_id=self.user.id,
            )
        )
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def test_requires_login(self):
        r = self.client.get("/producer-hunt")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers.get("Location", ""))

    def test_page_loads_for_signed_in_user(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        r = self.client.get("/producer-hunt")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("ph-canvas", html)
        self.assertIn("EXIT GAME", html)
        self.assertNotIn("app-sidebar", html)
        self.assertIn("/producer-hunt/static/js/main.js", html)
        self.assertIn('width="1920"', html)

    def test_static_js_served(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        r = self.client.get("/producer-hunt/static/js/main.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Game", r.get_data(as_text=True))

    def test_game_state_module_served(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        r = self.client.get("/producer-hunt/static/js/game-state.js")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("CHARACTER_SELECT", body)
        self.assertIn("LEVEL_COMPLETE", body)

    def test_studio_level_module_served(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        r = self.client.get("/producer-hunt/static/js/levels/studio-01.js")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn('id: "studio_01"', body)
        self.assertIn("The Post Suite", body)
        self.assertNotIn("assistant_producer", body)
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        r = self.client.get("/producer-hunt/static/js/asset-catalog.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("WORLD_SHEETS", r.get_data(as_text=True))

    def test_studio_background_served(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        r = self.client.get(
            "/producer-hunt/static/assets/environment/studio/backgrounds/studio_background_far.png"
        )
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.data), 100)

    def test_post_producer_idle_served(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        r = self.client.get(
            "/producer-hunt/static/assets/enemies/post_producer/sprites/post_producer_idle.png"
        )
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.data), 100)

    def test_menu_modules_served(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        for path in (
            "/producer-hunt/static/js/ui.js",
            "/producer-hunt/static/js/settings.js",
            "/producer-hunt/static/js/audio.js",
        ):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
        ui = self.client.get("/producer-hunt/static/js/ui.js").get_data(as_text=True)
        self.assertIn("drawSettings", ui)
        self.assertIn("drawConfirm", ui)

    def test_placeholder_idle_strip_served(self):
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        r = self.client.get("/producer-hunt/static/assets/characters/editor/sprites/editor_idle.png")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.data), 100)

    def test_static_requires_login(self):
        r = self.client.get("/producer-hunt/static/js/main.js")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers.get("Location", ""))

    def test_debug_flag_off_when_production(self):
        from unittest.mock import patch

        import producer_hunt.routes as ph_routes

        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        with patch.object(ph_routes, "is_production_env", return_value=True):
            r = self.client.get("/producer-hunt")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn('data-allow-debug="0"', html)
        self.assertIn("ph-20260819-prod", html)

    def test_machine_room_role_cannot_open_game(self):
        self.user.role = "machine_room"
        db.session.commit()
        with self.client.session_transaction() as sess:
            sess["account_id"] = self.user.id
        r = self.client.get("/producer-hunt")
        self.assertIn(r.status_code, (302, 403))
        if r.status_code == 302:
            self.assertNotIn("/producer-hunt", r.headers.get("Location", ""))
