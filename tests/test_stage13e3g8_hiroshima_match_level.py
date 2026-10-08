from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_match_level_2026 import (
    PDF_FILE, ANCHOR_FILE, ROUTE_FILE, PRIOR_FILE,
    audit_2026_hiroshima_match_level_evidence,
)


DATA = Path(__file__).resolve().parents[1] / "data"


def _fixture(dest: Path):
    for rel in (PDF_FILE, ANCHOR_FILE, ROUTE_FILE, PRIOR_FILE):
        f = dest / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / rel, f)


def _alter(root: Path, rel: str, edit):
    f = root / rel
    with f.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    edit(rows)
    with f.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class HiroshimaStage13E3G8EvidenceTests(unittest.TestCase):
    def test_eight_official_pdf_links_and_anchor_results(self):
        r = audit_2026_hiroshima_match_level_evidence(DATA)
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(8, r["official_pdf_links_identified"])
        self.assertEqual(8, r["district_seasons_with_anchor"])
        self.assertEqual(8, r["new_qualification_anchor_records"])
        self.assertEqual(2, r["overlap_with_previous_examples"])
        self.assertEqual(15, r["combined_unique_named_match_examples"])

    def test_pdf_link_only_never_authorizes_fmt025(self):
        r = audit_2026_hiroshima_match_level_evidence(DATA)
        self.assertEqual(0, r["official_pdf_bodies_checked"])
        self.assertFalse(r["full_individual_match_audit_complete"])
        self.assertFalse(r["fmt025_release_allowed"])
        self.assertEqual(0, r["verified_additional_optional_ranking_matches"])

    def test_false_claim_of_pdf_review_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _fixture(root)
            _alter(root, PDF_FILE, lambda rows: rows[0].update(
                source_access="pdf_fully_inspected",
                full_fixture_review_status="complete",
            ))
            r = audit_2026_hiroshima_match_level_evidence(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("unsupported claim" in e for e in r["errors"]))
            self.assertFalse(r["fmt025_release_allowed"])

    def test_qualification_decider_cannot_be_relabelled_ranking_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _fixture(root)
            _alter(root, ANCHOR_FILE, lambda rows: rows[-1].update(
                classification="post_qualification_optional_ranking",
                pre_match_proof="both_locked",
            ))
            r = audit_2026_hiroshima_match_level_evidence(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("ranking-only" in e for e in r["errors"]))

    def test_reconciled_old_match_score_cannot_change(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _fixture(root)
            _alter(root, ANCHOR_FILE, lambda rows: rows[0].update(
                team1_score="8",
            ))
            r = audit_2026_hiroshima_match_level_evidence(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("prior qualification evidence conflicts" in e
                                for e in r["errors"]))

    def test_invalid_winner_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _fixture(root)
            _alter(root, ANCHOR_FILE, lambda rows: rows[2].update(
                winner_name="広島桜が丘",
            ))
            r = audit_2026_hiroshima_match_level_evidence(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("score/winner mismatch" in e for e in r["errors"]))

    def test_duplicate_official_pdf_link_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _fixture(root)
            def mut(rows):
                rows[0]["official_pdf_url"] = rows[1]["official_pdf_url"]
            _alter(root, PDF_FILE, mut)
            r = audit_2026_hiroshima_match_level_evidence(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("duplicate or missing official PDF identity" in e
                                for e in r["errors"]))

    def test_wrong_stage_group_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _fixture(root)
            _alter(root, PDF_FILE, lambda rows: rows[0].update(
                stage_group_id="SGR000147",
            ))
            r = audit_2026_hiroshima_match_level_evidence(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("incorrect competition/group" in e
                                for e in r["errors"]))


if __name__ == "__main__":
    unittest.main()
