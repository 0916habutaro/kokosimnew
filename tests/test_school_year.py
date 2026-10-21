from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

from phase2_engine import DataRepository
from phase2_engine.live_season_planner import LiveSeasonGraphPlanner
from phase2_engine.live_season_save import create_live_season_save
from phase2_engine.school_year import (
    in_school_year,
    school_year_end,
    school_year_start,
)
from phase2_engine.year_transition import year_end_readiness


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


class SchoolYearBoundaryTests(unittest.TestCase):
    def test_school_year_runs_from_april_to_next_march(self):
        self.assertEqual(date(2026, 4, 1), school_year_start(2026))
        self.assertEqual(date(2027, 3, 31), school_year_end(2026))
        self.assertTrue(in_school_year(2026, date(2027, 2, 1)))
        self.assertFalse(in_school_year(2026, date(2026, 3, 31)))
        self.assertFalse(in_school_year(2026, date(2027, 4, 1)))


class SchoolYearRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = LiveSeasonGraphPlanner(
            DataRepository(DATA_ROOT),
            DATA_ROOT,
            2026102101,
            year=2026,
        ).build_plan()

    def test_default_start_is_april_first_with_march_games_already_played(
        self,
    ):
        state = self.plan.build_runtime()

        self.assertEqual(date(2026, 4, 1), state.start_date)
        self.assertEqual(date(2026, 4, 1), state.current_date)
        self.assertEqual(date(2027, 3, 31), state.end_date)
        # Senbatsu (March) is finished before the first playable day.
        self.assertEqual(
            "completed",
            state.status_by_competition["CMP000001"],
        )
        prestart_dates = [
            item["date"]
            for item in state.history
            if item["action"] == "play_prestart"
        ]
        self.assertTrue(prestart_dates)
        self.assertLess(max(prestart_dates), "2026-04-01")
        self.assertFalse([
            item
            for item in state.history
            if item["action"] == "play_today"
        ])
        save = create_live_season_save(self.plan, state)
        self.assertEqual("2026-04-01", save["start_date"])
        self.assertEqual([], save["processed_dates"])

    def test_start_date_must_be_inside_school_year(self):
        with self.assertRaises(ValueError):
            self.plan.build_runtime(start_date="2026-03-31")
        with self.assertRaises(ValueError):
            self.plan.build_runtime(start_date="2027-04-01")

    def test_clock_stops_at_end_of_march(self):
        state = self.plan.build_runtime()
        with self.assertRaises(ValueError):
            state.advance_to("2027-04-01")
        # Jumping the clock directly keeps this test fast.
        state.current_date = date(2027, 3, 31)
        with self.assertRaises(ValueError):
            state.next_day()

    def test_year_end_is_march_31_of_next_year(self):
        state = self.plan.build_runtime()
        self.assertIn(
            "current_date_not_year_end",
            year_end_readiness(state)["blockers"],
        )
        state.current_date = date(2027, 3, 31)
        self.assertNotIn(
            "current_date_not_year_end",
            year_end_readiness(state)["blockers"],
        )


if __name__ == "__main__":
    unittest.main()
