"""Stage39: evidence-constrained matching of final 11 observed Hiroshima schools."""
from __future__ import annotations

import csv
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_match_level_2026 import _read
from phase2_engine.hiroshima_stage13e3g37_school_master import (
    SchoolMasterPreviewLink, SchoolMasterPreviewError, UNRESOLVED, EXACT,
)
from phase2_engine.hiroshima_stage13e3g39_school_master import (
    REVIEW_FILE, EXPECTED, OUTCOME,
    audit_2026_hiroshima_stage13e3g39,
    load_2026_hiroshima_west_school_links_stage39,
    resolve_stage39_reviewed_master_links,
)
from phase2_engine.hiroshima_stage13e3g35_preview_gui_model import (
    OBSERVED_2026_WEST, FICTIONAL, HiroshimaPreviewGuiModel,
    PreviewGuiModelError,
)

DATA=Path(__file__).resolve().parents[1]/"data"


def unresolved(name):
    return SchoolMasterPreviewLink(
        observed_name=name,resolution_status=UNRESOLVED,school_id="",
        official_name="",federation_name="",program_id="",
        prefecture_code="34",source="",authorized_for_read_only_detail=False,
    )


def synthetic():
    names=list(EXPECTED)+[f"前段{i}" for i in range(7)]
    links={n:unresolved(n) for n in names}
    school_master=[]
    programs=[]
    for i,(name,(legal,founder,url)) in enumerate(EXPECTED.items(),1):
        sid=f"SCH{i:06}"
        school_master.append({
            "school_id":sid,"prefecture_code":"34",
            "official_name":legal,"federation_name":"other-"+str(i),
        })
        programs.append({
            "program_id":f"PRG{i:06}","school_id":sid,
            "reference_year":"2026","discipline":"hardball",
            "membership_status":"active",
        })
    return dict(
        prior_links=links,evidence_rows=_read(DATA,REVIEW_FILE),
        school_master=school_master,hardball_programs=programs,
    )


