from __future__ import annotations

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "data" / "schedules" / "2026" / "season_calendar.csv"
SOURCES = ROOT / "data" / "sources" / "phase2_sources.csv"

EXPECTED = {
    "CMP000039": ("P2SRC293", ["2026-07-09","2026-07-10","2026-07-11","2026-07-12","2026-07-14","2026-07-15","2026-07-16","2026-07-18","2026-07-20","2026-07-22","2026-07-24"]),
    "CMP000040": ("P2SRC294", ["2026-07-04","2026-07-05","2026-07-06","2026-07-07","2026-07-08","2026-07-11","2026-07-12","2026-07-15","2026-07-18","2026-07-19","2026-07-22","2026-07-25"]),
    "CMP000041": ("P2SRC295", ["2026-07-05","2026-07-06","2026-07-07","2026-07-08","2026-07-09","2026-07-11","2026-07-12","2026-07-13","2026-07-14","2026-07-15","2026-07-17","2026-07-18","2026-07-20","2026-07-22"]),
    "CMP000046": ("P2SRC296", ["2026-07-10","2026-07-11","2026-07-12","2026-07-18","2026-07-19","2026-07-20","2026-07-23","2026-07-25"]),
    "CMP000047": ("P2SRC297", ["2026-07-09","2026-07-10","2026-07-11","2026-07-12","2026-07-14","2026-07-15","2026-07-18","2026-07-19","2026-07-22","2026-07-24","2026-07-26"]),
    "CMP000048": ("P2SRC298", ["2026-07-11","2026-07-12","2026-07-18","2026-07-19","2026-07-20","2026-07-21","2026-07-23","2026-07-25"]),
}

class Stage12M3KoshinetsuHokurikuGameDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CALENDAR.open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with SOURCES.open(encoding="utf-8-sig", newline="") as f:
            cls.sources = list(csv.DictReader(f))
        cls.by = {r["competition_id"]: r for r in cls.calendar}
        cls.source_ids = {r["source_id"] for r in cls.sources}

    def test_exact_six_competitions(self):
        self.assertEqual(6, len(EXPECTED))
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
            "CMP000039": {"2026-07-13"},
            "CMP000046": {"2026-07-07"},
            "CMP000048": {"2026-07-08"},
        }
        for cid, dates in excluded.items():
            actual = set(self.by[cid]["game_date_list"].split(";"))
            self.assertTrue(actual.isdisjoint(dates), cid)

    def test_partial_cancel_days_with_completed_games_included(self):
        self.assertIn("2026-07-06", self.by["CMP000040"]["game_date_list"].split(";"))
        self.assertIn("2026-07-18", self.by["CMP000046"]["game_date_list"].split(";"))

    def test_stage12m3_batch_is_present_in_current_master(self):
        # season_calendar.csv は Stage 12M-8 まで累積更新されるため、
        # Stage 12M-3 終了時点の途中件数ではなく、当該バッチが現行masterに残ることを検証する。
        summer = [r for r in self.calendar if 23 <= int(r["competition_id"].replace("CMP","")) <= 71]
        self.assertEqual(49, len(summer))
        detailed_ids = {r["competition_id"] for r in summer if r["game_date_list"]}
        self.assertTrue(set(EXPECTED).issubset(detailed_ids))

    def test_stage12m3_batch_game_day_count(self):
        self.assertEqual(64, sum(len(v[1]) for v in EXPECTED.values()))

if __name__ == "__main__":
    unittest.main()
