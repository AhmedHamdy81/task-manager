"""Studio 01 Boss 01 defeat video wiring (Producer Hunt only)."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"
VIDEO = ROOT / "producer_hunt" / "static" / "producer_hunt" / "assets" / "videos" / "boss_01_defeat.mp4"
HTML = ROOT / "producer_hunt" / "templates" / "producer_hunt" / "game.html"
CSS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "css" / "game.css"
INIT = ROOT / "producer_hunt" / "__init__.py"


class ProducerHuntBossDefeatTests(unittest.TestCase):
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
        init = INIT.read_text()
        self.assertIn("ph-boss-intro", html)
        self.assertIn(">SKIP</button>", html)
        self.assertIn("object-fit: contain", css)
        self.assertIn("playCinematic", cine)
        self.assertIn("playBossIntro", cine)
        self.assertIn("playBossDefeat", cine)
        self.assertIn("BOSS_DEFEAT_SRC", cine)
        self.assertIn("defeatSrc", cine)
        self.assertIn("timeoutSec: 20", cine)
        self.assertIn("if (this._completed) return", cine)
        self.assertIn("reason === \"cancel\"", cine)
        self.assertIn("SKIP_GUARD_SEC = 0.5", cine)
        self.assertIn("BOSS_DEFEAT_SRC", cfg)
        self.assertIn("videos/boss_01_defeat.mp4", cfg)
        self.assertIn("ph-20260821-defeat", cfg)
        self.assertIn("ph-20260821-defeat", init)
        self.assertIn("defeatSequenceStarted", boss)
        self.assertIn("startDefeatSequence", boss)
        self.assertIn("afterDefeatCinematic", boss)
        self.assertIn("playBossDefeat", boss)
        self.assertIn("BOSS_STATES.complete", boss)
        self.assertIn('defeat_cinematic: "defeat_cinematic"', boss)
        self.assertNotIn("_finishDeath", boss)
        self.assertIn("playBossDefeat", game)
        self.assertIn("awardStudioClear", game)
        self.assertIn("sfx(\"level_complete\"", game)
        self.assertIn("dying", game)
        self.assertIn("defeat_cinematic", game)
        self.assertNotIn("assistant_producer/", cine)
        self.assertNotIn("beginDeath(); this.game.playBossDefeat", boss)

    def test_original_source_kept(self):
        src = VIDEO.with_name("boss_01_defeat.mp4.mp4")
        self.assertTrue(src.is_file(), str(src))
