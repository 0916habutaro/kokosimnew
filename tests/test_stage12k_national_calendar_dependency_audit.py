import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

from phase2_engine import DataRepository, SeasonOrchestrator


class Stage12KNationalCalendarDependencyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (DATA / "schedules" / "2026" / "season_calendar.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with (DATA / "competitions" / "selection_rules.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.selection_rules = list(csv.DictReader(f))
        with (DATA / "competitions" / "qualification_rules.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.qualification_rules = list(csv.DictReader(f))
        with (ROOT / "audits" / "phase2" / "stage12k" / "stage12k_national_calendar_audit_20261006.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.calendar_audit = list(csv.DictReader(f))
        with (ROOT / "audits" / "phase2" / "stage12k" / "stage12k_national_dependency_audit_20261006.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.dependency_audit = list(csv.DictReader(f))
        cls.repo = DataRepository(DATA)
        cls.season = SeasonOrchestrator(cls.repo, DATA).run_structural_season(2026, 2026100501)

    def test_national_calendar_audit_has_three_competitions(self):
        self.assertEqual(
            {"CMP000001", "CMP000002", "CMP000003"},
            {r["competition_id"] for r in self.calendar_audit},
        )

    def test_senbatsu_calendar_has_actual_11_match_days(self):
        by = {r["competition_id"]: r for r in self.calendar}
        row = by["CMP000001"]
        self.assertEqual("2026-03-06", row["draw_date"])
        self.assertEqual(
            ["2026-03-19","2026-03-20","2026-03-21","2026-03-22","2026-03-23","2026-03-24","2026-03-25","2026-03-26","2026-03-27","2026-03-29","2026-03-31"],
            row["game_date_list"].split(";"),
        )
        self.assertNotIn("2026-03-28", row["game_date_list"].split(";"))
        self.assertNotIn("2026-03-30", row["game_date_list"].split(";"))

    def test_summer_national_calendar_has_actual_15_match_days(self):
        by = {r["competition_id"]: r for r in self.calendar}
        row = by["CMP000002"]
        self.assertEqual("2026-08-01", row["draw_date"])
        self.assertEqual(15, len(row["game_date_list"].split(";")))
        for rest_day in ("2026-08-17", "2026-08-19", "2026-08-21"):
            self.assertNotIn(rest_day, row["game_date_list"].split(";"))
        self.assertEqual("2026-08-22", row["game_date_list"].split(";")[-1])

    def test_jingu_keeps_game_days_pending_until_draw(self):
        by = {r["competition_id"]: r for r in self.calendar}
        row = by["CMP000003"]
        self.assertEqual("2026-10-17", row["draw_date"])
        self.assertEqual("", row["game_date_list"])
        self.assertEqual("2026-11-19", row["start_date"])
        self.assertEqual("2026-11-24", row["end_date"])

    def test_senbatsu_selection_rules_total_32(self):
        rows = [r for r in self.selection_rules if r["destination_competition_id"] == "CMP000001"]
        self.assertEqual(12, len(rows))
        self.assertEqual(32, sum(int(r["total_quota"]) for r in rows))

    def test_summer_has_49_automatic_qualification_rules(self):
        rows = [r for r in self.qualification_rules if r["destination_competition_id"] == "CMP000002"]
        self.assertEqual(49, len(rows))
        self.assertEqual(49, sum(int(r["quota"]) for r in rows))
        self.assertTrue(all(r["source_result"] == "winner" for r in rows))

    def test_jingu_has_10_automatic_qualification_rules(self):
        rows = [r for r in self.qualification_rules if r["destination_competition_id"] == "CMP000003"]
        self.assertEqual(10, len(rows))
        self.assertEqual(10, sum(int(r["quota"]) for r in rows))
        self.assertEqual(
            {f"CMP0000{i:02d}" for i in range(13, 23)},
            {r["source_competition_id"] for r in rows},
        )

    def test_current_structural_season_executes_all_national_competitions(self):
        for cid, count in (("CMP000001", 32), ("CMP000002", 49), ("CMP000003", 10)):
            with self.subTest(competition_id=cid):
                self.assertIn(cid, self.season.competition_runs)
                self.assertEqual(count, len(self.season.competition_runs[cid].entrant_school_ids))
        self.assertEqual(59, len(self.season.qualification_resolutions))
        self.assertEqual(59, sum(r.status == "PASS" for r in self.season.qualification_resolutions))

    def test_national_dependency_audit_all_pass(self):
        self.assertEqual(3, len(self.dependency_audit))
        self.assertTrue(all(r["current_status"] == "PASS" for r in self.dependency_audit))


if __name__ == "__main__":
    unittest.main()
