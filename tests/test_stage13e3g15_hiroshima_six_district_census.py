from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g15 import (
    ADDITIONS, CENSUS, OFFICIAL_PDF_LIST,
    audit_2026_hiroshima_stage13e3g15,
)
from phase2_engine.hiroshima_stage13e3g14 import ADDITIONS as E14
from phase2_engine.hiroshima_stage13e3g13 import EVIDENCE_FILE as E13
from phase2_engine.hiroshima_stage13e3g12 import EVIDENCE_FILE as E12, QUEUE_FILE
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from phase2_engine.hiroshima_berth_roster_2026 import ROSTER_FILE, STAGE_GROUP_FILE
from phase2_engine.hiroshima_match_level_2026 import ANCHOR_FILE, PRIOR_FILE, ROUTE_FILE, PDF_FILE

DATA = Path(__file__).resolve().parents[1] / "data"
REQUIRED = (ADDITIONS, E14, E13, E12, QUEUE_FILE, TIMELINE_FILE, CENSUS,
            OFFICIAL_PDF_LIST, ROSTER_FILE, STAGE_GROUP_FILE,
            ANCHOR_FILE, PRIOR_FILE, ROUTE_FILE, PDF_FILE)


def fixture(root):
    for path in REQUIRED:
        dst = root / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / path, dst)


def edit(root, relative, fn):
    dst = root / relative
    with dst.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header, records = reader.fieldnames, list(reader)
    fn(records)
    with dst.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(records)


class Stage13E3G15SixDistrictResultCensuses(unittest.TestCase):
    def test_all_six_added_regions_reconcile_and_223_matches_exist(self):
        r = audit_2026_hiroshima_stage13e3g15(DATA)
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(115, r["new_partial_qualifier_matches"])
        self.assertEqual(223, r["cumulative_source_page_matches"])
        self.assertEqual(63, r["confirmed_qualification_award_matches"])
        self.assertEqual(160, r["nonaward_matches_not_conclusively_classified"])
        self.assertTrue(r["secondary_source_transcriptions_complete"])

    def test_six_new_district_slices_are_exact(self):
        r = audit_2026_hiroshima_stage13e3g15(DATA)
        self.assertEqual({
            "spring_north": 17, "spring_south": 24, "spring_east": 22,
            "autumn_west": 18, "autumn_north": 16, "autumn_south": 18,
        }, r["added_by_district_season"])

    def test_eight_total_secondary_result_page_counts(self):
        r = audit_2026_hiroshima_stage13e3g15(DATA)
        self.assertEqual({
            "spring_west":24, "spring_north":24, "spring_south":33, "spring_east":31,
            "autumn_west":25, "autumn_north":22, "autumn_south":34, "autumn_east":30,
        }, r["all_eight_html_result_censuses"])

    def test_official_pdf_results_remain_unverified(self):
        r = audit_2026_hiroshima_stage13e3g15(DATA)
        self.assertEqual(0, r["official_pdf_body_verification_count"])
        self.assertFalse(r["official_pdf_full_census_complete"])
        self.assertFalse(r["fmt025_release_allowed"])
        self.assertEqual(0, r["optional_ranking_only_matches_proven"])

    def test_every_new_match_remains_nonaward_not_a_rank_only_claim(self):
        with (DATA / ADDITIONS).open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(115,len(rows))
        self.assertTrue(all(x["qualification_effect_confirmed"] == "no" for x in rows))
        self.assertTrue(all(x["official_pdf_compared"] == "no" for x in rows))
        self.assertEqual(115, len({x["match_id"] for x in rows}))

    def test_a_changed_score_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);fixture(root)
            edit(root, ADDITIONS, lambda x: x[0].update(winner_score="99"))
            r = audit_2026_hiroshima_stage13e3g15(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("source-page match mismatch" in e for e in r["errors"]))

    def test_a_missing_fixture_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);fixture(root)
            edit(root, TIMELINE_FILE, lambda x: x.pop())
            r = audit_2026_hiroshima_stage13e3g15(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("223" in e or "missing or duplicate" in e for e in r["errors"]))

    def test_a_wrong_area_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);fixture(root)
            edit(root, ADDITIONS, lambda x: x[0].update(district_code="west"))
            r = audit_2026_hiroshima_stage13e3g15(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("115 new non-award" in e or "source-page match mismatch" in e for e in r["errors"]))

    def test_fabricated_official_pdf_review_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixture(root)
            edit(root,CENSUS,lambda x:x[0].update(full_official_census_complete="yes"))
            r=audit_2026_hiroshima_stage13e3g15(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("unsupported" in e for e in r["errors"]))

    def test_fabricated_qualification_game_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixture(root)
            edit(root,ADDITIONS,lambda x:x[0].update(qualification_effect_confirmed="yes"))
            r=audit_2026_hiroshima_stage13e3g15(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("unproven official PDF" in e for e in r["errors"]))

    def test_two_independent_joint_team_lineages_stay_visible(self):
        with (DATA / ADDITIONS).open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        combo={r["loser_name"] for r in rows if "・" in r["loser_name"]}
        self.assertIn("庄原実・向原・三次青陵・千代田・加計", combo)
        self.assertIn("黒瀬・大柿・黒瀬特別支援のみのお・並木学院", combo)
        self.assertIn("因島・松永",combo)

    def test_fabricated_html_complete_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixture(root)
            edit(root,CENSUS,lambda x:x[0].update(secondary_listed_games_transcribed="999"))
            r=audit_2026_hiroshima_stage13e3g15(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("secondary HTML census mismatch" in e or "published result count" in e for e in r["errors"]))


if __name__ == "__main__":
    unittest.main()
