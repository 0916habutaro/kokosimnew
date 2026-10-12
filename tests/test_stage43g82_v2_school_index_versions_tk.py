"""Stage43G-82: per-save v2 school index candidates and explicit GUI choice.

Candidate enumeration cannot grant trust. Every choice strictly verifies
the saved fictional full-A source and all derived membership rows.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import sys
import unittest

from phase2_engine.career_v2_school_index_health import (
    prepare_versioned_v2_school_index,
)
from phase2_engine.career_v2_school_game_tk import CareerV2SchoolGamePager
from phase2_engine.career_v2_school_index_versions import (
    DEFAULT_INDEX_NAME, MAX_VERSIONS, list_v2_school_index_versions,
    verify_v2_school_index_version,
)
from phase2_engine.career_history_scale_benchmark import file_sha256
import test_stage43g81_v2_school_index_health as stage81
import test_stage43g77_dual_school_game_tk as stage77

DISPLAY = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G82VersionSelectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage81.Stage43G81SchoolIndexLifecycleTests(
            "test_current_index_full_strict_source_and_memberships_verified"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.pager = CareerV2SchoolGamePager(
            self.fixture.source, self.fixture.calendar,
            stage81.stage79.stage27.FIRST, 10000,
            index_path=self.fixture.old,
        )

    def snapshots(self):
        return {
            p.name: file_sha256(p)
            for p in self.fixture.fixture.root.glob("*.sqlite3")
        }

    def build_versions(self):
        self.fixture.fixture.build()
        prepare_versioned_v2_school_index(
            self.fixture.source, self.fixture.calendar,
            self.fixture.old, self.fixture.new,
        )

    def test_missing_index_discovery_does_not_generate_or_activate(self):
        before = self.snapshots()
        self.assertEqual((), self.pager.available_index_versions())
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertEqual(self.fixture.old, self.pager.index_path)
        self.assertEqual(before, self.snapshots())
        with self.assertRaises(FileNotFoundError):
            self.pager.select_index_version(DEFAULT_INDEX_NAME)
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertEqual(before, self.snapshots())

    def test_two_versions_both_strict_verified_and_manual_activation(self):
        self.build_versions()
        before = self.snapshots()
        names = self.pager.available_index_versions()
        self.assertEqual((
            "fictional_v2_school_read_index.sqlite3",
            "fictional_v2_school_read_index_20261012.sqlite3",
        ), names)
        data = self.pager.select_index_version(self.fixture.new.name)
        self.assertEqual("ready", data["status"])
        self.assertTrue(data["strict_original_payloads_verified"])
        self.assertTrue(data["not_automatically_activated"])
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertEqual(self.fixture.new, self.pager.index_path)
        saved = self.pager.page
        self.pager.select_lookup("separate_index")
        self.assertEqual(saved["records"], self.pager.page["records"])
        self.assertEqual("separate_index", self.pager.lookup_mode)
        self.assertEqual(before, self.snapshots())
        second = self.pager.select_index_version(DEFAULT_INDEX_NAME)
        self.assertEqual("ready", second["status"])
        self.assertEqual(self.fixture.old, self.pager.index_path)
        self.assertEqual("separate_index", self.pager.lookup_mode)
        self.assertEqual(saved["records"], self.pager.page["records"])
        self.assertEqual(before, self.snapshots())

    def test_stale_old_index_rejected_until_explicit_new_version_selected(self):
        self.fixture.fixture.build()
        self.fixture._append_next_year()
        # Caller consciously constructs a *new* version, never overwrites old.
        refreshed = self.fixture._refresh()
        self.assertEqual("ready", refreshed["new_index_status"])
        before = self.snapshots()
        original_path = self.pager.index_path
        with self.assertRaisesRegex(ValueError, "extension_required"):
            self.pager.select_index_version(DEFAULT_INDEX_NAME)
        self.assertEqual(original_path, self.pager.index_path)
        new = self.pager.select_index_version(self.fixture.new.name)
        self.assertEqual(3, len(new["indexed_saved_years"]))
        self.pager.select_lookup("separate_index")
        page = self.pager.apply_filters(10000, 10002)
        self.assertEqual(6, page["total"])
        self.assertEqual(before, self.snapshots())

    def test_active_index_invalid_alternative_keeps_current_selection(self):
        self.build_versions()
        self.pager.select_lookup("separate_index")
        old_page = self.pager.page
        old_path = self.pager.index_path
        with sqlite3.connect(self.fixture.new) as conn:
            conn.execute("UPDATE meta SET source_path='/another-save/source.sqlite3'")
        before = self.snapshots()
        with self.assertRaisesRegex(ValueError, "integrity_conflict"):
            self.pager.select_index_version(self.fixture.new.name)
        self.assertIs(self.pager.page, old_page)
        self.assertEqual(self.pager.index_path, old_path)
        self.assertEqual("separate_index", self.pager.lookup_mode)
        self.assertEqual(before, self.snapshots())

    def test_reject_traversal_invalid_name_and_wrong_slot_provenance(self):
        self.build_versions()
        path = self.pager.index_path
        for candidate in (
            "../fictional_v2_school_read_index.sqlite3",
            "other.sqlite3", "/tmp/foreign.sqlite3",
            "fictional_v2_school_read_index_../x.sqlite3",
            "fictional_v2_school_read_index_.sqlite3",
        ):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.pager.select_index_version(candidate)
        self.assertEqual(path, self.pager.index_path)
        self.assertEqual(
            self.fixture.new.name,
            verify_v2_school_index_version(
                self.fixture.source, self.fixture.calendar,
                self.fixture.new.name,
            )["filename"],
        )

    def test_symlink_escape_rejected_and_not_listed(self):
        self.fixture.fixture.build()
        escape = self.fixture.fixture.root / "fictional_v2_school_read_index_escape.sqlite3"
        try:
            escape.symlink_to(self.fixture.old)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        self.assertNotIn(escape.name, self.pager.available_index_versions())
        with self.assertRaises(ValueError):
            self.pager.select_index_version(escape.name)

    def test_bounded_version_discovery_rejects_over_limit(self):
        for i in range(MAX_VERSIONS + 1):
            (self.fixture.fixture.root / (
                f"fictional_v2_school_read_index_TEST_{i:03d}.sqlite3"
            )).write_bytes(b"not actual SQLite")
        before = self.snapshots()
        with self.assertRaisesRegex(ValueError, "too many"):
            self.pager.available_index_versions()
        self.assertEqual(before, self.snapshots())
        self.assertEqual("original_json1", self.pager.lookup_mode)


@unittest.skipUnless(DISPLAY, "real Tk or Xvfb display required")
class Stage43G82TkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage77.Stage43G77HistoryTkTests(
            "test_v2_window_has_logical_tokens_and_strict_scope"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.slot = self.fixture.fixture.fixture.a_slot

    def _source_snapshots(self):
        return {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in self.slot.glob("*.sqlite3")
            if "index" not in p.name
        }

    def _build_versions(self):
        source = self.slot / "fictional_option_a_v2.sqlite3"
        calendar = self.slot / "sandbox_calendar_v2.sqlite3"
        old = self.slot / DEFAULT_INDEX_NAME
        new = self.slot / "fictional_v2_school_read_index_20261012.sqlite3"
        from phase2_engine.career_v2_school_read_index import build_v2_school_read_index
        build_v2_school_read_index(
            source, calendar, old, start_year=10000, end_year=10000,
        )
        prepare_versioned_v2_school_index(source, calendar, old, new)
        return old, new

    def test_gui_version_refresh_and_manual_source_activation(self):
        before = self._source_snapshots()
        child = self.fixture._open_v2()
        self.assertEqual((), tuple(child.index_version_box["values"]))
        self.assertIn("未検証", child.index_version_status_var.get())
        old, new = self._build_versions()
        child.refresh_versions_button.invoke()
        self.assertIn(new.name, tuple(child.index_version_box["values"]))
        self.assertIn(old.name, tuple(child.index_version_box["values"]))
        self.assertEqual("original_json1", child.pager.lookup_mode)
        original_rows = list(child.rows_by_widget_id.values())
        child.index_version_var.set(new.name)
        child._change_index_version()
        self.assertIsNone(child.last_error)
        self.assertEqual(new, child.pager.index_path)
        self.assertIn("厳密検証済み", child.index_version_status_var.get())
        self.assertEqual("original_json1", child.pager.lookup_mode)
        child.lookup_var.set("separate_index")
        child._change_lookup()
        self.assertEqual("separate_index", child.pager.lookup_mode)
        self.assertEqual(original_rows, list(child.rows_by_widget_id.values()))
        child.index_version_var.set(old.name)
        child._change_index_version()
        self.assertIsNone(child.last_error)
        self.assertEqual(old, child.pager.index_path)
        self.assertEqual(before, self._source_snapshots())

    def test_gui_reject_corrupt_version_and_slot_change_closes_child(self):
        old, new = self._build_versions()
        child = self.fixture._open_v2()
        child.refresh_versions_button.invoke()
        with sqlite3.connect(new) as conn:
            conn.execute("UPDATE meta SET calendar_path='different-slot'")
        before = self._source_snapshots()
        old_page = child.pager.page
        old_path = child.pager.index_path
        child.index_version_var.set(new.name)
        child._change_index_version()
        self.assertIsNotNone(child.last_error)
        self.assertIn("索引版を拒否", child.index_version_status_var.get())
        self.assertIs(old_page, child.pager.page)
        self.assertEqual(old_path, child.pager.index_path)
        self.assertEqual(old.name, child.index_version_var.get())
        self.fixture.gui.slot_var.set("save_B")
        self.fixture.gui._change_slot()
        self.assertIsNone(self.fixture.gui.v2_window)
        self.assertFalse(child.root.winfo_exists())
        self.assertEqual(before, self._source_snapshots())

    def test_legacy_window_never_offers_version_selection(self):
        bridge = self.fixture.gui.bridge
        bridge.open_year(2026)
        bridge.open_school(2026, self.fixture.fixture.a)
        self.fixture.gui._render()
        self.fixture.gui.legacy_games_button.invoke()
        legacy = self.fixture.gui.legacy_window
        self.assertIsNotNone(legacy)
        self.assertFalse(legacy.is_v2)
        self.assertIsNone(legacy.index_version_var)
        self.assertFalse(hasattr(legacy, "index_version_box"))


if __name__ == "__main__":
    unittest.main()
