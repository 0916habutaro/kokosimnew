from __future__ import annotations

import csv
import unittest
from pathlib import Path

from phase2_engine import DataRepository, SeasonOrchestrator

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

TARGET = {
    "CMP000023": (14, "2026-06-25", "2026-07-20", "P2SRC277"),
    "CMP000024": (18, "2026-06-20", "2026-07-21", "P2SRC278"),
    "CMP000025": (11, "2026-07-07", "2026-07-22", "P2SRC279"),
    "CMP000026": (12, "2026-07-09", "2026-07-25", "P2SRC280"),
    "CMP000027": (10, "2026-07-08", "2026-07-21", "P2SRC281"),
    "CMP000028": (11, "2026-07-10", "2026-07-27", "P2SRC282"),
    "CMP000029": (12, "2026-07-11", "2026-07-28", "P2SRC283"),
    "CMP000030": (10, "2026-07-09", "2026-07-25", "P2SRC284"),
}


class Stage12MHokkaidoTohokuSummerDatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def read(path: Path):
            with path.open(encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
        cls.calendar = read(DATA / "schedules" / "2026" / "season_calendar.csv")
        cls.sources = read(DATA / "sources" / "phase2_sources.csv")
        cls.audit = read(
            ROOT / "audits" / "phase2" / "stage12m" /
            "stage12m_hokkaido_tohoku_summer_calendar_audit_20261006.csv"
        )
        cls.repo = DataRepository(DATA)
        cls.season = SeasonOrchestrator(cls.repo, DATA).run_structural_season(
            2026, 2026100501
        )

    def test_exactly_eight_summer_local_competitions_are_detailed(self):
        summer_ids = {
            c["competition_id"]
            for c in self.repo.competitions.values()
            if c["competition_type"] == "summer_local_qualifier"
        }
        by = {r["competition_id"]: r for r in self.calendar}
        detailed = {
            cid for cid in summer_ids
            if by[cid]["game_date_list"].strip()
        }
        self.assertEqual(set(TARGET), detailed)
        self.assertEqual(8, len(detailed))
        self.assertEqual(41, len(summer_ids - detailed))

    def test_target_match_day_counts_windows_and_sources(self):
        by = {r["competition_id"]: r for r in self.calendar}
        for cid, (count, start, end, source_id) in TARGET.items():
            with self.subTest(competition_id=cid):
                row = by[cid]
                dates = row["game_date_list"].split(";")
                self.assertEqual(count, len(dates))
                self.assertEqual(start, row["start_date"])
                self.assertEqual(end, row["end_date"])
                self.assertEqual(source_id, row["primary_source_id"])
                self.assertEqual(dates, sorted(dates))
                self.assertEqual(len(dates), len(set(dates)))
                self.assertEqual(start, dates[0])
                self.assertEqual(end, dates[-1])

    def test_first_block_contains_98_unique_competition_match_days(self):
        by = {r["competition_id"]: r for r in self.calendar}
        self.assertEqual(
            98,
            sum(len(by[cid]["game_date_list"].split(";")) for cid in TARGET),
        )

    def test_actual_window_corrections_are_expected_four(self):
        by = {r["competition_id"]: r for r in self.audit}
        corrected = {
            cid for cid, row in by.items()
            if row["action"] == "window_corrected"
        }
        self.assertEqual(
            {"CMP000026", "CMP000027", "CMP000028", "CMP000029"},
            corrected,
        )
        self.assertEqual("2026-07-09", by["CMP000026"]["actual_start"])
        self.assertEqual("2026-07-25", by["CMP000026"]["actual_end"])
        self.assertEqual("2026-07-28", by["CMP000029"]["actual_end"])

    def test_stage12m_sources_exist(self):
        ids = {r["source_id"] for r in self.sources}
        self.assertTrue({f"P2SRC{i}" for i in range(277, 285)} <= ids)

    def test_all_calendar_rows_with_dates_stay_within_actual_window(self):
        for row in self.calendar:
            dates = [d for d in row["game_date_list"].split(";") if d]
            if not dates:
                continue
            with self.subTest(competition_id=row["competition_id"]):
                self.assertTrue(all(row["start_date"] <= d <= row["end_date"] for d in dates))

    def test_full_season_execution_remains_complete(self):
        self.assertEqual(162, len(self.season.competition_runs))
        self.assertEqual(94, len(self.season.prefectural_rows))
        self.assertEqual(16, len(self.season.regional_rows))
        self.assertEqual(49, len(self.season.summer_local_competition_ids))
        self.assertEqual(59, sum(r.status == "PASS" for r in self.season.qualification_resolutions))
        self.assertEqual(22, sum(r.status == "PASS" for r in self.season.access_resolutions))
        self.assertEqual([], self.season.calendar_gaps)
        self.assertEqual([], self.season.internal_structure_gaps)
        self.assertEqual([], self.season.regional_bridge_gaps)
        self.assertEqual([], self.season.warnings)


if __name__ == "__main__":
    unittest.main()
