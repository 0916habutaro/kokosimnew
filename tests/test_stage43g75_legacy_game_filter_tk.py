"""Stage43G-75: 30-game legacy search controller and real Tk read-only UI."""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import tkinter as tk
import unittest

from phase2_engine.career_history_scale_benchmark import (
    build_synthetic_archive, file_sha256,
)
from phase2_engine.career_history_tk_pilot import CareerHistoryTkPilot
from phase2_engine.career_legacy_school_game_tk import (
    CareerLegacySchoolGamePager, CareerLegacySchoolGamesTkPilot, _year,
)
import test_stage43g65_save_school_history_navigation as stage65

DISPLAY = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G75PagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.match = Path(self.tmp.name) / "historical_matches.sqlite3"
        self.other = Path(self.tmp.name) / "fictional_option_a_v2.sqlite3"
        build_synthetic_archive(
            self.match, schools=4, years=20, games_per_school_year=4,
        )
        self.school = "BENCH-SCH-0001"
        self.pager = CareerLegacySchoolGamePager(
            self.match, self.school, 2026,
        )

    def test_school_year_competition_and_forward_back_30(self):
        before = file_sha256(self.match)
        self.assertEqual(4, self.pager.page["total"])
        self.assertFalse(self.pager.can_next)
        all_years = self.pager.apply_filters(
            2026, 2045, "BENCH-CMP-A",
        )
        self.assertEqual(40, all_years["total"])
        self.assertEqual(30, len(all_years["records"]))
        self.assertTrue(self.pager.can_next)
        self.assertFalse(self.pager.can_previous)
        self.pager.move(1)
        self.assertEqual(30, self.pager.offset)
        self.assertEqual(10, len(self.pager.page["records"]))
        self.assertFalse(self.pager.can_next)
        self.assertEqual(self.pager.page, self.pager.move(1))
        self.pager.move(-1)
        self.assertEqual(0, self.pager.offset)
        self.assertEqual(self.pager.page, self.pager.move(-1))
        self.assertEqual("page", self.pager.page["verification_scope"])
        self.assertFalse(self.pager.page["all_filtered_window_checksums_verified"])
        self.assertTrue(all(
            item["school_id"] == self.school
            and item["competition_id"] == "BENCH-CMP-A"
            for item in self.pager.page["records"]
        ))
        self.assertEqual(before, file_sha256(self.match))
        self.assertFalse(self.other.exists())

    def test_filter_validation_rolls_back_current_page(self):
        self.pager.apply_filters(2026, 2045)
        self.pager.move(1)
        before = (
            self.pager.start_year, self.pager.end_year,
            self.pager.competition_id, self.pager.offset, self.pager.page,
        )
        for start, end, comp, scope in [
            (2045, 2026, None, "page"),
            (2026, 10000, None, "page"),
            (True, 2045, None, "page"),
            (2026, 2045, "", "page"),
            (2026, 2045, None, "unknown"),
        ]:
            with self.subTest(start=start, end=end, scope=scope):
                with self.assertRaises(ValueError):
                    self.pager.apply_filters(start, end, comp, scope)
                self.assertEqual(before, (
                    self.pager.start_year, self.pager.end_year,
                    self.pager.competition_id, self.pager.offset,
                    self.pager.page,
                ))
        with self.assertRaises(ValueError):
            self.pager.move(2)
        for value in ("10000", "-1", "2026.0", "２０２６", ""):
            with self.assertRaises(ValueError):
                _year(value)

    def test_offpage_sha_scope_and_failed_strict_filter_are_atomic(self):
        self.pager.apply_filters(2026, 2045)
        unchanged = self.pager.page
        with sqlite3.connect(self.match) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='BAD' "
                "WHERE team1_id=? AND year=2045",
                (self.school,),
            )
        altered = file_sha256(self.match)
        self.assertEqual(
            unchanged["records"], self.pager.apply_filters(
                2026, 2045, None, "page",
            )["records"],
        )
        self.assertFalse(self.pager.page["all_filtered_window_checksums_verified"])
        before = (self.pager.offset, self.pager.page, self.pager.verify_scope)
        with self.assertRaises(ValueError):
            self.pager.apply_filters(2026, 2045, None, "filtered_window")
        self.assertEqual(
            before, (self.pager.offset, self.pager.page, self.pager.verify_scope),
        )
        self.assertEqual(altered, file_sha256(self.match))

    def test_strict_scope_and_missing_source_read_only(self):
        digest = file_sha256(self.match)
        page = self.pager.apply_filters(
            2026, 2045, "BENCH-CMP-B", "filtered_window",
        )
        self.assertEqual(40, page["total"])
        self.assertTrue(page["all_filtered_window_checksums_verified"])
        self.assertEqual(digest, file_sha256(self.match))
        missing = Path(self.tmp.name) / "missing.sqlite3"
        empty = CareerLegacySchoolGamePager(missing, self.school, 2026)
        self.assertEqual(0, empty.page["total"])
        self.assertFalse(missing.exists())

    def test_requested_page_integrity_blocks_advancement(self):
        self.pager.apply_filters(2026, 2045)
        before = (self.pager.offset, self.pager.page)
        with sqlite3.connect(self.match) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='BAD' "
                "WHERE team1_id=? AND year=2034",
                (self.school,),
            )
        # Offset=30 begins in year2033: the corrupted next page must fail.
        with self.assertRaises(ValueError):
            self.pager.move(1)
        self.assertEqual(before, (self.pager.offset, self.pager.page))


