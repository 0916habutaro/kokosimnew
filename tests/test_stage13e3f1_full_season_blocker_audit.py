from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from phase2_engine import (
    ACTION_FIX_DEPENDENCY,
    ACTION_REVIEW_STRUCTURE,
    ACTION_VERIFY_STAGE_DATES,
    BLOCKER_BLOCKED,
    BLOCKER_CALENDAR_GAP,
    BLOCKER_COMPLETE,
    BLOCKER_WAITING_DEPENDENCY,
    DataRepository,
    LiveSeasonGraphPlanner,
    ORIGIN_CALENDAR_WITHOUT_STAGE,
    ORIGIN_DEPENDENCY_RESOLUTION,
    ORIGIN_PENDING_STAGE_CALENDAR,
    ORIGIN_UPSTREAM_DEPENDENCY,
    PRIORITY_LOCAL,
    PRIORITY_NATIONAL,
    PRIORITY_REGIONAL,
    audit_full_season_live_runtime,
    save_full_season_live_audit,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class Stage13E3F1FullSeasonBlockerAuditTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.seed = 2026100827
        cls.plan = LiveSeasonGraphPlanner(
            cls.repo,
            DATA_ROOT,
            cls.seed,
            year=2026,
        ).build_plan()
        cls.audit = audit_full_season_live_runtime(
            cls.plan
        )

    def test_year_end_counts_are_exact(
        self,
    ):
        summary = self.audit.summary()

        self.assertEqual(
            "2026-12-31",
            summary["processed_through"],
        )
        self.assertEqual(
            162,
            summary["competition_count"],
        )
        self.assertEqual(
            156,
            summary[
                "completed_competition_count"
            ],
        )
        self.assertEqual(
            6,
            summary[
                "blocked_competition_count"
            ],
        )
        self.assertEqual(
            {
                BLOCKER_CALENDAR_GAP: 4,
                BLOCKER_COMPLETE: 156,
                BLOCKER_WAITING_DEPENDENCY: 2,
            },
            summary["blocker_counts"],
        )
        self.assertEqual(
            {
                ORIGIN_CALENDAR_WITHOUT_STAGE: 1,
                ORIGIN_PENDING_STAGE_CALENDAR: 3,
                ORIGIN_UPSTREAM_DEPENDENCY: 2,
            },
            summary["blocker_origin_counts"],
        )
        self.assertEqual(
            3,
            summary[
                "pending_stage_row_count"
            ],
        )
        self.assertEqual(
            3,
            summary[
                "pending_stage_competition_count"
            ],
        )
        self.assertEqual(
            3,
            summary[
                "pending_stage_reached_row_count"
            ],
        )
        self.assertEqual(
            0,
            summary[
                "pending_stage_blocked_before_reach_row_count"
            ],
        )
        self.assertEqual(
            {
                PRIORITY_LOCAL: 1,
                PRIORITY_REGIONAL: 2,
            },
            summary["priority_counts"],
        )
        self.assertEqual(
            4,
            summary[
                "direct_calendar_gap_competition_count"
            ],
        )
        self.assertEqual(
            2,
            summary[
                "dependency_wait_competition_count"
            ],
        )
        self.assertEqual(
            0,
            summary[
                "runtime_blocked_competition_count"
            ],
        )
        self.assertEqual(
            ["CMP000003"],
            summary[
                "calendar_gap_without_pending_stage_competition_ids"
            ],
        )
        self.assertEqual(
            [],
            summary[
                "dependency_resolution_blocked_competition_ids"
            ],
        )
        self.assertEqual(
            2,
            summary[
                "unique_downstream_blocked_competition_count"
            ],
        )
        self.assertEqual(
            ["CMP000003"],
            summary[
                "blocked_national_competition_ids"
            ],
        )
        self.assertEqual(
            4,
            summary["action_count"],
        )
        self.assertEqual(
            {
                ACTION_REVIEW_STRUCTURE: 1,
                ACTION_VERIFY_STAGE_DATES: 3,
            },
            summary["action_counts"],
        )
        self.assertEqual(
            {
                PRIORITY_LOCAL: 2,
                PRIORITY_REGIONAL: 2,
            },
            summary[
                "action_priority_counts"
            ],
        )
        self.assertGreater(
            summary["completed_match_count"],
            10308,
        )

    def test_waiting_dependency_set_matches_expected_regional_and_jingu_chain(
        self,
    ):
        waiting = {
            row.competition_id
            for row in self.audit.competition_rows
            if row.blocker_kind
            == BLOCKER_WAITING_DEPENDENCY
        }
        self.assertEqual(
            {
                "CMP000006",
                "CMP000012",
            },
            waiting,
        )

        shikoku_spring = next(
            row
            for row
            in self.audit.competition_rows
            if row.competition_id
            == "CMP000011"
        )
        self.assertEqual(
            BLOCKER_COMPLETE,
            shikoku_spring.blocker_kind,
        )

        jingu = next(
            row
            for row
            in self.audit.competition_rows
            if row.competition_id
            == "CMP000003"
        )
        self.assertEqual(
            BLOCKER_CALENDAR_GAP,
            jingu.blocker_kind,
        )
        self.assertEqual(
            ORIGIN_CALENDAR_WITHOUT_STAGE,
            jingu.blocker_origin,
        )
        self.assertEqual(
            (),
            jingu.unresolved_source_competition_ids,
        )
        self.assertEqual(
            2,
            jingu.calendar_gap_count,
        )

    def test_pending_stage_runtime_reachability_is_explicit(
        self,
    ):
        by_comp = {
            row.competition_id: row
            for row
            in self.audit.competition_rows
        }
        pending_competitions = {
            row.competition_id
            for row
            in self.audit.stage_priority_rows
        }
        self.assertEqual(
            3,
            len(pending_competitions),
        )

        blocked_before_stage = {
            row.competition_id
            for row
            in self.audit.stage_priority_rows
            if not row.stage_reached
        }
        self.assertEqual(
            set(),
            blocked_before_stage,
        )

        for cid in (
            pending_competitions
            - blocked_before_stage
        ):
            blocker = by_comp[cid]
            self.assertEqual(
                BLOCKER_CALENDAR_GAP,
                blocker.blocker_kind,
                cid,
            )
            self.assertEqual(
                ORIGIN_PENDING_STAGE_CALENDAR,
                blocker.blocker_origin,
                cid,
            )
            self.assertGreater(
                blocker.calendar_gap_count,
                0,
                cid,
            )

        for cid in blocked_before_stage:
            blocker = by_comp[cid]
            self.assertEqual(
                BLOCKER_BLOCKED,
                blocker.blocker_kind,
            )
            self.assertEqual(
                ORIGIN_DEPENDENCY_RESOLUTION,
                blocker.blocker_origin,
            )
            self.assertTrue(
                blocker.resolution_failures
            )

    def test_non_stage_calendar_gap_and_access_failures_are_separate_actions(
        self,
    ):
        by_comp = {
            row.competition_id: row
            for row
            in self.audit.competition_rows
        }

        akita = by_comp["CMP000079"]
        self.assertEqual(
            BLOCKER_COMPLETE,
            akita.blocker_kind,
        )

        jingu = by_comp["CMP000003"]
        self.assertEqual(
            BLOCKER_CALENDAR_GAP,
            jingu.blocker_kind,
        )
        self.assertEqual(
            ORIGIN_CALENDAR_WITHOUT_STAGE,
            jingu.blocker_origin,
        )
        self.assertEqual(
            (),
            jingu.pending_stage_ids,
        )
        self.assertEqual(
            2,
            jingu.calendar_gap_count,
        )

        kanagawa = by_comp["CMP000095"]
        aichi = by_comp["CMP000113"]
        self.assertEqual((), kanagawa.resolution_failures)
        self.assertEqual((), aichi.resolution_failures)
        self.assertEqual(BLOCKER_COMPLETE, kanagawa.blocker_kind)
        self.assertEqual(BLOCKER_COMPLETE, aichi.blocker_kind)

        action_by_id = {
            row.action_id: row
            for row in self.audit.action_rows
        }
        self.assertEqual(
            ACTION_REVIEW_STRUCTURE,
            action_by_id[
                "structure:CMP000003"
            ].action_type,
        )
        self.assertEqual(
            PRIORITY_LOCAL,
            action_by_id[
                "structure:CMP000003"
            ].priority_tier,
        )
        self.assertNotIn("dependency:CMP000095", action_by_id)
        self.assertNotIn("dependency:CMP000113", action_by_id)

    def test_priority_tiers_follow_dependency_impact(
        self,
    ):
        p0 = [
            row
            for row
            in self.audit.stage_priority_rows
            if row.priority_tier
            == PRIORITY_NATIONAL
        ]
        p1 = [
            row
            for row
            in self.audit.stage_priority_rows
            if row.priority_tier
            == PRIORITY_REGIONAL
        ]
        p2 = [
            row
            for row
            in self.audit.stage_priority_rows
            if row.priority_tier
            == PRIORITY_LOCAL
        ]

        self.assertEqual(0, len(p0))
        self.assertEqual(2, len(p1))
        self.assertEqual(1, len(p2))

        self.assertTrue(all(
            row.season_segment == "spring"
            for row in p1
        ))
        self.assertTrue(all(
            row.downstream_blocked_competition_count
            == 1
            for row in p1
        ))
        self.assertEqual(
            "CMP000004",
            p2[0].competition_id,
        )
        self.assertEqual(
            0,
            p2[0]
            .downstream_blocked_competition_count,
        )

        action_by_id = {
            row.action_id: row
            for row in self.audit.action_rows
        }
        self.assertEqual(
            PRIORITY_LOCAL,
            action_by_id[
                "structure:CMP000003"
            ].priority_tier,
        )

    def test_national_championships_show_summer_complete_and_jingu_blocked(
        self,
    ):
        by_comp = {
            row.competition_id: row
            for row
            in self.audit.competition_rows
        }
        self.assertEqual(
            BLOCKER_COMPLETE,
            by_comp[
                "CMP000001"
            ].blocker_kind,
        )
        self.assertEqual(
            BLOCKER_COMPLETE,
            by_comp[
                "CMP000002"
            ].blocker_kind,
        )
        self.assertEqual(
            BLOCKER_CALENDAR_GAP,
            by_comp[
                "CMP000003"
            ].blocker_kind,
        )

    def test_audit_outputs_machine_readable_csv_and_json(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_full_season_live_audit(
                self.audit,
                tmp,
            )
            with open(
                paths["competition_blockers"],
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                competition_rows = list(
                    csv.DictReader(handle)
                )
            with open(
                paths[
                    "stage_calendar_priorities"
                ],
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                stage_rows = list(
                    csv.DictReader(handle)
                )
            with open(
                paths["blocker_actions"],
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                action_rows = list(
                    csv.DictReader(handle)
                )
            summary = json.loads(
                Path(
                    paths["summary"]
                ).read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(
                162,
                len(competition_rows),
            )
            self.assertEqual(
                3,
                len(stage_rows),
            )
            self.assertEqual(
                4,
                len(action_rows),
            )
            self.assertEqual(
                self.audit.summary(),
                summary,
            )
            self.assertEqual(
                PRIORITY_REGIONAL,
                stage_rows[0][
                    "priority_tier"
                ],
            )
            self.assertIn(
                "structure:CMP000003",
                {
                    row["action_id"]
                    for row in action_rows
                },
            )


if __name__ == "__main__":
    unittest.main()
