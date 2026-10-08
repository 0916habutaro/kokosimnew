from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g14 import (
    ADDITIONS, CENSUS, OFFICIAL_PDF_LIST, audit_2026_hiroshima_stage13e3g14
)
from phase2_engine.hiroshima_stage13e3g13 import EVIDENCE_FILE as E13
from phase2_engine.hiroshima_stage13e3g12 import EVIDENCE_FILE as E12, QUEUE_FILE
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from phase2_engine.hiroshima_berth_roster_2026 import ROSTER_FILE, STAGE_GROUP_FILE
from phase2_engine.hiroshima_match_level_2026 import ANCHOR_FILE, PRIOR_FILE, ROUTE_FILE, PDF_FILE

DATA = Path(__file__).resolve().parents[1] / "data"
INPUTS = (ADDITIONS,CENSUS,OFFICIAL_PDF_LIST,E13,E12,QUEUE_FILE,TIMELINE_FILE,
          ROSTER_FILE,STAGE_GROUP_FILE,ANCHOR_FILE,PRIOR_FILE,ROUTE_FILE,PDF_FILE)


def prepare(root):
    for name in INPUTS:
        dest = root / name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(DATA / name,dest)


def mutate(root,path,operation):
    filename = root / path
    with filename.open(encoding="utf-8-sig",newline="") as f:
        reader = csv.DictReader(f)
        header,values = reader.fieldnames,list(reader)
    operation(values)
    with filename.open("w",encoding="utf-8",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=header)
        writer.writeheader()
        writer.writerows(values)


class Stage13E3G14TwoSecondaryFixtureCensuses(unittest.TestCase):
    def test_two_secondary_result_pages_have_complete_recorded_fixtures(self):
        r=audit_2026_hiroshima_stage13e3g14(DATA)
        self.assertTrue(r["ok"],r["errors"])
        self.assertEqual(223,r["historical_sample_fixture_count"])
        self.assertEqual(25,r["source_page_new_non_award_fixtures"])
        self.assertEqual({"spring_west":24,"autumn_east":30},
                         r["source_page_transcribed_fixture_counts"])
        self.assertEqual({"spring_west":4,"autumn_east":21},
                         r["stage14_new_by_district"])

    def test_previous_63_qualification_events_are_unchanged(self):
        r=audit_2026_hiroshima_stage13e3g14(DATA)
        self.assertEqual(63,r["verified_berth_award_events"])
        self.assertEqual(8,r["secondarily_fully_transcribed_district_seasons"])
        self.assertEqual(0,r["district_seasons_without_complete_secondary_transcription"])

    def test_pdf_body_cannot_be_claimed_as_read_from_link_only(self):
        r=audit_2026_hiroshima_stage13e3g14(DATA)
        self.assertEqual(0,r["official_federation_pdf_bodies_read"])
        self.assertFalse(r["full_official_match_census_complete"])
        self.assertFalse(r["fmt025_release_allowed"])
        self.assertFalse(r["candidate_classification_is_ranking_evidence"])

    def test_source_page_fixture_score_tamper_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);prepare(root)
            mutate(root,ADDITIONS,lambda rows:rows[0].update(winner_score="100"))
            r=audit_2026_hiroshima_stage13e3g14(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("evidence mismatch" in e for e in r["errors"]))

    def test_complete_flag_on_unread_official_pdf_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);prepare(root)
            mutate(root,CENSUS,lambda rows:rows[0].update(full_official_census_complete="yes"))
            r=audit_2026_hiroshima_stage13e3g14(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("unsupported PDF completeness" in e for e in r["errors"]))

    def test_one_unfinished_secondary_group_cannot_become_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);prepare(root)
            mutate(root,CENSUS,lambda rows:next(r for r in rows if
                r["season"]=="spring" and r["district_code"]=="south"
            ).update(secondary_html_status="pending_full_result_transcription"))
            r=audit_2026_hiroshima_stage13e3g14(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("secondary HTML census mismatch" in e for e in r["errors"]))

    def test_early_results_remain_nonaward_not_ranking(self):
        with (DATA / ADDITIONS).open(encoding="utf-8",newline="") as f:
            a=list(csv.DictReader(f))
        self.assertEqual(25,len(a))
        self.assertTrue(all(x["winner_berth_status"]=="not_proven" for x in a))
        self.assertTrue(all(x["official_pdf_reconciled"]=="no" for x in a))

    def test_4_spring_west_results_include_combined_team(self):
        with (DATA / ADDITIONS).open(encoding="utf-8",newline="") as f:
            a=list(csv.DictReader(f))
        west=[r for r in a if r["season"]=="spring"]
        self.assertEqual(4,len(west))
        self.assertTrue(any(r["loser_name"]=="並木学院・五日市" for r in west))
        self.assertTrue(any(r["winner_name"]=="並木学院・五日市" for r in west))

    def test_source_page_fixture_removed_from_timeline_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);prepare(root)
            mutate(root,TIMELINE_FILE,lambda rows:rows.pop())
            r=audit_2026_hiroshima_stage13e3g14(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("expected 223" in e or "missing or duplicated" in e for e in r["errors"]))

    def test_pdf_link_change_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);prepare(root)
            mutate(root,CENSUS,lambda rows:rows[0].update(pdf_url="https://example.com/unsupported.pdf"))
            r=audit_2026_hiroshima_stage13e3g14(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("unsupported PDF completeness" in e for e in r["errors"]))


if __name__=="__main__":
    unittest.main()
