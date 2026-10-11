"""Stage43G-37: source-backed school/section filters, safe stat sort and Tk."""
from __future__ import annotations

import os
import sys
import unittest

import test_stage43g31_cross_era_browse_model as fixtures
from phase2_engine.career_cross_era_gui_pilot import (
    CareerCrossEraGuiPilot, MATCH_PAGE_SIZE,
)
from phase2_engine.career_cross_era_navigation import CareerCrossEraNavigator
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_match_table_projection import match_stat_projection

TK_AVAILABLE = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G37MatchStatFiltersTests(unittest.TestCase):
    def setUp(self):
        fx = fixtures.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year"
        )
        fx.setUp()
        self.addCleanup(fx.tearDown)
        fx.setup_both()
        self.fx = fx
        self.nav = CareerCrossEraNavigator(fx.root)
        self.years = [2026, 10000]
        self.page = self.nav.match_page(
            self.years, fx.a, selected_year=2026,
            competition_id=fixtures.COMP, match_id="OLD",
        )

    def paths(self):
        return [
            self.fx.old, self.fx.v2, self.fx.calendar,
            self.fx.rosters.db_path, self.fx.cache.path,
        ]

    def test_sourced_school_and_section_filter(self):
        all_rows = match_stat_projection(self.page)
        self.assertEqual(18 + 2 + 18 + 2, all_rows["total"])
        batters = match_stat_projection(self.page, section="batter_stats")
        self.assertEqual(18, batters["total"])
        team_a = match_stat_projection(
            self.page, school_id=self.fx.a, section="batter_stats",
        )
        self.assertEqual(9, team_a["total"])
        self.assertTrue(all(
            row["school_id"] == self.fx.a and
            row["section"] == "batter_stats" for row in team_a["rows"]
        ))
        team_b = match_stat_projection(
            self.page, school_id=self.fx.b, section="pitcher_stats",
        )
        self.assertEqual(1, team_b["total"])
        self.assertEqual(self.fx.b, team_b["rows"][0]["school_id"])
        self.assertEqual("OLD", self.page["match"]["match_id"])

    def test_sort_is_numeric_stable_and_missing_always_last(self):
        original = self.page["details"]["batter_stats"]
        saved_first = original[0]
        self.assertTrue(original)
        # Extend in-memory projection only. Do not change the archive.
        augmented = {**self.page, "details": {
            **self.page["details"],
            "batter_stats": [
                {"player_id": "PLY-MISSING", "school_id": self.fx.a},
                {"player_id": "PLY-HIGH", "school_id": self.fx.a,
                 "hits": 12, "strikeouts": 3},
                {"player_id": "PLY-TIE1", "school_id": self.fx.a,
                 "hits": 4, "strikeouts": 5},
                {"player_id": "PLY-TIE2", "school_id": self.fx.a,
                 "hits": 4, "strikeouts": 5},
            ],
        }}
        ranked = match_stat_projection(
            augmented, section="batter_stats", sort="hits_desc",
        )
        ids = [r["saved"]["player_id"] for r in ranked["rows"]]
        self.assertEqual(
            ["PLY-HIGH", "PLY-TIE1", "PLY-TIE2", "PLY-MISSING"], ids,
        )
        strikes = match_stat_projection(
            augmented, section="batter_stats", sort="strikeouts_desc",
        )
        self.assertEqual(
            ["PLY-TIE1", "PLY-TIE2", "PLY-HIGH", "PLY-MISSING"],
            [r["saved"]["player_id"] for r in strikes["rows"]],
        )
        self.assertIs(saved_first, original[0])
        self.assertNotIn("hits", augmented["details"]["batter_stats"][0])

    def test_pagination_is_bounded_and_does_not_duplicate_or_infer(self):
        enlarged = {**self.page, "details": {
            **self.page["details"],
            "batter_stats": self.page["details"]["batter_stats"] * 17,
        }}
        a = match_stat_projection(
            enlarged, section="batter_stats", offset=0,
            limit=MATCH_PAGE_SIZE,
        )
        b = match_stat_projection(
            enlarged, section="batter_stats", offset=MATCH_PAGE_SIZE,
            limit=MATCH_PAGE_SIZE,
        )
        self.assertEqual(18 * 17, a["total"])
        self.assertEqual(a["total"], b["total"])
        self.assertEqual(MATCH_PAGE_SIZE, len(a["rows"]))
        self.assertEqual(MATCH_PAGE_SIZE, len(b["rows"]))
        self.assertFalse(a["unrecorded_values_inferred"])
        self.assertFalse(a["original_archive_modified"])

    def test_invalid_school_section_sort_or_page_fails_closed(self):
        for values in (
            {"section": "batter_stats_typo"},
            {"school_id": "FAKE-SCHOOL"},
            {"sort": "dynamic_field"},
            {"offset": -1},
            {"limit": 0},
            {"limit": 101},
            {"limit": True},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                match_stat_projection(self.page, **values)

    def test_projected_filter_does_not_change_any_archive(self):
        before = [file_sha256(p) for p in self.paths()]
        for year, match_id in ((2026, "OLD"), (10000, "FUTURE")):
            page = self.nav.match_page(
                self.years, self.fx.a, selected_year=year,
                competition_id=fixtures.COMP, match_id=match_id,
            )
            for section in ("all", "inning_scores", "team_stats",
                            "batter_stats", "pitcher_stats"):
                for sort in ("saved", "player_id", "hits_desc", "strikeouts_desc"):
                    match_stat_projection(
                        page, section=section, school_id=self.fx.a,
                        sort=sort,
                    )
        self.assertEqual(before, [file_sha256(p) for p in self.paths()])

    @unittest.skipUnless(TK_AVAILABLE, "actual Tk needs Xvfb or Windows")
    def test_real_tk_school_filter_sort_and_reset_on_new_match(self):
        import tkinter as tk
        before = [file_sha256(p) for p in self.paths()]
        root = tk.Tk()
        self.addCleanup(root.destroy)
        gui = CareerCrossEraGuiPilot(
            root, self.nav, school_id=self.fx.a, years=self.years,
            selected_year=2026, data_root=fixtures.ROOT / "data",
        )
        game_link = next(
            target for target in gui.links.values()
            if target.get("view") == "match"
        )
        gui._open(game_link)
        self.assertTrue(gui.match_controls.winfo_manager())
        gui.match_section_var.set("打撃")
        gui.match_school_var.set(gui.labels.school(self.fx.a))
        gui.match_sort_var.set("安打・被安打の多い順")
        gui._change_match_filter()
        self.assertEqual(9, gui._visible_match_total)
        self.assertEqual(11, len(gui.table.get_children()))
        self.assertTrue(all(
            row["section"] == "batter_stats"
            and row["saved"]["school_id"] == self.fx.a
            for row in gui.row_details.values()
        ))
        self.assertIn('"sort": "hits_desc"', gui.details.get("1.0", "end"))
        gui._page(1)
        self.assertEqual(0, gui.match_offset)
        gui._back()
        self.assertFalse(gui.match_controls.winfo_manager())
        gui._open(next(
            target for target in gui.links.values()
            if target.get("view") == "match"
        ))
        self.assertEqual("すべて", gui.match_section_var.get())
        self.assertEqual("両校", gui.match_school_var.get())
        self.assertEqual("保存順", gui.match_sort_var.get())
        self.assertEqual(40, gui._visible_match_total)
        self.assertEqual(before, [file_sha256(p) for p in self.paths()])


if __name__ == "__main__":
    unittest.main()
