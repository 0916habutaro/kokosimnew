"""Stage43G-33: cross-era Tk pilot callbacks + true Tk smoke under Xvfb.

Standalone CI uses python/unittest headless controller checks. A second
xvfb-run invocation covers actual Tk widgets and navigation event dispatch.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

import test_stage43g31_cross_era_browse_model as source_fixture
from phase2_engine.career_cross_era_gui_pilot import (
    APP_NAME, CareerCrossEraGuiPilot,
    CareerCrossEraScreenController, available_sealed_years,
)
from phase2_engine.career_cross_era_navigation import CareerCrossEraNavigator
from phase2_engine.career_history_scale_benchmark import file_sha256

YEARS = [2026, 10000]
TK_AVAILABLE = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G33CrossEraGuiPilotTests(unittest.TestCase):
    def setUp(self):
        self.fixture = source_fixture.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.nav = CareerCrossEraNavigator(self.fixture.root)
        self.school = self.fixture.a

    def controller(self):
        return CareerCrossEraScreenController(
            self.nav, YEARS, self.school, selected_year=2026,
        )

    def test_controller_school_to_opponent_and_back_preserves_ids(self):
        ctrl = self.controller()
        self.assertEqual("cross_era_school", ctrl.page["screen"])
        self.assertEqual("YYYY-MM-DD", ctrl.page["date_kind"])
        link = ctrl.page["opponent_school_targets"][0]["target"]
        target = ctrl.open(link)
        self.assertEqual(self.fixture.b, target["school_id"])
        self.assertEqual(1, target["match_losses_from_saved_games"])
        self.assertEqual(self.school, ctrl.back()["school_id"])
        self.assertEqual(2026, ctrl.target["selected_year"])

    def test_year_switch_preserves_school_and_never_infers_missing_period(self):
        ctrl = self.controller()
        future = ctrl.change_year(10000)
        self.assertEqual("G{year}:MM-DD", future["date_kind"])
        self.assertEqual("G10000:04-01", future["match_page"][0]["date"])
        self.assertEqual(
            [{"from_year": 2027, "through_year": 9999}],
            future["unverified_intervening_year_intervals"],
        )
        self.assertEqual("YYYY-MM-DD", ctrl.back()["date_kind"])

    def test_player_link_switch_year_and_return_to_school(self):
        ctrl = self.controller()
        player = self.fixture.rosters.roster(2026, self.school).players[0].player_id
        link = next(
            x["target"] for x in ctrl.page["player_targets"]
            if x["player_id"] == player
        )
        current = ctrl.open(link)
        self.assertEqual("cross_era_player", current["screen"])
        self.assertEqual(player, current["player_id"])
        self.assertEqual("verified_box_score", current["selected_status"])
        self.assertIsNone(current["combined_career_totals"])
        absent = ctrl.change_year(10000)
        self.assertEqual(
            "not_on_saved_school_year_roster", absent["selected_status"],
        )
        self.assertIsNone(absent["selected_statistics"])
        current = ctrl.back()
        self.assertEqual(2026, current["selected_year"])
        old = ctrl.open(current["back_to_school_target"])
        self.assertEqual(self.school, old["school_id"])
        self.assertEqual("cross_era_school", old["screen"])

    def test_bad_navigation_keeps_current_target_history_and_page(self):
        ctrl = self.controller()
        target = dict(ctrl.target)
        page = ctrl.page
        history = list(ctrl.history)
        with self.assertRaises(ValueError):
            ctrl.change_year(2027)
        with self.assertRaises(ValueError):
            ctrl.open({"view": "school", "school_id": self.school})
        self.assertEqual(target, ctrl.target)
        self.assertIs(page, ctrl.page)
        self.assertEqual(history, ctrl.history)

    def test_page_beyond_saved_games_does_not_fake_rows(self):
        ctrl = self.controller()
        self.assertEqual(ctrl.page, ctrl.change_page(1))
        self.assertEqual(0, ctrl.offset)
        with self.assertRaises(ValueError):
            ctrl.change_page(0)
        self.assertEqual([], ctrl.history)

    def test_only_sealed_real_headers_returned_without_creating_files(self):
        before = [
            file_sha256(path) for path in (
                self.fixture.old, self.fixture.v2, self.fixture.calendar,
                self.fixture.rosters.db_path, self.fixture.cache.path,
            )
        ]
        self.assertEqual(YEARS, available_sealed_years(self.fixture.root))
        ctrl = self.controller()
        ctrl.change_year(10000)
        ctrl.back()
        self.assertEqual(
            before,
            [file_sha256(path) for path in (
                self.fixture.old, self.fixture.v2, self.fixture.calendar,
                self.fixture.rosters.db_path, self.fixture.cache.path,
            )],
        )
        self.assertFalse((self.fixture.root / "derived_player_stats.sqlite3").exists())

    def test_readable_future_only_without_legacy_archive(self):
        self.fixture.old.unlink()
        self.assertEqual([10000], available_sealed_years(self.fixture.root))
        ctrl = CareerCrossEraScreenController(
            self.nav, [10000], self.school, selected_year=10000,
        )
        self.assertEqual(1, ctrl.page["match_total"])
        self.assertFalse(self.fixture.old.exists())

    @unittest.skipUnless(TK_AVAILABLE, "actual Tk smoke requires DISPLAY or Windows")
    def test_actual_tk_treeview_year_selection_player_double_click_and_back(self):
        import tkinter as tk
        root = tk.Tk()
        self.addCleanup(root.destroy)
        gui = CareerCrossEraGuiPilot(
            root, self.nav, school_id=self.school,
            years=YEARS, selected_year=2026,
        )
        root.update_idletasks()
        self.assertIn("試験版", root.title())
        self.assertEqual(APP_NAME, root.title())
        self.assertEqual("2026", gui.year_var.get())
        self.assertTrue(gui.table.get_children())
        player_id = self.fixture.rosters.roster(2026, self.school).players[0].player_id
        iid = next(
            iid for iid, target in gui.links.items()
            if target.get("view") == "player"
            and target.get("player_id") == player_id
        )
        gui.table.selection_set(iid)
        gui._open_selection()
        self.assertEqual("cross_era_player", gui.controller.page["screen"])
        gui.year_var.set("10000")
        gui._change_year()
        self.assertEqual("not_on_saved_school_year_roster",
                         gui.controller.page["selected_status"])
        self.assertIn("not_on_saved_school_year_roster",
                      gui.details.get("1.0", "end"))
        gui._back()
        self.assertEqual(2026, gui.controller.page["selected_year"])
        gui._open(gui.controller.page["back_to_school_target"])
        self.assertEqual("cross_era_school", gui.controller.page["screen"])
        self.assertEqual("2026", gui.year_var.get())

    @unittest.skipUnless(TK_AVAILABLE, "actual Tk smoke requires DISPLAY or Windows")
    def test_existing_legacy_tk_pilot_opens_separate_cross_era_window(self):
        import tkinter as tk
        from phase2_engine.career_history_browse_model import (
            CareerHistoryBrowseModel, HistoryRoute,
        )
        from phase2_engine.career_history_gui_pilot import CareerHistoryGuiPilot
        from pathlib import Path
        root = tk.Tk()
        self.addCleanup(root.destroy)
        old = CareerHistoryGuiPilot(
            root, CareerHistoryBrowseModel(
                Path(source_fixture.ROOT) / "data", self.fixture.root,
            ),
        )
        old.navigator.open(HistoryRoute(
            "school", 2026, school_id=self.school,
        ))
        old.year_var.set("2026")
        old._open_cross_era()
        root.update_idletasks()
        children = [
            child for child in root.winfo_children()
            if isinstance(child, tk.Toplevel)
        ]
        self.assertEqual(1, len(children))
        child = children[0]
        self.assertEqual(APP_NAME, child.title())
        self.assertEqual("2026", child._career_cross_era_gui.year_var.get())
        self.assertEqual(self.school,
                         child._career_cross_era_gui.controller.target["school_id"])
        self.assertEqual("school", old.navigator.current.screen)
        self.assertFalse((self.fixture.root / "derived_player_stats.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
