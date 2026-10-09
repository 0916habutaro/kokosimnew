from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from phase2_engine.browse_gui_stage13d3 import Stage13D3BrowseApp
from phase2_engine.hiroshima_stage13e3g35_preview_gui import (
    HiroshimaPreviewWindow, open_hiroshima_preview_window,
)
from phase2_engine.hiroshima_stage13e3g35_preview_gui_model import (
    FICTIONAL, OBSERVED_2026_WEST, HiroshimaPreviewGuiModel,
    PreviewGuiModelError,
)
from phase2_engine.hiroshima_stage13e3g39_school_master import (
    load_2026_hiroshima_west_school_links_stage39,
)
from phase2_engine.hiroshima_stage13e3g40_school_browse_handoff import (
    TARGET_YEAR, SchoolBrowseHandoff, SOURCE_NOTE,
    preflight_2026_west_school_browse_handoff,
)
from phase2_engine.hiroshima_stage13e3g40 import audit_2026_hiroshima_stage13e3g40

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"


class FakeVar:
    def __init__(self,value=""):
        self.value=value
    def set(self,val):
        self.value=val
    def get(self):
        return self.value


class FakeSchoolTree:
    def __init__(self):
        self.ids=()
        self.selected=()
        self.focused=None
        self.values=()
    def get_children(self):
        return self.ids
    def selection_set(self,val):
        self.selected=(val,)
    def focus(self,val):
        self.focused=val
    def selection(self):
        return self.selected
    def item(self,iid,key):
        if key=="values":
            return self.values
        raise ValueError(key)


def populate_db(db, rows, *, tables=True):
    with sqlite3.connect(db) as conn:
        if tables:
            conn.execute(
                "CREATE TABLE school_records ("
                "year INTEGER, school_id TEXT, prefecture_code TEXT)"
            )
            conn.executemany(
                "INSERT INTO school_records VALUES (?,?,?)",rows,
            )


def get_link(name="山陽"):
    return load_2026_hiroshima_west_school_links_stage39(DATA).links[name]


def fake_existing_gui(db, year="2026"):
    """Use actual Stage13D3 navigation callback without a Tk display."""
    app=object.__new__(Stage13D3BrowseApp)
    app.model=SimpleNamespace(data_dir=DATA,db_path=db)
    app.year_var=FakeVar(year)
    app.school_search_var=FakeVar("")
    app.prefecture_var=FakeVar("")
    app.status_var=FakeVar("")
    app.school_tree=FakeSchoolTree()
    app.school_tab=object()
    app.notebook=MagicMock()
    app._current_year=lambda: int(app.year_var.get()) if app.year_var.get() else None
    app._search_schools=MagicMock(side_effect=lambda: setattr(
        app.school_tree,"ids",(get_link().school_id,)
        if app.prefecture_var.get()=="34" and app.school_search_var.get()==get_link().school_id
        else (),
    ))
    app._load_selected_school=MagicMock()
    return app


