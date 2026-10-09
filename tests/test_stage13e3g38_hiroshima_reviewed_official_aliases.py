from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g37_school_master import (
    SchoolMasterPreviewLink, SchoolMasterPreviewError, UNRESOLVED, EXACT,
)
from phase2_engine.hiroshima_stage13e3g38_reviewed_aliases import (
    EVIDENCE_FILE, STAGE38_MATCH, EXPECTED_SOURCES,
    audit_2026_hiroshima_stage13e3g38,
    load_2026_hiroshima_west_school_links_stage38,
    resolve_stage38_reviewed_master_links,
)
from phase2_engine.hiroshima_stage13e3g35_preview_gui_model import (
    FICTIONAL, OBSERVED_2026_WEST, HiroshimaPreviewGuiModel,
    PreviewGuiModelError,
)
from phase2_engine.hiroshima_match_level_2026 import _read

DATA=Path(__file__).resolve().parents[1]/"data"


def original(name):
    return SchoolMasterPreviewLink(
        observed_name=name, resolution_status=UNRESOLVED,
        school_id="", official_name="", federation_name="",
        program_id="", prefecture_code="34",source="",
        authorized_for_read_only_detail=False,
    )


def synthetic():
    names=list(_read(DATA,EVIDENCE_FILE)[0]["observed_name"] for _ in range(0))
    names=list(EXPECTED_SOURCES)+[f"その他{i:02}" for i in range(13)]
    baseline={name:original(name) for name in names}
    rows=_read(DATA,EVIDENCE_FILE)
    schools=[
        dict(school_id=f"SCH{i+1:06}",prefecture_code="34",
             official_name=EXPECTED_SOURCES[name][2],
             federation_name=f"other-name-{i}")
        for i,name in enumerate(EXPECTED_SOURCES)
    ]
    programs=[
        dict(school_id=f"SCH{i+1:06}",program_id=f"PRG{i+1:06}",
             reference_year="2026",discipline="hardball",membership_status="active")
        for i in range(5)
    ]
    return dict(prior_links=baseline,review_rows=rows,
                school_master=schools,hardball_programs=programs)


