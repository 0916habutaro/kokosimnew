"""采配の交代（段階F2）：代打・代走・守備固め・左右を見た起用（架空の学校・選手）。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest

from game_core.coaches import CoachTactics
from game_core.match_contract import validate_match_simulation_result
from game_core.match_simulator import MatchSimulator, validate_run_accounting
from game_core.match_state import TeamMatchParticipation, replay_team_participation
from test_stage13b3_team_strength import make_roster_abilities
import test_live_match_state as live

NEUTRAL = CoachTactics()


class DecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        abilities = make_roster_abilities(school_id="FAKE-SUBS")
        cls.base = next(a for a in abilities if a.primary_position not in ("P", "C"))
        cls.pitcher = replace(next(a for a in abilities if a.primary_position == "P"),
                              throws="R", platoon_trait=None)

    def batter(self, pid, **changes):
        values = {"contact": 50, "power": 50, "plate_discipline": 50, "speed": 50,
                  "bats": "R", "platoon_trait": None, **changes}
        return replace(self.base, player_id=pid, **values)

    def test_pinch_hitter_only_late_close_or_behind_with_a_clearly_better_bench_bat(self):
        weak, strong = self.batter("WEAK", contact=30, power=30), self.batter("STRONG", contact=75, power=75)
        pick = self.sim._choose_pinch_hitter
        args = dict(batter=weak, pitcher=self.pitcher, bench=[strong], pitcher_slot=False, tactics=NEUTRAL)
        self.assertEqual("STRONG", pick(inning=8, margin=-2, **args))
        self.assertIsNone(pick(inning=5, margin=-2, **args))      # 序盤
        self.assertIsNone(pick(inning=8, margin=3, **args))       # リードしている
        self.assertIsNone(pick(inning=8, margin=-6, **args))      # 大差で負けている
        close = self.batter("CLOSE", contact=35, power=35)
        self.assertIsNone(pick(inning=8, margin=0, batter=weak, pitcher=self.pitcher, bench=[close],
                               pitcher_slot=False, tactics=NEUTRAL))
        # 投手の打順は小さな差でも、積極的な監督は小さな差でも出す
        self.assertEqual("CLOSE", pick(inning=8, margin=0, batter=weak, pitcher=self.pitcher, bench=[close],
                                       pitcher_slot=True, tactics=NEUTRAL))
        self.assertEqual("CLOSE", pick(inning=8, margin=0, batter=weak, pitcher=self.pitcher, bench=[close],
                                       pitcher_slot=False, tactics=CoachTactics(substitutions=3.0)))

    def test_pinch_hitter_sees_the_pitchers_arm(self):
        # 左投手には、同じ能力なら右の打者の方が打てる
        lefty = replace(self.pitcher, throws="L")
        left_batter = self.batter("LB", bats="L", contact=45, power=45)
        right_bench = self.batter("RB", bats="R", contact=45, power=45)
        tactics = CoachTactics(substitutions=2.7)
        self.assertEqual("RB", self.sim._choose_pinch_hitter(
            batter=left_batter, pitcher=lefty, bench=[right_bench], inning=8, margin=-1,
            pitcher_slot=False, tactics=tactics))
        self.assertIsNone(self.sim._choose_pinch_hitter(
            batter=left_batter, pitcher=self.pitcher, bench=[right_bench], inning=8, margin=-1,
            pitcher_slot=False, tactics=tactics))

    def test_pinch_runner_for_a_slow_lead_runner_in_a_close_late_game(self):
        slow, fast = self.batter("SLOW", speed=35), self.batter("FAST", speed=80)
        players = {"SLOW": slow, "OTHER": self.batter("OTHER", speed=40)}
        pick = self.sim._choose_pinch_runner
        args = dict(players=players, bench=[fast], protected=set(), tactics=NEUTRAL)
        self.assertEqual(("SLOW", "FAST"), pick(bases=["OTHER", "SLOW", None], inning=9, margin=0, **args))
        self.assertIsNone(pick(bases=["OTHER", "SLOW", None], inning=6, margin=0, **args))
        self.assertIsNone(pick(bases=["OTHER", "SLOW", None], inning=9, margin=3, **args))
        self.assertEqual(("OTHER", "FAST"), pick(
            bases=["OTHER", "SLOW", None], inning=9, margin=0, players=players, bench=[fast],
            protected={"SLOW"}, tactics=NEUTRAL))

    def test_defensive_replacement_when_leading_and_for_players_who_entered_off_the_bench(self):
        inp = live.DHSimulationTests
        inp.setUpClass()
        team = inp.by_mode["none"][0]
        state = MatchSimulator()._initial_state(team, team.team_strength.starting_lineup.player_for_position("P"))
        players = {p.player_id: p for p in team.player_abilities}
        fielders = [a for a in state.defensive_alignment if a.defensive_position != "P"]
        target = fielders[0]
        poor = replace(players[target.player_id], fielding=10, arm_strength=10, throwing=10, catching=10)
        players[target.player_id] = poor
        glove = replace(players[target.player_id], player_id="GLOVE", fielding=95, arm_strength=95,
                        throwing=95, catching=95)
        pick = MatchSimulator()._choose_defensive_replacements
        args = dict(state=state, players=players, bench=[glove], tactics=NEUTRAL)
        self.assertEqual([(target.player_id, "GLOVE")], pick(inning=8, lead=2, entered=set(), **args))
        self.assertEqual([], pick(inning=8, lead=0, entered=set(), **args))
        self.assertEqual([], pick(inning=5, lead=2, entered=set(), **args))
        self.assertEqual([(target.player_id, "GLOVE")], pick(inning=8, lead=-3, entered={target.player_id}, **args))

    def test_platoon_reliever_matches_a_run_of_same_side_batters(self):
        players = {"RHP": replace(self.pitcher, player_id="RHP"),
                   "LHP": replace(self.pitcher, player_id="LHP", throws="L")}
        lefties = [self.batter(f"L{i}", bats="L") for i in range(2)] + [self.batter("R0")]
        pick = self.sim._platoon_reliever
        self.assertEqual("LHP", pick(candidates=["RHP", "LHP"], players=players, upcoming=lefties,
                                     inning=8, margin=1, tactics=NEUTRAL))
        self.assertIsNone(pick(candidates=["RHP", "LHP"], players=players, upcoming=lefties,
                               inning=4, margin=1, tactics=NEUTRAL))
        self.assertIsNone(pick(candidates=["RHP", "LHP"], players=players, upcoming=lefties,
                               inning=8, margin=6, tactics=NEUTRAL))
        switch = [self.batter(f"S{i}", bats="S") for i in range(3)]
        self.assertIsNone(pick(candidates=["RHP", "LHP"], players=players, upcoming=switch,
                               inning=8, margin=1, tactics=NEUTRAL))


class _Aggressive(MatchSimulator):
    """交代の基準をほとんどなくした試合計算（規則・整合を多くの交代で確かめる）。"""

    def __init__(self):
        super().__init__()
        self.params = deepcopy(self.params)
        subs = self.params["substitutions"]
        subs["late_inning_from"] = 1
        subs["pinch_hitter"].update(max_deficit=99, max_lead=99, min_gain=-100.0,
                                    pitcher_slot_min_gain=-100.0, max_per_game=4)
        subs["pinch_runner"].update(inning_from=1, max_deficit=99, max_lead=99, max_runner_speed=100,
                                    min_speed_gain=-100.0, max_per_game=3)
        subs["defensive_replacement"].update(min_lead=-99, max_lead=99, min_gain=-100.0,
                                             entered_min_gain=-100.0, max_per_half=1)


class FullGameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        live.DHSimulationTests.setUpClass()
        cls.fixture = live.DHSimulationTests()

    def test_many_substitutions_keep_rules_scores_and_earned_runs(self):
        reasons = set()
        for mode in ("none", "normal", "pitcher"):
            for number in range(3):
                with self.subTest(mode=mode, number=number):
                    inp = replace(self.fixture.match(mode), match_id=f"FAKE-SUBS-{mode}-{number}",
                                  generation_seed=20261300 + number)
                    result = _Aggressive().simulate(inp)
                    validate_match_simulation_result(result, inp)
                    if mode != "none":
                        validate_run_accounting(result)
                    for raw in result.team_participation:
                        record = TeamMatchParticipation.from_dict(raw.to_dict())
                        self.assertEqual(raw, record)  # 理由も保存・読込で残る
                        final = replay_team_participation(record, inp.reference_year)
                        reasons |= {c.reason for c in record.changes if c.reason}
                        # 一度退いた選手はそのあと打席に立たず、投げない
                        exited_at = {}
                        for change in record.changes:
                            if change.outgoing_player_id and change.reason:
                                exited_at.setdefault(change.outgoing_player_id,
                                                     change.moment.next_plate_appearance_no)
                        for event in result.events:
                            for pid in (event.batter_id, event.pitcher_id):
                                if pid in exited_at:
                                    self.assertLess(event.plate_appearance_no, exited_at[pid])
                        self.assertTrue(set(exited_at) <= final.exited_player_ids)
                    for row in result.batter_stats:
                        self.assertLessEqual(row.pinch_hit_at_bats, row.at_bats)
        self.assertEqual({"pinch_hitter", "pinch_runner", "defensive_replacement"}, reasons)

    def test_pinch_hitter_for_the_pitcher_brings_in_a_new_pitcher_without_pitching_himself(self):
        inp = replace(self.fixture.match("none"), match_id="FAKE-SUBS-P", generation_seed=20261400)
        result = _Aggressive().simulate(inp)
        pitchers = {(p.school_id, p.player_id) for p in result.pitcher_stats}
        for raw in result.team_participation:
            for change in raw.changes:
                if change.reason == "pinch_hitter" and any(
                        c.defensive_position == "P" and c.after_player_id == change.incoming_player_id
                        for c in change.defensive_changes):
                    self.assertNotIn((raw.school_id, change.incoming_player_id), pitchers)

    def test_weight_reuse_matches_uncached_games_with_substitutions(self):
        class Uncached(_Aggressive):
            pass

        for mode in ("none", "normal"):
            with self.subTest(mode=mode):
                inp = self.fixture.match(mode)
                cached = _Aggressive()
                cached_result = cached.simulate(inp)
                self.assertTrue(any(c.reason for p in cached_result.team_participation for c in p.changes))
                # _Aggressive も MatchSimulator の子なので使い回しはしない。本物と比べるため型をそろえる
                real = MatchSimulator()
                real.params = cached.params
                self.assertEqual(real.simulate(inp).to_dict(), Uncached().simulate(inp).to_dict())


if __name__ == "__main__":
    unittest.main()
