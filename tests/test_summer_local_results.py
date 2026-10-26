"""夏の地方大会の実際の試合（2021〜2025年。historical_results/summer_local.py）。"""
from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from historical_results.summer_local import (
    ALIAS_COLUMNS,
    GAME_COLUMNS,
    UNION_COLUMNS,
    finishes,
    read_games,
    validate,
)


def _game(tournament, date, top, bottom, top_score, bottom_score, **extra):
    row = dict.fromkeys(GAME_COLUMNS, "")
    row.update(
        year=tournament[:4], prefecture_code="99", tournament=tournament,
        round_label="", game_date=date, top_team=top, bottom_team=bottom,
        top_score=str(top_score), bottom_score=str(bottom_score),
        winner="top" if top_score > bottom_score else "bottom",
        result_type="decided", source_id="SRC1",
    )
    row.update(extra)
    return row


def _bracket(tournament="2024年架空大会"):
    """8校の大会。架空1が優勝、架空5が準優勝。"""
    return [
        _game(tournament, "2024-07-01", "架空1", "架空2", 5, 1),
        _game(tournament, "2024-07-01", "架空3", "架空4", 2, 3),
        _game(tournament, "2024-07-02", "架空5", "架空6", 7, 0),
        _game(tournament, "2024-07-02", "架空7", "架空8", 1, 0),
        _game(tournament, "2024-07-05", "架空1", "架空4", 4, 2),
        _game(tournament, "2024-07-05", "架空5", "架空7", 6, 5),
        _game(tournament, "2024-07-08", "架空5", "架空1", 0, 3),
    ]


class FinishTests(unittest.TestCase):
    def test_finish_counts_from_the_final(self):
        reached = finishes(_bracket())
        name = "2024年架空大会"
        self.assertEqual(1, reached[(name, "架空1")])
        self.assertEqual(2, reached[(name, "架空5")])
        self.assertEqual(4, reached[(name, "架空4")])
        self.assertEqual(4, reached[(name, "架空7")])
        self.assertEqual(8, reached[(name, "架空2")])
        self.assertEqual(8, reached[(name, "架空8")])

    def test_seeded_team_and_draw_replay(self):
        games = _bracket()
        # 架空9は2回戦から（シード）。引き分けの再試合は再試合の結果で数える
        games[4:4] = [
            _game("2024年架空大会", "2024-07-03", "架空1", "架空9", 2, 2, winner="", result_type="draw"),
            _game("2024年架空大会", "2024-07-04", "架空1", "架空9", 3, 1),
        ]
        reached = finishes(games)
        self.assertEqual(8, reached[("2024年架空大会", "架空9")])
        self.assertEqual(1, reached[("2024年架空大会", "架空1")])
        self.assertEqual(16, reached[("2024年架空大会", "架空2")])


class RepositoryDataTests(unittest.TestCase):
    def test_repository_data_is_consistent(self):
        issues = validate()
        self.assertEqual([], [str(issue) for issue in issues])

    def test_only_years_before_the_game_starts(self):
        years = {int(game["year"]) for game in read_games()}
        self.assertEqual({2021, 2022, 2023, 2024, 2025}, years)


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.master = self.root / "schools.csv"
        with self.master.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["school_id", "prefecture_code"])
            writer.writerows([["SCHX1", "99"], ["SCHX2", "99"], ["SCHX3", "98"]])
        with (self.root / "sources.csv").open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows([["source_id"], ["SRC1"]])

    def tearDown(self):
        self.tmp.cleanup()

    def _codes(self, games, aliases=()):
        with (self.root / "summer_local_games.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, GAME_COLUMNS)
            writer.writeheader()
            writer.writerows(games)
        with (self.root / "summer_local_team_aliases.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(ALIAS_COLUMNS)
            writer.writerows(aliases)
        return {issue.code for issue in validate(self.root, self.master)}

    def test_valid_bracket(self):
        games = _bracket()
        games[0]["top_school_id"] = "SCHX1"
        codes = self._codes(games, [("99", "架空1", "SCHX1", "略称")])
        # 実際の年ごとの試合数とは合わないので、それ以外は問題がない
        self.assertEqual({"GAME_COUNT"}, codes)

    def test_errors(self):
        games = _bracket()
        games[0]["top_school_id"] = "SCHX1"
        games[4]["top_school_id"] = "SCHX2"  # 同じ校名に別の学校
        games[1]["bottom_school_id"] = "SCHX3"  # 別の都道府県の学校
        games[2]["top_score"] = "0"  # 勝敗と得点が合わない
        late = _game("2026年架空大会", "2026-07-01", "架空1", "架空2", 1, 0)
        codes = self._codes(games + [late], [("99", "架空3", "SCHX1", "")])
        for code in ("AMBIGUOUS_NAME", "PREFECTURE", "SCORE", "YEAR", "NOT_USED"):
            self.assertIn(code, codes)

    def test_union_members(self):
        games = _bracket()
        games[0]["bottom_team"] = "架空2・架空10"
        with (self.root / "summer_local_union_members.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(UNION_COLUMNS)
            writer.writerows([
                ["99", "架空2・架空10", "架空2", "SCHX2"],
                ["99", "架空2・架空10", "架空11", ""],  # 構成校の名前が合わない
                ["99", "架空3・架空4", "架空3", ""],  # 試合にない連合チーム
            ])
        codes = self._codes(games)
        self.assertIn("MEMBER", codes)
        self.assertIn("UNKNOWN_TEAM", codes)

    def test_bracket_errors(self):
        games = _bracket()
        games.append(_game("2024年架空大会", "2024-07-09", "架空2", "架空4", 1, 0))
        self.assertIn("LOST_TWICE", self._codes(games))
        self.assertIn("CHAMPION", self._codes(_bracket()[:-1]))


if __name__ == "__main__":
    unittest.main()
