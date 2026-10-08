from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_berth_roster_2026 import (
    ROSTER_FILE, STAGE_GROUP_FILE, audit_2026_hiroshima_prefectural_berth_roster
)
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from phase2_engine.hiroshima_match_level_2026 import (
    ANCHOR_FILE, PRIOR_FILE, ROUTE_FILE, PDF_FILE
)

DATA = Path(__file__).resolve().parents[1] / "data"
FIXTURE_FILES = (
    ROSTER_FILE, STAGE_GROUP_FILE, TIMELINE_FILE, ANCHOR_FILE,
    PRIOR_FILE, ROUTE_FILE, PDF_FILE,
)


def copy_data(root: Path):
    for relative in FIXTURE_FILES:
        dest = root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / relative, dest)


def modify(root: Path, relative: str, fn):
    path = root / relative
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols, records = reader.fieldnames, list(reader)
    fn(records)
    with path.open("w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows(records)


class TestStage13E3G10HiroshimaMainBerthRoster(unittest.TestCase):
    def test_eight_district_rosters_have_exact_prefectural_slots(self):
        r = audit_2026_hiroshima_prefectural_berth_roster(DATA)
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual({"spring":32,"autumn":32}, r["season_berth_counts"])
        self.assertEqual({
            "spring_west":7,"spring_north":7,"spring_south":9,"spring_east":9,
            "autumn_west":7,"autumn_north":6,"autumn_south":10,"autumn_east":9,
        }, r["district_berth_counts"])
        self.assertEqual({"spring":32,"autumn":32}, r["stage_group_quota_sum_by_season"])

    def test_spring_west_selection_exemption_is_not_awarded_by_a_match(self):
        r = audit_2026_hiroshima_prefectural_berth_roster(DATA)
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(["崇徳"],r["confirmed_in_secondary_source_exemption"])
        self.assertEqual(17,r["sampled_match_berth_winners_reconciled"])
        self.assertEqual(46,r["qualifying_teams_lacking_sampled_award_game"])

    def test_listed_entrants_do_not_prove_a_complete_official_pdf_audit(self):
        r = audit_2026_hiroshima_prefectural_berth_roster(DATA)
        self.assertEqual(64,r["secondary_source_qualifier_count"])
        self.assertFalse(r["official_pdf_roster_comparison_complete"])
        self.assertFalse(r["match_by_match_federation_pdf_census_complete"])
        self.assertFalse(r["fmt025_release_allowed"])

    def test_roster_district_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);copy_data(root)
            modify(root, ROSTER_FILE, lambda rr: rr[1].update(school_name=rr[0]["school_name"]))
            r=audit_2026_hiroshima_prefectural_berth_roster(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("duplicate" in e for e in r["errors"]))

    def test_wrong_season_berth_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);copy_data(root)
            modify(root, ROSTER_FILE,lambda rr: rr.pop())
            r=audit_2026_hiroshima_prefectural_berth_roster(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("quota" in e or "64 entrants" in e for e in r["errors"]))

    def test_altering_sotoku_exemption_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);copy_data(root)
            modify(root, ROSTER_FILE,lambda rr: next(r for r in rr if
                r["season"]=="spring" and r["school_name"]=="崇徳").update(
                    qualification_basis="district_result_list",
                ))
            r=audit_2026_hiroshima_prefectural_berth_roster(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("exemption" in e for e in r["errors"]))

    def test_official_pdf_verification_must_not_be_claimed_without_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);copy_data(root)
            modify(root, ROSTER_FILE,lambda rr: rr[0].update(
                provenance_level="official_federation_pdf",
                federation_pdf_comparison="complete"
            ))
            r=audit_2026_hiroshima_prefectural_berth_roster(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("unsupported official PDF" in e for e in r["errors"]))

    def test_changing_stage_group_advance_quota_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);copy_data(root)
            modify(root,STAGE_GROUP_FILE,lambda rr: next(r for r in rr if
                r["stage_group_id"]=="SGR000140").update(advance_slots_to_next="6"))
            r=audit_2026_hiroshima_prefectural_berth_roster(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("stage-group quota" in e for e in r["errors"]))

    def test_berth_award_to_unlisted_team_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);copy_data(root)
            modify(root,TIMELINE_FILE,lambda rr: next(r for r in rr if
                r["match_id"]=="HT20260022").update(
                    winner_name="熊野",team1_score="3",team2_score="4"))
            r=audit_2026_hiroshima_prefectural_berth_roster(root)
            self.assertFalse(r["ok"])
            self.assertTrue(len(r["errors"])>0)

    def test_misassigned_regional_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);copy_data(root)
            modify(root,ROSTER_FILE,lambda rr: rr[0].update(
                source_url="https://example.com/unknown"
            ))
            r=audit_2026_hiroshima_prefectural_berth_roster(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("regional source" in e for e in r["errors"]))


if __name__ == "__main__":
    unittest.main()
