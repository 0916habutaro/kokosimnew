from __future__ import annotations

import unittest
from pathlib import Path

from phase2_engine import (
    DataRepository,
    LiveSeasonGraphPlanner,
    audit_full_season_live_runtime,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class Stage13E3F2DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo = DataRepository(DATA_ROOT)
        plan = LiveSeasonGraphPlanner(
            repo,
            DATA_ROOT,
            2026100827,
            year=2026,
        ).build_plan()
        cls.audit = audit_full_season_live_runtime(plan)

    def test_autumn_p0_chain_is_resolved_to_jingu_calendar_only(self):
        summary = self.audit.summary()

        self.assertEqual(160, summary["completed_competition_count"])
        self.assertGreater(summary["completed_match_count"], 10308)
        self.assertEqual(
            {
                "calendar_gap": 2,
                "complete": 160,
            },
            summary["blocker_counts"],
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
                "unique_downstream_blocked_competition_ids"
            ],
        )
        self.assertEqual(1, summary["pending_stage_row_count"])
        self.assertEqual(
            {"P2_local_only": 1},
            summary["priority_counts"],
        )

    def test_all_four_verified_autumn_residuals_are_complete(self):
        by_comp = {
            row.competition_id: row
            for row in self.audit.competition_rows
        }
        for competition_id in (
            "CMP000112",
            "CMP000136",
            "CMP000140",
            "CMP000162",
        ):
            with self.subTest(competition_id=competition_id):
                row = by_comp[competition_id]
                self.assertEqual("complete", row.blocker_kind)
                self.assertEqual(0, row.calendar_gap_count)

    def test_jingu_is_materialized_and_only_missing_its_game_dates(self):
        jingu = next(
            row
            for row in self.audit.competition_rows
            if row.competition_id == "CMP000003"
        )
        self.assertEqual("calendar_gap", jingu.blocker_kind)
        self.assertEqual(
            "calendar_gap_without_pending_stage",
            jingu.blocker_origin,
        )
        self.assertEqual(2, jingu.calendar_gap_count)
        self.assertEqual((), jingu.unresolved_source_competition_ids)

        actions = {
            row.action_id: row
            for row in self.audit.action_rows
        }
        self.assertIn("structure:CMP000003", actions)
        self.assertEqual(
            "review_unmodeled_pre_main_structure",
            actions["structure:CMP000003"].action_type,
        )


if __name__ == "__main__":
    unittest.main()
