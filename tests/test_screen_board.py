"""試合の画面の得点板の欄（行わなかった回・x。competition_views.board_cells と bottom_ended_early）。

最終回の裏は、省略なら「x」、攻撃の途中で終わったらその回の得点に「x」、3アウトまで行ったら得点だけ。"""
from __future__ import annotations

import unittest

from phase2_engine.screen.competition_views import board_cells, bottom_ended_early


def detail(bottoms: int, home_outs_against: int) -> dict:
    """後攻 H が裏を ``bottoms`` 回行い、裏を守った先攻 A の投手のアウトの合計が ``home_outs_against``。"""
    return {
        "inning_scores": [{"inning": n, "half": half, "batting_team_id": team, "runs": 0, "was_played": True}
                          for n in range(1, bottoms + 1) for half, team in (("top", "A"), ("bottom", "H"))],
        "pitcher_stats": [{"school_id": "A", "outs_recorded": home_outs_against},
                          {"school_id": "H", "outs_recorded": 3 * bottoms}],
    }


class BoardTests(unittest.TestCase):
    def test_columns_are_only_the_innings_played(self):
        called = board_cells([0, 1, 0, 2, 0] + [None] * 4, [3, 0, 4, 1, 3] + [None] * 4)
        self.assertEqual((5, 5), (len(called[0]), len(called[1])))
        self.assertEqual(9, len(board_cells([0] * 9, [1] + [0] * 8)[0]))
        self.assertEqual(10, len(board_cells([0] * 10, [0] * 9 + [1], ended_early=True)[0]))

    def test_last_bottom_ended_in_the_middle_gets_x_on_its_runs(self):
        # 5回裏に9−0から1点で10−0、7回裏に7−7から7点、0−3から10点、9回裏のサヨナラ
        self.assertEqual("1x", board_cells([0] * 5, [3, 2, 2, 2, 1], ended_early=True)[1][-1])
        self.assertEqual("7x", board_cells([1] * 7, [0, 0, 0, 0, 0, 7, 7], ended_early=True)[1][-1])
        self.assertEqual("10x", board_cells([0, 0, 3, 0, 0, 0, 0], [0] * 6 + [10], ended_early=True)[1][-1])
        self.assertEqual("2x", board_cells([0] * 9, [0] * 8 + [2], ended_early=True)[1][-1])

    def test_skipped_and_completed_last_bottoms(self):
        # 7回表終了時に後攻が14−7でリード：裏は省略して x
        top, bottom = board_cells([1] * 7, [2] * 6 + [None])
        self.assertEqual(("1", "x"), (top[-1], bottom[-1]))
        # 7回表終了時に先攻が14−7でリードし、裏は無得点で3アウト：0
        self.assertEqual("0", board_cells([2] * 7, [1] * 6 + [0])[1][-1])

    def test_ended_early_is_read_from_the_outs_of_the_bottom_halves(self):
        # 裏を7回行い、裏のアウトが 3×6＋2：7回裏は攻撃の途中で終わった
        self.assertTrue(bottom_ended_early(detail(7, 20), "H"))
        self.assertFalse(bottom_ended_early(detail(7, 21), "H"))
        # 投手の記録がない古い記録では判別しない（x を付けない）
        self.assertFalse(bottom_ended_early({"inning_scores": detail(7, 20)["inning_scores"]}, "H"))


if __name__ == "__main__":
    unittest.main()
