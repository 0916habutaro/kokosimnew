from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g12 import (
    EVIDENCE_FILE, QUEUE_FILE, audit_2026_hiroshima_stage13e3g12
)
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from phase2_engine.hiroshima_berth_roster_2026 import ROSTER_FILE, STAGE_GROUP_FILE
from phase2_engine.hiroshima_match_level_2026 import (
    ANCHOR_FILE, PRIOR_FILE, ROUTE_FILE, PDF_FILE
)

ROOT = Path(__file__).resolve().parents[1] / "data"
FILES = (EVIDENCE_FILE, QUEUE_FILE, TIMELINE_FILE, ROSTER_FILE,
         STAGE_GROUP_FILE, ANCHOR_FILE, PRIOR_FILE, ROUTE_FILE, PDF_FILE)


def _copy(root):
    for relative in FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def _modify(root, rel, fn):
    p = root / rel
    with p.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        keys, rows = reader.fieldnames, list(reader)
    fn(rows)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G12BerthGameEvidenceTests(unittest.TestCase):
    def test_all_24_games_are_reconciled_and_22_gaps_remain(self):
        r = audit_2026_hiroshima_stage13e3g12(ROOT)
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(24, r["supplemental_qualifying_games"])
        self.assertEqual(223, r["cumulative_dated_matches"])
        self.assertEqual(63, r["cumulative_evidenced_qualification_events"])
        self.assertEqual(0, r["remaining_unlinked_qualifying_schools"])
        self.assertTrue(r["historic_match_timeline_pass"])
        self.assertTrue(r["prefectural_roster_pass"])

    def test_eight_new_award_games_in_each_target_district(self):
        r = audit_2026_hiroshima_stage13e3g12(ROOT)
        self.assertEqual({
            "spring_east": 8, "spring_south": 8, "autumn_east": 8
        }, r["supplemental_by_district"])

    def test_official_pdf_not_reviewed_and_fmt025_remains_pending(self):
        r = audit_2026_hiroshima_stage13e3g12(ROOT)
        self.assertFalse(r["official_federation_pdf_full_review_complete"])
        self.assertEqual(0, r["ranking_only_post_qualification_games_proven"])
        self.assertFalse(r["fmt025_release_allowed"])

    def test_previously_unrecorded_sogo_gijutsu_is_qualified_april_5(self):
        with (ROOT / EVIDENCE_FILE).open(encoding="utf-8", newline="") as f:
            cases = list(csv.DictReader(f))
        game = next(x for x in cases if x["qualifying_school"] == "総合技術")
        self.assertEqual(("2026-04-05","大門","13-3"),(
            game["date"],game["losing_school"],game["score"]))

    def test_fukuyama_prior_stage13e3g7_game_is_preserved(self):
        with (ROOT / EVIDENCE_FILE).open(encoding="utf-8", newline="") as f:
            cases = list(csv.DictReader(f))
        game = next(x for x in cases if x["season"] == "autumn"
                    and x["qualifying_school"] == "福山")
        self.assertEqual(("2026-08-29","府中","10-1"),(
            game["date"],game["losing_school"],game["score"]))

    def test_altered_game_score_is_rejected_by_independent_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);_copy(root)
            _modify(root, EVIDENCE_FILE, lambda rr: rr[0].update(score="12-1"))
            report = audit_2026_hiroshima_stage13e3g12(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("contradicts dated game" in e for e in report["errors"]))

    def test_claim_of_official_pdf_inspection_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);_copy(root)
            _modify(root, EVIDENCE_FILE, lambda rr: rr[0].update(
                official_pdf_match_review="complete"))
            report = audit_2026_hiroshima_stage13e3g12(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("unsupported federation PDF" in e for e in report["errors"]))

    def test_missing_award_game_row_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);_copy(root)
            _modify(root, EVIDENCE_FILE, lambda rr: rr.pop())
            report = audit_2026_hiroshima_stage13e3g12(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("expected 8 new award games" in e for e in report["errors"]))

    def test_queue_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);_copy(root)
            _modify(root, QUEUE_FILE, lambda rr: rr.append(dict(gap_id="HG20269999",season="spring",district_code="east",school_name="近大福山",roster_id="HB20260025",status="award_match_not_yet_documented",needed_evidence="dated_berth_decider_or_exemption_proof",source_url="https://example.org")))
            report = audit_2026_hiroshima_stage13e3g12(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("remaining gap queue" in e for e in report["errors"]))

    def test_wrong_route_block_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);_copy(root)
            _modify(root, EVIDENCE_FILE, lambda rr: rr[0].update(route_block="F"))
            report = audit_2026_hiroshima_stage13e3g12(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("wrong official route block" in e for e in report["errors"]))


if __name__ == "__main__":
    unittest.main()
