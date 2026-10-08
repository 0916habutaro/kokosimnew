from __future__ import annotations

import csv
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
STAGES = ROOT / "data/schedules/2026/competition_stage_calendar.csv"
QUEUE = ROOT / "data/research/2026/research_pending_queue.csv"
MAIN = ROOT / "data/schedules/2026/season_calendar.csv"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class Stage13E3F3TokyoSpringPreliminaryTests(unittest.TestCase):
    def test_tokyo_preliminary_has_only_five_result_dates(self):
        stage = {r["stage_calendar_id"]: r for r in rows(STAGES)}["SC2026018"]
        self.assertEqual("CMP000094", stage["competition_id"])
        self.assertEqual("STG000209", stage["stage_id"])
        self.assertEqual("PRELIMINARY_QUALIFIER", stage["stage_code"])
        self.assertEqual("verified", stage["date_status"])
        self.assertEqual(
            "not_structured_separately", stage["calendar_relation"]
        )
        self.assertEqual(
            [
                "2026-03-14",
                "2026-03-15",
                "2026-03-20",
                "2026-03-21",
                "2026-03-22",
            ],
            stage["date_list"].split(";"),
        )

    def test_tokyo_preliminary_does_not_consume_main_calendar(self):
        stage = {r["stage_calendar_id"]: r for r in rows(STAGES)}["SC2026018"]
        main = {r["competition_id"]: r for r in rows(MAIN)}["CMP000094"]
        self.assertEqual("2026-04-01", main["start_date"])
        self.assertEqual("2026-05-03", main["end_date"])
        self.assertEqual("official_schedule", main["calendar_status"])
        stage_dates = set(stage["date_list"].split(";"))
        main_dates = set(main["game_date_list"].split(";"))
        self.assertTrue(stage_dates.isdisjoint(main_dates))

    def test_pending_queue_retains_other_pending_entries(self):
        queue = {r["task_id"]: r for r in rows(QUEUE)}
        stages = {r["stage_calendar_id"]: r for r in rows(STAGES)}
        self.assertEqual("resolved", queue["RS2026009"]["status"])
        self.assertEqual("verified", stages["SC2026018"]["date_status"])
        self.assertEqual("resolved", queue["RS2026021"]["status"])
        self.assertEqual("verified", stages["SC2026045"]["date_status"])
        self.assertEqual("needs_research", queue["RS2026001"]["status"])
        self.assertEqual("research_pending", stages["SC2026001"]["date_status"])
        self.assertEqual(
            1,
            sum(r["date_status"] == "research_pending" for r in stages.values()),
        )


if __name__ == "__main__":
    unittest.main()
