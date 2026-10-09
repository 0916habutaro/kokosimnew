"""Stage36: headless Tk callback harness + search/navigation/replay checks."""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g35_preview_gui import (
    HiroshimaPreviewWindow, SCHOOL_ALL, STATUS_ALL, main,
)
from phase2_engine.hiroshima_stage13e3g35_preview_gui_model import (
    FICTIONAL, OBSERVED_2026_WEST, SCENARIOS, HiroshimaPreviewGuiModel,
    PreviewGuiModelError,
)

DATA=Path(__file__).resolve().parents[1]/"data"


class FakeVar:
    def __init__(self,value=""):
        self.value=value
    def get(self):
        return self.value
    def set(self,value):
        self.value=value


class FakeTree:
    def __init__(self):
        self.items={}
        self.selected=()
        self.next_id=0
    @property
    def rows(self):
        return list(self.items.values())
    def get_children(self):
        return tuple(self.items)
    def delete(self,iid):
        self.items.pop(iid)
    def insert(self,parent,position,values):
        iid=f"item-{self.next_id}"
        self.next_id+=1
        self.items[iid]=tuple(values)
    def selection(self):
        return self.selected
    def item(self,iid,field):
        if field=="values":
            return self.items[iid]
        raise ValueError(field)
    def choose(self,index):
        self.selected=(list(self.items)[index],)


class FakeCombo:
    def __init__(self):
        self.values={}
    def __setitem__(self,key,val):
        self.values[key]=val


class FakeButton:
    def __init__(self):
        self.state=None
    def configure(self,**kw):
        if "state" in kw:
            self.state=kw["state"]


class FakeNotebook:
    def __init__(self):
        self.selected=None
    def select(self,index):
        self.selected=index


def fake_pilot(scenario=FICTIONAL):
    """Drive actual Tk callback methods without opening a native window."""
    ui=object.__new__(HiroshimaPreviewWindow)
    ui.model=HiroshimaPreviewGuiModel(DATA,scenario)
    ui.window=None
    ui._scenario_by_label={label:key for key,label in SCENARIOS}
    ui._label_by_scenario={key:label for key,label in SCENARIOS}
    ui.scenario_var=FakeVar(ui._label_by_scenario[scenario])
    ui.filter_var=FakeVar(STATUS_ALL)
    ui.school_var=FakeVar(SCHOOL_ALL)
    ui.school_search_var=FakeVar("")
    ui.summary_var=FakeVar("")
    ui.source_var=FakeVar("")
    ui.evidence_var=FakeVar("")
    ui.last_action_var=FakeVar("")
    ui.school_combo=FakeCombo()
    ui.next_button=FakeButton()
    ui.match_tree=FakeTree()
    ui.school_tree=FakeTree()
    ui.berth_tree=FakeTree()
    ui.notebook=FakeNotebook()
    ui._render()
    return ui


