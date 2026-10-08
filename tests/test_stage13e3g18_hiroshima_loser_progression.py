from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g18 import (
    TRANSITION_FILE, SUMMARY_FILE, SECOND_CHANCE_FILE, BLOCK_SOURCES,
    audit_2026_hiroshima_stage13e3g18,
)
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from phase2_engine.hiroshima_stage13e3g16 import EVENT_FILE
from phase2_engine.hiroshima_stage13e3g17 import CROSSWALK_FILE, GROUP_CONTRACT_FILE

DATA=Path(__file__).resolve().parents[1]/"data"
SOURCES=(TRANSITION_FILE,SUMMARY_FILE,SECOND_CHANCE_FILE,TIMELINE_FILE,
         EVENT_FILE,CROSSWALK_FILE,GROUP_CONTRACT_FILE,*BLOCK_SOURCES)


def copy_inputs(root):
    for path in SOURCES:
        to=root/path
        to.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(DATA/path,to)


def edit(root,rel,fn):
    p=root/rel
    with p.open(encoding="utf-8-sig",newline="") as file:
        rdr=csv.DictReader(file)
        h,rr=rdr.fieldnames,list(rdr)
    fn(rr)
    with p.open("w",encoding="utf-8",newline="") as file:
        w=csv.DictWriter(file,fieldnames=h)
        w.writeheader()
        w.writerows(rr)


