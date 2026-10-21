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

    def test_autumn_chain_including_jingu_completes(self):
        summary = self.audit.summary()

        self.assertEqual(162, summary["completed_competition_count"])
        self.assertGreater(summary["completed_match_count"], 10308)
        self.assertEqual({"complete": 162}, summary["blocker_counts"])
        self.assertEqual(
            [],
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
        self.assertEqual(0, summary["pending_stage_row_count"])
        self.assertEqual(
            {},
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

    def test_jingu_is_played_within_its_event_period(self):
        # 試合ごとの日付がデータにないので、開催期間の各日を試合日の候補にする
        jingu = next(
            row
            for row in self.audit.competition_rows
            if row.competition_id == "CMP000003"
        )
        self.assertEqual("complete", jingu.blocker_kind)
        self.assertEqual(0, jingu.calendar_gap_count)
        self.assertNotIn(
            "structure:CMP000003",
            {row.action_id for row in self.audit.action_rows},
        )

if __name__ == "__main__":
    unittest.main()
