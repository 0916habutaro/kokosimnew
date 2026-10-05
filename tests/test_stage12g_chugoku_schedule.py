import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

class Stage12GChugokuScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (DATA / "competitions" / "prefectural_competition_index_2026.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.index = list(csv.DictReader(f))
        with (DATA / "schedules" / "2026" / "season_calendar.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with (DATA / "schedules" / "2026" / "stage12g_chugoku_match_days_20261006.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.days = list(csv.DictReader(f))
        with (ROOT / "audits" / "phase2" / "stage12g" / "stage12g_chugoku_schedule_audit_20261006.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.audit = list(csv.DictReader(f))
        with (DATA / "sources" / "phase2_sources.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.sources = list(csv.DictReader(f))

    def test_chugoku_10_competitions_are_official(self):
        ids={r["competition_id"] for r in self.audit}
        self.assertEqual(10,len(ids))
        by={r["competition_id"]:r for r in self.calendar}
        self.assertTrue(all(by[c]["calendar_status"]=="official_schedule" for c in ids))

    def test_prefectural_schedule_count_is_69_of_94(self):
        ids={r["competition_id"] for r in self.index}
        by={r["competition_id"]:r for r in self.calendar}
        self.assertEqual(69,sum(by[c]["calendar_status"]=="official_schedule" for c in ids))
        self.assertEqual(25,sum(by[c]["calendar_status"]=="research_pending" for c in ids))

    def test_66_match_days_have_competition_ids(self):
        self.assertEqual(66,len(self.days))
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

    def test_key_scope_and_postponement_dates(self):
        by={r["competition_id"]:r for r in self.calendar}
        self.assertIn("2026-09-29",by["CMP000130"]["game_date_list"].split(";"))
        self.assertEqual("2026-09-11",by["CMP000132"]["start_date"])
        self.assertNotIn("2026-04-11",by["CMP000133"]["game_date_list"].split(";"))
        self.assertIn("2026-04-27",by["CMP000133"]["game_date_list"].split(";"))
        self.assertNotIn("2026-10-04",by["CMP000134"]["game_date_list"].split(";"))
        self.assertIn("2026-10-06",by["CMP000134"]["game_date_list"].split(";"))
        self.assertEqual("2026-04-18",by["CMP000135"]["start_date"])
        self.assertIn("2026-10-06",by["CMP000136"]["game_date_list"].split(";"))
        self.assertEqual("2026-04-24",by["CMP000137"]["start_date"])
        self.assertNotIn("2026-04-19",by["CMP000137"]["game_date_list"].split(";"))
        self.assertEqual("2026-09-25",by["CMP000138"]["start_date"])
        self.assertNotIn("2026-09-20",by["CMP000138"]["game_date_list"].split(";"))
        self.assertNotIn("2026-09-26",by["CMP000138"]["game_date_list"].split(";"))

if __name__ == "__main__": unittest.main()
