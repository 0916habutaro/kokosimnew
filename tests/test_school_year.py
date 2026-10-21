from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

from phase2_engine import DataRepository
from phase2_engine.initial_state import load_prior_results
from phase2_engine.live_season_planner import LiveSeasonGraphPlanner
from phase2_engine.live_season_save import create_live_season_save
from phase2_engine.school_year import (
    competition_school_year,
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

    def test_march_invitational_belongs_to_previous_school_year(self):
        repo = DataRepository(DATA_ROOT)
        senbatsu = repo.competitions["CMP000001"]
        self.assertEqual("2026", senbatsu["reference_year"])
        self.assertEqual(2025, competition_school_year(senbatsu))
        spring = {
            "reference_year": "2026",
            "competition_type": "prefectural_spring",
        }
        self.assertEqual(2026, competition_school_year(spring))


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
        # 2026年3月の選抜は前の年度の大会なので試合をしない（この年度の
        # 選抜は2027年3月）。3月に始まる春季県大会はこの年度の大会として、
        # 開始前の試合で処理する。
        self.assertFalse([
            key
            for key in state.completed_results()
            if "CMP000001" in key
        ])
        # 出場校は秋季地区大会の後に選ぶので、まだ始まっていない
        self.assertNotIn("CMP000001", state.competitions)
        self.assertTrue(
            state.calendar_rows["CMP000001"]["start_date"]
            .startswith("2027-03")
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


class PriorSchoolYearResultsTests(unittest.TestCase):
    """最初の年度の春は、開始前の実際の結果（initial_state）を使う。"""

    @classmethod
    def setUpClass(cls):
        cls.plan = LiveSeasonGraphPlanner(
            DataRepository(DATA_ROOT),
            DATA_ROOT,
            2026102102,
            year=2026,
        ).build_plan()
        cls.prior = load_prior_results(DATA_ROOT, 2026)

    def test_previous_invitational_is_not_played(self):
        # 計画にある選抜は2027年3月の第99回。2026年3月の第98回は入らず、
        # 春季大会はその出場校を実際の結果として使う。
        self.assertTrue(
            self.plan.entries["CMP000001"]
            .calendar_start_date.startswith("2027-03")
        )
        self.assertFalse([
            edge for edge in self.plan.dependency_edges
            if edge[0] == "CMP000001"
        ])
        self.assertEqual(
            tuple(
                school_id
                for school_id, _ in self.prior.senbatsu_entrants
            ),
            self.plan.prior_invitational_entrant_ids,
        )

    def test_prior_year_access_rules_use_actual_results(self):
        resolutions = {
            row.access_rule_id: row
            for row in self.plan.external_bootstrap_resolutions
        }
        for rule_id, ids in self.prior.school_ids_by_rule.items():
            with self.subTest(rule=rule_id):
                row = resolutions[rule_id]
                self.assertEqual("PASS", row.status)
                self.assertEqual(
                    "initial_state_actual",
                    row.resolution_source,
                )
                self.assertEqual(ids, row.resolved_school_ids)
        invitational = [
            row for row in resolutions.values()
            if row.source_event_kind == "national_invitational"
        ]
        self.assertTrue(invitational)
        for row in invitational:
            with self.subTest(rule=row.access_rule_id):
                self.assertEqual("PASS", row.status)
                self.assertEqual(
                    "initial_state_actual",
                    row.resolution_source,
                )
                self.assertTrue(row.resolved_school_ids)
                self.assertTrue(
                    set(row.resolved_school_ids)
                    <= set(self.plan.prior_invitational_entrant_ids)
                )
                annual = self.plan.annual_templates[
                    row.destination_competition_id
                ]
                self.assertTrue(
                    set(row.resolved_school_ids)
                    <= set(annual.direct_main_entry_school_ids)
                )

    def test_regional_feeder_uses_previous_invitational_entrants(self):
        state = self.plan.build_runtime()
        # 九州の春季地区大会は選抜出場校を推薦出場として先に確保する。
        self.assertNotIn(
            "CMP000001",
            state._source_ids_for_destination("CMP000012"),
        )
        _, resolutions, _ = (
            state._resolve_regional_feeder_destination("CMP000012")
        )
        invitational = [
            row for row in resolutions
            if row.source_competition_id == "CMP000001"
        ]
        self.assertEqual(1, len(invitational))
        self.assertEqual("PASS", invitational[0].status)
        self.assertTrue(
            set(invitational[0].resolved_school_ids)
            <= set(self.plan.prior_invitational_entrant_ids)
        )


if __name__ == "__main__":
    unittest.main()
