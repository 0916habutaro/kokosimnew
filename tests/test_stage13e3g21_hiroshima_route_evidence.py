from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g21 import (
    LOSS_TRACE_FILE,ROUTE_EVIDENCE_FILE,GROUP_REVIEW_FILE,
    audit_2026_hiroshima_stage13e3g21,
)
from phase2_engine.hiroshima_stage13e3g17 import GROUP_CONTRACT_FILE
from phase2_engine.hiroshima_stage13e3g18 import TRANSITION_FILE,SUMMARY_FILE
from phase2_engine.hiroshima_stage13e3g19 import GATE_OBSERVATIONS_FILE
from phase2_engine.hiroshima_stage13e3g20 import ROUTE_REQUIREMENTS_FILE,ZONE_CONTRACT_FILE
from phase2_engine.hiroshima_route_evidence_review import (
    ProposedRouteEvidence,RouteProofError,review_proposed_annual_route_evidence,
)

DATA=Path(__file__).resolve().parents[1]/"data"
INPUTS=(LOSS_TRACE_FILE,ROUTE_EVIDENCE_FILE,GROUP_REVIEW_FILE,
        TRANSITION_FILE,SUMMARY_FILE,GATE_OBSERVATIONS_FILE,
        ROUTE_REQUIREMENTS_FILE,ZONE_CONTRACT_FILE,GROUP_CONTRACT_FILE)


def copy_files(root):
    for rel in INPUTS:
        p=root/rel
        p.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(DATA/rel,p)


