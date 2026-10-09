from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase2_engine.hiroshima_official_pdf_intake import (
    OFFICIAL_2026_WEST_SOURCE, OfficialPdfIntakeError,
    inspect_local_pdf_candidate, inspect_with_poppler_pdfinfo,
    intake_offline_pdf, render_original_pdf_preview,
)
from phase2_engine.hiroshima_stage13e3g29 import (
    ATTEMPT_FILE, audit_2026_hiroshima_stage13e3g29,
)

DATA = Path(__file__).resolve().parents[1] / "data"


def plausible_pdf() -> bytes:
    """Intentionally not a valid parsed PDF: signature-only preflight example."""
    return b"%PDF-1.4\n" + b"0" * 800 + b"\n%%EOF\n"


def change_csv(path: Path, fn):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        columns, rows = rd.fieldnames, list(rd)
    fn(rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


class HiroshimaStage13E3G29OfficialPdfIntakeTests(unittest.TestCase):
    def test_original_pdf_missing_but_all_57_review_slots_preserved(self):
        report = audit_2026_hiroshima_stage13e3g29(DATA)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["new_pdf_acquisition_attempts"], 5)
        self.assertEqual(report["original_pdf_bytes_recovered"], 0)
        self.assertFalse(report["sha256_original_available"])
        self.assertEqual(report["official_match_numbers_independently_confirmed"], 0)
        self.assertEqual(report["official_arrows_independently_confirmed"], 0)
        self.assertEqual(report["historical_games_with_review_slots"], 25)
        self.assertEqual(report["historical_arrows_with_review_slots"], 32)
        self.assertTrue(report["offline_pdf_sha256_and_300dpi_importer_ready"])
        self.assertFalse(report["live_fmt025_runtime_enabled"])
        self.assertFalse(report["optional_ranking_enabled"])

    def assert_rejected(self, modify, fragment):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "data"
            shutil.copytree(DATA, root)
            change_csv(root / ATTEMPT_FILE, modify)
            report = audit_2026_hiroshima_stage13e3g29(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any(fragment in e for e in report["errors"]), report["errors"])

    def test_unproven_original_pdf_claim_is_rejected(self):
        self.assert_rejected(
            lambda rows: rows[2].update(raw_pdf_received="yes"), "raw_pdf_received"
        )
        self.assert_rejected(
            lambda rows: rows[3].update(pdf_bytes_sha256="a" * 64), "pdf_bytes_sha256"
        )

    def test_unverified_match_number_and_arrow_promotion_rejected(self):
        self.assert_rejected(
            lambda rows: rows[1].update(actual_official_match_numbers_verified="25"),
            "actual_official_match_numbers_verified",
        )
        self.assert_rejected(
            lambda rows: rows[2].update(actual_official_individual_arrows_verified="32"),
            "actual_official_individual_arrows_verified",
        )

    def test_official_source_or_2025_mix_rejected(self):
        self.assert_rejected(
            lambda rows: rows[0].update(document_year="2025"), "document_year"
        )
        self.assert_rejected(
            lambda rows: rows[0].update(
                target_official_pdf_url="https://hiroshima-hbf1950.com/img/file509.pdf"
            ), "target_official_pdf_url",
        )

    def test_transport_failure_and_runtime_changes_rejected(self):
        self.assert_rejected(
            lambda rows: rows[4].update(observed_outcome="pdf_downloaded"),
            "observed_outcome",
        )
        self.assert_rejected(
            lambda rows: rows[4].update(allow_fmt025_runtime="yes"),
            "allow_fmt025_runtime",
        )

    def test_missing_or_duplicate_attempt_is_rejected(self):
        self.assert_rejected(lambda rows: rows.pop(), "five distinct")
        self.assert_rejected(lambda rows: rows.append(dict(rows[0])), "five distinct")

    def test_local_potential_pdf_has_digest_but_not_official_proof(self):
        raw = plausible_pdf()
        result = inspect_local_pdf_candidate(
            raw, source_url=OFFICIAL_2026_WEST_SOURCE,
            intake_medium="operator_supplied_original_pdf",
        )
        self.assertEqual(result.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(result.claimed_year, "2026")
        self.assertEqual(result.intended_stage_group, "SGR000144")
        self.assertTrue(result.raw_pdf_bytes_received)
        self.assertFalse(result.source_identity_independently_verified)
        self.assertEqual(result.official_match_numbers_independently_verified, 0)
        self.assertEqual(result.official_transfer_arrows_independently_verified, 0)
        self.assertIsNone(result.parsed_page_count)
        self.assertFalse(result.runtime_enabled)

    def test_google_drive_loading_html_and_thumbnail_must_not_be_a_pdf(self):
        bodies = [
            b"<html>Loading...</html>" * 100,
            b"\x89PNG\r\n\x1a\n" + b"0" * 900,
            b"%PDF-1.4\n" + b"0" * 800,
            b"%PDF-1.4\n%%EOF\n",
            b"%PDF-1.9\n" + b"0" * 800 + b"%%EOF",
        ]
        for body in bodies:
            with self.subTest(head=body[:15]):
                with self.assertRaises(OfficialPdfIntakeError):
                    inspect_local_pdf_candidate(
                        body, source_url=OFFICIAL_2026_WEST_SOURCE,
                        intake_medium="operator_supplied_original_pdf",
                    )

    def test_no_prior_year_source_or_untrusted_intake_method(self):
        raw = plausible_pdf()
        for source, medium in (
            ("https://hiroshima-hbf1950.com/img/file509.pdf", "operator_supplied_original_pdf"),
            (OFFICIAL_2026_WEST_SOURCE, "web_html_shell"),
            (OFFICIAL_2026_WEST_SOURCE, "2025_bracket_official"),
        ):
            with self.subTest(source=source, medium=medium):
                with self.assertRaises(OfficialPdfIntakeError):
                    inspect_local_pdf_candidate(
                        raw, source_url=source, intake_medium=medium,
                    )

    def test_pdfinfo_requires_valid_count_and_success(self):
        with patch("phase2_engine.hiroshima_official_pdf_intake.shutil.which", return_value="/usr/bin/pdfinfo"):
            with patch("phase2_engine.hiroshima_official_pdf_intake.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess([], 0, "Pages: 2\n", "")
                self.assertEqual(inspect_with_poppler_pdfinfo(Path("candidate.pdf")), 2)
                run.return_value = subprocess.CompletedProcess([], 1, "", "not a PDF")
                with self.assertRaises(OfficialPdfIntakeError):
                    inspect_with_poppler_pdfinfo(Path("candidate.pdf"))
                run.return_value = subprocess.CompletedProcess([], 0, "Pages: 0\n", "")
                with self.assertRaises(OfficialPdfIntakeError):
                    inspect_with_poppler_pdfinfo(Path("candidate.pdf"))
        with patch("phase2_engine.hiroshima_official_pdf_intake.shutil.which", return_value=None):
            with self.assertRaises(OfficialPdfIntakeError):
                inspect_with_poppler_pdfinfo(Path("candidate.pdf"))

    def test_300_dpi_high_resolution_render_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outdir = root / "rendered"
            pdf = root / "candidate.pdf"
            pdf.write_bytes(plausible_pdf())
            with patch("phase2_engine.hiroshima_official_pdf_intake.shutil.which", return_value="/usr/bin/pdftoppm"):
                with patch("phase2_engine.hiroshima_official_pdf_intake.subprocess.run") as run:
                    def fake(args, **kwargs):
                        self.assertEqual(args[args.index("-r")+1], "300")
                        prefix = Path(args[-1])
                        prefix.parent.mkdir(parents=True, exist_ok=True)
                        (prefix.parent / (prefix.name + "-1.png")).write_bytes(b"fake")
                        return subprocess.CompletedProcess(args, 0, "", "")
                    run.side_effect = fake
                    result = render_original_pdf_preview(pdf, outdir, page_count=1)
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].suffix, ".png")
            with self.assertRaises(OfficialPdfIntakeError):
                render_original_pdf_preview(pdf, outdir, page_count=13)

    def test_manifest_from_parser_verified_candidate_still_unapproved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "candidate.pdf"
            pdf.write_bytes(plausible_pdf())
            with patch("phase2_engine.hiroshima_official_pdf_intake.inspect_with_poppler_pdfinfo", return_value=1):
                manifest = intake_offline_pdf(
                    pdf_path=pdf, output_dir=root / "output", render=False,
                )
            saved = json.loads((root / "output" / "original_pdf_candidate_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, manifest)
            self.assertEqual(saved["parsed_page_count"], 1)
            self.assertEqual(saved["sha256"], hashlib.sha256(pdf.read_bytes()).hexdigest())
            self.assertFalse(saved["source_identity_independently_verified"])
            self.assertFalse(saved["runtime_enabled"])
            self.assertEqual(saved["rendered_png_filenames"], [])
            self.assertIn("NOT", saved["authenticity_note"])


if __name__ == "__main__":
    unittest.main()
