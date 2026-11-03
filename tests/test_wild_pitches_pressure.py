"""度胸（G）と、暴投・捕逸・重盗・本盗・打席ごとの球数（H1）（架空の学校・選手）。"""
from __future__ import annotations

from dataclasses import replace
import random
import unittest

from game_core.highlights import game_highlights, validate_highlights
from game_core.match_contract import MatchSimulationInput
from game_core.match_simulator import MatchSimulator, validate_run_accounting
import test_pitcher_run_accounting as accounting
from test_stage13b3_team_strength import make_roster_abilities


class _Roll:
    """random() がいつも同じ値を返す乱数。"""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


class DecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        abilities = make_roster_abilities(school_id="FAKE-H1")
        cls.pitcher = next(a for a in abilities if a.primary_position == "P")
        cls.catcher = next(a for a in abilities if a.primary_position == "C")
        cls.runner = next(a for a in abilities if a.primary_position not in ("P", "C"))

    def test_pressure_is_scoring_position_or_late_close_game(self):
        under = self.sim._under_pressure
        self.assertFalse(under([None, None, None], 3, 0))
        self.assertFalse(under(["R1", None, None], 3, 0))
        self.assertTrue(under([None, "R2", None], 1, 5))
        self.assertTrue(under([None, None, "R3"], 1, -5))
        self.assertTrue(under([None, None, None], 7, 2))
        self.assertFalse(under([None, None, None], 7, 3))
        self.assertFalse(under([None, None, None], 6, 0))

    def test_low_composure_lowers_control_and_stuff_only_a_little(self):
        rule = self.sim.params["pressure"]
        calm = replace(self.pitcher, composure=int(rule["pivot"]))
        self.assertIs(calm, self.sim._pressured(calm))
        shaky = replace(self.pitcher, composure=20)
        pressed = self.sim._pressured(shaky)
        drop = rule["max_points"] * rule["control_per_point"]
        self.assertAlmostEqual(shaky.control - drop, pressed.control)
        self.assertAlmostEqual(shaky.stuff - rule["max_points"] * rule["stuff_per_point"], pressed.stuff)
        self.assertTrue(all(p.command < q.command for p, q in zip(pressed.pitch_repertoire, shaky.pitch_repertoire)))
        # 打席の結果では、落ちた投手のほうが打たれやすい
        weights = self.sim._event_weights
        hits = lambda w: sum(w[k] for k in ("single", "double", "triple", "home_run")) / sum(w.values())  # noqa: E731
        self.assertGreater(hits(weights(self.runner, pressed, 50.0)), hits(weights(self.runner, shaky, 50.0)))

    def test_wild_pitch_and_passed_ball_split_points(self):
        wild, passed = self.sim._wild_pitch_probabilities(self.pitcher, self.catcher)
        loose = replace(self.pitcher, control=25)
        self.assertGreater(self.sim._wild_pitch_probabilities(loose, self.catcher)[0], wild)
        clumsy = replace(self.catcher, catching=20)
        self.assertGreater(self.sim._wild_pitch_probabilities(self.pitcher, clumsy)[1], passed)
        choose = lambda roll, bases=("R1", None, None): self.sim._wild_pitch_or_passed_ball(  # noqa: E731
            bases=list(bases), pitcher=self.pitcher, catcher=self.catcher, rng=_Roll(roll))
        self.assertEqual("wp", choose(wild - 1e-9))
        self.assertEqual("pb", choose(wild + passed - 1e-9))
        self.assertIsNone(choose(wild + passed))
        self.assertIsNone(choose(0.0, (None, None, None)))

    def test_double_and_home_steal_decisions(self):
        players = {"R1": self.runner, "R2": self.runner, "R3": self.runner}
        steal = lambda bases, outs, roll, forced=False: self.sim._attempt_steal(  # noqa: E731
            bases=list(bases), outs=outs, margin=0, inning=3, offense_players=players,
            catcher=self.catcher, pitcher=self.pitcher, rng=_Roll(roll), forced=forced)
        self.assertEqual([("R2", 1, "sb"), ("R1", 0, "sb")], steal(("R1", "R2", None), 0, 0.0))
        # エンドランの空振り三振（必ず走る）で二塁走者が刺されると、一塁走者は二塁へ（盗塁は付かない）
        self.assertEqual([("R2", 1, "cs"), ("R1", 0, "adv")], steal(("R1", "R2", None), 0, 0.999, True))
        self.assertIsNone(steal(("R1", "R2", None), 0, 0.999))
        # 本盗：試みる確率は小さい（ふつうの乱数では試みない）
        self.assertEqual([("R3", 2, "sb")], steal((None, None, "R3"), 0, 0.0))
        self.assertIsNone(steal((None, None, "R3"), 0, 0.5))
        self.assertIsNone(steal((None, None, "R3"), 2, 0.0))
        attempt, success = self.sim._home_steal_probabilities(self.runner, self.catcher, self.pitcher)
        rule = self.sim.params["stolen_bases"]["home_steal"]
        self.assertLessEqual(attempt, rule["max_probability"])
        fast = replace(self.runner, stealing=90, speed=90)
        self.assertGreater(self.sim._home_steal_probabilities(fast, self.catcher, self.pitcher)[1], success)

    def test_double_steal_caught_for_the_third_out_leaves_the_trail_runner(self):
        players = {"R1": self.runner, "R2": self.runner}

        class Fail(_Roll):
            def __init__(self):
                self.values = [0.0, 0.999]   # 試みる、失敗する

            def random(self):
                return self.values.pop(0)

        self.assertEqual([("R2", 1, "cs")], self.sim._attempt_steal(
            bases=["R1", "R2", None], outs=2, margin=0, inning=3, offense_players=players,
            catcher=self.catcher, pitcher=self.pitcher, rng=Fail()))

    def test_more_strikeouts_and_walks_mean_more_pitches(self):
        rule = self.sim.params["pitch_count"]["tendency"]
        power = replace(self.pitcher, strikeout=85, control=35)
        finesse = replace(self.pitcher, strikeout=35, control=85)
        total = lambda p: sum(self.sim._pitches("field_out", random.Random(i), p, self.runner)  # noqa: E731
                              for i in range(400))
        self.assertGreater(total(power), total(finesse))
        self.assertLessEqual(total(power), 400 * (sum(self.sim.params["pitch_count"]["by_event"]["field_out"])
                                                  + rule["max_extra"]))


