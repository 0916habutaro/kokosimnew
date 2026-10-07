from __future__ import annotations

import unittest
from pathlib import Path

from phase2_engine.browse_gui_stage13d3 import (
    BATTING_METRICS,
    PITCHING_METRICS,
    Stage13D3BrowseApp,
)
from phase2_engine.browse_gui_stage12u import Stage12UBrowseApp


ROOT = Path(__file__).resolve().parents[1]
GUI_SOURCE = ROOT / "phase2_engine" / "browse_gui_stage13d3.py"
LAUNCHER_SOURCE = ROOT / "phase2_engine" / "browse_gui.py"


class Stage13D3ReadonlyGuiPlayerStatsTests(unittest.TestCase):
    def test_stage13d3_extends_existing_stage12u_gui(self):
        self.assertTrue(
            issubclass(Stage13D3BrowseApp, Stage12UBrowseApp)
        )

    def test_gui_adds_player_and_rankings_tabs(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn('text="選手・ロスター"', source)
        self.assertIn('text="個人成績ランキング"', source)
        self.assertIn('text="選手検索・詳細"', source)
        self.assertIn('text="学校ロスター"', source)

    def test_school_to_roster_to_player_navigation_exists(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("def _open_selected_school_roster(", source)
        self.assertIn("def _navigate_to_school_roster(", source)
        self.assertIn("def _on_roster_double_click(", source)
        self.assertIn("self._navigate_to_player(selection[0])", source)

    def test_competition_to_rankings_to_player_navigation_exists(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("def _open_current_competition_rankings(", source)
        self.assertIn("def _navigate_to_rankings(", source)
        self.assertIn(
            "def _on_batting_ranking_double_click(",
            source,
        )
        self.assertIn(
            "def _on_pitching_ranking_double_click(",
            source,
        )
        self.assertIn('text="この大会の個人成績ランキング"', source)

    def test_player_search_and_detail_use_read_model_contract(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("self.model.search_players(", source)
        self.assertIn("self.model.player_detail(", source)
        self.assertIn("self.model.school_roster_stats(", source)
        self.assertIn(
            "self.model.competition_leaderboards(",
            source,
        )

    def test_ranking_metric_choices_cover_stage13d1_metrics(self):
        self.assertEqual(
            {
                "ops",
                "batting_average",
                "on_base_percentage",
                "slugging_percentage",
                "hits",
                "home_runs",
                "rbi",
                "runs",
                "walks",
                "stolen_bases",
            },
            {metric for _, metric in BATTING_METRICS},
        )
        self.assertEqual(
            {
                "earned_run_average",
                "whip",
                "strikeouts",
                "strikeouts_per_9",
                "walks_per_9",
                "strikeout_walk_ratio",
                "k_minus_bb_pct",
            },
            {metric for _, metric in PITCHING_METRICS},
        )

    def test_display_formatters_are_stable(self):
        self.assertEqual("-", Stage13D3BrowseApp._format_rate(None))
        self.assertEqual("0.500", Stage13D3BrowseApp._format_rate(0.5))
        self.assertEqual(
            "1.931",
            Stage13D3BrowseApp._format_stat_value(1.931),
        )
        self.assertEqual(
            "12",
            Stage13D3BrowseApp._format_stat_value(12),
        )

    def test_stage13d3_gui_remains_read_only(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")
        for forbidden in (
            "INSERT INTO",
            "UPDATE ",
            "DELETE FROM",
            "replace_season_views(",
            "replace_season_player_master(",
            "replace_season_match_results(",
            "save_season_browse_repository(",
        ):
            self.assertNotIn(forbidden, source)

    def test_default_launcher_uses_stage13d3(self):
        source = LAUNCHER_SOURCE.read_text(encoding="utf-8")
        self.assertIn(
            "from .browse_gui_stage13d3 import Stage13D3BrowseApp",
            source,
        )
        self.assertIn("Stage13D3BrowseApp(root, model)", source)
        self.assertNotIn("Stage12UBrowseApp(root, model)", source)


if __name__ == "__main__":
    unittest.main()