class Stage13E3G36PilotNavigationTests(unittest.TestCase):
    def test_initial_gui_callback_populates_three_independent_tabs(self):
        ui=fake_pilot()
        self.assertEqual(len(ui.match_tree.rows),3)
        self.assertEqual(len(ui.school_tree.rows),4)
        self.assertEqual(len(ui.berth_tree.rows),0)
        self.assertEqual(ui.next_button.state,"normal")
        self.assertIn("全3試合",ui.summary_var.get())
        self.assertIn("架空",ui.source_var.get())

    def test_click_specific_ready_p2_before_p1(self):
        ui=fake_pilot()
        ui.match_tree.choose(1)
        ui._show_selected_result()
        self.assertEqual(ui.model.snapshot.checkpoint.applied_results,(("P2","C"),))
        self.assertEqual(len(ui.berth_tree.rows),1)
        self.assertEqual(ui.berth_tree.rows[0],("C","県大会進出確定","P2"))
        self.assertIn("P2",ui.last_action_var.get())
        self.assertIn("結果確定1",ui.summary_var.get())

    def test_cannot_select_unready_repechage(self):
        model=HiroshimaPreviewGuiModel(DATA)
        with self.assertRaises(PreviewGuiModelError):
            model.show_preapproved_result_for_match("R1")
        self.assertEqual(model.render().played_count,0)
        model.show_preapproved_result_for_match("P2")
        with self.assertRaises(PreviewGuiModelError):
            model.show_preapproved_result_for_match("P2")
        with self.assertRaises(PreviewGuiModelError):
            model.show_preapproved_result_for_match("NEVER")
        self.assertEqual(model.render().played_count,1)

    def test_school_search_finds_only_visible_names(self):
        ui=fake_pilot()
        ui.school_search_var.set("b")
        ui._search_schools()
        self.assertEqual(ui.school_var.get(),"B")
        self.assertEqual(ui.school_combo.values["values"],(SCHOOL_ALL,"B"))
        self.assertEqual(len(ui.school_tree.rows),1)
        self.assertEqual(len(ui.match_tree.rows),1)
        self.assertEqual(ui.match_tree.rows[0][0],"P1")
        self.assertEqual(len(ui.berth_tree.rows),0)

    def test_school_query_matches_multiple_entrants_and_filters_all_tabs(self):
        model=HiroshimaPreviewGuiModel(DATA)
        self.assertEqual(model.search_visible_school_ids(""),("A","B","C","D"))
        self.assertEqual(model.search_visible_school_ids("a"),("A",))
        out=model.render(school_query="a")
        self.assertEqual(len(out.match_rows),1)
        self.assertEqual(len(out.school_rows),1)
        self.assertEqual(out.berth_rows,())
        self.assertEqual(model.render(school_query="unmatched").match_rows,())
        self.assertEqual(model.render(school_query="unmatched").school_rows,())
        with self.assertRaises(PreviewGuiModelError):
            model.search_visible_school_ids(123)
        with self.assertRaises(PreviewGuiModelError):
            model.search_visible_school_ids("a"*101)

    def test_search_not_found_displays_empty_rows_not_all(self):
        ui=fake_pilot()
        ui.school_search_var.set("ZZ_UNKNOWN")
        ui._search_schools()
        self.assertEqual(ui.school_combo.values["values"],(SCHOOL_ALL,))
        self.assertEqual(ui.match_tree.rows,[])
        self.assertEqual(ui.school_tree.rows,[])
        self.assertEqual(ui.berth_tree.rows,[])
        self.assertIn("検索結果: 0校",ui.last_action_var.get())

    def test_clear_filters_restores_all_and_keeps_replayed_state(self):
        ui=fake_pilot()
        ui._show_next_result()
        ui.school_search_var.set("no match")
        ui._search_schools()
        self.assertEqual(len(ui.match_tree.rows),0)
        ui._clear_filters()
        self.assertEqual(ui.school_search_var.get(),"")
        self.assertEqual(ui.school_var.get(),SCHOOL_ALL)
        self.assertEqual(len(ui.match_tree.rows),3)
        self.assertEqual(len(ui.berth_tree.rows),1)
        self.assertEqual(ui.model.render().played_count,1)

    def test_school_to_match_navigation_works_after_search_is_active(self):
        ui=fake_pilot()
        ui.school_search_var.set("A")
        ui._search_schools()
        ui.school_var.set(SCHOOL_ALL)
        ui._clear_filters()
        ui.school_tree.choose(1)
        ui._choose_selected_school()
        self.assertEqual(ui.school_var.get(),"B")
        self.assertEqual(ui.notebook.selected,0)
        self.assertEqual([r[0] for r in ui.match_tree.rows],["P1"])

    def test_match_double_click_opens_school_record_without_unknown_team(self):
        ui=fake_pilot()
        ui.match_tree.choose(0)
        ui._choose_match_first_school()
        self.assertEqual(ui.school_var.get(),"A")
        self.assertEqual(ui.notebook.selected,1)
        self.assertEqual(len(ui.school_tree.rows),1)
        ui._clear_filters()
        ui.match_tree.choose(2)
        ui._choose_match_first_school()
        self.assertEqual(ui.school_var.get(),SCHOOL_ALL)

    def test_berth_to_match_navigation_and_search_reset(self):
        ui=fake_pilot()
        ui._show_next_result()
        ui.school_search_var.set("NO_MATCH")
        ui._search_schools()
        ui._clear_filters()
        ui.berth_tree.choose(0)
        ui._choose_selected_berth()
        self.assertEqual(ui.school_var.get(),"A")
        self.assertEqual(ui.notebook.selected,0)
        self.assertEqual(ui.match_tree.rows[0][0],"P1")

    def test_scenario_switch_clears_search_and_replayed_results(self):
        ui=fake_pilot()
        ui._show_next_result()
        ui.school_search_var.set("A")
        ui.school_var.set("A")
        ui.scenario_var.set(ui._label_by_scenario[OBSERVED_2026_WEST])
        ui._change_scenario()
        self.assertEqual(ui.model.scenario_id,OBSERVED_2026_WEST)
        self.assertEqual(ui.school_search_var.get(),"")
        self.assertEqual(ui.school_var.get(),SCHOOL_ALL)
        self.assertEqual(ui.model.render().played_count,0)
        self.assertEqual(len(ui.match_tree.rows),25)
        self.assertIn("二次資料",ui.source_var.get())

    def test_stale_school_selection_is_reset_before_revalidated_render(self):
        ui=fake_pilot()
        ui.school_var.set("NOT_PRESENT")
        ui._render()
        self.assertEqual(ui.school_var.get(),SCHOOL_ALL)
        self.assertEqual(len(ui.match_tree.rows),3)

    def test_history_search_limits_to_visible_registered_schools(self):
        model=HiroshimaPreviewGuiModel(DATA,OBSERVED_2026_WEST)
        self.assertEqual(model.search_visible_school_ids("未来に出る学校"),())
        self.assertEqual(model.render(school_query="未来に出る学校").match_rows,())
        model.show_next_preapproved_result()
        self.assertFalse(model.render().official_draw_verified)
        self.assertFalse(model.render().live_fmt025_runtime_enabled)

    def test_headless_cli_status_and_search_options(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            status=main(["--data-dir",str(DATA),"--headless","--scenario","fictional",
                         "--steps","1","--school-query","A","--status","completed"])
        self.assertEqual(status,0)
        data=json.loads(output.getvalue())
        self.assertEqual(data["played"],1)
        self.assertEqual(data["qualifiers"],1)
        self.assertEqual(data["school_query"],"A")
        self.assertEqual(data["status_filter"],"completed")
        self.assertEqual(len(data["matches"]),1)
        self.assertEqual(len(data["schools"]),1)
        self.assertEqual(len(data["berths"]),1)
        self.assertFalse(data["live_fmt025_runtime_enabled"])

    def test_selected_p2_then_ready_p1_still_cannot_skip_r1(self):
        model=HiroshimaPreviewGuiModel(DATA)
        model.show_preapproved_result_for_match("P2")
        with self.assertRaises(PreviewGuiModelError):
            model.show_preapproved_result_for_match("R1")
        model.show_preapproved_result_for_match("P1")
        self.assertIn("R1",model.snapshot.ready_match_ids)
        model.show_preapproved_result_for_match("R1")
        final=model.render()
        self.assertEqual(final.qualifier_count,3)
        self.assertTrue(final.replay_completed)
        self.assertFalse(final.official_draw_verified)
        self.assertFalse(final.live_fmt025_runtime_enabled)


if __name__=="__main__":
    unittest.main()
