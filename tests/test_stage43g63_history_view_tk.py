"""Stage43G-63: real Tk history browsing and source-only Japanese view."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
import tkinter as tk
import unittest

from phase2_engine.career_history_gui_bridge import CareerHistoryGuiBridge
from phase2_engine.career_history_view_projection import (
    CareerHistoryViewConflict, project_history_screen,
)
from phase2_engine.career_history_tk_pilot import CareerHistoryTkPilot
import test_stage43g31_cross_era_browse_model as stage31

DISPLAY = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G63HistoryGuiTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage31.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.bridge = CareerHistoryGuiBridge(self.fixture.root)

    def _hashes(self):
        return {
            f.name: sha256(f.read_bytes()).hexdigest()
            for f in Path(self.fixture.root).glob("*.sqlite3*")
            if f.is_file()
        }

    def _gui(self, size=24):
        if not DISPLAY:
            self.skipTest("requires Tk / Xvfb")
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        gui = CareerHistoryTkPilot(
            root, CareerHistoryGuiBridge(
                self.fixture.root, year_page_size=size,
            ), school_id=self.fixture.a,
        )
        root.update_idletasks()
        return gui

    @staticmethod
    def _select(gui, predicate):
        item = next(
            wid for wid, row in gui.rows_by_widget_id.items()
            if predicate(row)
        )
        gui.tree.selection_set(item)
        gui.open_button.invoke()

    def test_candidate_years_source_separated_and_no_write(self):
        before = self._hashes()
        view = project_history_screen(self.bridge.page)
        self.assertEqual("history_year_catalog", view["screen"])
        self.assertTrue(view["show_saved_candidate_warning"])
        self.assertEqual([10000, 2026], [
            x["year"] for x in view["rows"]
        ])
        self.assertTrue(all(
            "未検証" in x["note"] for x in view["rows"]
        ))
        self.assertEqual(before, self._hashes())

    def test_match_and_player_present_original_saved_fields(self):
        before = self._hashes()
        for year in (2026, 10000):
            bridge = CareerHistoryGuiBridge(self.fixture.root)
            school = project_history_screen(
                bridge.open_school(year, self.fixture.a),
            )
            self.assertEqual("history_school", school["screen"])
            match_link = next(x for x in school["rows"]
                              if x["title"].startswith("試合 "))
            match = project_history_screen(
                bridge.open_link(match_link["target"]),
            )
            self.assertEqual("history_match", match["screen"])
            self.assertIn(str(year), match["title"])
            for prefix in ("イニング別得点", "チーム成績",
                           "打撃成績", "投手成績"):
                records = [x for x in match["rows"]
                           if x["title"].startswith(prefix)
                           and x["kind"] == "detail"]
                self.assertTrue(records)
                self.assertIsInstance(
                    json.loads(records[0]["payload"]), dict,
                )
            bridge.back()
            person = next(x for x in school["rows"]
                          if x["title"].startswith("選手 "))
            player = project_history_screen(
                bridge.open_link(person["target"]),
            )
            self.assertEqual("history_player", player["screen"])
            self.assertFalse(player["allow_advance_year"])
        self.assertEqual(before, self._hashes())

    def test_fail_closed_bad_screen_and_provenance(self):
        page = dict(self.bridge.page)
        page["source_verified"] = True
        with self.assertRaises(CareerHistoryViewConflict):
            project_history_screen(page)
        page = dict(self.bridge.page)
        page["allow_advance_year"] = True
        with self.assertRaises(CareerHistoryViewConflict):
            project_history_screen(page)

    def test_tk_year_school_match_player_and_back(self):
        gui = self._gui()
        before = self._hashes()
        self._select(gui, lambda x: x["kind"] == "year"
                     and x["year"] == 2026)
        self.assertEqual("history_school", gui.view["screen"])
        self._select(gui, lambda x: x["title"].startswith("試合 "))
        self.assertEqual("history_match", gui.view["screen"])
        detail = next(w for w, x in gui.rows_by_widget_id.items()
                      if x["kind"] == "detail")
        gui.tree.selection_set(detail)
        gui._selected_detail()
        self.assertIn('"', gui.detail_text.get("1.0", "end"))
        gui.back_button.invoke()
        self.assertEqual("history_school", gui.view["screen"])
        self._select(gui, lambda x: x["title"].startswith("選手 "))
        self.assertEqual("history_player", gui.view["screen"])
        gui.back_button.invoke()
        gui.back_button.invoke()
        self.assertEqual("history_year_catalog", gui.view["screen"])
        self.assertEqual(before, self._hashes())

    def test_tk_older_years_and_v2_game_date(self):
        gui = self._gui(size=1)
        before = self._hashes()
        self.assertEqual(10000, gui.view["rows"][0]["year"])
        gui.older_button.invoke()
        self.assertEqual(2026, gui.view["rows"][0]["year"])
        gui.back_button.invoke()
        self._select(gui, lambda x: x["year"] == 10000)
        self._select(gui, lambda x: x["title"].startswith("試合 "))
        self.assertEqual("history_match", gui.view["screen"])
        self.assertIn("G10000:", gui.view["summary"])
        self.assertEqual(before, self._hashes())

    def test_tk_error_does_not_change_navigation_or_saved_files(self):
        gui = self._gui()
        self._select(gui, lambda x: x["kind"] == "year"
                     and x["year"] == 10000)
        prior = (gui.view, dict(gui.bridge.route),
                 list(gui.bridge.history))
        with sqlite3.connect(self.fixture.v2) as db:
            db.execute(
                "UPDATE v2_option_a_matches SET record_sha256='INVALID' "
                "WHERE year=10000"
            )
        after = self._hashes()
        self._select(gui, lambda x: x["title"].startswith("試合 "))
        self.assertIsNotNone(gui.last_error)
        self.assertEqual(prior, (
            gui.view, gui.bridge.route, gui.bridge.history,
        ))
        self.assertEqual(after, self._hashes())

    def test_tk_unknown_school_keeps_catalog(self):
        gui = self._gui()
        before = self._hashes()
        gui.school_var.set("UNSAVED_SCHOOL")
        self._select(gui, lambda x: x["year"] == 2026)
        self.assertIsNotNone(gui.last_error)
        self.assertEqual("history_year_catalog", gui.view["screen"])
        self.assertEqual(before, self._hashes())


if __name__ == "__main__":
    unittest.main()
