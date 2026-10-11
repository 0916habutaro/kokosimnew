"""Stage43G-55: Tokai browsing Tk controller and optional real Tk smoke.

The source fixture contains synthetic 2027 Option-A game records only.
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
import unittest

import test_stage43g54_tokai_season_history_browse as stage54
from phase2_engine.career_history_browse_model import CareerHistoryBrowseModel
from phase2_engine.career_history_gui_pilot import CareerHistoryGuiPilot
from phase2_engine.career_tokai_season_browse_model import (
    TOKAI, GIFU, TokaiSeasonBrowseConflict,
)
from phase2_engine.career_tokai_season_gui_pilot import (
    APP_NAME, CareerTokaiSeasonGuiPilot, TokaiSeasonScreenController,
)

GUI_AVAILABLE = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G55TokaiTkGuiTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage54.Stage43G54TokaiHistoryReadOnly(
            "test_competition_school_match_and_player_navigation_by_ids",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.model = self.fixture.model
        self.ctrl = TokaiSeasonScreenController(self.model, year=2027)
        self.before = self.fixture._sha()

    def test_controller_games_school_stats_back_and_source_integrity(self):
        self.assertEqual("tokai_season", self.ctrl.page["screen"])
        toc = self.ctrl.page["events"]
        tokai = next(x["competition_target"] for x in toc
                     if x["competition_id"] == TOKAI)
        page = self.ctrl.open(tokai)
        self.assertEqual("tokai_competition", page["screen"])
        self.assertEqual(1, page["matches"]["total"])
        match = self.ctrl.open(page["matches"]["rows"][0]["match_target"])
        self.assertEqual("tokai_match", match["screen"])
        self.assertEqual("recorded", match["inning_score_status"])
        school = self.ctrl.open(match["school_targets"][0])
        self.assertEqual("tokai_school", school["screen"])
        self.assertEqual(4, school["matches"]["total"])
        athlete = self.ctrl.open(school["player_targets"][0])
        self.assertEqual("tokai_player", athlete["screen"])
        self.assertIn("career_stats", athlete)
        self.assertEqual("tokai_school", self.ctrl.back()["screen"])
        self.assertEqual("tokai_match", self.ctrl.back()["screen"])
        self.assertEqual("tokai_competition", self.ctrl.back()["screen"])
        self.assertEqual("tokai_season", self.ctrl.back()["screen"])
        self.assertEqual("tokai_season", self.ctrl.back()["screen"])
        self.assertEqual(self.before, self.fixture._sha())

    def test_invalid_route_does_not_change_navigation_history(self):
        state = (dict(self.ctrl.target), self.ctrl.offset,
                 list(self.ctrl.history), self.ctrl.page)
        for bad in (
            {"screen": "competition", "year": 2027,
             "competition_id": "CMP000086"},
            {"screen": "match", "year": 2027,
             "competition_id": TOKAI, "match_id": "NOT-A-REAL-ID"},
            {"screen": "school", "year": 2027, "school_id": self.fixture.a,
             "extra": "wrong"},
            {"screen": "tokai_season", "year": True},
            {"screen": "not-supported", "year": 2027},
        ):
            with self.assertRaises((ValueError, TypeError)):
                self.ctrl.open(bad)
            self.assertEqual(
                state, (self.ctrl.target, self.ctrl.offset,
                        self.ctrl.history, self.ctrl.page),
            )
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.ctrl.change_page(1)
        self.assertEqual(self.before, self.fixture._sha())

    def test_school_and_competition_pagination_stays_within_saved_rows(self):
        toc = self.ctrl.page["events"]
        target = next(x["competition_target"] for x in toc
                      if x["competition_id"] == TOKAI)
        self.ctrl.open(target)
        self.assertEqual(self.ctrl.page, self.ctrl.change_page(1))
        self.assertEqual(0, self.ctrl.offset)
        self.assertEqual(self.ctrl.page, self.ctrl.change_page(-1))
        target = self.ctrl.page["school_targets"][0]
        self.ctrl.open(target)
        self.assertEqual(self.ctrl.page, self.ctrl.change_page(1))
        self.assertEqual(0, self.ctrl.offset)
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.ctrl.change_page(3)
        self.assertEqual("tokai_competition", self.ctrl.back()["screen"])

    @unittest.skipUnless(GUI_AVAILABLE, "requires real Tk display (Xvfb or Windows)")
    def test_real_tk_table_selection_and_back_to_saved_year(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        gui = CareerTokaiSeasonGuiPilot(root, self.model, year=2027)
        root.update_idletasks()
        self.assertEqual(APP_NAME, root.title())
        self.assertEqual(6, len(gui.table.get_children()))
        item = next(iid for iid, target in gui.links.items()
                    if target.get("competition_id") == TOKAI)
        gui.table.selection_set(item)
        gui._open_selection()
        self.assertEqual("tokai_competition", gui.controller.page["screen"])
        match_iid = next(iid for iid, target in gui.links.items()
                         if target.get("screen") == "match")
        gui.table.selection_set(match_iid)
        gui._open_selection()
        self.assertEqual("tokai_match", gui.controller.page["screen"])
        self.assertTrue(gui.controller.page["game"]["inning_scores"])
        gui._back()
        self.assertEqual("tokai_competition", gui.controller.page["screen"])
        gui._home()
        self.assertEqual("tokai_season", gui.controller.page["screen"])
        self.assertIn("公式", gui.status_var.get())
        self.assertEqual(self.before, self.fixture._sha())

    @unittest.skipUnless(GUI_AVAILABLE, "requires real Tk display (Xvfb or Windows)")
    def test_existing_history_pilot_opens_a_separate_tokai_window(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        base = CareerHistoryBrowseModel(
            self.fixture.model.source.repo.data_dir, self.fixture.slot,
        )
        pilot = CareerHistoryGuiPilot(root, base)
        pilot.year_var.set("2027")
        snapshot = (pilot.navigator.current, list(pilot.navigator._back))
        pilot._open_tokai()
        windows = [
            child for child in root.winfo_children()
            if isinstance(child, tk.Toplevel)
        ]
        self.assertEqual(1, len(windows))
        self.assertEqual(
            "tokai_season",
            windows[0]._career_tokai_season_gui.controller.page["screen"],
        )
        self.assertEqual(snapshot, (
            pilot.navigator.current, pilot.navigator._back,
        ))
        self.assertEqual(self.before, self.fixture._sha())


if __name__ == "__main__":
    unittest.main()
