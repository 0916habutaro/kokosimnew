from __future__ import annotations

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "data" / "schedules" / "2026" / "season_calendar.csv"
SOURCES = ROOT / "data" / "sources" / "phase2_sources.csv"

EXPECTED = {
    "CMP000064": ("P2SRC318", ["2026-07-06","2026-07-07","2026-07-08","2026-07-09","2026-07-10","2026-07-11","2026-07-12","2026-07-13","2026-07-14","2026-07-15","2026-07-16","2026-07-17","2026-07-18","2026-07-20","2026-07-21","2026-07-23","2026-07-25"]),
    "CMP000065": ("P2SRC319", ["2026-07-07","2026-07-08","2026-07-09","2026-07-10","2026-07-11","2026-07-12","2026-07-13","2026-07-14","2026-07-15","2026-07-16","2026-07-18","2026-07-20","2026-07-21","2026-07-24","2026-07-26"]),
    "CMP000066": ("P2SRC320", ["2026-07-06","2026-07-07","2026-07-08","2026-07-11","2026-07-12","2026-07-13","2026-07-18","2026-07-20","2026-07-23","2026-07-25"]),
    "CMP000067": ("P2SRC321", ["2026-07-07","2026-07-08","2026-07-09","2026-07-10","2026-07-11","2026-07-12","2026-07-13","2026-07-14","2026-07-16","2026-07-17","2026-07-19","2026-07-20","2026-07-22","2026-07-24"]),
    "CMP000068": ("P2SRC322", ["2026-07-05","2026-07-06","2026-07-07","2026-07-08","2026-07-09","2026-07-10","2026-07-11","2026-07-12","2026-07-13","2026-07-14","2026-07-15","2026-07-16","2026-07-17","2026-07-18","2026-07-19","2026-07-20","2026-07-23","2026-07-25"]),
    "CMP000069": ("P2SRC323", ["2026-07-04","2026-07-05","2026-07-06","2026-07-07","2026-07-08","2026-07-09","2026-07-10","2026-07-11","2026-07-13","2026-07-14","2026-07-16","2026-07-18","2026-07-20"]),
    "CMP000070": ("P2SRC324", ["2026-07-04","2026-07-05","2026-07-06","2026-07-07","2026-07-08","2026-07-09","2026-07-10","2026-07-11","2026-07-12","2026-07-13","2026-07-14","2026-07-15","2026-07-17","2026-07-18","2026-07-19","2026-07-20","2026-07-23","2026-07-25"]),
    "CMP000071": ("P2SRC325", ["2026-06-13","2026-06-14","2026-06-20","2026-06-21","2026-06-23","2026-06-27","2026-06-28","2026-07-04","2026-07-05","2026-07-12","2026-07-13","2026-07-18","2026-07-20"]),
}

class Stage12M8KyushuOkinawaGameDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CALENDAR.open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with SOURCES.open(encoding="utf-8-sig", newline="") as f:
            cls.sources = list(csv.DictReader(f))
        cls.by = {r["competition_id"]: r for r in cls.calendar}
        cls.source_ids = {r["source_id"] for r in cls.sources}

    def test_exact_eight_competitions(self):
        self.assertEqual(8, len(EXPECTED))
        for cid, (source_id, dates) in EXPECTED.items():
            row = self.by[cid]
            with self.subTest(competition_id=cid):
                self.assertEqual(source_id, row["primary_source_id"])
                self.assertEqual(dates, row["game_date_list"].split(";"))
                self.assertIn(source_id, self.source_ids)

    def test_dates_sorted_unique_and_in_window(self):
        for cid, (_, dates) in EXPECTED.items():
            row = self.by[cid]
            self.assertEqual(dates, sorted(dates), cid)
            self.assertEqual(len(dates), len(set(dates)), cid)
            self.assertTrue(all(row["start_date"] <= d <= row["end_date"] for d in dates), cid)

    def test_known_non_game_days_excluded(self):
        excluded = {
            "CMP000064": {"2026-07-04","2026-07-05"},
            "CMP000065": {"2026-07-05"},
            "CMP000067": {"2026-07-04","2026-07-05","2026-07-06"},
        }
        for cid, dates in excluded.items():
            actual = set(self.by[cid]["game_date_list"].split(";"))
            self.assertTrue(actual.isdisjoint(dates), cid)

    def test_partial_continuation_day_with_completed_games_included(self):
        self.assertIn("2026-06-27", self.by["CMP000071"]["game_date_list"].split(";"))

    def test_stage12m8_completes_all_summer_local_competitions(self):
        summer = [r for r in self.calendar if 23 <= int(r["competition_id"].replace("CMP","")) <= 71]
        self.assertEqual(49, len(summer))
        self.assertEqual(49, sum(bool(r["game_date_list"]) for r in summer))
        self.assertEqual(0, sum(not bool(r["game_date_list"]) for r in summer))
        self.assertEqual(161, sum(bool(r["game_date_list"]) for r in self.calendar))
        self.assertEqual(1, sum(not bool(r["game_date_list"]) for r in self.calendar))

    def test_stage12m8_batch_and_cumulative_game_day_counts(self):
        self.assertEqual(118, sum(len(v[1]) for v in EXPECTED.values()))
        summer = [r for r in self.calendar if 23 <= int(r["competition_id"].replace("CMP","")) <= 71]
        self.assertEqual(629, sum(len(r["game_date_list"].split(";")) for r in summer if r["game_date_list"]))

if __name__ == "__main__":
    unittest.main()
