from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g27 import (
    OTHER_SEVEN_FILE, EIGHT_COMPARISON_FILE, audit_2026_hiroshima_stage13e3g27,
)
from phase2_engine.hiroshima_stage13e3g23 import ACCESS_FILE, SOURCE_FILE
from phase2_engine.hiroshima_stage13e3g20 import ZONE_CONTRACT_FILE
from phase2_engine.hiroshima_stage13e3g21 import GROUP_REVIEW_FILE

DATA = Path(__file__).resolve().parents[1] / "data"


def change_file(root: Path, relative: str, operation):
    path = root / relative
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        cols, rows = reader.fieldnames, list(reader)
    operation(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G27AllOfficialSeasonalImagesTests(unittest.TestCase):
    def test_all_eight_official_images_and_spring_autumn_berths(self):
        result = audit_2026_hiroshima_stage13e3g27(DATA)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["official_2026_new_visual_previews"], 7)
        self.assertEqual(result["official_2026_seasonal_group_previews_total"], 8)
        self.assertEqual(result["spring_total_berths"], 32)
        self.assertEqual(result["autumn_total_berths"], 32)
        self.assertEqual(result["spring_exempt_berths"], 1)
        self.assertEqual(result["publisher_role_counts"],
                         {"primary": 38, "second_place": 35, "cross": 14})
        self.assertEqual(result["group_macro_counts"]["spring/south"], 6)
        self.assertEqual(result["group_macro_counts"]["autumn/east"], 5)
        self.assertFalse(result["official_2026_all_draw_arrows_verified"])
        self.assertEqual(result["source_pdf_bytes_acquired"], 0)
        self.assertFalse(result["official_year_independent_fmt025_policy_verified"])
        self.assertFalse(result["active_fmt025_runtime_changed"])
        self.assertFalse(result["optional_ranking_unlocked"])

    def assert_rejected(self, relative, mutation, expected_fragment):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "data"
            shutil.copytree(DATA, root)
            change_file(root, relative, mutation)
            result = audit_2026_hiroshima_stage13e3g27(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any(expected_fragment in e for e in result["errors"]),
                            result["errors"])

    def test_missing_image_record_rejected(self):
        self.assert_rejected(OTHER_SEVEN_FILE, lambda rows: rows.pop(),
                             "seven new official")

    def test_year_or_district_forgery_rejected(self):
        self.assert_rejected(OTHER_SEVEN_FILE,
                             lambda rows: rows[0].update(document_year="2025"),
                             "document_year")
        self.assert_rejected(OTHER_SEVEN_FILE,
                             lambda rows: rows[0].update(district_code="westX"),
                             "seven new official")

    def test_google_drive_document_substitution_rejected(self):
        self.assert_rejected(OTHER_SEVEN_FILE,
                             lambda rows: rows[0].update(official_pdf_url="https://example.com/p.pdf"),
                             "official_pdf_url")

    def test_false_pdf_bytes_and_sha_claims_rejected(self):
        self.assert_rejected(OTHER_SEVEN_FILE,
                             lambda rows: rows[1].update(official_raw_pdf_bytes_downloaded="yes"),
                             "official_raw_pdf_bytes_downloaded")

    def test_false_individual_draw_arrows_rejected(self):
        self.assert_rejected(OTHER_SEVEN_FILE,
                             lambda rows: rows[3].update(all_individual_pairing_arrows_verified="yes"),
                             "all_individual_pairing_arrows_verified")
        self.assert_rejected(OTHER_SEVEN_FILE,
                             lambda rows: rows[5].update(all_official_match_numbers_verified="yes"),
                             "all_official_match_numbers_verified")

    def test_year_generic_loser_rule_cannot_be_claimed(self):
        self.assert_rejected(OTHER_SEVEN_FILE,
                             lambda rows: rows[2].update(future_year_general_rule_verified="yes"),
                             "future_year_general_rule_verified")
        self.assert_rejected(OTHER_SEVEN_FILE,
                             lambda rows: rows[4].update(annual_loser_round_selector_verified="yes"),
                             "annual_loser_round_selector_verified")

    def test_no_rank_only_and_no_live_fmt025(self):
        self.assert_rejected(OTHER_SEVEN_FILE,
                             lambda rows: rows[4].update(fmt025_live_runtime_enabled="yes"),
                             "fmt025_live_runtime_enabled")
        self.assert_rejected(OTHER_SEVEN_FILE,
                             lambda rows: rows[6].update(optional_ranking_unlocked="yes"),
                             "optional_ranking_unlocked")

    def test_spring_west_exempt_from_draw_not_double_counted(self):
        self.assert_rejected(EIGHT_COMPARISON_FILE,
                             lambda rows: rows[0].update(direct_main_exemption_berths="0"),
                             "direct_main_exemption_berths")
        self.assert_rejected(EIGHT_COMPARISON_FILE,
                             lambda rows: rows[0].update(seasonal_group_berth_total="6"),
                             "seasonal_group_berth_total")

    def test_seasonal_quota_and_zone_overwrite_rejected(self):
        self.assert_rejected(EIGHT_COMPARISON_FILE,
                             lambda rows: rows[2].update(zone_count="5"),
                             "zone_count")
        self.assert_rejected(EIGHT_COMPARISON_FILE,
                             lambda rows: rows[6].update(other_qualifier_berths="3"),
                             "other_qualifier_berths")

    def test_aggregate_cross_events_are_publisher_not_official_arrows(self):
        self.assert_rejected(EIGHT_COMPARISON_FILE,
                             lambda rows: rows[7].update(publisher_cross_event_count="9"),
                             "publisher_cross_event_count")
        self.assert_rejected(EIGHT_COMPARISON_FILE,
                             lambda rows: rows[5].update(official_complete_draw_edges_transcribed="yes"),
                             "official_complete_draw_edges_transcribed")

    def test_source_html_loading_earlier_snapshot_remains_historical(self):
        self.assert_rejected(ACCESS_FILE,
                             lambda rows: rows[0].update(preview_outcome="official_draw_complete"),
                             "Stage23 earlier access snapshot")

    def test_federation_link_mapping_and_runtime_review_stay_locked(self):
        self.assert_rejected(SOURCE_FILE,
                             lambda rows: rows[1].update(official_pdf_url="https://example.com/other"),
                             "official_pdf_url")
        self.assert_rejected(ZONE_CONTRACT_FILE,
                             lambda rows: rows[4].update(allow_live_runtime_integration="yes"),
                             "does not authorize live routing")
        self.assert_rejected(GROUP_REVIEW_FILE,
                             lambda rows: rows[6].update(exact_fmt025_route_release_approved="yes"),
                             "does not authorize live routing")


if __name__ == "__main__":
    unittest.main()
