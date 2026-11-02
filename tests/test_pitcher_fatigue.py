"""投手の疲れ：試合の中・連投・交代・先発の休養・怪我・打席の結果の使い回し（架空の学校・選手）。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
import unittest

from game_core import fatigue
from game_core.coaches import CoachTactics
from game_core.injuries import injury_model
from game_core.match_contract import MatchSimulationInput, TeamMatchInput
from game_core.match_simulator import MatchSimulator
from game_core.team_strength import TeamStrengthGenerator
from test_stage13b3_team_strength import make_roster_abilities


class FatigueFormulaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule = MatchSimulator().params["fatigue"]

    def test_carry_grows_with_recent_pitches_and_fades_with_rest(self):
        carry = lambda history, stamina=50: fatigue.carry_fatigue(history, stamina, self.rule)  # noqa: E731
        self.assertEqual(0.0, carry({}))
        self.assertEqual(0.0, carry({0: 150}))  # 今日の分は含めない
        free = self.rule["carry"]["free_pitches"]
        self.assertEqual(0.0, carry({1: free}))
        self.assertGreater(carry({1: 140}), carry({1: 80}))
        self.assertGreater(carry({1: 120}), carry({3: 120}))
        self.assertGreater(carry({1: 120, 2: 120}), carry({1: 120}))
        # スタミナが高いほど回復が速い
        self.assertLess(carry({2: 130}, stamina=80), carry({2: 130}, stamina=30))

    def test_in_game_fatigue_starts_after_the_stamina_threshold(self):
        base = self.rule["in_game"]["base_pitches"]
        self.assertEqual(0.0, fatigue.in_game_fatigue(base, 50, self.rule))
        self.assertGreater(fatigue.in_game_fatigue(base + 30, 50, self.rule), 0.0)
        self.assertLess(fatigue.in_game_fatigue(base + 30, 80, self.rule),
                        fatigue.in_game_fatigue(base + 30, 30, self.rule))

    def test_stage_lowers_velocity_stuff_control_and_pitches(self):
        abilities = make_roster_abilities(school_id="FAKE-FATIGUE")
        pitcher = next(a for a in abilities if a.primary_position == "P")
        self.assertIs(pitcher, fatigue.tired(pitcher, 0, self.rule))
        worn = fatigue.tired(pitcher, 4, self.rule)
        self.assertLess(worn.velocity_kmh, pitcher.velocity_kmh)
        self.assertLess(worn.stuff, pitcher.stuff)
        self.assertLess(worn.control, pitcher.control)
        self.assertTrue(all(w.quality < p.quality for w, p in zip(worn.pitch_repertoire, pitcher.pitch_repertoire)))
        self.assertEqual(pitcher.strikeout, worn.strikeout)
        points = self.rule["stage_points"]
        self.assertEqual(0, fatigue.stage_of(points * 0.99, self.rule))
        self.assertEqual(2, fatigue.stage_of(points * 2.5, self.rule))
        self.assertEqual("", fatigue.label_of(0, self.rule))
        self.assertTrue(fatigue.label_of(self.rule["max_stage"], self.rule))

    def test_history_from_log_counts_days_before_today(self):
        log = {"2026-07-20": 120, "2026-07-21": 40, "2026-07-22": 90}
        self.assertEqual({2: 120, 1: 40}, fatigue.history_from_log(log, date(2026, 7, 22)))


class FatigueDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        gen = TeamStrengthGenerator()
        cls.teams = []
        for sid in ("FAKE-FAT-A", "FAKE-FAT-B"):
            abilities = tuple(replace(a, player_id=sid + "-" + a.player_id)
                              for a in make_roster_abilities(school_id=sid))
            cls.teams.append(TeamMatchInput(sid, gen.generate(abilities), abilities))
        cls.staff = cls.sim._pitcher_order(cls.teams[0])

    def test_tired_ace_rests_when_a_fresher_pitcher_exists(self):
        rest = self.sim.params["fatigue"]["rest_starter_points"]
        ace, second = self.staff[0], self.staff[1]
        order, size = self.sim._game_staff(self.teams[0], None, {ace: rest + 1})
        self.assertEqual(second, order[0])
        # 先発を外したエースは救援の順番の最後（基本は休養）
        self.assertEqual(ace, order[size - 1])
        # 全員が疲れていればエースのまま。疲れが小さければ休ませない
        everyone = {pid: rest + 1 for pid in self.staff}
        self.assertEqual(ace, self.sim._game_staff(self.teams[0], None, everyone)[0][0])
        self.assertEqual(ace, self.sim._game_staff(self.teams[0], None, {ace: rest - 0.5})[0][0])

    def test_fatigue_triggers_the_change_and_tactics_still_apply(self):
        pitcher = self.teams[0].player_abilities[0]
        stats = {"batters_faced": 10, "runs_allowed": 0}
        limit = self.sim.params["fatigue"]["change"]["starter_points"]
        change = lambda **kw: self.sim._should_change_pitcher(  # noqa: E731
            pitcher=pitcher, stats=stats, starter=True, has_next=True, **kw)
        self.assertFalse(change(fatigue=limit - 1))
        self.assertTrue(change(fatigue=limit))
        early = CoachTactics(bf_multiplier=0.8)
        self.assertTrue(change(fatigue=limit * 0.85, tactics=early))
        self.assertFalse(self.sim._should_change_pitcher(
            pitcher=pitcher, stats=stats, starter=True, has_next=False, fatigue=limit * 3))

    def test_weight_reuse_gives_the_same_result_with_fatigue(self):
        class Uncached(MatchSimulator):
            """使い回しをしない（MatchSimulator そのものだけが使い回す）。"""

        heavy = {pid: {1: 140, 2: 130} for pid in self.staff}
        match = MatchSimulationInput("FAT-1", "FAKE-FAT-CUP", 2026, 20261101,
                                     *self.teams, team_generation_seed=2026100701)
        cached = self.sim.simulate(match, pitch_history=heavy)
        uncached = Uncached().simulate(match, pitch_history=heavy)
        self.assertEqual(cached, uncached)
        self.assertTrue(any(p.exit_fatigue > 0 for p in cached.pitcher_stats))
        # 疲れがあると結果が変わる（疲れの段階が打席の結果に効いている）
        self.assertNotEqual(cached, self.sim.simulate(match))


class RestedAceTests(unittest.TestCase):
    """疲れで先発を外したエースの休養と救援（状況・能力・疲れ・監督の傾向で決まる）。"""

    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        abilities = make_roster_abilities(school_id="FAKE-REST")
        pitchers = [a for a in abilities if a.primary_position == "P"]
        cls.ace = replace(pitchers[0], stuff=80, control=75, strikeout=78)
        cls.weak = replace(pitchers[1], stuff=45, control=45, strikeout=45)
        cls.strong = replace(pitchers[1], stuff=85, control=80, strikeout=82)

    def calls(self, *, inning=8, lead=1, carry=2.0, candidate=None, tactics=CoachTactics(), runs=300):
        import random

        candidate = self.weak if candidate is None else candidate
        return sum(self.sim._call_rested_ace(
            ace=self.ace, ace_carry=carry, candidate=candidate, candidate_stage=0,
            ace_stage=fatigue.stage_of(carry, self.sim.params["fatigue"]), inning=inning, lead=lead,
            tactics=tactics, rng=random.Random(seed)) for seed in range(runs))

    def test_close_late_games_sometimes_call_the_ace_but_not_always(self):
        called = self.calls()
        self.assertGreater(called, 0)
        self.assertLess(called, 300)

    def test_ace_keeps_resting_early_in_blowouts_too_tired_or_with_a_good_reliever(self):
        rule = self.sim.params["fatigue"]["rested_ace_relief"]
        self.assertEqual(0, self.calls(inning=rule["late_inning_from"] - 1))
        self.assertEqual(0, self.calls(lead=rule["close_margin"] + 3))
        self.assertEqual(0, self.calls(lead=-(rule["close_margin"] + 3)))
        self.assertEqual(0, self.calls(carry=rule["max_carry_points"] + 1))
        self.assertEqual(0, self.calls(candidate=self.strong))

    def test_bullpen_minded_coaches_call_the_ace_more_often(self):
        self.assertGreater(self.calls(tactics=CoachTactics(bf_multiplier=0.8)),
                           self.calls(tactics=CoachTactics(bf_multiplier=1.2)))


class RestedAceGameTests(FatigueDecisionTests):
    """試合を通して：前日に多く投げたエースは先発せず、試合によって休むか救援に出る。"""

    def matches(self, count):
        for number in range(count):
            yield MatchSimulationInput(f"REST-{number}", "FAKE-FAT-CUP", 2026, 20261101 + number,
                                       *self.teams, team_generation_seed=2026100701)

    def test_tired_ace_skips_the_start_and_either_rests_or_relieves(self):
        ace = self.staff[0]
        # 前日にエースだけが多く投げた（球数制限の記録の形から）
        history = fatigue.history_from_log({"2026-07-20": 135}, date(2026, 7, 21))
        rested = relieved = 0
        for match in self.matches(40):
            result = self.sim.simulate(match, pitch_history={ace: history})
            record = next(r for r in result.team_participation if r.school_id == self.teams[0].school_id)
            self.assertNotEqual(ace, record.starting_pitcher_id)
            pitched = any(p.player_id == ace and p.batters_faced > 0 for p in result.pitcher_stats)
            relieved += pitched
            rested += not pitched
        self.assertGreater(rested, 0)
        self.assertGreater(relieved, 0)

    def test_pitch_limit_still_keeps_the_ace_out(self):
        ace = self.staff[0]
        history = {ace: {1: 135}}
        for match in self.matches(15):
            result = self.sim.simulate(match, pitch_history=history,
                                       pitch_allowances={ace: 0})
            self.assertFalse(any(p.player_id == ace and p.batters_faced > 0 for p in result.pitcher_stats))

    def test_weight_reuse_matches_with_a_rested_ace(self):
        class Uncached(MatchSimulator):
            pass

        history = {self.staff[0]: {1: 140}}
        for match in self.matches(3):
            self.assertEqual(self.sim.simulate(match, pitch_history=history),
                             Uncached().simulate(match, pitch_history=history))


class PitchLogConnectionTests(unittest.TestCase):
    def test_pitch_log_becomes_next_day_fatigue_and_lower_abilities(self):
        from types import SimpleNamespace

        from game_core.tournament_bridge import AbilityMatchResolver

        abilities = make_roster_abilities(school_id="FAKE-LOG")
        team = TeamMatchInput("FAKE-LOG", TeamStrengthGenerator().generate(abilities), abilities)
        pitcher = next(a for a in abilities if a.primary_position == "P")
        resolver = SimpleNamespace(season_state=SimpleNamespace(
            pitch_log={pitcher.player_id: {"2026-07-20": 130, "2026-07-21": 30}}))
        history = AbilityMatchResolver._pitch_history(resolver, (team,), date(2026, 7, 21))
        self.assertEqual({pitcher.player_id: {1: 130}}, history)  # 今日の分は含めない
        sim = MatchSimulator()
        rule = sim.params["fatigue"]
        carry = sim.carry_fatigue(team, history)[pitcher.player_id]
        stage = fatigue.stage_of(carry, rule)
        self.assertGreaterEqual(stage, 1)
        self.assertTrue(fatigue.label_of(stage, rule))  # 画面に連投の疲れの印が出る
        self.assertLess(fatigue.tired(pitcher, stage, rule).stuff, pitcher.stuff)

    def test_rest_threshold_matches_the_first_screen_label(self):
        rule = MatchSimulator().params["fatigue"]
        first = rule["labels"][0]["min_stage"] * rule["stage_points"]
        self.assertEqual(first, rule["rest_starter_points"])


class FatigueInjuryTests(unittest.TestCase):
    def test_tired_pitchers_get_hurt_a_little_more_unless_injuries_are_off(self):
        model = injury_model()
        rested = model.match_chance(pitches=100, load7=100, consecutive=0, level="normal", fatigue_stage=0)[0]
        tired = model.match_chance(pitches=100, load7=100, consecutive=0, level="normal", fatigue_stage=6)[0]
        self.assertGreater(tired, rested)
        self.assertEqual(0.0, model.match_chance(
            pitches=100, load7=100, consecutive=0, level="none", fatigue_stage=6)[0])


if __name__ == "__main__":
    unittest.main()
