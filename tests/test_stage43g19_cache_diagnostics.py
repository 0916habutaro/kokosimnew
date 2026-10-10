"""Stage43G-19 read-only school/year cache diagnosis and real timing tests."""
from __future__ import annotations

import sqlite3
import unittest

from test_stage43g17_readonly_cache_browse import (
    Stage43G17ReadonlyCacheBrowseTests,
)
from phase2_engine.career_history_cache_diagnostics import (
    CareerHistoryCacheDiagnostics,
)


class Stage43G19HistoryCacheDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Stage43G17ReadonlyCacheBrowseTests(
            "test_cache_absent_never_created_and_raw_is_fully_checked"
        )
        self.fixture.setUp()
        self.reader = CareerHistoryCacheDiagnostics(self.fixture.model)
        self.a = self.fixture.a
        self.cache = self.fixture.cache_path

    def tearDown(self):
        self.fixture.tearDown()

    def report(self, check_cached_rows=True):
        return self.reader.report(
            self.a, start_year=2026, end_year=2027,
            check_cached_rows=check_cached_rows,
        )

    def test_missing_cache_does_not_create_sqlite(self):
        result = self.report()
        self.assertEqual("missing", result["cache_file_state"])
        self.assertEqual(["cache_missing", "source_active"], [
            r["cache_status"] for r in result["rows"]
        ])
        self.assertFalse(result["source_payloads_rechecked_on_read"])
        self.assertFalse(self.cache.exists())

    def test_sealed_cache_diagnostics_and_no_write_to_any_database(self):
        self.fixture.build(2026)
        paths = (
            self.cache, self.fixture.seed.fixture.history.db_path,
            self.fixture.seed.fixture.rosters.db_path,
        )
        before = [path.read_bytes() for path in paths]
        result = self.report()
        self.assertEqual(["cache_ready", "source_active"], [
            r["cache_status"] for r in result["rows"]
        ])
        self.assertEqual(1, result["counts"]["cache_ready"])
        self.assertEqual(before, [path.read_bytes() for path in paths])
        metadata_only = self.report(check_cached_rows=False)
        self.assertEqual("cache_metadata_matches",
                         metadata_only["rows"][0]["cache_status"])
        self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_cache_ledger_divergence_is_reported_not_hidden(self):
        self.fixture.build(2026)
        with sqlite3.connect(self.fixture.seed.fixture.history.db_path) as conn:
            conn.execute(
                "UPDATE career_years SET ledger_sha256='TAMPERED' "
                "WHERE year=2026"
            )
        self.assertEqual("cache_source_mismatch",
                         self.report()["rows"][0]["cache_status"])

    def test_cached_player_sha_tamper_is_reported_as_corrupt(self):
        self.fixture.build(2026)
        with sqlite3.connect(self.cache) as conn:
            conn.execute(
                "UPDATE player_year_stat_cache SET payload_sha256='BAD' "
                "WHERE school_id=? AND year=2026",
                (self.a,),
            )
        self.assertEqual("cache_corrupt",
                         self.report()["rows"][0]["cache_status"])

    def test_cache_row_in_active_year_is_not_accepted(self):
        self.fixture.build(2026)
        with sqlite3.connect(self.cache) as conn:
            conn.execute(
                "INSERT INTO school_year_stat_cache VALUES(?,?,?,?,?,?,?)",
                (self.a, 2027, "FALSE", 0, 0, 0, "FALSE"),
            )
        self.assertEqual("cache_on_unsealed_source",
                         self.report()["rows"][1]["cache_status"])

    def test_unreadable_cache_file_is_reported(self):
        self.cache.write_bytes(b"invalid database bytes")
        result = self.report()
        self.assertEqual("unreadable", result["cache_file_state"])
        self.assertEqual(["cache_unreadable", "cache_unreadable"], [
            row["cache_status"] for row in result["rows"]
        ])

    def test_orphan_cache_players_detected(self):
        self.fixture.build(2026)
        with sqlite3.connect(self.cache) as conn:
            conn.execute(
                "INSERT INTO player_year_stat_cache "
                "(school_id,year,player_id,payload_json,payload_sha256) "
                "VALUES(?,?,?,?,?)",
                (self.a, 2027, "ORPHAN", "{}", "invalid"),
            )
        self.assertEqual("orphan_cache_rows",
                         self.report()["rows"][1]["cache_status"])

    def test_benchmark_reports_measured_local_timings_not_global_claims(self):
        self.fixture.build(2026)
        result = self.reader.benchmark(
            self.a, start_year=2026, end_year=2027, repeats=2
        )
        self.assertEqual(2, len(result["elapsed_ms"]))
        self.assertGreaterEqual(result["median_elapsed_ms"], 0)
        self.assertGreaterEqual(result["max_peak_traced_python_bytes"], 0)
        self.assertEqual("one_local_slot_one_school",
                         result["measurement_scope"])
        self.assertFalse(result["nationwide_3000_schools_100_years_verified"])

    def test_unknown_school_invalid_ranges_are_rejected(self):
        with self.assertRaises(ValueError):
            self.reader.report(
                "UNKNOWN", start_year=2026, end_year=2027
            )
        with self.assertRaises(ValueError):
            self.reader.report(
                self.a, start_year=2027, end_year=2026
            )
        with self.assertRaises(ValueError):
            self.reader.benchmark(
                self.a, start_year=2026, end_year=2027, repeats=0
            )


if __name__ == "__main__":
    unittest.main()
