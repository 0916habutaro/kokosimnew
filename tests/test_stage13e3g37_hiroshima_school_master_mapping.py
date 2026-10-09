from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g37_school_master import (
    AMBIGUOUS, EXACT, REVIEWED, UNRESOLVED, WRONG_MASTER,
    SCHOOL_LEDGER_FILE, SchoolMasterPreviewError,
    audit_2026_hiroshima_stage13e3g37,
    load_2026_hiroshima_west_school_links,
    observed_autumn_west_names, resolve_2026_hiroshima_school_links,
)
from phase2_engine.hiroshima_stage13e3g35_preview_gui_model import (
    FICTIONAL, OBSERVED_2026_WEST, HiroshimaPreviewGuiModel,
    PreviewGuiModelError,
)
from phase2_engine.hiroshima_match_level_2026 import _read
from phase2_engine.hiroshima_stage13e3g25 import NODES_FILE

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"


def school(sid,name, pref="34", official=None):
    return dict(school_id=sid, prefecture_code=pref,
                official_name=official or name+"高等学校", federation_name=name)


def program(sid, pid, membership="active", year="2026"):
    return dict(school_id=sid, program_id=pid, reference_year=year,
                discipline="hardball", membership_status=membership)


def review(name,sid=""):
    return dict(observed_name=name, prefecture_code="34",
                reference_year="2026", reviewed_alias_school_id=sid,
                reviewed_alias_source=("post_qualification_rank_school_aliases.csv" if sid else ""),
                master_identity_status=(
                    "previously_reviewed_alias_reference" if sid
                    else "require_exact_federation_name_or_unresolved"))


