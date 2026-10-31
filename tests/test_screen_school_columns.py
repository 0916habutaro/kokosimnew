"""学校の画面と選手の一覧に出す能力・成績・評判・甲子園の回数をまとめる部品。

大会や名簿は読まず、小さな値だけで確かめる。校名・選手は架空。
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from phase2_engine.screen.player_views import (
    aptitude_rows,
    member_abilities,
    member_stats,
    season_stats,
)
from phase2_engine.screen.school_views import koshien_appearances, reputation_ranks


ROOT = Path(__file__).resolve().parents[1]
BANDS = json.loads(
    (ROOT / "config" / "abilities" / "ability_scale_v1.json").read_text(encoding="utf-8")
)["display_bands"]


class MemberTests(unittest.TestCase):
    def test_pitcher_and_batter_abilities(self):
        values = {"velocity_kmh": 141, "control": 82, "stamina": 55,
                  "contact": 91, "power": 45, "speed": 70, "fielding": 20}
        pitcher = member_abilities(values, "P", BANDS)
        self.assertEqual(["velocity_kmh", "control", "stamina"], list(pitcher))
        # 球速はランクを付けず km/h
        self.assertEqual({"value": 141, "rank": ""}, pitcher["velocity_kmh"])
        self.assertEqual("A", pitcher["control"]["rank"])
        batter = member_abilities(values, "SS", BANDS)
        self.assertEqual(["contact", "power", "speed", "fielding"], list(batter))
        self.assertEqual(["S", "E", "B", "G"], [v["rank"] for v in batter.values()])
        # 能力が読めないときは空
        self.assertEqual({"value": None, "rank": ""}, member_abilities(None, "C", BANDS)["contact"])

    def test_season_stats_as_numbers(self):
        details = [
            {"batter_stats": [{"player_id": "p1", "at_bats": 4, "hits": 2, "home_runs": 1}],
             "pitcher_stats": [{"player_id": "p2", "outs_recorded": 20, "earned_runs": 2}]},
            {"batter_stats": [{"player_id": "p1", "at_bats": 4, "hits": 1}],
             "pitcher_stats": [{"player_id": "p2", "outs_recorded": 7, "earned_runs": 1}]},
        ]
        batter = member_stats(season_stats(details, "p1"))
        self.assertAlmostEqual(3 / 8, batter["average"])
        self.assertEqual(1, batter["home_runs"])
        self.assertIsNone(batter["era"])
        pitcher = member_stats(season_stats(details, "p2"))
        self.assertAlmostEqual(3.0, pitcher["era"])
        self.assertEqual(27, pitcher["outs"])
        self.assertEqual(
            {"average": None, "home_runs": None, "era": None, "outs": None},
            member_stats(season_stats(details, "nobody")),
        )


class AptitudeTests(unittest.TestCase):
    def test_rows_in_position_order(self):
        rows = aptitude_rows({"SS": 95, "P": 10, "CF": 64}, {"P": "投", "SS": "遊"}, BANDS)
        self.assertEqual(["P", "SS", "CF"], [r["key"] for r in rows])
        self.assertEqual(["投", "遊", "CF"], [r["label"] for r in rows])
        self.assertEqual(["G", "S", "C"], [r["rank"] for r in rows])


class SchoolColumnTests(unittest.TestCase):
    def test_reputation_ranks_by_share(self):
        values = {f"s{i:02d}": float(i) for i in range(10)}
        ranks = reputation_ranks(values, [["A", 0.9], ["B", 0.5], ["C", 0.0]])
        self.assertEqual("A", ranks["s09"])
        self.assertEqual("B", ranks["s05"])
        self.assertEqual("C", ranks["s04"])
        self.assertEqual({}, reputation_ranks({}, [["A", 0.0]]))

    def test_koshien_appearances_add_actual_and_game(self):
        game = {"summer": {"appearances": {"x": 2}}, "spring": {"appearances": {}}}
        actual = {"summer": {"appearances": 5}, "spring": {"appearances": 1}}
        self.assertEqual({"summer": 7, "spring": 1}, koshien_appearances(actual, game, "x"))
        # 実際の記録がない学校はゲーム内の記録だけ
        self.assertEqual({"summer": 2, "spring": 0}, koshien_appearances(None, game, "x"))


if __name__ == "__main__":
    unittest.main()