@unittest.skipUnless(DISPLAY, "real Tk/Xvfb display required")
class Stage43G75TkTests(unittest.TestCase):
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

    def _sqlite_hashes(self):
        return {
            str(p.relative_to(self.fixture.root)):
                sha256(p.read_bytes()).hexdigest()
            for p in self.fixture.root.rglob("*.sqlite3*") if p.is_file()
        }

    def _open_legacy(self):
        bridge = self.gui.bridge
        bridge.open_year(2026)
        bridge.open_school(2026, self.fixture.a)
        self.gui._render()
        self.assertEqual("normal", str(self.gui.legacy_games_button["state"]))
        self.gui.legacy_games_button.invoke()
        self.assertIsNotNone(self.gui.legacy_window)
        return self.gui.legacy_window

    def test_tk_search_error_and_navigation_window_closure(self):
        before = self._sqlite_hashes()
        child = self._open_legacy()
        self.assertEqual(self.fixture.a, child.pager.school_id)
        self.assertEqual(2026, child.pager.start_year)
        initial = child.pager.page
        child.end_var.set("10000")
        child.search_button.invoke()
        self.assertEqual(initial, child.pager.page)
        self.assertIsNotNone(child.last_error)
        child.end_var.set("2026")
        child.search_button.invoke()
        self.assertIsNone(child.last_error)
        self.assertIn("表示ページのみSHA照合済み", child.status_var.get())
        self.gui.back_button.invoke()
        self.assertIsNone(self.gui.legacy_window)
        self.assertFalse(child.root.winfo_exists())
        self.assertEqual(before, self._sqlite_hashes())

    def test_v2_school_never_enables_legacy_search(self):
        before = self._sqlite_hashes()
        child = self._open_legacy()
        self.gui.back_button.invoke()
        self.gui.back_button.invoke()
        self.gui.back_button.invoke()
        self.assertEqual("history_year_catalog", self.gui.view["screen"])
        bridge = self.gui.bridge
        bridge.open_year(10000)
        school = bridge.page["data"]["schools"][0]["school_id"]
        bridge.open_school(10000, school)
        self.gui._render()
        self.assertEqual("disabled", str(self.gui.legacy_games_button["state"]))
        self.gui._open_legacy_games()
        self.assertIsNone(self.gui.legacy_window)
        self.assertIsNotNone(self.gui.last_error)
        self.assertEqual(before, self._sqlite_hashes())

    def test_slot_switch_closes_old_search_without_mutating_saves(self):
        before = self._sqlite_hashes()
        child = self._open_legacy()
        self.gui.slot_var.set("save_B")
        self.gui._change_slot()
        self.assertEqual("save_B", self.gui.slot_var.get())
        self.assertIsNone(self.gui.legacy_window)
        self.assertFalse(child.root.winfo_exists())
        self.assertEqual("history_year_catalog", self.gui.view["screen"])
        self.assertEqual(before, self._sqlite_hashes())


if __name__ == "__main__":
    unittest.main()