class Stage13E3G18HiroshimaLoserProgression(unittest.TestCase):
    def test_223_fixtures_yield_287_observed_connections(self):
        r=audit_2026_hiroshima_stage13e3g18(DATA)
        self.assertTrue(r["ok"],r["errors"])
        self.assertEqual(223,r["historical_secondary_fixture_count"])
        self.assertEqual(159,r["distinct_school_or_joint_team_seasonal_entries"])
        self.assertEqual(287,r["observed_match_to_match_transitions"])
        self.assertEqual({
            "WIN_PRIMARY_TO_PRIMARY":83,
            "LOSS_PRIMARY_TO_REPECHAGE":121,
            "WIN_REPECHAGE_TO_REPECHAGE":77,
            "LOSS_REPECHAGE_TO_REPECHAGE":6,
        },r["transition_classification_counts"])

    def test_eight_groups_and_63_berths_are_unmodified(self):
        r=audit_2026_hiroshima_stage13e3g18(DATA)
        self.assertTrue(r["secondary_results_all_eight_districts_recorded"])
        with (DATA/SUMMARY_FILE).open(encoding="utf-8",newline="") as file:
            rows=list(csv.DictReader(file))
        self.assertEqual(8,len(rows))
        self.assertEqual(63,sum(int(x["qualification_award_wins"]) for x in rows))
        self.assertEqual(287,sum(int(x["observed_transitions"]) for x in rows))

    def test_six_second_chances_after_losing_a_repechage_decider(self):
        r=audit_2026_hiroshima_stage13e3g18(DATA)
        self.assertEqual(6,r["verified_after_loss_second_chance_examples"])
        with (DATA/SECOND_CHANCE_FILE).open(encoding="utf-8",newline="") as file:
            rows=list(csv.DictReader(file))
        self.assertEqual({
            "安西","総合技術","呉三津田","熊野","神辺旭","英数学館"
        },{x["school_display_name"] for x in rows})
        self.assertTrue(all(x["second_match_winner_has_berth_award"]=="yes" for x in rows))

    def test_chronology_of_kure_mitsuta_and_kumano(self):
        with (DATA/SECOND_CHANCE_FILE).open(encoding="utf-8",newline="") as file:
            rows={x["school_display_name"]:x for x in csv.DictReader(file)}
        self.assertEqual(("HT20260023","HT20260020","2026-09-05","2026-09-06"),
                         (rows["呉三津田"]["first_qualification_decider_loss_id"],
                          rows["呉三津田"]["second_qualification_decider_id"],
                          rows["呉三津田"]["first_match_date"],
                          rows["呉三津田"]["second_match_date"]))
        self.assertEqual(("HT20260022","HT20260021"),
                         (rows["熊野"]["first_qualification_decider_loss_id"],
                          rows["熊野"]["second_qualification_decider_id"]))

    def test_cross_zone_block_hint_change_is_not_a_verified_draw_edge(self):
        r=audit_2026_hiroshima_stage13e3g18(DATA)
        self.assertEqual(10,r["block_display_label_changes"])
        self.assertEqual(0,r["official_federation_pdf_draw_edges_verified"])
        self.assertFalse(r["draw_accurate_runtime_transition_ready"])

    def test_15_publisher_events_have_30_team_side_transitions(self):
        r=audit_2026_hiroshima_stage13e3g18(DATA)
        self.assertEqual(30,r["annotated_publisher_event_transitions"])

    def test_historical_school_sequences_not_installed_as_runtime_rules(self):
        r=audit_2026_hiroshima_stage13e3g18(DATA)
        self.assertFalse(r["historical_games_pinned_to_simulation"])
        self.assertFalse(r["fmt025_optional_ranking_release_allowed"])
        self.assertEqual("2026_secondary_result_observed_team_sequences_not_annual_draw",
                         r["verification_scope"])

    def test_changed_source_game_date_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_inputs(root)
            edit(root,TIMELINE_FILE,lambda rr:rr[0].update(match_date="2026-03-27"))
            r=audit_2026_hiroshima_stage13e3g18(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("participant transition" in x or "not strictly later" in x
                                for x in r["errors"]))

    def test_transition_removal_caught(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_inputs(root)
            edit(root,TRANSITION_FILE,lambda rr:rr.pop())
            r=audit_2026_hiroshima_stage13e3g18(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("287" in x for x in r["errors"]))

    def test_reassigning_school_to_other_transition_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_inputs(root)
            edit(root,TRANSITION_FILE,lambda rr:rr[0].update(school_display_name="架空高校"))
            r=audit_2026_hiroshima_stage13e3g18(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("participant transition row" in x for x in r["errors"]))

    def test_fake_official_pdf_draw_confirmation_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_inputs(root)
            edit(root,TRANSITION_FILE,lambda rr:rr[0].update(official_pdf_draw_edge_verified="yes"))
            r=audit_2026_hiroshima_stage13e3g18(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("official_pdf_draw_edge_verified" in x for x in r["errors"]))

    def test_fake_runtime_enablement_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_inputs(root)
            edit(root,TRANSITION_FILE,lambda rr:rr[0].update(runtime_draw_transition_enabled="yes"))
            r=audit_2026_hiroshima_stage13e3g18(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("runtime_draw_transition_enabled" in x for x in r["errors"]))

    def test_second_chance_score_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_inputs(root)
            edit(root,SECOND_CHANCE_FILE,lambda rr:rr[0].update(second_match_score="99-0"))
            r=audit_2026_hiroshima_stage13e3g18(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("after-loss second-chance row" in x for x in r["errors"]))

    def test_block_hint_alteration_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_inputs(root)
            edit(root,TRANSITION_FILE,lambda rr:rr[0].update(from_block_hint="Z"))
            r=audit_2026_hiroshima_stage13e3g18(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("participant transition row" in x for x in r["errors"]))

    def test_duplicate_same_day_school_appearance_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_inputs(root)
            edit(root,TIMELINE_FILE,lambda rr:rr[1].update(
                team1_name=rr[0]["team1_name"],match_date=rr[0]["match_date"]))
            r=audit_2026_hiroshima_stage13e3g18(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("not strictly later calendar date" in x for x in r["errors"]))

    def test_publisher_stage_game_routing_cannot_be_forged(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_inputs(root)
            edit(root,TRANSITION_FILE,lambda rr:next(
                x for x in rr if x["target_publisher_route_id"]
            ).update(target_publisher_route_id="HR20269999"))
            r=audit_2026_hiroshima_stage13e3g18(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("target_publisher_route_id" in x for x in r["errors"]))


if __name__=="__main__":
    unittest.main()
