from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g30 import (
    WRITTEN_RULES_FILE, UNRESOLVED_ROUTE_RULES_FILE,
    audit_2026_hiroshima_stage13e3g30, evaluate_written_rule_scope,
)

DATA = Path(__file__).resolve().parents[1] / "data"


def edit_csv(path: Path, change):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns, rows = reader.fieldnames, list(reader)
    change(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class HiroshimaStage13E3G30WrittenRulesTests(unittest.TestCase):
    def test_2026_official_written_scope_and_missing_48_route_rules(self):
        result = audit_2026_hiroshima_stage13e3g30(DATA)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["written_source_claims"], 23)
        self.assertEqual(result["evidence_grades"], {
            "federation_page_explicit": 16,
            "federation_page_reference_only": 1,
            "contemporary_independent_report": 5,
            "federation_image_visual_macro_only": 1,
        })
        self.assertEqual(result["authority_scoped_claims"],
                         {"quota": 6, "calendar": 6, "MAIN_rules_only": 4})
        self.assertEqual(result["year_limited_official_autumn_berths"], 32)
        self.assertEqual(result["unresolved_district_rule_proof_items"], 48)
        self.assertEqual(result["2026_match_numbered_draw_rules_proven"], 0)
        self.assertEqual(result["verified_primary_loser_round_selectors"], 0)
        self.assertFalse(result["year_independent_fmt025_policy_approved"])
        self.assertFalse(result["live_fmt025_runtime_changed"])
        self.assertFalse(result["optional_ranking_unlocked"])

    def assert_rejected(self, relative: str, action, fragment: str):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            shutil.copytree(DATA, root)
            edit_csv(root / relative, action)
            result = audit_2026_hiroshima_stage13e3g30(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any(fragment in e for e in result["errors"]),
                            result["errors"])

    def test_federation_quota_change_detected(self):
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: rows[1].update(normalized_claim_value="8"),
                             "autumn_west_quota/normalized_claim_value")
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: rows[0].update(normalized_claim_value="33"),
                             "autumn_MAIN_slots/normalized_claim_value")

    def test_federation_date_shift_detected(self):
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: rows[5].update(normalized_claim_value="2026-08-21"),
                             "autumn_qualifier_start/normalized_claim_value")

    def test_year_change_and_source_link_substitution_detected(self):
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: rows[2].update(document_year="2025"),
                             "autumn_north_quota/document_year")
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: rows[4].update(source_url="https://example.com"),
                             "autumn_east_quota/source_url")

    def test_scope_prohibits_copying_main_mercy_into_qualifier_rules(self):
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: next(x for x in rows if x["claim_key"] == "autumn_MAIN_mercy").update(
                                 applicability_scope="district_qualifier_rules"
                             ),
                             "autumn_MAIN_mercy/applicability_scope")
        row = next(x for x in read_csv(DATA / WRITTEN_RULES_FILE)
                   if x["claim_key"] == "autumn_MAIN_mercy")
        decision = evaluate_written_rule_scope(row)
        self.assertTrue(decision.can_use_as_main_only_rules)
        self.assertFalse(decision.can_use_as_year_limited_calendar)
        self.assertFalse(decision.can_select_primary_loser_destination)
        self.assertFalse(decision.can_enable_fmt025_runtime)

    def test_direct_quota_can_be_used_as_2026_quota_but_not_draw(self):
        row = next(x for x in read_csv(DATA / WRITTEN_RULES_FILE)
                   if x["claim_key"] == "autumn_west_quota")
        effect = evaluate_written_rule_scope(row)
        self.assertTrue(effect.can_use_as_year_limited_quota)
        self.assertFalse(effect.can_determine_qualifier_bracket)
        self.assertFalse(effect.can_claim_year_independent_policy)

    def test_media_west_four_plus_three_is_not_federation_transfer_rule(self):
        row = next(x for x in read_csv(DATA / WRITTEN_RULES_FILE)
                   if x["claim_key"] == "autumn_west_report_repechage")
        effect = evaluate_written_rule_scope(row)
        self.assertFalse(effect.can_use_as_year_limited_quota)
        self.assertFalse(effect.can_select_primary_loser_destination)
        self.assertFalse(effect.can_enable_fmt025_runtime)
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: next(x for x in rows if x["claim_key"] == "autumn_west_report_repechage").update(
                                 evidence_grade="federation_page_explicit"
                             ),
                             "autumn_west_report_repechage/evidence_grade")

    def test_rule_reference_is_not_copied_as_rule_text(self):
        row = next(x for x in read_csv(DATA / WRITTEN_RULES_FILE)
                   if x["claim_key"] == "autumn_external_rule_references")
        effect = evaluate_written_rule_scope(row)
        self.assertFalse(effect.can_use_as_main_only_rules)
        self.assertFalse(effect.can_select_primary_loser_destination)
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: next(x for x in rows if x["claim_key"] == "autumn_external_rule_references").update(
                                 evidence_grade="federation_page_explicit"
                             ),
                             "autumn_external_rule_references/evidence_grade")

    def test_visual_macro_not_automatic_loser_selector(self):
        row = next(x for x in read_csv(DATA / WRITTEN_RULES_FILE)
                   if x["claim_key"] == "autumn_west_2026_macro_C_D_cross")
        self.assertFalse(evaluate_written_rule_scope(row).can_determine_qualifier_bracket)
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: rows[-1].update(annual_loser_selector_proven="yes"),
                             "autumn_west_2026_macro_C_D_cross/annual_loser_selector_proven")

    def test_unverified_fmt025_or_future_rules_cannot_be_promoted(self):
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: rows[0].update(runtime_use_as_2026_fmt025_selector="yes"),
                             "autumn_MAIN_slots/runtime_use_as_2026_fmt025_selector")
        self.assert_rejected(WRITTEN_RULES_FILE,
                             lambda rows: rows[1].update(year_independent_policy_approved="yes"),
                             "autumn_west_quota/year_independent_policy_approved")

    def test_rule_proof_requirements_exactly_six_per_group(self):
        rows = read_csv(DATA / UNRESOLVED_ROUTE_RULES_FILE)
        self.assertEqual(len(rows), 48)
        self.assertEqual(len(set((x["season"], x["district_code"], x["requested_rule_key"])
                                 for x in rows)), 48)
        self.assertEqual(len([x for x in rows if x["rule_category"] == "primary_loser_transfer"]), 8)
        self.assertEqual(len([x for x in rows if x["rule_category"] == "conditional_retry"]), 8)

    def test_unproven_loser_and_cross_route_approval_detected(self):
        self.assert_rejected(UNRESOLVED_ROUTE_RULES_FILE,
                             lambda rows: next(x for x in rows if x["rule_category"] == "primary_loser_transfer").update(
                                 explicit_2026_formula_available="yes"
                             ),
                             "explicit_2026_formula_available")
        self.assert_rejected(UNRESOLVED_ROUTE_RULES_FILE,
                             lambda rows: rows[28].update(fmt025_runtime_authorized="yes"),
                             "fmt025_runtime_authorized")

    def test_distinct_2026_and_future_policy_required(self):
        self.assert_rejected(UNRESOLVED_ROUTE_RULES_FILE,
                             lambda rows: rows[0].update(eligible_for_repeatable_years="yes"),
                             "eligible_for_repeatable_years")
        self.assert_rejected(UNRESOLVED_ROUTE_RULES_FILE,
                             lambda rows: rows[0].update(optional_ranking_authorized="yes"),
                             "optional_ranking_authorized")

    def test_wrong_or_duplicated_requirement_detected(self):
        self.assert_rejected(UNRESOLVED_ROUTE_RULES_FILE,
                             lambda rows: rows.pop(), "48")
        self.assert_rejected(UNRESOLVED_ROUTE_RULES_FILE,
                             lambda rows: rows.append(dict(rows[0])), "48")
        self.assert_rejected(UNRESOLVED_ROUTE_RULES_FILE,
                             lambda rows: rows[0].update(district_code="south"),
                             "unverified route evidence promoted")

    def test_cannot_accept_unknown_claim_or_incomplete_record(self):
        with self.assertRaises(ValueError):
            evaluate_written_rule_scope({"claim_key": "fake_automatic_loser_rule"})
        with self.assertRaises(ValueError):
            sample = dict(read_csv(DATA / WRITTEN_RULES_FILE)[0])
            sample["claim_key"] = "future_2027_standard_rule"
            evaluate_written_rule_scope(sample)


if __name__ == "__main__":
    unittest.main()
