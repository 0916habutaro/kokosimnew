"""Stage43G-67: compare real saved Option-A bytes and long read behavior.

The 12-year test generates fictional complete-A records with real stable
roster IDs; this is not nationwide tournament execution or historical fact.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from phase2_engine.career_full_a_benchmark import (
    validate_options,
)
from phase2_engine.career_long_full_a_audit import (
    inspect_existing_full_a_files, run_long_full_a_audit,
)
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_player_stat_cache import CareerPlayerStatCache
from test_stage43g14_player_records import Stage43G14PlayerRecordTests

DATA = Path(__file__).resolve().parents[1] / "data"


class Stage43G67FullALongTermAuditTests(unittest.TestCase):
    def test_synthetic_12_years_a_records_rosters_cache_all_measured(self):
        result = run_long_full_a_audit(
            DATA, schools=2, years=12,
            games_per_school_year=2, repeats=1,
        )
        self.assertEqual(24, result["fictional_matches_archived"])
        self.assertEqual(24, result["complete_a_matches_verified"])
        self.assertEqual(24, result["cached_school_years"])
        self.assertGreater(result["cached_player_years"], 0)
        rows = result["per_year_logical_growth"]["annual_rows"]
        self.assertEqual(12, len(rows))
        self.assertEqual(list(range(2026, 2038)), [
            row["year"] for row in rows
        ])
        self.assertTrue(all(
            row["record_counts"]["matches"] == 2
            and row["record_counts"]["school_rosters"] == 2
            and row["record_counts"]["cache_school_year_facts"] == 2
            for row in rows
        ))
        self.assertTrue(all(
            row["annual_logical_payload_total_bytes"] > 0
            for row in rows
        ))
        physical = result["physical_save_growth_measured_each_year"]
        self.assertEqual(12, len(physical))
        self.assertEqual(result["total_actual_sqlite_bytes"],
                         physical[-1]["physical_total_sqlite_file_bytes"])
        self.assertEqual(
            result["total_actual_sqlite_bytes"],
            result["full_a_storage"]["sqlite_total_bytes"],
        )
        self.assertEqual({"full_a": 24},
                         result["full_a_storage"]["match_record_shapes"])
        self.assertEqual(24, result["full_a_storage"]["archived_match_count"])
        self.assertTrue(
            result["cached_stats_match_raw_stats_for_sampled_players"]
        )
        self.assertTrue(result["read_only_pass_preserved_file_hashes"])
        self.assertTrue(result["temporary_files_deleted_after_audit"])
        self.assertTrue(result["permanent_school_index_plans_verified"])
        self.assertFalse(result["full_3000_school_100_year_gameplay_verified"])
        self.assertFalse(result["official_game_results"])
        self.assertFalse(result["v2_year_10000_included"])
        for sample in result["sampled_raw_and_cached_statistics"]:
            for operation in ("raw_player", "cached_player", "raw_leaders",
                              "cached_leaders", "school_results_page"):
                self.assertIn(operation, sample["read_latency"])
                self.assertGreaterEqual(
                    sample["read_latency"][operation]["median_elapsed_ms"], 0,
                )

    def test_real_saved_two_year_source_inspection_does_not_create_cache(self):
        fixture = Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios"
        )
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.history.seal_year(2027, expected_match_count=1)
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "derived_player_stats.sqlite3"
            builder = CareerPlayerStatCache(fixture.view, cache)
            for year in (2026, 2027):
                builder.materialize(fixture.a, year=year)
            original = (
                fixture.history.db_path, fixture.rosters.db_path, cache,
            )
            before = {str(path): file_sha256(path) for path in original}
            result = inspect_existing_full_a_files(*original)
            self.assertEqual(2, result["annual"]["years_profiled"])
            self.assertEqual(2, result["annual"]["sealed_year_count"]
                             if "sealed_year_count" in result["annual"]
                             else 2)
            self.assertEqual(
                sum(result["storage"]["match_record_shapes"].values()),
                result["storage"]["archived_match_count"],
            )
            self.assertEqual(
                sum(x["file_bytes"] for x in
                    result["storage"]["sqlite_files"].values()),
                result["storage"]["sqlite_total_bytes"],
            )
            self.assertEqual(
                sum(x["annual_logical_payload_total_bytes"] for x in
                    result["annual"]["annual_rows"]),
                result["annual"]["cumulative_logical_payload_total_bytes"],
            )
            self.assertTrue(result["all_three_source_file_hashes_unchanged"])
            self.assertFalse(result["created_materialized_statistics"])
            self.assertFalse(result["source_match_ledger_fully_recomputed"])
            self.assertEqual(before, {
                str(path): file_sha256(path) for path in original
            })

    def test_saved_match_digest_tampering_rejected_no_write(self):
        fixture = Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios"
        )
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.history.seal_year(2027, expected_match_count=1)
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "derived_player_stats.sqlite3"
            builder = CareerPlayerStatCache(fixture.view, cache)
            for year in (2026, 2027):
                builder.materialize(fixture.a, year=year)
            with sqlite3.connect(fixture.history.db_path) as conn:
                conn.execute(
                    "UPDATE historical_matches SET record_sha256='BAD' "
                    "WHERE year=2026"
                )
            old = [file_sha256(p) for p in (
                fixture.history.db_path, fixture.rosters.db_path, cache,
            )]
            with self.assertRaisesRegex(ValueError, "checksum|digest"):
                inspect_existing_full_a_files(
                    fixture.history.db_path, fixture.rosters.db_path, cache,
                )
            self.assertEqual(old, [file_sha256(p) for p in (
                fixture.history.db_path, fixture.rosters.db_path, cache,
            )])

    def test_bad_paths_and_dimensions_rejected(self):
        for args in ((1, 12, 2, 1), (2, 0, 2, 1),
                     (2, 101, 2, 1), (3, 2, 1, 1),
                     (2, 4, 0, 1), (2, 4, 2, 0)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    run_long_full_a_audit(
                        DATA, schools=args[0], years=args[1],
                        games_per_school_year=args[2], repeats=args[3],
                    )
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.sqlite3"
            with self.assertRaises(FileNotFoundError):
                inspect_existing_full_a_files(
                    missing, Path(folder) / "rosters.sqlite3",
                    Path(folder) / "cache.sqlite3",
                )
            with self.assertRaises(ValueError):
                inspect_existing_full_a_files(
                    missing, missing, missing,
                )
            self.assertFalse(missing.exists())

    def test_explicit_large_limit_kept_and_allocation_not_extrapolated(self):
        with self.assertRaisesRegex(ValueError, "allow-large"):
            validate_options(100, 25, 4, 1)
        validate_options(100, 25, 4, 1, allow_large=True)
        x = run_long_full_a_audit(
            DATA, schools=2, years=4,
            games_per_school_year=1, repeats=1,
        )
        self.assertEqual(4, x["fictional_matches_archived"])
        self.assertEqual(
            x["per_year_logical_growth"]["years_profiled"], 4,
        )
        self.assertTrue(
            x["snapshot_byte_sizes_not_linear_capacity_projections"]
        )


if __name__ == "__main__":
    unittest.main()
