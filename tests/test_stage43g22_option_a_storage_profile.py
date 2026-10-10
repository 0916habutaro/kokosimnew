"""Stage43G-22: full Option-A persisted bytes, index footprint and safety."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

import test_stage43g14_player_records as fixture
from phase2_engine.career_full_a_benchmark import run_full_a_benchmark
from phase2_engine.career_option_a_storage_profile import (
    FIELDS, profile_option_a_storage, sqlite_file_profile,
)
from phase2_engine.career_player_stat_cache import CareerPlayerStatCache
from phase2_engine.career_history_scale_benchmark import file_sha256

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


class Stage43G22OptionAStorageProfileTests(unittest.TestCase):
    def test_real_saved_A_field_byte_partition_and_three_sqlite_files(self):
        result = run_full_a_benchmark(
            DATA_ROOT, schools=2, years=3, games_per_school_year=2,
            repeats=1,
        )
        audit = result["storage_profile"]
        self.assertEqual("43G-21", result["stage"])
        self.assertEqual(6, audit["archived_match_count"])
        self.assertEqual({"full_a": 6}, audit["match_record_shapes"])
        self.assertTrue(audit["source_verified_record_sha256"])
        parts = audit["payload_bytes"]
        self.assertEqual(
            parts["persisted_payload_bytes"],
            parts["metadata_and_json_syntax_bytes"] + sum(
                parts[key + "_value_bytes"] for key in FIELDS
            ),
        )
        for key in FIELDS:
            self.assertGreater(parts[key + "_value_bytes"], 0)
        self.assertGreater(audit["payload_min_bytes"], 0)
        self.assertGreaterEqual(
            audit["payload_max_bytes"], audit["payload_median_bytes"]
        )
        self.assertEqual(
            result["total_database_bytes"], audit["sqlite_total_bytes"]
        )
        for name, size in result["database_bytes"].items():
            file_info = audit["sqlite_files"][name]
            self.assertEqual(size, file_info["file_bytes"])
            self.assertEqual(
                file_info["allocated_page_bytes"],
                file_info["page_size"] * file_info["page_count"],
            )
            self.assertGreater(file_info["page_count"], 0)
            if file_info["dbstat_available"]:
                self.assertIsInstance(file_info["btree_page_bytes"], dict)
                self.assertGreater(len(file_info["btree_page_bytes"]), 0)
        zipped = audit["gzip_sample"]
        self.assertEqual(6, zipped["records_sampled"])
        self.assertGreater(zipped["sample_uncompressed_payload_bytes"], 0)
        self.assertGreater(zipped["sample_gzip_encoded_bytes"], 0)
        self.assertTrue(zipped["hypothetical_only_not_applied_to_save"])
        self.assertFalse(audit["full_option_a_real_tournament_execution_verified"])

    def test_profile_never_writes_and_rejects_changed_source_sha(self):
        base = fixture.Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios"
        )
        base.setUp()
        try:
            with tempfile.TemporaryDirectory() as d:
                cache_path = Path(d) / "derived.sqlite3"
                CareerPlayerStatCache(
                    base.view, cache_path
                ).materialize(base.a, year=2026)
                files = (
                    base.history.db_path, base.rosters.db_path, cache_path
                )
                before = [file_sha256(path) for path in files]
                view = profile_option_a_storage(
                    *files, gzip_sample_limit=1
                )
                self.assertEqual(2, view["archived_match_count"])
                self.assertEqual(
                    1, view["gzip_sample"]["records_sampled"]
                )
                self.assertEqual(before, [
                    file_sha256(path) for path in files
                ])
                with sqlite3.connect(base.history.db_path) as conn:
                    conn.execute(
                        "UPDATE historical_matches SET record_sha256='CORRUPT' "
                        "WHERE year=2026"
                    )
                with self.assertRaisesRegex(ValueError, "digest mismatch"):
                    profile_option_a_storage(*files)
        finally:
            base.tearDown()

    def test_zero_sample_does_not_hypothesize_savings(self):
        base = fixture.Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios"
        )
        base.setUp()
        try:
            with tempfile.TemporaryDirectory() as d:
                cache = Path(d) / "cache.sqlite3"
                CareerPlayerStatCache(base.view, cache).materialize(
                    base.a, year=2026
                )
                profile = profile_option_a_storage(
                    base.history.db_path, base.rosters.db_path,
                    cache, gzip_sample_limit=0,
                )
                self.assertEqual(0, profile["gzip_sample"]["records_sampled"])
                self.assertIsNone(profile["gzip_sample"]["sample_ratio"])
        finally:
            base.tearDown()

    def test_reject_missing_files_or_unbounded_samples_without_creation(self):
        with tempfile.TemporaryDirectory() as d:
            a, b, c = (Path(d) / name for name in (
                "matches.sqlite3", "rosters.sqlite3", "derived.sqlite3"
            ))
            with self.assertRaises(FileNotFoundError):
                profile_option_a_storage(a, b, c)
            with self.assertRaises(FileNotFoundError):
                sqlite_file_profile(a)
            self.assertFalse(any(path.exists() for path in (a, b, c)))
            with self.assertRaises(ValueError):
                profile_option_a_storage(a, b, c, gzip_sample_limit=1001)
            with self.assertRaises(ValueError):
                profile_option_a_storage(a, b, c, gzip_sample_limit=True)


if __name__ == "__main__":
    unittest.main()
