from __future__ import annotations

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKING = ROOT / "data" / "schedules" / "2026" / "autumn_recheck_calendar.csv"
CHECKPOINTS = ROOT / "audits" / "phase2" / "stage12n" / "stage12n_recheck_checkpoints_20261007.csv"
SOURCES = ROOT / "data" / "sources" / "phase2_sources.csv"

class Stage12NAutumnRecheckCalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def load(path):
            with path.open(encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
        cls.tracking = load(TRACKING)
        cls.checkpoints = load(CHECKPOINTS)
        cls.sources = load(SOURCES)

    def test_tracking_counts(self):
        self.assertEqual(27, len(self.tracking))
        self.assertEqual(18, sum(r["tracking_scope"] == "prefectural" for r in self.tracking))
        self.assertEqual(9, sum(r["tracking_scope"] == "regional" for r in self.tracking))
        self.assertEqual(26, len({r["competition_id"] for r in self.tracking}))

    def test_hokkaido_is_only_shared_competition(self):
        shared = [r for r in self.tracking if r["shared_competition"] == "true"]
        self.assertEqual(2, len(shared))
        self.assertEqual({"CMP000013"}, {r["competition_id"] for r in shared})
        self.assertEqual({"prefectural", "regional"}, {r["tracking_scope"] for r in shared})

    def test_planned_date_invariants(self):
        for row in self.tracking:
            dates = row["remaining_planned_dates"].split(";")
            self.assertTrue(dates, row["tracking_id"])
            self.assertEqual(dates, sorted(dates), row["tracking_id"])
            self.assertEqual(len(dates), len(set(dates)), row["tracking_id"])
            self.assertTrue(all(d >= "2026-10-07" for d in dates), row["tracking_id"])
            self.assertEqual(dates[0], row["next_scheduled_date"], row["tracking_id"])
            self.assertEqual(dates[-1], row["final_scheduled_date"], row["tracking_id"])

    def test_sources_exist(self):
        source_ids = {r["source_id"] for r in self.sources}
        for row in self.tracking:
            self.assertIn(row["schedule_source_id"], source_ids, row["tracking_id"])

    def test_checkpoint_bounds(self):
        dates = [r["checkpoint_date"] for r in self.checkpoints]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual("2026-10-07", dates[0])
        self.assertEqual("2026-11-05", dates[-1])

    def test_first_checkpoint_targets(self):
        first = self.checkpoints[0]
        self.assertEqual("2026-10-07", first["checkpoint_date"])
        self.assertEqual("3", first["tracking_item_count"])
        self.assertEqual("2", first["unique_competition_count"])
        self.assertEqual({"CMP000013", "CMP000148"}, set(first["competition_ids"].split(";")))

if __name__ == "__main__":
    unittest.main()
