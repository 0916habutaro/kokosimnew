from __future__ import annotations

import unittest
from pathlib import Path

from phase2_engine import (
    DataRepository,
    LiveSeasonGraphPlanner,
    PLAN_ACCESS,
    PLAN_QUALIFICATION,
    PLAN_REGIONAL_FEEDER,
    PLAN_ROOT,
    STRATEGY_DEFERRED_STRUCTURAL,
    STRATEGY_DEPENDENCY_AGGREGATE,
    STRATEGY_SENBATSU_BOOTSTRAP,
    STRATEGY_STRUCTURAL,
    STRATEGY_SUMMER_AREA,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class Stage13E3D3FullSeasonPlannerTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.seed = 2026100822
        cls.planner = LiveSeasonGraphPlanner(
            cls.repo,
            DATA_ROOT,
            cls.seed,
            year=2026,
        )
        cls.plan = cls.planner.build_plan()

    def test_plan_covers_all_162_competitions(
        self,
    ):
        summary = self.plan.summary()

        self.assertEqual(
            162,
            summary["competition_count"],
        )
        self.assertEqual(
            162,
            summary["template_count"],
        )
        self.assertEqual(
            162,
            summary["calendar_count"],
        )
        self.assertEqual(
            162,
            summary["topological_count"],
        )
        self.assertEqual(
            165,
            summary["dependency_edge_count"],
        )
        self.assertEqual(
            {
                STRATEGY_DEFERRED_STRUCTURAL: 13,
                STRATEGY_DEPENDENCY_AGGREGATE: 18,
                STRATEGY_SENBATSU_BOOTSTRAP: 1,
                STRATEGY_STRUCTURAL: 81,
                STRATEGY_SUMMER_AREA: 49,
            },
            summary["strategy_counts"],
        )
        self.assertEqual(
            {
                PLAN_ACCESS: 13,
                PLAN_QUALIFICATION: 2,
                PLAN_REGIONAL_FEEDER: 16,
                PLAN_ROOT: 131,
            },
            summary[
                "dependency_family_counts"
            ],
        )
        self.assertEqual(
            {
                "autumn": 56,
                "spring": 56,
                "summer": 50,
            },
            summary["season_segment_counts"],
        )
        self.assertEqual(
            15,
            summary[
                "stage_calendar_pending_count"
            ],
        )
        self.assertEqual(
            35,
            summary[
                "stage_calendar_verified_count"
            ],
        )
        self.assertEqual(
            0,
            summary["warning_count"],
        )

    def test_topological_order_respects_every_dependency_edge(
        self,
    ):
        position = {
            cid: index
            for index, cid
            in enumerate(
                self.plan.topological_order
            )
        }
        self.assertEqual(
            set(self.plan.entries),
            set(position),
        )
        for source, destination in (
            self.plan.dependency_edges
        ):
            self.assertLess(
                position[source],
                position[destination],
                f"{source} must precede "
                f"{destination}",
            )

    def test_external_access_rules_are_structurally_bootstrapped(
        self,
    ):
        summary = self.plan.summary()
        self.assertEqual(
            8,
            summary[
                "external_bootstrap_count"
            ],
        )
        self.assertEqual(
            8,
            summary[
                "external_bootstrap_pass_count"
            ],
        )
        self.assertEqual(
            0,
            summary[
                "external_bootstrap_unresolved_count"
            ],
        )
        self.assertTrue(all(
            row.status == "PASS"
            for row in (
                self.plan
                .external_bootstrap_resolutions
            )
        ))

        tokyo_spring = (
            self.plan.annual_templates[
                "CMP000094"
            ]
        )
        self.assertEqual(
            STRATEGY_STRUCTURAL,
            self.plan.entries[
                "CMP000094"
            ].strategy,
        )
        self.assertEqual(
            64,
            len(
                tokyo_spring
                .direct_main_entry_school_ids
            ),
        )

        okinawa_autumn = (
            self.plan.annual_templates[
                "CMP000128"
            ]
        )
        self.assertEqual(
            4,
            len(
                okinawa_autumn
                .direct_main_entry_school_ids
            ),
        )

    def test_same_year_access_destinations_are_deferred_without_placeholders(
        self,
    ):
        tokyo_autumn = (
            self.plan.annual_templates[
                "CMP000016"
            ]
        )
        entry = self.plan.entries[
            "CMP000016"
        ]
        self.assertEqual(
            STRATEGY_DEFERRED_STRUCTURAL,
            entry.strategy,
        )
        self.assertEqual(
            PLAN_ACCESS,
            entry.dependency_family,
        )
        self.assertEqual(
            ("CMP000036", "CMP000037"),
            entry.dependency_source_competition_ids,
        )
        self.assertEqual(
            [],
            tokyo_autumn.entrant_school_ids,
        )
        self.assertEqual(
            [],
            tokyo_autumn
            .direct_main_entry_school_ids,
        )

        hokkaido_spring = (
            self.plan.entries["CMP000004"]
        )
        self.assertEqual(
            STRATEGY_DEFERRED_STRUCTURAL,
            hokkaido_spring.strategy,
        )
        self.assertEqual(
            ("CMP000001",),
            hokkaido_spring
            .dependency_source_competition_ids,
        )

    def test_root_templates_are_generated_without_manual_annual_inputs(
        self,
    ):
        senbatsu = self.plan.annual_templates[
            "CMP000001"
        ]
        self.assertEqual(
            STRATEGY_SENBATSU_BOOTSTRAP,
            self.plan.entries[
                "CMP000001"
            ].strategy,
        )
        self.assertEqual(
            32,
            len(senbatsu.entrant_school_ids),
        )
        self.assertEqual(
            32,
            len(set(
                senbatsu.entrant_school_ids
            )),
        )

        summer = self.plan.annual_templates[
            "CMP000034"
        ]
        self.assertEqual(
            STRATEGY_SUMMER_AREA,
            self.plan.entries[
                "CMP000034"
            ].strategy,
        )
        self.assertGreater(
            len(summer.entrant_school_ids),
            0,
        )

        regional = self.plan.annual_templates[
            "CMP000011"
        ]
        self.assertEqual(
            STRATEGY_DEPENDENCY_AGGREGATE,
            self.plan.entries[
                "CMP000011"
            ].strategy,
        )
        self.assertEqual(
            [],
            regional.entrant_school_ids,
        )

    def test_full_plan_builds_runtime_with_131_roots_and_31_waiting_destinations(
        self,
    ):
        state = self.plan.build_runtime(
            start_date="2026-01-01"
        )
        summary = state.summary()

        self.assertEqual(
            162,
            summary[
                "template_competition_count"
            ],
        )
        self.assertEqual(
            135,
            summary["active_runtime_count"],
        )
        self.assertEqual(
            {
                "active": 135,
                "waiting_dependencies": 27,
            },
            summary["status_counts"],
        )
        self.assertNotIn(
            "CMP000002",
            state.competitions,
        )
        self.assertNotIn(
            "CMP000016",
            state.competitions,
        )
        self.assertIn(
            "CMP000001",
            state.competitions,
        )
        self.assertIn(
            "CMP000034",
            state.competitions,
        )
        # The spring access benefit depends on Senbatsu participants,
        # not on the tournament winner or its completion date.
        self.assertIn(
            "CMP000113",
            state.competitions,
        )
        self.assertIn(
            "CMP000095",
            state.competitions,
        )
        self.assertNotIn(
            "CMP000002",
            state.competitions,
        )

    def test_full_plan_automatically_materializes_summer_national_and_tokyo_autumn(
        self,
    ):
        state = self.plan.build_runtime(
            start_date="2026-01-01"
        )
        state.advance_through(
            "2026-08-05"
        )

        self.assertIn(
            "CMP000002",
            state.competitions,
        )
        summer_national = state.competitions[
            "CMP000002"
        ]
        self.assertEqual(
            49,
            len(
                summer_national
                .runtime.entrant_school_ids
            ),
        )
        self.assertEqual(
            49,
            len(set(
                summer_national
                .runtime.entrant_school_ids
            )),
        )

        self.assertIn(
            "CMP000016",
            state.competitions,
        )
        tokyo_autumn = state.competitions[
            "CMP000016"
        ]
        annual = tokyo_autumn.runtime.annual
        self.assertEqual(
            2,
            len(
                annual
                .direct_main_entry_school_ids
            ),
        )
        self.assertEqual(
            232,
            len(annual.entrant_school_ids),
        )
        self.assertTrue(
            set(
                annual
                .direct_main_entry_school_ids
            ).issubset(
                set(annual.entrant_school_ids)
            )
        )
        self.assertEqual(
            0,
            tokyo_autumn.summary()[
                "calendar_gap_count"
            ],
        )
        self.assertEqual(
            "2026-09-12",
            tokyo_autumn.next_scheduled_date(),
        )


if __name__ == "__main__":
    unittest.main()
