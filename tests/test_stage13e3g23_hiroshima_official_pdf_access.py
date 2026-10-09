from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g23 import (
    ACCESS_FILE, SOURCE_FILE, audit_2026_hiroshima_stage13e3g23, _drive_id,
)
from phase2_engine.hiroshima_stage13e3g21 import GROUP_REVIEW_FILE
from phase2_engine.hiroshima_stage13e3g22 import PRIOR_YEAR_PDF_FILE

DATA = Path(__file__).resolve().parents[1] / "data"
FILES = (ACCESS_FILE, SOURCE_FILE, GROUP_REVIEW_FILE, PRIOR_YEAR_PDF_FILE)


def copy_data(root: Path):
    for relative in FILES:
        dest = root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / relative, dest)


def modify(root: Path, filename: str, change):
    path = root / filename
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        rows = list(reader)
    change(rows)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


class HiroshimaOfficialPdfStage23Tests(unittest.TestCase):
    def test_eight_official_links_and_zero_claimed_pdf_bodies(self):
        result = audit_2026_hiroshima_stage13e3g23(DATA)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["2026_federation_pdf_links"], 8)
        self.assertEqual(result["2026_pdf_landing_shells_checked"], 8)
        self.assertEqual(result["2026_official_pdf_bodies_obtained"], 0)
        self.assertEqual(result["2026_official_draw_edges_verified"], 0)
        self.assertTrue(result["2026_all_eight_annual_fmt025_graphs_blocked"])
        self.assertFalse(result["active_runtime_changed"])

    def assert_rejected(self, filename: str, change, fragment: str):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            copy_data(root)
            modify(root, filename, change)
            result = audit_2026_hiroshima_stage13e3g23(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any(fragment in e for e in result["errors"]), result["errors"])

    def test_claimed_pdf_read_without_bytes_rejected(self):
        self.assert_rejected(ACCESS_FILE, lambda x: x[4].update(pdf_body_bytes_obtained="yes"), "pdf_body_bytes_obtained")

    def test_claimed_pairings_without_pdf_rejected(self):
        self.assert_rejected(ACCESS_FILE, lambda x: x[4].update(verified_pairing_edge_count="25"), "verified_pairing_edge_count")

    def test_replaced_hash_without_original_rejected(self):
        self.assert_rejected(ACCESS_FILE, lambda x: x[4].update(pdf_sha256="1" * 64), "pdf_sha256")

    def test_fake_access_success_rejected(self):
        self.assert_rejected(ACCESS_FILE, lambda x: x[4].update(preview_outcome="verified_pdf"), "preview_outcome")

    def test_wrong_year_and_2025_reuse_rejected(self):
        self.assert_rejected(ACCESS_FILE, lambda x: x[4].update(document_year="2025"), "document_year")
        self.assert_rejected(PRIOR_YEAR_PDF_FILE, lambda x: x[0].update(prior_year_graph_reusable_for_2026="yes"), "2025 official graph")

    def test_wrong_official_title_rejected(self):
        self.assert_rejected(ACCESS_FILE, lambda x: x[4].update(official_file_title="2026 fully parsed.pdf"), "official_file_title")

    def test_duplicate_pdf_source_rejected(self):
        self.assert_rejected(SOURCE_FILE, lambda x: x[4].update(official_pdf_url=x[0]["official_pdf_url"]), "official_google_drive_file_id")

    def test_manual_claim_of_fmt025_unlock_rejected(self):
        self.assert_rejected(ACCESS_FILE, lambda x: x[4].update(allow_live_fmt025_runtime="yes"), "allow_live_fmt025_runtime")
        self.assert_rejected(GROUP_REVIEW_FILE, lambda x: x[4].update(exact_fmt025_route_release_approved="yes"), "FMT025 release status")

    def test_missing_or_repeated_district_rejected(self):
        self.assert_rejected(ACCESS_FILE, lambda x: x.pop(), "eight distinct")

    def test_uri_id_parser_accepts_only_drive_file_view_links(self):
        self.assertEqual(_drive_id("https://drive.google.com/file/d/ABC_123/view?usp=sharing"), "ABC_123")
        self.assertIsNone(_drive_id("https://example.com/file/d/ABC_123/view"))
        self.assertIsNone(_drive_id("https://drive.google.com/uc?export=download&id=ABC_123"))


if __name__ == "__main__":
    unittest.main()
