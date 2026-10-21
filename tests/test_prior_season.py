"""前の年度の結果（PriorResults）をセーブに書いて戻す。"""
from __future__ import annotations

import json
import unittest

from phase2_engine.initial_state import PriorResults


class PriorResultsTests(unittest.TestCase):
    def test_round_trip_through_json(self):
        prior = PriorResults(
            year=2027,
            senbatsu_entrants=(("SCHX01", "90"), ("SCHX02", "91")),
            autumn_prefectural_rankings={"90": ("SCHX01", "SCHX03")},
            autumn_regional_entrants={"91": ("SCHX02",)},
        )
        restored = PriorResults.from_dict(
            json.loads(json.dumps(prior.to_dict()))
        )
        self.assertEqual(prior, restored)
        self.assertTrue(restored.from_game)
        self.assertEqual(["SCHX02"], restored.senbatsu_entrants_from("91"))

    def test_actual_results_are_not_game_results(self):
        self.assertFalse(
            PriorResults(year=2026, school_ids_by_rule={"R": ("A",)}).from_game
        )


if __name__ == "__main__":
    unittest.main()
