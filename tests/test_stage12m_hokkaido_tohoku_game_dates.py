from __future__ import annotations

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "data" / "schedules" / "2026" / "season_calendar.csv"
SOURCES = ROOT / "data" / "sources" / "phase2_sources.csv"

EXPECTED = {
    "CMP000023": ("P2SRC277", "2026-07-20", ["2026-06-25","2026-06-26","2026-06-27","2026-06-28","2026-06-29","2026-07-07","2026-07-08","2026-07-09","2026-07-10","2026-07-12","2026-07-13","2026-07-14","2026-07-18","2026-07-20"]),
    "CMP000024": ("P2SRC278", "2026-07-21", ["2026-06-20","2026-06-21","2026-06-22","2026-06-23","2026-06-24","2026-06-25","2026-06-26","2026-06-27","2026-06-28","2026-06-29","2026-07-08","2026-07-09","2026-07-10","2026-07-11","2026-07-12","2026-07-13","2026-07-14","2026-07-19","2026-07-21"]),
    "CMP000025": ("P2SRC279", "2026-07-22", ["2026-07-07","2026-07-08","2026-07-09","2026-07-13","2026-07-14","2026-07-15","2026-07-17","2026-07-18","2026-07-20","2026-07-22"]),
    "CMP000026": ("P2SRC280", "2026-07-25", ["2026-07-09","2026-07-10","2026-07-11","2026-07-13","2026-07-14","2026-07-15","2026-07-16","2026-07-17","2026-07-18","2026-07-20","2026-07-23","2026-07-25"]),
    "CMP000027": ("P2SRC281", "2026-07-21", ["2026-07-08","2026-07-09","2026-07-10","2026-07-11","2026-07-13","2026-07-14","2026-07-16","2026-07-17","2026-07-19","2026-07-21"]),
    "CMP000028": ("P2SRC282", "2026-07-27", ["2026-07-10","2026-07-11","2026-07-12","2026-07-13","2026-07-14","2026-07-17","2026-07-18","2026-07-19","2026-07-20","2026-07-23","2026-07-27"]),
    "CMP000029": ("P2SRC283", "2026-07-28", ["2026-07-11","2026-07-12","2026-07-13","2026-07-14","2026-07-15","2026-07-16","2026-07-17","2026-07-18","2026-07-19","2026-07-22","2026-07-27","2026-07-28"]),
    "CMP000030": ("P2SRC284", "2026-07-25", ["2026-07-09","2026-07-10","2026-07-11","2026-07-12","2026-07-14","2026-07-15","2026-07-18","2026-07-20","2026-07-23","2026-07-25"]),
}

class Stage12M1HokkaidoTohokuGameDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CALENDAR.open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with SOURCES.open(encoding="utf-8-sig", newline="") as f:
            cls.sources = list(csv.DictReader(f))
        cls.by_competition = {r["competition_id"]: r for r in cls.calendar}
        cls.source_ids = {r["source_id"] for r in cls.sources}

    def test_exact_eight_competitions_are_structured(self):
        self.assertEqual(8, len(EXPECTED))
        for cid, (source_id, expected_end, dates) in EXPECTED.items():
            row = self.by_competition[cid]
            with self.subTest(competition_id=cid):
                self.assertEqual(expected_end, row["end_date"])
                self.assertEqual(source_id, row["primary_source_id"])
                self.assertEqual(dates, row["game_date_list"].split(";"))
                self.assertIn(source_id, self.source_ids)

    def test_dates_are_sorted_unique_and_inside_calendar_window(self):
        for cid, (_, _, dates) in EXPECTED.items():
            row = self.by_competition[cid]
            with self.subTest(competition_id=cid):
                self.assertEqual(dates, sorted(dates))
                self.assertEqual(len(dates), len(set(dates)))
                self.assertTrue(all(row["start_date"] <= d <= row["end_date"] for d in dates))

    def test_known_non_game_days_are_not_registered(self):
        excluded = {
            "CMP000025": {"2026-07-12"},
            "CMP000026": {"2026-07-08", "2026-07-19", "2026-07-22"},
            "CMP000028": {"2026-07-25", "2026-07-26"},
            "CMP000029": {"2026-07-09", "2026-07-24", "2026-07-26"},
        }
        for cid, dates in excluded.items():
            actual = set(self.by_competition[cid]["game_date_list"].split(";"))
            self.assertTrue(actual.isdisjoint(dates), cid)

    def test_stage12m1_batch_is_present_in_current_master(self):
        # season_calendar.csv は Stage 12M-8 まで累積更新されるため、
        # Stage 12M-1 終了時点の途中件数ではなく、当該バッチが現行masterに残ることを検証する。
        summer = [r for r in self.calendar if 23 <= int(r["competition_id"].replace("CMP","")) <= 71]
        self.assertEqual(49, len(summer))
        detailed_ids = {r["competition_id"] for r in summer if r["game_date_list"]}
        self.assertTrue(set(EXPECTED).issubset(detailed_ids))

    def test_stage12m1_total_actual_game_days(self):
        self.assertEqual(98, sum(len(v[2]) for v in EXPECTED.values()))

if __name__ == "__main__":
    unittest.main()
