"""Producer Hunt Phase 9 — Studio 01 scoring, combos, ranks, and results."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "producer_hunt" / "static" / "producer_hunt" / "js"


class ProducerHuntPhase9Tests(unittest.TestCase):
    def setUp(self):
        self.score = (JS / "score-manager.js").read_text()
        self.records = (JS / "score-records.js").read_text()
        self.results = (JS / "results.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.enemy = (JS / "enemy.js").read_text()
        self.boss = (JS / "boss.js").read_text()
        self.rescue = (JS / "rescues.js").read_text()
        self.brk = (JS / "destructibles.js").read_text()
        self.enc = (JS / "encounters.js").read_text()
        self.audio = (JS / "audio-catalog.js").read_text()
        self.hud = (JS / "hud.js").read_text()
        self.player = (JS / "player.js").read_text()
        self.waves = (JS / "waves.js").read_text()
        self.s2 = (JS / "levels" / "studio-02.js").read_text()

    def test_central_values_and_dedupe(self):
        self.assertIn("export class ScoreManager", self.score)
        for key, value in (
            ("post_producer: 100", "100"),
            ("colorist: 175", "175"),
            ("vfx_supervisor: 250", "250"),
            ("client: 300", "300"),
            ("boss_01: 10000", "10000"),
            ("equipment_crate: 25", "25"),
            ("production_monitor: 40", "40"),
            ("film_reel_container: 50", "50"),
            ("electrical_control_box: 75", "75"),
            ("compressed_air_canister: 100", "100"),
            ("camera_operator: 500", "500"),
            ("stunt_performer: 750", "750"),
            ("all_rescues: 2000", "2000"),
            ("studio_01_complete: STUDIO_CLEAR_BONUS", "5000"),
            ("multi_kill: 500", "500"),
            ("chain_reaction: 400", "400"),
            ("no_damage_encounter: 750", "750"),
            ("boss_perfect: 3000", "3000"),
            ("weapon_master: 1000", "1000"),
        ):
            self.assertIn(key, self.score, key)
        self.assertIn("STUDIO_CLEAR_BONUS = 5000", self.score)
        self.assertIn("STUDIO_CLEAR_BONUS = 5000", self.waves)
        self.assertIn("this.awarded.has(eventId)", self.score)
        self.assertIn("if (this.awarded.has(eventId)) return 0;", self.score)
        self.assertIn("this.bumpCombo();", self.score)
        self.assertIn("COMBO_WINDOW_SEC = 3.5", self.score)
        self.assertIn("if (n >= 15) return 2.5", self.score)
        self.assertIn("easy: 0.9", self.score)
        self.assertIn("hard: 1.2", self.score)

    def test_pipeline_is_authoritative(self):
        self.assertNotIn("game.score +=", self.enemy)
        self.assertNotIn("this.game.score += this.cfg.scoreValue", self.boss)
        self.assertIn("awardBoss", self.boss)
        self.assertIn("awardEnemyDefeat", self.game)
        self.assertIn("awardRescue", self.rescue)
        self.assertIn("awardDestructible", self.brk)
        self.assertIn("awardEncounter", self.enc)
        self.assertIn("noteAttackFired", self.player)
        self.assertIn("nextVolleyId", self.player)
        self.assertIn("return amt", self.enemy)
        self.assertNotIn("return this.isBoss ? 0 : this.spec.scoreValue", self.enemy)

    def test_results_rank_records_controls(self):
        self.assertIn("export class ResultsScreen", self.results)
        self.assertIn("STUDIO 01 COMPLETE", self.results)
        self.assertIn("NEW RECORD", self.results)
        self.assertIn("RANK BREAKDOWN", self.results)
        self.assertIn("CONTINUE — COMING SOON", self.game)
        self.assertIn("RETRY STUDIO 01", self.game)
        self.assertIn("openResults", self.game)
        self.assertIn("if (this._resultsOpened) return", self.game)
        self.assertIn("compareAndSaveRecords", self.records)
        self.assertIn("RECORDS_KEY", self.records)
        self.assertIn("playResultsMusic", self.game)
        self.assertIn("playMenuMusic", self.game)
        self.assertIn("combat: 0.35", self.score)
        self.assertIn('rank = "S"', self.score)
        self.assertIn("Boss not defeated", self.score)
        self.assertIn("drawScoringHud", self.game)
        self.assertIn("COMBO ${board.comboCount}", self.game)
        self.assertNotIn("ESSAM SALAMA", self.s2)

    def test_audio_cues_registered(self):
        for cue in (
            "score_tick",
            "combo_increase",
            "combo_break",
            "bonus_awarded",
            "new_record",
            "rank_reveal",
            "studio_complete",
        ):
            self.assertIn(cue, self.audio)
        self.assertIn("music_results", self.audio)


if __name__ == "__main__":
    unittest.main()
