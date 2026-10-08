from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import unittest
from pathlib import Path

from phase2_engine import (
    AnnualCompetitionInput,
    DEPENDENCY_ACTIVE,
    DEPENDENCY_BLOCKED_DATE,
    DEPENDENCY_COMPLETED,
    DEPENDENCY_WAITING,
    DataRepository,
    LiveSeasonDependencyRuntimeState,
    StructuralAnnualInputFactory,
    TournamentEngine,
    load_competition_stage_calendar,
    stage_date_lists_by_competition,
    validate_competition_stage_calendar,
)
from phase2_engine.browse_views import (
    load_season_calendar,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class Stage13E3D1LiveDependencyCalendarTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.year = 2026
        cls.seed = 2026100820
        cls.factory = StructuralAnnualInputFactory(
            cls.repo,
            DATA_ROOT,
            cls.seed,
        )
        cls.calendar_rows = load_season_calendar(
            DATA_ROOT
        )
        cls.calendar_by_comp = {
            row["competition_id"]: row
            for row in cls.calendar_rows
        }
        cls.stage_calendar_rows = (
            load_competition_stage_calendar(
                DATA_ROOT,
                year=cls.year,
            )
        )

    def _summer_annual(
        self,
        competition_id: str,
        seed_offset: int,
    ) -> AnnualCompetitionInput:
        return AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=(
                self.factory.summer_area_school_ids(
                    competition_id,
                    self.year,
                )
            ),
            rng_seed=self.seed + seed_offset,
        )

    def _autumn_template(
        self,
        competition_id: str,
        seed_offset: int,
    ) -> AnnualCompetitionInput:
        return self.factory.build_prefectural(
            competition_id,
            self.year,
            rng_seed=self.seed + seed_offset,
        )

    @staticmethod
    def _daily_dates(
        start: str,
        count: int,
    ) -> list[str]:
        first = date.fromisoformat(start)
        return [
            (
                first
                + timedelta(days=index)
            ).isoformat()
            for index in range(count)
        ]

    def test_stage_calendar_covers_all_pre_main_stages(
        self,
    ):
        summary = (
            validate_competition_stage_calendar(
                self.repo,
                self.stage_calendar_rows,
                year=self.year,
            )
        )
        self.assertEqual(
            50,
            summary["pre_main_stage_count"],
        )
        self.assertEqual(
            50,
            summary["row_count"],
        )
        self.assertEqual(
            36,
            summary["verified_count"],
        )
        self.assertEqual(
            14,
            summary["research_pending_count"],
        )
        self.assertEqual(
            27,
            summary[
                "calendar_relation_counts"
            ][
                "explicitly_excluded_from_main_calendar"
            ],
        )

    def test_pending_stage_calendar_maps_to_empty_dates(
        self,
    ):
        mapping = (
            stage_date_lists_by_competition(
                self.stage_calendar_rows,
                include_pending=True,
            )
        )
        self.assertIn("CMP000004", mapping)
        self.assertEqual(
            [],
            mapping["CMP000004"][
                "BRANCH_QUALIFIER"
            ],
        )
        self.assertEqual(
            [],
            mapping["CMP000095"][
                "BRANCH_QUALIFIER"
            ],
        )

    def test_pending_stage_dates_do_not_consume_main_calendar(
        self,
    ):
        summer = self._summer_annual(
            "CMP000029",
            1,
        )
        autumn = self._autumn_template(
            "CMP000077",
            2,
        )
        pending_stage_rows = deepcopy(
            self.stage_calendar_rows
        )
        for row in pending_stage_rows:
            if row["competition_id"] == "CMP000077":
                row["date_list"] = ""
                row["date_status"] = "research_pending"

        state = (
            LiveSeasonDependencyRuntimeState
            .from_annual_templates(
                engine=TournamentEngine(
                    self.repo
                ),
                repo=self.repo,
                annual_templates=[
                    summer,
                    autumn,
                ],
                calendar_rows=[
                    self.calendar_by_comp[
                        "CMP000029"
                    ],
                    self.calendar_by_comp[
                        "CMP000077"
                    ],
                ],
                rng_seed=self.seed,
                start_date="2026-07-01",
                stage_calendar_rows=(
                    pending_stage_rows
                ),
            )
        )

        self.assertEqual(
            DEPENDENCY_WAITING,
            state.dependency_state(
                "CMP000077"
            )["status"],
        )
        state.advance_through(
            "2026-07-28"
        )
        destination = state.dependency_state(
            "CMP000077"
        )
        self.assertTrue(
            destination["is_active"]
        )
        self.assertGreater(
            destination[
                "calendar_gap_count"
            ],
            0,
        )
        scheduled = state.competitions[
            "CMP000077"
        ]
        self.assertEqual(
            "",
            scheduled.next_scheduled_date(),
        )
        self.assertTrue(
            scheduled.calendar_gap_matches()
        )
        self.assertTrue(all(
            row["stage_code"]
            == "BRANCH_QUALIFIER"
            for row in (
                scheduled.calendar_gap_matches()
            )
        ))

    def test_miyagi_summer_winner_activates_autumn_direct_entry(
        self,
    ):
        summer = self._summer_annual(
            "CMP000029",
            3,
        )
        autumn = self._autumn_template(
            "CMP000077",
            4,
        )
        branch_dates = self._daily_dates(
            "2026-08-10",
            20,
        )
        state = (
            LiveSeasonDependencyRuntimeState
            .from_annual_templates(
                engine=TournamentEngine(
                    self.repo
                ),
                repo=self.repo,
                annual_templates=[
                    summer,
                    autumn,
                ],
                calendar_rows=[
                    self.calendar_by_comp[
                        "CMP000029"
                    ],
                    self.calendar_by_comp[
                        "CMP000077"
                    ],
                ],
                rng_seed=self.seed,
                start_date="2026-07-01",
                stage_calendar_rows=(
                    self.stage_calendar_rows
                ),
                stage_date_lists_by_competition_override={
                    "CMP000077": {
                        "BRANCH_QUALIFIER": (
                            branch_dates
                        ),
                    },
                },
            )
        )

        self.assertIn(
            "CMP000029",
            state.competitions,
        )
        self.assertNotIn(
            "CMP000077",
            state.competitions,
        )
        self.assertEqual(
            DEPENDENCY_WAITING,
            state.dependency_state(
                "CMP000077"
            )["status"],
        )

        state.advance_through(
            "2026-07-27"
        )
        self.assertNotIn(
            "CMP000077",
            state.competitions,
        )
        state.advance_through(
            "2026-07-28"
        )

        source_run = state.completed_runs()[
            "CMP000029"
        ]
        champion = (
            source_run.outcome
            .champion_school_id
        )
        self.assertTrue(champion)
        self.assertIn(
            "CMP000077",
            state.competitions,
        )
        destination = state.competitions[
            "CMP000077"
        ]
        self.assertIn(
            champion,
            destination.runtime.annual
            .direct_main_entry_school_ids,
        )
        self.assertEqual(
            "2026-07-28",
            state.dependency_state(
                "CMP000077"
            )["activated_on"],
        )
        resolution = next(
            row
            for row in state.resolutions
            if row.access_rule_id
            == "ACR000002"
        )
        self.assertEqual(
            "PASS",
            resolution.status,
        )
        self.assertEqual(
            (champion,),
            resolution.resolved_school_ids,
        )

        state.advance_through(
            "2026-09-23"
        )
        self.assertEqual(
            DEPENDENCY_COMPLETED,
            state.dependency_state(
                "CMP000077"
            )["status"],
        )
        lazy = state.completed_runs()[
            "CMP000077"
        ]

        expected_annual = deepcopy(
            autumn
        )
        expected_annual.direct_main_entry_school_ids = [
            champion
        ]
        if (
            champion
            not in expected_annual
            .entrant_school_ids
        ):
            expected_annual.entrant_school_ids.append(
                champion
            )
        legacy = TournamentEngine(
            self.repo
        ).run(expected_annual)
        self.assertEqual(
            legacy.to_dict(),
            lazy.to_dict(),
        )

    def test_mie_summer_winner_becomes_seed_event_bypass(
        self,
    ):
        summer = self._summer_annual(
            "CMP000045",
            5,
        )
        autumn = self._autumn_template(
            "CMP000116",
            6,
        )
        seed_dates = self._daily_dates(
            "2026-08-01",
            20,
        )
        state = (
            LiveSeasonDependencyRuntimeState
            .from_annual_templates(
                engine=TournamentEngine(
                    self.repo
                ),
                repo=self.repo,
                annual_templates=[
                    summer,
                    autumn,
                ],
                calendar_rows=[
                    self.calendar_by_comp[
                        "CMP000045"
                    ],
                    self.calendar_by_comp[
                        "CMP000116"
                    ],
                ],
                rng_seed=self.seed,
                start_date="2026-07-01",
                stage_calendar_rows=(
                    self.stage_calendar_rows
                ),
                stage_date_lists_by_competition_override={
                    "CMP000116": {
                        "SEED_EVENT": seed_dates,
                    },
                },
            )
        )
        state.advance_through(
            "2026-07-27"
        )

        source_run = state.completed_runs()[
            "CMP000045"
        ]
        champion = (
            source_run.outcome
            .champion_school_id
        )
        destination = state.competitions[
            "CMP000116"
        ]
        self.assertIn(
            champion,
            destination.runtime.annual
            .seed_event_bypass_school_ids,
        )
        self.assertNotIn(
            champion,
            destination.runtime.annual
            .direct_main_entry_school_ids,
        )
        resolution = next(
            row
            for row in state.resolutions
            if row.access_rule_id
            == "ACR000014"
        )
        self.assertEqual(
            "PASS",
            resolution.status,
        )

        state.advance_through(
            "2026-09-27"
        )
        lazy = state.completed_runs()[
            "CMP000116"
        ]
        expected_annual = deepcopy(
            autumn
        )
        expected_annual.seed_event_bypass_school_ids = [
            champion
        ]
        if (
            champion
            not in expected_annual
            .entrant_school_ids
        ):
            expected_annual.entrant_school_ids.append(
                champion
            )
        legacy = TournamentEngine(
            self.repo
        ).run(expected_annual)
        self.assertEqual(
            legacy.to_dict(),
            lazy.to_dict(),
        )

    def test_destination_is_blocked_when_first_stage_date_precedes_source_completion(
        self,
    ):
        summer = self._summer_annual(
            "CMP000029",
            7,
        )
        autumn = self._autumn_template(
            "CMP000077",
            8,
        )
        invalid_branch_dates = self._daily_dates(
            "2026-07-20",
            10,
        )
        state = (
            LiveSeasonDependencyRuntimeState
            .from_annual_templates(
                engine=TournamentEngine(
                    self.repo
                ),
                repo=self.repo,
                annual_templates=[
                    summer,
                    autumn,
                ],
                calendar_rows=[
                    self.calendar_by_comp[
                        "CMP000029"
                    ],
                    self.calendar_by_comp[
                        "CMP000077"
                    ],
                ],
                rng_seed=self.seed,
                start_date="2026-07-01",
                stage_calendar_rows=(
                    self.stage_calendar_rows
                ),
                stage_date_lists_by_competition_override={
                    "CMP000077": {
                        "BRANCH_QUALIFIER": (
                            invalid_branch_dates
                        ),
                    },
                },
            )
        )
        state.advance_through(
            "2026-07-28"
        )
        dep = state.dependency_state(
            "CMP000077"
        )
        self.assertEqual(
            DEPENDENCY_BLOCKED_DATE,
            dep["status"],
        )
        self.assertFalse(dep["is_active"])
        self.assertNotIn(
            "CMP000077",
            state.competitions,
        )

    def test_public_snapshot_does_not_expose_destination_before_dependency_completion(
        self,
    ):
        state = (
            LiveSeasonDependencyRuntimeState
            .from_annual_templates(
                engine=TournamentEngine(
                    self.repo
                ),
                repo=self.repo,
                annual_templates=[
                    self._summer_annual(
                        "CMP000029",
                        9,
                    ),
                    self._autumn_template(
                        "CMP000077",
                        10,
                    ),
                ],
                calendar_rows=[
                    self.calendar_by_comp[
                        "CMP000029"
                    ],
                    self.calendar_by_comp[
                        "CMP000077"
                    ],
                ],
                rng_seed=self.seed,
                start_date="2026-07-01",
                stage_calendar_rows=(
                    self.stage_calendar_rows
                ),
            )
        )
        snapshot = state.public_snapshot()
        self.assertIn(
            "CMP000029",
            snapshot["active_competitions"],
        )
        self.assertNotIn(
            "CMP000077",
            snapshot["active_competitions"],
        )
        self.assertEqual(
            DEPENDENCY_WAITING,
            snapshot["dependencies"][
                "CMP000077"
            ]["status"],
        )
        self.assertEqual(
            [],
            snapshot["resolutions"],
        )


if __name__ == "__main__":
    unittest.main()
