"""大会・日程・出典の基礎データの整合（件数や日付そのものは固定しない）。

全大会に日程が1行ずつあり、試合日は期間の中で重ならずに並び、日程の出典が出典表にあり、
大会のつながり（地区・甲子園・神宮への進出）がすべて解決することを確かめる。
"""
from __future__ import annotations

import csv
import unittest
from pathlib import Path

from phase2_engine import DataRepository, SeasonOrchestrator

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class DataIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.competitions = read(DATA / "competitions" / "competitions.csv")
        cls.calendar = read(DATA / "schedules" / "2026" / "season_calendar.csv")
        cls.sources = {row["source_id"] for row in read(DATA / "sources" / "phase2_sources.csv")}
        cls.qualification = read(DATA / "competitions" / "qualification_rules.csv")
        cls.repo = DataRepository(DATA)
        cls.season = SeasonOrchestrator(cls.repo, DATA).run_structural_season(2026, 2026100501)

    def test_every_competition_has_one_official_calendar_row(self):
        ids = [row["competition_id"] for row in self.calendar]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({row["competition_id"] for row in self.competitions}, set(ids))
        self.assertTrue(all(row["calendar_status"] == "official_schedule" for row in self.calendar))

    def test_game_dates_are_sorted_unique_and_inside_the_period(self):
        for row in self.calendar:
            dates = [day for day in row["game_date_list"].split(";") if day]
            with self.subTest(competition_id=row["competition_id"]):
                self.assertLessEqual(row["start_date"], row["end_date"])
                self.assertEqual(dates, sorted(set(dates)))
                self.assertTrue(all(row["start_date"] <= day <= row["end_date"] for day in dates))
                if row["draw_date"]:
                    self.assertLessEqual(row["draw_date"], row["start_date"])

    def test_calendar_sources_exist(self):
        for row in self.calendar:
            with self.subTest(competition_id=row["competition_id"]):
                self.assertIn(row["primary_source_id"], self.sources)

    def test_every_summer_qualifier_sends_its_winner_to_koshien(self):
        summer = {row["competition_id"] for row in self.competitions
                  if row["competition_type"] == "summer_local_qualifier"}
        koshien = {row["competition_id"] for row in self.competitions
                   if row["competition_type"] == "national_championship"}
        rules = [row for row in self.qualification
                 if row["destination_competition_id"] in koshien]
        self.assertEqual(summer, {row["source_competition_id"] for row in rules})
        self.assertTrue(all(row["source_result"] == "winner" for row in rules))

    def test_structural_season_runs_every_competition_and_resolves_every_link(self):
        season = self.season
        self.assertEqual(set(self.repo.competitions), set(season.competition_runs))
        self.assertTrue(season.qualification_resolutions)
        self.assertTrue(all(r.status == "PASS" for r in season.qualification_resolutions))
        self.assertFalse(any(r.date_status == "FAIL" for r in season.qualification_resolutions))
        self.assertTrue(all(r.status == "PASS" for r in season.access_resolutions))
        self.assertEqual([], season.calendar_gaps)
        self.assertEqual([], season.internal_structure_gaps)
        self.assertEqual([], season.regional_bridge_gaps)
        self.assertEqual([], season.warnings)


if __name__ == "__main__":
    unittest.main()
