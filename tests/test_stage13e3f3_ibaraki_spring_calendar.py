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


class Stage13E3F3IbarakiSpringCalendarTests(unittest.TestCase):
    def test_ibaraki_actual_dates_are_separate_from_main(self):
        stages = {row["stage_calendar_id"]: row for row in read_rows(STAGE)}
        row = stages["SC2026012"]
        dates = row["date_list"].split(";")
        self.assertEqual(
            [
                "2026-04-08",
                "2026-04-09",
                "2026-04-10",
                "2026-04-11",
                "2026-04-12",
                "2026-04-13",
            ],
            dates,
        )
        self.assertEqual("CMP000084", row["competition_id"])
        self.assertEqual("BRANCH_QUALIFIER", row["stage_code"])
        self.assertEqual("verified", row["date_status"])
        self.assertEqual(
            "explicitly_excluded_from_main_calendar",
            row["calendar_relation"],
        )
        self.assertTrue(all(date < "2026-04-18" for date in dates))

    def test_queue_resolved_and_fukushima_not_regressed(self):
        queue = {row["task_id"]: row for row in read_rows(QUEUE)}
        self.assertEqual("resolved", queue["RS2026006"]["status"])
        self.assertEqual("resolved", queue["RS2026005"]["status"])
        stages = {row["stage_calendar_id"]: row for row in read_rows(STAGE)}
        self.assertEqual("verified", stages["SC2026010"]["date_status"])
        self.assertEqual(10, len(stages["SC2026010"]["date_list"].split(";")))


if __name__ == "__main__":
    unittest.main()
