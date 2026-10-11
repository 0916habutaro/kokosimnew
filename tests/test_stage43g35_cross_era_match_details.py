"""Stage43G-35: immutable source-specific match details and Tk drilldown."""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest

import test_stage43g31_cross_era_browse_model as fixtures
from phase2_engine.career_cross_era_gui_pilot import (
    CareerCrossEraGuiPilot, CareerCrossEraScreenController,
)
from phase2_engine.career_cross_era_navigation import CareerCrossEraNavigator
from phase2_engine.career_history_scale_benchmark import file_sha256

TK_AVAILABLE = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G35MatchDetailTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.nav = CareerCrossEraNavigator(self.fixture.root)
        self.school = self.fixture.a
        self.years = [2026, 10000]

    def controller(self):
        return CareerCrossEraScreenController(
            self.nav, self.years, self.school, selected_year=2026,
        )

    def test_legacy_match_drilldown_has_saved_option_a_fields(self):
        ctrl = self.controller()
        link = ctrl.page["match_detail_targets"][0]["target"]
        self.assertEqual("match", link["view"])
        result = ctrl.open(link)
        self.assertEqual("cross_era_match", result["screen"])
        self.assertEqual("historical_matches_legacy_iso", result["source"])
        self.assertEqual("YYYY-MM-DD", result["match"]["date_kind"])
        self.assertEqual("OLD", result["match"]["match_id"])
        self.assertEqual("full_option_a_saved", result["detail_status"])
        self.assertEqual([], result["missing_detail_fields"])
        self.assertEqual(18, len(result["details"]["inning_scores"]))
        self.assertEqual(18, len(result["details"]["batter_stats"]))
        self.assertEqual(2, len(result["details"]["pitcher_stats"]))
        self.assertEqual(self.school, ctrl.back()["school_id"])

    def test_old_score_only_match_discloses_absent_detail_without_guessing(self):
        import tempfile
        from pathlib import Path
        from phase2_engine.historical_match_archive import HistoricalMatchArchive

        with tempfile.TemporaryDirectory() as temp:
            archive = HistoricalMatchArchive(
                Path(temp) / "historical_matches.sqlite3"
            )
            row = self.fixture.sample(2026, "SCORE_ONLY")
            row.pop("ability_detail")
            row["score_source"] = "synthetic_final_score_only"
            archive.sync(
                year=2026, rng_seed=17,
                resolver_contract="stage43g35_score_only_fixture",
                plan_fingerprint="legacy-2026-score-only",
                completed=[row],
            )
            archive.seal_year(2026, expected_match_count=1)
            original = file_sha256(archive.db_path)
            detail = CareerCrossEraNavigator(temp).match_page(
                [2026], self.school, selected_year=2026,
                competition_id=row["competition_id"],
                match_id=row["match_id"],
            )
            self.assertEqual("cross_era_match", detail["screen"])
            self.assertEqual("partial_or_score_only_legacy",
                             detail["detail_status"])
            self.assertEqual(
                ["inning_scores", "team_stats", "batter_stats", "pitcher_stats"],
                detail["missing_detail_fields"],
            )
            self.assertTrue(
                all(value is None for value in detail["details"].values())
            )
            self.assertEqual(original, file_sha256(archive.db_path))

    def test_v2_match_keeps_logical_year_and_own_original(self):
        ctrl = self.controller()
        future = ctrl.change_year(10000)
        result = ctrl.open(future["match_detail_targets"][0]["target"])
        self.assertEqual("fictional_option_a_v2", result["source"])
        self.assertEqual("G10000:04-01", result["match"]["date"])
        self.assertEqual("FUTURE", result["match"]["match_id"])
        self.assertEqual("full_option_a_saved", result["detail_status"])
        self.assertFalse(result["combined_career_stats_authorized"])

    def test_switching_year_from_match_returns_school_not_false_game(self):
        ctrl = self.controller()
        ctrl.open(ctrl.page["match_detail_targets"][0]["target"])
        result = ctrl.change_year(10000)
        self.assertEqual("cross_era_school", result["screen"])
        self.assertEqual(10000, result["selected_year"])
        self.assertEqual("OLD", ctrl.back()["match"]["match_id"])

    def test_tampered_match_rejected_without_changing_navigation(self):
        ctrl = self.controller()
        before = (dict(ctrl.target), ctrl.page, list(ctrl.history))
        with sqlite3.connect(self.fixture.old) as conn:
            conn.execute(
                "UPDATE historical_matches SET payload_json='{}' "
                "WHERE year=2026 AND match_id='OLD'"
            )
        link = ctrl.page["match_detail_targets"][0]["target"]
        with self.assertRaises(ValueError):
            ctrl.open(link)
        self.assertEqual(before[0], ctrl.target)
        self.assertIs(before[1], ctrl.page)
        self.assertEqual(before[2], ctrl.history)

    def test_malformed_or_unknown_game_route_rejected(self):
        ctrl = self.controller()
        link = dict(ctrl.page["match_detail_targets"][0]["target"])
        with self.assertRaises(ValueError):
            ctrl.open({**link, "year": 2026})
        with self.assertRaises(ValueError):
            ctrl.open({**link, "match_id": "NOT_SAVED"})
        with self.assertRaises(ValueError):
            ctrl.open({**link, "selected_year": 10000})
        self.assertEqual([], ctrl.history)
        self.assertEqual("cross_era_school", ctrl.page["screen"])

    def test_detail_navigation_never_writes_source_files(self):
        files = [
            self.fixture.old, self.fixture.v2, self.fixture.calendar,
            self.fixture.rosters.db_path, self.fixture.cache.path,
        ]
        before = [file_sha256(path) for path in files]
        ctrl = self.controller()
        ctrl.open(ctrl.page["match_detail_targets"][0]["target"])
        ctrl.change_year(10000)
        ctrl.open(ctrl.page["match_detail_targets"][0]["target"])
        self.assertEqual(before, [file_sha256(path) for path in files])

    @unittest.skipUnless(TK_AVAILABLE, "real Tk needs DISPLAY or Windows")
    def test_real_tk_match_row_opens_detailed_line_scores(self):
        import tkinter as tk

        root = tk.Tk()
        self.addCleanup(root.destroy)
        gui = CareerCrossEraGuiPilot(
            root, self.nav, school_id=self.school, years=self.years,
            selected_year=2026, data_root=fixtures.ROOT / "data",
        )
        root.update_idletasks()
        item = next(
            iid for iid, link in gui.links.items()
            if link.get("view") == "match"
        )
        gui.table.selection_set(item)
        gui._open_selection()
        self.assertEqual("cross_era_match", gui.controller.page["screen"])
        rows = [
            gui.table.item(iid, "values")
            for iid in gui.table.get_children()
        ]
        text = " ".join(str(value) for row in rows for value in row)
        self.assertIn("1回表", text)
        self.assertIn("打撃", text)
        self.assertIn("投手", text)
        self.assertIn("saved_option_a_details",
                      gui.details.get("1.0", "end"))
        gui.year_var.set("10000")
        gui._change_year()
        self.assertEqual("cross_era_school", gui.controller.page["screen"])
        self.assertEqual(10000, gui.controller.page["selected_year"])


if __name__ == "__main__":
    unittest.main()
