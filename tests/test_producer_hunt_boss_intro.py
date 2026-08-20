"""Studio 01 Boss 01 intro video wiring (Producer Hunt only)."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"
VIDEO = ROOT / "producer_hunt" / "static" / "producer_hunt" / "assets" / "videos" / "boss_01_intro.mp4"
HTML = ROOT / "producer_hunt" / "templates" / "producer_hunt" / "game.html"
CSS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "css" / "game.css"


class ProducerHuntBossIntroTests(unittest.TestCase):
    def test_converted_mp4_exists_and_is_h264(self):
        self.assertTrue(VIDEO.is_file(), str(VIDEO))
        self.assertGreater(VIDEO.stat().st_size, 100_000)
        data = VIDEO.read_bytes()
        self.assertIn(b"ftyp", data[:32])
        self.assertIn(b"avc1", data[:256] + data[256:4096])
        moov = data.find(b"moov")
        mdat = data.find(b"mdat")
        self.assertNotEqual(moov, -1)
        self.assertTrue(mdat == -1 or moov < mdat)

    def test_overlay_and_controller(self):
        html = HTML.read_text()
        css = CSS.read_text()
        cine = (JS / "cinematic.js").read_text()
        boss = (JS / "boss.js").read_text()
        game = (JS / "game.js").read_text()
        cfg = (JS / "config.js").read_text()
        self.assertIn("ph-boss-intro", html)
        self.assertIn("ph-boss-intro__video", html)
        self.assertIn("ph-boss-intro__skip", html)
        self.assertIn("playsinline", html)
        self.assertIn("object-fit: contain", css)
        self.assertIn("export class CinematicPlayer", cine)
        self.assertIn("playBossIntro", cine)
        self.assertIn("if (this._completed) return", cine)
        self.assertIn("reason === \"cancel\"", cine)
        self.assertIn("SKIP_GUARD_SEC = 0.5", cine)
        self.assertIn("DEBUG_REPLAY_BOSS_INTRO = false", cfg)
        self.assertIn("videos/boss_01_intro.mp4", cfg)
        self.assertIn('intro: "intro"', boss)
        self.assertIn("playerInArena", boss)
        self.assertIn("afterIntro", boss)
        self.assertIn("this.game.playBossMusic()", boss)
        self.assertIn("setGameplayMuted?.(false)", boss)
        self.assertIn("audio?.unlock?.()", cine)
        self.assertIn("skipIntro", boss)
        self.assertIn("bossIntroWatched", boss)
        self.assertIn("playBossIntro", game)
        self.assertIn("beginCinematic", game)
        self.assertIn("updateCinematicInput", game)
        self.assertIn("_cinematicActive", game)
        self.assertIn("cinematic?.cancel", game)
        self.assertNotIn("assistant_producer/", cine)


if __name__ == "__main__":
    unittest.main()
