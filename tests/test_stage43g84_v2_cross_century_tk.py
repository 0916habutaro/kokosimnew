"""Stage43G-84: Tk opt-in reading across multiple sealed fictional v2 centuries.

Full source remains unchanged; this stage does not build any shard in a
search callback and does not mix legacy ISO with Gxxxxx logical dates.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import sys
import tkinter as tk
import unittest

from phase2_engine.career_v2_school_game_tk import CareerV2SchoolGamePager
from phase2_engine.career_legacy_school_game_tk import (
    CareerLegacySchoolGamePager, CareerLegacySchoolGamesTkPilot,
)
from phase2_engine.career_history_scale_benchmark import file_sha256
import test_stage43g83_v2_century_shards as stage83
import test_stage43g77_dual_school_game_tk as stage77

DISPLAY = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G84CenturyPagerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage83.Stage43G83ShardedV2Tests(
            "test_two_centuries_order_29_plus_7_and_global_30_page",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture._populate()
        self.pager = CareerV2SchoolGamePager(
            self.fixture.source, self.fixture.calendar,
            stage83.stage27.FIRST, 10000,
        )
        self.paths = ()
        self.names = ()

    def build_shards(self):
        self.fixture._build()
        self.paths = tuple(self.fixture.index_paths)
        self.names = tuple(x.name for x in self.paths)

    def hashes(self):
        return {x.name: file_sha256(x) for x in
                (self.fixture.source, self.fixture.calendar, *self.paths)}

    def test_explicit_cross_century_activation_and_global_two_pages(self):
        self.build_shards()
        before = self.hashes()
        self.assertEqual("original_json1", self.pager.lookup_mode)
        result = self.pager.select_century_shards(
            self.names, start_year=10000, end_year=10100,
        )
        self.assertEqual("century_shards", self.pager.lookup_mode)
        self.assertEqual(36, result["total"])
        self.assertEqual(30, len(result["records"]))
        self.assertEqual(10100, result["records"][-1]["year"])
        self.assertTrue(result["cross_century_school_index_shards"])
        self.assertFalse(result["legacy_records_combined"])
        self.assertTrue(result["original_source_data_version_unchanged"])
        second = self.pager.move(1)
        self.assertEqual(30, self.pager.offset)
        self.assertEqual(6, len(second["records"]))
        self.assertTrue(all(r["game_day_token"].startswith("G10100:")
                            for r in second["records"]))
        self.assertFalse(self.pager.can_next)
        self.assertTrue(self.pager.can_previous)
        self.assertEqual(30, len(self.pager.move(-1)["records"]))
        self.assertEqual(before, self.hashes())
        self.assertFalse(self.fixture.fixture.legacy_file.exists())

    def test_strict_scope_filters_and_source_rechecks_after_opt_in(self):
        self.build_shards()
        self.pager.select_century_shards(
            self.names, start_year=10000, end_year=10100,
            verify_scope="selected_years",
            competition_id=stage83.stage27.COMP,
        )
        self.assertEqual("selected_years", self.pager.verify_scope)
        self.assertTrue(self.pager.page["all_selected_year_payloads_verified"])
        self.assertTrue(self.pager.page["offpage_derived_memberships_verified"])
        self.assertEqual(36, self.pager.page["total"])
        self.pager.apply_filters(10100, 10100)
        self.assertEqual(7, self.pager.page["total"])
        self.assertEqual(10100, self.pager.page["records"][0]["year"])

    def test_unlisted_shards_or_wrong_year_keep_old_page_filters(self):
        self.build_shards()
        old_page = self.pager.page
        for candidates in (
            self.names[:1], self.names + self.names[:1],
            ("../fake.sqlite3",), ("not_a_century_shard.sqlite3",),
            ("fictional_v2_school_read_index_G10000_G10099_miss.sqlite3",),
        ):
            with self.subTest(candidates=candidates), self.assertRaises(ValueError):
                self.pager.select_century_shards(
                    candidates, start_year=10000, end_year=10100,
                )
            self.assertIs(old_page, self.pager.page)
            self.assertEqual("original_json1", self.pager.lookup_mode)
            self.assertEqual((10000, 10000), (
                self.pager.start_year, self.pager.end_year,
            ))
            self.assertEqual((), self.pager.century_index_paths)

    def test_switch_back_to_original_is_not_unverified_fallback(self):
        self.build_shards()
        self.pager.select_century_shards(
            self.names, start_year=10000, end_year=10100,
        )
        saved = self.pager.page
        with self.assertRaises(ValueError):
            # The 101-year range cannot be scanned by the old <=100-year API.
            self.pager.select_lookup("original_json1")
        self.assertEqual("century_shards", self.pager.lookup_mode)
        self.assertIs(saved, self.pager.page)
        self.pager.apply_filters(10000, 10000)
        original = self.pager.select_lookup("original_json1")
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertEqual(29, original["total"])
        self.assertEqual(29, len(original["records"]))

    def test_corrupted_shard_after_activation_rejects_next_page_atomically(self):
        self.build_shards()
        self.pager.select_century_shards(
            self.names, start_year=10000, end_year=10100,
        )
        old = self.pager.page
        with sqlite3.connect(self.paths[1]) as con:
            con.execute("UPDATE meta SET source_path='different-save'")
        before = self.hashes()
        with self.assertRaises(ValueError):
            self.pager.move(1)
        self.assertIs(old, self.pager.page)
        self.assertEqual(0, self.pager.offset)
        self.assertEqual(before, self.hashes())

    def test_duplicate_shard_over_limit_and_bad_flags_are_rejected(self):
        self.build_shards()
        for inputs in (
            (), self.names * 17, ("bad",), (True,),
        ):
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                self.pager.select_century_shards(
                    inputs, start_year=10000, end_year=10100,
                )
        self.assertEqual("original_json1", self.pager.lookup_mode)


@unittest.skipUnless(DISPLAY, "real Tk or Xvfb display required")
class Stage43G84CenturyTkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage83.Stage43G83ShardedV2Tests(
            "test_two_centuries_order_29_plus_7_and_global_30_page",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture._populate()
        self.pager = CareerV2SchoolGamePager(
            self.fixture.source, self.fixture.calendar,
            stage83.stage27.FIRST, 10000,
        )
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.window = CareerLegacySchoolGamesTkPilot(self.root, self.pager)
        self.addCleanup(lambda: self.window.root.destroy()
                        if self.window.root.winfo_exists() else None)

    def make_indexes(self):
        self.fixture._build()
        return tuple(path.name for path in self.fixture.index_paths)

    def before_files(self):
        return {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in self.fixture.fixture.root.glob("*.sqlite3")
        }

    def test_real_tk_cross_century_30_plus_6_and_sha_scope(self):
        baseline = self.before_files()
        self.assertFalse(hasattr(self.window, "legacy_cross_index_box"))
        self.assertEqual("original_json1", self.window.lookup_var.get())
        names = self.make_indexes()
        self.window.start_var.set("10000")
        self.window.end_var.set("10100")
        self.window.century_files_var.set(" ".join(names))
        self.window.century_apply_button.invoke()
        self.assertIsNone(self.window.last_error)
        self.assertEqual("century_shards", self.pager.lookup_mode)
        self.assertEqual(36, self.pager.page["total"])
        self.assertEqual(30, len(self.window.rows_by_widget_id))
        self.assertIn("年代横断索引2件", self.window.status_var.get())
        self.assertIn("厳密照合済み", self.window.century_status_var.get())
        self.window.next_button.invoke()
        self.assertEqual(30, self.pager.offset)
        self.assertEqual(6, len(self.window.rows_by_widget_id))
        self.assertTrue(all(r["game_day_token"].startswith("G10100:")
                            for r in self.window.rows_by_widget_id.values()))
        self.window.scope_var.set("selected_years")
        self.window.search_button.invoke()
        self.assertIsNone(self.window.last_error)
        self.assertTrue(self.pager.page["all_selected_year_payloads_verified"])
        self.assertEqual(baseline, {
            k: v for k, v in self.before_files().items() if k in baseline
        })

    def test_missing_shard_in_ui_retains_previous_results(self):
        self.make_indexes()
        self.window.start_var.set("10000")
        self.window.end_var.set("10100")
        self.window.century_files_var.set(
            self.fixture.index_paths[0].name,
        )
        old_page = self.pager.page
        self.window.century_apply_button.invoke()
        self.assertIsNotNone(self.window.last_error)
        self.assertIs(old_page, self.pager.page)
        self.assertEqual("original_json1", self.window.lookup_var.get())
        self.assertIn("切替は拒否", self.window.century_status_var.get())
        self.assertEqual(29, len(self.window.rows_by_widget_id))

    def test_legacy_tk_retains_no_v2_century_controls(self):
        parent = self.root
        fake = stage77.Stage43G77HistoryTkTests(
            "test_legacy_selected_year_still_has_only_legacy_button",
        )
        fake.setUp()
        self.addCleanup(fake.doCleanups)
        bridge = fake.gui.bridge
        bridge.open_year(2026)
        bridge.open_school(2026, fake.fixture.a)
        fake.gui._render()
        fake.gui.legacy_games_button.invoke()
        legacy = fake.gui.legacy_window
        self.assertIsNotNone(legacy)
        self.assertFalse(legacy.is_v2)
        self.assertIsNone(legacy.century_files_var)
        self.assertFalse(hasattr(legacy, "century_apply_button"))


if __name__ == "__main__":
    unittest.main()
