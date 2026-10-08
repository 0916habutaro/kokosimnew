from __future__ import annotations

import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine import DataRepository
from phase2_engine.browse_repository import BrowseRepository
from phase2_engine.competition_schedule_runtime import ScheduledCompetitionRuntime
from phase2_engine.ranking_cross_block_2026 import (
    build_verified_2026_cross_block_sidecar,
    hiroshima_2026_qualification_guard,
)
from phase2_engine.ranking_school_reconciliation_2026 import (
    CROSS_AREA, audit_ranking_school_mapping_2026,
)


DATA = Path(__file__).resolve().parents[1] / "data"
SOURCE_FILES = (
    "competitions/2026/post_qualification_rank_school_mapping.csv",
    "competitions/2026/post_qualification_rank_school_aliases.csv",
    "competitions/2026/post_qualification_rank_observations.csv",
    "competitions/2026/post_qualification_cross_block_pairs.csv",
    "competitions/competition_stage_groups.csv",
    "competitions/post_qualification_ranking_profiles.csv",
    "master/schools.csv", "master/baseball_programs.csv",
    "areas/school_area_memberships.csv",
)


class CompleteRuntime:
    is_complete = True


def sidecar(locked=None):
    return build_verified_2026_cross_block_sidecar(
        DATA,
        reference_id="RR20260023",
        locked_school_ids=locked or ["SCH002522", "SCH002479"],
        qualification_locked_on="2026-08-22",
    )


class Stage13E3G6CrossBlock2026Tests(unittest.TestCase):
    def test_cross_block_qualifiers_are_verified_without_area_reassignment(self):
        result = audit_ranking_school_mapping_2026(DATA)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(1, result["verified_cross_block_reference_count"])
        self.assertEqual(CROSS_AREA, "mapped_cross_block_ranking_reference")
        self.assertEqual([{
            "reference_id": "RR20260023",
            "competition_id": "CMP000112",
            "team1_area_id": "AREA000068",
            "team2_area_id": "AREA000067",
        }], result["cross_area_review"])

    def test_explicit_i_j_pair_builds_pending_sidecar_without_historical_winner(self):
        state = sidecar()
        self.assertEqual("XBLOCK_I_J", state.event.group_id)
        self.assertEqual("D20260830", state.event.event_id)
        self.assertEqual(("2026-08-30",), state.match_dates)
        self.assertEqual(
            {"SCH002522", "SCH002479"}, set(state.event.locked_school_ids)
        )
        rows = state.matches_for_date("2026-08-30")
        self.assertEqual(1, len(rows))
        self.assertEqual("pending", rows[0]["status"])
        self.assertEqual("", rows[0]["winner_id"])
        self.assertIsNone(rows[0]["team1_score"])
        self.assertEqual("none", rows[0]["qualifier_effect"])

    def test_can_attach_to_complete_autumn_runtime_without_blocking_main(self):
        from phase2_engine.competition_schedule_runtime import ScheduledCompetitionRuntime
        parent = ScheduledCompetitionRuntime(
            repo=DataRepository(DATA), runtime=CompleteRuntime(),
            competition_id="CMP000112", competition_name="静岡秋",
            calendar_dates=[], stage_date_lists={}, calendar_status="official_schedule",
        )
        state = sidecar()
        parent.attach_ranking_sidecar(state)
        day = parent.matches_for_date("2026-08-30")
        self.assertEqual(1, len(day))
        self.assertEqual("SCH002522", day[0]["team1_id"])
        self.assertTrue(parent.is_complete)
        parent.resolve_ranking_date(
            "2026-08-30",
            winners_by_group={state.instance_key: {
                day[0]["match_id"]: "SCH002479"
            }},
        )
        self.assertTrue(parent.is_complete)
        self.assertEqual("SCH002479", state.event.results[day[0]["match_id"]])
        self.assertEqual(
            ["SCH002522", "SCH002479"],
            list(state.event.locked_school_ids),
        )

    def test_requires_both_already_qualified_and_precise_reference(self):
        with self.assertRaisesRegex(ValueError, "both bracket-block winners"):
            sidecar(["SCH002522", "NOT_QUALIFIED"])
        with self.assertRaisesRegex(ValueError, "cross-block"):
            build_verified_2026_cross_block_sidecar(
                DATA, reference_id="RR20260001",
                locked_school_ids=["SCH002522", "SCH002479"],
                qualification_locked_on="2026-08-22",
            )
        with self.assertRaisesRegex(ValueError, "follow qualification"):
            build_verified_2026_cross_block_sidecar(
                DATA, reference_id="RR20260023",
                locked_school_ids=["SCH002522", "SCH002479"],
                qualification_locked_on="2026-08-30",
            )

    def test_cross_block_snapshot_and_sqlite_can_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            db = BrowseRepository(Path(directory) / "season.sqlite3")
            state = sidecar()
            db.save_ranking_sidecar(2026, state)
            rows = db.competition_ranking_matches(2026, "CMP000112")
            self.assertEqual(1, len(rows))
            self.assertEqual("D20260830", rows[0]["ranking_instance_id"])
            restored = db.load_ranking_sidecar(
                2026, "CMP000112", "XBLOCK_I_J", "D20260830"
            )
            self.assertEqual(state.snapshot(), restored.snapshot())
            mid = restored.matches_for_date("2026-08-30")[0]["match_id"]
            restored.resolve_date("2026-08-30", {mid: "SCH002522"})
            db.save_ranking_sidecar(2026, restored)
            self.assertEqual(
                "completed", db.competition_ranking_matches(
                    2026, "CMP000112"
                )[0]["status"],
            )

    def test_unsubstantiated_bracket_pair_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in SOURCE_FILES:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(DATA / relative, target)
            path = root / "competitions/2026/post_qualification_cross_block_pairs.csv"
            with path.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                fields = list(reader.fieldnames or [])
                rows = list(reader)
            rows[0]["source_block2"] = "K"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            report = audit_ranking_school_mapping_2026(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("cross-block" in error for error in report["errors"]))

    def test_hiroshima_qualifying_games_remain_excluded(self):
        guard = hiroshima_2026_qualification_guard(DATA)
        self.assertTrue(guard["ok"], guard["errors"])
        self.assertEqual([
            "RR20260032", "RR20260033", "RR20260034",
        ], guard["excluded_qualification_reference_ids"])
        self.assertEqual(0, guard["verified_optional_ranking_count"])
        self.assertTrue(guard["needs_full_2026_bracket_outcome_review"])
        self.assertEqual(32, guard["federation_main_berths_per_season"])


if __name__ == "__main__":
    unittest.main()
