from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from phase2_engine import (
    BLOCKER_CALENDAR_GAP,
    BLOCKER_COMPLETE,
    BLOCKER_WAITING_DEPENDENCY,
    DataRepository,
    LiveSeasonGraphPlanner,
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
        print(
            "STAGE13E3F1_SUMMARY",
            json.dumps(
                summary,
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        print(
            "STAGE13E3F1_NONCOMPLETE",
            json.dumps(
                [
                    row.to_dict()
                    for row
                    in self.audit.competition_rows
                    if row.blocker_kind
                    != BLOCKER_COMPLETE
                ],
                ensure_ascii=False,
                sort_keys=True,
            ),
        )

        self.assertEqual(
            "2026-12-31",
            summary["processed_through"],
        )
        self.assertEqual(
            162,
            summary["competition_count"],
        )
        self.assertEqual(
            99,
            summary[
                "completed_competition_count"
            ],
        )
        self.assertEqual(
            63,
            summary[
                "blocked_competition_count"
            ],
        )
        self.assertEqual(
            {
                BLOCKER_CALENDAR_GAP: 47,
                BLOCKER_COMPLETE: 99,
                BLOCKER_WAITING_DEPENDENCY: 16,
            },
            summary["blocker_counts"],
        )
        self.assertEqual(
            49,
            summary[
                "pending_stage_row_count"
            ],
        )
        self.assertEqual(
            47,
            summary[
                "pending_stage_competition_count"
            ],
        )
        self.assertEqual(
            {
                PRIORITY_LOCAL: 1,
                PRIORITY_NATIONAL: 28,
                PRIORITY_REGIONAL: 20,
            },
            summary["priority_counts"],
        )
        self.assertEqual(
            47,
            summary[
                "direct_calendar_gap_competition_count"
            ],
        )
        self.assertEqual(
            16,
            summary[
                "dependency_wait_competition_count"
            ],
        )
        self.assertEqual(
            16,
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
                "CMP000003",
                "CMP000005",
                "CMP000006",
                "CMP000007",
                "CMP000008",
                "CMP000009",
                "CMP000010",
                "CMP000012",
                "CMP000014",
                "CMP000015",
                "CMP000017",
                "CMP000018",
                "CMP000019",
                "CMP000020",
                "CMP000021",
                "CMP000022",
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
            10,
            len(
                jingu
                .unresolved_source_competition_ids
            ),
        )

    def test_every_pending_stage_maps_to_direct_calendar_gap(
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
            47,
            len(pending_competitions),
        )
        for cid in pending_competitions:
            blocker = by_comp[cid]
            self.assertEqual(
                BLOCKER_CALENDAR_GAP,
                blocker.blocker_kind,
                cid,
            )
            self.assertGreater(
                blocker.calendar_gap_count,
                0,
                cid,
            )
            self.assertTrue(
                blocker.pending_stage_ids,
                cid,
            )

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

        self.assertEqual(28, len(p0))
        self.assertEqual(20, len(p1))
        self.assertEqual(1, len(p2))

        self.assertTrue(all(
            row.season_segment == "autumn"
            for row in p0
        ))
        self.assertTrue(all(
            "CMP000003"
            in row.downstream_national_competition_ids
            for row in p0
        ))
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
            BLOCKER_WAITING_DEPENDENCY,
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
                49,
                len(stage_rows),
            )
            self.assertEqual(
                self.audit.summary(),
                summary,
            )
            self.assertEqual(
                PRIORITY_NATIONAL,
                stage_rows[0][
                    "priority_tier"
                ],
            )


if __name__ == "__main__":
    unittest.main()
