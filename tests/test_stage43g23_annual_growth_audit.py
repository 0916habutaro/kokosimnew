"""Stage43G-23 annual immutable save growth, year-cohort, index audits."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from phase2_engine.career_annual_growth_audit import (
    physical_year_snapshot, profile_annual_growth,
    school_query_plan_audit,
)
from phase2_engine.career_full_a_benchmark import (
    run_full_a_benchmark, START_YEAR,
)
from phase2_engine.career_player_stat_cache import CareerPlayerStatCache
from phase2_engine.career_history_scale_benchmark import file_sha256
from test_stage43g14_player_records import Stage43G14PlayerRecordTests


DATA = Path(__file__).resolve().parents[1] / "data"


class Stage43G23AnnualGrowthAuditTests(unittest.TestCase):
    def test_real_2school_3year_save_growth_and_all_indexes(self):
        result = run_full_a_benchmark(
            DATA, schools=2, years=3, games_per_school_year=2, repeats=1,
        )
        history = result["annual_growth"]
        self.assertEqual(3, history["sealed_year_count"])
        self.assertEqual([START_YEAR, START_YEAR + 1, START_YEAR + 2],
                         [r["year"] for r in history["rows"]])
        self.assertGreater(
            history["bootstrap_prior_entry_year_identities"], 0
        )
        self.assertTrue(history[
            "prior_entry_cohorts_attributed_to_first_saved_year"
        ])
        self.assertTrue(history["record_sha256_checked"])
        self.assertFalse(history["source_match_ledger_fully_recomputed"])
        self.assertFalse(history["school_year_cache_fact_sha_fully_recomputed"])
        self.assertTrue(history[
            "logical_bytes_are_not_sqlite_physical_file_deltas"
        ])
        for i, row in enumerate(history["rows"]):
            self.assertEqual(2, row["record_counts"]["matches"])
            self.assertEqual(2, row["record_counts"]["school_rosters"])
            self.assertEqual(2, row["record_counts"]["cache_school_year_facts"])
            self.assertGreater(
                row["logical_payload_bytes"]["match_payload"], 0
            )
            self.assertGreater(
                row["logical_payload_bytes"]["school_roster_payload"], 0
            )
            self.assertGreater(
                row["logical_payload_bytes"]["derived_player_year_payload"], 0
            )
            self.assertEqual(
                sum(row["logical_payload_bytes"].values()),
                row["annual_logical_payload_total_bytes"],
            )
            if i:
                self.assertGreater(
                    row["cumulative_logical_payload_total_bytes"],
                    history["rows"][i-1][
                        "cumulative_logical_payload_total_bytes"
                    ],
                )
        self.assertEqual(
            history["final_logical_payload_total_bytes"],
            history["rows"][-1][
                "cumulative_logical_payload_total_bytes"
            ],
        )
        self.assertEqual(
            sum(history["final_logical_payload_bytes"].values()),
            history["final_logical_payload_total_bytes"],
        )
        physical = result["annual_physical_snapshots"]
        self.assertEqual(3, len(physical))
        self.assertEqual(result["database_bytes"],
                         physical[-1]["allocated_file_bytes"])
        self.assertEqual(result["total_database_bytes"],
                         physical[-1]["allocated_total_file_bytes"])
        self.assertEqual(
            physical[-1]["allocated_total_file_bytes"],
            sum(row["allocated_total_delta_bytes"] for row in physical)
        )
        plans = result["school_index_plans"]
        self.assertTrue(plans["all_expected_indexes_selected"])
        self.assertEqual({
            "home_matches", "away_matches",
            "school_alumni", "cached_player",
        }, set(plans["plans"]))

    def _sealed_two_year_fixture(self):
        fixture = Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios"
        )
        fixture.setUp()
        fixture.history.seal_year(2027, expected_match_count=1)
        # Caller is responsible for fixture.tearDown().
        return fixture

    def test_report_reads_existing_data_and_does_not_mutate(self):
        fixture = self._sealed_two_year_fixture()
        try:
            with tempfile.TemporaryDirectory() as d:
                cache = Path(d) / "derived.sqlite3"
                builder = CareerPlayerStatCache(fixture.view, cache)
                for year in (2026, 2027):
                    builder.materialize(fixture.a, year=year)
                paths = (fixture.history.db_path,
                         fixture.rosters.db_path, cache)
                before = [file_sha256(p) for p in paths]
                result = profile_annual_growth(*paths)
                self.assertEqual(2, result["sealed_year_count"])
                self.assertEqual(1, result["rows"][0]["record_counts"]["matches"])
                self.assertEqual(1, result["rows"][1]["record_counts"]["matches"])
                self.assertEqual(before, [file_sha256(p) for p in paths])
                detail = school_query_plan_audit(
                    *paths, fixture.a, fixture.hitter, 2026, 2027
                )
                self.assertEqual(4, len(detail["plans"]))
                self.assertEqual(before, [file_sha256(p) for p in paths])
        finally:
            fixture.tearDown()

    def test_active_year_kept_as_active_without_fabricated_seal(self):
        fixture = Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios"
        )
        fixture.setUp()
        try:
            with tempfile.TemporaryDirectory() as d:
                cache = Path(d) / "derived.sqlite3"
                CareerPlayerStatCache(fixture.view, cache).materialize(
                    fixture.a, year=2026
                )
                report = profile_annual_growth(
                    fixture.history.db_path,
                    fixture.rosters.db_path, cache,
                )
                self.assertEqual(2, report["year_count"])
                self.assertEqual(1, report["sealed_year_count"])
                self.assertEqual(1, report["active_year_count"])
                self.assertEqual(["sealed", "active"], [
                    row["source_year_status"] for row in report["rows"]
                ])
                self.assertEqual(
                    0, report["rows"][1][
                        "record_counts"]["cache_school_year_facts"]
                )
        finally:
            fixture.tearDown()

    def test_tampered_row_and_cache_ledger_rejected(self):
        fixture = self._sealed_two_year_fixture()
        try:
            with tempfile.TemporaryDirectory() as d:
                cache = Path(d) / "derived.sqlite3"
                builder = CareerPlayerStatCache(fixture.view, cache)
                for year in (2026, 2027):
                    builder.materialize(fixture.a, year=year)
                args = (fixture.history.db_path,
                        fixture.rosters.db_path, cache)
                with sqlite3.connect(cache) as conn:
                    conn.execute(
                        "UPDATE school_year_stat_cache SET "
                        "source_ledger_sha256='TAMPERED' "
                        "WHERE year=2026"
                    )
                with self.assertRaisesRegex(ValueError, "source ledger mismatch"):
                    profile_annual_growth(*args)
                with sqlite3.connect(fixture.history.db_path) as source:
                    actual = source.execute(
                        "SELECT ledger_sha256 FROM career_years WHERE year=2026"
                    ).fetchone()[0]
                with sqlite3.connect(cache) as conn:
                    conn.execute(
                        "UPDATE school_year_stat_cache SET "
                        "source_ledger_sha256=? WHERE year=2026",
                        (actual,),
                    )
                    conn.execute(
                        "UPDATE player_year_stat_cache SET payload_sha256='BAD' "
                        "WHERE year=2026 AND school_id=?",
                        (fixture.a,),
                    )
                with self.assertRaisesRegex(ValueError, "derived stats checksum"):
                    profile_annual_growth(*args)
        finally:
            fixture.tearDown()

    def test_annual_physical_snapshot_requires_adjacent_year_and_all_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            files = {}
            for key in ("matches", "rosters", "derived_cache"):
                path = root / (key + ".sqlite3")
                path.write_bytes(b"benchmark-only")
                files[key] = path
            first = physical_year_snapshot(2026, files)
            self.assertEqual(14, first["allocated_file_bytes"]["matches"])
            second = physical_year_snapshot(2027, files, previous=first)
            self.assertEqual(0, second["allocated_total_delta_bytes"])
            with self.assertRaises(ValueError):
                physical_year_snapshot(2029, files, previous=first)
            with self.assertRaises(ValueError):
                physical_year_snapshot(True, files)
            with self.assertRaises(ValueError):
                physical_year_snapshot(2026, {"matches": files["matches"]})
            files["rosters"].unlink()
            with self.assertRaises(FileNotFoundError):
                physical_year_snapshot(2027, files)

    def test_missing_database_cannot_be_created_by_read_audit(self):
        with tempfile.TemporaryDirectory() as d:
            paths = tuple(Path(d) / (label + ".sqlite3")
                          for label in ("matches", "rosters", "cache"))
            with self.assertRaises(FileNotFoundError):
                profile_annual_growth(*paths)
            with self.assertRaises(FileNotFoundError):
                school_query_plan_audit(*paths, "SCHOOL", "PLAYER", 2026, 2027)
            self.assertFalse(any(p.exists() for p in paths))


if __name__ == "__main__":
    unittest.main()
