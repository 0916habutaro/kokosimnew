from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_qualification_timeline_2026 import (
    TIMELINE_FILE, audit_2026_hiroshima_qualification_timeline,
)
from phase2_engine.hiroshima_match_level_2026 import (
    ANCHOR_FILE, PRIOR_FILE, ROUTE_FILE, PDF_FILE,
)

DATA = Path(__file__).resolve().parents[1] / "data"


def fixture(root: Path):
    for rel in (TIMELINE_FILE, ANCHOR_FILE, PRIOR_FILE, ROUTE_FILE, PDF_FILE):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / rel, dest)


def change(root: Path, mut):
    dest = root / TIMELINE_FILE
    with dest.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        headers, rows = rd.fieldnames, list(rd)
    mut(rows)
    with dest.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G9HiroshimaQualificationTimeline(unittest.TestCase):
    def test_all_8_district_seasons_are_sampled_without_exhaustive_claim(self):
        report = audit_2026_hiroshima_qualification_timeline(DATA)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(37, report["sampled_result_match_count"])
        self.assertEqual(8, report["district_seasons_with_sampled_results"])
        self.assertEqual(17, report["evidenced_winner_berth_lock_count"])
        self.assertEqual(8, report["prior_3g8_anchor_matches"])
        self.assertEqual(4, report["prior_3g7_example_matches"])
        self.assertFalse(report["full_pdf_match_transcription_complete"])
        self.assertFalse(report["fmt025_release_allowed"])
        self.assertEqual(0, report["verified_optional_ranking_matches"])

    def test_kumano_and_kure_mitsuda_september_5_not_prequalified(self):
        r = audit_2026_hiroshima_qualification_timeline(DATA)
        byid = {x["match_id"]: x for x in r["match_prequalification_observations"]}
        # The Sep 5 losses precede the two teams' Sep 6 berth-award wins.
        for matchid in ("HT20260022", "HT20260023"):
            self.assertFalse(byid[matchid]["both_previously_qualified"])

    def test_missing_lock_is_unknown_not_explicitly_unqualified(self):
        r = audit_2026_hiroshima_qualification_timeline(DATA)
        state = r["match_prequalification_observations"][0]
        self.assertEqual("unknown_from_partial_inventory", state["team1_pre_match_state"])
        self.assertEqual("unknown_from_partial_inventory", state["team2_pre_match_state"])
        self.assertTrue(r["missing_berth_lock_must_be_treated_as_unknown"])

    def test_proved_both_locks_still_cannot_infer_optional_ranking(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            fixture(root)
            def append(rows):
                specimen = rows[0].copy()
                specimen.update(
                    match_id="HT20269999", season="autumn",
                    competition_id="CMP000136",stage_group_id="SGR000146",
                    district_code="south",match_date="2026-09-08",
                    start_time="",team1_name="瀬戸内",team1_score="5",
                    team2_name="熊野",team2_score="4",winner_name="瀬戸内",
                    round_label="参考比較試合",winner_berth_status="not_proven",
                )
                rows.append(specimen)
            change(root, append)
            r = audit_2026_hiroshima_qualification_timeline(root)
            self.assertTrue(r["ok"], r["errors"])
            self.assertIn("HT20269999", r["potential_both_locked_match_ids"])
            self.assertFalse(r["fmt025_release_allowed"])
            self.assertEqual(0, r["verified_optional_ranking_matches"])

    def test_same_date_lock_without_finish_time_does_not_prove_qualification(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            fixture(root)
            def append(rows):
                specimen = rows[0].copy()
                specimen.update(
                    match_id="HT20269998",season="autumn",competition_id="CMP000136",
                    stage_group_id="SGR000146",district_code="south",
                    match_date="2026-09-06",start_time="17:00",
                    team1_name="熊野",team1_score="6",team2_name="呉三津田",
                    team2_score="4",winner_name="熊野",
                    round_label="参考比較試合",winner_berth_status="not_proven",
                )
                rows.append(specimen)
            change(root, append)
            r = audit_2026_hiroshima_qualification_timeline(root)
            self.assertTrue(r["ok"], r["errors"])
            self.assertNotIn("HT20269998", r["potential_both_locked_match_ids"])

    def test_false_ranking_classification_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            fixture(root)
            change(root, lambda rows: rows[0].update(
                winner_berth_status="optional_ranking_event"
            ))
            r = audit_2026_hiroshima_qualification_timeline(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("cannot designate historical ranking" in s for s in r["errors"]))

    def test_previous_anchor_winner_conflict_is_detected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            fixture(root)
            change(root, lambda rows: next(r for r in rows
                if r["season"] == "autumn" and r["district_code"] == "east").update(
                    winner_name="英数学館"
                ))
            r = audit_2026_hiroshima_qualification_timeline(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("prior anchor changed" in s for s in r["errors"]))

    def test_duplicate_berth_award_winner_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            fixture(root)
            change(root, lambda rows: next(r for r in rows
                if r["team1_name"] == "修道" and r["team2_name"] == "宮島工"
                and r["match_date"] == "2026-03-21").update(
                    winner_berth_status="berth_award",
                    round_label="予選代表決定戦",
                ))
            r = audit_2026_hiroshima_qualification_timeline(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("duplicated qualification lock" in s for s in r["errors"]))

    def test_absent_proven_berth_label_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            fixture(root)
            change(root, lambda rows: next(r for r in rows
                if r["match_date"] == "2026-04-11").update(
                    round_label="任意順位戦"
                ))
            r = audit_2026_hiroshima_qualification_timeline(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("missing berth-decider" in s for s in r["errors"]))


if __name__ == "__main__":
    unittest.main()
