from __future__ import annotations

import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine import (
    DataRepository,
    LiveSeasonGraphPlanner,
    audit_full_season_live_runtime,
)
from phase2_engine.final_season_integrity_audit import (
    build_final_season_integrity_report,
    save_final_season_integrity_report,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
YEAR = 2026
FIXTURE_PATHS = (
    "competitions/competitions.csv",
    "competitions/competition_stages.csv",
    "schedules/2026/season_calendar.csv",
    "schedules/2026/competition_stage_calendar.csv",
    "schedules/2026/known_same_day_stage_overlaps.csv",
    "research/2026/research_pending_queue.csv",
)


def _temp_fixture(path: Path) -> None:
    for item in FIXTURE_PATHS:
        dest = path / item
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / item, dest)


def _rewrite_csv(path: Path, change) -> None:
    with path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    change(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3F4FinalSeasonIntegrityStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_final_season_integrity_report(DATA, year=YEAR)

    def test_all_structural_checks_pass(self):
        self.assertTrue(self.report["ok"])
        self.assertFalse([
            c for c in self.report["checks"] if c["status"] == "FAIL"
        ])

    def test_all_pre_main_calendar_rows_are_verified(self):
        counts = self.report["summary"]
        self.assertEqual(162, counts["competition_count"])
        self.assertEqual(162, counts["main_calendar_count"])
        self.assertEqual(50, counts["pre_main_stage_count"])
        self.assertEqual(50, counts["verified_pre_main_stage_count"])
        self.assertEqual(0, counts["pending_pre_main_stage_count"])
        self.assertEqual(21, counts["stage_research_task_count"])

    def test_gifu_main_omits_exclusively_preliminary_dates(self):
        with (DATA / "schedules/2026/season_calendar.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        main = {r["competition_id"]: r for r in rows}["CMP000110"]
        self.assertEqual("2026-09-05", main["start_date"])
        days = main["game_date_list"].split(";")
        self.assertNotIn("2026-08-29", days)
        self.assertNotIn("2026-08-30", days)
        self.assertIn("2026-09-05", days)

    def test_gifu_september_fifth_is_intentional_same_day_staging(self):
        self.assertEqual(1, self.report["summary"]["known_same_day_overlap_count"])
        self.assertEqual(
            [{
                "competition_id": "CMP000110",
                "stage_calendar_id": "SC2026025",
                "date": "2026-09-05",
            }],
            self.report["same_day_overlaps"],
        )

    def test_unfinished_publication_and_designs_remain_visible(self):
        issues = {
            r["task_id"]: r["status"]
            for r in self.report["open_research"]
        }
        self.assertEqual({
            "RS2026022": "awaiting_publication",
            "RS2026025": "design_pending",
            "RS2026026": "design_pending",
        }, issues)
        self.assertEqual(1, self.report["summary"]["blank_main_calendar_count"])
        self.assertEqual(3, self.report["summary"]["open_research_count"])
        self.assertIn(
            "DEFERRED", {c["status"] for c in self.report["checks"]}
        )

    def test_json_and_csv_reports_are_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            outputs = save_final_season_integrity_report(self.report, temp)
            self.assertEqual(
                self.report,
                json.loads(Path(outputs["summary"]).read_text(encoding="utf-8")),
            )
            with Path(outputs["checks"]).open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(self.report["checks"], saved)

    def test_unapproved_same_day_overlap_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            _temp_fixture(data)
            main = data / "schedules/2026/season_calendar.csv"

            def revert_gifu(rowlist):
                target = next(
                    r for r in rowlist
                    if r["competition_id"] == "CMP000110"
                )
                target["start_date"] = "2026-08-29"
                target["game_date_list"] = (
                    "2026-08-29;2026-08-30;" + target["game_date_list"]
                )

            _rewrite_csv(main, revert_gifu)
            report = build_final_season_integrity_report(data, year=YEAR)
            self.assertFalse(report["ok"])
            failures = {c["check"] for c in report["checks"]
                        if c["status"] == "FAIL"}
            self.assertIn("pre_main_main_boundary", failures)

    def test_stale_exception_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            _temp_fixture(data)
            allowed = data / "schedules/2026/known_same_day_stage_overlaps.csv"
            with allowed.open(encoding="utf-8", newline="") as handle:
                raw = handle.read()
            allowed.write_text(
                raw + (
                    "CMP000004,SC2026001,2026-05-08,"
                    "不正な例外の動作確認,https://example.org/\n"
                ),
                encoding="utf-8",
            )
            report = build_final_season_integrity_report(data, year=YEAR)
            self.assertFalse(report["ok"])
            self.assertIn("stale stage exception", next(
                c["detail"] for c in report["checks"]
                if c["check"] == "pre_main_main_boundary"
            ))

    def test_unresolved_stage_task_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            _temp_fixture(data)
            queue = data / "research/2026/research_pending_queue.csv"

            def reopen(rowlist):
                row = next(r for r in rowlist if r["task_id"] == "RS2026001")
                row["status"] = "needs_research"

            _rewrite_csv(queue, reopen)
            report = build_final_season_integrity_report(data, year=YEAR)
            self.assertFalse(report["ok"])
            self.assertIn("stage_research_queue", [
                c["check"] for c in report["checks"] if c["status"] == "FAIL"
            ])

    def test_duplicate_stage_day_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            _temp_fixture(data)
            schedule = data / "schedules/2026/competition_stage_calendar.csv"

            def duplicate(rowlist):
                row = next(
                    r for r in rowlist if r["stage_calendar_id"] == "SC2026001"
                )
                row["date_list"] += ";2026-05-17"

            _rewrite_csv(schedule, duplicate)
            report = build_final_season_integrity_report(data, year=YEAR)
            self.assertFalse(report["ok"])
            self.assertIn("calendar_dates_and_status", [
                c["check"] for c in report["checks"] if c["status"] == "FAIL"
            ])


class Stage13E3F4FinalSeasonIntegrityRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo = DataRepository(DATA)
        plan = LiveSeasonGraphPlanner(
            repo, DATA, 2026100827, year=YEAR,
        ).build_plan()
        cls.audit = audit_full_season_live_runtime(plan)
        cls.report = build_final_season_integrity_report(
            DATA, year=YEAR, live_audit=cls.audit
        )

    def test_complete_runtime_with_only_jingu_deferred(self):
        self.assertTrue(self.report["ok"], self.report["checks"])
        self.assertEqual(
            161, self.report["summary"]["simulated_completed_competition_count"]
        )
        self.assertEqual(
            ["CMP000003"],
            self.report["summary"]["simulated_incomplete_competition_ids"],
        )
        self.assertGreater(
            self.report["summary"]["simulated_completed_match_count"], 10000
        )

    def test_no_downstream_or_pre_main_waits(self):
        runtime = self.report["live_summary"]
        self.assertEqual(0, runtime["pending_stage_row_count"])
        self.assertEqual(0, runtime["dependency_wait_competition_count"])
        self.assertEqual(0, runtime["unique_downstream_blocked_competition_count"])
        self.assertEqual([], self.audit.stage_priority_rows)
        self.assertEqual(["CMP000003"], [
            r.competition_id for r in self.audit.competition_rows
            if r.blocker_kind != "complete"
        ])


if __name__ == "__main__":
    unittest.main()
