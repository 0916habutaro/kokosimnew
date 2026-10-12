"""Stage43G-80: optional Tk v2 school index, with explicit opt-in and rollback.

No search creates a sidecar. Every indexed page still verifies the sealed
fictional v2 source; tests use saved full-A synthetic sources only.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import sys
import unittest

from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_school_game_tk import CareerV2SchoolGamePager
from phase2_engine.career_v2_school_read_index import (
    build_v2_school_read_index,
)
import test_stage43g79_v2_school_read_index as stage79
import test_stage43g77_dual_school_game_tk as stage77

DISPLAY = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G80PagerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage79.Stage43G79IndependentSchoolIndexTests(
            "test_atomic_build_unchanged_source_and_exact_old_api_page_match"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.populate()
        self.index = self.fixture.index
        self.pager = CareerV2SchoolGamePager(
            self.fixture.source, self.fixture.calendar,
            stage79.stage27.FIRST, 10000,
            index_path=self.index,
        )

    def source_hashes(self):
        return (file_sha256(self.fixture.source),
                file_sha256(self.fixture.calendar))

    def test_missing_index_is_never_created_and_selection_atomic(self):
        before_source = self.source_hashes()
        original = self.pager.page
        self.assertFalse(self.index.exists())
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertEqual("original_json1",
                         self.pager.select_lookup("original_json1")
                         and self.pager.lookup_mode)
        with self.assertRaises(FileNotFoundError):
            self.pager.select_lookup("separate_index")
        self.assertFalse(self.index.exists())
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertIs(original, self.pager.page)
        self.assertEqual(before_source, self.source_hashes())

    def test_explicit_index_selection_preserves_page_filters_and_source(self):
        self.fixture.build()
        before_source = self.source_hashes()
        before_index = file_sha256(self.index)
        original = self.pager.apply_filters(
            10000, 10001, stage79.stage27.COMP,
            "selected_years",
        )
        self.assertEqual(4, original["total"])
        indexed = self.pager.select_lookup("separate_index")
        self.assertEqual("separate_index", self.pager.lookup_mode)
        self.assertTrue(indexed["uses_separate_verified_school_index"])
        self.assertTrue(indexed["all_selected_year_payloads_verified"])
        self.assertEqual(original["records"], indexed["records"])
        self.assertEqual(original["total"], indexed["total"])
        self.assertEqual(10000, self.pager.start_year)
        self.assertEqual(10001, self.pager.end_year)
        self.assertEqual(stage79.stage27.COMP, self.pager.competition_id)
        self.assertEqual("selected_years", self.pager.verify_scope)
        back = self.pager.select_lookup("original_json1")
        self.assertEqual(original["records"], back["records"])
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertEqual(before_source, self.source_hashes())
        self.assertEqual(before_index, file_sha256(self.index))

    def test_wrong_index_source_and_corruption_fail_without_fallback(self):
        self.fixture.build()
        previous = self.pager.page
        with sqlite3.connect(self.index) as con:
            con.execute("UPDATE meta SET source_path='/other/source.sqlite3'")
        with self.assertRaisesRegex(ValueError, "different saved source"):
            self.pager.select_lookup("separate_index")
        self.assertIs(previous, self.pager.page)
        self.assertEqual("original_json1", self.pager.lookup_mode)
        # The original JSON1 read remains separately available.
        self.assertEqual(previous["records"],
                         self.pager.apply_filters(10000, 10000)["records"])

    def test_invalid_mode_and_failed_index_scope_remain_atomic(self):
        self.fixture.build()
        before = (self.pager.lookup_mode, self.pager.page,
                  self.pager.start_year, self.pager.end_year)
        with self.assertRaises(ValueError):
            self.pager.select_lookup("automatic_fallback")
        with self.assertRaises(ValueError):
            self.pager.select_lookup(True)
        self.assertEqual(before, (
            self.pager.lookup_mode, self.pager.page,
            self.pager.start_year, self.pager.end_year,
        ))
        # Original JSON1 reader can inspect an unindexed (unsaved) year;
        # opting into the independently built 10000..10001 index must fail.
        self.pager.apply_filters(10000, 10002)
        original = self.pager.page
        with self.assertRaisesRegex(ValueError, "different saved source or year"):
            self.pager.select_lookup("separate_index")
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertIs(original, self.pager.page)
        self.assertEqual((10000, 10002), (
            self.pager.start_year, self.pager.end_year,
        ))


@unittest.skipUnless(DISPLAY, "real Tk or Xvfb display required")
class Stage43G80TkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage77.Stage43G77HistoryTkTests(
            "test_v2_window_has_logical_tokens_and_strict_scope"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.gui = self.fixture.gui

    def slot(self) -> Path:
        return self.fixture.fixture.fixture.a_slot

    def source_hashes(self):
        root = self.slot()
        return {name: sha256((root / name).read_bytes()).hexdigest()
                for name in (
                    "fictional_option_a_v2.sqlite3",
                    "sandbox_calendar_v2.sqlite3",
                    "historical_matches.sqlite3",
                ) if (root / name).exists()}

    def create_index(self):
        root = self.slot()
        return build_v2_school_read_index(
            root / "fictional_option_a_v2.sqlite3",
            root / "sandbox_calendar_v2.sqlite3",
            root / "fictional_v2_school_read_index.sqlite3",
            start_year=10000, end_year=10000,
        )

    def test_v2_ui_missing_index_error_then_opt_in_and_back(self):
        before = self.source_hashes()
        child = self.fixture._open_v2()
        self.assertTrue(child.is_v2)
        self.assertEqual("original_json1", child.lookup_var.get())
        self.assertIn("原本JSON1", child.status_var.get())
        initial = child.pager.page
        child.lookup_var.set("separate_index")
        child._change_lookup()
        self.assertIsNotNone(child.last_error)
        self.assertEqual("original_json1", child.lookup_var.get())
        self.assertIs(child.pager.page, initial)
        self.assertFalse(
            (self.slot() / "fictional_v2_school_read_index.sqlite3").exists()
        )
        self.create_index()
        self.assertEqual(before, self.source_hashes())
        original_items = list(child.rows_by_widget_id.values())
        child.lookup_var.set("separate_index")
        child._change_lookup()
        self.assertIsNone(child.last_error)
        self.assertEqual("separate_index", child.pager.lookup_mode)
        self.assertIn("独立SQLite学校索引", child.status_var.get())
        self.assertEqual(original_items, list(child.rows_by_widget_id.values()))
        child.scope_var.set("selected_years")
        child.search_button.invoke()
        self.assertIsNone(child.last_error)
        self.assertTrue(child.pager.page["offpage_derived_memberships_verified"])
        child.lookup_var.set("original_json1")
        child._change_lookup()
        self.assertEqual("original_json1", child.pager.lookup_mode)
        self.assertIn("原本JSON1", child.status_var.get())
        self.assertEqual(before, self.source_hashes())

    def test_bad_cache_rolls_back_and_slot_switch_discards_lookup(self):
        self.create_index()
        before = self.source_hashes()
        child = self.fixture._open_v2()
        child.lookup_var.set("separate_index")
        child._change_lookup()
        self.assertEqual("separate_index", child.pager.lookup_mode)
        with sqlite3.connect(child.pager.index_path) as con:
            con.execute("UPDATE meta SET source_path='WRONG' ")
        old_page = child.pager.page
        child.lookup_var.set("original_json1")
        child._change_lookup()
        self.assertEqual("original_json1", child.pager.lookup_mode)
        child.lookup_var.set("separate_index")
        child._change_lookup()
        self.assertIsNotNone(child.last_error)
        self.assertEqual("original_json1", child.pager.lookup_mode)
        self.assertEqual("original_json1", child.lookup_var.get())
        self.assertIsNot(old_page, child.pager.page)
        self.gui.slot_var.set("save_B")
        self.gui._change_slot()
        self.assertEqual("save_B", self.gui.slot_var.get())
        self.assertIsNone(self.gui.v2_window)
        self.assertFalse(child.root.winfo_exists())
        self.assertEqual(before, self.source_hashes())

    def test_legacy_window_never_has_v2_index_controls(self):
        bridge = self.gui.bridge
        bridge.open_year(2026)
        bridge.open_school(2026, self.fixture.fixture.a)
        self.gui._render()
        self.gui.legacy_games_button.invoke()
        self.assertIsNotNone(self.gui.legacy_window)
        self.assertFalse(self.gui.legacy_window.is_v2)
        self.assertIsNone(self.gui.legacy_window.lookup_var)
        self.assertFalse(hasattr(self.gui.legacy_window, "lookup_box"))


if __name__ == "__main__":
    unittest.main()