class Stage13E3G39AllSchoolIdentityTests(unittest.TestCase):
    def test_all_eleven_synthetic_distinct_exact_official_names_resolve(self):
        report=resolve_stage39_reviewed_master_links(**synthetic())
        self.assertEqual(report.evidence_reviewed,11)
        self.assertEqual(set(report.newly_matched),set(EXPECTED))
        self.assertEqual(report.candidates_unmatched,())
        self.assertEqual(len(report.links),18)
        self.assertTrue(all(report.links[name].resolution_status==OUTCOME
                            for name in EXPECTED))
        self.assertTrue(all(not row.official_2026_draw_verified
                            and not row.live_fmt025_runtime_enabled
                            for row in report.links.values()))

    def test_unavailable_master_name_stays_explicitly_unresolved(self):
        s=synthetic()
        s["school_master"]=s["school_master"][1:]
        result=resolve_stage39_reviewed_master_links(**s)
        self.assertIn("五日市",result.candidates_unmatched)
        self.assertFalse(result.links["五日市"].authorized_for_read_only_detail)
        self.assertEqual(result.links["五日市"].school_id,"")

    def test_cross_prefecture_and_wrong_year_or_discipline_rejected(self):
        for field,value in (
            ("prefecture_code","35"),
            ("reference_year","2025"),
            ("discipline","softball"),
            ("membership_status","inactive"),
        ):
            with self.subTest(field=field):
                s=synthetic()
                if field=="prefecture_code":
                    s["school_master"][0][field]=value
                else:
                    s["hardball_programs"][0][field]=value
                result=resolve_stage39_reviewed_master_links(**s)
                self.assertIn("五日市",result.candidates_unmatched)
                self.assertEqual(result.links["五日市"].school_id,"")

    def test_homonymous_prefecture_and_city_school_never_merge(self):
        s=synthetic()
        s["school_master"].append({
            "school_id":"SCH009999","prefecture_code":"34",
            "official_name":"広島県立基町高等学校","federation_name":"基町",
        })
        s["hardball_programs"].append({
            "school_id":"SCH009999","program_id":"PRG009999",
            "reference_year":"2026","discipline":"hardball","membership_status":"active",
        })
        result=resolve_stage39_reviewed_master_links(**s)
        self.assertEqual(result.links["基町"].official_name,"広島市立基町高等学校")
        self.assertNotEqual(result.links["基町"].school_id,"SCH009999")

    def test_duplicate_official_school_or_program_fails_closed(self):
        for kind in ("duplicate_school_name","duplicate_program"):
            s=synthetic()
            if kind=="duplicate_school_name":
                s["school_master"].append({
                    **s["school_master"][0],"school_id":"SCH009999",
                })
            else:
                s["hardball_programs"].append({
                    **s["hardball_programs"][0],"program_id":"PRG009999",
                })
            report=resolve_stage39_reviewed_master_links(**s)
            self.assertIn("五日市",report.candidates_unmatched)
            self.assertEqual(report.links["五日市"].school_id,"")

    def test_duplicate_school_id_in_master_is_error(self):
        s=synthetic()
        s["school_master"].append({
            **s["school_master"][0],"official_name":"別の学校",
        })
        with self.assertRaises(SchoolMasterPreviewError):
            resolve_stage39_reviewed_master_links(**s)

    def test_already_verified_prior_id_is_immutable(self):
        s=synthetic()
        school=s["school_master"][0]
        prior=SchoolMasterPreviewLink(
            observed_name="五日市",resolution_status=EXACT,
            school_id=school["school_id"],official_name=school["official_name"],
            federation_name="五日市",program_id="PRG000001",
            prefecture_code="34",source="master/schools.csv",
            authorized_for_read_only_detail=True,
        )
        s["prior_links"]["五日市"]=prior
        report=resolve_stage39_reviewed_master_links(**s)
        self.assertEqual(report.links["五日市"],prior)
        self.assertNotIn("五日市",report.newly_matched)
        s["prior_links"]["五日市"]=SchoolMasterPreviewLink(
            **{**prior.__dict__,"official_name":"偽の旧校名"}
        )
        with self.assertRaises(SchoolMasterPreviewError):
            resolve_stage39_reviewed_master_links(**s)

    def test_prior_ids_cannot_be_reused_as_new_mappings(self):
        s=synthetic()
        other=SchoolMasterPreviewLink(
            observed_name="前段0",resolution_status=EXACT,
            school_id="SCH000001",official_name="前段正式",
            federation_name="前段0",program_id="PRG000001",
            prefecture_code="34",source="previous-review",
            authorized_for_read_only_detail=True,
        )
        s["prior_links"]["前段0"]=other
        result=resolve_stage39_reviewed_master_links(**s)
        self.assertIn("五日市",result.candidates_unmatched)
        self.assertEqual(result.links["五日市"].school_id,"")

    def test_review_source_year_legal_name_founder_and_scope_are_immutable(self):
        s=synthetic()
        for field,val in (
            ("reference_year","2025"),("prefecture_code","35"),
            ("founder_category","private"),
            ("publication_alias_url","https://unverified.example.com"),
            ("school_authority_url","https://unverified.example.com"),
            ("proposed_master_official_name","広島市立五日市高等学校"),
            ("decision","official_bracket_approved"),
            ("proof_scope","verified_2026_draw"),
        ):
            with self.subTest(field=field):
                bad=copy.deepcopy(s)
                bad["evidence_rows"][0][field]=val
                with self.assertRaises(SchoolMasterPreviewError):
                    resolve_stage39_reviewed_master_links(**bad)

    def test_unknown_or_duplicate_review_row_rejected(self):
        s=synthetic()
        for rows in (
            s["evidence_rows"][:-1],
            s["evidence_rows"]+[s["evidence_rows"][0]],
            [{**s["evidence_rows"][0],"observed_name":"未知の学校"}]+s["evidence_rows"][1:],
        ):
            with self.subTest(count=len(rows)):
                with self.assertRaises(SchoolMasterPreviewError):
                    resolve_stage39_reviewed_master_links(**{
                        **s,"evidence_rows":rows,
                    })

    def test_real_data_eighteen_master_ids_remain_unique(self):
        report=load_2026_hiroshima_west_school_links_stage39(DATA)
        self.assertEqual(len(report.links),18)
        self.assertEqual(report.evidence_reviewed,11)
        self.assertEqual(len({
            item.school_id for item in report.links.values() if item.school_id
        }),sum(bool(item.school_id) for item in report.links.values()))
        self.assertEqual(report.links["山陽"].school_id,"SCH001774")
        self.assertEqual(report.links["広島城北"].school_id,"SCH001777")
        self.assertTrue(all(not x.official_2026_draw_verified for x in report.links.values()))

    def test_integrated_real_audit_counts_and_unresolved_explicit(self):
        r=audit_2026_hiroshima_stage13e3g39(DATA)
        self.assertTrue(r["ok"],r["errors"])
        self.assertEqual(r["2026_west_observed_names"],18)
        self.assertEqual(r["previously_verified_school_ids"],7)
        self.assertEqual(r["reviewed_11_name_candidates"],11)
        self.assertEqual(r["total_uniquely_verified_master_ids"]
                         +len(r["remaining_unverified_names"]),18)
        self.assertFalse(r["live_fmt025_enabled"])
        self.assertFalse(r["windows_gui_visual_verified"])
        self.assertEqual(r["official_2026_8_region_season_route_requirements_unverified"],48)
        print("STAGE39_SCHOOL_MASTER_RESULT",{
            "total":r["total_uniquely_verified_master_ids"],
            "new":r["newly_verified_names"],
            "remaining":r["remaining_unverified_names"],
            "id_map":r["verified_school_id_map"],
        })

    def test_gui_uses_new_verified_names_and_does_not_upgrade_unmatched(self):
        model=HiroshimaPreviewGuiModel(DATA,OBSERVED_2026_WEST)
        links=load_2026_hiroshima_west_school_links_stage39(DATA).links
        for name,link in links.items():
            if link.authorized_for_read_only_detail and name in model.search_visible_school_ids(name):
                detail=model.get_verified_school_master_detail(name)
                self.assertEqual(detail.school_id,link.school_id)
                self.assertIn(link.school_id,[row[6] for row in model.render().school_rows])
            elif name in model.search_visible_school_ids(name):
                with self.assertRaises(PreviewGuiModelError):
                    model.get_verified_school_master_detail(name)
        fictional=HiroshimaPreviewGuiModel(DATA,FICTIONAL)
        with self.assertRaises(PreviewGuiModelError):
            fictional.get_verified_school_master_detail("五日市")

    def test_modified_2026_source_review_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/"data"
            shutil.copytree(DATA,base)
            path=base/REVIEW_FILE
            rows=_read(base,REVIEW_FILE)
            rows[0]["proposed_master_official_name"]="存在しない高校"
            with path.open("w",encoding="utf-8",newline="") as file:
                wr=csv.DictWriter(file,fieldnames=list(rows[0]))
                wr.writeheader();wr.writerows(rows)
            with self.assertRaises(SchoolMasterPreviewError):
                audit_2026_hiroshima_stage13e3g39(base)


if __name__=="__main__":
    unittest.main()
