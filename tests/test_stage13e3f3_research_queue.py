from __future__ import annotations

import csv
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "data/research/2026/research_pending_queue.csv"
STAGE = ROOT / "data/schedules/2026/competition_stage_calendar.csv"


class Stage13E3F3ResearchQueueTests(unittest.TestCase):
    @staticmethod
    def read_rows(path):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_all_unverified_stage_calendars_are_tracked_once(self):
        stages = self.read_rows(STAGE)
        tasks = self.read_rows(QUEUE)
        expected = {
            row["stage_calendar_id"]
            for row in stages
            if row["date_status"] == "research_pending"
        }
        actual = [
            row["stage_calendar_id"]
            for row in tasks
            if row["task_type"] == "stage_calendar"
            and row["status"] != "resolved"
        ]
        self.assertEqual(expected, set(actual))
        self.assertEqual(len(expected), len(actual))

    def test_queue_has_unique_identifiers_and_valid_statuses(self):
        tasks = self.read_rows(QUEUE)
        self.assertEqual(26, len(tasks))
        self.assertEqual(
            len(tasks), len({row["task_id"] for row in tasks})
        )
        self.assertTrue(all(row["review_not_before"] for row in tasks))
        allowed = {
            "needs_research",
            "awaiting_publication",
            "needs_engine_fix",
            "design_pending",
            "resolved",
        }
        self.assertTrue(all(row["status"] in allowed for row in tasks))

    def test_future_jingu_research_not_marked_complete(self):
        tasks = self.read_rows(QUEUE)
        jingu = [
            row for row in tasks
            if row["competition_id"] == "CMP000003"
        ]
        self.assertEqual(1, len(jingu))
        self.assertEqual("awaiting_publication", jingu[0]["status"])
        self.assertEqual("2026-10-17", jingu[0]["review_not_before"])

    def test_access_rules_are_separately_tracked(self):
        tasks = self.read_rows(QUEUE)
        rules = {
            row["access_rule_id"] for row in tasks
            if row["task_type"] == "access_rule"
        }
        self.assertEqual({"ACR000008", "ACR000012"}, rules)


if __name__ == "__main__":
    unittest.main()