class PlayAccountingTests(unittest.TestCase):
    """暴投・捕逸・本盗・重盗の得点・自責点・成績・要点の整合（試合全体）。"""

    # 架空の2校と照合は自責点のテストのものを借りる（そのテスト自体は繰り返さない）
    @classmethod
    def setUpClass(cls):
        accounting.PitcherRunAccountingTests.setUpClass.__func__(cls)

    match = accounting.PitcherRunAccountingTests.match
    check_totals = accounting.PitcherRunAccountingTests.check_totals

    def play_with(self, top, advances=(), steals=None):
        class Scripted(accounting._ScriptedSimulator):
            advance_results = tuple(advances)

            def _attempt_steal(self, *, bases, outs, **kwargs):
                if steals is None or not steals or outs >= 3:
                    return None
                return steals.pop(0)(bases)

        sim = Scripted({self.teams[1].school_id: top, self.teams[0].school_id: ()})
        result = sim.simulate(self.match())
        self.check_totals(result)
        pitcher = [p for p in result.pitcher_stats if p.school_id == self.teams[1].school_id][0]
        return result, pitcher

    def test_wild_pitch_run_is_earned_and_passed_ball_run_is_not(self):
        for kind, earned in (("wp", 1), ("pb", 0)):
            with self.subTest(kind=kind):
                result, pitcher = self.play_with(["triple"], [kind])
                first = result.events[0]
                metadata = dict(first.metadata)
                self.assertEqual(1, first.runs_scored)
                charged_kind, charged = metadata["advance"].split("|")
                self.assertEqual(kind, charged_kind)
                if kind == "wp":
                    self.assertEqual(first.pitcher_id, charged)
                self.assertEqual((1, earned), (pitcher.runs_allowed, pitcher.earned_runs))
                self.assertEqual(int(kind == "wp"), pitcher.wild_pitches)
                catchers = [b for b in result.batter_stats if b.school_id == self.teams[1].school_id]
                self.assertEqual(int(kind == "pb"), sum(b.passed_balls for b in catchers))
                highlights = game_highlights(result.events)
                validate_highlights(highlights)
                # 三塁打の得点の要点はなく、暴投・捕逸の要点に1点
                self.assertEqual([["W", 1, "t", kind, metadata["advance"].split("|")[1], 1]],
                                 [h for h in highlights if h[0] in ("W", "S")])

    def test_passed_ball_run_becomes_earned_if_a_later_hit_would_score_it(self):
        _, pitcher = self.play_with(["double", "single"], ["pb"])
        # 捕逸で三塁へ進み、単打で生還。単打で二塁から生還できたとは限らないので自責点にしない
        self.assertEqual((1, 0), (pitcher.runs_allowed, pitcher.earned_runs))
        _, pitcher = self.play_with(["double", "home_run"], ["pb"])
        # 本塁打なら捕逸がなくても生還していた（自責点）
        self.assertEqual((2, 2), (pitcher.runs_allowed, pitcher.earned_runs))

    def test_home_steal_scores_an_earned_run(self):
        result, pitcher = self.play_with(["triple"], steals=[lambda bases: [(bases[2], 2, "sb")]])
        self.assertEqual((1, 1), (pitcher.runs_allowed, pitcher.earned_runs))
        runner = dict(result.events[0].metadata)["bases_after_play"].split("|")[2]
        rows = {b.player_id: b for b in result.batter_stats}
        self.assertEqual((1, 1), (rows[runner].stolen_bases, rows[runner].runs))
        self.assertIn(["B", 1, "t", runner, "sb", 4], game_highlights(result.events))

    def test_double_steal_records_each_runner(self):
        result, pitcher = self.play_with(
            ["walk", "walk", "single"],
            steals=[lambda b: None, lambda b: [(b[1], 1, "sb"), (b[0], 0, "sb")]])
        event = result.events[1]
        self.assertEqual(2, len(dict(event.metadata)["steal"].split(";")))
        offense = [b for b in result.batter_stats if b.school_id == self.teams[0].school_id]
        catchers = [b for b in result.batter_stats if b.school_id == self.teams[1].school_id]
        self.assertEqual(2, sum(b.stolen_bases for b in offense))
        self.assertEqual(2, sum(b.catcher_steal_attempts for b in catchers))
        self.assertEqual("|" + "|".join(dict(event.metadata)["bases_after_play"].split("|")[:2]),
                         dict(event.metadata)["bases_after"])
        self.assertEqual(pitcher.runs_allowed, result.team1_score)


