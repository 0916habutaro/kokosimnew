"""夏の記念大会の2つの区分を1つの府県として扱う（評判・県の強さ・記録・画面。ADR-046）。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from game_core.annual_reputation import koshien_prefecture_games
from phase2_engine import DataRepository, commemorative
from phase2_engine.screen import rankings, record_filters
from phase2_engine.screen.data import GameScreenData
from phase2_engine.screen.school_names import prefecture_names

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = commemorative.load_config(ROOT / "config")


class KoshienPrefectureGamesTests(unittest.TestCase):
    def test_two_representatives_of_one_prefecture_are_not_a_prefecture_game(self):
        # 架空の学校：N1・S1 は同じ府県（90）の2つの区分の代表、X1 はほかの県（91）
        prefecture = {"N1": "90", "S1": "90", "X1": "91"}
        repo = SimpleNamespace(team=lambda sid: SimpleNamespace(prefecture_code=prefecture[sid]))
        season = SimpleNamespace(repo=repo)
        matches = [SimpleNamespace(winner_id="N1", loser_id="S1"),
                   SimpleNamespace(winner_id="N1", loser_id="X1")]
        self.assertEqual({"90": [1, 1], "91": [0, 1]}, koshien_prefecture_games(season, matches))


class RecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.parent, cls.entry = next(iter(commemorative.split_parents(DATA).items()))
        cls.children = [child["competition_id"] for child in cls.entry["children"]]

    def test_split_competitions_are_held_only_in_commemorative_years(self):
        parents = commemorative.split_parents(DATA)
        child = self.repo.competitions[self.children[0]]
        parent = self.repo.competitions[self.parent]
        self.assertFalse(commemorative.held_in(CONFIG, child, range(2026, 2028), parents))
        self.assertTrue(commemorative.held_in(CONFIG, child, range(2026, 2029), parents))
        self.assertFalse(commemorative.held_in(CONFIG, parent, [2028], parents))
        self.assertTrue(commemorative.held_in(CONFIG, parent, [2028, 2029], parents))

    def test_record_filters_list_split_competitions_when_held(self):
        def catalog(held):
            return {c["competition_id"]: c for c in record_filters.build_catalog(
                self.repo.competitions, [], lambda c: c.get("competition_level", ""),
                lambda cid, name: name, held=held)}
        self.assertNotIn(self.children[0], catalog(lambda c: not c.get(commemorative.PARENT_KEY)))
        found = catalog(lambda c: True)
        # 区分の大会は都道府県の大会（その府県で絞ると出る）で、地図のマスは分けない
        for cid in self.children:
            self.assertEqual([self.entry["prefecture"]], found[cid]["prefectures"])
            self.assertFalse(found[cid]["split"])

    def test_district_schools_count_for_their_prefecture(self):
        data = GameScreenData.__new__(GameScreenData)
        data.service = SimpleNamespace(repo=self.repo)
        data.config_root = ROOT / "config"
        data.prefectures = prefecture_names(DATA)
        tile_of, _ = data._school_tiles()
        members = [next(iter(self.repo.area_school_ids[("2026", child["area"])]))
                   for child in self.entry["children"]]
        self.assertEqual({self.entry["prefecture"]}, {tile_of(sid) for sid in members})
        totals = {sid: rankings.finish(rankings.empty()) for sid in members}
        for total in totals.values():
            total["summer"]["appearances"] = 1
        by_prefecture = rankings.prefecture_totals(totals, tile_of)
        self.assertEqual(2, rankings.finish(by_prefecture[self.entry["prefecture"]])["summer"]["appearances"])


if __name__ == "__main__":
    unittest.main()
