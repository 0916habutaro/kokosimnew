"""能力ランキングの画面（phase2_engine/screen/ability_rankings.py）。学校はすべて架空。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from phase2_engine.screen import ability_rankings as ar
from phase2_engine.screen.data import GameScreenData


ROOT = Path(__file__).resolve().parents[1]


def team(overall, batting=50.0, pitching=50.0, defense=50.0, running=50.0):
    return {"overall": overall, "batting": batting, "pitching": pitching,
            "defense": defense, "running": running}


class TeamRowTests(unittest.TestCase):
    def test_overall_order_and_ties_by_school_id(self):
        rows = ar.team_rows({"S3": team(60.0), "S1": team(70.0), "S2": team(60.0)})
        self.assertEqual(["S1", "S2", "S3"], [r["school_id"] for r in rows])
        self.assertEqual([1, 2, 3], [r["place"] for r in rows])

    def test_sort_by_batting(self):
        rows = ar.team_rows({"S1": team(70.0, batting=40.0), "S2": team(60.0, batting=65.0)},
                            sort_key="batting")
        self.assertEqual(["S2", "S1"], [r["school_id"] for r in rows])

    def test_schools_without_abilities_are_left_out(self):
        # 部員が9人に満たない学校は能力が None
        rows = ar.team_rows({"S1": team(70.0), "S2": None})
        self.assertEqual(["S1"], [r["school_id"] for r in rows])


class ReputationGapTests(unittest.TestCase):
    def setUp(self):
        # 300校：評判は S000 が1位…、総合は逆に S299 が1位…
        ids = [f"S{i:03d}" for i in range(300)]
        self.reputation = {sid: 300.0 - i for i, sid in enumerate(ids)}
        self.overall = {sid: float(i) for i, sid in enumerate(ids)}
        # 評判100位（S099）を総合10位に、評判10位（S009）を総合300位にする
        self.overall["S099"], self.overall["S290"] = self.overall["S290"], self.overall["S099"]
        self.overall["S009"], self.overall["S000"] = self.overall["S000"], self.overall["S009"]

    def test_dark_horse_and_underperformer(self):
        gap = ar.reputation_gap(self.reputation, self.overall, min_places=50)
        horse = {r["school_id"]: r for r in gap["dark_horse"]}
        self.assertEqual((100, 10, 90), (horse["S099"]["reputation_place"],
                                         horse["S099"]["overall_place"], horse["S099"]["gap"]))
        under = {r["school_id"]: r for r in gap["underperformer"]}
        self.assertEqual((10, 300), (under["S009"]["reputation_place"], under["S009"]["overall_place"]))
        # 差の大きい順
        gaps = [r["gap"] for r in gap["dark_horse"]]
        self.assertEqual(sorted(gaps, reverse=True), gaps)

    def test_small_gap_is_in_neither(self):
        gap = ar.reputation_gap({"S1": 3.0, "S2": 2.0, "S3": 1.0}, {"S1": 1.0, "S2": 2.0, "S3": 3.0},
                                min_places=3)
        self.assertEqual({"dark_horse": [], "underperformer": []}, gap)


class PrefectureStrengthTests(unittest.TestCase):
    def test_average_of_top_n_and_small_prefectures(self):
        overall = {"A1": 70.0, "A2": 60.0, "A3": 10.0, "B1": 50.0}
        prefecture = {"A1": "90", "A2": "90", "A3": "90", "B1": "91"}
        rows = ar.prefecture_strength(overall, prefecture.get, top_n=2)
        self.assertEqual(["90", "91"], [r["prefecture_code"] for r in rows])
        self.assertEqual((65.0, 2, "A1", 70.0), (rows[0]["average"], rows[0]["count"],
                                                 rows[0]["top_school_id"], rows[0]["top_overall"]))
        # 2校に満たない県はある学校だけの平均
        self.assertEqual((50.0, 1), (rows[1]["average"], rows[1]["count"]))


class ScreenDataTests(unittest.TestCase):
    """画面のデータ（ability_rankings）：計算中・県内の順位・大会の出場校。"""

    def screen(self, abilities, ready=True, competitions=()):
        data = GameScreenData.__new__(GameScreenData)
        data.config_root = ROOT / "config"
        repo = SimpleNamespace(
            schools={"S1": {"prefecture_code": "90"}, "S2": {"prefecture_code": "91"},
                     "S3": {"prefecture_code": "90"}},
            data_dir=ROOT / "data")
        data.service = SimpleNamespace(repo=repo)
        data._regions = {"90": "R1", "91": "R2"}
        data.prefectures = {"90": "架空県", "91": "仮想県"}
        data.names = lambda sid, day="": sid
        data._today_members = lambda: {sid: [] for sid in repo.schools}
        data._current_year = lambda: 2030
        data.abilities = SimpleNamespace(get=lambda members, year: (abilities, ready))
        data._reputation_ranks = lambda: {"S1": "A", "S2": "B", "S3": "C"}
        data._reputation_labels = lambda: ["S", "A", "B", "C"]
        data._ranking_competitions = lambda: [dict(c) for c in competitions]
        return data

    def test_computing(self):
        out = self.screen({}, ready=False).ability_rankings()
        self.assertEqual(("computing", []), (out["status"], out["rows"]))

    def test_prefecture_place_and_national_place(self):
        data = self.screen({"S1": team(60.0), "S2": team(70.0), "S3": team(65.0)})
        out = data.ability_rankings({"prefecture": "90"})
        self.assertEqual([("S3", 1, 2), ("S1", 2, 3)],
                         [(r["school_id"], r["place"], r["national_place"]) for r in out["rows"]])

    def test_competition_entrants_and_undecided(self):
        abilities = {"S1": team(60.0), "S2": team(70.0), "S3": team(65.0)}
        competitions = [
            {"competition_id": "SUMMER", "name": "夏", "decided": False, "entrants": []},
            {"competition_id": "SPRING", "name": "春", "decided": True, "entrants": ["S1", "S3"]},
        ]
        data = self.screen(abilities, competitions=competitions)
        # 既定は出場校の決まっている大会
        out = data.ability_rankings({"team_view": "competition"})
        self.assertEqual("SPRING", out["filters"]["competition_id"])
        self.assertEqual(["S3", "S1"], [r["school_id"] for r in out["rows"]])
        out = data.ability_rankings({"team_view": "competition", "competition_id": "SUMMER"})
        self.assertEqual((False, []), (out["decided"], out["rows"]))


if __name__ == "__main__":
    unittest.main()
