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
    def test_dump_stage13e3f2_audit(self):
        repo = DataRepository(DATA_ROOT)
        plan = LiveSeasonGraphPlanner(
            repo,
            DATA_ROOT,
            2026100827,
            year=2026,
        ).build_plan()
        audit = audit_full_season_live_runtime(plan)
        noncomplete = {}
        for row in audit.competition_rows:
            if row.blocker_kind == "complete":
                continue
            noncomplete.setdefault(
                row.blocker_kind,
                [],
            ).append({
                "competition_id": (
                    row.competition_id
                ),
                "origin": row.blocker_origin,
                "calendar_gap_count": (
                    row.calendar_gap_count
                ),
                "pending_stage_ids": list(
                    row.pending_stage_ids
                ),
                "unresolved_sources": list(
                    row.unresolved_source_competition_ids
                ),
                "resolution_failures": list(
                    row.resolution_failures
                ),
            })
        residual_gap_details = {}
        for cid in (
            "CMP000112",
            "CMP000136",
            "CMP000140",
            "CMP000162",
        ):
            scheduled = audit.state.competitions[
                cid
            ]
            residual_gap_details[cid] = [
                {
                    "match_id": row["match_id"],
                    "stage_code": row["stage_code"],
                    "phase_code": row["phase_code"],
                    "round_no": row["round_no"],
                    "group_id": row["group_id"],
                }
                for row
                in scheduled.calendar_gap_matches()
            ]

        self.maxDiff = None
        self.assertEqual(
            {},
            {
                "summary": audit.summary(),
                "residual_gap_details": (
                    residual_gap_details
                ),
                "noncomplete": noncomplete,
                "actions": [
                    {
                        "id": row.action_id,
                        "type": row.action_type,
                        "priority": (
                            row.priority_tier
                        ),
                        "competition_id": (
                            row.competition_id
                        ),
                        "stage_id": row.stage_id,
                    }
                    for row in audit.action_rows
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()
