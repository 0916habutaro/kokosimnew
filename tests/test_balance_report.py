"""バランスの物差しの集計（架空の学校・選手の試合記録で確かめる。試合は進めない）。"""
from __future__ import annotations

import unittest

from phase2_engine.balance_report import BalanceTally, average, format_report

RANKINGS = {
    "batter_qualification": {"minimum_team_games": 1, "plate_appearances_per_team_game": 2.0},
    "pitcher_qualification": {"minimum_team_games": 1, "outs_recorded_per_team_game": 3.0},
}
KINDS = {"LOC": "summer_local_qualifier", "KOS": "national_championship"}


def match(year, cid, a, b, score_a, score_b, inning, *, complete=True, sb=0, dp=0, wp=0, pb=0, errors=0):
    pitchers = [dict(player_id=f"{a}-P1", school_id=a, batters_faced=30, pitches=120,
                     outs_recorded=27, earned_runs=score_b, wild_pitches=wp),
                dict(player_id=f"{b}-P1", school_id=b, batters_faced=20, pitches=80,
                     outs_recorded=15, earned_runs=score_a)]
    if not complete:
        pitchers.append(dict(player_id=f"{b}-P2", school_id=b, batters_faced=5, pitches=20,
                             outs_recorded=3, earned_runs=0))
    return {
        "reference_year": year, "competition_id": cid,
        "team1_school_id": a, "team2_school_id": b,
        "team1_score": score_a, "team2_score": score_b, "last_inning": inning,
        "team_participation": [dict(school_id=a, starting_pitcher_id=f"{a}-P1"),
                               dict(school_id=b, starting_pitcher_id=f"{b}-P1")],
        "pitcher_stats": pitchers,
        "team_stats": [dict(school_id=a, errors=errors), dict(school_id=b, errors=0)],
        "batter_stats": [dict(player_id=f"{a}-B1", school_id=a, plate_appearances=4, at_bats=4,
                              hits=2, home_runs=1, stolen_bases=sb, grounded_into_double_plays=dp),
                         dict(player_id=f"{b}-B1", school_id=b, plate_appearances=4, at_bats=4,
                              hits=1, home_runs=0, passed_balls=pb)],
    }


