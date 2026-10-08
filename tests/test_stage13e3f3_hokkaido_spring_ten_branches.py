from __future__ import annotations

import csv
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "data/schedules/2026/competition_stage_calendar.csv"
QUEUE = ROOT / "data/research/2026/research_pending_queue.csv"
MAIN = ROOT / "data/schedules/2026/season_calendar.csv"
REPORT = ROOT / "docs/research/stage13e3f3_hokkaido_spring_20261008.md"
EXPECTED_DATES = [f"2026-05-{day:02d}" for day in range(8, 18)]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class Stage13E3F3HokkaidoSpringTenBranchesTests(unittest.TestCase):
    def test_hokkaido_has_ten_verified_actual_match_dates(self):
        by_id = {r["stage_calendar_id"]: r for r in read_rows(STAGE)}
        stage = by_id["SC2026001"]
        self.assertEqual("CMP000004", stage["competition_id"])
        self.assertEqual("STG000163", stage["stage_id"])
        self.assertEqual("BRANCH_QUALIFIER", stage["stage_code"])
        self.assertEqual("verified", stage["date_status"])
        self.assertEqual(
            "not_structured_separately", stage["calendar_relation"]
        )
        self.assertEqual(EXPECTED_DATES, stage["date_list"].split(";"))
        self.assertEqual(
            len(EXPECTED_DATES), len(set(stage["date_list"].split(";")))
        )

    def test_pre_main_and_main_dates_are_disjoint(self):
        stage = {r["stage_calendar_id"]: r for r in read_rows(STAGE)}[
            "SC2026001"
        ]
        main = {r["competition_id"]: r for r in read_rows(MAIN)}[
            "CMP000004"
        ]
        self.assertEqual("2026-05-25", main["start_date"])
        self.assertEqual("2026-05-31", main["end_date"])
        self.assertEqual(
            [
                "2026-05-25",
                "2026-05-26",
                "2026-05-27",
                "2026-05-28",
                "2026-05-30",
                "2026-05-31",
            ],
            main["game_date_list"].split(";"),
        )
        self.assertEqual("official_schedule", main["calendar_status"])
        self.assertTrue(
            set(stage["date_list"].split(";")).isdisjoint(
                set(main["game_date_list"].split(";"))
            )
        )

    def test_all_pre_main_stage_calendars_are_verified(self):
        stages = read_rows(STAGE)
        self.assertEqual(50, len(stages))
        self.assertEqual(0, sum(r["date_status"] == "research_pending" for r in stages))
        self.assertTrue(all(r["date_status"] == "verified" for r in stages))
        queue = read_rows(QUEUE)
        stage_tasks = [r for r in queue if r["task_type"] == "stage_calendar"]
        self.assertEqual(0, sum(r["status"] != "resolved" for r in stage_tasks))
        hokkaido = {r["task_id"]: r for r in queue}["RS2026001"]
        self.assertEqual("resolved", hokkaido["status"])

    def test_official_daily_sources_for_every_registered_day(self):
        report = REPORT.read_text(encoding="utf-8")
        for day in range(8, 18):
            with self.subTest(day=day):
                self.assertIn(
                    f"newsflash_1_202605{day:02d}.html", report
                )
        for branch in (
            "函館", "室蘭", "札幌", "小樽", "空知",
            "旭川", "名寄", "北見", "十勝", "釧根",
        ):
            with self.subTest(branch=branch):
                self.assertIn(branch, report)


if __name__ == "__main__":
    unittest.main()
