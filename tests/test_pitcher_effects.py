"""投手の能力ごとの役割：球速・球威・変化球・奪三振・制球（架空の学校・選手）。"""
from __future__ import annotations

from dataclasses import replace
import unittest

from game_core.abilities import PitchAbility
from game_core.match_simulator import MatchSimulator
from test_stage13b3_team_strength import make_roster_abilities

BATTER_KEYS = ("contact", "power", "plate_discipline", "strikeout_resistance", "speed")


class PitcherEffectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        abilities = make_roster_abilities(school_id="FAKE-PITCH-ROLE")
        batter = next(a for a in abilities if a.primary_position not in ("P", "C"))
        pitcher = next(a for a in abilities if a.primary_position == "P")
        # 左右の差がない組み合わせ（両打ちは投手と逆に立つので差があるため右対左は避ける）
        cls.batter = replace(batter, **{k: 50 for k in BATTER_KEYS}, bats="R", platoon_trait=None)
        cls.pitches = (PitchAbility("four_seam", 50, 50, 50), PitchAbility("slider", 50, 50, 50))
        cls.pitcher = replace(
            pitcher, velocity_kmh=130, control=50, stuff=50, strikeout=50, groundball=50,
            pitch_repertoire=cls.pitches, throws="R", platoon_trait=None,
        )

    def weights(self, **changes):
        pitcher = replace(self.pitcher, **changes)
        weights = self.sim._event_weights(self.batter, pitcher, 50.0)
        total = sum(weights.values())
        return {key: value / total for key, value in weights.items()}

    def pitches_with(self, **changes):
        return tuple(replace(p, **changes) if p.pitch_type != "four_seam" else p for p in self.pitches)

    def test_velocity_adds_strikeouts_and_takes_away_singles(self):
        slow, fast = self.weights(velocity_kmh=130), self.weights(velocity_kmh=150)
        self.assertGreater(fast["strikeout"], slow["strikeout"] + 0.02)
        self.assertLess(fast["single"], slow["single"])
        self.assertAlmostEqual(fast["home_run"], slow["home_run"], delta=slow["home_run"] * 0.1)

    def test_stuff_weakens_contact_rather_than_adding_strikeouts(self):
        weak, strong = self.weights(stuff=30), self.weights(stuff=80)
        self.assertLess(strong["home_run"], weak["home_run"])
        self.assertLess(strong["double"], weak["double"])
        self.assertGreater(strong["field_out"], weak["field_out"])
        # 三振への効きは小さい（球速・変化球の質・奪三振の役割）
        self.assertLess(abs(strong["strikeout"] - weak["strikeout"]), 0.01)

    def test_pitch_quality_adds_swinging_strikeouts(self):
        weak = self.weights(pitch_repertoire=self.pitches_with(quality=30))
        strong = self.weights(pitch_repertoire=self.pitches_with(quality=80))
        self.assertGreater(strong["strikeout"], weak["strikeout"] + 0.02)

    def test_control_hurts_hits_only_below_the_pivot(self):
        pivot = self.sim.params["pitcher_effects"]["control_pivot"]
        at_pivot = self.weights(control=pivot)
        above = self.weights(control=pivot + 30)
        below = self.weights(control=pivot - 20)
        # 制球は四球をいつも減らすが、安打・長打を増やすのは基準より低いときだけ
        self.assertLess(above["walk"], at_pivot["walk"])
        self.assertGreater(below["walk"], at_pivot["walk"])
        hits = lambda w: w["single"] / w["field_out"]
        self.assertAlmostEqual(hits(above), hits(at_pivot), places=9)
        self.assertGreater(hits(below), hits(at_pivot))
        self.assertGreater(below["home_run"] / below["field_out"], at_pivot["home_run"] / at_pivot["field_out"])

    def test_breaking_ball_command_is_blended_by_usage(self):
        control = self.sim._effective_control
        fastball_only = replace(self.pitcher, control=60, pitch_repertoire=(PitchAbility("four_seam", 50, 20, 100),))
        self.assertEqual(60, control(fastball_only))
        light = replace(self.pitcher, control=60, pitch_repertoire=(
            PitchAbility("four_seam", 50, 50, 80), PitchAbility("curve", 50, 20, 20)))
        heavy = replace(self.pitcher, control=60, pitch_repertoire=(
            PitchAbility("four_seam", 50, 50, 30), PitchAbility("curve", 50, 20, 70)))
        self.assertLess(control(heavy), control(light))
        self.assertLess(control(light), 60)

    def test_strikeout_ability_still_drives_strikeouts(self):
        self.assertGreater(self.weights(strikeout=80)["strikeout"],
                           self.weights(strikeout=30)["strikeout"] + 0.1)


if __name__ == "__main__":
    unittest.main()
