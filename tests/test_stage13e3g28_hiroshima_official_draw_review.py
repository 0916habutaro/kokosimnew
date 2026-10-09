from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g28 import (
    NUMBER_QUEUE_FILE, ARROW_QUEUE_FILE, DrawReviewError,
    DrawMatchProposal, DrawArrowProposal, audit_2026_hiroshima_stage13e3g28,
    preflight_proposed_2026_draw,
)
from phase2_engine.hiroshima_stage13e3g25 import NODES_FILE, EDGES_FILE
from phase2_engine.hiroshima_stage13e3g24 import OFFICIAL_SOURCE

DATA = Path(__file__).resolve().parents[1] / "data"


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def change_csv(path: Path, fn):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns, rows = reader.fieldnames, list(reader)
    fn(rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


class HiroshimaStage13E3G28NumberedDrawReviewTests(unittest.TestCase):
    def test_57_separate_official_review_items_are_pending(self):
        report = audit_2026_hiroshima_stage13e3g28(DATA)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["official_number_review_tasks"], 25)
        self.assertEqual(report["official_arrow_review_tasks"], 32)
        self.assertEqual(report["high_priority"], {
            "primary_loser_to_repechage": 14,
            "runnerup_C_D_cross_gate": 2,
            "other_observed_continuation": 16,
        })
        self.assertEqual(report["official_match_numbers_independently_verified"], 0)
        self.assertEqual(report["official_individual_arrows_independently_verified"], 0)
        self.assertFalse(report["official_pdf_bytes_acquired"])
        self.assertFalse(report["annual_loser_rule_verified"])
        self.assertFalse(report["live_fmt025_runtime_changed"])

    def assert_bad(self, path: str, mutate, expected_fragment: str):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            shutil.copytree(DATA, root)
            change_csv(root / path, mutate)
            report = audit_2026_hiroshima_stage13e3g28(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any(expected_fragment in e for e in report["errors"]), report["errors"])

    def test_official_match_number_unverified_must_stay_blank(self):
        self.assert_bad(NUMBER_QUEUE_FILE,
                        lambda r: r[0].update(official_match_number="10"),
                        "official_match_number")
        self.assert_bad(NUMBER_QUEUE_FILE,
                        lambda r: r[1].update(official_number_verified="yes"),
                        "official_number_verified")

    def test_wrong_official_pairing_and_school_rejected(self):
        self.assert_bad(NUMBER_QUEUE_FILE,
                        lambda r: r[0].update(secondary_pairing_team1="架空校"),
                        "secondary_pairing_team1")
        self.assert_bad(NUMBER_QUEUE_FILE,
                        lambda r: r[0].update(official_pairing_verified="yes"),
                        "official_pairing_verified")

    def test_falsified_pdf_receipt_or_year_not_accepted(self):
        self.assert_bad(NUMBER_QUEUE_FILE,
                        lambda r: r[0].update(official_document_displayed_as="downloaded_pdf_sha256_verified"),
                        "official_document_displayed_as")
        self.assert_bad(NUMBER_QUEUE_FILE,
                        lambda r: r[0].update(document_year="2025"),
                        "document_year")
        self.assert_bad(ARROW_QUEUE_FILE,
                        lambda r: r[0].update(official_document_url="https://example.com/fake.pdf"),
                        "official_document_url")

    def test_undocumented_loser_to_repechage_transfer_rejected(self):
        self.assert_bad(ARROW_QUEUE_FILE,
                        lambda r: next(x for x in r
                                       if x["transition_id"] == "HPTR20260073").update(
                            official_arrow_verified="yes"
                        ), "official_arrow_verified")

    def test_wrong_priority_or_outcome_rejected(self):
        self.assert_bad(ARROW_QUEUE_FILE,
                        lambda r: next(x for x in r
                                       if x["transition_id"] == "HPTR20260073").update(
                            review_priority="other_observed_continuation"
                        ), "review_priority")
        self.assert_bad(ARROW_QUEUE_FILE,
                        lambda r: r[0].update(observed_outcome="loser"), "observed_outcome")

    def test_remove_duplicate_or_redirect_is_rejected(self):
        self.assert_bad(NUMBER_QUEUE_FILE, lambda r: r.pop(), "all 25 games")
        self.assert_bad(ARROW_QUEUE_FILE, lambda r: r.append(dict(r[0])), "all 25 games")
        self.assert_bad(ARROW_QUEUE_FILE,
                        lambda r: r[0].update(to_match_id="HT20260072"), "to_match_id")

    def test_live_runtime_cannot_be_unlocked_by_visual_preview(self):
        self.assert_bad(NUMBER_QUEUE_FILE,
                        lambda r: r[0].update(live_runtime_enabled="yes"), "live_runtime_enabled")
        self.assert_bad(ARROW_QUEUE_FILE,
                        lambda r: r[0].update(live_runtime_enabled="yes"), "live_runtime_enabled")

    def history(self):
        return load_csv(DATA / NODES_FILE), load_csv(DATA / EDGES_FILE)

    def test_two_match_one_winner_arrow_candidate_only(self):
        nodes, edges = self.history()
        candidates = (
            DrawMatchProposal("HT20260175", "10", "広島井口", "大竹", "A / initial slot"),
            DrawMatchProposal("HT20260173", "11", "広島商", "広島井口", "A / second-round"),
        )
        arrows = (
            DrawArrowProposal("HPTR20260072", "10", "11",
                              "広島井口", "winner", "A / winner path"),
        )
        result = preflight_proposed_2026_draw(
            historical_nodes=nodes, historical_edges=edges,
            matches=candidates, arrows=arrows,
        )
        self.assertEqual((result.candidate_match_count, result.candidate_arrow_count), (2, 1))
        self.assertTrue(result.candidate_only)
        self.assertFalse(result.independently_official_verified)
        self.assertFalse(result.runtime_enabled)

    def test_primary_loser_transfer_candidate_shape_not_official_approval(self):
        nodes, edges = self.history()
        proposals = (
            DrawMatchProposal("HT20260173", "11", "広島商", "広島井口", "zone A first"),
            DrawMatchProposal("HT20260172", "12", "広島井口", "大竹", "zone A second"),
        )
        arrows = (DrawArrowProposal("HPTR20260073", "11", "12",
                                    "広島井口", "loser", "A loss/second chance"),)
        result = preflight_proposed_2026_draw(
            historical_nodes=nodes, historical_edges=edges,
            matches=proposals, arrows=arrows,
        )
        self.assertEqual(result.candidate_arrow_count, 1)
        self.assertFalse(result.independently_official_verified)

    def test_duplicate_number_or_invalid_manual_candidate_rejected(self):
        nodes, edges = self.history()
        base = DrawMatchProposal("HT20260175", "1", "広島井口", "大竹", "A panel")
        rejects = (
            (base, base),
            (base, DrawMatchProposal("HT20260173", "1", "広島商", "広島井口", "A panel")),
            (DrawMatchProposal("HT20260175", "0", "広島井口", "大竹", "A"),),
            (DrawMatchProposal("HT20260175", "01", "広島井口", "大竹", "A"),),
            (DrawMatchProposal("HT20260175", "10", "広島井口", "修道", "A"),),
            (DrawMatchProposal("HT20260175", "10", "広島井口", "大竹", ""),),
            (DrawMatchProposal("HT20260175", "10", "広島井口", "大竹",
                               "A", "https://example.org/2025"),),
        )
        for row in rejects:
            with self.subTest(row=row):
                with self.assertRaises(DrawReviewError):
                    preflight_proposed_2026_draw(
                        historical_nodes=nodes, historical_edges=edges,
                        matches=row, arrows=(),
                    )

    def test_unmatched_or_unconfirmed_arrow_cannot_pass_preflight(self):
        nodes, edges = self.history()
        matches = (
            DrawMatchProposal("HT20260175", "10", "広島井口", "大竹", "A initial"),
            DrawMatchProposal("HT20260173", "11", "広島商", "広島井口", "A second"),
        )
        examples = (
            DrawArrowProposal("HPTR20260072", "9", "11", "広島井口", "winner", "A"),
            DrawArrowProposal("HPTR20260072", "10", "11", "広島井口", "loser", "A"),
            DrawArrowProposal("HPTR20260072", "10", "11", "広島商", "winner", "A"),
            DrawArrowProposal("HPTR20260072", "10", "11", "広島井口", "winner", ""),
            DrawArrowProposal("HPTR20260073", "10", "11", "広島井口", "loser", "A"),
            DrawArrowProposal("INVALID", "10", "11", "広島井口", "winner", "A"),
        )
        for proposal in examples:
            with self.subTest(proposal=proposal):
                with self.assertRaises(DrawReviewError):
                    preflight_proposed_2026_draw(
                        historical_nodes=nodes, historical_edges=edges,
                        matches=matches, arrows=(proposal,),
                    )

    def test_duplicate_arrow_proposals_rejected(self):
        nodes, edges = self.history()
        matches = (
            DrawMatchProposal("HT20260175", "10", "広島井口", "大竹", "A initial"),
            DrawMatchProposal("HT20260173", "11", "広島商", "広島井口", "A second"),
        )
        arrow = DrawArrowProposal("HPTR20260072", "10", "11",
                                  "広島井口", "winner", "A")
        with self.assertRaises(DrawReviewError):
            preflight_proposed_2026_draw(
                historical_nodes=nodes, historical_edges=edges,
                matches=matches, arrows=(arrow, arrow),
            )


if __name__ == "__main__":
    unittest.main()
