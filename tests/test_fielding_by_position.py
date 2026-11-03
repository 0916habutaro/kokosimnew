"""打球の方向ごとの守備（H2）：行き先・守った選手の効き・失策の付け先・進塁と併殺（架空の学校・選手）。"""
from __future__ import annotations

from dataclasses import replace
import unittest

from game_core.match_contract import validate_match_simulation_result
from game_core.match_simulator import MatchSimulator, _Fielded, validate_run_accounting
import test_pitcher_run_accounting as accounting
from test_stage13b3_team_strength import make_roster_abilities


class _Rolls:
    """random() が並べた値を順に返す乱数。"""

    def __init__(self, *values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0)


class FieldingDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        cls.players = make_roster_abilities(school_id="FAKE-FLD")
        cls.by_position = {}
        for player in cls.players:
            cls.by_position.setdefault(player.primary_position, player)
        cls.right = replace(cls.players[8], bats="R")
        cls.left = replace(cls.players[8], bats="L")
        cls.pitcher = replace(cls.by_position["P"], throws="R")

    def alignment(self, **override):
        positions = ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
        lineup = {pos: self.by_position.get(pos, self.by_position["LF"]) for pos in positions}
        lineup.update(override)
        players = {}
        alignment = []
        for pos in positions:
            player = replace(lineup[pos], player_id=f"FAKE-{pos}")
            players[player.player_id] = player
            alignment.append((pos, player.player_id))
        return tuple(alignment), players

    def test_direction_by_batting_side(self):
        # ゴロ・引っ張り（方向の最初）・最初の守備位置：右打者は三塁、左打者は一塁
        position = self.sim._fielding_position
        self.assertEqual("3B", position("field_out", "ground", "R", _Rolls(0.0, 0.0)))
        self.assertEqual("1B", position("field_out", "ground", "L", _Rolls(0.0, 0.0)))
        # 流しのフライの大半は右翼（右打者）、左打者は左翼
        self.assertEqual("RF", position("field_out", "fly", "R", _Rolls(0.99, 0.0)))
        self.assertEqual("LF", position("field_out", "fly", "L", _Rolls(0.99, 0.0)))
        # 長打は外野だけ
        self.assertEqual("CF", position("double", "line", "R", _Rolls(0.6, 0.5)))

    def test_profile_reference_and_out_of_position(self):
        alignment, players = self.alignment()
        profile = self.sim._fielding_profile(alignment, players)
        shares = self.sim.params["fielding"]["reference_share"]
        expected = sum(profile.players[p][1] * shares[p] for p in shares) / sum(shares.values())
        self.assertAlmostEqual(expected, profile.skill_reference)
        self.assertNotIn("C", profile.players)  # 捕手は打球を処理しない（盗塁・暴投・捕逸で効く）
        # 本職でない選手（捕手）を遊撃に置くと、適性が低く守備の値が下がる
        moved_alignment, moved_players = self.alignment(SS=self.by_position["C"])
        moved = self.sim._fielding_profile(moved_alignment, moved_players)
        self.assertLess(moved.players["SS"][3], 60)
        self.assertLess(moved.players["SS"][1], profile.players["SS"][1])

    def test_fielded_event_split_points(self):
        rule = self.sim.params["fielding"]
        weights = {"single": 0.2, "field_out": 0.5, "reached_on_error": 0.02}
        event = self.sim._fielded_event
        gap = 10.0
        m_hit = self.sim._fielding_multiplier(gap, rule["hit_log_per_point"])
        self.assertLess(m_hit, 1)
        # うまい選手：単打を m の割合だけ残し、残りは凡退
        self.assertEqual("single", event("single", weights, gap, _Rolls(m_hit - 1e-9, 0.0)))
        self.assertEqual("field_out", event("single", weights, gap, _Rolls(m_hit, 0.0)))
        # へたな選手：凡退を (m − 1) × 単打 ÷ 凡退 の割合で単打に
        m_bad = self.sim._fielding_multiplier(-gap, rule["hit_log_per_point"])
        threshold = (m_bad - 1) * 0.2 / 0.5
        self.assertEqual("single", event("field_out", weights, -gap, _Rolls(threshold - 1e-9, 0.99)))
        self.assertEqual("field_out", event("field_out", weights, -gap, _Rolls(threshold, 0.99)))
        # 失策も同じ：へたな選手の凡退が失策に
        m_err = self.sim._fielding_multiplier(-gap, rule["error_log_per_point"])
        self.assertGreater(m_err, m_bad)
        e_threshold = (m_err - 1) * 0.02 / 0.5
        self.assertEqual("reached_on_error",
                         event("field_out", weights, -gap, _Rolls(0.99, e_threshold - 1e-9)))
        # 重みに単打・凡退がない（試験用の打席列）なら変えない
        self.assertEqual("single", event("single", {"single": 1.0}, gap, _Rolls()))
        # 倍率は上限・下限に収まる
        self.assertEqual(rule["max_multiplier"], self.sim._fielding_multiplier(-1000, 1.0))

    def test_double_play_bonus_from_infielder_arm(self):
        # ゴロ（打球の種類を渡す）で一塁に走者・0死：併殺の確率が肩の差で動く
        def dp(bonus, roll):
            return self.sim._classify_out("field_out", ["R1", None, None], 0, self.right,
                                          _Rolls(roll), self.pitcher, 50.0, "ground", bonus)
        base = self.sim._double_play_probability(float(self.right.speed), 50.0)
        self.assertEqual("ground_out", dp(0.0, base + 0.01))
        self.assertEqual("double_play", dp(0.05, base + 0.01))
        # ライナーの凡退は犠飛にしない
        self.assertEqual("fly_out", self.sim._classify_out(
            "field_out", [None, None, "R3"], 0, self.right, _Rolls(0.0), self.pitcher, 50.0, "line"))