class BalanceTallyTests(unittest.TestCase):
    def tally(self, history=None):
        return BalanceTally(lambda cid: KINDS[cid[:3]], history or {}, RANKINGS)

    def test_local_metrics_and_per_game_counts(self):
        tally = self.tally()
        tally.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-B", 10, 0, 5, sb=2, dp=1, wp=2, pb=1, errors=3))
        tally.add_match("LOC1", match(2026, "LOC1", "FAKE-C", "FAKE-D", 3, 2, 9, complete=False))
        row = tally.summary()[2026]
        self.assertEqual({"games": 2, "runs_per_team": 3.75, "called_share": 0.5,
                          "shutout_share": 0.5, "extra_share": 0.0,
                          "margin": {"0-2": 0.5, "3-5": 0.0, "6-9": 0.0, "10+": 0.5}}, row["local"])
        self.assertEqual({"starts": 4, "pitches_mean": 100.0, "complete_game_share": 0.75},
                         row["starters"])
        self.assertEqual({"games": 2, "stolen_bases": 1.0, "double_plays": 0.5, "wild_pitches": 1.0,
                          "passed_balls": 0.5, "errors": 1.5, "errors_local": 1.5}, row["per_game"])
        # 球数：420球・105打者・87アウト（2試合。2試合目は救援が1人）
        self.assertEqual({"per_plate_appearance": 4.0, "per_team_game": 105.0, "per_nine_innings": 130.3},
                         row["pitch_counts"])

    def test_first_time_and_repeat_use_real_history_then_earlier_game_years(self):
        tally = self.tally({"FAKE-A": {2020, 2025}})
        tally.add_match("KOS", match(2026, "KOS", "FAKE-A", "FAKE-B", 3, 1, 9))
        tally.add_match("KOS", match(2027, "KOS", "FAKE-B", "FAKE-C", 3, 1, 9))
        summary = tally.summary()
        # FAKE-A は2020年・2025年に出ている（直前10年に2回）、FAKE-B は初めて
        self.assertEqual({"teams": 2, "first_time": 1, "first_time_share": 0.5, "repeat": 1,
                          "prior10": {"0": 0.5, "1": 0.0, "2": 0.5, "3": 0.0}},
                         summary[2026]["koshien"])
        # FAKE-B は2026年に出ているので初出場ではなく、2年続けて
        self.assertEqual({"teams": 2, "first_time": 1, "first_time_share": 0.5, "repeat": 1,
                          "prior10": {"0": 0.5, "1": 0.5, "2": 0.0, "3": 0.0}},
                         summary[2027]["koshien"])
        # 甲子園の1試合あたり（両チーム）と大会の個人成績
        per_game = summary[2026]["koshien_per_game"]
        self.assertEqual((1, 1.0, 0.375), (per_game["games"], per_game["home_runs"], per_game["batting_average"]))
        self.assertIn("koshien_leaders", summary[2026])

    def test_leaders_use_qualification_and_rosters_count_s_and_velocity(self):
        tally = self.tally()
        tally.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-B", 2, 1, 9))
        tally.add_rosters(2026, [
            (3, True, {"velocity_kmh": 151, "control": 90, "stamina": 40}),
            (3, True, {"velocity_kmh": 128, "control": 60}),
            (2, True, {"velocity_kmh": 149, "control": 95}),
            (3, False, {"velocity_kmh": None, "contact": 92}),
        ])
        row = tally.summary()[2026]
        leaders = row["leaders"]
        self.assertEqual([0.5, 0.25], [r[0] for r in leaders["batting_average"]])
        self.assertEqual(1, leaders["home_runs"][0][0])
        # 5回（15アウト）の投手は規定（1試合3アウト）に届くが、自責点が多いので2番目
        self.assertEqual([1.0, 3.6], [r[0] for r in leaders["earned_run_average"]])
        rosters = row["rosters"]
        self.assertEqual(2, rosters["third_year_pitchers"])
        self.assertEqual(1, rosters["velocity_bands"]["150〜"])
        self.assertEqual(1, rosters["velocity_bands"]["〜129"])
        self.assertEqual({"contact": 1, "control": 2}, rosters["s_count"])

    def test_rosters_count_a_by_grade_and_koshien_bench_by_grade(self):
        from types import SimpleNamespace

        tally = self.tally()
        tally.add_rosters(2026, [
            (1, False, {"contact": 82, "power": 81, "velocity_kmh": None}),
            (1, False, {"contact": 79, "strikeout_resistance": 95}),  # 主な能力でないものは数えない
            (2, True, {"control": 80, "velocity_kmh": 146}),
            (3, True, {"control": 91, "stuff": 85, "velocity_kmh": 151}),
            (3, False, {"speed": 90}),
        ])
        grades = tally.summary()[2026]["rosters"]["by_grade"]
        self.assertEqual((1, 1), (grades["1"]["a_one"], grades["1"]["a_two"]))
        self.assertEqual((1, 0, 1, 0), (grades["2"]["a_one"], grades["2"]["a_two"],
                                        grades["2"]["kmh145"], grades["2"]["kmh150"]))
        self.assertEqual((2, 1, 1, 151), (grades["3"]["a_one"], grades["3"]["a_two"],
                                          grades["3"]["kmh150"], grades["3"]["fastest"]))
        self.assertEqual({"control": 1, "speed": 1}, tally.summary()[2026]["rosters"]["s_third_main"])

        def player(pid, grade):
            return SimpleNamespace(player_id=pid, academic_year=grade)

        rosters = SimpleNamespace(roster=lambda year, sid: SimpleNamespace(players={
            "FAKE-A": [player("a1", 1), player("a2", 2), player("a3", 3), player("a4", 3)],
            "FAKE-B": [player("b1", 1), player("b2", 2)],
        }[sid]))
        season = SimpleNamespace(bench_members={
            "KOS1:FAKE-A": ("a1", "a3"),  # ベンチ入りの選手だけ
            "KOS1:FAKE-B": (),            # 全員が入った学校
            "LOC1:FAKE-A": ("a2",),       # 地方大会は数えない
        })
        tally.add_koshien_bench(2026, season, rosters)
        self.assertEqual({"1": 2, "2": 1, "3": 1}, tally.summary()[2026]["koshien_bench"])
        self.assertIn("夏の甲子園のベンチ入り: 1年 2人（50.0%）", format_report("x", tally.summary()))

    def test_summer_unions_against_five_single_years_and_last_year(self):
        from types import SimpleNamespace

        tally = self.tally()
        # 実際の記録：5年続けて単独 FAKE-A〜D、2025年に連合 FAKE-E・F
        tally.summer_actual = ({"FAKE-A", "FAKE-B", "FAKE-C", "FAKE-D"}, {"FAKE-E", "FAKE-F"})

        def season(*teams):
            run = SimpleNamespace(entrant_school_ids=["FAKE-A"] + [f"FAKE-S{n}" for n in range(9)])
            return SimpleNamespace(union_plans={"LOC1": SimpleNamespace(
                teams=[SimpleNamespace(schools=team) for team in teams], absent=())},
                competitions={"LOC1": SimpleNamespace(to_competition_run=lambda: run)})

        tally.add_unions(2026, season(("FAKE-A", "FAKE-E"), ("FAKE-X", "FAKE-Y")), tally.kind_of)
        tally.add_unions(2027, season(("FAKE-A", "FAKE-Z")), tally.kind_of)
        out = tally.summary()
        self.assertEqual({"five_single": 1, "five_single_total": 4, "five_single_share": 0.25,
                          "previous": 2, "continued": 1, "continued_share": 0.5},
                         out[2026]["summer_union_history"])
        # 2027年は2026年のゲームの連合（4校）から続けて連合になった割合
        self.assertEqual((1, 4), (out[2027]["summer_union_history"]["continued"],
                                  out[2027]["summer_union_history"]["previous"]))
        self.assertIn("夏の連合：5年続けて単独だった学校が連合 1／4校（25.0%）", format_report("x", out))
        # 夏の連合チームの数と、出場チーム（連合は1チーム）のうち連合の割合
        self.assertEqual(10, out[2026]["unions"]["summer_local_qualifier"]["entrants"])
        self.assertIn("夏の地方大会の連合チーム: 2チーム／出場10チーム（20.0%）", format_report("x", out))

    def test_leaders_skip_players_whose_team_played_too_few_games(self):
        tally = BalanceTally(lambda cid: KINDS[cid[:3]], {}, RANKINGS, min_team_games=2)
        tally.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-B", 2, 1, 9))
        tally.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-C", 2, 1, 9))
        leaders = tally.summary()[2026]["leaders"]
        self.assertEqual({"FAKE-A"}, {r[2] for rows in leaders.values() for r in rows})

    def test_top_reputation_turnover(self):
        tally = self.tally()
        for year in range(2026, 2032):
            # 毎年1校ずつ入れ替わる（架空の学校）
            tally.add_top_reputation(year, {f"X{n}": -n for n in range(year - 2026, 60)}, count=3)
        out = tally.summary()
        self.assertNotIn("reputation_top50", out[2026])
        self.assertEqual({"vs_previous": 1, "vs_start": 1}, out[2027]["reputation_top50"])
        self.assertEqual({"vs_previous": 1, "vs_5_years": 3, "vs_start": 3},
                         out[2031]["reputation_top50"])
        self.assertIn("評判の上位50校の入れ替わり: 前の年から 1校 / 5年前から 3校",
                      format_report("x", out))

    def test_average_keeps_shared_numbers_and_drops_leaders(self):
        a, b = self.tally(), self.tally()
        a.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-B", 4, 0, 9))
        b.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-B", 2, 1, 9))
        merged = average([a.summary(), b.summary()])
        self.assertEqual(1.75, merged[2026]["local"]["runs_per_team"])
        self.assertEqual(0.5, merged[2026]["local"]["shutout_share"])
        self.assertNotIn("leaders", merged[2026])