class StrictReplayTests(unittest.TestCase):
    """DHの試合の照合（validate_run_accounting）で、暴投・捕逸・重盗・本盗を再生できる。"""

    @classmethod
    def setUpClass(cls):
        from test_live_match_state import DHSimulationTests

        DHSimulationTests.setUpClass()
        cls.fixture = DHSimulationTests()

    def test_replay_and_rejects_tampered_evidence(self):
        import test_live_match_state

        original = test_live_match_state._ScriptedSimulator
        # 単打・暴投、四球・捕逸、四球（満塁）、三塁打・本盗、単打、四球・重盗（二塁走者が刺される）
        plays = {"double": lambda b: [(b[1], 1, "cs"), (b[0], 0, "adv")], "home": lambda b: [(b[2], 2, "sb")]}

        class Scripted(original):
            advance_results = ("wp", "pb")

            def _attempt_steal(self, *, bases, outs, **kwargs):
                if outs >= 3:
                    return None
                if bases[0] and bases[1] and not bases[2] and "double" in plays:
                    return plays.pop("double")(bases)
                if bases[2] and not bases[1] and "home" in plays:
                    return plays.pop("home")(bases)
                return None

        test_live_match_state._ScriptedSimulator = Scripted
        try:
            _, result, _ = self.fixture.play(
                'normal', regulation_innings=2,
                top=('single', 'walk', 'walk', 'triple', 'single', 'walk', 'walk'))
        finally:
            test_live_match_state._ScriptedSimulator = original
        validate_run_accounting(result)
        metadata = [dict(e.metadata) for e in result.events]
        self.assertTrue(any("advance" in m for m in metadata))
        self.assertTrue(any(";" in m.get("steal", "") for m in metadata))
        # 記録の塁を書き換えると照合で止まる
        index = next(i for i, m in enumerate(metadata) if "advance" in m)
        event = result.events[index]
        broken = tuple((k, "||" if k == "bases_after_play" else v) for k, v in event.metadata)
        tampered = replace(result, events=(*result.events[:index], replace(event, metadata=broken),
                                           *result.events[index + 1:]))
        with self.assertRaises(ValueError):
            validate_run_accounting(tampered)


class WeightReuseTests(unittest.TestCase):
    def test_weight_reuse_gives_the_same_result_with_pressure(self):
        class Uncached(MatchSimulator):
            """使い回しをしない（MatchSimulator そのものだけが使い回す）。"""

        accounting.PitcherRunAccountingTests.setUpClass.__func__(type(self))
        sim = MatchSimulator()
        for number in range(3):
            match = MatchSimulationInput(f"H1-{number}", "FAKE-RUN-CUP", 2026, 20261102 + number,
                                         *self.teams, team_generation_seed=2026100701)
            self.assertEqual(sim.simulate(match), Uncached().simulate(match))


if __name__ == "__main__":
    unittest.main()
