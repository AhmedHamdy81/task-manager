"""Producer Hunt audio registry, event wiring, and optional files."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"
AUDIO_DIR = ROOT / "producer_hunt" / "static" / "producer_hunt" / "assets" / "audio"

REQUIRED = [
    "music/menu_theme.ogg",
    "music/studio_01_theme.ogg",
    "music/level_complete.ogg",
    "sfx/ui_move.ogg",
    "sfx/ui_confirm.ogg",
    "sfx/ui_back.ogg",
    "sfx/editor_shoot.ogg",
    "sfx/assistant_shoot.ogg",
    "sfx/vfx_supervisor_shoot.ogg",
    "sfx/colorist_shoot.ogg",
    "sfx/post_producer_attack.ogg",
    "sfx/player_hit.ogg",
    "sfx/enemy_hit.ogg",
    "sfx/projectile_impact.ogg",
    "sfx/pickup_collect.ogg",
    "sfx/checkpoint_activate.ogg",
    "sfx/door_open.ogg",
    "sfx/player_death.ogg",
    "sfx/level_complete.ogg",
]


class ProducerHuntAudioTests(unittest.TestCase):
    def test_registry_ids_and_categories(self):
        catalog = (JS / "audio-catalog.js").read_text()
        for key in (
            "menu_theme",
            "studio_01_theme",
            "level_complete_music",
            "ui_move",
            "ui_confirm",
            "ui_back",
            "editor_shoot",
            "assistant_shoot",
            "vfx_supervisor_shoot",
            "colorist_shoot",
            "post_producer_attack",
            "player_hit",
            "enemy_hit",
            "projectile_impact",
            "pickup_collect",
            "checkpoint_activate",
            "door_open",
            "player_death",
            "level_complete",
        ):
            self.assertIn(f"{key}:", catalog)
            self.assertIn(f'sound("{key}"', catalog)
        self.assertIn(', "music"', catalog)
        self.assertIn(', "effects"', catalog)
        self.assertIn(', "ui"', catalog)
        self.assertIn("maxInstances: 3", catalog)
        self.assertIn("maxInstances: 4", catalog)
        self.assertIn("WEAPON_SOUND_ID", catalog)
        self.assertIn("editor_pulse: \"editor_shoot\"", catalog)
        self.assertIn("deadline_projectile: \"post_producer_attack\"", catalog)

    def test_mixer_has_unlock_pause_and_optional_load(self):
        audio = (JS / "audio.js").read_text()
        self.assertIn("async unlock", audio)
        self.assertIn("playMusic", audio)
        self.assertIn("pauseMusic", audio)
        self.assertIn("resumeMusic", audio)
        self.assertIn("stopGameplayVoices", audio)
        self.assertIn("setGameplayMuted", audio)
        self.assertIn("Missing optional sound", audio)
        self.assertIn("Autoplay was blocked", audio)
        self.assertIn("MUSIC_CROSSFADE_SEC", audio)
        self.assertIn("createStereoPanner", audio)
        self.assertIn("this.volumes.master * this.volumes[cat] * def.volume", audio)
        self.assertIn("dispose", audio)
        self.assertNotIn("copyrighted arcade", audio)

    def test_game_wires_authoritative_events(self):
        game = (JS / "game.js").read_text()
        player = (JS / "player.js").read_text()
        enemy = (JS / "enemy.js").read_text()
        self.assertIn('playMusic("menu_theme")', game)
        self.assertIn('playMusic(this.world.music || "studio_01_theme", { restart: true })', game)
        self.assertIn('playMusic("level_complete_music")', game)
        self.assertIn('sfx("ui_move")', game)
        self.assertIn('sfx("ui_confirm")', game)
        self.assertIn('sfx("ui_back")', game)
        self.assertIn('sfx("player_hit")', game)
        self.assertIn('sfx("enemy_hit"', game)
        self.assertIn('sfx("projectile_impact"', game)
        self.assertIn('sfx("pickup_collect"', game)
        self.assertIn('sfx("checkpoint_activate"', game)
        self.assertIn('sfx("door_open"', game)
        self.assertIn('sfx("player_death"', game)
        self.assertIn('sfx("level_complete"', game)
        self.assertIn("audio.dispose()", game)
        self.assertIn("pauseMusic()", game)
        self.assertIn("resumeMusic()", game)
        self.assertIn("WEAPON_SOUND_ID", player)
        self.assertIn("editor_shoot", player)
        self.assertIn("post_producer_attack", enemy)
        self.assertIn("if (!dealt) continue", game)

    def test_required_binaries_are_optional_and_listed(self):
        required_doc = (AUDIO_DIR / "REQUIRED.txt").read_text()
        catalog = (JS / "audio-catalog.js").read_text()
        for rel in REQUIRED:
            self.assertIn(rel, required_doc)
            stem = rel.rsplit(".", 1)[0]
            self.assertIn(f"audio/{stem}", catalog)


if __name__ == "__main__":
    unittest.main()
