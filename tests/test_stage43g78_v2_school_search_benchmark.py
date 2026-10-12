"""Stage43G-78: deterministic source/plan and real measured full-A read audit."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from phase2_engine.career_v2_school_search_benchmark import (
    SOURCE, run_v2_school_search_audit,
)
from phase2_engine.career_history_scale_benchmark import file_sha256


class Stage43G78V2SchoolSearchAuditTests(unittest.TestCase):
    def test_small_full_a_measurement_has_provenance_and_unchanged_sources(self):
        result = run_v2_school_search_audit(
            years=2, games_per_year=4, repetitions=2,
        )
        self.assertEqual(SOURCE, result["audit_contract"])
        self.assertEqual(8, result["full_a_saved_matches"])
        self.assertEqual(2, result["target_school_saved_matches"])
        self.assertEqual(10000, result["first_game_year"])
        self.assertEqual(10001, result["last_game_year"])
        self.assertTrue(result["synthetic_full_option_a_only"])
        self.assertTrue(result["source_bytes_unchanged"])
        self.assertEqual(
            result["source_sha256_before"], result["source_sha256_after"]
        )
        self.assertFalse(result["actual_3000_school_100_year_gameplay_proven"])
        self.assertFalse(result["cross_machine_latency_guarantee"])
        self.assertFalse(result["official_competition_or_real_multiyear_progression"])
        self.assertTrue(result["school_filter_uses_unindexed_json1_scan"])
        self.assertTrue(result["strict_scope_verifies_all_saved_year_payloads"])
        for metric in ("page", "selected_years", "competition_page"):
            data = result["measured_queries"][metric]
            self.assertEqual(2, data["samples"])
            self.assertEqual(2, len(data["samples_ms"]))
            self.assertGreaterEqual(data["median_ms"], 0.0)
            self.assertGreaterEqual(data["max_ms"], data["median_ms"])
        self.assertTrue(result["query_plans"]["count_school_matches"])
        self.assertTrue(result["query_plans"]["first_30_school_matches"])
        self.assertTrue(result["query_plans"]["sealed_ledger_rows"])
        self.assertIn("source_bytes_unchanged", json.loads(json.dumps(result)))

    def test_multi_year_more_than_one_page_is_bounded_and_read_only(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = run_v2_school_search_audit(
                years=4, games_per_year=43, repetitions=1,
                output_root=root,
            )
            self.assertEqual(172, result["full_a_saved_matches"])
            self.assertEqual(12, result["target_school_saved_matches"])
            self.assertEqual(30, result["page_size"])
            self.assertTrue(result["source_bytes_unchanged"])
            self.assertFalse(result["fixture_written_to_isolated_temporary_files_only"])
            before = {
                p.name: file_sha256(p)
                for p in root.glob("*.sqlite3")
            }
            self.assertEqual(result["source_sha256_after"], before)
            with self.assertRaisesRegex(ValueError, "refuses"):
                run_v2_school_search_audit(
                    years=2, games_per_year=4, output_root=root,
                )
            self.assertEqual(
                before,
                {p.name: file_sha256(p) for p in root.glob("*.sqlite3")}
            )

    def test_incorrect_dimensions_rejected_without_writing(self):
        cases = (
            {"years": 0}, {"years": 101}, {"years": True},
            {"games_per_year": 1}, {"games_per_year": 1001},
            {"games_per_year": False}, {"repetitions": 0},
            {"repetitions": 21}, {"repetitions": True},
            {"years": 50, "games_per_year": 40},
        )
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            for case in cases:
                with self.subTest(case=case):
                    with self.assertRaises(ValueError):
                        run_v2_school_search_audit(
                            output_root=folder, **case,
                        )
            self.assertEqual([], list(folder.iterdir()))


if __name__ == "__main__":
    unittest.main()
