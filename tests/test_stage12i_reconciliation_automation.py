from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from phase2_engine.reconciliation import (
    build_reconciliation_status,
    load_reconciliation_queue,
    summarize_reconciliation_status,
    write_reconciliation_status_csv,
)

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "audits" / "phase2" / "stage12i" / "stage12i_autumn_reconciliation_queue_20261006.csv"
SNAPSHOT = ROOT / "audits" / "phase2" / "stage12i" / "stage12i_recheck_status_20261006.csv"


class Stage12IReconciliationAutomationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = load_reconciliation_queue(QUEUE)

    def test_october_6_status_matches_stage12i_snapshot(self):
        rows = build_reconciliation_status(self.queue, date(2026, 10, 6))
        summary = summarize_reconciliation_status(rows)
        self.assertEqual(19, summary["total"])
        self.assertEqual(0, summary["recheck_due"])
        self.assertEqual(6, summary["today_pending"])
        self.assertEqual(13, summary["future_pending"])
        self.assertEqual("2026-10-06", summary["next_check_date"])

    def test_october_7_marks_unresolved_october_6_rows_due(self):
        rows = build_reconciliation_status(self.queue, date(2026, 10, 7))
        summary = summarize_reconciliation_status(rows)
        self.assertEqual(6, summary["recheck_due"])
        self.assertEqual(1, summary["today_pending"])
        self.assertEqual(12, summary["future_pending"])
        self.assertEqual("2026-10-06", summary["next_check_date"])

    def test_today_competitions_are_expected_six(self):
        rows = build_reconciliation_status(self.queue, date(2026, 10, 6))
        today = {r.competition_id for r in rows if r.status == "today_pending"}
        self.assertEqual(
            {"CMP000091","CMP000120","CMP000122","CMP000134","CMP000136","CMP000148"},
            today,
        )

    def test_next_check_date_is_derived_from_remaining_dates(self):
        rows = build_reconciliation_status(self.queue, date(2026, 10, 6))
        by = {r.competition_id: r for r in rows}
        self.assertEqual("2026-10-06", by["CMP000148"].next_check_date)
        self.assertEqual("2026-10-07", by["CMP000013"].next_check_date)
        self.assertEqual("2026-10-10", by["CMP000016"].next_check_date)

    def test_empty_remaining_dates_becomes_complete(self):
        row = {
            "competition_id": "CMPTEST",
            "prefecture_code": "00",
            "prefecture": "テスト県",
            "latest_confirmed_date": "2026-10-06",
            "remaining_planned_dates": "",
            "notes": "",
        }
        status = build_reconciliation_status([row], date(2026, 10, 7))[0]
        self.assertEqual("complete", status.status)
        self.assertEqual("", status.next_check_date)
        self.assertEqual(0, status.remaining_count)

    def test_duplicate_competition_id_is_rejected(self):
        row = {
            "competition_id": "CMPTEST",
            "prefecture_code": "00",
            "prefecture": "テスト県",
            "latest_confirmed_date": "",
            "remaining_planned_dates": "2026-10-10",
            "notes": "",
        }
        with self.assertRaises(ValueError):
            build_reconciliation_status([row, dict(row)], date(2026, 10, 6))

    def test_committed_october_6_snapshot_matches_generator(self):
        generated = [r.to_dict() for r in build_reconciliation_status(self.queue, date(2026, 10, 6))]
        with SNAPSHOT.open(encoding="utf-8-sig", newline="") as f:
            committed = list(csv.DictReader(f))
        normalized = []
        for row in generated:
            normalized.append({k: str(v) for k, v in row.items()})
        self.assertEqual(normalized, committed)

    def test_writer_roundtrip(self):
        rows = build_reconciliation_status(self.queue, date(2026, 10, 6))
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "status.csv"
            write_reconciliation_status_csv(rows, out)
            with out.open(encoding="utf-8-sig", newline="") as f:
                loaded = list(csv.DictReader(f))
        self.assertEqual(19, len(loaded))
        self.assertIn("recheck_reason", loaded[0])
        self.assertIn("next_check_date", loaded[0])


if __name__ == "__main__":
    unittest.main()
