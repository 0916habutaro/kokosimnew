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
        noncomplete = [
            row.to_dict()
            for row in audit.competition_rows
            if row.blocker_kind != "complete"
        ]
        self.assertEqual(
            {},
            {
                "summary": audit.summary(),
                "noncomplete": noncomplete,
                "actions": [
                    row.to_dict()
                    for row in audit.action_rows
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()
