"""凡退時の走者：ゴロ・フライ・併殺・進塁打・タッチアップ（架空の学校・選手）。"""
from __future__ import annotations

from dataclasses import replace
import random
import unittest

from game_core.highlights import game_highlights, validate_highlights
from game_core.match_contract import validate_match_simulation_result
from game_core.match_simulator import MatchSimulator
from test_pitcher_run_accounting import PitcherRunAccountingTests, _ScriptedSimulator
from test_stage13b3_team_strength import make_roster_abilities


class _FixedAdvance(MatchSimulator):
    """凡退の間の進塁を必ず起こす（advance=True）か起こさない。"""

    def __init__(self, advance: bool):
        super().__init__()
        self.advance = advance

    def _advance_out(self, key, runner, defense_strength, rng):
        return self.advance


class _ScriptedAdvance(_ScriptedSimulator):
    def _advance_out(self, key, runner, defense_strength, rng):
        return True


class ApplyOutEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        abilities = make_roster_abilities(school_id="FAKE-OUTS")
        cls.players = {a.player_id: a for a in abilities}
        cls.ids = [a.player_id for a in abilities]

    def apply(self, event, bases, outs, *, advance=True):
        sim = _FixedAdvance(advance)
        bases = list(bases)
        scored, outs_on_play, rbi = sim._apply_event(
            event_type=event, batter_id="BATTER", bases=bases,
            offense_players=self.players, defense_strength=50.0,
            rng=random.Random(1), outs=outs,
        )
        return bases, scored, outs_on_play, rbi

    def test_double_play_retires_batter_and_runner_on_first(self):
        a, b, c = self.ids[:3]
        self.assertEqual(([None, None, None], [], 2, 0), self.apply("double_play", [a, None, None], 0))
        # 0死なら三塁の走者は生還するが打点にしない。二塁の走者は三塁へ
        self.assertEqual(([None, None, b], [c], 2, 0), self.apply("double_play", [a, b, c], 0))
        # 1死からの併殺で3アウト：得点はない
        bases, scored, outs, _ = self.apply("double_play", [a, b, c], 1)
        self.assertEqual(([], 2), (scored, outs))
        with self.assertRaises(ValueError):
            self.apply("double_play", [None, b, None], 0)

    def test_ground_out_advances_runners_and_scores_with_rbi(self):
        a, b, c = self.ids[:3]
        self.assertEqual(([None, None, None], [c], 1, 1), self.apply("ground_out", [None, None, c], 0))
        self.assertEqual(([None, None, c], [], 1, 0),
                         self.apply("ground_out", [None, None, c], 0, advance=False))
        self.assertEqual(([None, None, b], [], 1, 0), self.apply("ground_out", [None, b, None], 1))
        # 押し出される走者は必ず進む（満塁なら三塁の走者が生還し打点）
        self.assertEqual(([None, a, b], [c], 1, 1),
                         self.apply("ground_out", [a, b, c], 0, advance=False))
        # 2死からのゴロは3アウト目：走者は動かず得点もない
        self.assertEqual(([a, b, c], [], 1, 0), self.apply("ground_out", [a, b, c], 2))

    def test_fly_out_tags_up_from_second_and_sacrifice_fly(self):
        _, b, c = self.ids[:3]
        self.assertEqual(([None, None, b], [], 1, 0), self.apply("fly_out", [None, b, None], 0))
        self.assertEqual(([None, b, None], [], 1, 0),
                         self.apply("fly_out", [None, b, None], 0, advance=False))
        self.assertEqual(([None, b, None], [], 1, 0), self.apply("fly_out", [None, b, None], 2))
        self.assertEqual(([None, None, b], [c], 1, 1), self.apply("sacrifice_fly", [None, b, c], 0))


class ClassifyOutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        abilities = make_roster_abilities(school_id="FAKE-CLASSIFY")
        cls.batter = next(a for a in abilities if a.primary_position != "P")
        cls.pitcher = next(a for a in abilities if a.primary_position == "P")

    def classify(self, bases, outs, *, batter=None, defense=50.0, seed=0, runs=400):
        rng = random.Random(seed)
        return [
            self.sim._classify_out("field_out", bases, outs, batter or self.batter, rng,
                                   self.pitcher, defense)
            for _ in range(runs)
        ]

    def test_double_play_and_sacrifice_fly_only_where_allowed(self):
        self.assertNotIn("double_play", self.classify([None, "R2", None], 0))
        self.assertNotIn("double_play", self.classify(["R1", None, None], 2))
        self.assertIn("double_play", self.classify(["R1", None, None], 1))
        self.assertNotIn("sacrifice_fly", self.classify([None, None, None], 0))
        self.assertNotIn("sacrifice_fly", self.classify([None, None, "R3"], 2))
        self.assertIn("sacrifice_fly", self.classify([None, None, "R3"], 1))
        self.assertEqual({"ground_out", "fly_out"}, set(self.classify([None, None, None], 0)))
        self.assertEqual("strikeout", self.sim._classify_out(
            "strikeout", ["R1", None, None], 0, self.batter, random.Random(0)))

    def test_abilities_move_the_split_points(self):
        slugger = replace(self.batter, power=90, contact=40)
        spray = replace(self.batter, power=30, contact=80)
        self.assertLess(self.sim._ground_share(slugger, self.pitcher),
                        self.sim._ground_share(spray, self.pitcher))
        sinker = replace(self.pitcher, groundball=90)
        self.assertGreater(self.sim._ground_share(self.batter, sinker),
                           self.sim._ground_share(self.batter, self.pitcher))
        # 俊足の打者ほど、守備の弱いチームほど併殺になりにくい
        self.assertLess(self.sim._double_play_probability(85, 50),
                        self.sim._double_play_probability(30, 50))
        self.assertLess(self.sim._double_play_probability(50, 40),
                        self.sim._double_play_probability(50, 70))


class OutRunAccountingTests(PitcherRunAccountingTests):
    """得点・自責点・打点・併殺打が実際のイベントと整合する（試合全体を通す）。"""

    def play_out(self, top):
        sim = _ScriptedAdvance({self.teams[1].school_id: top, self.teams[0].school_id: ()})
        result = sim.simulate(self.match())
        self.check_totals(result)
        validate_match_simulation_result(result, self.match())
        return result

    def test_ground_out_run_is_earned_and_an_rbi(self):
        result = self.play_out(["triple", "ground_out"])
        top = [e for e in result.events if e.inning == 1 and e.half == "top"]
        self.assertEqual((1, 1), (top[1].runs_scored, top[1].rbi))
        pitcher = [p for p in result.pitcher_stats if p.school_id == self.teams[1].school_id][0]
        self.assertEqual((1, 1), (pitcher.runs_allowed, pitcher.earned_runs))

    def test_double_play_run_is_not_an_rbi_and_is_counted(self):
        result = self.play_out(["triple", "walk", "double_play"])
        dp = [e for e in result.events if e.event_type == "double_play"][0]
        self.assertEqual((1, 0, 2), (dp.runs_scored, dp.rbi, dp.outs_on_play))
        batter = next(b for b in result.batter_stats if b.player_id == dp.batter_id)
        self.assertEqual(1, batter.grounded_into_double_plays)
        highlights = game_highlights(result.events)
        validate_highlights(highlights)
        self.assertIn(["D", 1, "t", dp.batter_id], highlights)

    def test_out_after_error_mirrors_only_clean_advances(self):
        # 失策で出た走者の得点は自責にならないが、安打の走者が内野ゴロの間に
        # 還った得点は、失策がなくても入っていたので自責点
        result = self.play_out(["reached_on_error", "triple", "ground_out"])
        pitcher = [p for p in result.pitcher_stats if p.school_id == self.teams[1].school_id][0]
        self.assertEqual((2, 1), (pitcher.runs_allowed, pitcher.earned_runs))


class DHStrictValidationTests(unittest.TestCase):
    """DHの試合は保存前に全イベントで得点・自責点を再生して照合する（validate_run_accounting）。"""

    @classmethod
    def setUpClass(cls):
        from test_live_match_state import DHSimulationTests

        DHSimulationTests.setUpClass()
        cls.fixture = DHSimulationTests()

    def test_out_events_replay_in_strict_validation(self):
        from game_core.match_simulator import validate_run_accounting

        _, result, _ = self.fixture.play(
            'normal', regulation_innings=2,
            top=('triple', 'walk', 'double_play', 'ground_out',
                 'walk', 'ground_out', 'triple', 'sacrifice_fly', 'fly_out'))
        validate_run_accounting(result)
        types = {e.event_type for e in result.events}
        self.assertTrue({'double_play', 'ground_out', 'fly_out'} <= types)


if __name__ == "__main__":
    unittest.main()