class Stage13E3G37SchoolMasterContractTests(unittest.TestCase):
    def test_exact_match_and_reviewed_alias_requires_2026_active_program(self):
        schools=[school("SCH000001","実名"),school("SCH001774","山陽正式",official="山陽高等学校")]
        programs=[program("SCH000001","PRG000001"),program("SCH001774","PRG001774")]
        aliases=[dict(prefecture_code="34", observed_name="山陽",
                      school_id="SCH001774", master_official_name="山陽高等学校")]
        result=resolve_2026_hiroshima_school_links(
            observations=("実名","山陽"),school_master=schools,
            hardball_programs=programs,reviewed_aliases=aliases,
            evidence_rows=[review("実名"),review("山陽","SCH001774")])
        self.assertEqual(result["実名"].resolution_status,EXACT)
        self.assertEqual(result["実名"].school_id,"SCH000001")
        self.assertEqual(result["山陽"].resolution_status,REVIEWED)
        self.assertEqual(result["山陽"].program_id,"PRG001774")
        self.assertTrue(result["山陽"].authorized_for_read_only_detail)
        self.assertFalse(result["山陽"].official_2026_draw_verified)

    def test_wrong_prefecture_and_inactive_or_wrong_year_do_not_link(self):
        for sc,prg in (
            (school("SCH001","対戦校",pref="35"),program("SCH001","P1")),
            (school("SCH001","対戦校"),program("SCH001","P1",membership="inactive")),
            (school("SCH001","対戦校"),program("SCH001","P1",year="2025")),
        ):
            with self.subTest(sc=sc,prg=prg):
                result=resolve_2026_hiroshima_school_links(
                    observations=("対戦校",),school_master=[sc],
                    hardball_programs=[prg],reviewed_aliases=[],
                    evidence_rows=[review("対戦校")])
                self.assertEqual(result["対戦校"].school_id,"")
                self.assertEqual(result["対戦校"].resolution_status,UNRESOLVED)
                self.assertFalse(result["対戦校"].authorized_for_read_only_detail)

    def test_two_exact_candidates_with_same_federation_name_are_ambiguous(self):
        schools=[school("S1","同名"),school("S2","同名")]
        result=resolve_2026_hiroshima_school_links(
            observations=("同名",),school_master=schools,
            hardball_programs=[program("S1","P1"),program("S2","P2")],
            reviewed_aliases=[],evidence_rows=[review("同名")])
        self.assertEqual(result["同名"].resolution_status,AMBIGUOUS)
        self.assertEqual(result["同名"].school_id,"")

    def test_unsupported_fuzzy_short_name_stays_unresolved(self):
        result=resolve_2026_hiroshima_school_links(
            observations=("工大",),school_master=[school("SCH999","広島工大")],
            hardball_programs=[program("SCH999","P999")],
            reviewed_aliases=[],evidence_rows=[review("工大")])
        self.assertEqual(result["工大"].school_id,"")
        self.assertEqual(result["工大"].resolution_status,UNRESOLVED)

    def test_reviewed_alias_requires_exact_prior_evidence_and_official_name(self):
        school_row=school("SCH001774","山陽正式",official="山陽高等学校")
        alias=dict(prefecture_code="34",observed_name="山陽",
                   school_id="SCH001774",master_official_name="山陽高等学校")
        for wrong_alias in (
            [],
            [{**alias,"school_id":"SCH000123"}],
            [{**alias,"master_official_name":"別校"}],
        ):
            result=resolve_2026_hiroshima_school_links(
                observations=("山陽",),school_master=[school_row],
                hardball_programs=[program("SCH001774","P1")],
                reviewed_aliases=wrong_alias,evidence_rows=[review("山陽","SCH001774")])
            self.assertEqual(result["山陽"].resolution_status,WRONG_MASTER)
            self.assertEqual(result["山陽"].school_id,"")

    def test_prior_alias_cannot_be_used_silently_without_ledger(self):
        ali=dict(prefecture_code="34",observed_name="別称",
                 school_id="SCH1",master_official_name="正式高等学校")
        result=resolve_2026_hiroshima_school_links(
            observations=("別称",),school_master=[school("SCH1","別名",official="正式高等学校")],
            hardball_programs=[program("SCH1","P1")],
            reviewed_aliases=[ali],evidence_rows=[review("別称")])
        self.assertEqual(result["別称"].resolution_status,WRONG_MASTER)
        self.assertEqual(result["別称"].school_id,"")

    def test_two_observed_names_cannot_share_one_master_id(self):
        school_row=school("SCH1","直記",official="正式高等学校")
        alias=dict(prefecture_code="34",observed_name="別称",
                   school_id="SCH1",master_official_name="正式高等学校")
        result=resolve_2026_hiroshima_school_links(
            observations=("直記","別称"),school_master=[school_row],
            hardball_programs=[program("SCH1","P1")],
            reviewed_aliases=[alias],evidence_rows=[review("直記"),review("別称","SCH1")])
        self.assertEqual(result["直記"].resolution_status,AMBIGUOUS)
        self.assertEqual(result["別称"].resolution_status,AMBIGUOUS)
        self.assertEqual(result["直記"].school_id,"")
        self.assertEqual(result["別称"].school_id,"")

    def test_ledger_duplicate_missing_and_cross_prefecture_rejected(self):
        inputs=dict(observations=("A","B"),school_master=[school("S1","A"),school("S2","B")],
                    hardball_programs=[program("S1","P1"),program("S2","P2")],
                    reviewed_aliases=[])
        for evidence in (
            [review("A"),review("A")],
            [review("A")],
            [review("A"),{**review("B"),"prefecture_code":"35"}],
            [review("A"),{**review("B"),"reference_year":"2025"}],
            [review("A"),{**review("B"),"reviewed_alias_school_id":"S2"}],
        ):
            with self.subTest(evidence=evidence):
                with self.assertRaises(SchoolMasterPreviewError):
                    resolve_2026_hiroshima_school_links(
                        **inputs,evidence_rows=evidence)

    def test_duplicate_school_id_or_duplicate_2026_hardball_program_rejected(self):
        with self.assertRaises(SchoolMasterPreviewError):
            resolve_2026_hiroshima_school_links(
                observations=("A",),school_master=[school("S1","A"),school("S1","B")],
                hardball_programs=[program("S1","P1")],
                reviewed_aliases=[],evidence_rows=[review("A")])
        with self.assertRaises(SchoolMasterPreviewError):
            resolve_2026_hiroshima_school_links(
                observations=("A",),school_master=[school("S1","A")],
                hardball_programs=[program("S1","P1"),program("S1","P2")],
                reviewed_aliases=[],evidence_rows=[review("A")])

    def test_2026_observed_names_are_exactly_18_from_25_results(self):
        names=observed_autumn_west_names(_read(DATA,NODES_FILE))
        self.assertEqual(len(names),18)
        self.assertIn("山陽",names)
        self.assertIn("広島城北",names)
        self.assertIn("広島工大",names)

    def test_real_master_two_previously_approved_hiroshima_aliases(self):
        links=load_2026_hiroshima_west_school_links(DATA)
        self.assertEqual(len(links),18)
        self.assertEqual(links["山陽"].school_id,"SCH001774")
        self.assertEqual(links["広島城北"].school_id,"SCH001777")
        self.assertTrue(links["山陽"].authorized_for_read_only_detail)
        self.assertTrue(links["広島城北"].authorized_for_read_only_detail)
        self.assertTrue(all(not l.live_fmt025_runtime_enabled for l in links.values()))
        self.assertEqual(
            len({x.school_id for x in links.values() if x.school_id}),
            sum(bool(x.school_id) for x in links.values()))

    def test_real_master_integrated_audit_reports_unresolved_conservatively(self):
        report=audit_2026_hiroshima_stage13e3g37(DATA)
        self.assertTrue(report["ok"],report["errors"])
        self.assertEqual(report["observed_2026_west_schools"],18)
        self.assertGreaterEqual(report["resolved_unique_school_ids"],2)
        self.assertEqual(report["verified_prior_alias_ids"],
                         {"山陽":"SCH001774","広島城北":"SCH001777"})
        self.assertEqual(
            report["resolved_unique_school_ids"]+len(report["unresolved_or_ambiguous_school_names"]),18)
        self.assertFalse(report["official_individual_draw_verified"])
        self.assertFalse(report["live_fmt025_runtime_enabled"])

    def test_preview_fictional_has_no_formal_school_detail(self):
        model=HiroshimaPreviewGuiModel(DATA,FICTIONAL)
        self.assertTrue(all(row[6]=="架空（対象外）" for row in model.render().school_rows))
        with self.assertRaises(PreviewGuiModelError):
            model.get_verified_school_master_detail("A")

    def test_preview_real_master_detail_only_after_observed_school_visible(self):
        model=HiroshimaPreviewGuiModel(DATA,OBSERVED_2026_WEST)
        with self.assertRaises(PreviewGuiModelError):
            model.get_verified_school_master_detail("NOT_A_REAL_SCHOOL")
        for _ in range(25):
            model.show_next_preapproved_result()
        detail=model.get_verified_school_master_detail("山陽")
        self.assertEqual(detail.school_id,"SCH001774")
        self.assertEqual(detail.prefecture_code,"34")
        self.assertTrue(detail.authorized_for_read_only_detail)
        self.assertFalse(detail.official_2026_draw_verified)
        self.assertIn("SCH001774",[row[6] for row in model.render().school_rows])
        ids=model.search_visible_school_ids(detail.official_name)
        self.assertIn("山陽",ids)

    def test_review_ledger_tamper_cannot_promote_new_unreviewed_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"data"
            shutil.copytree(DATA,root)
            path=root/SCHOOL_LEDGER_FILE
            rows=_read(root,SCHOOL_LEDGER_FILE)
            self.assertEqual(len(rows),18)
            for item in rows:
                if item["observed_name"]=="広島工大":
                    item["reviewed_alias_school_id"]="SCH999999"
                    item["reviewed_alias_source"]="post_qualification_rank_school_aliases.csv"
                    item["master_identity_status"]="previously_reviewed_alias_reference"
            with path.open("w",encoding="utf-8",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            report=audit_2026_hiroshima_stage13e3g37(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("unexpected, missing" in e for e in report["errors"]))


if __name__=="__main__":
    unittest.main()
