from __future__ import annotations

from types import SimpleNamespace
import unittest

from phase2_engine.live_season_dependency import (
    LiveSeasonDependencyRuntimeState,
)


class Stage13E3F3SenbatsuAccessTests(unittest.TestCase):
    def _resolve(self, quota_mode, observed_count, participants):
        prefecture = "14"
        schools = {
            school_id: {"prefecture_code": code}
            for school_id, code in participants
        }
        source = SimpleNamespace(
            is_complete=True,
            to_competition_run=lambda: SimpleNamespace(
                entrant_school_ids=list(schools),
                outcome=None,
            ),
        )
        runtime = LiveSeasonDependencyRuntimeState(
            engine=None,
            repo=SimpleNamespace(schools=schools),
        )
        runtime.competitions["CMP000001"] = source
        rule = {
            "access_rule_id": "ACR000008",
            "destination_competition_id": "CMP000095",
            "destination_prefecture_code": prefecture,
            "source_competition_id_2026": "CMP000001",
            "source_result_selector":
                "participant_from_destination_prefecture",
            "action_type":
                "grant_main_entry_bypass_branch_qualifier",
            "quota_mode": quota_mode,
            "observed_2026_count": str(observed_count),
        }
        return runtime._resolve_rule(rule)

    def test_all_matches_grants_both_generated_entrants(self):
        result = self._resolve(
            "all_matches", 1,
            [("S1", "14"), ("S2", "14"), ("S3", "23")],
        )
        self.assertEqual("PASS", result.status)
        self.assertEqual(("S1", "S2"), result.resolved_school_ids)
        self.assertEqual(2, result.expected_count)

    def test_all_matches_may_match_historical_observation(self):
        result = self._resolve(
            "all_matches", 1,
            [("S1", "14"), ("S3", "23")],
        )
        self.assertEqual("PASS", result.status)
        self.assertEqual(1, result.expected_count)

    def test_fixed_quota_still_rejects_overallocation(self):
        result = self._resolve(
            "fixed", 1,
            [("S1", "14"), ("S2", "14")],
        )
        self.assertEqual("FAIL", result.status)
        self.assertEqual(1, result.expected_count)

    def test_all_matches_does_not_invent_missing_entrants(self):
        result = self._resolve(
            "all_matches", 1,
            [("S3", "23")],
        )
        self.assertEqual("PASS", result.status)
        self.assertEqual((), result.resolved_school_ids)
        self.assertEqual(0, result.expected_count)


if __name__ == "__main__":
    unittest.main()
