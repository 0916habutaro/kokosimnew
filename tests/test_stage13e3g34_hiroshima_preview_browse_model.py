from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from phase2_engine.browse_views import DatedMatchRow, SeasonBrowseViews
from phase2_engine.hiroshima_fmt025_input_preflight import load_preflight_payload_json
from phase2_engine.hiroshima_fmt025_incremental_preview import (
    IncrementalPreviewError, start_read_only_preview, record_preapproved_match_result,
    replace_checkpoint_results,
)
from phase2_engine.hiroshima_fmt025_preview_browse_model import (
    DATE_SECONDARY, DATE_UNDATED, VIEW_SCOPE, QualifierBrowseMatch,
    build_fmt025_preview_browse_views,
)
from phase2_engine.hiroshima_stage13e3g32 import EXAMPLE_SANDBOX_FILE, EXAMPLE_OBSERVED_FILE
from phase2_engine.hiroshima_stage13e3g34 import (
    SAMPLE_PHASE_ROWS_FILE, audit_2026_hiroshima_stage13e3g34,
)
from phase2_engine.hiroshima_stage13e3g31 import replay_stage25_historical_observations
from phase2_engine.hiroshima_stage13e3g25 import NODES_FILE, EDGES_FILE
from phase2_engine.hiroshima_match_level_2026 import _read

DATA = Path(__file__).resolve().parents[1] / "data"


def fixture(relative):
    return load_preflight_payload_json((DATA / relative).read_text(encoding="utf-8"))


def initial():
    payload=fixture(EXAMPLE_SANDBOX_FILE)
    state=start_read_only_preview(payload)
    return payload,state,build_fmt025_preview_browse_views(payload,state.checkpoint)


def after(*events):
    p,s,_=initial()
    for mid,win in events:
        s=record_preapproved_match_result(p,s.checkpoint,match_id=mid,recorded_winner_id=win)
    return p,s,build_fmt025_preview_browse_views(p,s.checkpoint)


