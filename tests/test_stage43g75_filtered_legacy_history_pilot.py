"""Stage43G-75: existing cross-era Tk pilot opens indexed old-A filters.

All fixtures contain synthetic score-only or fictional A games, never
official results. The filtered Tk window never rewrites source SQLite.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

from phase2_engine.career_history_scale_benchmark import (
    build_synthetic_archive, file_sha256,
)
from phase2_engine.career_legacy_filtered_history_pilot import (
    CareerLegacyFilteredSchoolController,
    CareerLegacyFilteredSchoolPilot, FILTER_PAGE_SIZE,
)
from phase2_engine.career_cross_era_navigation import CareerCrossEraNavigator
from phase2_engine.career_cross_era_gui_pilot import CareerCrossEraGuiPilot
import test_stage43g31_cross_era_browse_model as stage31

TK_AVAILABLE = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G75FilteredLegacyPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.slot = Path(self.temp.name)
        self.match_path = self.slot / "historical_matches.sqlite3"
        build_synthetic_archive(
            self.match_path, schools=2, years=3,
            games_per_school_year=36,
        )
        self.school = "BENCH-SCH-0001"
        self.years = [2026, 2027, 2028]

    def controller(self, *, selected_year=2026):
        return CareerLegacyFilteredSchoolController(
            self.slot, self.school, self.years,
            selected_year=selected_year,
        )

    def test_headless_initial_legacy_school_view_limits_to_30_visible_games(self):
        before = file_sha256(self.match_path)
        ctrl = self.controller()
        self.assertEqual(36, ctrl.page["total"])
        self.assertEqual(30, len(ctrl.page["records"]))
        self.assertEqual("legacy_filtered_school_match_page", ctrl.page["screen"])
        self.assertEqual([2026, 2027, 2028], ctrl.page["available_years"])
        self.assertEqual(
            ["BENCH-CMP-A", "BENCH-CMP-B"],
            ctrl.page["available_competition_ids"],
        )
        self.assertTrue(ctrl.page["year_header_sealed"])
        self.assertFalse(ctrl.page["v2_games_included"])
        self.assertTrue(ctrl.page["visible_match_checksums_verified"])
        self.assertFalse(ctrl.page["all_filtered_window_checksums_verified"])
        self.assertEqual(before, file_sha256(self.match_path))

    def test_forward_back_page_uses_only_visible_save_ids(self):
        ctrl = self.controller()
        first = ctrl.page["records"][0]["match_id"]
        second = ctrl.change_page(1)
        self.assertEqual(FILTER_PAGE_SIZE, second["offset"])
        self.assertEqual(6, len(second["records"]))
        self.assertNotEqual(first, second["records"][0]["match_id"])
        self.assertIs(second, ctrl.change_page(1))
        self.assertEqual(second["offset"], ctrl.offset)
        self.assertEqual(0, ctrl.change_page(-1)["offset"])
        self.assertEqual(first, ctrl.page["records"][0]["match_id"])
        self.assertIs(ctrl.page, ctrl.change_page(-1))

    def test_competition_filter_persists_original_id_then_year_resets(self):
        ctrl = self.controller()
        ctrl.change_page(1)
        selected = ctrl.change_competition("BENCH-CMP-A")
        self.assertEqual(0, selected["offset"])
        self.assertEqual(18, selected["total"])
        self.assertTrue(all(
            row["competition_id"] == "BENCH-CMP-A"
            for row in selected["records"]
        ))
        self.assertEqual("BENCH-CMP-A", ctrl.competition_id)
        next_year = ctrl.change_year(2027)
        self.assertEqual(2027, next_year["selected_year"])
        self.assertIsNone(next_year["competition_id"])
        self.assertEqual(36, next_year["total"])
        self.assertEqual(0, ctrl.offset)
        self.assertEqual([2026, 2027, 2028], next_year["available_years"])

    def test_exact_visible_id_for_navigation_only_not_off_page_id(self):
        ctrl = self.controller()
        visible = ctrl.page["records"][0]
        expected = (
            2026, visible["competition_id"], visible["match_id"],
        )
        self.assertEqual(expected, ctrl.select_visible_match(
            visible["match_id"], visible["competition_id"],
        ))
        with self.assertRaises(ValueError):
            ctrl.select_visible_match(
                "BENCH-2026-0001-35", "BENCH-CMP-B",
            )
        with self.assertRaises(ValueError):
            ctrl.select_visible_match(visible["match_id"], "WRONG-CMP")

    def test_hidden_match_corruption_not_claimed_in_fast_mode(self):
        ctrl = self.controller()
        before = ctrl.page["records"][0]
        with sqlite3.connect(self.match_path) as conn:
            conn.execute(
                "UPDATE historical_matches SET payload_json='{}' "
                "WHERE year=2026 AND match_id='BENCH-2026-0001-35'"
            )
        changed_hash = file_sha256(self.match_path)
        page = ctrl._read()
        self.assertEqual(before, page["records"][0])
        self.assertFalse(page["all_filtered_window_checksums_verified"])
        ctrl.verify_scope = "filtered_window"
        with self.assertRaises(ValueError):
            ctrl._read()
        self.assertEqual(changed_hash, file_sha256(self.match_path))

    def test_filtered_deep_verification_only_for_selected_competition(self):
        ctrl = self.controller()
        selected = ctrl.change_competition("BENCH-CMP-A")
        self.assertEqual(18, selected["total"])
        with sqlite3.connect(self.match_path) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='BAD' "
                "WHERE year=2026 AND match_id='BENCH-2026-0001-35'"
            )
        before = file_sha256(self.match_path)
        ctrl.verify_scope = "filtered_window"
        good = ctrl._read()
        self.assertTrue(good["all_filtered_window_checksums_verified"])
        # Strict mode rejects corrupt B and leaves the selected A filter.
        with self.assertRaises(ValueError):
            ctrl.change_competition(None)
        self.assertEqual("BENCH-CMP-A", ctrl.competition_id)
        self.assertEqual(18, ctrl.page["total"])
        self.assertEqual(0, ctrl.offset)

    def test_sealed_year_header_change_rejected_without_changing_page(self):
        ctrl = self.controller()
        with sqlite3.connect(self.match_path) as conn:
            conn.execute(
                "UPDATE career_years SET status='active' WHERE year=2027"
            )
        before = file_sha256(self.match_path)
        original = ctrl.page
        with self.assertRaisesRegex(ValueError, "sealed"):
            ctrl.change_year(2027)
        self.assertIs(original, ctrl.page)
        self.assertEqual(2026, ctrl.selected_year)
        self.assertEqual(before, file_sha256(self.match_path))
        with self.assertRaisesRegex(ValueError, "sealed"):
            CareerLegacyFilteredSchoolController(
                self.slot, self.school, self.years,
            )

    def test_missing_unsaved_v2_outside_selection_and_invalid_filters_rejected(self):
        ctrl = self.controller()
        for year in (2025, 2029, 10000, True, "2026"):
            with self.subTest(year=year):
                with self.assertRaises(ValueError):
                    ctrl.change_year(year)
        with self.assertRaises(ValueError):
            ctrl.change_competition("NOT-ON-SCHOOL-SAVE")
        with self.assertRaises(ValueError):
            ctrl.change_competition(True)
        for delta in (True, 0, 2, "1"):
            with self.assertRaises(ValueError):
                ctrl.change_page(delta)
        self.assertFalse((self.slot / "fictional_option_a_v2.sqlite3").exists())
        self.assertFalse((self.slot / "career_rosters.sqlite3").exists())
        for years in ([2026, 2026], [2028, 2026], [2026, 10000], []):
            with self.assertRaises(ValueError):
                CareerLegacyFilteredSchoolController(
                    self.slot, self.school, years,
                )
        with self.assertRaises(FileNotFoundError):
            CareerLegacyFilteredSchoolController(
                self.slot / "missing", self.school, [2026],
            )

    @unittest.skipUnless(TK_AVAILABLE, "Tk test needs Windows or DISPLAY")
    def test_real_tk_filters_pages_and_opens_selected_saved_match(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        invoked = []
        gui = CareerLegacyFilteredSchoolPilot(
            root, self.controller(),
            open_match=lambda *args: invoked.append(args),
        )
        self.assertEqual(30, len(gui.table.get_children()))
        gui._step(1)
        self.assertEqual(6, len(gui.table.get_children()))
        gui.competition_var.set("BENCH-CMP-A")
        gui._comp_selected()
        self.assertEqual(18, len(gui.table.get_children()))
        gui.year_var.set("2028")
        gui._year_selected()
        self.assertEqual(30, len(gui.table.get_children()))
        first = gui.table.get_children()[0]
        gui.table.selection_set(first)
        gui._open_selection()
        self.assertEqual(1, len(invoked))
        self.assertEqual(2028, invoked[0][0])
        self.assertTrue(invoked[0][1].startswith("BENCH-CMP-"))

    @unittest.skipUnless(TK_AVAILABLE, "Tk test needs Windows or DISPLAY")
    def test_parent_cross_era_tk_opens_legacy_filtered_pilot_no_save_writes(self):
        import tkinter as tk
        stage = stage31.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year",
        )
        stage.setUp()
        self.addCleanup(stage.tearDown)
        stage.setup_both()
        sources = [
            stage.old, stage.v2, stage.calendar,
            stage.rosters.db_path, stage.cache.path,
        ]
        before = {str(p): file_sha256(p) for p in sources}
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        nav = CareerCrossEraNavigator(stage.root)
        gui = CareerCrossEraGuiPilot(
            root, nav, school_id=stage.a, years=[2026, 10000],
            selected_year=2026, data_root=stage31.ROOT / "data",
        )
        gui._open_legacy_history_filter()
        self.assertIsNotNone(gui.legacy_filter_window)
        self.assertEqual(2026, gui.legacy_filter_view.controller.selected_year)
        self.assertEqual(1, gui.legacy_filter_view.controller.page["total"])
        row = gui.legacy_filter_view.table.get_children()[0]
        gui.legacy_filter_view.table.selection_set(row)
        gui.legacy_filter_view._open_selection()
        self.assertEqual("cross_era_match", gui.controller.page["screen"])
        self.assertEqual("OLD", gui.controller.page["match"]["match_id"])
        self.assertEqual(
            before, {str(p): file_sha256(p) for p in sources},
        )
        gui.legacy_filter_window.destroy()


if __name__ == "__main__":
    unittest.main()
