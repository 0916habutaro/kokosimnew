"""夏の記念大会（回数の下一桁が0の選手権は7府県が2代表・56校。ADR-046）。

区分の大会は、もとの府県の大会の行を写してつくる（phase2_engine/commemorative.py）。
ここでは決まり（回数・区分・代表の数・組み合わせ）を確かめ、データの中身は固定しない。"""
from __future__ import annotations

import csv
from pathlib import Path
import unittest

from phase2_engine import DataRepository, commemorative
from phase2_engine.national_day_plan import match_dates, plan_for
from phase2_engine.paths import resolve_data_file
from phase2_engine.season_catalog import season_competitions
from phase2_engine.tournament_runtime import MainTournamentRuntimeState

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = commemorative.load_config(ROOT / "config")
RULE = CONFIG["championship"]
LOCAL = {"competition_type": "summer_local_qualifier", "competition_name": "第108回全国高等学校野球選手権テスト大会"}


def _rows(name):
    with resolve_data_file(DATA, name).open(encoding="utf-8-sig", newline="") as handle:
        return commemorative.expand_rows(name, csv.DictReader(handle), DATA)


class EditionTests(unittest.TestCase):
    def test_editions_110_and_120_split_but_115_does_not(self):
        # ひな形の地方大会は第108回（2026年度）
        found = {108 + offset: commemorative.is_split_year(CONFIG, LOCAL, offset) for offset in (1, 2, 3, 7, 12)}
        self.assertEqual({109: False, 110: True, 111: False, 115: False, 120: True}, found)


class SeasonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.competitions = _rows("competitions.csv")
        cls.calendars = {row["competition_id"]: row for row in _rows("season_calendar.csv")}

    def locals_in(self, year):
        season = season_competitions(self.competitions, self.calendars, year, CONFIG)
        rows = {row["competition_id"]: row for row in self.competitions}
        return season, [cid for cid in season if rows[cid]["competition_type"] == "summer_local_qualifier"]

    def test_commemorative_year_has_two_locals_in_each_split_prefecture(self):
        normal_season, normal = self.locals_in(2027)
        season, split = self.locals_in(2028)
        rows = {row["competition_id"]: row for row in self.competitions}
        self.assertEqual(RULE["team_count"], len(split))
        self.assertEqual(len(normal) + len(RULE["split_prefectures"]), len(split))
        for prefecture, districts in RULE["split_prefectures"].items():
            names = [season[cid].display_name for cid in split if rows[cid]["prefecture_code"] == prefecture]
            self.assertEqual([f"第110回全国高等学校野球選手権記念{d}大会" for d in districts], names)
        self.assertEqual("第110回全国高等学校野球選手権記念大会", season["CMP000002"].display_name)
        # 区分の大会は記念大会の年だけ
        self.assertFalse(any(rows[cid].get(commemorative.PARENT_KEY) for cid in normal))
        _, after = self.locals_in(2029)
        self.assertEqual(sorted(normal), sorted(after))

    def test_each_split_competition_has_its_rules(self):
        parents = commemorative.split_parents(DATA)
        for name, column in (("season_calendar.csv", "competition_id"), ("competition_stages.csv", "competition_id"),
                             ("qualification_rules.csv", "source_competition_id"),
                             ("competition_seed_rules.csv", "destination_competition_id")):
            rows = _rows(name)
            for parent, entry in parents.items():
                count = sum(row[column] == parent for row in rows)
                for child in entry["children"]:
                    self.assertEqual(count, sum(row[column] == child["competition_id"] for row in rows), (name, child))

    def test_rules_from_competitions_not_held_are_dropped(self):
        repo = DataRepository(DATA)
        parent, entry = next(iter(commemorative.split_parents(DATA).items()))
        child = entry["children"][0]["competition_id"]
        self.assertTrue(commemorative.unused_source(parent, [child], repo.competitions))
        self.assertTrue(commemorative.unused_source(child, [parent], repo.competitions))
        self.assertFalse(commemorative.unused_source(child, [child], repo.competitions))
        self.assertFalse(commemorative.unused_source("CMP000002", [], repo.competitions))


class SchoolSplitTests(unittest.TestCase):
    def test_schools_go_to_the_district_in_the_table_once(self):
        repo = DataRepository(DATA)
        with resolve_data_file(DATA, RULE["split_data"]).open(encoding="utf-8-sig", newline="") as handle:
            table = list(csv.DictReader(handle))
        for parent, entry in commemorative.split_parents(DATA).items():
            whole = repo.area_school_ids[("2026", entry["area"])]
            parts = [repo.area_school_ids[("2026", child["area"])] for child in entry["children"]]
            # 府県のどの学校も、どちらか1つの区分の大会に出る（連合チームも区分の学校どうしで組む）
            self.assertEqual(whole, parts[0] | parts[1])
            self.assertFalse(parts[0] & parts[1])
            for child, members in zip(entry["children"], parts):
                expected = {row["school_id"] for row in table
                            if row["prefecture_code"] == entry["prefecture"] and row["district_2018"] == child["district"]}
                self.assertEqual(expected, members)


class KoshienTests(unittest.TestCase):
    def test_56_schools_play_24_first_round_games(self):
        main = MainTournamentRuntimeState.create(
            competition_id="C2", reference_year=2028, generation_seed=1, stage_id="MAIN",
            entrants=[f"S{i:02d}" for i in range(56)], bye_layout="paired")
        games = [sum(not main.matches[m].is_bye for m in main.match_ids_by_round[r])
                 for r in range(1, main.total_rounds + 1)]
        self.assertEqual([24, 16, 8, 4, 2, 1], games)
        plan = plan_for(DATA, "national_championship", 56)
        self.assertEqual(55, len(match_dates(plan, main, [f"2028-08-{day:02d}" for day in range(3, 18)])))


if __name__ == "__main__":
    unittest.main()
