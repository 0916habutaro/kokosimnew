from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g22 import (
    PUBLISHER_GROUPS_FILE, PRIOR_YEAR_PDF_FILE,
    audit_2026_hiroshima_stage13e3g22,
)
from phase2_engine.hiroshima_stage13e3g17 import CROSSWALK_FILE, GROUP_CONTRACT_FILE
from phase2_engine.hiroshima_stage13e3g18 import TRANSITION_FILE
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE

DATA=Path(__file__).resolve().parents[1]/"data"
FILES=(PUBLISHER_GROUPS_FILE, PRIOR_YEAR_PDF_FILE,
       TIMELINE_FILE,CROSSWALK_FILE,GROUP_CONTRACT_FILE,TRANSITION_FILE)


def copy_data(root):
    for relative in FILES:
        p=root/relative
        p.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(DATA/relative,p)


def edit(root,rel,fn):
    p=root/rel
    with p.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        columns,rows=reader.fieldnames,list(reader)
    fn(rows)
    with p.open("w",encoding="utf-8",newline="") as f:
        wr=csv.DictWriter(f,fieldnames=columns)
        wr.writeheader()
        wr.writerows(rows)


class Stage13E3G22AutumnWestPublisherCrosscheckTests(unittest.TestCase):
    def test_nine_published_events_and_25_secondary_recorded_games(self):
        r=audit_2026_hiroshima_stage13e3g22(DATA)
        self.assertTrue(r["ok"],r["errors"])
        self.assertEqual(9,r["2026_autumn_west_pub_child_events"])
        self.assertEqual(25,r["2026_autumn_west_source_games"])

    def test_all_18_primary_teams_and_14_losers_reconciled(self):
        r=audit_2026_hiroshima_stage13e3g22(DATA)
        self.assertEqual(18,r["2026_initial_publisher_team_entries"])
        self.assertEqual(14,r["2026_published_primary_losers_in_second_place_events"])
        self.assertEqual(14,r["2026_primary_losers_with_observed_next_game"])
        self.assertEqual(2,r["2026_publisher_placeholder_entries"])

    def test_four_primary_berths_and_secondary_three_berths(self):
        r=audit_2026_hiroshima_stage13e3g22(DATA)
        self.assertEqual((4,2,1,7),(
            r["2026_primary_awards"],r["2026_secondary_direct_awards"],
            r["2026_secondary_cd_cross_awards"],r["2026_total_qualified"]))

    def test_same_2025_official_pdf_not_reused_as_2026_rule(self):
        r=audit_2026_hiroshima_stage13e3g22(DATA)
        self.assertTrue(r["2025_official_bracket_pdf_checked"])
        self.assertEqual(3,r["2025_official_cross_gate_count"])
        self.assertEqual(1,r["2026_publisher_named_cross_gate_count"])
        self.assertFalse(r["2025_draw_same_as_2026"])
        self.assertEqual(0,r["2026_official_bracket_pdf_body_inspected"])
        self.assertEqual(0,r["2026_official_draw_edges_confirmed"])

    def test_synthetic_match_runtime_is_never_enabled_by_historical_results(self):
        r=audit_2026_hiroshima_stage13e3g22(DATA)
        self.assertTrue(r["2026_actual_team_trail_reconstructed"])
        self.assertFalse(r["annual_independent_fmt025_rules_approved"])
        self.assertFalse(r["active_fmt025_runtime_changed"])
        self.assertFalse(r["fmt025_optional_ranking_unlocked"])

    def test_2026_two_top_secondary_qualifiers_and_cd_last_berth(self):
        with (DATA/PUBLISHER_GROUPS_FILE).open(encoding="utf-8",newline="") as f:
            data=list(csv.DictReader(f))
        by_id={r["published_route_id"]:r for r in data}
        self.assertEqual("HT20260035",by_id["HR20260045"]["observed_decider_match_id"])
        self.assertEqual("HT20260070",by_id["HR20260047"]["observed_decider_match_id"])
        self.assertEqual("広島工大;広島城北",by_id["HR20260052"]["normalized_real_team_names"])
        self.assertEqual("HT20260072",by_id["HR20260052"]["observed_decider_match_id"])

    def test_dummy_is_not_a_real_school(self):
        with (DATA/PUBLISHER_GROUPS_FILE).open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(2,sum(r["publisher_participants_display"].split(";").count("ダミー") for r in rows))
        self.assertFalse(any("ダミー" in r["normalized_real_team_names"] for r in rows))

    def test_primary_champion_not_present_in_same_zone_runnerup_roster(self):
        with (DATA/PUBLISHER_GROUPS_FILE).open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        groups={r["phase_execution_role"]+":"+r["zone_scope"]:r for r in rows}
        for z,champ in (("A","広島商"),("B","山陽"),("C","広島国泰寺"),("D","崇徳")):
            with self.subTest(zone=z):
                self.assertIn(champ,groups["PRIMARY:"+z]["normalized_real_team_names"].split(";"))
                self.assertNotIn(champ,groups["REPECHAGE_ZONE:"+z]["normalized_real_team_names"].split(";"))

    def test_2025_cross_semifinal_and_loser_final_remain_previous_year_only(self):
        with (DATA/PRIOR_YEAR_PDF_FILE).open(encoding="utf-8",newline="") as f:
            pdf=next(csv.DictReader(f))
        self.assertEqual("2025",pdf["prior_year"])
        self.assertEqual("winner_A2_vs_winner_B2",pdf["official_2025_cross_zone_gate_27"])
        self.assertEqual("winner_C2_vs_winner_D2",pdf["official_2025_cross_zone_gate_28"])
        self.assertEqual("loser_27_vs_loser_28",pdf["official_2025_final_seventh_berth_gate_29"])
        self.assertEqual("no",pdf["prior_year_graph_reusable_for_2026"])

    def test_modified_publisher_participant_membership_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root,PUBLISHER_GROUPS_FILE,lambda rows:rows[1].update(
                normalized_real_team_names="大竹;廿日市西;広島井口;別の学校"))
            r=audit_2026_hiroshima_stage13e3g22(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("normalization" in x or "losing cohort" in x for x in r["errors"]))

    def test_wrong_inferred_2025_same_as_2026_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root,PRIOR_YEAR_PDF_FILE,lambda rows:rows[0].update(
                same_draw_topology_between_years="yes"))
            r=audit_2026_hiroshima_stage13e3g22(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("prior-year official bracket evidence" in x for x in r["errors"]))

    def test_official_2026_pdf_false_confirmation_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root,PUBLISHER_GROUPS_FILE,lambda rows:rows[0].update(
                official_2026_federation_pdf_body_checked="yes"))
            r=audit_2026_hiroshima_stage13e3g22(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("wrong publisher identity" in x for x in r["errors"]))

    def test_wrong_berth_award_scoreboard_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root,TIMELINE_FILE,lambda rows:next(
                r for r in rows if r["match_id"]=="HT20260072"
            ).update(winner_name="広島城北"))
            r=audit_2026_hiroshima_stage13e3g22(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("C/D observed final" in x or "award" in x for x in r["errors"]))

    def test_cross_gate_requires_both_prior_second_place_winners(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root,PUBLISHER_GROUPS_FILE,lambda rows:rows[8].update(
                normalized_real_team_names="広島工大;基町",
                publisher_participants_display="工大高;基町",
            ))
            r=audit_2026_hiroshima_stage13e3g22(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("C/D cross game" in x or "publisher child final" in x for x in r["errors"]))

    def test_published_secondary_roster_must_cover_each_first_stage_loser(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root,TRANSITION_FILE,lambda rows:next(
                r for r in rows if r["season"]=="autumn" and r["district_code"]=="west"
                and r["transition_kind"]=="LOSS_PRIMARY_TO_REPECHAGE"
            ).update(school_display_name="架空校"))
            r=audit_2026_hiroshima_stage13e3g22(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("14 primary losers" in x for x in r["errors"]))

    def test_team_aliases_are_explicit_and_audited(self):
        with (DATA/PUBLISHER_GROUPS_FILE).open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        prim={r["zone_scope"]:r for r in rows if r["phase_execution_role"]=="PRIMARY"}
        self.assertIn("広島商業",prim["A"]["publisher_participants_display"])
        self.assertIn("広島商",prim["A"]["normalized_real_team_names"])
        self.assertIn("工大高",prim["C"]["publisher_participants_display"])
        self.assertIn("広島工大",prim["C"]["normalized_real_team_names"])


if __name__=="__main__":
    unittest.main()
