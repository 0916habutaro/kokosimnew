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
    PLAN_SELECTION,
    STRATEGY_DEFERRED_STRUCTURAL,
    STRATEGY_DEPENDENCY_AGGREGATE,
    STRATEGY_SENBATSU_SELECTION,
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

        # 2026年3月の選抜は2025年度の大会。2026年度の選抜は2027年3月の第99回。
        self.assertEqual(
            "第99回選抜高等学校野球大会",
            self.plan.entries["CMP000001"].display_name,
        )
        self.assertEqual(
            "2027-03-18",
            self.plan.entries["CMP000001"].calendar_start_date,
        )
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
            171,
            summary["dependency_edge_count"],
        )
        self.assertEqual(
            {
                STRATEGY_DEFERRED_STRUCTURAL: 9,
                STRATEGY_DEPENDENCY_AGGREGATE: 18,
                STRATEGY_SENBATSU_SELECTION: 1,
                STRATEGY_STRUCTURAL: 85,
                STRATEGY_SUMMER_AREA: 49,
            },
            summary["strategy_counts"],
        )
        self.assertEqual(
            {
                PLAN_ACCESS: 9,
                PLAN_QUALIFICATION: 2,
                PLAN_REGIONAL_FEEDER: 16,
                PLAN_ROOT: 134,
                PLAN_SELECTION: 1,
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
            0,
            summary[
                "stage_calendar_pending_count"
            ],
        )
        self.assertEqual(
            50,
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
        # 前年秋の7件・前の年度の選抜の5件・新人戦の1件
        self.assertEqual(
            13,
            summary[
                "external_bootstrap_count"
            ],
        )
        self.assertEqual(
            13,
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
        # 前の年度の選抜の出場校は、計画の段階で直接出場として入る。
        self.assertEqual(
            STRATEGY_STRUCTURAL,
            hokkaido_spring.strategy,
        )
        self.assertEqual(
            (),
            hokkaido_spring
            .dependency_source_competition_ids,
        )
        self.assertEqual(
            1,
            len(
                self.plan.annual_templates[
                    "CMP000004"
                ].direct_main_entry_school_ids
            ),
        )

    def test_root_templates_are_generated_without_manual_annual_inputs(
        self,
    ):
        self.assertEqual(
            32,
            len(set(
                self.plan
                .prior_invitational_entrant_ids
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

    def test_full_plan_builds_runtime_with_134_roots_and_28_waiting_destinations(
        self,
    ):
        state = self.plan.build_runtime()
        summary = state.summary()

        self.assertEqual(
            162,
            summary[
                "template_competition_count"
            ],
        )
        self.assertEqual(
            134,
            summary["active_runtime_count"],
        )
        # March spring competitions finish before the April start.
        self.assertEqual(
            {
                "active": 123,
                "completed": 11,
                "waiting_dependencies": 28,
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
        # 2027年3月の第99回選抜は、秋季地区大会の後に出場校を選ぶ
        self.assertNotIn(
            "CMP000001",
            state.competitions,
        )
        self.assertIn(
            "CMP000034",
            state.competitions,
        )
        # The spring access benefit uses the previous school year's
        # Senbatsu participants, which are known before the season.
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
        state = self.plan.build_runtime()
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
