"""Stage43G-69: compare independent, observed 12-year A and v2 reports.

Uses source-authenticated audit outputs; never treats synthetic years as
an actual single career or the two physical DB footprints as savings.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from phase2_engine.career_cross_era_storage_evidence import (
    CareerStorageEvidenceConflict, compare_independent_a_audits,
)
from phase2_engine.career_long_full_a_audit import run_long_full_a_audit
from phase2_engine.career_v2_long_storage_audit import audit_saved_v2_storage
from test_stage43g68_v2_long_storage_audit import (
    Stage43G68V2LongStorageAuditTests,
)

ROOT = Path(__file__).resolve().parents[1]


class Stage43G69CrossEraEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = run_long_full_a_audit(
            ROOT / "data", schools=2, years=12,
            games_per_school_year=2, repeats=1,
        )
        cls.v2_fixture = Stage43G68V2LongStorageAuditTests(
            "test_twelve_v2_years_true_roster_progression_full_a_and_size",
        )
        cls.v2_fixture.setUp()
        cls.addClassCleanup(cls.v2_fixture.doCleanups)
        cls.v2_fixture._progress(10011)
        cls.v2 = audit_saved_v2_storage(
            cls.v2_fixture.root, list(range(10000, 10012)),
        )
        cls.original_file_hashes = cls.v2_fixture._hashes()

    def test_true_12_year_comparison_explicit_source_boundaries(self):
        out = compare_independent_a_audits(self.legacy, self.v2)
        self.assertEqual("43G-69", out["stage"])
        legacy, future = out["legacy"], out["fictional_v2"]
        self.assertEqual({"first": 2026, "last": 2037},
                         legacy["year_range"])
        self.assertEqual({"first": 10000, "last": 10011},
                         future["year_range"])
        self.assertEqual(12, legacy["sampled_years"])
        self.assertEqual(12, future["sampled_years"])
        self.assertEqual(24, legacy["exact_saved_match_count"])
        self.assertEqual(23, future["exact_saved_match_count"])
        self.assertEqual(24, legacy["saved_school_year_roster_count"])
        self.assertEqual(24, future["saved_school_year_roster_count"])
        self.assertTrue(out["source_match_counts_may_differ"])
        self.assertTrue(out["source_formats_have_different_schema_and_file_counts"])
        self.assertEqual(3, legacy["whole_sqlite_files_count"])
        self.assertEqual(4, future["whole_sqlite_files_count"])
        self.assertEqual(
            self.legacy["total_actual_sqlite_bytes"],
            legacy["whole_sqlite_files_bytes"],
        )
        self.assertEqual(
            self.v2["total_v2_roster_cache_calendar_sqlite_file_bytes"],
            future["whole_sqlite_files_bytes"],
        )
        self.assertFalse(out["aggregated_career_statistics_authorized"])
        self.assertFalse(out["physical_file_storage_savings_claimed"])
        self.assertFalse(out["historical_tournament_progression_proven"])
        self.assertTrue(out["evidence_is_stored_report_not_reinspection_of_live_sqlite"])

    def test_ratios_are_within_each_format_and_not_capacity_prediction(self):
        out = compare_independent_a_audits(self.legacy, self.v2)
        for part in (out["legacy"], out["fictional_v2"]):
            self.assertEqual(
                round(
                    part["measured_json_bytes"]["match"]
                    / part["exact_saved_match_count"], 2,
                ), part["observed_match_json_bytes_per_saved_match"],
            )
            self.assertEqual(
                sum(part["measured_json_bytes"].values()),
                part["measured_json_bytes_total"],
            )
            self.assertGreater(
                part["observed_roster_json_bytes_per_saved_school_year"], 0,
            )
        self.assertIn(
            "unlike-depth-performance-times-as-speed-ranking",
            out["do_not_compare_or_infer"],
        )
        self.assertIn(
            "physical-bytes-per-year-as-full-save-forecast",
            out["do_not_compare_or_infer"],
        )

    def test_no_sqlite_mutations_and_no_source_report_mutations(self):
        original_legacy = deepcopy(self.legacy)
        original_v2 = deepcopy(self.v2)
        result = compare_independent_a_audits(self.legacy, self.v2)
        self.assertEqual(self.legacy, original_legacy)
        self.assertEqual(self.v2, original_v2)
        self.assertEqual(
            self.original_file_hashes,
            self.v2_fixture._hashes(),
        )
        self.assertIsNone(
            result["legacy"].get("player_career_totals"),
        )

    def test_reject_tampered_annual_payload_math_in_both_eras(self):
        for which in ("legacy", "v2"):
            old, newer = deepcopy(self.legacy), deepcopy(self.v2)
            if which == "legacy":
                old["per_year_logical_growth"]["annual_rows"][0][
                    "logical_payload_bytes"
                ]["match_payload"] += 1
            else:
                newer["year_rows"][0]["exact_json_payload_bytes"][
                    "match_payload"
                ] += 1
            with self.subTest(which=which):
                with self.assertRaises(CareerStorageEvidenceConflict):
                    compare_independent_a_audits(old, newer)

    def test_reject_tampered_source_counts_file_sizes_and_missing_proofs(self):
        changes = (
            ("legacy", lambda r: r["full_a_storage"].update(
                {"archived_match_count": 99,
                 "match_record_shapes": {"full_a": 99}}
            )),
            ("legacy", lambda r: r.update(
                {"cached_stats_match_raw_stats_for_sampled_players": False}
            )),
            ("legacy", lambda r: r["full_a_storage"].update(
                {"sqlite_total_bytes": 1}
            )),
            ("v2", lambda r: r.update(
                {"all_selected_years_original_match_and_cache_deep_verified": False}
            )),
            ("v2", lambda r: r["year_rows"][0].update({"match_count": -1})),
            ("v2", lambda r: r["sqlite_files"]["v2_matches"].update(
                {"file_bytes": 1}
            )),
            ("v2", lambda r: r["year_rows"][0].update(
                {"cached_school_deep_read": {}}
            )),
        )
        for era, mutator in changes:
            old, newer = deepcopy(self.legacy), deepcopy(self.v2)
            mutator(old if era == "legacy" else newer)
            with self.subTest(era=era, mutator=str(mutator)):
                with self.assertRaises(CareerStorageEvidenceConflict):
                    compare_independent_a_audits(old, newer)

    def test_reject_era_misclassification_unsorted_or_duplicate_years(self):
        for era, update in (
            ("legacy", lambda r: r["per_year_logical_growth"][
                "annual_rows"][0].update({"year": 10000})),
            ("v2", lambda r: r["selected_years"].reverse()),
            ("v2", lambda r: r["year_rows"][0].update({"year": 2026})),
            ("v2", lambda r: r["year_rows"][1].update({"year": 10000})),
        ):
            old, newer = deepcopy(self.legacy), deepcopy(self.v2)
            update(old if era == "legacy" else newer)
            with self.subTest(era=era):
                with self.assertRaises(CareerStorageEvidenceConflict):
                    compare_independent_a_audits(old, newer)

    def test_refuse_false_real_world_or_nationwide_progress_claims(self):
        for era, key in (
            ("legacy", "official_game_results"),
            ("legacy", "full_3000_school_100_year_gameplay_verified"),
            ("v2", "complete_career_progression_to_10000_verified"),
            ("v2", "full_nation_or_official_tournament_results_verified"),
        ):
            old, newer = deepcopy(self.legacy), deepcopy(self.v2)
            (old if era == "legacy" else newer)[key] = True
            with self.subTest(key=key):
                with self.assertRaises(CareerStorageEvidenceConflict):
                    compare_independent_a_audits(old, newer)

    def test_json_cli_readonly_and_refuses_output_overwriting_an_input(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            left = folder / "legacy.json"
            right = folder / "v2.json"
            output = folder / "comparison.json"
            left.write_text(
                json.dumps(self.legacy, ensure_ascii=False),
                encoding="utf-8",
            )
            right.write_text(
                json.dumps(self.v2, ensure_ascii=False),
                encoding="utf-8",
            )
            before = {
                p.name: sha256(p.read_bytes()).hexdigest()
                for p in (left, right)
            }
            args = [
                sys.executable, "-m",
                "phase2_engine.career_cross_era_storage_evidence",
                "--legacy-report", str(left),
                "--v2-report", str(right),
                "--output-json", str(output),
            ]
            subprocess.run(args, check=True, capture_output=True, text=True)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                "43G-69", saved["stage"],
            )
            self.assertEqual(
                before, {
                    p.name: sha256(p.read_bytes()).hexdigest()
                    for p in (left, right)
                },
            )
            bad = subprocess.run(
                args[:-1] + [str(left)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, bad.returncode)
            self.assertEqual(
                before, {
                    p.name: sha256(p.read_bytes()).hexdigest()
                    for p in (left, right)
                },
            )


if __name__ == "__main__":
    unittest.main()
