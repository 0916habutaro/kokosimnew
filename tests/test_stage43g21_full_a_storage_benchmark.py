"""Stage43G-21 complete A/roster/cache measured benchmark regression tests."""
from __future__ import annotations

from pathlib import Path
import unittest

from phase2_engine.career_full_a_benchmark import (
    run_full_a_benchmark, validate_options,
)

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


class Stage43G21FullAStorageBenchmarkTests(unittest.TestCase):
    def test_two_school_two_year_all_A_and_cache_provenance(self):
        result = run_full_a_benchmark(
            DATA_ROOT, schools=2, years=2,
            games_per_school_year=2, repeats=1,
        )
        self.assertEqual(4, result["expected_matches"])
        self.assertEqual(4, result["counts"]["matches"])
        self.assertEqual(4, result["counts"]["full_option_a_matches"])
        self.assertEqual(4, result["counts"]["school_year_rosters"])
        self.assertEqual(4, result["counts"]["cached_school_years"])
        self.assertGreater(result["counts"]["player_identities"], 0)
        self.assertGreater(result["counts"]["cached_player_years"], 0)
        self.assertTrue(result["genuine_roster_identity_attribution"])
        self.assertTrue(result["option_a_innings_teams_batters_pitchers_present"])
        self.assertTrue(result["all_db_hashes_unchanged_on_read"])
        self.assertTrue(result["temporary_fixture_deleted_after_run"])
        self.assertFalse(result["real_game_tournament_progression_verified"])
        self.assertFalse(result["nationwide_3000_school_100_year_verified"])
        self.assertEqual(2, len(result["reads"]))
        for sample in result["reads"]:
            self.assertTrue(sample["cached_matches_raw"])
            self.assertEqual({
                "raw_player", "cached_player", "raw_leaders",
                "cached_leaders", "school_results_page",
            }, set(sample["read_latency"]))
            for timing in sample["read_latency"].values():
                self.assertEqual(1, timing["repeats"])
                self.assertGreaterEqual(timing["median_elapsed_ms"], 0)
                self.assertGreaterEqual(timing["max_traced_python_bytes"], 0)
        self.assertEqual(
            sum(result["database_bytes"].values()),
            result["total_database_bytes"],
        )
        self.assertGreater(
            result["database_bytes"]["matches"], 0
        )
        self.assertGreater(
            result["database_bytes"]["rosters"], 0
        )
        self.assertGreater(
            result["database_bytes"]["derived_cache"], 0
        )

    def test_four_school_three_year_career_continuity(self):
        result = run_full_a_benchmark(
            DATA_ROOT, schools=4, years=3,
            games_per_school_year=2, repeats=1,
        )
        self.assertEqual(12, result["counts"]["matches"])
        self.assertEqual(12, result["counts"]["full_option_a_matches"])
        self.assertEqual(12, result["counts"]["school_year_rosters"])
        self.assertEqual(12, result["counts"]["cached_school_years"])
        self.assertEqual(3, len(result["reads"]))

    def test_larger_fixture_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "allow-large"):
            validate_options(100, 50, 2, 2)
        validate_options(100, 50, 2, 2, allow_large=True)

    def test_invalid_dimensions_and_types_are_rejected(self):
        for args in (
            (1, 2, 2, 2), (3, 2, 2, 2), (101, 1, 1, 1),
            (2, 0, 2, 1), (2, 101, 2, 1),
            (2, 1, 0, 1), (2, 1, 21, 1),
            (2, 1, 1, 0), (2, 1, 1, 11),
            (True, 1, 1, 1),
        ):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    validate_options(*args)
        with self.assertRaises(ValueError):
            validate_options(2, 1, 1, 1, allow_large=1)


if __name__ == "__main__":
    unittest.main()
