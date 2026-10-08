from __future__ import annotations

import csv
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "data/schedules/2026/competition_stage_calendar.csv"
QUEUE = ROOT / "data/research/2026/research_pending_queue.csv"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class Stage13E3F3SaitamaSpringCalendarTests(unittest.TestCase):
    def test_actual_match_dates_exclude_main_and_unplayed_reserve_day(self):
        by_id = {r["stage_calendar_id"]: r for r in read_rows(STAGE)}
        row = by_id["SC2026014"]
        self.assertEqual("CMP000090", row["competition_id"])
        self.assertEqual("BRANCH_QUALIFIER", row["stage_code"])
        self.assertEqual("verified", row["date_status"])
        self.assertEqual(
            "explicitly_excluded_from_main_calendar",
            row["calendar_relation"],
        )
        self.assertEqual(
            [
                "2026-04-10",
                "2026-04-11",
                "2026-04-12",
                "2026-04-13",
                "2026-04-14",
                "2026-04-15",
                "2026-04-16",
            ],
            row["date_list"].split(";"),
        )
        self.assertNotIn("2026-04-17", row["date_list"])
        self.assertNotIn("2026-04-23", row["date_list"])

    def test_queue_resolution_retains_prior_prefectures(self):
        queue = {r["task_id"]: r for r in read_rows(QUEUE)}
        stages = {r["stage_calendar_id"]: r for r in read_rows(STAGE)}
        for task, stage in (
            ("RS2026005", "SC2026010"),
            ("RS2026006", "SC2026012"),
            ("RS2026007", "SC2026014"),
        ):
            self.assertEqual("resolved", queue[task]["status"])
            self.assertEqual("verified", stages[stage]["date_status"])


if __name__ == "__main__":
    unittest.main()
