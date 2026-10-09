from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.browse_gui_stage13d3 import Stage13D3BrowseApp
from phase2_engine.hiroshima_fmt025_incremental_preview import IncrementalPreviewError
from phase2_engine.hiroshima_stage13e3g35_preview_gui import (
    APP_TITLE, HiroshimaPreviewWindow, build_parser,
)
from phase2_engine.hiroshima_stage13e3g35_preview_gui_model import (
    FICTIONAL, OBSERVED_2026_WEST, SCENARIOS,
    STATUS_LABELS, HiroshimaPreviewGuiModel, PreviewGuiModelError,
)
from phase2_engine.hiroshima_stage13e3g35 import (
    audit_2026_hiroshima_stage13e3g35,
)

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"


class Stage13E3G35PilotGuiTests(unittest.TestCase):
    def test_full_gui_contract_audit(self):
        report=audit_2026_hiroshima_stage13e3g35(DATA)
        self.assertTrue(report["ok"],report["errors"])
        self.assertEqual(report["pilot"],{
            "scenario_count":2, "fictional_states":4,
            "historical_revealed_games":25, "historical_school_count":18,
            "historical_qualifier_count":7,
        })
        self.assertTrue(report["attached_to_existing_browse_gui"])
        self.assertFalse(report["sqlite_changes"])
        self.assertFalse(report["native_window_visual_check_performed"])
        self.assertEqual(report["annual_unresolved_official_route_items"],48)
        self.assertEqual(report["newly_verified_official_arrows"],0)
        self.assertFalse(report["live_fmt025_runtime_enabled"])
        self.assertFalse(report["optional_ranking_enabled"])

    def test_initial_fictional_gui_presenter(self):
        model=HiroshimaPreviewGuiModel(DATA)
        data=model.render()
        self.assertEqual(data.scenario_id,FICTIONAL)
        self.assertEqual((data.played_count,data.ready_count,data.waiting_count),(0,2,1))
        self.assertEqual(data.qualifier_count,0)
        self.assertEqual(len(data.match_rows),3)
        self.assertEqual(len(data.school_rows),4)
        self.assertEqual(data.berth_rows,())
        self.assertTrue(data.next_result_enabled)
        self.assertTrue(all(row[6]=="－" for row in data.match_rows))
        self.assertTrue(all(row[4]=="－" for row in data.match_rows))
        self.assertEqual(data.source_note, "架空の試験データです。実在の公式抽選・試合結果ではありません。")

    def test_one_button_click_advances_only_preapproved_result(self):
        model=HiroshimaPreviewGuiModel(DATA)
        self.assertEqual(model.show_next_preapproved_result(),"P1")
        current=model.render()
        self.assertEqual((current.played_count,current.ready_count,current.waiting_count),(1,1,1))
        self.assertEqual(current.qualifier_count,1)
        self.assertEqual(current.berth_rows,(("A","県大会進出確定","P1"),))
        self.assertIn("1/3",current.summary)
        self.assertEqual(len(model.render(status_filter="completed").match_rows),1)
        self.assertEqual(len(model.render(status_filter="waiting").match_rows),1)

    def test_complete_three_fictional_preapproved_results(self):
        model=HiroshimaPreviewGuiModel(DATA)
        self.assertEqual([model.show_next_preapproved_result() for _ in range(3)],
                         ["P1","P2","R1"])
        out=model.render()
        self.assertEqual(out.played_count,3)
        self.assertEqual(out.qualifier_count,3)
        self.assertEqual(len(out.berth_rows),3)
        self.assertTrue(out.replay_completed)
        self.assertFalse(out.next_result_enabled)
        self.assertIsNone(model.show_next_preapproved_result())
        self.assertFalse(out.live_fmt025_runtime_enabled)
        self.assertFalse(out.official_draw_verified)

    def test_scenario_switch_resets_progress_and_evidence_grade(self):
        model=HiroshimaPreviewGuiModel(DATA)
        model.show_next_preapproved_result()
        model.set_scenario(OBSERVED_2026_WEST)
        history=model.render()
        self.assertEqual(history.played_count,0)
        self.assertEqual(history.qualifier_quota,7)
        self.assertEqual(len(history.match_rows),25)
        self.assertEqual(history.qualifier_count,0)
        self.assertTrue(all(x[6]=="－" for x in history.match_rows))
        self.assertIn("二次資料",history.source_note)
        self.assertIn("not_official_drawing",history.evidence_grade)
        model.set_scenario(FICTIONAL)
        self.assertEqual(model.render().played_count,0)

    def test_school_and_status_filter_are_independent(self):
        model=HiroshimaPreviewGuiModel(DATA)
        all_items=model.render()
        self.assertEqual(all_items.school_choices,("A","B","C","D"))
        self.assertEqual(len(model.render(school_filter="A").match_rows),1)
        self.assertEqual(len(model.render(school_filter="B").match_rows),1)
        self.assertEqual(len(model.render(status_filter="waiting").match_rows),1)
        self.assertEqual(len(model.render(status_filter="ready").match_rows),2)
        self.assertEqual(len(model.render(status_filter="completed").match_rows),0)
        filtered=model.render(school_filter="A",status_filter="ready")
        self.assertEqual(len(filtered.match_rows),1)
        self.assertEqual(len(filtered.school_rows),1)
        with self.assertRaises(PreviewGuiModelError):
            model.render(status_filter="unknown")
        with self.assertRaises(PreviewGuiModelError):
            model.render(school_filter="not_a_school")

    def test_completed_history_keeps_missing_scores_and_source_date(self):
        model=HiroshimaPreviewGuiModel(DATA, OBSERVED_2026_WEST)
        for _ in range(25):
            self.assertIsNotNone(model.show_next_preapproved_result())
        final=model.render()
        self.assertEqual((final.played_count,len(final.school_rows),final.qualifier_count),(25,18,7))
        self.assertTrue(final.replay_completed)
        self.assertFalse(final.next_result_enabled)
        self.assertTrue(all(row[4]=="－" for row in final.match_rows))
        self.assertTrue(all(row[8]=="二次結果日付" for row in final.match_rows))
        self.assertTrue(all(row[7]!="未定" for row in final.match_rows))
        self.assertEqual(len(final.berth_rows),7)
        self.assertTrue(all(b[1]=="県大会進出確定" for b in final.berth_rows))
        self.assertFalse(final.official_draw_verified)

    def test_historical_unplayed_match_date_hidden_from_gui(self):
        model=HiroshimaPreviewGuiModel(DATA, OBSERVED_2026_WEST)
        pending=model.render()
        self.assertEqual(len(pending.match_rows),25)
        self.assertTrue(all(x[7]=="未定" and x[8]=="日付未定" for x in pending.match_rows))

    def test_checkpoint_restore_cannot_invent_winners_or_live_status(self):
        model=HiroshimaPreviewGuiModel(DATA)
        model.show_next_preapproved_result()
        checkpoint=model.export_checkpoint()
        saved=json.loads(checkpoint)
        self.assertEqual(len(saved["applied_results"]),1)
        model.reset_preview()
        model.restore_checkpoint(checkpoint)
        self.assertEqual(model.render().played_count,1)
        bad=dict(saved)
        bad["applied_results"]=[["R1","B"]]
        with self.assertRaises(IncrementalPreviewError):
            model.restore_checkpoint(json.dumps(bad))
        self.assertEqual(model.render().played_count,1)
        bad=dict(saved)
        bad["live_fmt025_runtime_enabled"]=True
        with self.assertRaises(IncrementalPreviewError):
            model.restore_checkpoint(json.dumps(bad))

    def test_only_whitelisted_scenarios_allowed(self):
        self.assertEqual(len(SCENARIOS),2)
        with self.assertRaises(PreviewGuiModelError):
            HiroshimaPreviewGuiModel(DATA, "2027_autumn_west_official")
        with self.assertRaises(PreviewGuiModelError):
            HiroshimaPreviewGuiModel(DATA, "all_auto_generated")

    def test_read_model_does_not_write_sqlite_or_make_simulated_scores(self):
        source=(ROOT/"phase2_engine/hiroshima_stage13e3g35_preview_gui_model.py").read_text(encoding="utf-8")
        self.assertNotIn("BrowseRepository(",source)
        self.assertNotIn("sqlite3.connect(",source)
        self.assertNotIn("team1_score = random",source)
        self.assertIn("record_preapproved_match_result(",source)
        out=HiroshimaPreviewGuiModel(DATA).render()
        self.assertTrue(all(item[4]=="－" for item in out.match_rows))

    def test_existing_gui_has_separate_pilot_button_and_keeps_old_tabs(self):
        source=(ROOT/"phase2_engine/browse_gui_stage13d3.py").read_text(encoding="utf-8")
        self.assertTrue(issubclass(Stage13D3BrowseApp,object))
        self.assertIn('text="予選進行プレビュー（試験・別画面）"',source)
        self.assertIn("def _open_hiroshima_preview_pilot(",source)
        self.assertIn("open_hiroshima_preview_window(self.root, self.model.data_dir)",source)
        self.assertIn('text="この大会の個人成績ランキング"',source)
        self.assertIn('text="個人成績ランキング"',source)

    def test_tk_window_has_dedicated_tabs_and_read_only_controls(self):
        source=(ROOT/"phase2_engine/hiroshima_stage13e3g35_preview_gui.py").read_text(encoding="utf-8")
        self.assertIn("class HiroshimaPreviewWindow:",source)
        self.assertIn('text="大会別・試合進行"',source)
        self.assertIn('text="学校別戦績"',source)
        self.assertIn('text="県大会進出確定"',source)
        self.assertIn('text="既登録の次の結果を表示"',source)
        self.assertIn("status_filter=status, school_filter=school,",source)
        self.assertIn("school_query=self.school_search_var.get(),",source)
        self.assertIn("def _choose_selected_school(",source)
        self.assertIn("def _choose_selected_berth(",source)
        self.assertIn("root.withdraw()",source)
        self.assertIn("self.window = tk.Toplevel(parent)",source)

    def test_standalone_headless_parser_does_not_require_sqlite(self):
        parser=build_parser()
        args=parser.parse_args(["--data-dir","data","--headless","--scenario",FICTIONAL,"--steps","2"])
        self.assertTrue(args.headless)
        self.assertEqual(args.steps,2)
        self.assertEqual(args.scenario,FICTIONAL)
        self.assertIn("予選進行プレビュー",APP_TITLE)
        self.assertIn("completed",STATUS_LABELS)

    def test_bad_secondary_source_refuses_to_render_gui(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"data"
            shutil.copytree(DATA,root)
            fixture=root/"research/2026/hiroshima_fmt025_preflight_example_observed_2026_autumn_west_stage13e3g32.json"
            src=json.loads(fixture.read_text(encoding="utf-8"))
            src["year"]=2025
            fixture.write_text(json.dumps(src,ensure_ascii=False),encoding="utf-8")
            with self.assertRaises(ValueError):
                HiroshimaPreviewGuiModel(root,OBSERVED_2026_WEST)


if __name__ == "__main__":
    unittest.main()
