import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

class Stage12GTohokuScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (DATA / "competitions" / "prefectural_competition_index_2026.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.index = list(csv.DictReader(f))
        with (DATA / "schedules" / "2026" / "season_calendar.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with (DATA / "schedules" / "2026" / "stage12g_tohoku_match_days_20261005.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.days = list(csv.DictReader(f))
        with (ROOT / "audits" / "phase2" / "stage12g" / "stage12g_tohoku_schedule_audit_20261005.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.audit = list(csv.DictReader(f))

    def test_tohoku_12_competitions_are_official(self):
        ids={r["competition_id"] for r in self.audit}
        self.assertEqual(12,len(ids))
        by={r["competition_id"]:r for r in self.calendar}
        self.assertTrue(all(by[c]["calendar_status"]=="official_schedule" for c in ids))

    def test_prefectural_schedule_count_includes_tohoku(self):
        ids={r["competition_id"] for r in self.index}
        by={r["competition_id"]:r for r in self.calendar}
        self.assertGreaterEqual(sum(by[c]["calendar_status"]=="official_schedule" for c in ids),15)

    def test_92_match_days_have_competition_ids(self):
        self.assertEqual(92,len(self.days))
        self.assertTrue(all(r["competition_id"] for r in self.days))

    def test_match_days_match_audit_lists(self):
        by={}
        for r in self.days:
            by.setdefault(r["competition_id"],[]).append(r["match_date"])
        for r in self.audit:
            self.assertEqual(r["match_dates"].split(";"),by[r["competition_id"]])

if __name__ == "__main__": unittest.main()
