"""盗塁・牽制死・盗塁阻止（架空の学校・選手）。"""
from __future__ import annotations

from dataclasses import replace
import unittest

from game_core.highlights import game_highlights, validate_highlights
from game_core.match_simulator import MatchSimulator, validate_run_accounting
from test_pitcher_run_accounting import PitcherRunAccountingTests, _ScriptedSimulator
from test_stage13b3_team_strength import make_roster_abilities


def _with_steals(base, results):
    """盗塁を試みうる場面が来るたびに、results の結果を順に使う（なくなったら試みない）。"""

    class Forced(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.steal_results = list(results)

        def _attempt_steal(self, *, bases, outs, **kwargs):
            from_index = self._steal_base(bases)
            if from_index is None or outs >= 3 or not self.steal_results:
                return None
            return bases[from_index], from_index, self.steal_results.pop(0)

    return Forced


class StealDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        abilities = make_roster_abilities(school_id="FAKE-STEAL")
        cls.runner = next(a for a in abilities if a.primary_position not in ("P", "C"))
        cls.catcher = next(a for a in abilities if a.primary_position == "C")
        cls.pitcher = next(a for a in abilities if a.primary_position == "P")

    def test_only_second_and_third_base_steals(self):
        self.assertEqual(0, self.sim._steal_base(["R1", None, None]))
        self.assertEqual(0, self.sim._steal_base(["R1", None, "R3"]))
        self.assertEqual(1, self.sim._steal_base([None, "R2", None]))
        self.assertEqual(1, self.sim._steal_base(["R1", "R2", None]))
        self.assertIsNone(self.sim._steal_base([None, None, "R3"]))
        self.assertIsNone(self.sim._steal_base(["R1", "R2", "R3"]))
        self.assertIsNone(self.sim._steal_base([None, None, None]))

    def test_attempts_depend_on_runner_and_situation(self):
        fast = replace(self.runner, stealing=85, speed=85)
        slow = replace(self.runner, stealing=30, speed=30)
        attempt = self.sim._steal_attempt_probability
        self.assertGreater(attempt(fast, 0, outs=1, margin=0, inning=3),
                           attempt(slow, 0, outs=1, margin=0, inning=3) * 3)
        self.assertLess(attempt(fast, 1, outs=1, margin=0, inning=3),
                        attempt(fast, 0, outs=1, margin=0, inning=3))
        self.assertLess(attempt(fast, 0, outs=1, margin=8, inning=3),
                        attempt(fast, 0, outs=1, margin=0, inning=3))
        self.assertGreater(attempt(fast, 0, outs=1, margin=1, inning=8),
                           attempt(fast, 0, outs=1, margin=1, inning=3))
        self.assertLessEqual(attempt(replace(fast, stealing=100, speed=100), 0, outs=1, margin=0, inning=8),
                             self.sim.params["stolen_bases"]["attempt"]["max_probability"])

    def test_success_and_pickoff_split_points(self):
        success = self.sim._steal_success_probability
        fast = replace(self.runner, stealing=62, speed=60)
        slow = replace(self.runner, stealing=40, speed=40)
        strong = replace(self.catcher, arm_strength=85, throwing=80, catching=80)
        quick = replace(self.pitcher, quick=85)
        base = success(fast, self.catcher, self.pitcher, 0)
        self.assertGreater(base, success(slow, self.catcher, self.pitcher, 0))
        self.assertLess(success(fast, strong, self.pitcher, 0), base)
        self.assertLess(success(fast, self.catcher, quick, 0), base)
        # 本職でない捕手（捕球なし）でも決まる
        self.assertTrue(0 < success(fast, replace(self.runner, catching=None), self.pitcher, 0) < 1)
        pickoff = self.sim._pickoff_probability
        self.assertGreater(pickoff(self.runner, quick), pickoff(self.runner, self.pitcher))
        self.assertLess(pickoff(replace(self.runner, baserunning=90), self.pitcher),
                        pickoff(self.runner, self.pitcher))


class StealAccountingTests(PitcherRunAccountingTests):
    """盗塁・盗塁死・牽制死の成績、投手のアウト、得点・自責点の整合（試合全体）。"""

    def play_steals(self, top, results):
        sim = _with_steals(_ScriptedSimulator, results)(
            {self.teams[1].school_id: top, self.teams[0].school_id: ()})
        result = sim.simulate(self.match())
        self.check_totals(result)
        return result

    def team_rows(self, result, school_id):
        return [b for b in result.batter_stats if b.school_id == school_id]

    def test_steal_then_double_scores_an_earned_run(self):
        result = self.play_steals(["walk", "double"], ["sb"])
        offense, defense = self.teams[0].school_id, self.teams[1].school_id
        self.assertEqual(1, sum(b.stolen_bases for b in self.team_rows(result, offense)))
        self.assertEqual(1, sum(b.catcher_steal_attempts for b in self.team_rows(result, defense)))
        pitcher = [p for p in result.pitcher_stats if p.school_id == defense][0]
        self.assertEqual((1, 1), (pitcher.runs_allowed, pitcher.earned_runs))
        first = result.events[0]
        self.assertEqual(("sb", 0), (dict(first.metadata)["steal"].split("|")[2], first.outs_on_play))

    def test_caught_stealing_and_pickoff_are_outs_for_the_pitcher(self):
        result = self.play_steals(["walk", "walk", "home_run"], ["cs", "po"])
        offense, defense = self.teams[0].school_id, self.teams[1].school_id
        rows = self.team_rows(result, offense)
        self.assertEqual((1, 1), (sum(b.caught_stealing for b in rows), sum(b.picked_off for b in rows)))
        catcher = self.team_rows(result, defense)
        self.assertEqual((1, 1), (sum(b.catcher_steal_attempts for b in catcher),
                                  sum(b.catcher_caught_stealing for b in catcher)))
        top = [e for e in result.events if (e.inning, e.half) == (1, "top")]
        # 四球・盗塁死（1死）、四球・牽制死（2死）、本塁打（1点）、凡退（3死）
        self.assertEqual([1, 1, 0, 1], [e.outs_on_play for e in top])
        self.assertEqual(1, sum(e.runs_scored for e in top))
        pitcher = [p for p in result.pitcher_stats if p.school_id == defense][0]
        self.assertEqual((1, 1), (pitcher.runs_allowed, pitcher.earned_runs))
        highlights = game_highlights(result.events)
        validate_highlights(highlights)
        self.assertEqual(["cs", "po"], [h[4] for h in highlights if h[0] == "B"])

    def test_error_runner_steal_stays_unearned(self):
        result = self.play_steals(["reached_on_error", "double"], ["sb"])
        pitcher = [p for p in result.pitcher_stats if p.school_id == self.teams[1].school_id][0]
        self.assertEqual((1, 0), (pitcher.runs_allowed, pitcher.earned_runs))


class StealDHStrictValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_live_match_state import DHSimulationTests

        DHSimulationTests.setUpClass()
        cls.fixture = DHSimulationTests()

    def test_steals_replay_in_strict_validation(self):
        import test_live_match_state

        original = test_live_match_state._ScriptedSimulator
        test_live_match_state._ScriptedSimulator = _with_steals(original, ["sb", "sb", "cs", "po"])
        try:
            _, result, _ = self.fixture.play(
                'normal', regulation_innings=2,
                top=('walk', 'single', 'double', 'walk', 'walk', 'triple'))
        finally:
            test_live_match_state._ScriptedSimulator = original
        validate_run_accounting(result)
        steals = [dict(e.metadata)["steal"].split("|")[2] for e in result.events
                  if "steal" in dict(e.metadata)]
        self.assertEqual(["sb", "sb", "cs", "po"], steals)


if __name__ == "__main__":
    unittest.main()
