"""試合の画面の経過・交代の文言（phase2_engine/screen/match_wording.py）。学校・選手はすべて架空。"""
from __future__ import annotations

from pathlib import Path
import unittest

from phase2_engine.screen.competition_views import match_detail
from phase2_engine.screen.match_wording import (
    group_changes, load_wording, plate_appearance_orders, score_text, tactic_text, wild_pitch_text,
)

WORDING = load_wording(Path(__file__).resolve().parents[1] / "config")


class WordingTests(unittest.TestCase):
    def test_score_events(self):
        self.assertEqual("適時打で2点", score_text(WORDING, "single", 2))
        self.assertEqual("内野ゴロの間に1点", score_text(WORDING, "ground_out", 1))
        self.assertEqual("押し出し四球で1点", score_text(WORDING, "walk", 1))
        self.assertEqual("適時二塁打で3点", score_text(WORDING, "double", 3))
        # 暴投（1点）→ 暴投。点はあとに1回だけ
        self.assertEqual("暴投で1点", wild_pitch_text(WORDING, "wp", 1))
        self.assertEqual("捕逸", wild_pitch_text(WORDING, "pb", 0))

    def test_tactics_have_no_nested_brackets(self):
        text, success = tactic_text(WORDING, "hit_and_run", "line_drive_double_play")
        self.assertEqual(("エンドラン失敗：飛球で併殺（走者戻れず）", False), (text, success))
        self.assertTrue(tactic_text(WORDING, "hit_and_run", "single")[1])
        self.assertNotIn("追い込まれて打つ", tactic_text(WORDING, "bunt", "foul")[0])

    def test_double_play_is_written_with_the_batting_school_and_batter(self):
        row = {"team1_id": "A", "team2_id": "B", "team1_score": 0, "team2_score": 0, "status": "completed"}
        detail = {"inning_scores": [{"inning": 1, "half": "top", "runs": 0, "plate_appearances": 3},
                                    {"inning": 1, "half": "bottom", "runs": 0, "plate_appearances": 3}],
                  "highlights": [["D", 1, "t", "PA"]]}
        names = {"PA": "山田"}
        out = match_detail(row, detail, lambda sid: sid + "高",
                           lambda sid: {pid: type("P", (), {"display_name": n}) for pid, n in names.items()})
        dp = out["highlights"][0]
        self.assertEqual(("A高", "山田", "併殺打"), (dp["school_name"], dp["player_name"], dp["text"]))


class ChangeTests(unittest.TestCase):
    def test_batting_order_of_the_next_batter(self):
        # 1回表3人・1回裏4人・2回表5人：7打席目は1回裏の4人目＝裏の4番、8打席目は2回表の先頭＝表の4番
        orders = plate_appearance_orders([{"half": "top", "plate_appearances": 3},
                                          {"half": "bottom", "plate_appearances": 4},
                                          {"half": "top", "plate_appearances": 5}])
        self.assertEqual((4, 4, 8), (orders[7], orders[8], orders[12]))

    def test_same_moment_changes_are_one_box_and_obvious_exits_are_hidden(self):
        def person(pid):
            return {"player_id": pid, "name": pid}
        base = {"inning": 7, "half": "表", "next_plate_appearance_no": 40, "school_id": "A",
                "school_name": "A高", "moment": "7回表・3番打者の前"}
        changes = [
            {**base, "outgoing": person("X"), "incoming": person("Y"), "fully_exited": [person("X")]},
            {**base, "batting_changes": [{"outgoing": person("D"), "incoming": person("E")}],
             "fully_exited": [person("D"), person("Z")]},
            {**base, "next_plate_appearance_no": 41, "outgoing": person("Q"), "incoming": person("R")},
        ]
        groups = group_changes(changes)
        self.assertEqual([2, 1], [len(group["changes"]) for group in groups])
        # 打順の交代で退いた X・D は出さず、交代の行に出ない Z だけ
        self.assertEqual(["Z"], [p["player_id"] for p in groups[0]["fully_exited"]])


class ProgressOrderTests(unittest.TestCase):
    """経過では、交代はその回の出来事のあとにまとめる（要点は打席の番号を持たず、暴投・盗塁と
    交代の前後は分からないため）。出来事どうしは記録の順のまま。"""

    def test_changes_come_after_the_events_of_their_half(self):
        from unittest.mock import patch
        from phase2_engine.screen import competition_views as cv
        row = {"team1_id": "A", "team2_id": "B", "team1_score": 2, "team2_score": 0, "status": "completed"}
        detail = {"inning_scores": [{"inning": 7, "half": "top", "batting_team_id": "A", "runs": 2,
                                     "plate_appearances": 6},
                                    {"inning": 7, "half": "bottom", "batting_team_id": "B", "runs": 0,
                                     "plate_appearances": 3}],
                  # 7回表：代走 PR が入ったあと、暴投で PR が生還、つづけて適時打。7回裏に併殺
                  "highlights": [["W", 7, "t", "wp", "BP", 1], ["S", 7, "t", "S4", "single", 1],
                                 ["D", 7, "b", "T1"]]}
        change = {"inning": 7, "half": "表", "next_plate_appearance_no": 2, "school_id": "A",
                  "school_name": "A高", "reason": "pinch_runner", "kind": "substitution", "label": "代走",
                  "outgoing": {"player_id": "S1", "name": "一番"}, "incoming": {"player_id": "PR", "name": "代走"},
                  "batting_order": 1, "moves": []}
        lineups = ({"A": None, "B": None}, [change], {"A": {}, "B": {}}, {"A": {}, "B": {}},
                   {"A": set(), "B": set()}, {"A": set(), "B": set()})
        with patch.object(cv, "_match_lineups", return_value=lineups):
            out = match_detail(row, detail, lambda sid: sid + "高", lambda sid: {})
        self.assertEqual(["wild_pitch", "score", "substitution", "double_play"],
                         [h["kind"] for h in out["highlights"]])
        self.assertEqual(["1−0", "2−0"], [h.get("score") for h in out["highlights"][:2]])
        self.assertEqual("7回表・2番打者の前", out["highlights"][2]["moment"])

if __name__ == "__main__":
    unittest.main()
