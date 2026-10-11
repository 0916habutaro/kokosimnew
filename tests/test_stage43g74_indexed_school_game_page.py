"""Stage43G-74: school/year/competition indexed saved game pagination.

Uses actual persisted score-only synthetic fixtures and an independent real
Option-A archive fixture; no generated score is an official game result.
"""
from __future__ import annotations

from hashlib import sha256
import sqlite3
from pathlib import Path
import tempfile
import unittest

from phase2_engine.career_history_scale_benchmark import (
    build_synthetic_archive, file_sha256,
)
from phase2_engine.career_indexed_school_game_page import (
    IndexedSchoolGamePageConflict, read_indexed_school_game_page,
)
from phase2_engine.career_longitudinal_read import (
    CareerHistoryViewConflict, CareerLongitudinalReadModel,
)
import test_stage43g14_player_records as real_a_fixture


class Stage43G74IndexedSchoolGamePageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "historical_matches.sqlite3"
        self.roster = Path(self.tmp.name) / "no_roster_created.sqlite3"
        built = build_synthetic_archive(
            self.path, schools=8, years=4, games_per_school_year=4,
        )
        self.assertEqual(128, built["match_rows"])
        self.school = "BENCH-SCH-0001"
        self.away = "BENCH-OPP-0001"
        self.model = CareerLongitudinalReadModel(self.path, self.roster)

    def test_year_competition_school_page_only_requested_records(self):
        before = file_sha256(self.path)
        page = self.model.school_game_page(
            self.school, start_year=2027, end_year=2028,
            competition_id="BENCH-CMP-A", limit=2,
        )
        self.assertEqual(4, page["total"])
        self.assertEqual(2, len(page["records"]))
        self.assertEqual(
            [2027, 2027], [r["year"] for r in page["records"]],
        )
        self.assertTrue(all(
            r["competition_id"] == "BENCH-CMP-A"
            and r["opponent_school_id"] == self.away
            and r["result_for_school"] == "win"
            for r in page["records"]
        ))
        second = self.model.school_game_page(
            self.school, start_year=2027, end_year=2028,
            competition_id="BENCH-CMP-A", limit=2, offset=2,
        )
        self.assertEqual(
            4, len(page["records"] + second["records"]),
        )
        self.assertEqual(2028, second["records"][0]["year"])
        self.assertEqual([], self.model.school_game_page(
            self.school, start_year=2027, end_year=2028,
            competition_id="BENCH-CMP-A", limit=2, offset=4,
        )["records"])
        self.assertEqual(before, file_sha256(self.path))
        self.assertFalse(self.roster.exists())
        self.assertFalse(page["all_filtered_window_checksums_verified"])
        self.assertTrue(page["visible_match_checksums_verified"])

    def test_away_team_school_index_and_result_are_correct(self):
        page = self.model.school_game_page(
            self.away, start_year=2026, end_year=2029,
            limit=3, offset=0, verify_scope="filtered_window",
        )
        self.assertEqual(16, page["total"])
        self.assertEqual(3, len(page["records"]))
        self.assertTrue(all(
            r["opponent_school_id"] == self.school
            and r["result_for_school"] == "loss"
            and r["runs_for"] == 1 for r in page["records"]
        ))
        self.assertTrue(page["all_filtered_window_checksums_verified"])

    def test_school_first_competition_seek_uses_both_existing_indexes(self):
        with sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=ro", uri=True,
        ) as conn:
            for col, name in (
                ("team1_id", "idx_history_school1_year"),
                ("team2_id", "idx_history_school2_year"),
            ):
                plan = conn.execute(
                    "EXPLAIN QUERY PLAN SELECT match_id "
                    "FROM historical_matches "
                    f"WHERE {col}=? AND year BETWEEN ? AND ? "
                    "AND competition_id=?",
                    (self.school, 2026, 2029, "BENCH-CMP-A"),
                ).fetchall()
                self.assertTrue(
                    any(name in row[3] for row in plan),
                    (name, plan),
                )
        selected = self.model.school_game_page(
            self.school, start_year=2026, end_year=2029,
            competition_id="BENCH-CMP-A", limit=2, offset=7,
        )
        self.assertEqual(8, selected["total"])
        self.assertEqual(1, len(selected["records"]))

    def test_page_mode_does_not_claim_an_unread_corrupt_match_is_verified(self):
        original = self.model.school_game_page(
            self.school, start_year=2026, end_year=2029,
            limit=1, offset=0,
        )
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE historical_matches SET payload_json='{}' "
                "WHERE year=2029 AND team1_id=?",
                (self.school,),
            )
        before = file_sha256(self.path)
        shallow = self.model.school_game_page(
            self.school, start_year=2026, end_year=2029,
            limit=1, offset=0,
        )
        self.assertEqual(original["records"], shallow["records"])
        self.assertFalse(shallow["all_filtered_window_checksums_verified"])
        with self.assertRaisesRegex(
            IndexedSchoolGamePageConflict, "digest",
        ):
            self.model.school_game_page(
                self.school, start_year=2026, end_year=2029,
                limit=1, offset=0, verify_scope="filtered_window",
            )
        self.assertEqual(before, file_sha256(self.path))
        # Old aggregated school_results keeps its full-window integrity rule.
        with self.assertRaises(CareerHistoryViewConflict):
            self.model.school_results(
                self.school, start_year=2026, end_year=2029,
                limit=1, offset=0,
            )

    def test_selected_tournament_full_scan_scope_not_other_competitions(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='WRONG' "
                "WHERE competition_id='BENCH-CMP-B' AND team1_id=?",
                (self.school,),
            )
        before = file_sha256(self.path)
        scoped = self.model.school_game_page(
            self.school, start_year=2026, end_year=2029,
            competition_id="BENCH-CMP-A", limit=1, offset=7,
            verify_scope="filtered_window",
        )
        self.assertEqual(8, scoped["total"])
        self.assertEqual(1, len(scoped["records"]))
        self.assertTrue(scoped["unselected_competitions_not_verified"])
        with self.assertRaises(IndexedSchoolGamePageConflict):
            self.model.school_game_page(
                self.school, start_year=2026, end_year=2029,
                verify_scope="filtered_window",
            )
        self.assertEqual(before, file_sha256(self.path))

    def test_page_checks_visible_digest_winner_and_original_index_fields(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='BAD' "
                "WHERE year=2026 AND team1_id=?",
                (self.school,),
            )
        before = file_sha256(self.path)
        with self.assertRaises(IndexedSchoolGamePageConflict):
            self.model.school_game_page(
                self.school, start_year=2026, end_year=2026,
                limit=2,
            )
        self.assertEqual(before, file_sha256(self.path))

    def test_real_saved_complete_a_fixture_uses_same_indexed_pages(self):
        fixture = real_a_fixture.Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios",
        )
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        before = file_sha256(fixture.history.db_path)
        pages = CareerLongitudinalReadModel(
            fixture.history, fixture.rosters,
        )
        result = pages.school_game_page(
            fixture.a, start_year=2026, end_year=2027,
            competition_id="CMP000086", limit=1, offset=1,
            verify_scope="filtered_window",
        )
        self.assertEqual(2, result["total"])
        self.assertEqual(2027, result["records"][0]["year"])
        self.assertTrue(result["visible_match_checksums_verified"])
        self.assertEqual(before, file_sha256(fixture.history.db_path))

    def test_missing_and_invalid_selections_are_rejected_or_return_empty(self):
        bad = [
            {"start_year": 2027, "end_year": 2026},
            {"start_year": 0, "end_year": 1},
            {"start_year": 9999, "end_year": 10000},
            {"start_year": True, "end_year": 2029},
            {"start_year": 2026, "end_year": 2029, "competition_id": ""},
            {"start_year": 2026, "end_year": 2029, "competition_id": True},
            {"start_year": 2026, "end_year": 2029, "limit": 0},
            {"start_year": 2026, "end_year": 2029, "limit": 201},
            {"start_year": 2026, "end_year": 2029, "offset": -1},
            {"start_year": 2026, "end_year": 2029, "verify_scope": "all_saves"},
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.model.school_game_page(
                        self.school, **kwargs,
                    )
        missing = read_indexed_school_game_page(
            Path(self.tmp.name) / "absent.sqlite3",
            self.school, start_year=2026, end_year=2026,
        )
        self.assertEqual([], missing["records"])
        self.assertEqual(0, missing["total"])
        self.assertFalse(
            (Path(self.tmp.name) / "absent.sqlite3").exists()
        )
        empty = self.model.school_game_page(
            "UNKNOWN-SCHOOL", start_year=2026, end_year=2029,
        )
        self.assertEqual(0, empty["total"])


if __name__ == "__main__":
    unittest.main()