class PlatoonAndAbilityTableTests(unittest.TestCase):
    def test_platoon_within_the_same_batter(self):
        tally = BalanceTally(lambda cid: KINDS[cid[:3]], {}, RANKINGS)
        detail = match(2026, "LOC1", "FAKE-A", "FAKE-B", 2, 1, 9)
        detail["batter_stats"][0].update(vs_rhp_at_bats=20, vs_rhp_hits=4, vs_lhp_at_bats=20, vs_lhp_hits=8)
        tally.add_match("LOC1", detail, bats_of=lambda school, player: "R")
        # 右打ちが逆の側（左投手）に .400、同じ側に .200
        self.assertEqual({"R": {"weight": 20.0, "opposite_minus_same": 0.2}},
                         tally.summary()[2026]["platoon_within"])

    def test_ability_table_moves_in_the_intended_direction(self):
        from phase2_engine.balance_report import ability_table

        table = ability_table()
        contact = table["打者 contact"]
        self.assertLess(contact[30]["average"], contact[50]["average"])
        self.assertLess(contact[50]["average"], contact[95]["average"])
        self.assertLess(table["打者 power"][30]["home_run"], table["打者 power"][95]["home_run"])
        self.assertGreater(table["投手 strikeout"][95]["strikeout"], table["投手 strikeout"][50]["strikeout"])
        self.assertLess(table["投手 control"][95]["walk"], table["投手 control"][30]["walk"])


class SituationCounterTests(unittest.TestCase):
    def test_counts_tactics_by_situation_and_restores_the_simulator(self):
        from game_core.match_simulator import MatchSimulator
        from phase2_engine.balance_report import SituationCounter
        import test_pitcher_run_accounting as accounting

        accounting.PitcherRunAccountingTests.setUpClass()
        fixture = accounting.PitcherRunAccountingTests()
        original = MatchSimulator._choose_tactic
        original_pitches = MatchSimulator._pitches
        original_field = MatchSimulator._field_ball
        counter = SituationCounter(lambda cid: "national_championship")
        with counter.watching():
            for number in range(3):
                MatchSimulator().simulate(fixture.match(number))
        self.assertIs(original, MatchSimulator._choose_tactic)
        summary = counter.summary()[2026]
        first = summary["all"]["無死一塁"]
        self.assertGreater(first["plate_appearances"], 0)
        self.assertTrue(0 <= first["bunt"] <= 1 and 0 <= first["hit_and_run"] <= 1)
        self.assertEqual(summary["all"], summary["koshien"])
        # 度胸の帯ごとの被打率も数え、包んだものは元に戻る
        self.assertIs(original_pitches, MatchSimulator._pitches)
        bands = counter.play_summary()[2026]["composure"]
        self.assertTrue(bands and all(0 <= v["average"] <= 1 for v in bands.values()))
        # 守備位置・守備の値の帯ごとの打球も数える（H2）
        self.assertIs(original_field, MatchSimulator._field_ball)
        fielding = counter.play_summary()[2026]["fielding"]
        self.assertEqual(fielding["all"]["balls"],
                         sum(v["balls"] for k, v in fielding.items() if k.startswith("pos:")))


if __name__ == "__main__":
    unittest.main()
