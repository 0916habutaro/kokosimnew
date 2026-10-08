from __future__ import annotations

import csv
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "data/schedules/2026/competition_stage_calendar.csv"
QUEUE = ROOT / "data/research/2026/research_pending_queue.csv"
MAIN = ROOT / "data/schedules/2026/season_calendar.csv"

ACTUAL_DATES = (
    "2026-03-20",
    "2026-03-21",
    "2026-03-22",
    "2026-03-27",
    "2026-03-28",
)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class Stage13E3F3KanagawaSpringCalendarTests(unittest.TestCase):
    def test_five_actual_match_days_are_verified(self):
        stage = {r["stage_calendar_id"]: r for r in rows(STAGE)}["SC2026019"]
        self.assertEqual("CMP000095", stage["competition_id"])
        self.assertEqual("STG000177", stage["stage_id"])
        self.assertEqual("BRANCH_QUALIFIER", stage["stage_code"])
        self.assertEqual("verified", stage["date_status"])
        self.assertEqual(
            "explicitly_excluded_from_main_calendar",
            stage["calendar_relation"],
        )
        self.assertEqual(ACTUAL_DATES, tuple(stage["date_list"].split(";")))
        self.assertEqual(len(ACTUAL_DATES), len(set(ACTUAL_DATES)))

    def test_canceled_day_and_main_are_excluded(self):
        stage = {r["stage_calendar_id"]: r for r in rows(STAGE)}["SC2026019"]
        main = {r["competition_id"]: r for r in rows(MAIN)}["CMP000095"]
        dates = set(stage["date_list"].split(";"))
        self.assertNotIn("2026-03-26", dates)
        self.assertEqual("2026-04-04", main["start_date"])
        main_dates = set(main["game_date_list"].split(";"))
        self.assertTrue(main_dates.isdisjoint(dates))
        self.assertEqual("official_schedule", main["calendar_status"])

    def test_queue_resolution_and_other_pending_entries(self):
        queue = {r["task_id"]: r for r in rows(QUEUE)}
        stages = {r["stage_calendar_id"]: r for r in rows(STAGE)}
        self.assertEqual("resolved", queue["RS2026010"]["status"])
        self.assertEqual("verified", stages["SC2026019"]["date_status"])
        self.assertEqual("resolved", queue["RS2026009"]["status"])
        self.assertEqual("verified", stages["SC2026018"]["date_status"])
        for task, stage in (
            ("RS2026001", "SC2026001"),
            ("RS2026021", "SC2026045"),
        ):
            self.assertEqual("needs_research", queue[task]["status"])
            self.assertEqual("research_pending", stages[stage]["date_status"])
        self.assertEqual(
            2,
            sum(r["date_status"] == "research_pending" for r in stages.values()),
        )


if __name__ == "__main__":
    unittest.main()
