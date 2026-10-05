import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

class Stage12GTokyoSpringScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (DATA / "competitions" / "prefectural_competition_index_2026.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.index = list(csv.DictReader(f))
        with (DATA / "schedules" / "2026" / "season_calendar.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with (DATA / "schedules" / "2026" / "stage12g_tokyo_spring_match_days_20261006.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.days = list(csv.DictReader(f))
        with (ROOT / "audits" / "phase2" / "stage12g" / "stage12g_tokyo_spring_schedule_audit_20261006.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.audit = list(csv.DictReader(f))
        with (DATA / "sources" / "phase2_sources.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.sources = list(csv.DictReader(f))

    def test_tokyo_spring_is_official(self):
        by={r["competition_id"]:r for r in self.calendar}
        self.assertEqual("official_schedule",by["CMP000094"]["calendar_status"])

    def test_all_94_prefectural_schedules_are_official(self):
        ids={r["competition_id"] for r in self.index}
        by={r["competition_id"]:r for r in self.calendar}
        self.assertEqual(94,sum(by[c]["calendar_status"]=="official_schedule" for c in ids))
        self.assertEqual(0,sum(by[c]["calendar_status"]=="research_pending" for c in ids))

    def test_tokyo_spring_has_15_main_match_days(self):
        self.assertEqual(15,len(self.days))
        self.assertTrue(all(r["competition_id"]=="CMP000094" for r in self.days))

    def test_match_days_match_audit_and_calendar(self):
        self.assertEqual(1,len(self.audit))
        audit_dates=self.audit[0]["match_dates"].split(";")
        day_dates=[r["match_date"] for r in self.days]
        by={r["competition_id"]:r for r in self.calendar}
        cal_dates=by["CMP000094"]["game_date_list"].split(";")
        self.assertEqual(audit_dates,day_dates)
        self.assertEqual(audit_dates,cal_dates)

    def test_calendar_source_exists(self):
        source_ids={r["source_id"] for r in self.sources}
        by={r["competition_id"]:r for r in self.calendar}
        self.assertIn(by["CMP000094"]["primary_source_id"],source_ids)

    def test_preliminary_dates_are_excluded_but_april_4_is_kept(self):
        by={r["competition_id"]:r for r in self.calendar}
        ds=by["CMP000094"]["game_date_list"].split(";")
        for d in ["2026-03-14","2026-03-15","2026-03-20","2026-03-21","2026-03-22"]:
            self.assertNotIn(d,ds)
        self.assertIn("2026-04-04",ds)
        self.assertEqual("2026-04-01",by["CMP000094"]["start_date"])
        self.assertEqual("2026-05-03",by["CMP000094"]["end_date"])

if __name__ == "__main__": unittest.main()
