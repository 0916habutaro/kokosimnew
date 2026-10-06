from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from phase2_engine.recheck_calendar import (
    build_due_queue,
    load_recheck_calendar,
    summarize_due_queue,
    validate_recheck_calendar,
    write_due_queue_csv,
)

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "data" / "schedules" / "2026" / "autumn_recheck_calendar.csv"
SNAPSHOT = ROOT / "audits" / "phase2" / "stage12o" / "stage12o_due_queue_20261007.csv"


class Stage12ORecheckCalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendar = load_recheck_calendar(CALENDAR)

    def test_october_7_due_queue(self):
        due = build_due_queue(self.calendar, date(2026, 10, 7))
        summary = summarize_due_queue(due, self.calendar, date(2026, 10, 7))
        self.assertEqual(27, summary["total_tracking"])
        self.assertEqual(3, summary["due_count"])
        self.assertEqual(3, summary["today_pending"])
        self.assertEqual(0, summary["overdue"])
        self.assertEqual(2, summary["unique_due_competitions"])
        self.assertEqual("2026-10-08", summary["next_future_date"])

    def test_october_7_targets_hokkaido_and_fukuoka(self):
        due = build_due_queue(self.calendar, date(2026, 10, 7))
        self.assertEqual(
            {"CMP000013", "CMP000148"},
            {row.competition_id for row in due},
        )
        hokkaido = [row for row in due if row.competition_id == "CMP000013"]
        self.assertEqual(2, len(hokkaido))
        self.assertEqual({"prefectural", "regional"}, {row.tracking_scope for row in hokkaido})

    def test_missed_checkpoint_remains_overdue(self):
        due = build_due_queue(self.calendar, date(2026, 10, 8))
        self.assertEqual(5, len(due))
        self.assertEqual(3, sum(row.due_status == "overdue" for row in due))
        self.assertEqual(2, sum(row.due_status == "today_pending" for row in due))
        self.assertEqual(
            {"CMP000013", "CMP000120", "CMP000128", "CMP000148"},
            {row.competition_id for row in due},
        )

    def test_duplicate_tracking_id_is_rejected(self):
        row = dict(self.calendar[0])
        with self.assertRaises(ValueError):
            validate_recheck_calendar([row, dict(row)])

    def test_duplicate_competition_id_is_allowed_for_shared_scope(self):
        validate_recheck_calendar(self.calendar)
        shared = [row for row in self.calendar if row["competition_id"] == "CMP000013"]
        self.assertEqual(2, len(shared))

    def test_committed_october_7_snapshot_matches_generator(self):
        generated = [row.to_dict() for row in build_due_queue(self.calendar, date(2026, 10, 7))]
        with SNAPSHOT.open(encoding="utf-8-sig", newline="") as f:
            committed = list(csv.DictReader(f))
        self.assertEqual(generated, committed)

    def test_writer_roundtrip(self):
        due = build_due_queue(self.calendar, date(2026, 10, 7))
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "due.csv"
            write_due_queue_csv(due, out)
            with out.open(encoding="utf-8-sig", newline="") as f:
                loaded = list(csv.DictReader(f))
        self.assertEqual(3, len(loaded))
        self.assertIn("due_status", loaded[0])
        self.assertIn("tracking_id", loaded[0])


if __name__ == "__main__":
    unittest.main()
