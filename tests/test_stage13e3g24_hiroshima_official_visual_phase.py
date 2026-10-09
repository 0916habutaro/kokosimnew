from __future__ import annotations
import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g24 import (
    GRAPH_FILE, PREVIEW_FILE, audit_2026_hiroshima_stage13e3g24,
)
from phase2_engine.hiroshima_stage13e3g22 import PUBLISHER_GROUPS_FILE, PRIOR_YEAR_PDF_FILE
from phase2_engine.hiroshima_stage13e3g23 import ACCESS_FILE
from phase2_engine.hiroshima_stage13e3g21 import GROUP_REVIEW_FILE
from phase2_engine.hiroshima_stage13e3g17 import CROSSWALK_FILE, GROUP_CONTRACT_FILE
from phase2_engine.hiroshima_stage13e3g18 import TRANSITION_FILE
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE

DATA = Path(__file__).resolve().parents[1] / "data"
FILES = (
    GRAPH_FILE, PREVIEW_FILE, PUBLISHER_GROUPS_FILE, PRIOR_YEAR_PDF_FILE,
    ACCESS_FILE, GROUP_REVIEW_FILE, CROSSWALK_FILE, GROUP_CONTRACT_FILE,
    TRANSITION_FILE, TIMELINE_FILE,
)


def copy_data(root: Path):
    for rel in FILES:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / rel, dst)


def change_csv(root: Path, path: str, change):
    filename = root / path
    with filename.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    change(rows)
    with filename.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class HiroshimaStage13E3G24OfficialImageTests(unittest.TestCase):
    def test_official_2026_preview_macrograph_and_safety(self):
        report = audit_2026_hiroshima_stage13e3g24(DATA)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["new_2026_federation_image_visual_inspections"], 1)
        self.assertEqual(report["2026_autumn_west_initial_teams"], 18)
        self.assertEqual(report["2026_autumn_west_official_macro_phase_nodes"], 9)
        self.assertEqual(report["2026_autumn_west_awarded_main_berths"], 7)
        self.assertEqual(report["2026_graph_direct_a_b_second_place_berths"], 2)
        self.assertEqual(report["2026_graph_cd_second_place_final_gate"], 1)
        self.assertEqual(report["2026_official_pdf_original_bytes"], 0)
        self.assertFalse(report["2026_25_match_number_edges_fully_transcribed"])
        self.assertFalse(report["2026_reusable_full_fmt025_policy_verified"])
        self.assertFalse(report["live_fmt025_runtime_changed"])

    def assert_rejected(self, rel, mutation, fragment):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            copy_data(root)
            change_csv(root, rel, mutation)
            report = audit_2026_hiroshima_stage13e3g24(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any(fragment in x for x in report["errors"]), report["errors"])

    def test_official_image_not_pdf_file(self):
        self.assert_rejected(PREVIEW_FILE,
                             lambda r: r[0].update(source_pdf_bytes_downloaded="yes"),
                             "source_pdf_bytes_downloaded")
        self.assert_rejected(PREVIEW_FILE,
                             lambda r: r[0].update(source_pdf_sha256="f" * 64),
                             "source_pdf_sha256")

    def test_full_arrow_transcription_claim_rejected(self):
        self.assert_rejected(PREVIEW_FILE,
                             lambda r: r[0].update(all_pairings_and_loser_arrows_reviewed="yes"),
                             "all_pairings_and_loser_arrows_reviewed")
        self.assert_rejected(GRAPH_FILE,
                             lambda r: r[8].update(complete_pairing_edges_transcribed="yes"),
                             "complete_pairing_edges_transcribed")

    def test_a_second_place_must_qualify_directly(self):
        self.assert_rejected(GRAPH_FILE,
                             lambda r: r[1].update(official_2026_graph_destination="C_D_CROSS"),
                             "official_2026_graph_destination")

    def test_b_second_place_direct_berth_protected(self):
        self.assert_rejected(GRAPH_FILE,
                             lambda r: r[3].update(verified_berth_from_this_event="no"),
                             "verified_berth_from_this_event")

    def test_cd_only_feed_cross_zone(self):
        self.assert_rejected(GRAPH_FILE,
                             lambda r: r[5].update(official_2026_graph_destination="MAIN"),
                             "official_2026_graph_destination")
        self.assert_rejected(GRAPH_FILE,
                             lambda r: r[7].update(official_2026_graph_destination="MAIN"),
                             "official_2026_graph_destination")

    def test_2025_graph_wrongly_reused(self):
        self.assert_rejected(PRIOR_YEAR_PDF_FILE,
                             lambda r: r[0].update(prior_year_graph_reusable_for_2026="yes"),
                             "2025 gate")

    def test_2026_federation_link_substitution_rejected(self):
        self.assert_rejected(PREVIEW_FILE,
                             lambda r: r[0].update(source_official_pdf_url="https://example.org/draw"),
                             "source_official_pdf_url")
        self.assert_rejected(GRAPH_FILE,
                             lambda r: r[0].update(source_official_pdf_url="https://example.org/draw"),
                             "source_official_pdf_url")

    def test_wrong_season_provenance_rejected(self):
        self.assert_rejected(PREVIEW_FILE,
                             lambda r: r[0].update(document_year="2025"),
                             "document_year")

    def test_missing_phase_event_rejected(self):
        self.assert_rejected(GRAPH_FILE, lambda r: r.pop(), "nine autumn west")

    def test_main_award_winner_mismatch_rejected(self):
        self.assert_rejected(GRAPH_FILE,
                             lambda r: r[8].update(observed_winner="広島城北"),
                             "observed_winner")

    def test_attempt_to_activate_fmt025_rejected(self):
        self.assert_rejected(GRAPH_FILE,
                             lambda r: r[0].update(fmt025_live_route_approved="yes"),
                             "fmt025_live_route_approved")
        self.assert_rejected(GROUP_REVIEW_FILE,
                             lambda r: r[4].update(exact_fmt025_route_release_approved="yes"),
                             "must not release")

    def test_prior_2026_html_only_snapshot_is_not_rewritten(self):
        self.assert_rejected(ACCESS_FILE,
                             lambda r: r[4].update(preview_outcome="official_image_read"),
                             "Stage23 dated")

    def test_extra_duplicate_phase_event_rejected(self):
        self.assert_rejected(GRAPH_FILE,
                             lambda r: r[1].update(event_audit_id=r[0]["event_audit_id"]),
                             "duplicate phase")


if __name__ == "__main__":
    unittest.main()
