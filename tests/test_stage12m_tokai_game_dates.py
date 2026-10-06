from __future__ import annotations

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "data" / "schedules" / "2026" / "season_calendar.csv"
SOURCES = ROOT / "data" / "sources" / "phase2_sources.csv"

EXPECTED = {
    "CMP000042": ("P2SRC299", ["2026-07-04","2026-07-05","2026-07-11","2026-07-12","2026-07-18","2026-07-19","2026-07-21","2026-07-23","2026-07-25","2026-07-27"]),
    "CMP000043": ("P2SRC300", ["2026-06-28","2026-07-04","2026-07-05","2026-07-07","2026-07-08","2026-07-10","2026-07-11","2026-07-12","2026-07-18","2026-07-19","2026-07-21","2026-07-23","2026-07-27","2026-07-28"]),
    "CMP000044": ("P2SRC301", ["2026-07-04","2026-07-05","2026-07-11","2026-07-12","2026-07-18","2026-07-19","2026-07-20","2026-07-22","2026-07-23","2026-07-26","2026-07-28"]),
    "CMP000045": ("P2SRC302", ["2026-07-04","2026-07-05","2026-07-08","2026-07-11","2026-07-12","2026-07-18","2026-07-19","2026-07-21","2026-07-23","2026-07-25","2026-07-27"]),
}

class Stage12M4TokaiGameDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CALENDAR.open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with SOURCES.open(encoding="utf-8-sig", newline="") as f:
            cls.sources = list(csv.DictReader(f))
        cls.by = {r["competition_id"]: r for r in cls.calendar}
        cls.source_ids = {r["source_id"] for r in cls.sources}

    def test_exact_four_competitions(self):
        self.assertEqual(4, len(EXPECTED))
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
            "CMP000042": {"2026-06-28"},
            "CMP000043": {"2026-06-27"},
            "CMP000045": {"2026-07-03"},
        }
        for cid, dates in excluded.items():
            actual = set(self.by[cid]["game_date_list"].split(";"))
            self.assertTrue(actual.isdisjoint(dates), cid)

    def test_partial_cancel_days_with_completed_games_included(self):
        self.assertIn("2026-06-28", self.by["CMP000043"]["game_date_list"].split(";"))
        self.assertIn("2026-07-18", self.by["CMP000044"]["game_date_list"].split(";"))
        self.assertIn("2026-07-04", self.by["CMP000045"]["game_date_list"].split(";"))
        self.assertIn("2026-07-05", self.by["CMP000045"]["game_date_list"].split(";"))

    def test_stage12m4_progress_counts(self):
        summer = [r for r in self.calendar if 23 <= int(r["competition_id"].replace("CMP","")) <= 71]
        self.assertEqual(49, len(summer))
        detailed = [r for r in summer if r["game_date_list"]]
        empty = [r for r in summer if not r["game_date_list"]]
        self.assertEqual(26, len(detailed))
        self.assertEqual(23, len(empty))
        self.assertEqual(138, sum(bool(r["game_date_list"]) for r in self.calendar))
        self.assertEqual(24, sum(not bool(r["game_date_list"]) for r in self.calendar))

    def test_stage12m4_batch_and_cumulative_game_day_counts(self):
        self.assertEqual(46, sum(len(v[1]) for v in EXPECTED.values()))
        summer = [r for r in self.calendar if 23 <= int(r["competition_id"].replace("CMP","")) <= 71]
        self.assertEqual(320, sum(len(r["game_date_list"].split(";")) for r in summer if r["game_date_list"]))

if __name__ == "__main__":
    unittest.main()
