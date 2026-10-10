"""Stage41: headless tests of real Tk browse/preview navigation callbacks."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from phase2_engine.browse_gui_stage13d3 import Stage13D3BrowseApp
from phase2_engine.browse_gui_stage12u import Stage12UBrowseApp
from phase2_engine.hiroshima_stage13e3g35_preview_gui import (
    HiroshimaPreviewWindow,
)
from phase2_engine.hiroshima_stage13e3g39_school_master import (
    load_2026_hiroshima_west_school_links_stage39,
)
from phase2_engine.hiroshima_stage13e3g40_school_browse_handoff import (
    preflight_2026_west_school_browse_handoff,
)

DATA=Path(__file__).resolve().parents[1]/"data"


class State:
    def __init__(self,value=""):
        self.value=value
    def set(self,value):
        self.value=value
    def get(self):
        return self.value


class FakeSchoolTree:
    def __init__(self):
        self.children=()
        self.selected=()
        self.current_focus=""
    def get_children(self):
        return self.children
    def selection_set(self,id):
        self.selected=(id,)
    def focus(self,id):
        self.current_focus=id


def school(name="山陽"):
    return load_2026_hiroshima_west_school_links_stage39(DATA).links[name]


def make_sqlite(db, ids):
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE school_records(year INTEGER,school_id TEXT,prefecture_code TEXT)")
        con.executemany(
            "INSERT INTO school_records VALUES (?,?,?)",
            [(2026,sid,"34") for sid in ids],
        )


def fake_parent(db, year="2026", window=None):
    obj=object.__new__(Stage13D3BrowseApp)
    obj.model=SimpleNamespace(db_path=db,data_dir=DATA)
    obj.year_var=State(year)
    obj.school_search_var=State("")
    obj.prefecture_var=State("")
    obj.status_var=State("")
    obj.school_tree=FakeSchoolTree()
    obj.school_tab=object()
    obj.notebook=MagicMock()
    obj.root=MagicMock()
    obj.preview_return_button=MagicMock()
    obj.school_preview_return_button=MagicMock()
    obj._hiroshima_preview_return_school_id=""
    obj._hiroshima_preview_window=(
        SimpleNamespace(window=window) if window is not None else None
    )
    obj._search_schools=MagicMock(
        side_effect=lambda: setattr(
            obj.school_tree,"children",(school().school_id,)
            if obj.school_search_var.get()==school().school_id
            and obj.prefecture_var.get()=="34" else (),
        )
    )
    obj._load_selected_school=MagicMock()
    return obj


class Stage13E3G41NavigationPolishTests(unittest.TestCase):
    def test_successful_handoff_activates_return_in_both_parent_tabs(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"browse.sqlite3"
            make_sqlite(db,[school().school_id])
            window=MagicMock()
            window.winfo_exists.return_value=1
            obj=fake_parent(db,window=window)
            result=obj._navigate_from_hiroshima_preview(school())
            self.assertTrue(result.allowed,result.reason)
            self.assertEqual(obj._hiroshima_preview_return_school_id,school().school_id)
            obj.preview_return_button.configure.assert_called_with(state="normal")
            obj.school_preview_return_button.configure.assert_called_with(state="normal")
            obj.notebook.select.assert_called_once_with(obj.school_tab)
            obj.root.lift.assert_called_once()
            obj.root.focus_set.assert_called_once()
            self.assertEqual(obj.year_var.get(),"2026")

    def test_return_reuses_same_pilot_and_preserves_its_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"browse.sqlite3"
            make_sqlite(db,[school().school_id])
            window=MagicMock()
            window.winfo_exists.return_value=1
            obj=fake_parent(db,window=window)
            obj._navigate_from_hiroshima_preview(school())
            self.assertTrue(obj._return_to_hiroshima_preview())
            window.deiconify.assert_called_once()
            window.lift.assert_called_once()
            window.focus_set.assert_called_once()
            self.assertIs(obj._hiroshima_preview_window.window,window)
            self.assertIn("史実はSQLiteのゲーム戦績と別",obj.status_var.get())

    def test_closed_pilot_disables_all_return_buttons(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"browse.sqlite3"
            window=MagicMock()
            window.winfo_exists.return_value=0
            obj=fake_parent(db,window=window)
            obj._hiroshima_preview_return_school_id="SCH001774"
            self.assertFalse(obj._return_to_hiroshima_preview())
            self.assertIsNone(obj._hiroshima_preview_window)
            self.assertEqual(obj._hiroshima_preview_return_school_id,"")
            obj.preview_return_button.configure.assert_called_with(state="disabled")
            obj.school_preview_return_button.configure.assert_called_with(state="disabled")
            window.lift.assert_not_called()

    def test_parent_year_change_revokes_return_without_switching_year(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"browse.sqlite3"
            make_sqlite(db,[school().school_id])
            window=MagicMock()
            window.winfo_exists.return_value=1
            obj=fake_parent(db,window=window)
            obj._navigate_from_hiroshima_preview(school())
            obj.year_var.set("2025")
            with patch.object(Stage12UBrowseApp,"_on_year_changed",return_value=None):
                obj._on_year_changed()
            self.assertEqual(obj.year_var.get(),"2025")
            self.assertEqual(obj._hiroshima_preview_return_school_id,"")
            obj.preview_return_button.configure.assert_called_with(state="disabled")
            obj.school_preview_return_button.configure.assert_called_with(state="disabled")
            denied=obj._navigate_from_hiroshima_preview(school())
            self.assertFalse(denied.allowed)
            self.assertEqual(obj.year_var.get(),"2025")
            obj.notebook.select.assert_called_once()

    def test_missing_searched_school_restores_prior_filters_atomically(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"browse.sqlite3"
            make_sqlite(db,[school().school_id])
            obj=fake_parent(db)
            obj.school_search_var.set("以前の検索")
            obj.prefecture_var.set("35")
            obj._search_schools=MagicMock(
                side_effect=lambda: setattr(obj.school_tree,"children",())
            )
            result=obj._navigate_from_hiroshima_preview(school())
            self.assertFalse(result.allowed)
            self.assertEqual(obj.school_search_var.get(),"以前の検索")
            self.assertEqual(obj.prefecture_var.get(),"35")
            self.assertEqual(obj._search_schools.call_count,2)
            obj.notebook.select.assert_not_called()
            obj._load_selected_school.assert_not_called()

    def test_sqlite_error_while_searching_restores_filters(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"browse.sqlite3"
            make_sqlite(db,[school().school_id])
            obj=fake_parent(db)
            obj.school_search_var.set("before")
            obj.prefecture_var.set("01")
            calls=[0]
            def fail_once():
                calls[0]+=1
                if calls[0]==1:
                    raise ValueError("temporary bad browse school query")
            obj._search_schools=MagicMock(side_effect=fail_once)
            with self.assertRaisesRegex(ValueError,"bad browse"):
                obj._navigate_from_hiroshima_preview(school())
            self.assertEqual(obj.school_search_var.get(),"before")
            self.assertEqual(obj.prefecture_var.get(),"01")
            self.assertEqual(obj._search_schools.call_count,2)
            obj.notebook.select.assert_not_called()

    def test_reopening_preview_when_open_reuses_window(self):
        with tempfile.TemporaryDirectory() as root:
            obj=fake_parent(Path(root)/"nonexistent.sqlite3")
            window=MagicMock()
            window.winfo_exists.return_value=1
            pilot=SimpleNamespace(window=window)
            obj._hiroshima_preview_window=pilot
            with patch(
                "phase2_engine.hiroshima_stage13e3g35_preview_gui.open_hiroshima_preview_window"
            ) as spawn:
                obj._open_hiroshima_preview_pilot()
            spawn.assert_not_called()
            self.assertIs(obj._hiroshima_preview_window,pilot)
            window.lift.assert_called_once()

    def test_launching_new_preview_does_not_enable_return_before_school_handoff(self):
        with tempfile.TemporaryDirectory() as root:
            obj=fake_parent(Path(root)/"nonexistent.sqlite3")
            newpilot=SimpleNamespace(window=MagicMock())
            with patch(
                "phase2_engine.hiroshima_stage13e3g35_preview_gui.open_hiroshima_preview_window",
                return_value=newpilot,
            ) as spawn:
                obj._open_hiroshima_preview_pilot()
            self.assertIs(obj._hiroshima_preview_window,newpilot)
            self.assertIs(spawn.call_args.kwargs["on_navigate_verified_school"].__self__,obj)
            obj.preview_return_button.configure.assert_called_with(state="disabled")
            obj.school_preview_return_button.configure.assert_called_with(state="disabled")

    def test_preview_return_has_no_sqlite_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"browse.sqlite3"
            make_sqlite(db,[school().school_id])
            before=db.read_bytes()
            window=MagicMock()
            window.winfo_exists.return_value=1
            obj=fake_parent(db,window=window)
            obj._navigate_from_hiroshima_preview(school())
            self.assertTrue(obj._return_to_hiroshima_preview())
            self.assertEqual(db.read_bytes(),before)

    def test_no_database_still_gives_clear_reason_without_changing_filters(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"missing.sqlite3"
            obj=fake_parent(db)
            obj.school_search_var.set("検索中")
            obj.prefecture_var.set("01")
            result=obj._navigate_from_hiroshima_preview(school())
            self.assertFalse(result.allowed)
            self.assertIn("存在しません",result.reason)
            self.assertFalse(db.exists())
            self.assertEqual(obj.school_search_var.get(),"検索中")
            self.assertEqual(obj.prefecture_var.get(),"01")
            obj._search_schools.assert_not_called()

    def test_parent_focus_not_called_when_window_closed(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"browse.sqlite3"
            make_sqlite(db,[school().school_id])
            window=MagicMock()
            window.winfo_exists.return_value=0
            obj=fake_parent(db,window=window)
            result=obj._navigate_from_hiroshima_preview(school())
            self.assertTrue(result.allowed)
            obj.root.lift.assert_not_called()
            obj.preview_return_button.configure.assert_not_called()
            obj.notebook.select.assert_called_once_with(obj.school_tab)

    def test_no_readonly_navigation_for_spoofed_other_master_identity(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"browse.sqlite3"
            make_sqlite(db,[school().school_id])
            obj=fake_parent(db,window=MagicMock())
            forged=replace(school(),official_name="別の学校")
            result=obj._navigate_from_hiroshima_preview(forged)
            self.assertFalse(result.allowed)
            obj.notebook.select.assert_not_called()
            obj.preview_return_button.configure.assert_not_called()

    def test_parent_screen_contains_return_in_both_school_and_competition_tabs(self):
        source=(ROOT/"phase2_engine/browse_gui_stage13d3.py").read_text(encoding="utf-8")
        self.assertIn("self.school_preview_return_button",source)
        self.assertIn("self.preview_return_button",source)
        self.assertIn("self._set_preview_return_enabled(True)",source)
        self.assertIn("def _on_year_changed(self, _event=None)",source)
        self.assertIn("def _return_to_hiroshima_preview(self)",source)
        self.assertIn("prior_search = self.school_search_var.get()",source)


if __name__=="__main__":
    unittest.main()
