from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g13 import (
    EVIDENCE_FILE, JOINT_LOSERS, audit_2026_hiroshima_stage13e3g13
)
from phase2_engine.hiroshima_stage13e3g12 import EVIDENCE_FILE as OLD_EVIDENCE, QUEUE_FILE
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from phase2_engine.hiroshima_berth_roster_2026 import ROSTER_FILE, STAGE_GROUP_FILE
from phase2_engine.hiroshima_match_level_2026 import ANCHOR_FILE, PRIOR_FILE, ROUTE_FILE, PDF_FILE

DATA = Path(__file__).resolve().parents[1] / "data"
INPUTS = (EVIDENCE_FILE, OLD_EVIDENCE, QUEUE_FILE, TIMELINE_FILE, ROSTER_FILE,
          STAGE_GROUP_FILE, ANCHOR_FILE, PRIOR_FILE, ROUTE_FILE, PDF_FILE)


def stage_fixture(root):
    for rel in INPUTS:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / rel, target)


def edit(root, rel, fn):
    target = root / rel
    with target.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    fn(rows)
    with target.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G13HiroshimaAllBerthWinners(unittest.TestCase):
    def test_all_63_nonexempt_awards_with_one_exempt_entrant(self):
        r = audit_2026_hiroshima_stage13e3g13(DATA)
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(22, r["newly_documented_qualification_games"])
        self.assertEqual(223, r["cumulative_sample_match_count"])
        self.assertEqual(63, r["match_proven_qualification_school_count"])
        self.assertEqual(1, r["exempt_seasonal_entrant_count"])
        self.assertEqual(64, r["secondary_source_seasonal_entrant_count"])
        self.assertTrue(r["secondary_roster_qualification_award_coverage_complete"])
        self.assertEqual(0, r["qualification_award_investigation_queue_remaining"])

    def test_five_groups_have_the_exact_discovered_award_counts(self):
        r = audit_2026_hiroshima_stage13e3g13(DATA)
        self.assertEqual({
            "spring_north": 6, "spring_west": 1,
            "autumn_west": 6, "autumn_north": 5, "autumn_south": 4,
        }, r["new_games_by_region"])

    def test_still_not_an_exhaustive_official_pdf_audit(self):
        r = audit_2026_hiroshima_stage13e3g13(DATA)
        self.assertFalse(r["all_official_federation_pdf_game_cards_inspected"])
        self.assertEqual(0, r["ranking_only_optional_matches_confirmed"])
        self.assertFalse(r["fmt025_release_allowed"])
        self.assertEqual("full_berth_winner_coverage_not_full_match_census", r["scope"])

    def test_late_repechage_north_spring_is_qualification_not_ranking(self):
        with (DATA / EVIDENCE_FILE).open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        r = next(x for x in rows if x["qualifying_school"] == "庄原格致")
        self.assertEqual(("2026-04-05","安西","7-6"),
                         (r["date"],r["losing_team_display"],r["score"]))
        self.assertEqual("予選敗者戦代表決定戦", r["round_label"])

    def test_joint_teams_have_full_school_lists_in_display(self):
        with (DATA / EVIDENCE_FILE).open(encoding="utf-8", newline="") as f:
            rows = {x["match_id"]: x for x in csv.DictReader(f)}
        self.assertEqual(2, len(JOINT_LOSERS))
        for mid, display in JOINT_LOSERS.items():
            self.assertEqual(display, rows[mid]["losing_team_display"])
            self.assertEqual("yes", rows[mid]["combined_team_display"])

    def test_score_tampering_caught(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); stage_fixture(root)
            edit(root,EVIDENCE_FILE,lambda rr: rr[0].update(score="99-0"))
            report = audit_2026_hiroshima_stage13e3g13(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("unmatched result" in e for e in report["errors"]))

    def test_untrue_official_pdf_flag_is_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); stage_fixture(root)
            edit(root,EVIDENCE_FILE,lambda rr: rr[0].update(official_pdf_inspected="yes"))
            report = audit_2026_hiroshima_stage13e3g13(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("unsupported federation PDF" in e for e in report["errors"]))

    def test_removed_qualifying_game_is_detected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); stage_fixture(root)
            edit(root,TIMELINE_FILE,lambda rr: rr.pop())
            report = audit_2026_hiroshima_stage13e3g13(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("223" in e or "qualification winners" in e for e in report["errors"]))

    def test_reintroduced_unlinked_school_is_detected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); stage_fixture(root)
            def reintroduce(rr):
                rr.append({
                    "gap_id":"HG20269999","season":"autumn","district_code":"north",
                    "school_name":"広陵","roster_id":"HB20260042",
                    "status":"award_match_not_yet_documented",
                    "needed_evidence":"dated_berth_decider_or_exemption_proof",
                    "source_url":"https://example.com/",
                })
            edit(root,QUEUE_FILE,reintroduce)
            report = audit_2026_hiroshima_stage13e3g13(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("0 missing" in e for e in report["errors"]))

    def test_winner_not_in_roster_is_detected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); stage_fixture(root)
            edit(root,EVIDENCE_FILE,lambda rr: rr[0].update(qualifying_school="未登録高校"))
            report = audit_2026_hiroshima_stage13e3g13(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("missing MAIN entrant" in e for e in report["errors"]))

    def test_joint_team_shorthand_is_detected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); stage_fixture(root)
            edit(root,EVIDENCE_FILE,lambda rr: next(r for r in rr
                 if r["match_id"] == "HT20260075").update(losing_team_display="加計芸北"))
            report = audit_2026_hiroshima_stage13e3g13(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("combined-team display" in e or "unmatched result" in e
                                for e in report["errors"]))


if __name__ == "__main__":
    unittest.main()
