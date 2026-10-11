"""Stage43G-73 full A source/rosters/cache and indexed reader scale audit.

Five bounded cases are real append-only A record/annual roster/cache writes
with fictional scores/players, never a nationwide tournament simulation.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from phase2_engine.career_full_a_scaling_study import (
    CONTROLLED_CASES, run_full_a_scaling_study,
)

DATA = Path(__file__).resolve().parents[1] / "data"


class Stage43G73ScalingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_full_a_scaling_study(DATA, repeats=1)
        cls.rows = {r["case"]: r for r in cls.report["cases"]}

    def test_five_distinct_axes_and_archived_actual_full_a_count(self):
        self.assertEqual(
            [n for n, *_ in CONTROLLED_CASES], self.report["case_labels"]
        )
        self.assertEqual(5, len(self.rows))
        self.assertTrue(
            self.report["sample_cases_comparable_by_one_input_dimension"]
        )
        self.assertEqual(
            {"baseline": 4, "school_only": 16, "years_only": 16,
             "games_only": 16, "combined": 128},
            {name: r["archived_complete_a_matches"]
             for name, r in self.rows.items()},
        )
        self.assertEqual(
            180, self.report["total_synthetic_full_a_matches_generated"],
        )

    def test_exact_school_year_roster_and_cached_player_coverage(self):
        for name, r in self.rows.items():
            with self.subTest(case=name):
                self.assertEqual(
                    r["schools_with_generated_rosters"]
                    * r["successive_sealed_years"],
                    r["saved_school_year_rosters"],
                )
                self.assertGreater(r["derived_cache_player_year_rows"], 0)
                self.assertTrue(
                    r["source_and_cache_stats_match_on_sampled_players"]
                )
                self.assertTrue(
                    r["school_first_history_and_cached_player_indexes_selected"]
                )
                self.assertFalse(r["full_game_engine_progression_verified"])

    def test_known_db_size_and_json_bytes_a_distinct_storage_metric(self):
        for name, r in self.rows.items():
            with self.subTest(case=name):
                self.assertGreater(r["exact_saved_json_logical_bytes"], 0)
                self.assertGreater(r["saved_sqlite_files_bytes"], 0)
                self.assertEqual(
                    r["saved_sqlite_files_bytes"],
                    sum(x["sqlite_file_bytes"]
                        for x in r["physical_sqlite_components"].values()),
                )
                self.assertEqual(3, len(r["physical_sqlite_components"]))
                if all(x["dbstat_available"] for x in
                       r["physical_sqlite_components"].values()):
                    self.assertGreater(r["known_index_btree_bytes_sum"], 0)
                else:
                    self.assertIsNone(r["known_index_btree_bytes_sum"])

    def test_single_axis_cases_have_expected_dimensions(self):
        base = self.rows["baseline"]
        schools = self.rows["school_only"]
        years = self.rows["years_only"]
        games = self.rows["games_only"]
        self.assertEqual(
            (base["successive_sealed_years"],
             base["games_per_school_year_input"]),
            (schools["successive_sealed_years"],
             schools["games_per_school_year_input"]),
        )
        self.assertEqual(
            (base["schools_with_generated_rosters"],
             base["games_per_school_year_input"]),
            (years["schools_with_generated_rosters"],
             years["games_per_school_year_input"]),
        )
        self.assertEqual(
            (base["schools_with_generated_rosters"],
             base["successive_sealed_years"]),
            (games["schools_with_generated_rosters"],
             games["successive_sealed_years"]),
        )
        self.assertEqual(8, self.rows["combined"]["schools_with_generated_rosters"])
        self.assertEqual(8, self.rows["combined"]["successive_sealed_years"])

    def test_paired_cache_index_control_keeps_exact_rows_and_queries(self):
        for name, r in self.rows.items():
            with self.subTest(case=name):
                probe = r["paired_identical_cache_old_index"]
                self.assertEqual(
                    r["derived_cache_player_year_rows"],
                    probe["saved_player_year_rows"],
                )
                self.assertTrue(probe["new_and_old_full_row_digest_identical"])
                self.assertGreaterEqual(
                    probe["observed_extra_file_bytes_with_duplicate"], 0,
                )
                self.assertTrue(probe["read_latency_ranking_not_asserted"])
                self.assertGreaterEqual(probe["new_exact_row_read_median_ms"], 0)
                self.assertGreaterEqual(probe["old_exact_row_read_median_ms"], 0)

    def test_indexed_school_page_and_player_cache_measured_all_cases(self):
        operations = (
            "school_results_page", "raw_player", "cached_player",
            "raw_leaders", "cached_leaders",
        )
        for name, r in self.rows.items():
            with self.subTest(case=name):
                self.assertEqual(
                    set(operations), set(r["browse_and_stat_read_latency_ms"]),
                )
                for op in operations:
                    read = r["browse_and_stat_read_latency_ms"][op]
                    self.assertGreaterEqual(
                        read["median_of_school_sample_medians_ms"], 0,
                    )
                    self.assertEqual(
                        read["school_sample_count"],
                        len(read["per_sample_median_ms"]),
                    )

    def test_nationwide_or_linear_forecast_not_claimed(self):
        self.assertFalse(
            self.report["national_3000_school_100_year_runtime_verified"]
        )
        self.assertTrue(
            self.report["physical_file_size_per_year_is_not_linear_capacity_forecast"]
        )
        self.assertTrue(
            self.report["index_page_saving_from_existing_user_save_not_established"]
        )
        self.assertTrue(self.report["read_latency_rankings_not_claimed"])
        self.assertTrue(self.report["score_innings_player_stats_preserved"])
        self.assertTrue(self.report["all_original_source_sha_unchanged"])
        self.assertTrue(self.report["all_files_disposable_and_removed"])

    def test_invalid_dimensions_and_unbounded_runs_rejected(self):
        bad_cases = (
            (), (("same", 2, 2, 2), ("same", 2, 3, 2)),
            (("large", 10, 1, 2),),
            (("years", 2, 9, 2),),
            (("games", 2, 2, 9),),
            (("odd", 3, 2, 2),),
            (("notint", True, 2, 2),),
            (("bad", 2, 2, 2),) * 6,
        )
        for cases in bad_cases:
            with self.subTest(cases=cases):
                with self.assertRaises(ValueError):
                    run_full_a_scaling_study(DATA, cases=cases, repeats=1)
        for repeats in (True, 0, 6):
            with self.assertRaises(ValueError):
                run_full_a_scaling_study(
                    DATA, cases=(("single", 2, 1, 1),),
                    repeats=repeats,
                )

    def test_single_custom_case_is_separate_not_one_axis_comparison(self):
        result = run_full_a_scaling_study(
            DATA, cases=(("one_extra", 2, 1, 1),), repeats=1,
        )
        self.assertEqual(["one_extra"], result["case_labels"])
        self.assertEqual(1, result["total_synthetic_full_a_matches_generated"])
        self.assertFalse(result["sample_cases_comparable_by_one_input_dimension"])


if __name__ == "__main__":
    unittest.main()