class Stage13E3G40SafeSchoolBrowseTests(unittest.TestCase):
    def test_integrated_real_18_school_probe_and_official_safety(self):
        report=audit_2026_hiroshima_stage13e3g40(DATA)
        self.assertTrue(report["ok"],report["errors"])
        self.assertEqual(report["handoff"]["verified_preview_schools"],18)
        self.assertEqual(report["handoff"]["exact_2026_school_id_passing_synthetic_sqlite_probe"],18)
        self.assertTrue(report["handoff"]["wrong_year_refused"])
        self.assertTrue(report["handoff"]["missing_db_not_created"])
        self.assertFalse(report["native_tk_window_visual_checked"])
        self.assertFalse(report["2026_historical_qualifier_results_inserted"])
        self.assertEqual(report["2026_official_8_group_routes_unresolved"],48)
        self.assertFalse(report["production_fmt025_runtime_enabled"])

    def test_exact_school_id_prefecture_and_2026_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"browse.sqlite3"
            link=get_link("山陽")
            populate_db(db,[(2026,link.school_id,"34")])
            out=preflight_2026_west_school_browse_handoff(
                db,link,selected_browse_year=2026,
            )
            self.assertTrue(out.allowed,out.reason)
            self.assertEqual(out.school_id,"SCH001774")
            self.assertEqual(out.observed_name,"山陽")
            self.assertEqual(out.year,2026)
            self.assertIn("史実25試合と合算されません",out.source_note)
            self.assertFalse(out.added_qualifier_history_to_sqlite)
            self.assertFalse(out.official_2026_qualification_graph_verified)

    def test_missing_sqlite_cannot_be_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"nonexistent.sqlite3"
            route=preflight_2026_west_school_browse_handoff(
                db,get_link(),selected_browse_year=2026,
            )
            self.assertFalse(route.allowed)
            self.assertFalse(db.exists())
            self.assertIn("存在しません",route.reason)

    def test_wrong_year_never_falls_back_to_other_season(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"browse.sqlite3"
            populate_db(db,[(2025,get_link().school_id,"34"),
                            (2027,get_link().school_id,"34")])
            for year in (2025,2027,None,True,"2026"):
                result=preflight_2026_west_school_browse_handoff(
                    db,get_link(),selected_browse_year=year,
                )
                self.assertFalse(result.allowed)
                self.assertIn("2026年",result.reason)
            result=preflight_2026_west_school_browse_handoff(
                db,get_link(),selected_browse_year=2026,
            )
            self.assertFalse(result.allowed)
            self.assertIn("一意に存在しません",result.reason)

    def test_wrong_prefecture_or_other_id_cannot_navigate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"browse.sqlite3"
            populate_db(db,[(2026,get_link().school_id,"35"),
                            (2026,"SCH001775","34")])
            result=preflight_2026_west_school_browse_handoff(
                db,get_link(),selected_browse_year=2026,
            )
            self.assertFalse(result.allowed)
            self.assertIn("広島県コード",result.reason)

    def test_duplicate_records_are_refused_even_if_schema_would_allow_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"browse.sqlite3"
            populate_db(db,[(2026,get_link().school_id,"34")]*2)
            result=preflight_2026_west_school_browse_handoff(
                db,get_link(),selected_browse_year=2026,
            )
            self.assertFalse(result.allowed)
            self.assertIn("一意",result.reason)

    def test_missing_school_records_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"browse.sqlite3"
            populate_db(db,[],tables=False)
            result=preflight_2026_west_school_browse_handoff(
                db,get_link(),selected_browse_year=2026,
            )
            self.assertFalse(result.allowed)
            self.assertIn("テーブル",result.reason)

    def test_fake_or_unapproved_link_fails(self):
        link=get_link("山陽")
        for replacement in (
            {"authorized_for_read_only_detail":False},
            {"prefecture_code":"35"},
            {"school_id":"ABCD"},
            {"program_id":""},
            {"official_name":""},
            {"official_2026_draw_verified":True},
            {"live_fmt025_runtime_enabled":True},
        ):
            candidate=replace(link,**replacement)
            route=preflight_2026_west_school_browse_handoff(
                "not-even-a-file",candidate,selected_browse_year=2026,
            )
            self.assertFalse(route.allowed)
            self.assertIn("照合",route.reason)
        with self.assertRaises(TypeError):
            preflight_2026_west_school_browse_handoff(
                "file",{"school_id":"SCH001774"},selected_browse_year=2026,
            )

    def test_existing_gui_callback_navigates_exact_school_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"browse.sqlite3"
            link=get_link()
            populate_db(db,[(2026,link.school_id,"34")])
            app=fake_existing_gui(db)
            before=db.read_bytes()
            route=app._navigate_from_hiroshima_preview(link)
            self.assertTrue(route.allowed,route.reason)
            self.assertEqual(app.school_search_var.get(),link.school_id)
            self.assertEqual(app.prefecture_var.get(),"34")
            self.assertEqual(app.school_tree.selection(),(link.school_id,))
            self.assertEqual(app.school_tree.focused,link.school_id)
            app._load_selected_school.assert_called_once()
            app.notebook.select.assert_called_once_with(app.school_tab)
            self.assertIn("二次史実25試合と合算しません",app.status_var.get())
            self.assertEqual(db.read_bytes(),before)

    def test_existing_gui_blocked_when_year_other_than_2026(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"browse.sqlite3"
            populate_db(db,[(2026,get_link().school_id,"34")])
            app=fake_existing_gui(db,year="2025")
            route=app._navigate_from_hiroshima_preview(get_link())
            self.assertFalse(route.allowed)
            self.assertEqual(app.year_var.get(),"2025")
            app._search_schools.assert_not_called()
            app._load_selected_school.assert_not_called()
            app.notebook.select.assert_not_called()

    def test_parent_revalidates_link_from_stage39_before_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"browse.sqlite3"
            populate_db(db,[(2026,get_link().school_id,"34")])
            app=fake_existing_gui(db)
            spoof=replace(get_link(),official_name="別の学校")
            route=app._navigate_from_hiroshima_preview(spoof)
            self.assertFalse(route.allowed)
            app._load_selected_school.assert_not_called()

    def test_not_in_gui_search_results_cannot_select_other_school(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"browse.sqlite3"
            populate_db(db,[(2026,get_link().school_id,"34")])
            app=fake_existing_gui(db)
            app._search_schools=MagicMock(side_effect=lambda: setattr(app.school_tree,"ids",()))
            route=app._navigate_from_hiroshima_preview(get_link())
            self.assertFalse(route.allowed)
            app.notebook.select.assert_not_called()
            app._load_selected_school.assert_not_called()

    def test_standalone_pilot_has_no_scored_sqlite_handoff(self):
        source=(ROOT/"phase2_engine/hiroshima_stage13e3g35_preview_gui.py").read_text(encoding="utf-8")
        self.assertIn('state="normal" if self.on_navigate_verified_school else "disabled"',source)
        self.assertIn("def _navigate_to_existing_school_browse(",source)
        self.assertIn("on_navigate_verified_school=on_navigate_verified_school",source)
        self.assertIn("2026年のみ",source)

    def test_preview_only_verified_visible_school_can_invoke_handoff(self):
        pilot=HiroshimaPreviewGuiModel(DATA,OBSERVED_2026_WEST)
        for _ in range(25):
            pilot.show_next_preapproved_result()
        link=pilot.get_verified_school_master_detail("山陽")
        self.assertEqual(link.school_id,get_link("山陽").school_id)
        fictitious=HiroshimaPreviewGuiModel(DATA,FICTIONAL)
        with self.assertRaises(PreviewGuiModelError):
            fictitious.get_verified_school_master_detail("A")

    def test_preview_callback_without_native_tk_receives_validated_identity(self):
        pilot=HiroshimaPreviewGuiModel(DATA,OBSERVED_2026_WEST)
        for _ in range(25):
            pilot.show_next_preapproved_result()
        link=pilot.get_verified_school_master_detail("山陽")
        mock_call=MagicMock(return_value=SchoolBrowseHandoff(
            allowed=True,reason="OK",year=2026,school_id=link.school_id,
            observed_name=link.observed_name,official_name=link.official_name,
        ))
        window=object.__new__(HiroshimaPreviewWindow)
        window.model=pilot
        window.on_navigate_verified_school=mock_call
        window.school_tree=FakeSchoolTree()
        window.school_tree.selected=("row-1",)
        window.school_tree.values=("山陽",)
        window.last_action_var=FakeVar()
        window.window=None
        window._navigate_to_existing_school_browse()
        mock_call.assert_called_once_with(link)
        self.assertIn("史実とは別データ",window.last_action_var.get())

    def test_unknown_or_unavailable_preview_navigation_never_calls_parent(self):
        pilot=HiroshimaPreviewGuiModel(DATA,FICTIONAL)
        mock_call=MagicMock()
        window=object.__new__(HiroshimaPreviewWindow)
        window.model=pilot
        window.on_navigate_verified_school=mock_call
        window.school_tree=FakeSchoolTree()
        window.school_tree.selected=("row-1",)
        window.school_tree.values=("A",)
        window.last_action_var=FakeVar()
        window.window=None
        with patch("phase2_engine.hiroshima_stage13e3g35_preview_gui.messagebox.showwarning"):
            window._navigate_to_existing_school_browse()
        mock_call.assert_not_called()
        self.assertIn("検証に失敗",window.last_action_var.get())


if __name__=="__main__":
    unittest.main()
