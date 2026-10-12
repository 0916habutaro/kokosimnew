"""Stage43G-79 indexed-vs-JSON1 measured full-A synthetic read audit."""
from __future__ import annotations
import unittest
from phase2_engine.career_v2_school_read_index_benchmark import (
    audit_indexed_v2_search,
)


class Stage43G79IndexedBenchmarkTests(unittest.TestCase):
    def test_small_reproducible_sources_match_and_remain_unchanged(self):
        report = audit_indexed_v2_search(
            years=2, games_per_year=4, repetitions=2,
        )
        self.assertEqual(8, report["fictional_full_a_matches"])
        self.assertEqual(2, report["target_school_matches"])
        self.assertTrue(report["source_json1_vs_index_records_identical"])
        self.assertTrue(report["original_sqlite_unchanged"])
        self.assertEqual(report["source_sha256_before"],
                         report["source_sha256_after"])
        self.assertGreater(report["index_bytes"], 0)
        self.assertTrue(report["school_lookup_sql_plan"])
        self.assertTrue(any(
            "school_id=?" in plan for plan in report["school_lookup_sql_plan"]
        ))
        self.assertFalse(report["real_full_scale_3000_school_history_proven"])
        for value in report["measurement"].values():
            self.assertEqual(2, len(value["samples_ms"]))
            self.assertGreaterEqual(value["median_ms"], 0)

    def test_invalid_input_fails_before_creating_fixture(self):
        for kwargs in (
            {"years": 0}, {"years": 101}, {"years": True},
            {"games_per_year": 1}, {"repetitions": 0},
            {"games_per_year": False},
            {"years": 50, "games_per_year": 100},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    audit_indexed_v2_search(**kwargs)


if __name__ == "__main__":
    unittest.main()