def edit_file(root,rel,edit):
    file=root/rel
    with file.open(encoding="utf-8-sig",newline="") as fh:
        reader=csv.DictReader(fh)
        fieldnames,rows=reader.fieldnames,list(reader)
    edit(rows)
    with file.open("w",encoding="utf-8",newline="") as fh:
        writer=csv.DictWriter(fh,fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G21HiroshimaObservedLoserAudit(unittest.TestCase):
    def test_121_real_forwardings_and_103_block_labels(self):
        r=audit_2026_hiroshima_stage13e3g21(DATA)
        self.assertTrue(r["ok"],r["errors"])
        self.assertEqual(287,r["secondary_dated_fixture_progressions"])
        self.assertEqual(121,r["primary_loser_observed_forwardings"])
        self.assertEqual(103,r["both_block_labels_available"])
        self.assertEqual(103,r["same_display_block_label"])
        self.assertEqual(30,r["historical_publisher_dest_annotated_edges"])

    def test_87_routes_and_8_seasonal_review_rows(self):
        r=audit_2026_hiroshima_stage13e3g21(DATA)
        self.assertEqual(87,r["route_evidence_checklists"])
        self.assertEqual(8,r["seasonal_release_reviews"])
        self.assertEqual({
            "PRIMARY":38,"REPECHAGE_ZONE":35,"REPECHAGE_CROSS_ZONE_GATE":14,
        },r["route_role_counts"])

    def test_quota_and_exemption_conservation(self):
        r=audit_2026_hiroshima_stage13e3g21(DATA)
        self.assertEqual({
            "qualifier_award_quota":63,"primary_award_quota":38,
            "nonprimary_award_quota":25,"direct_main_exempt_slots":1,
            "cross_decider_events":14,
        },r["slot_conservation"])

    def test_no_draw_selector_or_ranking_promoted(self):
        r=audit_2026_hiroshima_stage13e3g21(DATA)
        self.assertEqual(0,r["verified_official_loser_forwarding_rules"])
        self.assertEqual(0,r["verified_official_runnerup_to_cross_gate_rules"])
        self.assertEqual(0,r["verified_official_retry_rules"])
        self.assertEqual(0,r["official_pdf_bodies_inspected"])
        self.assertFalse(r["fmt025_live_route_release_allowed"])
        self.assertFalse(r["ranking_only_game_release_allowed"])

    def test_child_route_requirements_cover_three_role_families(self):
        with (DATA/ROUTE_EVIDENCE_FILE).open(encoding="utf-8",newline="") as fh:
            rows=list(csv.DictReader(fh))
        unique={r["role"]:r["required_annual_evidence_items"].split(";")
                for r in rows}
        self.assertEqual(2,len(unique["PRIMARY"]))
        self.assertEqual(2,len(unique["REPECHAGE_ZONE"]))
        self.assertEqual(3,len(unique["REPECHAGE_CROSS_ZONE_GATE"]))
        self.assertTrue(all(x["live_fmt025_runtime_allowed"]=="no" for x in rows))

    def test_primary_loser_traces_are_strictly_season_local(self):
        with (DATA/LOSS_TRACE_FILE).open(encoding="utf-8",newline="") as fh:
            rows=list(csv.DictReader(fh))
        self.assertEqual(121,len(rows))
        self.assertTrue(all(r["primary_loss_date"]<r["next_repechage_date"] for r in rows))
        self.assertTrue(all(r["annual_loser_selector_verified"]=="no" for r in rows))

    def test_mutated_loser_match_id_caught(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_files(root)
            edit_file(root,LOSS_TRACE_FILE,lambda x:x[0].update(next_repechage_match_id="HX999"))
            r=audit_2026_hiroshima_stage13e3g21(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("historical row" in e for e in r["errors"]))

    def test_missing_loser_history_caught(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_files(root)
            edit_file(root,LOSS_TRACE_FILE,lambda x:x.pop())
            r=audit_2026_hiroshima_stage13e3g21(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("121" in e for e in r["errors"]))

    def test_unverified_rule_false_promotion_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_files(root)
            edit_file(root,LOSS_TRACE_FILE,lambda x:x[0].update(
                annual_loser_selector_verified="yes"))
            r=audit_2026_hiroshima_stage13e3g21(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("annual_loser_selector_verified" in e for e in r["errors"]))

    def test_publisher_title_cannot_unlock_cross_zone_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_files(root)
            edit_file(root,ROUTE_EVIDENCE_FILE,lambda x:next(
                row for row in x if row["role"]=="REPECHAGE_CROSS_ZONE_GATE"
            ).update(secondary_candidate_transfer_verified="yes"))
            r=audit_2026_hiroshima_stage13e3g21(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("annual route evidence mismatch" in e for e in r["errors"]))

    def test_duplicate_or_missing_evidence_route_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_files(root)
            edit_file(root,ROUTE_EVIDENCE_FILE,lambda x:x[0].update(
                route_id=x[1]["route_id"]))
            r=audit_2026_hiroshima_stage13e3g21(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("87" in e for e in r["errors"]))

    def test_group_release_false_claim_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_files(root)
            edit_file(root,GROUP_REVIEW_FILE,lambda x:x[0].update(
                exact_fmt025_route_release_approved="yes"))
            r=audit_2026_hiroshima_stage13e3g21(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("season district route release mismatch" in e for e in r["errors"]))

    def test_group_observed_loser_count_forgery_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_files(root)
            edit_file(root,GROUP_REVIEW_FILE,lambda x:x[2].update(
                primary_loser_to_repechage_observed="99"))
            r=audit_2026_hiroshima_stage13e3g21(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("season district route release mismatch" in e for e in r["errors"]))


class Stage13E3G21ManualEvidenceReviewTests(unittest.TestCase):
    def _review(self,proofs=(),required=("primary_loser_round_to_secondary_selector",
                                        "secondary_zone_bracket_pairings")):
        return review_proposed_annual_route_evidence(
            route_id="example-zone",required_keys=required,
            supplied_evidence=proofs,season_year="2026",
        )

    def _ref(self,key,**overrides):
        params=dict(evidence_key=key,source_kind="federation_bracket_draw",
                    document_ref="source-001",pinpoint_location="page 2: bracket node X",
                    season_year="2026",supplied_document_body_reviewed=True)
        params.update(overrides)
        return ProposedRouteEvidence(**params)

    def test_empty_2026_evidence_is_blocked(self):
        r=self._review()
        self.assertEqual(2,len(r.missing_evidence_keys))
        self.assertFalse(r.structurally_complete_for_manual_review)
        self.assertFalse(r.actual_game_runtime_enabled)

    def test_secondary_result_pages_cannot_satisfy_official_draw_requirement(self):
        key="primary_loser_round_to_secondary_selector"
        x=self._ref(key,source_kind="secondary_dated_results")
        r=self._review((x,))
        self.assertEqual((key,),r.unsupported_evidence_keys)
        self.assertIn("secondary_zone_bracket_pairings",r.missing_evidence_keys)

    def test_publisher_child_event_name_is_not_official_loser_rule(self):
        x=self._ref("primary_loser_round_to_secondary_selector",
                    source_kind="publisher_event_title")
        r=self._review((x,))
        self.assertFalse(r.structurally_complete_for_manual_review)

    def test_pdf_link_without_readable_body_is_rejected(self):
        x=self._ref("primary_loser_round_to_secondary_selector",
                    supplied_document_body_reviewed=False)
        r=self._review((x,))
        self.assertEqual((x.evidence_key,),r.unsupported_evidence_keys)

    def test_year_mismatch_does_not_confirm_2026_rules(self):
        x=self._ref("primary_loser_round_to_secondary_selector",season_year="2025")
        r=self._review((x,))
        self.assertFalse(r.structurally_complete_for_manual_review)

    def test_year_independent_regulation_is_allowed_as_metadata_only(self):
        k="primary_loser_round_to_secondary_selector"
        x=self._ref(k,source_kind="federation_published_regulations",
                    season_year="year_independent")
        r=self._review((x,),required=(k,))
        self.assertTrue(r.structurally_complete_for_manual_review)
        self.assertFalse(r.source_content_independently_verified)
        self.assertFalse(r.actual_game_runtime_enabled)

    def test_complete_hypothetical_packet_never_unlocks_live_engine(self):
        keys=("primary_loser_round_to_secondary_selector",
              "secondary_zone_bracket_pairings")
        r=self._review(tuple(self._ref(k) for k in keys))
        self.assertTrue(r.structurally_complete_for_manual_review)
        self.assertEqual((),r.missing_evidence_keys)
        self.assertFalse(r.source_content_independently_verified)
        self.assertFalse(r.actual_game_runtime_enabled)
        self.assertFalse(r.optional_ranking_enabled)

    def test_blank_document_or_pinpoint_is_not_proof(self):
        key="primary_loser_round_to_secondary_selector"
        for kw in (dict(document_ref=""),dict(pinpoint_location="")):
            with self.subTest(kw=kw):
                r=self._review((self._ref(key,**kw),),required=(key,))
                self.assertFalse(r.structurally_complete_for_manual_review)

    def test_duplicate_submission_is_rejected(self):
        x=self._ref("annual_entrant_zone_assignment")
        with self.assertRaisesRegex(RouteProofError,"duplicate"):
            self._review((x,x),required=(x.evidence_key,))

    def test_unknown_or_unsolicited_key_is_rejected(self):
        with self.assertRaises(RouteProofError):
            self._review((self._ref("unused"),))
        with self.assertRaises(RouteProofError):
            self._review((self._ref("cross_zone_bracket_pairings"),))

    def test_duplicate_or_invalid_requirement_is_rejected(self):
        with self.assertRaises(RouteProofError):
            self._review(required=("annual_entrant_zone_assignment",)*2)
        with self.assertRaises(RouteProofError):
            self._review(required=("unknown",))
        with self.assertRaises(RouteProofError):
            self._review(required=())

    def test_2026_document_does_not_silently_verify_2027_season(self):
        x=self._ref("official_primary_bracket_pairings")
        r=review_proposed_annual_route_evidence(
            route_id="other-year",required_keys=(x.evidence_key,),
            supplied_evidence=(x,),season_year="2027",
        )
        self.assertFalse(r.structurally_complete_for_manual_review)


if __name__=="__main__":
    unittest.main()
