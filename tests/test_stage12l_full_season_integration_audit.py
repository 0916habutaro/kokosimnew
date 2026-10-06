from __future__ import annotations

import csv
import unittest
from pathlib import Path

from phase2_engine import DataRepository, SeasonOrchestrator

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class Stage12LFullSeasonIntegrationAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def read(path: Path):
            with path.open(encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))

        cls.competitions = read(DATA / "competitions" / "competitions.csv")
        cls.calendar = read(DATA / "schedules" / "2026" / "season_calendar.csv")
        cls.feeder_rules = read(DATA / "competitions" / "regional_feeder_rules.csv")
        cls.qualification_rules = read(DATA / "competitions" / "qualification_rules.csv")
        cls.access_rules = read(DATA / "competitions" / "competition_access_rules.csv")
        cls.selection_rules = read(DATA / "competitions" / "selection_rules.csv")
        cls.full_calendar_audit = read(
            ROOT / "audits" / "phase2" / "stage12l" /
            "stage12l_full_competition_calendar_audit_20261006.csv"
        )
        cls.summary = read(
            ROOT / "audits" / "phase2" / "stage12l" /
            "stage12l_full_season_summary_20261006.csv"
        )
        cls.remaining = read(
            ROOT / "audits" / "phase2" / "stage12l" /
            "stage12l_remaining_work_20261006.csv"
        )
        cls.repo = DataRepository(DATA)
        cls.season = SeasonOrchestrator(cls.repo, DATA).run_structural_season(
            2026, 2026100501
        )

    def test_all_162_competitions_have_one_official_calendar_row(self):
        self.assertEqual(162, len(self.competitions))
        self.assertEqual(162, len(self.calendar))
        competition_ids = {r["competition_id"] for r in self.competitions}
        calendar_ids = [r["competition_id"] for r in self.calendar]
        self.assertEqual(162, len(set(calendar_ids)))
        self.assertEqual(competition_ids, set(calendar_ids))
        self.assertTrue(all(r["calendar_status"] == "official_schedule" for r in self.calendar))

    def test_full_calendar_audit_covers_all_competitions(self):
        self.assertEqual(162, len(self.full_calendar_audit))
        self.assertEqual(
            {r["competition_id"] for r in self.competitions},
            {r["competition_id"] for r in self.full_calendar_audit},
        )

    def test_calendar_detail_gap_is_exactly_49_summer_local_plus_jingu(self):
        period_only = [
            r for r in self.full_calendar_audit
            if r["game_date_detail_status"] == "period_only"
        ]
        pending = [
            r for r in self.full_calendar_audit
            if r["game_date_detail_status"] == "future_pending"
        ]
        detailed = [
            r for r in self.full_calendar_audit
            if r["game_date_detail_status"] == "detailed"
        ]
        unexpected = [
            r for r in self.full_calendar_audit
            if r["game_date_detail_status"] == "unexpected_empty"
        ]
        self.assertEqual(49, len(period_only))
        self.assertTrue(all(r["competition_type"] == "summer_local_qualifier" for r in period_only))
        self.assertEqual(["CMP000003"], [r["competition_id"] for r in pending])
        self.assertEqual(112, len(detailed))
        self.assertEqual([], unexpected)

    def test_all_detailed_game_dates_are_unique_sorted_and_within_window(self):
        for row in self.calendar:
            dates = [d for d in row["game_date_list"].split(";") if d]
            if not dates:
                continue
            with self.subTest(competition_id=row["competition_id"]):
                self.assertEqual(dates, sorted(dates))
                self.assertEqual(len(dates), len(set(dates)))
                self.assertTrue(all(row["start_date"] <= d <= row["end_date"] for d in dates))

    def test_static_dependency_master_counts(self):
        self.assertEqual(96, len(self.feeder_rules))
        self.assertEqual(59, len(self.qualification_rules))
        self.assertEqual(22, len(self.access_rules))
        self.assertEqual(12, len(self.selection_rules))
        self.assertEqual(
            32,
            sum(
                int(r["total_quota"])
                for r in self.selection_rules
                if r["destination_competition_id"] == "CMP000001"
            ),
        )

    def test_runtime_executes_all_162_competitions(self):
        self.assertEqual(162, len(self.season.competition_runs))
        self.assertEqual(set(self.repo.competitions), set(self.season.competition_runs))

    def test_runtime_execution_partition_is_complete(self):
        self.assertEqual(94, len(self.season.prefectural_rows))
        self.assertEqual(16, len(self.season.regional_rows))
        self.assertEqual(49, len(self.season.summer_local_competition_ids))
        for cid in ("CMP000001", "CMP000002", "CMP000003"):
            self.assertIn(cid, self.season.competition_runs)
        self.assertEqual(94 + 16 + 49 + 3, len(self.season.competition_runs))

    def test_runtime_dependencies_are_fully_resolved(self):
        self.assertEqual(59, len(self.season.qualification_resolutions))
        self.assertEqual(59, sum(r.status == "PASS" for r in self.season.qualification_resolutions))
        self.assertFalse(any(r.date_status == "FAIL" for r in self.season.qualification_resolutions))
        self.assertEqual(22, len(self.season.access_resolutions))
        self.assertTrue(all(r.status == "PASS" for r in self.season.access_resolutions))

    def test_runtime_has_no_structural_calendar_or_bridge_gaps(self):
        self.assertEqual([], self.season.calendar_gaps)
        self.assertEqual([], self.season.internal_structure_gaps)
        self.assertEqual([], self.season.regional_bridge_gaps)
        self.assertEqual([], self.season.warnings)

    def test_remaining_work_is_explicit_and_bounded(self):
        by = {r["remaining_id"]: r for r in self.remaining}
        self.assertEqual({"REM001", "REM002", "REM003", "REM004"}, set(by))
        self.assertEqual("49", by["REM001"]["count"])
        self.assertEqual("1", by["REM002"]["count"])
        self.assertEqual("19", by["REM003"]["count"])
        self.assertEqual("9", by["REM004"]["count"])


if __name__ == "__main__":
    unittest.main()
