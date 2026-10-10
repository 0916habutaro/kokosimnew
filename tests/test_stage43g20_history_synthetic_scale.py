"""Stage43G-20 real-indexed synthetic archive scaling smoke tests."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from phase2_engine.career_history_scale_benchmark import (
    START_YEAR, build_synthetic_archive, file_sha256,
    measure_indexed_history, run_benchmark, school_id, validate_scale,
)
from phase2_engine.career_longitudinal_read import CareerLongitudinalReadModel
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.historical_match_archive import HistoricalMatchArchive


class Stage43G20HistorySyntheticScaleTests(unittest.TestCase):
    def test_small_scale_stores_all_matches_and_measures_real_indexed_pages(self):
        result = run_benchmark(
            schools=3, years=4, games_per_school_year=3, repeats=2,
        )
        self.assertEqual(36, result["actual_match_rows"])
        self.assertEqual(36, result["expected_match_rows"])
        self.assertGreater(result["database_bytes"], 0)
        self.assertTrue(result["temporary_data_deleted_after_run"])
        self.assertFalse(result["production_gameplay_or_full_option_A_verified"])
        self.assertFalse(result["synthetic_3000_schools_100_years_exercised"])
        read = result["read_measurements"]
        self.assertTrue(read["db_unmodified_by_reads"])
        self.assertTrue(read["required_school_first_indexes_present"])
        self.assertEqual(3, len(read["samples"]))
        for row in read["samples"]:
            self.assertEqual(8, row["total_groups"])
            self.assertEqual(8, row["first_page_rows"])
            self.assertEqual(2, len(row["repeat_elapsed_ms"]))
            self.assertGreaterEqual(row["median_first_page_ms"], 0)
            self.assertGreaterEqual(row["max_traced_python_bytes"], 0)

    def test_two_years_indexed_history_is_correct_and_sealed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bench.sqlite3"
            summary = build_synthetic_archive(
                path, schools=2, years=2, games_per_school_year=4,
            )
            self.assertEqual(16, summary["match_rows"])
            model = CareerLongitudinalReadModel(
                HistoricalMatchArchive(path),
                CareerRosterArchive(Path(temp) / "never-created-rosters.sqlite3"),
            )
            school = school_id(2)
            page = model.school_results(
                school, start_year=START_YEAR,
                end_year=START_YEAR + 1, limit=1, offset=1,
            )
            self.assertEqual(4, page["total_groups"])
            self.assertEqual(1, len(page["records"]))
            self.assertEqual(2, page["records"][0]["games"])
            self.assertEqual(2, page["records"][0]["wins"])
            self.assertEqual(0, page["records"][0]["losses"])
            with closing(sqlite3.connect(
                path.resolve().as_uri() + "?mode=ro", uri=True
            )) as conn:
                rows = conn.execute(
                    "SELECT status,match_count,ledger_sha256 FROM career_years "
                    "ORDER BY year"
                ).fetchall()
                self.assertEqual(2, len(rows))
                self.assertTrue(all(r[0] == "sealed" and r[1] == 8
                                    and len(r[2]) == 64 for r in rows))
                recorded = conn.execute(
                    "SELECT payload_json FROM historical_matches LIMIT 1"
                ).fetchone()[0]
                self.assertIn('"batter_stats":null', recorded)
            digest = file_sha256(path)
            measure_indexed_history(
                path, schools=2, years=2,
                games_per_school_year=4, repeats=1
            )
            self.assertEqual(digest, file_sha256(path))
            self.assertFalse(
                (Path(temp) / "never-created-rosters.sqlite3").exists()
            )

    def test_existing_archive_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "existing.sqlite3"
            path.write_bytes(b"keep original data")
            with self.assertRaises(FileExistsError):
                build_synthetic_archive(
                    path, schools=1, years=1,
                    games_per_school_year=1,
                )
            self.assertEqual(b"keep original data", path.read_bytes())

    def test_scale_rejects_large_unconfirmed_or_invalid_jobs(self):
        self.assertEqual(
            1_200_000,
            validate_scale(3000, 100, 4, 1, allow_large=True),
        )
        with self.assertRaisesRegex(ValueError, "allow-large"):
            validate_scale(3000, 100, 4, 1)
        with self.assertRaises(ValueError):
            validate_scale(3000, 100, 50, 1, allow_large=True)
        with self.assertRaises(ValueError):
            validate_scale(1, 0, 2, 1)
        with self.assertRaises(ValueError):
            validate_scale(True, 2, 2, 1)
        with self.assertRaises(ValueError):
            validate_scale(1, 2, 2, 0)
        with self.assertRaises(ValueError):
            validate_scale(1, 2, 2, 1, allow_large=1)


if __name__ == "__main__":
    unittest.main()
