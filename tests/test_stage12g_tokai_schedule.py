import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

class Stage12GTokaiScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (DATA / "competitions" / "prefectural_competition_index_2026.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.index = list(csv.DictReader(f))
        with (DATA / "schedules" / "2026" / "season_calendar.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with (DATA / "schedules" / "2026" / "stage12g_tokai_match_days_20261005.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.days = list(csv.DictReader(f))
        with (ROOT / "audits" / "phase2" / "stage12g" / "stage12g_tokai_schedule_audit_20261005.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.audit = list(csv.DictReader(f))
        with (DATA / "sources" / "phase2_sources.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.sources = list(csv.DictReader(f))

    def test_tokai_8_competitions_are_official(self):
        ids={r["competition_id"] for r in self.audit}
        self.assertEqual(8,len(ids))
        by={r["competition_id"]:r for r in self.calendar}
        self.assertTrue(all(by[c]["calendar_status"]=="official_schedule" for c in ids))

    def test_prefectural_schedule_count_includes_tokai(self):
        ids={r["competition_id"] for r in self.index}
        by={r["competition_id"]:r for r in self.calendar}
        self.assertGreaterEqual(sum(by[c]["calendar_status"]=="official_schedule" for c in ids),47)

    def test_59_match_days_have_competition_ids(self):
        self.assertEqual(59,len(self.days))
        self.assertTrue(all(r["competition_id"] for r in self.days))

    def test_match_days_match_audit_lists(self):
        by={}
        for r in self.days:
            by.setdefault(r["competition_id"],[]).append(r["match_date"])
        for r in self.audit:
            self.assertEqual(r["match_dates"].split(";"),by[r["competition_id"]])

    def test_calendar_sources_exist(self):
        source_ids={r["source_id"] for r in self.sources}
        by={r["competition_id"]:r for r in self.calendar}
        for r in self.audit:
            self.assertIn(by[r["competition_id"]]["primary_source_id"],source_ids)

    def test_key_postponement_and_scope_dates(self):
        by={r["competition_id"]:r for r in self.calendar}
        self.assertEqual("2026-04-29",by["CMP000109"]["end_date"])
        self.assertNotIn("2026-04-26",by["CMP000109"]["game_date_list"].split(";"))
        self.assertEqual("2026-04-18",by["CMP000111"]["start_date"])
        self.assertNotIn("2026-09-26",by["CMP000114"]["game_date_list"].split(";"))
        self.assertEqual("2026-09-27",by["CMP000114"]["end_date"])
        self.assertEqual("2026-09-27",by["CMP000116"]["end_date"])

if __name__ == "__main__": unittest.main()
