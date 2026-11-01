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
        order, _ = self.sim._game_staff(self.teams[0], None, {ace: rest + 1})
        self.assertEqual(second, order[0])
        self.assertIn(ace, order)
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
