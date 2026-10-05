import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

class Stage12IAutumnReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (DATA / "schedules" / "2026" / "season_calendar.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.calendar = list(csv.DictReader(f))
        with (ROOT / "audits" / "phase2" / "stage12i" / "stage12i_autumn_reconciliation_queue_20261006.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.queue = list(csv.DictReader(f))
        with (DATA / "competitions" / "prefectural_competition_index_2026.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.index = list(csv.DictReader(f))
        with (DATA / "sources" / "phase2_sources.csv").open(encoding="utf-8-sig", newline="") as f:
            cls.sources = list(csv.DictReader(f))

    def test_reconciliation_queue_has_19_autumn_competitions(self):
        self.assertEqual(19, len(self.queue))
        self.assertEqual(19, len({r["competition_id"] for r in self.queue}))

    def test_queue_status_split_is_6_today_13_future(self):
        self.assertEqual(6, sum(r["reconciliation_status"] == "today_pending" for r in self.queue))
        self.assertEqual(13, sum(r["reconciliation_status"] == "future_pending" for r in self.queue))

    def test_fukuoka_is_only_calendar_correction(self):
        corrected = [r for r in self.queue if r["action"] == "calendar_corrected"]
        self.assertEqual(["CMP000148"], [r["competition_id"] for r in corrected])

    def test_fukuoka_calendar_includes_october_14(self):
        by = {r["competition_id"]: r for r in self.calendar}
        row = by["CMP000148"]
        self.assertEqual("2026-10-14", row["end_date"])
        self.assertEqual(
            ["2026-10-03","2026-10-04","2026-10-06","2026-10-07","2026-10-10","2026-10-12","2026-10-14"],
            row["game_date_list"].split(";"),
        )
        self.assertEqual("P2SRC260", row["primary_source_id"])

    def test_new_reconciliation_sources_exist(self):
        ids = {r["source_id"] for r in self.sources}
        self.assertTrue({"P2SRC260", "P2SRC261"} <= ids)

    def test_all_94_prefectural_schedules_remain_official(self):
        ids = {r["competition_id"] for r in self.index}
        by = {r["competition_id"]: r for r in self.calendar}
        self.assertEqual(94, sum(by[c]["calendar_status"] == "official_schedule" for c in ids))
        self.assertEqual(0, sum(by[c]["calendar_status"] == "research_pending" for c in ids))

if __name__ == "__main__":
    unittest.main()
