"""とても強い投手の効きの頭打ち（match_simulation_v1 の pitcher_effects.index_soft_cap）。"""
from __future__ import annotations

from dataclasses import replace
import unittest

from game_core.match_simulator import MatchSimulator
from test_stage13b3_team_strength import make_roster_abilities


class PitcherIndexCapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        players = make_roster_abilities(school_id="FAKE-CAP", seed=5)
        cls.pitcher = next(p for p in players if p.primary_position == "P")

    def indexes(self, sim, **abilities):
        return sim._pitcher_indexes(replace(self.pitcher, **abilities))

    def test_only_the_part_above_the_knee_is_damped(self):
        capped = MatchSimulator()
        plain = MatchSimulator()
        plain.params["pitcher_effects"]["index_soft_cap"] = {}
        caps = capped.params["pitcher_effects"]["index_soft_cap"]
        self.assertTrue(caps)
        ordinary = dict(velocity_kmh=126, stuff=52, control=55, groundball=50)
        ace = dict(velocity_kmh=148, stuff=95, control=80, groundball=80)
        for outcome, cap in caps.items():
            knee, rate = float(cap["knee"]), float(cap["rate"])
            low = self.indexes(plain, **ordinary)[outcome]
            self.assertLess(low, knee)
            self.assertEqual(low, self.indexes(capped, **ordinary)[outcome])   # ふつうの投手は変わらない
            high = self.indexes(plain, **ace)[outcome]
            self.assertGreater(high, knee)
            self.assertAlmostEqual(knee + (high - knee) * rate, self.indexes(capped, **ace)[outcome])
        # 頭打ちのない結果（本塁打など）は変わらない
        for outcome in set(self.indexes(plain, **ace)) - set(caps):
            self.assertEqual(self.indexes(plain, **ace)[outcome], self.indexes(capped, **ace)[outcome])


if __name__ == "__main__":
    unittest.main()
