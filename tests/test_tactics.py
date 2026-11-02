"""作戦（段階F1）：送りバント・スクイズ・エンドランと監督の小技・機動力（架空の学校・選手）。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
import random
import unittest

from game_core.coaches import Coach, CoachBook, CoachTactics
from game_core.highlights import game_highlights, validate_highlights
from game_core.match_contract import validate_match_simulation_result
from game_core.match_simulator import MatchSimulator, validate_run_accounting
import test_live_match_state as live
import test_pitcher_run_accounting as accounting
from test_stage13b3_team_strength import make_roster_abilities

class AttemptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        abilities = make_roster_abilities(school_id="FAKE-TACTICS")
        cls.batter = next(a for a in abilities if a.primary_position not in ("P", "C"))
        cls.runner = replace(cls.batter, player_id="RUNNER", speed=60)

    def hitter(self, **changes):
        return replace(self.batter, **{"contact": 50, "power": 50, "bunt": 50,
                                       "strikeout_resistance": 50, **changes})

    def test_bunt_needs_a_runner_on_first_or_second_third_empty_and_less_than_two_outs(self):
        p = self.sim._bunt_attempt_probability
        b = self.hitter()
        self.assertGreater(p(b, ["R", None, None], 0, 0, 3), 0)
        self.assertGreater(p(b, [None, "R", None], 0, 0, 3), 0)
        self.assertEqual(0, p(b, ["R", None, "R3"], 0, 0, 3))
        self.assertEqual(0, p(b, ["R", None, None], 2, 0, 3))
        self.assertEqual(0, p(b, [None, None, None], 0, 0, 3))
        # 0死の方が1死より多い
        self.assertGreater(p(b, ["R", None, None], 0, 0, 3), p(b, ["R", None, None], 1, 0, 3))

    def test_bunt_depends_on_score_hitting_and_coach(self):
        p = self.sim._bunt_attempt_probability
        b, bases = self.hitter(), ["R", None, None]
        close = p(b, bases, 0, 0, 3)
        self.assertLess(p(b, bases, 0, -5, 3), close)       # 大きくリードされている
        self.assertLess(p(b, bases, 0, 5, 3), close)        # 大きくリードしている
        self.assertGreater(p(b, bases, 0, 0, 8), close)     # 終盤の接戦
        self.assertGreater(close, p(self.hitter(contact=80, power=80), bases, 0, 0, 3))
        self.assertGreater(p(b, bases, 0, 0, 3, 2.0), close)
        self.assertLess(p(b, bases, 0, 0, 3, 0.5), close)

    def test_squeeze_needs_runner_on_third_less_than_two_outs_and_a_close_score(self):
        p = self.sim._squeeze_attempt_probability
        b = self.hitter()
        self.assertGreater(p(b, [None, None, "R3"], 1, 0, 8), p(b, [None, None, "R3"], 1, 0, 3))
        self.assertEqual(0, p(b, [None, "R", None], 1, 0, 8))
        self.assertEqual(0, p(b, [None, None, "R3"], 2, 0, 8))
        self.assertEqual(0, p(b, [None, None, "R3"], 1, 6, 8))
        self.assertGreater(p(b, [None, None, "R3"], 1, 0, 8, 2.0), p(b, [None, None, "R3"], 1, 0, 8))

    def test_hit_and_run_needs_a_runner_on_first_and_prefers_contact_hitters(self):
        p = self.sim._hit_and_run_probability
        b = self.hitter()
        self.assertGreater(p(b, self.runner, ["R", None, None], 0, 0), 0)
        self.assertEqual(0, p(b, self.runner, ["R", "R2", "R3"], 0, 0))
        self.assertEqual(0, p(b, None, [None, "R2", None], 0, 0))
        self.assertEqual(0, p(b, self.runner, ["R", None, None], 2, 0))
        self.assertGreater(p(self.hitter(contact=80, strikeout_resistance=80), self.runner, ["R", None, None], 0, 0),
                           p(b, self.runner, ["R", None, None], 0, 0))
        self.assertGreater(p(b, self.runner, ["R", None, None], 0, 0, 2.0), p(b, self.runner, ["R", None, None], 0, 0))

    def test_low_bunt_ability_fails_more_and_without_a_runner_on_first_there_is_no_double_play(self):
        def outcomes(bunt, bases):
            rng = random.Random(4)
            players = {"R": self.runner, "R3": self.runner}
            return [self.sim._bunt_outcome("bunt", batter=self.hitter(bunt=bunt), bases=bases,
                                           offense_players=players, defense_strength=50.0, rng=rng)
                    for _ in range(3000)]
        good, poor = outcomes(80, ["R", None, None]), outcomes(20, ["R", None, None])
        self.assertGreater(good.count("ok"), poor.count("ok") + 300)
        self.assertEqual({"ok", "foul", "pop", "fc", "dp"}, set(poor))
        self.assertNotIn("dp", outcomes(20, [None, "R", None]))

    def test_squeeze_success_uses_bunt_ability_and_the_runners_speed(self):
        def rate(bunt, speed):
            rng = random.Random(9)
            players = {"R3": replace(self.runner, speed=speed)}
            results = [self.sim._bunt_outcome("squeeze", batter=self.hitter(bunt=bunt), bases=[None, None, "R3"],
                                              offense_players=players, defense_strength=50.0, rng=rng)
                       for _ in range(3000)]
            self.assertNotIn("foul", results)
            return results.count("ok") / len(results)
        self.assertGreater(rate(80, 50), rate(20, 50) + 0.2)
        self.assertGreater(rate(50, 90), rate(50, 20) + 0.1)


class ApplyBuntTests(unittest.TestCase):
    def apply(self, tactic, outcome, bases):
        bases = list(bases)
        return (*MatchSimulator._apply_bunt(tactic, outcome, "B", bases), bases)

    def test_sacrifice_and_failures_move_the_right_runners(self):
        self.assertEqual(("sacrifice_bunt", [], 1, 0, [None, "R1", "R2"]), self.apply("bunt", "ok", ["R1", "R2", None]))
        self.assertEqual(("bunt_pop_out", [], 1, 0, ["R1", None, None]), self.apply("bunt", "pop", ["R1", None, None]))
        # 先の走者がアウト（一塁だけなら二塁で、一・二塁なら三塁で）
        self.assertEqual(("fielder_choice", [], 1, 0, ["B", None, None]), self.apply("bunt", "fc", ["R1", None, None]))
        self.assertEqual(("fielder_choice", [], 1, 0, ["B", "R1", None]), self.apply("bunt", "fc", ["R1", "R2", None]))
        self.assertEqual(("fielder_choice", [], 1, 0, ["B", None, None]), self.apply("bunt", "fc", [None, "R2", None]))
        self.assertEqual(("bunt_double_play", [], 2, 0, [None, None, None]), self.apply("bunt", "dp", ["R1", None, None]))
        self.assertEqual(("bunt_double_play", [], 2, 0, [None, "R1", None]), self.apply("bunt", "dp", ["R1", "R2", None]))

    def test_squeeze_scores_with_an_rbi_or_retires_the_runner_from_third(self):
        self.assertEqual(("sacrifice_bunt", ["R3"], 1, 1, [None, "R1", None]), self.apply("squeeze", "ok", ["R1", None, "R3"]))
        self.assertEqual(("fielder_choice", [], 1, 0, ["B", "R1", None]), self.apply("squeeze", "fc", ["R1", None, "R3"]))
        self.assertEqual(("bunt_pop_out", [], 1, 0, [None, None, "R3"]), self.apply("squeeze", "pop", [None, None, "R3"]))
        self.assertEqual(("bunt_double_play", [], 2, 0, [None, "R2", None]), self.apply("squeeze", "dp", [None, "R2", "R3"]))


class _AlwaysTactic(MatchSimulator):
    """作戦を試みられる場面では必ず試み、成否は順番に回す（得点・自責点の整合を見る）。"""

    def __init__(self, outcomes=("ok", "foul", "pop", "fc", "dp")):
        super().__init__()
        self.outcomes = outcomes
        self.count = 0
        self.seen = set()

    def _choose_tactic(self, *, batter, bases, outs, margin, inning, offense_players, tactics, rng):
        if outs < 2 and bases[2] is not None:
            return "squeeze"
        if outs < 2 and bases[2] is None and (bases[0] or bases[1]):
            return "bunt" if self.count % 2 else "hit_and_run" if bases[0] else "bunt"
        return None

    def _bunt_outcome(self, tactic, *, bases, **kwargs):
        self.count += 1
        outcome = self.outcomes[self.count % len(self.outcomes)]
        if tactic == "squeeze" and outcome == "foul":
            outcome = "ok"
        if tactic == "bunt" and outcome == "dp" and bases[0] is None:
            outcome = "fc"
        self.seen.add((tactic, outcome))
        return outcome


class _Fixture(unittest.TestCase):
    """DHあり・なしの架空の2校（test_live_match_state と同じ作り方。そちらのテストは流さない）。"""

    @classmethod
    def setUpClass(cls):
        live.DHSimulationTests.setUpClass()
        cls.fixture = live.DHSimulationTests()

    def match(self, mode):
        return self.fixture.match(mode)


class FullGameTests(_Fixture):
    def test_every_tactic_keeps_scores_stats_and_earned_runs_consistent(self):
        seen = set()
        events = set()
        for mode in ("none", "normal", "pitcher"):
            for number in range(6):
                inp = replace(self.match(mode), match_id=f"FAKE-TACTIC-{mode}-{number}",
                              generation_seed=20261100 + number)
                sim = _AlwaysTactic()
                result = sim.simulate(inp)
                validate_match_simulation_result(result, inp)
                if mode != "none":
                    validate_run_accounting(result)
                seen |= sim.seen
                for event in result.events:
                    tactic = dict(event.metadata).get("tactic")
                    if tactic:
                        events.add((tactic.split(":")[0], event.event_type))
                validate_highlights(game_highlights(result.events))
                # 犠打（スクイズを含む）は犠打の欄に、バント・ライナーの併殺は併殺打に入らない
                for row in result.batter_stats:
                    mine = [e for e in result.events if e.batter_id == row.player_id
                            and e.offense_school_id == row.school_id]
                    self.assertEqual(sum(e.event_type == "sacrifice_bunt" for e in mine), row.sacrifice_bunts)
                    self.assertEqual(sum(e.event_type == "double_play" for e in mine),
                                     row.grounded_into_double_plays)
        self.assertTrue({("squeeze", "ok"), ("squeeze", "fc"), ("bunt", "foul"), ("bunt", "dp")} <= seen, seen)
        self.assertIn(("squeeze", "sacrifice_bunt"), events)
        self.assertIn(("bunt", "bunt_double_play"), events)
        self.assertTrue(any(kind == "hit_and_run" for kind, _ in events))

    def test_squeeze_run_is_earned_and_highlighted(self):
        class Squeeze(_AlwaysTactic):
            def _choose_tactic(self, *, bases, outs, **kwargs):
                return "squeeze" if bases[2] is not None and outs < 2 else None

        for number in range(40):
            inp = replace(self.match("normal"), match_id=f"FAKE-SQUEEZE-{number}", generation_seed=20261200 + number)
            result = Squeeze(outcomes=("ok",)).simulate(inp)
            squeezes = [e for e in result.events if dict(e.metadata).get("tactic") == "squeeze:ok"]
            if squeezes:
                break
        event = squeezes[0]
        self.assertEqual(("sacrifice_bunt", 1, 1), (event.event_type, event.runs_scored, event.rbi))
        validate_run_accounting(result)
        highlights = game_highlights(result.events)
        self.assertIn(["T", event.inning, "t" if event.half == "top" else "b", event.batter_id, "squeeze", "ok"],
                      highlights)


class WeightReuseTests(_Fixture):
    def test_cached_weights_match_uncached_games_with_tactics(self):
        class Uncached(MatchSimulator):
            pass

        busy = CoachTactics(small_ball=2.5, mobility=2.5)
        for mode in ("none", "normal"):
            with self.subTest(mode=mode):
                cached, reference = MatchSimulator(), Uncached()
                inp = self.match(mode)
                tactics = {inp.team1.school_id: busy, inp.team2.school_id: busy}
                first = cached.simulate(inp, tactics=tactics)
                self.assertEqual(first.to_dict(), reference.simulate(inp, tactics=tactics).to_dict())
                kinds = {dict(e.metadata).get("tactic", ":").split(":")[0] for e in first.events}
                self.assertTrue({"bunt", "hit_and_run"} & kinds, kinds)


class CoachStrategyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = CoachBook([], first_year=2026)

    def coach(self, small_ball, mobility):
        return Coach("COACH-X", "架空 監督", 1980, "FAKE-SCH", 2020, 50, 50, 50, 50,
                     small_ball=small_ball, mobility=mobility)

    def test_strategy_multipliers_are_neutral_at_fifty_and_capped(self):
        self.assertEqual((1.0, 1.0), self.book.strategy_multipliers(self.coach(50, 50)))
        high, low = self.book.strategy_multipliers(self.coach(80, 80)), self.book.strategy_multipliers(self.coach(20, 20))
        self.assertTrue(high[0] > 1.5 and high[1] > 1.5 and low[0] < 0.6 and low[1] < 0.6)
        cap = self.book.tactics_config["strategy"]["max_abs_log"]
        top = self.book.strategy_multipliers(self.coach(100, 100))
        self.assertTrue(all(value <= round(2.718281828 ** cap, 6) for value in top))
        with self.assertRaises(ValueError):
            self.book.strategy_multipliers(self.coach(0, 50))

    def test_strategy_applies_from_the_start_while_pitching_tendencies_wait(self):
        coach = replace(self.coach(80, 20), pitching_change=90)
        book = CoachBook([coach], first_year=2026)
        early = book.tactics_for("FAKE-SCH", date(2026, 7, 1))
        self.assertEqual((1.0, 0), (early.bf_multiplier, early.quick_hook_reduction))
        self.assertGreater(early.small_ball, 1.5)
        self.assertLess(early.mobility, 0.6)

    def test_steal_attempts_follow_the_coachs_mobility(self):
        sim = MatchSimulator()
        runner = make_roster_abilities(school_id="FAKE-RUN")[3]
        base = sim._steal_attempt_probability(runner, 0, outs=0, margin=0, inning=3)
        self.assertGreater(sim._steal_attempt_probability(runner, 0, outs=0, margin=0, inning=3, mobility=2.0), base)
        self.assertLess(sim._steal_attempt_probability(runner, 0, outs=0, margin=0, inning=3, mobility=0.5), base)


if __name__ == "__main__":
    unittest.main()


class HitAndRunStrikeoutTests(unittest.TestCase):
    """エンドランの空振り三振：走っている一塁走者が盗塁・盗塁死になる（塁・アウト・成績）。"""

    @classmethod
    def setUpClass(cls):
        accounting.PitcherRunAccountingTests.setUpClass()
        cls.fixture = accounting.PitcherRunAccountingTests()

    def play(self, script, success):
        class Scripted(accounting._ScriptedSimulator):
            def _choose_tactic(self, *, batter, bases, outs, margin, inning, offense_players, tactics, rng):
                runner = offense_players.get(bases[0]) if bases[0] else None
                ok = self._hit_and_run_probability(batter, runner, bases, outs, margin) > 0
                return "hit_and_run" if ok else None

            def _steal_attempt_probability(self, *args, **kwargs):
                return 0.0  # ふつうの盗塁はさせない

            def _steal_success_probability(self, *args, **kwargs):
                return 1.0 if success else 0.0

        fx = self.fixture
        # 確かめる打席のあとに本塁打を足して試合を決める
        sim = Scripted({fx.teams[1].school_id: (*script, "home_run"), fx.teams[0].school_id: ()})
        result = sim.simulate(fx.match())
        fx.check_totals(result)
        event = result.events[len(script) - 1]
        metadata = dict(event.metadata)
        rows = {(b.school_id, b.player_id): b for b in result.batter_stats}
        return event, metadata, rows

    def runner_row(self, rows, event, metadata):
        runner = metadata["steal"].split("|")[0]
        return runner, rows[(event.offense_school_id, runner)]

    def test_runner_on_first_steals_or_is_caught_with_zero_or_one_out(self):
        for prefix, outs_before in (((), 0), (("strikeout",), 1)):
            for success in (True, False):
                with self.subTest(outs=outs_before, success=success):
                    script = (*prefix, "single", "strikeout")
                    event, metadata, rows = self.play(script, success)
                    self.assertEqual(("strikeout", "hit_and_run:strikeout"), (event.event_type, metadata["tactic"]))
                    first = metadata["bases_before"].split("|")[0]
                    runner, row = self.runner_row(rows, event, metadata)
                    self.assertEqual(first, runner)
                    self.assertEqual("|1|", f"|{metadata['steal'].split('|')[1]}|")
                    if success:
                        self.assertEqual(f"|{runner}|", metadata["bases_after"])
                        self.assertEqual((1, 0), (row.stolen_bases, row.caught_stealing))
                        self.assertEqual(str(outs_before + 1), metadata["outs_after"])
                    else:
                        self.assertEqual("||", metadata["bases_after"])
                        self.assertEqual((0, 1), (row.stolen_bases, row.caught_stealing))
                        self.assertEqual(str(outs_before + 2), metadata["outs_after"])
                        self.assertEqual(2, event.outs_on_play)

    def test_first_and_third_only_the_runner_on_first_runs(self):
        for success in (True, False):
            with self.subTest(success=success):
                event, metadata, rows = self.play(("triple", "walk", "strikeout"), success)
                third = metadata["bases_before"].split("|")[2]
                runner, row = self.runner_row(rows, event, metadata)
                self.assertEqual(metadata["bases_before"].split("|")[0], runner)
                expected = f"|{runner}|{third}" if success else f"||{third}"
                self.assertEqual(expected, metadata["bases_after"])

    def test_no_hit_and_run_with_runners_on_first_and_second(self):
        # 一・二塁では両方の走者が走る（重盗）。扱っていないのでエンドランにしない
        sim = MatchSimulator()
        batter = make_roster_abilities(school_id="FAKE-HR")[3]
        self.assertEqual(0, sim._hit_and_run_probability(batter, batter, ["R1", "R2", None], 0, 0))
        event, metadata, rows = self.play(("walk", "walk", "strikeout"), True)
        self.assertNotIn("tactic", metadata)
        self.assertNotIn("steal", metadata)
        self.assertEqual(metadata["bases_before"], metadata["bases_after"])
        self.assertEqual("1", metadata["outs_after"])
