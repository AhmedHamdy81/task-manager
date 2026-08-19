"""Producer Hunt Phase 2 — studio_02 Client Review level data."""

from __future__ import annotations

import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "producer_hunt" / "static" / "producer_hunt" / "js"


class ProducerHuntStudio02Tests(unittest.TestCase):
    def setUp(self):
        self.s2 = (JS / "levels" / "studio-02.js").read_text()
        self.index = (JS / "levels" / "level-01.js").read_text()
        self.game = (JS / "game.js").read_text()
        self.world = (JS / "levels" / "world.js").read_text()
        self.settings = (JS / "settings.js").read_text()

    def test_identity_and_registry(self):
        self.assertIn('id: "studio_02"', self.s2)
        self.assertIn('name: "Client Review"', self.s2)
        self.assertIn("studio_02: STUDIO_02", self.index)
        self.assertIn("LEVEL_ORDER", self.index)
        self.assertIn("nextLevelId", self.index)
        self.assertIn("levelDataLoads", self.index)

    def test_encounters_and_composition(self):
        self.assertIn('id: "enc_intro_client"', self.s2)
        self.assertIn('enemyIds: ["cl_intro"]', self.s2)
        self.assertIn('id: "enc_mixed_early"', self.s2)
        self.assertIn('enemyIds: ["pp_early", "cl_early"]', self.s2)
        self.assertIn('id: "enc_final"', self.s2)
        self.assertIn('enemyIds: ["pp_final_a", "pp_final_b", "cl_final"]', self.s2)
        self.assertEqual(self.s2.count('type: "client"'), 3)
        self.assertEqual(self.s2.count('type: "post_producer"'), 3)
        self.assertNotIn("assistant_producer", self.s2)
        self.assertLessEqual(len(["pp_final_a", "pp_final_b", "cl_final"]), 3)

    def test_checkpoint_objectives_doors(self):
        self.assertIn("studio_02_start", self.s2)
        self.assertIn("studio_02_mid", self.s2)
        self.assertIn("studio_02_review", self.s2)
        self.assertIn("studio_02_exit", self.s2)
        self.assertIn("studio_02_key", self.s2)
        self.assertIn('requireEncounters: ["enc_final"]', self.s2)
        self.assertIn('encounterId: "enc_intro_client"', self.s2)
        self.assertIn('checkpointId: "studio_02_mid"', self.s2)
        self.assertIn('doorId: "studio_02_review"', self.s2)

    def test_pickups_and_hazards(self):
        for pid in (
            "studio_02_health_mixed",
            "studio_02_energy_corridor",
            "studio_02_token_bay",
            "studio_02_token_opt_a",
            "studio_02_token_opt_b",
            "studio_02_key",
            "studio_02_health_final",
            "studio_02_energy_final",
        ):
            self.assertIn(pid, self.s2)
        self.assertIn("studio_02_cable_intro", self.s2)
        self.assertIn("live_cable", self.s2)
        self.assertIn("hot_light", self.s2)

    def test_transition_and_persistence(self):
        self.assertIn("advanceToNextLevel", self.game)
        self.assertIn("nextPlayableLevel", self.game)
        self.assertIn("applyEncounterSnapshot", self.game)
        self.assertIn("phase2Complete", self.game)
        self.assertIn("phase2Complete", self.settings)
        self.assertIn("PHASE 2 COMPLETE", self.game)
        self.assertIn("this.projectiles = []", self.game)

    def test_validation_covers_bounds_and_types(self):
        self.assertIn("outside level bounds", self.world)
        self.assertIn('ALLOWED_ENEMIES = new Set(["post_producer", "client"])', self.world)
        self.assertIn("references missing encounter", self.world)


if __name__ == "__main__":
    unittest.main()
