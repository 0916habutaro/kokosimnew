"""試合の画面の「成績」の表（phase2_engine/screen/match_tables.py）。選手・学校はすべて架空。"""
from __future__ import annotations

import unittest

from phase2_engine.screen.match_tables import batting_table, innings_label, pitching_table


def batter(pid, order=None, **stats):
    return {"player_id": pid, "batting_order": order, "at_bats": 0, "runs": 0, "hits": 0, **stats}


LINEUP = {"players": [{"player_id": f"S{n}", "batting_order": n} for n in range(1, 10)]}
CHANGES = [
    # 5回：3番の代打 PH（そのあと一塁）、7回：9番の代走 PR（守らずに退く）
    {"school_id": "T", "incoming": {"player_id": "PH"}, "batting_order": 3, "reason": "pinch_hitter",
     "kind": "substitution"},
    {"school_id": "T", "incoming": {"player_id": "PR"}, "batting_order": 9, "reason": "pinch_runner",
     "kind": "substitution"},
    {"school_id": "U", "incoming": {"player_id": "X"}, "batting_order": 1, "reason": None, "kind": "substitution"},
]


class BattingTableTests(unittest.TestCase):
    def table(self):
        rows = [batter(f"S{n}", n, at_bats=4, hits=n % 2, runs=1 if n == 1 else 0) for n in range(1, 10)]
        rows += [batter("PH", 3, at_bats=2, hits=1), batter("PR", 9)]
        history = {"S1": ["投", "一", "投"], "S3": ["一"], "PH": ["一"], "S9": ["中"]}
        return batting_table(rows, LINEUP, CHANGES, "T", history)

    def test_substitutes_come_right_after_the_player_they_replaced(self):
        rows = self.table()["rows"]
        self.assertEqual(["S1", "S2", "S3", "PH", "S4", "S5", "S6", "S7", "S8", "S9", "PR"],
                         [row["player_id"] for row in rows])
        ph = rows[3]
        self.assertEqual((None, True), (ph["slot"], ph["sub"]))
        self.assertEqual((3, False), (rows[2]["slot"], rows[2]["sub"]))

    def test_marks(self):
        marks = {row["player_id"]: row["mark"] for row in self.table()["rows"]}
        self.assertEqual(("打一", "走", "投一投", "一"), (marks["PH"], marks["PR"], marks["S1"], marks["S3"]))

    def test_total_is_the_sum_of_the_rows(self):
        table = self.table()
        for key in ("at_bats", "runs", "hits"):
            self.assertEqual(sum(row[key] for row in table["rows"]), table["total"][key])
        self.assertEqual(38, table["total"]["at_bats"])

    def test_defensive_entry_starts_with_shu(self):
        rows = [batter("S1", 1), batter("X", 1)]
        table = batting_table(rows, LINEUP, CHANGES, "U", {"X": ["中"]})
        self.assertEqual("守中", next(row["mark"] for row in table["rows"] if row["player_id"] == "X"))

    def test_without_lineup_record_keeps_order(self):
        table = batting_table([batter("A", 1), batter("B", 2)], None, [], "T", {})
        self.assertEqual(["−", "−"], [row["mark"] for row in table["rows"]])


class PitchingTableTests(unittest.TestCase):
    def test_innings(self):
        self.assertEqual(("2/3", "1 1/3", "3", "0"), (innings_label(2), innings_label(4), innings_label(9),
                                                      innings_label(0)))

    def test_only_two_way_pitcher_gets_a_mark_and_total_innings(self):
        rows = [{"player_id": "P1", "outs": 20, "hits_allowed": 5, "home_runs_allowed": 1, "walks": 1,
                 "hit_batters": 1},
                {"player_id": "P2", "outs": 4, "hits_allowed": 1, "home_runs_allowed": 0}]
        table = pitching_table(rows, two_way={"P1"})
        # DH の試合で、兼任でない投手に「守備専任」などの札は付かない
        self.assertEqual(["投・DH", ""], [row["mark"] for row in table["rows"]])
        self.assertEqual(["6 2/3", "1 1/3"], [row["innings"] for row in table["rows"]])
        self.assertEqual(("8", 6, 1, 2), (table["total"]["innings"], table["total"]["hits_allowed"],
                                          table["total"]["home_runs_allowed"], table["total"]["walks_hbp"]))



class RunningScoreTests(unittest.TestCase):
    def test_home_steal_run_is_counted(self):
        # 0−0 から本盗で先制し、そのあと適時打で1点：適時打の行は 2−0
        from phase2_engine.screen.competition_views import match_detail
        row = {"team1_id": "A", "team2_id": "B", "team1_score": 2, "team2_score": 0, "status": "completed"}
        detail = {"inning_scores": [{"inning": 1, "half": "top", "batting_team_id": "A", "runs": 2,
                                     "plate_appearances": 5}],
                  "highlights": [["B", 1, "t", "R1", "sb", 4], ["S", 1, "t", "H1", "single", 1]]}
        out = match_detail(row, detail, lambda sid: sid, lambda sid: {})
        self.assertEqual(["1−0", "2−0"], [h.get("score") for h in out["highlights"]])


if __name__ == "__main__":
    unittest.main()
