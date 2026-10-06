from __future__ import annotations

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "data" / "schedules" / "2026" / "season_calendar.csv"
SOURCES = ROOT / "data" / "sources" / "phase2_sources.csv"
QUEUE = ROOT / "audits" / "phase2" / "stage12ij" / "stage12i_autumn_reconciliation_queue_20261006_eod.csv"
REGIONAL = ROOT / "audits" / "phase2" / "stage12ij" / "stage12j_autumn_regional_recheck_queue_20261006_eod.csv"
REMAINING = ROOT / "audits" / "phase2" / "stage12ij" / "stage12ij_remaining_work_20261006_eod.csv"

ACTUALIZED = {
    "CMP000091": "2026-10-06",
    "CMP000120": "2026-10-06",
    "CMP000122": "2026-10-06",
    "CMP000134": "2026-10-06",
    "CMP000136": "2026-10-06",
    "CMP000148": "2026-10-06",
}

class Stage12IJAutumnRecheckEODTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def load(path):
            with path.open(encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
        cls.calendar = load(CALENDAR)
        cls.sources = load(SOURCES)
        cls.queue = load(QUEUE)
        cls.regional = load(REGIONAL)
        cls.remaining = load(REMAINING)
        cls.by = {r["competition_id"]: r for r in cls.calendar}

    def test_six_october_6_actualizations_are_in_calendar(self):
        for cid, d in ACTUALIZED.items():
            row = self.by[cid]
            self.assertIn(d, row["game_date_list"].split(";"), cid)
            self.assertEqual("2026-10-06", row["verified_at"], cid)
            self.assertIn("EOD再照合", row["notes"], cid)

    def test_prefectural_queue_counts(self):
        self.assertEqual(19, len(self.queue))
        by = {r["competition_id"]: r for r in self.queue}
        self.assertEqual("completed", by["CMP000091"]["reconciliation_status"])
        self.assertEqual("", by["CMP000091"]["remaining_planned_dates"])
        self.assertEqual(6, sum(r["action"] == "actualized" for r in self.queue))
        self.assertEqual(18, sum(r["reconciliation_status"] != "completed" for r in self.queue))

    def test_october_7_is_still_future_at_eod_cutoff(self):
        by = {r["competition_id"]: r for r in self.queue}
        self.assertEqual("future_pending", by["CMP000013"]["reconciliation_status"])
        self.assertTrue(by["CMP000013"]["remaining_planned_dates"].startswith("2026-10-07"))
        self.assertEqual("future_pending", by["CMP000148"]["reconciliation_status"])
        self.assertTrue(by["CMP000148"]["remaining_planned_dates"].startswith("2026-10-07"))

    def test_stage12j_nine_owned_regions_are_future_pending(self):
        owned = [r for r in self.regional if r["tracking_stage"] == "Stage12J"]
        self.assertEqual(9, len(owned))
        self.assertTrue(all(r["status"] == "future_pending" for r in owned))
        hokkaido = next(r for r in owned if r["competition_id"] == "CMP000013")
        self.assertEqual("2026-10-07", hokkaido["next_check_date"])

    def test_sources_and_remaining_counts(self):
        source_ids = {r["source_id"] for r in self.sources}
        for n in range(326, 332):
            self.assertIn(f"P2SRC{n}", source_ids)
        rem = {r["remaining_id"]: r for r in self.remaining}
        self.assertEqual("0", rem["REM001"]["count"])
        self.assertEqual("18", rem["REM003"]["count"])
        self.assertEqual("9", rem["REM004"]["count"])

if __name__ == "__main__":
    unittest.main()
