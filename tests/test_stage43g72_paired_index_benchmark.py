"""Stage43G-72: equal-row-count SQLite clones quantify one duplicate B-tree.

Checks physical file deltas and unchanged exact source payload bytes; does
not assume that reducing a preexisting user's SQLite file saves those bytes.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_paired_index_benchmark import (
    CareerControlledIndexConflict, compare_duplicate_index_build,
)
import test_stage43g70_storage_btree_audit as source_v2
import test_stage43g71_stats_cache_index_audit as source_cache


class Stage43G72PairedIndexTests(unittest.TestCase):
    def setUp(self):
        self.v2 = source_v2.Stage43G70BtreeAuditTests(
            "test_new_v2_keeps_primary_key_and_calendar_day_index",
        )
        self.v2.setUp()
        self.addCleanup(self.v2.doCleanups)
        self.cache = source_cache.Stage43G71CacheIndexTests(
            "test_new_legacy_cache_avoids_duplicate_but_player_lookup_survives",
        )
        self.cache.setUp()
        self.addCleanup(self.cache.doCleanups)

    def test_v2_two_identical_complete_a_match_rows_old_index_uses_extra_pages(self):
        path = self.v2.source
        before = file_sha256(path)
        report = compare_duplicate_index_build(
            path, kind="v2_matches", repeats=3,
        )
        self.assertEqual("43G-72", report["stage"])
        self.assertEqual("v2_matches", report["kind"])
        self.assertEqual(2, report["new_schema"]["stored_rows"])
        self.assertEqual(
            report["new_schema"]["ordered_full_row_sha256"],
            report["previous_schema"]["ordered_full_row_sha256"],
        )
        self.assertTrue(report["identical_record_rows_and_full_content_sha"])
        self.assertFalse(report["new_schema"]["explicit_pk_duplicate_present"])
        self.assertTrue(report["previous_schema"]["explicit_pk_duplicate_present"])
        self.assertGreater(
            report["observed_extra_file_bytes_in_old_index_copy"], 0,
        )
        self.assertTrue(report["exact_row_indexed_lookup_preserved"])
        self.assertTrue(report["source_sqlite_sha_unchanged"])
        self.assertTrue(report["temporary_sqlite_files_removed"])
        self.assertEqual(before, file_sha256(path))

    def test_old_a_derived_player_cache_equal_rows_different_index_only(self):
        path = self.cache.legacy_path
        before = file_sha256(path)
        report = compare_duplicate_index_build(
            path, kind="legacy_cache", repeats=5,
        )
        self.assertEqual("legacy_cache", report["kind"])
        self.assertGreater(report["new_schema"]["stored_rows"], 0)
        self.assertGreater(
            report["observed_extra_file_bytes_in_old_index_copy"], 0,
        )
        self.assertTrue(report["identical_record_rows_and_full_content_sha"])
        self.assertEqual(
            report["new_schema"]["ordered_full_row_sha256"],
            report["previous_schema"]["ordered_full_row_sha256"],
        )
        self.assertTrue(report["in_place_existing_save_savings_not_established"])
        self.assertTrue(report["median_read_latency_comparison_is_observational_only"])
        self.assertEqual(5, len(
            report["new_schema"]["repeated_exact_row_lookup_ms"]
        ))
        self.assertEqual(5, len(
            report["previous_schema"]["repeated_exact_row_lookup_ms"]
        ))
        self.assertEqual(before, file_sha256(path))

    def test_identical_original_option_a_records_and_cache_do_not_change(self):
        inputs = (self.v2.source, self.cache.legacy_path,
                  self.cache.v2_path, self.cache.old.seed.history.db_path,
                  self.cache.old.seed.rosters.db_path)
        before = {str(p): file_sha256(p) for p in inputs}
        first = compare_duplicate_index_build(
            self.v2.source, kind="v2_matches", repeats=2,
        )
        second = compare_duplicate_index_build(
            self.cache.legacy_path, kind="legacy_cache", repeats=2,
        )
        self.assertEqual(
            before, {str(p): file_sha256(p) for p in inputs}
        )
        self.assertTrue(first["original_option_a_payload_format_unchanged"])
        self.assertTrue(second["original_option_a_payload_format_unchanged"])
        self.assertFalse(first["nationwide_50_100_year_runtime_not_simulated"] is False)

    def test_reject_existing_old_duplicate_index_without_modifying_source(self):
        with sqlite3.connect(self.v2.source) as db:
            db.execute(
                "CREATE INDEX idx_v2_games_school_a ON "
                "v2_option_a_matches(year,competition_id,match_id)"
            )
        path = self.v2.source
        before = file_sha256(path)
        with self.assertRaises(CareerControlledIndexConflict):
            compare_duplicate_index_build(path, kind="v2_matches")
        self.assertEqual(before, file_sha256(path))

    def test_reject_legacy_cache_old_duplicate_index_without_mutation(self):
        with sqlite3.connect(self.cache.legacy_path) as db:
            db.execute(
                "CREATE INDEX idx_cached_school_year ON "
                "player_year_stat_cache(school_id,year,player_id)"
            )
        before = file_sha256(self.cache.legacy_path)
        with self.assertRaises(CareerControlledIndexConflict):
            compare_duplicate_index_build(
                self.cache.legacy_path, kind="legacy_cache",
            )
        self.assertEqual(before, file_sha256(self.cache.legacy_path))

    def test_invalid_kind_repeats_missing_source_and_symlink(self):
        for bad_kind, count in (("v2_cache", 2), ("v2_matches", 0),
                                ("legacy_cache", 26),
                                ("legacy_cache", True)):
            with self.subTest(kind=bad_kind, repeats=count):
                with self.assertRaises(ValueError):
                    compare_duplicate_index_build(
                        self.cache.legacy_path, kind=bad_kind, repeats=count
                    )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "no_saved.sqlite3"
            with self.assertRaises(FileNotFoundError):
                compare_duplicate_index_build(
                    missing, kind="v2_matches",
                )
            self.assertFalse(missing.exists())
            symlink = root / "linked.sqlite3"
            symlink.symlink_to(self.v2.source)
            with self.assertRaises(FileNotFoundError):
                compare_duplicate_index_build(
                    symlink, kind="v2_matches",
                )

    def test_cli_output_and_never_overwrites_source_database(self):
        path = self.cache.legacy_path
        before = file_sha256(path)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "paired.json"
            args = [
                sys.executable, "-m",
                "phase2_engine.career_paired_index_benchmark",
                "--kind", "legacy_cache",
                "--saved-db", str(path),
                "--repeats", "3",
                "--output-json", str(target),
            ]
            subprocess.run(args, check=True, capture_output=True, text=True)
            report = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual("43G-72", report["stage"])
            self.assertEqual(3, report["repeat_count"])
            refused = subprocess.run(
                args[:-1] + [str(path)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(before, file_sha256(path))


if __name__ == "__main__":
    unittest.main()