class _FixedFielder(accounting._ScriptedSimulator):
    """打球はいつも同じ守備位置へ。守った選手で結果は変えない（試験用の打席列のまま）。"""

    position = "SS"
    arm_gap = 0.0
    seen_defense: list

    def _field_ball(self, event_type, *, weights, batter, pitcher, profile, rng):
        if event_type not in ("single", "double", "triple", "field_out", "reached_on_error"):
            return event_type, None
        player_id, skill, _, aptitude = profile.players[self.position]
        return event_type, _Fielded(self.position, player_id, "ground", skill, aptitude, 0.0, self.arm_gap)

    def _apply_event(self, **kwargs):
        self.__dict__.setdefault("seen_defense", []).append(kwargs["defense_strength"])
        return super()._apply_event(**kwargs)


class ErrorChargeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        accounting.PitcherRunAccountingTests.setUpClass.__func__(cls)

    match = accounting.PitcherRunAccountingTests.match

    def play(self, position, top, arm_gap=0.0):
        class Sim(_FixedFielder):
            pass

        Sim.position, Sim.arm_gap = position, arm_gap
        # 最後の本塁打で試合を決める
        sim = Sim({self.teams[1].school_id: (*top, "home_run"), self.teams[0].school_id: ()})
        result = sim.simulate(self.match())
        validate_match_simulation_result(result, self.match())
        return sim, result

    def test_error_is_charged_to_the_fielder(self):
        _, result = self.play("SS", ["reached_on_error", "reached_on_error"])
        defense = self.teams[1].school_id
        team = next(t for t in result.team_stats if t.school_id == defense)
        event = result.events[0]
        position, fielder = dict(event.metadata)["fielder"].split("|")
        self.assertEqual("SS", position)
        rows = {b.player_id: b for b in result.batter_stats if b.school_id == defense}
        self.assertEqual((2, 2), (team.errors, rows[fielder].errors))
        self.assertEqual(0, sum(p.errors for p in result.pitcher_stats))
        # 失策の走者の得点は自責点にしない（今までどおり）
        self.assertTrue(all(p.earned_runs <= p.runs_allowed for p in result.pitcher_stats))

    def test_pitcher_error_goes_to_the_pitcher(self):
        _, result = self.play("P", ["reached_on_error"])
        pitcher = next(p for p in result.pitcher_stats if p.player_id == result.events[0].pitcher_id)
        self.assertEqual(1, pitcher.errors)
        self.assertEqual(0, sum(b.errors for b in result.batter_stats))

    def test_validation_rejects_a_missing_or_wrong_fielder(self):
        _, result = self.play("SS", ["reached_on_error"])
        event = result.events[0]
        for metadata in (tuple((k, v) for k, v in event.metadata if k != "fielder"),
                         tuple((k, "P|" + v.split("|")[1] if k == "fielder" else v) for k, v in event.metadata)):
            tampered = replace(result, events=(replace(event, metadata=metadata), *result.events[1:]))
            with self.assertRaises(ValueError):
                validate_match_simulation_result(tampered, self.match())

    def test_fielder_arm_changes_runner_advance(self):
        rule = MatchSimulator().params["fielding"]
        sim, _ = self.play("RF", ["single", "single"], arm_gap=10.0)
        base = next(t for t in self.teams if t.school_id == self.teams[1].school_id).team_strength.defense_strength
        # 肩の差 +10 で、進塁の判断に使う守備力が 10 × advance_points_per_arm_point 上がる
        self.assertAlmostEqual(base + 10.0 * rule["advance_points_per_arm_point"], sim.seen_defense[0])
        runner = make_roster_abilities(school_id="FAKE-FLD")[8]
        advance = MatchSimulator()._advance_probability
        self.assertLess(advance(base_probability=0.6, runner=runner, defense_strength=base + 6.0),
                        advance(base_probability=0.6, runner=runner, defense_strength=base))


class StrictReplayAndReuseTests(unittest.TestCase):
    def test_dh_replay_with_errors(self):
        from test_live_match_state import DHSimulationTests

        DHSimulationTests.setUpClass()
        fixture = DHSimulationTests()
        _, result, _ = fixture.play('normal', regulation_innings=2,
                                    top=('reached_on_error', 'single', 'reached_on_error', 'double'))
        validate_run_accounting(result)
        self.assertEqual(2, sum(e.event_type == "reached_on_error" for e in result.events))
        self.assertEqual(2, sum(b.errors for b in result.batter_stats) + sum(p.errors for p in result.pitcher_stats))

    def test_weight_reuse_gives_the_same_result_with_fielding(self):
        from game_core.match_contract import MatchSimulationInput

        class Uncached(MatchSimulator):
            """使い回しをしない（MatchSimulator そのものだけが使い回す）。"""

        accounting.PitcherRunAccountingTests.setUpClass.__func__(type(self))
        sim = MatchSimulator()
        for number in range(3):
            match = MatchSimulationInput(f"H2-{number}", "FAKE-RUN-CUP", 2026, 20261103 + number,
                                         *self.teams, team_generation_seed=2026100701)
            self.assertEqual(sim.simulate(match), Uncached().simulate(match))


if __name__ == "__main__":
    unittest.main()
