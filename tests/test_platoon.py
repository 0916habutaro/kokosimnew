"""左右の差・両打ち・個人の得意不得意・投打の左右の作り方（架空の学校・選手）。"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import random
import unittest

from game_core.match_simulator import MatchSimulator
from game_core.players import draw_hands
from game_core.school_edits import AbilityEditor
from test_stage13b3_team_strength import make_roster_abilities


class PlatoonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        abilities = make_roster_abilities(school_id="FAKE-PLATOON")
        batter = next(a for a in abilities if a.primary_position not in ("P", "C"))
        pitcher = next(a for a in abilities if a.primary_position == "P")
        cls.batter = replace(batter, platoon_trait=None)
        cls.pitcher = replace(pitcher, platoon_trait=None)
        cls.rule = cls.sim.params["platoon"]

    def hitter(self, bats, trait=None):
        return replace(self.batter, bats=bats, platoon_trait=trait)

    def arm(self, throws, trait=None):
        return replace(self.pitcher, throws=throws, platoon_trait=trait)

    def test_same_side_hurts_and_left_on_left_hurts_more(self):
        points = self.sim._platoon_points
        same = self.rule["same_side_points"]
        self.assertEqual(-same["R"], points(self.hitter("R"), self.arm("R")))
        self.assertEqual(-same["L"], points(self.hitter("L"), self.arm("L")))
        self.assertLess(points(self.hitter("L"), self.arm("L")), points(self.hitter("R"), self.arm("R")))
        self.assertEqual(self.rule["opposite_side_points"], points(self.hitter("L"), self.arm("R")))
        self.assertEqual(self.rule["opposite_side_points"], points(self.hitter("R"), self.arm("L")))

    def test_switch_hitter_always_takes_the_opposite_side(self):
        switch = self.hitter("S")
        self.assertEqual("L", self.sim.batting_side(switch, self.arm("R")))
        self.assertEqual("R", self.sim.batting_side(switch, self.arm("L")))
        for throws in ("R", "L"):
            self.assertEqual(self.rule["opposite_side_points"],
                             self.sim._platoon_points(switch, self.arm(throws)))

    def test_individual_traits_only_apply_to_their_matchup(self):
        points = self.sim._platoon_points
        trait = self.rule["trait_points"]
        base = points(self.hitter("R"), self.arm("L"))
        self.assertEqual(base + trait, points(self.hitter("R", "vs_left_good"), self.arm("L")))
        self.assertEqual(base - trait, points(self.hitter("R", "vs_left_bad"), self.arm("L")))
        # 対左投手の特性は右投手には効かない
        self.assertEqual(points(self.hitter("R"), self.arm("R")),
                         points(self.hitter("R", "vs_left_bad"), self.arm("R")))
        # 投手の対左打者◎は左の打席の打者（左投手に対する両打ちは右の打席）だけを抑える
        good = self.arm("R", "vs_left_good")
        self.assertEqual(points(self.hitter("L"), self.arm("R")) - trait, points(self.hitter("L"), good))
        self.assertEqual(points(self.hitter("R"), self.arm("R")), points(self.hitter("R"), good))
        self.assertEqual(points(self.hitter("S"), self.arm("L")),
                         points(self.hitter("S"), self.arm("L", "vs_left_good")))

    def test_points_move_the_event_weights(self):
        weights = self.sim._event_weights
        favourable = weights(self.hitter("L"), self.arm("R"), 50.0)
        unfavourable = weights(self.hitter("L"), self.arm("L"), 50.0)
        self.assertGreater(favourable["single"], unfavourable["single"])
        self.assertLess(favourable["strikeout"], unfavourable["strikeout"])

    def test_trait_can_be_edited_and_validated(self):
        editor = AbilityEditor()
        edited = editor.player(self.batter, {"platoon_trait": "vs_left_good"}, [])
        self.assertEqual("vs_left_good", edited.platoon_trait)
        self.assertIsNone(editor.player(edited, {"platoon_trait": None}, []).platoon_trait)
        with self.assertRaises(ValueError):
            editor.player(self.batter, {"platoon_trait": "vs_right_good"}, [])


class HandednessGenerationTests(unittest.TestCase):
    def test_left_throwers_only_at_first_base_outfield_and_pitcher(self):
        rng = random.Random(3)
        for position in ("C", "2B", "3B", "SS"):
            self.assertTrue(all(draw_hands(position, rng)[0] == "R" for _ in range(300)))
        for position in ("P", "1B", "LF", "CF", "RF"):
            self.assertIn("L", {draw_hands(position, rng)[0] for _ in range(300)})

    def test_left_throwers_mostly_bat_left_and_overall_shares_are_kept(self):
        rng = random.Random(5)
        left_throw = Counter()
        while sum(left_throw.values()) < 2000:
            throws, bats = draw_hands("LF", rng)
            if throws == "L":
                left_throw[bats] += 1
        self.assertGreater(left_throw["L"] / 2000, 0.75)
        # 1校の守備位置の並び（投手5・捕手2・一塁1・二遊三各2・外野各2）で、左打ちは約25%・両打ちは約4%
        slots = ["P"] * 5 + ["C"] * 2 + ["1B"] + ["2B", "3B", "SS", "LF", "CF", "RF"] * 2
        bats = Counter(draw_hands(position, rng)[1] for _ in range(1500) for position in slots)
        total = sum(bats.values())
        self.assertTrue(0.22 < bats["L"] / total < 0.28, bats)
        self.assertTrue(0.025 < bats["S"] / total < 0.055, bats)


if __name__ == "__main__":
    unittest.main()
