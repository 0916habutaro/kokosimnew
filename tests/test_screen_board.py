"""試合の画面の得点板の欄（行わなかった回・x・サヨナラ。competition_views.board_cells）。"""
from __future__ import annotations

import unittest

from phase2_engine.screen.competition_views import board_cells


class BoardTests(unittest.TestCase):
    def test_columns_are_only_the_innings_played(self):
        called = board_cells([0, 1, 0, 2, 0] + [None] * 4, [3, 0, 4, 1, 3] + [None] * 4, home_won=True)
        self.assertEqual((5, 5), (len(called[0]), len(called[1])))
        normal = board_cells([0] * 9, [1] + [0] * 8, home_won=False)
        self.assertEqual(9, len(normal[0]))
        extra = board_cells([0] * 10, [0] * 9 + [1], home_won=True)
        self.assertEqual(10, len(extra[0]))

    def test_walk_off_runs_get_x(self):
        top, bottom = board_cells([0] * 9, [0] * 8 + [2], home_won=True)
        self.assertEqual("2x", bottom[-1])

    def test_called_win_with_three_outs_in_the_last_bottom_has_no_x(self):
        # 後攻が9−0で迎えた5回裏に1点を足して10−0、3アウトでコールド：サヨナラではない
        top, bottom = board_cells([0] * 5 + [None] * 4, [3, 2, 2, 2, 1] + [None] * 4, home_won=True)
        self.assertEqual("1", bottom[-1])
        # 7−7 で迎えた7回裏に7点を取り、3アウトまで行ってコールド：サヨナラの x は付けない
        top, bottom = board_cells([1, 1, 1, 1, 1, 1, 1], [0, 0, 0, 0, 0, 7, 7], home_won=True, called=True)
        self.assertEqual("7", bottom[-1])
        # 同点で迎えた裏に勝ち越せばサヨナラ
        top, bottom = board_cells([1, 0, 0, 0, 0, 0, 0, 0, 1], [0, 0, 1, 0, 0, 0, 0, 1, 1], home_won=True)
        self.assertEqual("1x", bottom[-1])

    def test_home_does_not_bat_in_the_last_inning(self):
        top, bottom = board_cells([0] * 9, [1] + [0] * 7 + [None], home_won=True)
        self.assertEqual(("0", "x"), (top[-1], bottom[-1]))
        # 5回コールドで後攻が5回裏を行わない
        top, bottom = board_cells([0, 0, 0, 0, 0] + [None] * 4, [5, 3, 2, 0, None] + [None] * 4, home_won=True)
        self.assertEqual(["5", "3", "2", "0", "x"], bottom)


if __name__ == "__main__":
    unittest.main()
