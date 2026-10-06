import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

class Stage12JRegionalCalendarAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (DATA / "competitions" / "competitions.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.competitions = list(csv.DictReader(f))
        with (DATA / "schedules" / "2026" / "season_calendar.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with (ROOT / "audits" / "phase2" / "stage12j" / "stage12j_spring_regional_calendar_audit_20261006.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.spring_audit = list(csv.DictReader(f))
        with (ROOT / "audits" / "phase2" / "stage12j" / "stage12j_autumn_regional_recheck_queue_20261006.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.autumn_queue = list(csv.DictReader(f))
        with (DATA / "sources" / "phase2_sources.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.sources = list(csv.DictReader(f))

    def test_all_19_regional_competitions_have_official_calendar(self):
        regional_ids = {
            r["competition_id"]
            for r in self.competitions
            if r["competition_level"] == "regional"
            and r["competition_type"] in {"spring_regional", "autumn_regional"}
        }
        self.assertEqual(19, len(regional_ids))
        by = {r["competition_id"]: r for r in self.calendar}
        self.assertTrue(regional_ids <= set(by))
        self.assertTrue(all(by[c]["calendar_status"] == "official_schedule" for c in regional_ids))

    def test_spring_audit_has_nine_and_exactly_two_corrections(self):
        self.assertEqual(9, len(self.spring_audit))
        corrected = {r["competition_id"] for r in self.spring_audit if r["action"] == "calendar_corrected"}
        self.assertEqual({"CMP000005", "CMP000012"}, corrected)

    def test_tohoku_spring_actual_match_days(self):
        by = {r["competition_id"]: r for r in self.calendar}
        row = by["CMP000005"]
        self.assertEqual(
            ["2026-06-09", "2026-06-10", "2026-06-12", "2026-06-13"],
            row["game_date_list"].split(";"),
        )
        self.assertNotIn("2026-06-11", row["game_date_list"].split(";"))
        self.assertEqual("P2SRC263", row["primary_source_id"])

    def test_kyushu_spring_actual_match_days_and_end_date(self):
        by = {r["competition_id"]: r for r in self.calendar}
        row = by["CMP000012"]
        self.assertEqual("2026-04-27", row["end_date"])
        self.assertEqual(
            ["2026-04-18", "2026-04-20", "2026-04-21", "2026-04-22", "2026-04-24", "2026-04-25", "2026-04-27"],
            row["game_date_list"].split(";"),
        )
        self.assertNotIn("2026-04-19", row["game_date_list"].split(";"))
        self.assertEqual("P2SRC270", row["primary_source_id"])

    def test_autumn_queue_has_ten_regions_with_tokyo_delegated(self):
        self.assertEqual(10, len(self.autumn_queue))
        tracked = [r for r in self.autumn_queue if r["status"] == "tracked_stage12i"]
        future = [r for r in self.autumn_queue if r["status"] == "future_pending"]
        self.assertEqual(["CMP000016"], [r["competition_id"] for r in tracked])
        self.assertEqual(9, len(future))
        by = {r["competition_id"]: r for r in self.autumn_queue}
        self.assertEqual("2026-10-07", by["CMP000013"]["next_check_date"])
        self.assertEqual("2026-10-10", by["CMP000017"]["next_check_date"])

    def test_stage12j_sources_exist(self):
        ids = {r["source_id"] for r in self.sources}
        self.assertTrue({f"P2SRC{i}" for i in range(262, 273)} <= ids)

if __name__ == "__main__":
    unittest.main()
