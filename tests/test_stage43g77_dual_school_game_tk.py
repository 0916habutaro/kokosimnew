"""Stage43G-77: source-gated dual archive Tk school game search.

All fixtures are saved fictional A records. No official baseball results are
simulated by these GUI tests.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import sys
import tkinter as tk
import unittest

from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_history_tk_pilot import CareerHistoryTkPilot
from phase2_engine.career_legacy_school_game_tk import _year
from phase2_engine.career_v2_school_game_tk import CareerV2SchoolGamePager
import test_stage43g27_v2_option_a_archive as stage27
import test_stage43g65_save_school_history_navigation as stage65

DISPLAY = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G77V2PagerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage27.Stage43G27V2OptionASidecarTests(
            "test_10000_full_a_match_sealed_and_readonly_paged",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.sidecar.append(10000, stage27.full_a(10000, "V2-FIRST"))
        self.fixture.sidecar.append(
            10000, stage27.full_a(10000, "V2-SECOND", "04-02"),
        )
        self.fixture.sidecar.seal_year(10000, expected_match_count=2)
        self.pager = CareerV2SchoolGamePager(
            self.fixture.v2_file, self.fixture.calendar_file,
            stage27.FIRST, 10000,
        )

    def test_pager_preserves_v2_token_and_source(self):
        before = (
            file_sha256(self.fixture.v2_file),
            file_sha256(self.fixture.calendar_file),
        )
        self.assertEqual(2, self.pager.page["total"])
        self.assertTrue(all(row["game_day_token"].startswith("G10000:")
                            for row in self.pager.page["records"]))
        self.assertFalse(self.pager.page["legacy_records_combined"])
        self.assertEqual("fictional_option_a_v2", self.pager.source_kind)
        strict = self.pager.apply_filters(
            10000, 10000, stage27.COMP, "selected_years",
        )
        self.assertTrue(strict["all_selected_year_payloads_verified"])
        self.assertEqual(self.pager.page, self.pager.move(1))
        self.assertEqual(self.pager.page, self.pager.move(-1))
        self.assertFalse(self.pager.can_next)
        self.assertEqual(before, (
            file_sha256(self.fixture.v2_file),
            file_sha256(self.fixture.calendar_file),
        ))
        self.assertFalse(self.fixture.legacy_file.exists())

    def test_v2_multiple_year_pages_30_plus_one(self):
        from phase2_engine.career_calendar_v2 import explicit_sandbox_plan
        self.fixture.calendar.record(explicit_sandbox_plan(
            10001, {stage27.COMP: ["04-01", "04-02"]},
            approved_for_fictional_game=True,
        ))
        for i in range(29):
            self.fixture.sidecar.append(
                10001, stage27.full_a(10001, f"V2-NEXT-{i:03d}"),
            )
        self.fixture.sidecar.seal_year(10001, expected_match_count=29)
        before = (
            file_sha256(self.fixture.v2_file),
            file_sha256(self.fixture.calendar_file),
        )
        first = self.pager.apply_filters(10000, 10001)
        self.assertEqual(31, first["total"])
        self.assertEqual(30, len(first["records"]))
        self.assertTrue(self.pager.can_next)
        tail = self.pager.move(1)
        self.assertEqual(30, self.pager.offset)
        self.assertEqual(1, len(tail["records"]))
        self.assertEqual(10001, tail["records"][0]["year"])
        self.assertFalse(self.pager.can_next)
        self.assertEqual(tail, self.pager.move(1))
        front = self.pager.move(-1)
        self.assertEqual(0, self.pager.offset)
        self.assertEqual(30, len(front["records"]))
        self.assertEqual(before, (
            file_sha256(self.fixture.v2_file),
            file_sha256(self.fixture.calendar_file),
        ))

    def test_invalid_filters_preserve_current_page(self):
        before = (
            self.pager.start_year, self.pager.end_year,
            self.pager.offset, self.pager.page,
        )
        for start, end, scope in (
            (9999, 10000, "page"),
            (10000, 10100, "page"),
            (True, 10000, "page"),
            (10000, 10000, "filtered_window"),
        ):
            with self.subTest(start=start, end=end, scope=scope):
                with self.assertRaises(ValueError):
                    self.pager.apply_filters(start, end, None, scope)
                self.assertEqual(before, (
                    self.pager.start_year, self.pager.end_year,
                    self.pager.offset, self.pager.page,
                ))
        self.assertEqual(10000, _year("10000", min_year=10000, max_year=None))
        with self.assertRaises(ValueError):
            _year("9999", min_year=10000, max_year=None)

    def test_corrupted_visible_match_fails_closed(self):
        import sqlite3
        with sqlite3.connect(self.fixture.v2_file) as conn:
            conn.execute(
                "UPDATE v2_option_a_matches SET record_sha256='WRONG' "
                "WHERE match_id='V2-FIRST'"
            )
        before = (self.pager.offset, self.pager.page)
        with self.assertRaises(ValueError):
            self.pager.apply_filters(10000, 10000)
        self.assertEqual(before, (self.pager.offset, self.pager.page))


@unittest.skipUnless(DISPLAY, "real Tk or Xvfb display required")
class Stage43G77HistoryTkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage65.Stage43G65SaveSchoolNavigationTests(
            "test_save_year_school_match_player_back_readonly",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.withdraw()
        self.gui = CareerHistoryTkPilot(
            self.root, self.fixture.session.bridge,
            slot_session=self.fixture.session,
        )

    def _sha(self):
        save_root = self.fixture.fixture.root
        return {
            str(p.relative_to(save_root)): sha256(p.read_bytes()).hexdigest()
            for p in save_root.rglob("*.sqlite3*") if p.is_file()
        }

    def _open_v2(self):
        bridge = self.gui.bridge
        bridge.open_year(10000)
        bridge.open_school(10000, self.fixture.a)
        self.gui._render()
        self.assertEqual("disabled", str(self.gui.legacy_games_button["state"]))
        self.assertEqual("normal", str(self.gui.v2_games_button["state"]))
        self.gui.v2_games_button.invoke()
        self.assertIsNotNone(self.gui.v2_window)
        return self.gui.v2_window

    def test_v2_window_has_logical_tokens_and_strict_scope(self):
        before = self._sha()
        child = self._open_v2()
        self.assertTrue(child.is_v2)
        self.assertIn("架空v2", child.status_var.get())
        self.assertIn("G{year}:MM-DD", child.status_var.get())
        self.assertTrue(all(
            row["game_day_token"].startswith("G10000:")
            for row in child.rows_by_widget_id.values()
        ))
        original = child.pager.page
        child.start_var.set("9999")
        child.search_button.invoke()
        self.assertIsNotNone(child.last_error)
        self.assertEqual(original, child.pager.page)
        child.start_var.set("10000")
        child.scope_var.set("selected_years")
        child.search_button.invoke()
        self.assertIsNone(child.last_error)
        self.assertTrue(child.pager.page["all_selected_year_payloads_verified"])
        self.assertIn("全学校・全大会", child.status_var.get())
        self.assertEqual(before, self._sha())

    def test_year_route_and_slot_changes_close_child(self):
        before = self._sha()
        child = self._open_v2()
        self.gui.back_button.invoke()
        self.assertIsNone(self.gui.v2_window)
        self.assertFalse(child.root.winfo_exists())
        # New verified v2 selection produces a new isolated child.
        self.gui.back_button.invoke()
        self.gui.back_button.invoke()
        self.assertEqual("history_year_catalog", self.gui.view["screen"])
        child2 = self._open_v2()
        self.gui.slot_var.set("save_B")
        self.gui._change_slot()
        self.assertIsNone(self.gui.v2_window)
        self.assertFalse(child2.root.winfo_exists())
        self.assertEqual("save_B", self.gui.slot_var.get())
        self.assertEqual(before, self._sha())

    def test_legacy_selected_year_still_has_only_legacy_button(self):
        before = self._sha()
        bridge = self.gui.bridge
        bridge.open_year(2026)
        bridge.open_school(2026, self.fixture.a)
        self.gui._render()
        self.assertEqual("normal", str(self.gui.legacy_games_button["state"]))
        self.assertEqual("disabled", str(self.gui.v2_games_button["state"]))
        self.gui._open_v2_games()
        self.assertIsNone(self.gui.v2_window)
        self.assertIsNotNone(self.gui.last_error)
        self.gui.legacy_games_button.invoke()
        self.assertIsNotNone(self.gui.legacy_window)
        self.assertFalse(self.gui.legacy_window.is_v2)
        self.assertEqual(before, self._sha())


if __name__ == "__main__":
    unittest.main()
