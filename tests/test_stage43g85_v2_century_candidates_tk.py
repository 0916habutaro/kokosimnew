"""Stage43G-85: opt-in, untrusted preview of in-slot v2 century shards.

All tests use synthetic complete Option-A sealed games and verified source;
no nationwide simulated progression is claimed.
"""
from __future__ import annotations

from hashlib import sha256
import os
import sys
from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_calendar_v2 import explicit_sandbox_plan
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_school_century_candidates import (
    MAX_CANDIDATE_FILES,
    preview_v2_school_century_candidates,
    stage_explicit_century_candidate_names,
)
import test_stage43g83_v2_century_shards as stage83
import test_stage43g84_v2_cross_century_tk as stage84

DISPLAY = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G85CenturyCandidateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage83.Stage43G83ShardedV2Tests(
            "test_two_centuries_order_29_plus_7_and_global_30_page",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture._populate()

    def preview(self, start=10000, end=10100):
        return preview_v2_school_century_candidates(
            self.fixture.source, self.fixture.calendar,
            start_year=start, end_year=end,
        )

    def hashes(self):
        return {
            f.name: file_sha256(f)
            for f in self.fixture.fixture.root.glob("*.sqlite3")
        }

    def test_preview_unbuilt_centuries_reports_missing_without_writes(self):
        before = self.hashes()
        report = self.preview()
        self.assertEqual([10000, 10100], report["saved_years"])
        self.assertEqual([10000, 10100], report["missing_window_starts"])
        self.assertEqual(0, report["candidate_count"])
        self.assertEqual([], report["unsealed_saved_years"])
        self.assertTrue(report["candidate_source_integrity_not_verified"])
        self.assertTrue(report["no_implicit_generation_or_activation"])
        self.assertEqual(before, self.hashes())
        with self.assertRaisesRegex(ValueError, "exactly one candidate"):
            stage_explicit_century_candidate_names(report, [])

    def test_two_centuries_and_versions_are_explicit_one_per_saved_bucket(self):
        self.fixture._build()
        old = tuple(x.name for x in self.fixture.index_paths)
        versioned = self.fixture._build(version="v02")
        newer = tuple(Path(x["index_path"]).name for x in versioned["shards"])
        before = self.hashes()
        report = self.preview()
        self.assertEqual(4, report["candidate_count"])
        self.assertEqual([], report["missing_window_starts"])
        self.assertEqual([2, 2], [
            len(x["candidate_names"]) for x in report["required_windows"]
        ])
        selection = stage_explicit_century_candidate_names(
            report, [newer[1], old[0]],
        )
        self.assertEqual((old[0], newer[1]), selection)
        for invalid in (
            [old[0]],
            [old[0], newer[0]],
            [newer[0], old[0], newer[1]],
            [old[0], old[0]],
            ["../" + old[0], old[1]],
            ["wrong-save.sqlite3", old[1]],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                stage_explicit_century_candidate_names(report, invalid)
        self.assertEqual(before, self.hashes())

    def test_filename_candidate_is_not_integrity_approval(self):
        self.fixture._build()
        old = self.fixture.index_paths[:]
        fake = self.fixture.fixture.root / (
            "fictional_v2_school_read_index_G10000_G10099_bad.sqlite3"
        )
        fake.write_bytes(b"intentionally invalid SQLite")
        report = self.preview()
        self.assertIn(fake.name, report["required_windows"][0]["candidate_names"])
        staged = stage_explicit_century_candidate_names(
            report, [fake.name, old[1].name],
        )
        self.assertEqual(fake.name, staged[0])
        from phase2_engine.career_v2_school_game_tk import CareerV2SchoolGamePager
        pager = CareerV2SchoolGamePager(
            self.fixture.source, self.fixture.calendar,
            stage83.stage27.FIRST, 10000,
        )
        old_page = pager.page
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            pager.select_century_shards(
                staged, start_year=10000, end_year=10100,
            )
        self.assertIs(old_page, pager.page)
        self.assertEqual("original_json1", pager.lookup_mode)
        self.assertFalse(self.fixture.fixture.legacy_file.exists())

    def test_unsealed_year_reported_and_staging_denied(self):
        self.fixture._build()
        self.fixture.fixture.calendar.record(explicit_sandbox_plan(
            10101, {stage83.stage27.COMP: ["04-01"]},
            approved_for_fictional_game=True,
        ))
        self.fixture.fixture.sidecar.append(
            10101, stage83.stage27.full_a(10101, "PENDING"),
        )
        before = self.hashes()
        report = self.preview(end=10101)
        self.assertEqual([10101], report["unsealed_saved_years"])
        self.assertEqual([], report["missing_window_starts"])
        with self.assertRaisesRegex(ValueError, "unsealed"):
            stage_explicit_century_candidate_names(
                report, [x.name for x in self.fixture.index_paths],
            )
        self.assertEqual(before, self.hashes())

    def test_symlinks_invalid_years_and_bounded_scan(self):
        self.fixture._build()
        original = self.fixture.index_paths[0]
        link = self.fixture.fixture.root / (
            "fictional_v2_school_read_index_G10000_G10099_link.sqlite3"
        )
        try:
            link.symlink_to(original)
        except (OSError, NotImplementedError):
            pass
        report = self.preview()
        self.assertNotIn(link.name, report["required_windows"][0]["candidate_names"])
        for bounds in ((9999, 10000), (10100, 10000), (10000, 13200),
                       (True, 10100)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                self.preview(*bounds)
        # Candidates from an unrelated slot cannot leak into this slot.
        other = self.fixture.fixture.root / "other-save"
        other.mkdir()
        (other / "fictional_v2_school_read_index_G10000_G10099_x.sqlite3").write_bytes(
            b"foreign"
        )
        self.assertEqual(2, self.preview()["candidate_count"])
        for i in range(MAX_CANDIDATE_FILES):
            (self.fixture.fixture.root /
             f"fictional_v2_school_read_index_G10000_G10099_Z{i:04}.sqlite3"
            ).write_bytes(b"candidate only")
        with self.assertRaisesRegex(ValueError, "too many"):
            self.preview()


@unittest.skipUnless(DISPLAY, "real Tk or Xvfb display required")
class Stage43G85CenturyCandidateTkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage84.Stage43G84CenturyTkTests(
            "test_real_tk_cross_century_30_plus_6_and_sha_scope",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.child = self.fixture.window
        self.pager = self.fixture.pager

    def _names_and_widgets(self):
        self.fixture.make_indexes()
        self.child.start_var.set("10000")
        self.child.end_var.set("10100")
        self.child._preview_century_candidates()
        ids = list(self.child.century_candidates_by_widget_id)
        return ids, list(self.child.century_candidates_by_widget_id.values())

    def test_preview_never_activates_and_manual_choice_builds_30_plus_6(self):
        before = self.fixture.before_files()
        self.child.start_var.set("10000")
        self.child.end_var.set("10100")
        self.child._preview_century_candidates()
        self.assertIsNone(self.child.last_error)
        self.assertIn("欠落2件", self.child.century_candidate_status_var.get())
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertEqual("", self.child.century_files_var.get())
        ids, names = self._names_and_widgets()
        self.assertEqual(2, len(ids))
        self.assertEqual(2, len(names))
        self.assertIn("未検証", self.child.century_candidate_status_var.get())
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.child.century_candidates_tree.selection_set(*ids)
        self.child.stage_century_candidates_button.invoke()
        self.assertIsNone(self.child.last_error)
        self.assertEqual(" ".join(names), self.child.century_files_var.get())
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertIn("未検証", self.child.century_candidate_status_var.get())
        self.child.century_apply_button.invoke()
        self.assertIsNone(self.child.last_error)
        self.assertEqual("century_shards", self.pager.lookup_mode)
        self.assertEqual(36, self.pager.page["total"])
        self.assertEqual(30, len(self.child.rows_by_widget_id))
        self.child.next_button.invoke()
        self.assertEqual(30, self.pager.offset)
        self.assertEqual(6, len(self.child.rows_by_widget_id))
        self.assertEqual(before, {
            k: v for k, v in self.fixture.before_files().items() if k in before
        })

    def test_partial_selection_and_filter_changes_preserve_page(self):
        ids, names = self._names_and_widgets()
        old = self.pager.page
        self.child.century_files_var.set("previous text")
        self.child.century_candidates_tree.selection_set(ids[0])
        self.child.stage_century_candidates_button.invoke()
        self.assertIsNotNone(self.child.last_error)
        self.assertEqual("previous text", self.child.century_files_var.get())
        self.assertIs(self.pager.page, old)
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.child.century_candidates_tree.selection_set(*ids)
        self.child.end_var.set("10099")
        self.child.stage_century_candidates_button.invoke()
        self.assertIsNotNone(self.child.last_error)
        self.assertIn("再読込", self.child.century_candidate_status_var.get())
        self.assertEqual("previous text", self.child.century_files_var.get())
        self.assertIs(self.pager.page, old)

    def test_forged_index_candidate_stays_untrusted_and_rolls_back(self):
        ids, names = self._names_and_widgets()
        fake = self.fixture.fixture.fixture.root / (
            "fictional_v2_school_read_index_G10000_G10099_Zfake.sqlite3"
        )
        fake.write_bytes(b"not an actual SQLite")
        self.child._preview_century_candidates()
        names_by_id = self.child.century_candidates_by_widget_id
        chosen = [
            wid for wid, name in names_by_id.items()
            if name == fake.name or name == names[1]
        ]
        self.assertEqual(2, len(chosen))
        self.child.century_candidates_tree.selection_set(*chosen)
        self.child.stage_century_candidates_button.invoke()
        self.assertIsNone(self.child.last_error)
        before_page = self.pager.page
        self.child.century_apply_button.invoke()
        self.assertIsNotNone(self.child.last_error)
        self.assertIs(before_page, self.pager.page)
        self.assertEqual("original_json1", self.pager.lookup_mode)
        self.assertIn("切替は拒否", self.child.century_status_var.get())

    def test_legacy_does_not_have_candidate_picker(self):
        from phase2_engine.career_legacy_school_game_tk import (
            CareerLegacySchoolGamesTkPilot,
        )
        import test_stage43g77_dual_school_game_tk as stage77
        prev = stage77.Stage43G77HistoryTkTests(
            "test_legacy_selected_year_still_has_only_legacy_button",
        )
        prev.setUp()
        self.addCleanup(prev.doCleanups)
        bridge = prev.gui.bridge
        bridge.open_year(2026)
        bridge.open_school(2026, prev.fixture.a)
        prev.gui._render()
        prev.gui.legacy_games_button.invoke()
        legacy = prev.gui.legacy_window
        self.assertFalse(legacy.is_v2)
        self.assertFalse(hasattr(legacy, "century_candidates_tree"))


if __name__ == "__main__":
    unittest.main()
