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


class Stage13E3F3ChibaSpringCalendarTests(unittest.TestCase):
    def test_chiba_four_actual_dates_exclude_rest_days_and_main(self):
        stages = {row["stage_calendar_id"]: row for row in read_rows(STAGE)}
        row = stages["SC2026016"]
        self.assertEqual("CMP000092", row["competition_id"])
        self.assertEqual("BRANCH_QUALIFIER", row["stage_code"])
        self.assertEqual("verified", row["date_status"])
        self.assertEqual(
            "explicitly_excluded_from_main_calendar",
            row["calendar_relation"],
        )
        dates = row["date_list"].split(";")
        self.assertEqual(
            [
                "2026-04-02",
                "2026-04-04",
                "2026-04-05",
                "2026-04-08",
            ],
            dates,
        )
        for excluded in ("2026-04-03", "2026-04-06", "2026-04-07", "2026-04-18"):
            self.assertNotIn(excluded, dates)

    def test_chiba_queue_resolved_prior_saitama_retained(self):
        tasks = {row["task_id"]: row for row in read_rows(QUEUE)}
        stages = {row["stage_calendar_id"]: row for row in read_rows(STAGE)}
        self.assertEqual("resolved", tasks["RS2026008"]["status"])
        self.assertEqual("resolved", tasks["RS2026007"]["status"])
        self.assertEqual("verified", stages["SC2026014"]["date_status"])
        self.assertEqual(7, len(stages["SC2026014"]["date_list"].split(";")))


if __name__ == "__main__":
    unittest.main()
