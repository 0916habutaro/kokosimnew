"""Stage43G-36: formatted match tables, bounded rendering, linear v2 verification."""
from __future__ import annotations

from unittest import mock
import os
import sqlite3
import sys
import unittest

import test_stage43g31_cross_era_browse_model as fixtures
from phase2_engine.career_cross_era_browse_model import CareerCrossEraBrowseModel
from phase2_engine.career_cross_era_gui_pilot import (
    CareerCrossEraGuiPilot, MATCH_PAGE_SIZE, MATCH_HEADINGS,
)
from phase2_engine.career_cross_era_navigation import CareerCrossEraNavigator
from phase2_engine.career_history_scale_benchmark import file_sha256

TK_AVAILABLE = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G36MatchTableTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.nav = CareerCrossEraNavigator(self.fixture.root)
        self.years = [2026, 10000]
        self.school = self.fixture.a

    def _source_paths(self):
        return [
            self.fixture.old, self.fixture.v2, self.fixture.calendar,
            self.fixture.rosters.db_path, self.fixture.cache.path,
        ]

    def _v2_detail(self, *, verify_source=True):
        return self.nav.browse.match_detail(
            self.years, self.school, selected_year=10000,
            competition_id=fixtures.COMP, match_id="FUTURE",
            verify_source=verify_source,
        )

    def test_v2_detail_does_not_rescan_paged_year_matches(self):
        with mock.patch.object(
            self.nav.browse.v2, "year_matches",
            side_effect=AssertionError("obsolete annual re-pagination"),
        ):
            with mock.patch.object(
                self.nav.browse.v2, "_verified_year",
                wraps=self.nav.browse.v2._verified_year,
            ) as check:
                result = self._v2_detail()
        self.assertEqual("cross_era_match", result["screen"])
        self.assertEqual("FUTURE", result["match"]["match_id"])
        # Whole-year deep source verification exactly once, plus one
        # indexed per-match fetch and its own SHA/date/identity check.
        self.assertEqual(1, check.call_count)
        self.assertTrue(result["source_payloads_rechecked"])

    def test_shallow_mode_still_checks_requested_match_sha(self):
        with sqlite3.connect(self.fixture.v2) as con:
            con.execute(
                "UPDATE v2_option_a_matches SET payload_json='{}' "
                "WHERE year=10000 AND competition_id=? AND match_id='FUTURE'",
                (fixtures.COMP,),
            )
        with self.assertRaises(ValueError):
            self._v2_detail(verify_source=False)

    def test_wrong_id_rejected_without_unverified_fallback(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            self.nav.browse.match_detail(
                self.years, self.school, selected_year=10000,
                competition_id=fixtures.COMP, match_id="OTHER",
            )

    def test_readonly_archive_bytes_unchanged_after_verified_drilldown(self):
        before = [file_sha256(p) for p in self._source_paths()]
        self._v2_detail()
        self.nav.browse.match_detail(
            self.years, self.school, selected_year=2026,
            competition_id=fixtures.COMP, match_id="OLD",
        )
        self.assertEqual(before, [file_sha256(p) for p in self._source_paths()])

    def test_unstored_fields_are_not_padded_with_zeroes(self):
        self.assertEqual(
            "未収録", CareerCrossEraGuiPilot._saved({}, "strikeouts")
        )
        self.assertEqual(
            "未収録", CareerCrossEraGuiPilot._saved(
                {"hits": None}, "hits",
            ),
        )
        self.assertEqual(
            "0", CareerCrossEraGuiPilot._saved({"hits": 0}, "hits")
        )
        self.assertEqual(
            "未収録", CareerCrossEraGuiPilot._saved({"hits": True}, "hits")
        )
        self.assertEqual(
            "6.2", CareerCrossEraGuiPilot._innings_pitched(
                {"outs_recorded": 20},
            ),
        )
        self.assertEqual(
            "未収録", CareerCrossEraGuiPilot._innings_pitched({}),
        )

    @unittest.skipUnless(TK_AVAILABLE, "Tk window requires DISPLAY or Windows")
    def test_real_tk_renders_stat_columns_and_raw_record_on_selection(self):
        import tkinter as tk

        root = tk.Tk()
        self.addCleanup(root.destroy)
        gui = CareerCrossEraGuiPilot(
            root, self.nav, school_id=self.school, years=self.years,
            selected_year=2026, data_root=fixtures.ROOT / "data",
        )
        game_link = next(
            target for target in gui.links.values()
            if target.get("view") == "match"
        )
        gui._open(game_link)
        self.assertEqual("cross_era_match", gui.controller.page["screen"])
        self.assertEqual(
            len(MATCH_HEADINGS),
            len(root.tk.splitlist(gui.table["displaycolumns"])),
        )
        self.assertEqual("安打／被安打", gui.table.heading("hits", "text"))
        rows = [
            gui.table.item(iid, "values") for iid in gui.table.get_children()
        ]
        self.assertTrue(any(str(row[0]).startswith("打撃 / ") for row in rows))
        self.assertTrue(any(str(row[0]).startswith("投手 / ") for row in rows))
        self.assertIn("保存済み", gui.details.get("1.0", "end"))
        batter_id = next(
            iid for iid in gui.row_details
            if gui.row_details[iid]["section"] == "batter_stats"
        )
        gui.table.selection_set(batter_id)
        gui._show_row_detail()
        self.assertIn("selected_saved_record", gui.details.get("1.0", "end"))
        self.assertIn("player_id", gui.details.get("1.0", "end"))

    @unittest.skipUnless(TK_AVAILABLE, "Tk window requires DISPLAY or Windows")
    def test_tk_match_pagination_limits_insertions_without_rewriting(self):
        import tkinter as tk

        before = [file_sha256(p) for p in self._source_paths()]
        root = tk.Tk()
        self.addCleanup(root.destroy)
        gui = CareerCrossEraGuiPilot(
            root, self.nav, school_id=self.school, years=self.years,
            selected_year=2026, data_root=fixtures.ROOT / "data",
        )
        gui._open(next(
            target for target in gui.links.values()
            if target.get("view") == "match"
        ))
        # Inflate the *in-memory test view only*, never the saved SQLite.
        page = gui.controller.page
        page["details"]["batter_stats"] = (
            page["details"]["batter_stats"] * 15
        )
        gui._render(page)
        self.assertEqual(0, gui.match_offset)
        self.assertLessEqual(len(gui.table.get_children()), MATCH_PAGE_SIZE + 2)
        gui._page(1)
        self.assertEqual(MATCH_PAGE_SIZE, gui.match_offset)
        self.assertLessEqual(len(gui.table.get_children()), MATCH_PAGE_SIZE + 2)
        self.assertIn("81～160", gui.status_var.get())
        gui._page(-1)
        self.assertEqual(0, gui.match_offset)
        gui._back()
        self.assertEqual("cross_era_school", gui.controller.page["screen"])
        self.assertEqual(0, gui.match_offset)
        self.assertEqual(before, [file_sha256(p) for p in self._source_paths()])


if __name__ == "__main__":
    unittest.main()