class Stage13E3G38ReviewedAliases(unittest.TestCase):
    def test_synthetic_all_five_reviewed_official_names_resolve_uniquely(self):
        candidate=resolve_stage38_reviewed_master_links(**synthetic())
        self.assertEqual(candidate.reviewed_name_count,5)
        self.assertEqual(set(candidate.newly_resolved_by_review),set(EXPECTED_SOURCES))
        self.assertEqual(len(candidate.candidate_names_not_found_in_master),0)
        self.assertTrue(all(candidate.links[n].resolution_status==STAGE38_MATCH
                            for n in EXPECTED_SOURCES))
        self.assertTrue(all(not candidate.links[n].official_2026_draw_verified
                            for n in EXPECTED_SOURCES))
        self.assertEqual(candidate.links["広島商"].official_name,"広島県立広島商業高等学校")

    def test_unknown_name_kept_unresolved_when_master_not_found(self):
        data=synthetic()
        data["school_master"]=data["school_master"][:-1]
        report=resolve_stage38_reviewed_master_links(**data)
        self.assertIn("広島国泰寺",report.candidate_names_not_found_in_master)
        self.assertFalse(report.links["広島国泰寺"].authorized_for_read_only_detail)
        self.assertEqual(report.links["広島国泰寺"].school_id,"")

    def test_wrong_prefecture_master_does_not_become_school_id(self):
        data=synthetic()
        data["school_master"][0]["prefecture_code"]="35"
        result=resolve_stage38_reviewed_master_links(**data)
        self.assertIn("修大協創",result.candidate_names_not_found_in_master)
        self.assertEqual(result.links["修大協創"].school_id,"")

    def test_wrong_year_or_inactive_hardball_cannot_be_linked(self):
        for field,value in (("reference_year","2025"),("membership_status","inactive"),("discipline","softball")):
            with self.subTest(field=field):
                data=synthetic()
                data["hardball_programs"][0][field]=value
                result=resolve_stage38_reviewed_master_links(**data)
                self.assertIn("修大協創",result.candidate_names_not_found_in_master)

    def test_duplicate_same_official_name_or_program_refuses(self):
        for variant in ("other_id_same_official", "duplicate_program"):
            data=synthetic()
            if variant=="other_id_same_official":
                data["school_master"].append(
                    {**data["school_master"][0],"school_id":"SCH009999"}
                )
            else:
                data["hardball_programs"].append(
                    {**data["hardball_programs"][0],"program_id":"PRG009999"}
                )
            report=resolve_stage38_reviewed_master_links(**data)
            self.assertFalse(report.links["修大協創"].authorized_for_read_only_detail)

    def test_stage37_verified_school_has_precedence_no_double_mapping(self):
        data=synthetic()
        old=data["school_master"][0]
        link=SchoolMasterPreviewLink(
            observed_name="修大協創",resolution_status=EXACT,
            school_id=old["school_id"],official_name=old["official_name"],
            federation_name="修大協創",program_id="PRG000001",
            prefecture_code="34",source="master/schools.csv",
            authorized_for_read_only_detail=True,
        )
        data["prior_links"]["修大協創"]=link
        result=resolve_stage38_reviewed_master_links(**data)
        self.assertEqual(result.links["修大協創"],link)
        self.assertNotIn("修大協創",result.newly_resolved_by_review)

    def test_existing_verification_conflict_is_rejected(self):
        data=synthetic()
        data["prior_links"]["修大協創"]=SchoolMasterPreviewLink(
            observed_name="修大協創",resolution_status=EXACT,
            school_id="SCH123456",official_name="別高校",
            federation_name="修大協創",program_id="P",prefecture_code="34",
            source="master/schools.csv",authorized_for_read_only_detail=True,
        )
        with self.assertRaises(SchoolMasterPreviewError):
            resolve_stage38_reviewed_master_links(**data)

    def test_source_url_school_name_scope_and_extra_rows_are_immutable(self):
        for key,value in (
            ("publication_alias_url","https://wrong.example.net"),
            ("school_official_url","https://wrong.example.net"),
            ("proposed_master_official_name","広島市立広島商業高等学校"),
            ("prefecture_code","35"),
            ("reference_year","2025"),
            ("decision","approved_for_official_bracket"),
            ("proof_scope","official_2026_bracket"),
        ):
            data=synthetic()
            data["review_rows"][3][key]=value
            with self.subTest(key=key), self.assertRaises(SchoolMasterPreviewError):
                resolve_stage38_reviewed_master_links(**data)
        data=synthetic()
        data["review_rows"].append(dict(data["review_rows"][0]))
        with self.assertRaises(SchoolMasterPreviewError):
            resolve_stage38_reviewed_master_links(**data)

    def test_same_master_id_already_allocated_is_not_reassigned(self):
        data=synthetic()
        master=data["school_master"][1]
        data["prior_links"]["その他00"]=SchoolMasterPreviewLink(
            observed_name="その他00",resolution_status=EXACT,school_id=master["school_id"],
            official_name=master["official_name"],federation_name="その他00",
            program_id=data["hardball_programs"][1]["program_id"],
            prefecture_code="34",source="master/schools.csv",
            authorized_for_read_only_detail=True,
        )
        report=resolve_stage38_reviewed_master_links(**data)
        self.assertIn("広島工大",report.candidate_names_not_found_in_master)
        self.assertFalse(report.links["広島工大"].authorized_for_read_only_detail)

    def test_real_2026_master_allows_only_verified_unique_links(self):
        report=load_2026_hiroshima_west_school_links_stage38(DATA)
        self.assertEqual(len(report.links),18)
        self.assertEqual(report.reviewed_name_count,5)
        self.assertEqual(report.links["山陽"].school_id,"SCH001774")
        self.assertEqual(report.links["広島城北"].school_id,"SCH001777")
        self.assertEqual(
            len({v.school_id for v in report.links.values() if v.school_id}),
            sum(bool(v.school_id) for v in report.links.values()),
        )
        self.assertTrue(all(not row.live_fmt025_runtime_enabled for row in report.links.values()))

    def test_stage38_real_audit_preserves_stage37_and_authority_boundaries(self):
        report=audit_2026_hiroshima_stage13e3g38(DATA)
        self.assertTrue(report["ok"],report["errors"])
        self.assertEqual(report["observed_school_count"],18)
        self.assertEqual(report["reviewed_new_official_name_candidates"],5)
        self.assertGreaterEqual(report["total_verified_master_ids"],report["prior_verified_count"])
        self.assertEqual(report["total_verified_master_ids"]+len(report["still_unresolved_names"]),18)
        self.assertFalse(report["live_fmt025_enabled"])
        self.assertFalse(report["official_2026_west_numbered_arrows_verified"])
        self.assertFalse(report["sqlite_written"])
        print("STAGE38_MASTER_RECONCILIATION", {
            "previous":report["prior_verified_count"],
            "new_names":report["newly_resolved_names"],
            "still_unresolved":report["still_unresolved_names"],
            "total":report["total_verified_master_ids"],
        })

    def test_real_pilot_master_details_obey_verified_status_and_fictional_block(self):
        pilot=HiroshimaPreviewGuiModel(DATA,OBSERVED_2026_WEST)
        links=load_2026_hiroshima_west_school_links_stage38(DATA).links
        for name,row in links.items():
            visible=name in pilot.search_visible_school_ids(name)
            if not visible:
                with self.assertRaises(PreviewGuiModelError):
                    pilot.get_verified_school_master_detail(name)
            elif row.authorized_for_read_only_detail:
                detail=pilot.get_verified_school_master_detail(name)
                self.assertEqual(detail.school_id,row.school_id)
                self.assertIn(row.school_id,[x[6] for x in pilot.render().school_rows])
                self.assertIn(name,pilot.search_visible_school_ids(detail.official_name))
            else:
                with self.assertRaises(PreviewGuiModelError):
                    pilot.get_verified_school_master_detail(name)
        fictional=HiroshimaPreviewGuiModel(DATA,FICTIONAL)
        with self.assertRaises(PreviewGuiModelError):
            fictional.get_verified_school_master_detail("山陽")

    def test_master_candidate_file_tamper_fails_integration_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"data"
            shutil.copytree(DATA,root)
            path=root/EVIDENCE_FILE
            rows=_read(root,EVIDENCE_FILE)
            rows[0]["proposed_master_official_name"]="でたらめな学校"
            with path.open("w",newline="",encoding="utf-8") as file:
                writer=csv.DictWriter(file,fieldnames=list(rows[0]))
                writer.writeheader();writer.writerows(rows)
            with self.assertRaises(SchoolMasterPreviewError):
                audit_2026_hiroshima_stage13e3g38(root)


if __name__=="__main__":
    unittest.main()