class HiroshimaStage13E3G34BrowseReadModelTests(unittest.TestCase):
    def test_four_state_contract_and_25_historical_matches(self):
        report=audit_2026_hiroshima_stage13e3g34(DATA)
        self.assertTrue(report["ok"],report["errors"])
        self.assertEqual(len(report["fictional_browse_milestones"]),4)
        self.assertEqual(report["2026_west_read_model"]["matches"],25)
        self.assertEqual(report["2026_west_read_model"]["schools"],18)
        self.assertEqual(report["2026_west_read_model"]["confirmed_qualifiers"],7)
        self.assertFalse(report["wrote_browse_sqlite"])
        self.assertFalse(report["official_draw_promoted"])
        self.assertFalse(report["fmt025_live_enabled"])
        self.assertEqual(report["unresolved_annual_route_rule_items"],48)

    def test_pending_ready_completed_as_separate_browse_rows(self):
        p,state,view=initial()
        self.assertEqual(len(view.matches_by_date),3)
        rows={x.match_id:x for x in view.matches_by_date}
        self.assertEqual((rows["P1"].match_status,rows["P2"].match_status,rows["R1"].match_status),
                         ("ready","ready","waiting"))
        self.assertEqual(rows["P1"].team1_name,"A")
        self.assertEqual(rows["P1"].team2_name,"B")
        self.assertEqual(rows["R1"].team1_id,"")
        self.assertEqual(rows["R1"].team2_id,"")
        self.assertEqual(rows["R1"].winner_id,"")
        self.assertEqual(rows["R1"].match_date,"")
        self.assertEqual(rows["R1"].result_text,"対戦カード未確定")
        self.assertEqual(rows["P1"].result_text,"対戦カード確定・結果未記録")
        self.assertEqual(view.proof_scope,VIEW_SCOPE)

    def test_no_unscheduled_date_or_fabricated_score(self):
        p,s,view=after(("P1","A"),("P2","C"),("R1","B"))
        self.assertEqual(len(view.matches_for_date("")),3)
        self.assertEqual(view.matches_for_date("2026-08-22"),())
        for m in view.matches_by_date:
            self.assertEqual(m.date_source,DATE_UNDATED)
            self.assertEqual(m.match_date,"")
            self.assertIsNone(m.team1_score)
            self.assertIsNone(m.team2_score)
            self.assertEqual(m.score_source,"not_available")
            self.assertIn("得点未収録",m.result_text)
            self.assertEqual(m.official_match_number,"")
            self.assertFalse(m.is_official_draw_verified)

    def test_winner_and_loser_hidden_until_completed(self):
        _,_,before=initial()
        for m in before.matches_by_date:
            self.assertEqual(m.winner_id,"")
            self.assertEqual(m.loser_id,"")
        _,_,after_one=after(("P1","A"))
        p1=next(m for m in after_one.matches_by_date if m.match_id=="P1")
        self.assertEqual((p1.winner_id,p1.loser_id),("A","B"))
        r1=next(m for m in after_one.matches_by_date if m.match_id=="R1")
        self.assertEqual((r1.winner_id,r1.loser_id),("",""))

    def test_two_results_unlock_repechage_participants_but_not_result(self):
        _,_,view=after(("P1","A"),("P2","C"))
        r1=next(m for m in view.matches_by_date if m.match_id=="R1")
        self.assertEqual((r1.team1_id,r1.team2_id),("B","D"))
        self.assertEqual(r1.match_status,"ready")
        self.assertEqual(r1.winner_id,"")
        self.assertIsNone(r1.team1_score)
        self.assertEqual(view.competition_results[0].confirmed_qualifier_count,2)
        self.assertEqual(view.competition_results[0].remaining_qualifier_slots,1)

    def test_berth_origin_exact_awarding_match_not_prior_win(self):
        _,_,v=after(("P1","A"),("P2","C"),("R1","B"))
        self.assertEqual([(x.school_id,x.awarded_from_match_id) for x in v.confirmed_berths],
                         [("A","P1"),("C","P2"),("B","R1")])
        self.assertTrue(all(x.qualification_kind=="earned_from_completed_match"
                            for x in v.confirmed_berths))

    def test_school_counts_ignore_unknown_future_match(self):
        _,_,v=initial()
        schools={x.school_id:x for x in v.school_records}
        self.assertEqual(set(schools),{"A","B","C","D"})
        self.assertEqual(schools["A"].games,0)
        self.assertEqual(schools["A"].ready_match_count,1)
        self.assertEqual(schools["B"].qualification_status,"ready")
        _,_,done=after(("P1","A"))
        schools={x.school_id:x for x in done.school_records}
        self.assertEqual((schools["A"].games,schools["A"].wins,schools["A"].losses),(1,1,0))
        self.assertEqual((schools["B"].games,schools["B"].wins,schools["B"].losses),(1,0,1))
        self.assertEqual(schools["A"].qualification_status,"qualified")
        self.assertEqual(schools["B"].qualification_status,"no_ready_game")

    def test_competition_summary_keeps_main_qualification_not_champion(self):
        _,_,v=after(("P1","A"),("P2","C"),("R1","B"))
        row=v.competition_results[0]
        self.assertEqual((row.fixture_count,row.completed_count,row.qualifier_quota),(3,3,3))
        self.assertEqual(row.confirmed_qualifier_count,3)
        self.assertTrue(row.replay_completed)
        self.assertFalse(row.official_draw_verified)
        self.assertFalse(row.live_fmt025_enabled)
        self.assertFalse(hasattr(row,"champion_name"))
        self.assertEqual(row.year,None)
        self.assertEqual(row.group_id,"SANDBOX")

    def test_school_date_competition_navigation_filters(self):
        _,_,v=after(("P1","A"),("P2","C"),("R1","B"))
        self.assertEqual([x.match_id for x in v.matches_for_school("A")],["P1"])
        self.assertEqual(set(x.match_id for x in v.matches_for_school("B")),{"P1","R1"})
        self.assertEqual(v.matches_for_school("unknown"),())
        self.assertEqual(len(v.matches_for_competition("SANDBOX")),3)
        self.assertEqual(v.matches_for_competition("SGR000144"),())
        with self.assertRaises(ValueError):
            v.matches_for_school("")
        with self.assertRaises(ValueError):
            v.matches_for_date(None)
        with self.assertRaises(ValueError):
            v.matches_for_competition("")

    def test_immutable_view_and_dict_exports_do_not_mutate_source(self):
        p,state,v=initial()
        self.assertIsInstance(v.matches_by_date,tuple)
        self.assertIsInstance(v.school_records,tuple)
        with self.assertRaises(FrozenInstanceError):
            v.matches_by_date[0].winner_id="A"
        d=v.matches_by_date[0].to_dict()
        d["winner_id"]="fabricated"
        self.assertEqual(v.matches_by_date[0].winner_id,"")
        self.assertEqual(v.competition_results[0].to_dict()["ready_count"],2)

    def test_do_not_coerce_unplayed_fixtures_into_scored_season_schema(self):
        _,_,v=initial()
        self.assertNotIsInstance(v,SeasonBrowseViews)
        self.assertTrue(all(not isinstance(m,DatedMatchRow) for m in v.matches_by_date))
        self.assertFalse(hasattr(v,"write_to_sqlite"))
        self.assertFalse(hasattr(v,"persist"))

    def test_untrusted_checkpoint_must_be_revalidated(self):
        p,s,_=initial()
        tampered=replace(s.checkpoint, applied_results=(("R1","B"),))
        with self.assertRaises(IncrementalPreviewError):
            build_fmt025_preview_browse_views(p,tampered)
        cheat=replace(s.checkpoint,live_fmt025_runtime_enabled=True)
        with self.assertRaises(IncrementalPreviewError):
            build_fmt025_preview_browse_views(p,cheat)

    def test_tampered_stage32_input_is_rejected(self):
        p,s,_=initial()
        altered=copy.deepcopy(p)
        altered["official_draw_verified"]=True
        with self.assertRaises(IncrementalPreviewError):
            build_fmt025_preview_browse_views(altered,s.checkpoint)
        altered=copy.deepcopy(p)
        altered["winners_by_match"]["R1"]="D"
        with self.assertRaises(IncrementalPreviewError):
            build_fmt025_preview_browse_views(altered,s.checkpoint)

    def test_history_initial_has_no_match_dates_or_result_text_leak(self):
        p=fixture(EXAMPLE_OBSERVED_FILE)
        s=start_read_only_preview(p,data_dir=DATA)
        v=build_fmt025_preview_browse_views(p,s.checkpoint,data_dir=DATA)
        self.assertEqual(v.competition_results[0].year,2026)
        self.assertEqual(v.competition_results[0].group_id,"SGR000144")
        self.assertEqual(v.competition_results[0].fixture_count,25)
        self.assertTrue(all(not m.match_date and not m.winner_id for m in v.matches_by_date))
        self.assertTrue(all(m.date_source==DATE_UNDATED for m in v.matches_by_date))
        self.assertEqual(len(v.confirmed_berths),0)
        self.assertIn("史実結果閲覧",v.competition_results[0].competition_name)
        self.assertIn("not_official_drawing",v.competition_results[0].evidence_grade)

    def test_historical_completed_date_is_secondary_not_projected_or_official(self):
        p=fixture(EXAMPLE_OBSERVED_FILE)
        s=start_read_only_preview(p,data_dir=DATA)
        by_match={r["match_id"]:r for r in _read(DATA,NODES_FILE)}
        trace=replay_stage25_historical_observations(_read(DATA,NODES_FILE),_read(DATA,EDGES_FILE))
        first=s.ready_match_ids[0]
        winner={x.match_id:x.winner_id for x in trace.match_traces}[first]
        s=record_preapproved_match_result(p,s.checkpoint,match_id=first,
                                          recorded_winner_id=winner,data_dir=DATA)
        v=build_fmt025_preview_browse_views(p,s.checkpoint,data_dir=DATA)
        completed=[m for m in v.matches_by_date if m.match_status=="completed"]
        self.assertEqual(len(completed),1)
        self.assertEqual(completed[0].match_date,by_match[first]["match_date"])
        self.assertEqual(completed[0].date_source,DATE_SECONDARY)
        self.assertEqual(len(v.matches_for_date(completed[0].match_date)),1)
        self.assertTrue(all(m.match_date=="" for m in v.matches_by_date if m.match_status!="completed"))
        self.assertTrue(all(m.team1_score is None and m.team2_score is None for m in v.matches_by_date))

    def test_history_full_25_match_7_berth_18_school_view(self):
        p=fixture(EXAMPLE_OBSERVED_FILE)
        s=start_read_only_preview(p,data_dir=DATA)
        oracle=replay_stage25_historical_observations(_read(DATA,NODES_FILE),_read(DATA,EDGES_FILE))
        winners={x.match_id:x.winner_id for x in oracle.match_traces}
        for _ in range(25):
            mid=s.ready_match_ids[0]
            s=record_preapproved_match_result(p,s.checkpoint,match_id=mid,
                                              recorded_winner_id=winners[mid],data_dir=DATA)
        v=build_fmt025_preview_browse_views(p,s.checkpoint,data_dir=DATA)
        self.assertEqual(len(v.matches_by_date),25)
        self.assertEqual(len(v.confirmed_berths),7)
        self.assertEqual(len(v.school_records),18)
        self.assertEqual(set(x.school_id for x in v.confirmed_berths),set(oracle.qualifier_ids))
        self.assertEqual(sum(x.games for x in v.school_records),50)
        self.assertEqual(sum(x.wins for x in v.school_records),25)
        self.assertEqual(sum(x.losses for x in v.school_records),25)
        self.assertTrue(all(m.match_date and m.date_source==DATE_SECONDARY
                            for m in v.matches_by_date))
        self.assertTrue(all(m.official_match_number=="" for m in v.matches_by_date))
        self.assertFalse(v.live_fmt025_runtime_enabled)

    def test_manifest_data_corruption_causes_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"data"
            shutil.copytree(DATA,root)
            target=root/SAMPLE_PHASE_ROWS_FILE
            s=target.read_text(encoding="utf-8")
            target.write_text(s.replace("after_P1,1,1,1,4,1,2,no","after_P1,1,1,1,4,2,2,no"),
                              encoding="utf-8")
            report=audit_2026_hiroshima_stage13e3g34(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any("browse milestone row 1" in x for x in report["errors"]),report["errors"])


if __name__ == "__main__":
    unittest.main()
