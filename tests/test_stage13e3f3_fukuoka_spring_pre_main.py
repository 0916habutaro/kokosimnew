from __future__ import annotations

import csv
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "data/schedules/2026/competition_stage_calendar.csv"
QUEUE = ROOT / "data/research/2026/research_pending_queue.csv"
MAIN = ROOT / "data/schedules/2026/season_calendar.csv"

EXPECTED_MATCH_DATES = [
    "2026-03-20",
    "2026-03-21",
    "2026-03-22",
    "2026-03-23",
    "2026-03-24",
    "2026-03-26",
    "2026-03-27",
    "2026-03-28",
    "2026-03-29",
    "2026-03-30",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class Stage13E3F3FukuokaSpringPreMainTests(unittest.TestCase):
    def test_only_actual_match_days_are_registered(self):
        stage = {row["stage_calendar_id"]: row for row in read_rows(STAGE)}[
            "SC2026045"
        ]
        self.assertEqual("CMP000147", stage["competition_id"])
        self.assertEqual("STG000196", stage["stage_id"])
        self.assertEqual("BRANCH_QUALIFIER", stage["stage_code"])
        self.assertEqual("verified", stage["date_status"])
        self.assertEqual("not_structured_separately", stage["calendar_relation"])
        dates = stage["date_list"].split(";")
        self.assertEqual(EXPECTED_MATCH_DATES, dates)
        self.assertEqual(len(dates), len(set(dates)))
        self.assertNotIn("2026-03-25", dates)

    def test_main_dates_remain_separate_and_unchanged(self):
        main = {row["competition_id"]: row for row in read_rows(MAIN)}[
            "CMP000147"
        ]
        stage = {row["stage_calendar_id"]: row for row in read_rows(STAGE)}[
            "SC2026045"
        ]
        self.assertEqual("2026-04-02", main["start_date"])
        self.assertEqual("2026-04-06", main["end_date"])
        self.assertEqual(
            ["2026-04-02", "2026-04-05", "2026-04-06"],
            main["game_date_list"].split(";"),
        )
        self.assertEqual("official_schedule", main["calendar_status"])
        self.assertTrue(
            set(stage["date_list"].split(";")).isdisjoint(
                set(main["game_date_list"].split(";"))
            )
        )

    def test_fukuoka_resolved_and_only_hokkaido_pending(self):
        queue = {row["task_id"]: row for row in read_rows(QUEUE)}
        stages = {row["stage_calendar_id"]: row for row in read_rows(STAGE)}
        self.assertEqual("resolved", queue["RS2026021"]["status"])
        self.assertEqual("verified", stages["SC2026045"]["date_status"])
        self.assertEqual("resolved", queue["RS2026001"]["status"])
        self.assertEqual("verified", stages["SC2026001"]["date_status"])
        pending = [
            row["stage_calendar_id"]
            for row in stages.values()
            if row["date_status"] == "research_pending"
        ]
        self.assertEqual([], pending)


if __name__ == "__main__":
    unittest.main()
