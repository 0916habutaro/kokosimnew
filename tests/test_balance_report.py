"""バランスの物差しの集計（架空の学校・選手の試合記録で確かめる。試合は進めない）。"""
from __future__ import annotations

import unittest

from phase2_engine.balance_report import BalanceTally, average

RANKINGS = {
    "batter_qualification": {"minimum_team_games": 1, "plate_appearances_per_team_game": 2.0},
    "pitcher_qualification": {"minimum_team_games": 1, "outs_recorded_per_team_game": 3.0},
}
KINDS = {"LOC": "summer_local_qualifier", "KOS": "national_championship"}


def match(year, cid, a, b, score_a, score_b, inning, *, complete=True, sb=0, dp=0):
    pitchers = [dict(player_id=f"{a}-P1", school_id=a, batters_faced=30, pitches=120,
                     outs_recorded=27, earned_runs=score_b),
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
        "batter_stats": [dict(player_id=f"{a}-B1", school_id=a, plate_appearances=4, at_bats=4,
                              hits=2, home_runs=1, stolen_bases=sb, grounded_into_double_plays=dp),
                         dict(player_id=f"{b}-B1", school_id=b, plate_appearances=4, at_bats=4,
                              hits=1, home_runs=0)],
    }


class BalanceTallyTests(unittest.TestCase):
    def tally(self, history=None):
        return BalanceTally(lambda cid: KINDS[cid[:3]], history or {}, RANKINGS)

    def test_local_metrics_and_per_game_counts(self):
        tally = self.tally()
        tally.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-B", 10, 0, 5, sb=2, dp=1))
        tally.add_match("LOC1", match(2026, "LOC1", "FAKE-C", "FAKE-D", 3, 2, 9, complete=False))
        row = tally.summary()[2026]
        self.assertEqual({"games": 2, "runs_per_team": 3.75, "called_share": 0.5,
                          "shutout_share": 0.5}, row["local"])
        self.assertEqual({"starts": 4, "pitches_mean": 100.0, "complete_game_share": 0.75},
                         row["starters"])
        self.assertEqual({"games": 2, "stolen_bases": 1.0, "double_plays": 0.5}, row["per_game"])

    def test_first_time_and_repeat_use_real_history_then_earlier_game_years(self):
        tally = self.tally({"FAKE-A": {2020, 2025}})
        tally.add_match("KOS", match(2026, "KOS", "FAKE-A", "FAKE-B", 3, 1, 9))
        tally.add_match("KOS", match(2027, "KOS", "FAKE-B", "FAKE-C", 3, 1, 9))
        summary = tally.summary()
        self.assertEqual({"teams": 2, "first_time": 1, "first_time_share": 0.5, "repeat": 1},
                         summary[2026]["koshien"])
        # FAKE-B は2026年に出ているので初出場ではなく、2年続けて
        self.assertEqual({"teams": 2, "first_time": 1, "first_time_share": 0.5, "repeat": 1},
                         summary[2027]["koshien"])

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

    def test_leaders_skip_players_whose_team_played_too_few_games(self):
        tally = BalanceTally(lambda cid: KINDS[cid[:3]], {}, RANKINGS, min_team_games=2)
        tally.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-B", 2, 1, 9))
        tally.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-C", 2, 1, 9))
        leaders = tally.summary()[2026]["leaders"]
        self.assertEqual({"FAKE-A"}, {r[2] for rows in leaders.values() for r in rows})

    def test_average_keeps_shared_numbers_and_drops_leaders(self):
        a, b = self.tally(), self.tally()
        a.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-B", 4, 0, 9))
        b.add_match("LOC1", match(2026, "LOC1", "FAKE-A", "FAKE-B", 2, 1, 9))
        merged = average([a.summary(), b.summary()])
        self.assertEqual(1.75, merged[2026]["local"]["runs_per_team"])
        self.assertEqual(0.5, merged[2026]["local"]["shutout_share"])
        self.assertNotIn("leaders", merged[2026])


if __name__ == "__main__":
    unittest.main()
