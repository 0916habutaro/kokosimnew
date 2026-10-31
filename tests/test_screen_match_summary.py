"""試合の結果の要約（コールド・勝利投手・敗戦投手・本塁打）。

架空の試合の経過（保存済みの記録と同じ形）だけで確かめる。学校・選手は架空。
"""
from __future__ import annotations

import unittest

from phase2_engine.screen.match_summary import (
    called_inning,
    called_label,
    home_runs,
    pitchers_of_record,
)

MERCY = [[5, 10], [7, 7]]


def S(inning, half, runs, batter="x", event="single"):
    return ["S", inning, half, batter, event, runs]


def P(inning, half, school, pitcher):
    return ["P", inning, half, school, pitcher]


def game(highlights, pitchers, *, innings=9, last_inning=None):
    """A（先攻）対 B（後攻）。pitchers は (学校, 投手, アウト, 失点)。"""
    score = {"A": 0, "B": 0}
    for item in highlights:
        if item[0] == "S":
            score["A" if item[2] == "t" else "B"] += item[5]
    halves = []
    for inning in range(1, innings + 1):
        halves.append({"inning": inning, "half": "top", "batting_team_id": "A", "was_played": True})
        halves.append({"inning": inning, "half": "bottom", "batting_team_id": "B", "was_played": True})
    return {
        "team1_id": "A", "team2_id": "B",
        "team1_score": score["A"], "team2_score": score["B"],
        "winner_id": "A" if score["A"] > score["B"] else "B" if score["B"] > score["A"] else "",
        "last_inning": last_inning or innings,
        "inning_scores": halves,
        "highlights": highlights,
        "pitcher_stats": [
            {"school_id": school, "player_id": pid, "outs_recorded": outs, "runs_allowed": runs}
            for school, pid, outs, runs in pitchers
        ],
    }


class PitchersOfRecordTests(unittest.TestCase):
    def record(self, detail):
        out = pitchers_of_record(detail)
        return out and (out["win"][1], out["loss"][1])

    def test_complete_game(self):
        detail = game([S(1, "b", 1), S(5, "t", 2)], [("A", "a1", 27, 1), ("B", "b1", 27, 2)])
        self.assertEqual(("a1", "b1"), self.record(detail))

    def test_starter_short_of_five_innings_gives_win_to_most_effective_reliever(self):
        detail = game(
            [S(3, "t", 2), P(5, "b", "A", "a2"), P(9, "b", "A", "a3")],
            [("A", "a1", 12, 0), ("A", "a2", 12, 0), ("A", "a3", 3, 0), ("B", "b1", 27, 2)],
        )
        self.assertEqual(("a2", "b1"), self.record(detail))

    def test_starter_with_five_innings_keeps_the_win(self):
        detail = game(
            [S(3, "t", 2), P(6, "b", "A", "a2")],
            [("A", "a1", 15, 0), ("A", "a2", 12, 0), ("B", "b1", 27, 2)],
        )
        self.assertEqual(("a1", "b1"), self.record(detail))

    def test_comeback_win_goes_to_pitcher_of_record_at_go_ahead_run(self):
        # A が先制、B が逆転（a1 が負け投手になりかけ）、A が再逆転して勝つ
        detail = game(
            [S(1, "t", 1), S(6, "b", 2), P(7, "t", "B", "b2"), P(7, "b", "A", "a2"), S(8, "t", 2)],
            [("A", "a1", 18, 2), ("A", "a2", 9, 0), ("B", "b1", 18, 1), ("B", "b2", 9, 2)],
        )
        self.assertEqual(("a2", "b2"), self.record(detail))

    def test_starter_leaving_in_a_tie_does_not_get_the_win(self):
        detail = game(
            [S(2, "t", 1), S(4, "b", 1), P(7, "b", "A", "a2"), S(8, "t", 1)],
            [("A", "a1", 18, 1), ("A", "a2", 9, 0), ("B", "b1", 27, 2)],
        )
        self.assertEqual(("a2", "b1"), self.record(detail))

    def test_go_ahead_run_by_inherited_runner_loses_for_departed_pitcher(self):
        # 0-0 の5回表、b1 が走者を2人残して降り、b2 が3ランを打たれる
        detail = game(
            [P(5, "t", "B", "b2"), S(5, "t", 3, event="home_run")],
            [("A", "a1", 27, 0), ("B", "b1", 13, 2), ("B", "b2", 14, 1)],
        )
        self.assertEqual(("a1", "b1"), self.record(detail))

    def test_home_team_walk_off(self):
        detail = game(
            [S(1, "t", 1), S(9, "b", 2)],
            [("A", "a1", 26, 2), ("B", "b1", 27, 1)],
        )
        self.assertEqual(("b1", "a1"), self.record(detail))

    def test_five_inning_game_needs_four_innings_from_starter(self):
        detail = game(
            [S(1, "t", 10)],
            [("A", "a1", 12, 0), ("A", "a2", 3, 0), ("B", "b1", 15, 10)],
            innings=5,
        )
        self.assertEqual(("a1", "b1"), self.record(detail))

    def test_runs_that_do_not_add_up_are_not_decided(self):
        detail = game([S(1, "t", 1)], [("A", "a1", 27, 0), ("B", "b1", 27, 0)])
        self.assertIsNone(pitchers_of_record(detail))
        self.assertIsNone(pitchers_of_record(None))
        tied = game([S(1, "t", 1), S(1, "b", 1)], [("A", "a1", 27, 1), ("B", "b1", 27, 1)])
        self.assertIsNone(pitchers_of_record(tied))


class CalledGameTests(unittest.TestCase):
    def test_called_by_mercy_rule(self):
        five = {"inning_scores": [{"inning": 5}], "team1_score": 12, "team2_score": 1}
        self.assertEqual(5, called_inning(five, MERCY))
        self.assertEqual("5回コールド", called_label(five, MERCY))
        # 履歴に書き出した記録の形（学校IDは team1_id、終わった回は半イニングの記録から）
        seven = {"inning_scores": [{"inning": 6}, {"inning": 7}], "team1_id": "A", "team1_score": 0, "team2_score": 8}
        self.assertEqual("7回コールド", called_label(seven, MERCY))
        # 9回まで行った試合・点差が足りない試合・記録がない試合はコールドではない
        self.assertEqual("", called_label({"inning_scores": [{"inning": 9}], "team1_score": 15, "team2_score": 0}, MERCY))
        self.assertEqual("", called_label({"inning_scores": [{"inning": 6}], "team1_score": 5, "team2_score": 0}, MERCY))
        self.assertEqual("", called_label(None, MERCY))


class HomeRunTests(unittest.TestCase):
    def test_home_runs_in_order(self):
        detail = game(
            [S(2, "b", 1, "b9", "home_run"), S(3, "t", 2, "a4", "double"), S(8, "t", 2, "a3", "home_run")],
            [("A", "a1", 27, 1), ("B", "b1", 27, 4)],
        )
        self.assertEqual(
            [("B", "b9", 2), ("A", "a3", 8)],
            [(h["school_id"], h["player_id"], h["inning"]) for h in home_runs(detail)],
        )


if __name__ == "__main__":
    unittest.main()
