"""Producer Hunt audio registry, event wiring, and optional MP3 files."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"
AUDIO_DIR = ROOT / "producer_hunt" / "static" / "producer_hunt" / "assets" / "audio"

REQUIRED = [
    "music/menu_theme.mp3",
    "music/studio_01_theme.mp3",
    "music/gameplay_music.mp3",
    "music/boss_music.mp3",
    "music/boss_01_theme.mp3",
    "music/game_over_music.mp3",
    "sfx/player_shoot.mp3",
    "sfx/player_hit.mp3",
    "sfx/player_jump.mp3",
    "sfx/player_land.mp3",
    "sfx/player_death.mp3",
    "sfx/enemy_hit.mp3",
    "sfx/enemy_death.mp3",
    "sfx/projectile_impact.mp3",
    "sfx/pickup_collect.mp3",
    "sfx/health_pickup.mp3",
    "sfx/ammo_pickup.mp3",
    "sfx/powerup_collect.mp3",
    "sfx/boss_warning.mp3",
    "sfx/level_complete.mp3",
    "sfx/game_over.mp3",
    "sfx/ui_hover.mp3",
    "sfx/ui_confirm.mp3",
    "sfx/ui_back.mp3",
    "sfx/pause.mp3",
]

CANONICAL_KEYS = [
    "music_menu",
    "music_studio_01",
    "music_gameplay",
    "music_boss",
    "music_boss_01",
    "music_game_over",
    "player_shoot",
    "player_hit",
    "player_jump",
    "player_land",
    "player_death",
    "enemy_hit",
    "enemy_death",
    "projectile_impact",
    "pickup_collect",
    "health_pickup",
    "ammo_pickup",
    "powerup_collect",
    "boss_warning",
    "level_complete",
    "game_over",
    "ui_hover",
    "ui_confirm",
    "ui_back",
    "pause",
]


class ProducerHuntAudioTests(unittest.TestCase):
    def test_registry_ids_and_mp3_paths(self):
        catalog = (JS / "audio-catalog.js").read_text()
        for key in CANONICAL_KEYS:
            self.assertIn(f"{key}:", catalog)
            self.assertIn(f'sound("{key}"', catalog)
        self.assertIn("music/menu_theme", catalog)
        self.assertNotIn("menu_music", catalog)
        self.assertIn("music/studio_01_theme", catalog)
        self.assertIn("LEVEL_MUSIC", catalog)
        self.assertIn('studio_01: "music_studio_01"', catalog)
        self.assertIn("volume: 0.42", catalog)
        self.assertIn("music/gameplay_music", catalog)
        self.assertIn("music/boss_music", catalog)
        self.assertIn("music/game_over_music", catalog)
        self.assertIn("sfx/player_shoot", catalog)
        self.assertIn(', "music"', catalog)
        self.assertIn(', "effects"', catalog)
        self.assertIn(', "ui"', catalog)
        self.assertIn("maxInstances: 3", catalog)
        self.assertIn("maxInstances: 4", catalog)
        self.assertIn("WEAPON_SOUND_ID", catalog)
        self.assertIn('editor_pulse: "player_shoot"', catalog)
        self.assertIn("SOUND_ALIASES", catalog)
        self.assertIn("pickupSoundId", catalog)
        self.assertNotIn("createOscillator", catalog)

    def test_mixer_has_unlock_pause_and_optional_load(self):
        audio = (JS / "audio.js").read_text()
        self.assertIn("async unlock", audio)
        self.assertIn("playMusic", audio)
        self.assertIn("stopMusic", audio)
        self.assertIn("pauseMusic", audio)
        self.assertIn("resumeMusic", audio)
        self.assertIn("stopGameplayVoices", audio)
        self.assertIn("setGameplayMuted", audio)
        self.assertIn("Missing optional sound", audio)
        self.assertIn(".mp3", audio)
        self.assertIn("Autoplay was blocked", audio)
        self.assertIn("MUSIC_LOOP_CROSSFADE_SEC", audio)
        self.assertIn("_overlapMusicLoop", audio)
        self.assertIn("_scheduleMusicLoop", audio)
        self.assertIn("createStereoPanner", audio)
        self.assertIn("this.volumes.master * this.volumes[cat] * def.volume", audio)
        self.assertIn("this.muted ? 0 : this.volumes.master", audio)
        self.assertIn("ensureMusic", audio)
        self.assertIn("_mixerReady", audio)
        self.assertIn('this._ctx.state === "interrupted"', audio)
        self.assertIn("_isUsableMusic", audio)
        self.assertNotIn("if (this._missing.has(def.id)) this.stopMusic", audio)
        self.assertNotIn("createOscillator", audio)
        self.assertNotIn("copyrighted arcade", audio)

    def test_game_wires_authoritative_events(self):
        game = (JS / "game.js").read_text()
        player = (JS / "player.js").read_text()
        enemy = (JS / "enemy.js").read_text()
        self.assertIn("playMenuMusic", game)
        self.assertIn("playLevelMusic", game)
        self.assertIn("ensureMusic", game)
        self.assertIn('hasBuffer("music_game_over")', game)
        self.assertIn('playMusic("music_game_over")', game)
        self.assertIn('playMusic("music_menu"', game)
        self.assertIn("loop: true", game)
        self.assertIn("volume: 0.4", game)
        self.assertIn("musicForLevel", game)
        self.assertIn("musicPlayOpts", game)
        self.assertNotIn("restart: true", game)
        self.assertIn("playBossMusic", game)
        self.assertIn("music_boss_01", game)
        self.assertIn("music_boss", game)
        self.assertIn("audio.unlock().then(start)", game)
        self.assertIn("stopMusic", game)
        self.assertIn('sfx("ui_hover")', game)
        self.assertIn('sfx("ui_confirm")', game)
        self.assertIn('sfx("ui_back")', game)
        self.assertIn('sfx("pause")', game)
        self.assertIn('sfx("player_hit")', game)
        self.assertIn('sfx("enemy_hit"', game)
        self.assertIn('sfx("enemy_death"', game)
        self.assertIn('opts.sfx', game)
        self.assertIn("pickupSoundId", game)
        self.assertIn('sfx("player_death"', game)
        self.assertIn('sfx("level_complete"', game)
        self.assertIn('sfx("game_over"', game)
        self.assertIn("audio.dispose()", game)
        self.assertIn("pauseMusic()", game)
        self.assertIn("resumeMusic()", game)
        self.assertIn("updateBossMusic", game)
        self.assertIn("WEAPON_SOUND_ID", player)
        self.assertIn("player_shoot", player)
        self.assertIn("player_jump", player)
        self.assertIn("player_land", player)
        self.assertNotIn("post_producer_attack", enemy)
        self.assertIn("if (!dealt) continue", game)

    def test_mp3s_are_optional_and_listed(self):
        required_doc = (AUDIO_DIR / "REQUIRED.txt").read_text()
        catalog = (JS / "audio-catalog.js").read_text()
        self.assertTrue((AUDIO_DIR / "music").is_dir())
        self.assertTrue((AUDIO_DIR / "sfx").is_dir())
        for rel in REQUIRED:
            self.assertIn(rel, required_doc)
            stem = rel.rsplit(".", 1)[0]
            self.assertIn(stem, catalog)
            path = AUDIO_DIR / rel
            if rel in ("music/menu_theme.mp3", "music/studio_01_theme.mp3"):
                self.assertTrue(path.is_file(), str(path))
            else:
                self.assertFalse(path.is_file(), f"placeholder binary must not be committed: {rel}")

    def test_levels_use_gameplay_music_key(self):
        s1 = (JS / "levels" / "studio-01.js").read_text()
        s2 = (JS / "levels" / "studio-02.js").read_text()
        world = (JS / "levels" / "world.js").read_text()
        self.assertIn('music: "music_studio_01"', s1)
        self.assertIn('music: "music_gameplay"', s2)
        self.assertIn("musicForLevel(level.id, level.music)", world)


if __name__ == "__main__":
    unittest.main()
