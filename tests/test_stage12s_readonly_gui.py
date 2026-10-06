from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phase2_engine.browse_gui_model import (
    BrowseGuiModel,
    UNDATED_LABEL,
)
from phase2_engine.browse_repository import BrowseRepository
from phase2_engine.browse_views import (
    CompetitionResultRow,
    DatedMatchRow,
    SchoolRecordRow,
    SeasonBrowseViews,
)

ROOT = Path(__file__).resolve().parents[1]


class Stage12SReadOnlyGuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "browse.sqlite3"
        self.repository = BrowseRepository(self.db)
        self.repository.replace_season_views(
            2026,
            2026100701,
            self._views(),
        )
        self.model = BrowseGuiModel(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _views():
        matches = [
            DatedMatchRow(
                match_date="2026-07-10",
                date_source="projected_v1",
                competition_id="CMP-A",
                competition_name="A大会",
                season_segment="summer",
                competition_type="summer_local",
                competition_level="prefectural",
                match_id="M1",
                stage_code="MAIN",
                phase_code="R1",
                round_no=1,
                round_name="1回戦",
                group_id="",
                group_name="",
                team1_id="S1",
                team1_name="第一高校",
                team1_score=5,
                team2_id="S2",
                team2_name="第二高校",
                team2_score=2,
                winner_id="S1",
                winner_name="第一高校",
                loser_id="S2",
                loser_name="第二高校",
                is_bye=False,
                score_source="generated_v1",
                result_text="第一高校 5-2 第二高校",
            ),
            DatedMatchRow(
                match_date="",
                date_source="undated",
                competition_id="CMP-B",
                competition_name="B大会",
                season_segment="autumn",
                competition_type="national",
                competition_level="national",
                match_id="M2",
                stage_code="MAIN",
                phase_code="F",
                round_no=1,
                round_name="決勝",
                group_id="",
                group_name="",
                team1_id="S3",
                team1_name="第三高校",
                team1_score=1,
                team2_id="S4",
                team2_name="第四高校",
                team2_score=0,
                winner_id="S3",
                winner_name="第三高校",
                loser_id="S4",
                loser_name="第四高校",
                is_bye=False,
                score_source="override",
                result_text="第三高校 1-0 第四高校",
            ),
        ]
        competitions = [
            CompetitionResultRow(
                competition_id="CMP-A",
                competition_name="A大会",
                season_segment="summer",
                competition_type="summer_local",
                competition_level="prefectural",
                start_date="2026-07-10",
                end_date="2026-07-11",
                calendar_status="official_schedule",
                scheduled_date_count=2,
                first_match_date="2026-07-10",
                last_match_date="2026-07-10",
                date_sources="projected_v1",
                match_count=1,
                played_match_count=1,
                bye_count=0,
                participant_count=2,
                champion_id="S1",
                champion_name="第一高校",
                runner_up_id="S2",
                runner_up_name="第二高校",
                total_runs=7,
                average_total_runs=7.0,
                score_sources="generated_v1",
            ),
            CompetitionResultRow(
                competition_id="CMP-B",
                competition_name="B大会",
                season_segment="autumn",
                competition_type="national",
                competition_level="national",
                start_date="2026-11-19",
                end_date="2026-11-24",
                calendar_status="official_schedule",
                scheduled_date_count=0,
                first_match_date="",
                last_match_date="",
                date_sources="undated",
                match_count=1,
                played_match_count=1,
                bye_count=0,
                participant_count=2,
                champion_id="S3",
                champion_name="第三高校",
                runner_up_id="S4",
                runner_up_name="第四高校",
                total_runs=1,
                average_total_runs=1.0,
                score_sources="override",
            ),
        ]
        schools = [
            SchoolRecordRow(
                school_id="S1", school_name="第一高校", prefecture_code="01",
                competition_count=1, competition_ids="CMP-A",
                games=1, wins=1, losses=0, win_pct=1.0,
                runs_for=5, runs_against=2, run_differential=3,
                titles=1, runner_up_finishes=0,
                last_game_date="2026-07-10",
            ),
            SchoolRecordRow(
                school_id="S2", school_name="第二高校", prefecture_code="01",
                competition_count=1, competition_ids="CMP-A",
                games=1, wins=0, losses=1, win_pct=0.0,
                runs_for=2, runs_against=5, run_differential=-3,
                titles=0, runner_up_finishes=1,
                last_game_date="2026-07-10",
            ),
            SchoolRecordRow(
                school_id="S3", school_name="第三高校", prefecture_code="13",
                competition_count=1, competition_ids="CMP-B",
                games=1, wins=1, losses=0, win_pct=1.0,
                runs_for=1, runs_against=0, run_differential=1,
                titles=1, runner_up_finishes=0,
                last_game_date="",
            ),
            SchoolRecordRow(
                school_id="S4", school_name="第四高校", prefecture_code="13",
                competition_count=1, competition_ids="CMP-B",
                games=1, wins=0, losses=1, win_pct=0.0,
                runs_for=0, runs_against=1, run_differential=-1,
                titles=0, runner_up_finishes=1,
                last_game_date="",
            ),
        ]
        return SeasonBrowseViews(
            matches_by_date=matches,
            competition_results=competitions,
            school_records=schools,
        )

    def test_available_years(self):
        self.assertEqual([2026], self.model.available_years())

    def test_date_choices_include_undated_label_last(self):
        self.assertEqual(
            ["2026-07-10", UNDATED_LABEL],
            self.model.date_choices(2026),
        )

    def test_date_choice_loads_dated_matches(self):
        rows = self.model.matches_for_date_choice(2026, "2026-07-10")
        self.assertEqual(["M1"], [row["match_id"] for row in rows])

    def test_undated_choice_loads_undated_matches(self):
        rows = self.model.matches_for_date_choice(2026, UNDATED_LABEL)
        self.assertEqual(["M2"], [row["match_id"] for row in rows])

    def test_competition_options_and_detail(self):
        options = self.model.competition_options(2026)
        self.assertEqual(
            ["CMP-A", "CMP-B"],
            [option.competition_id for option in options],
        )
        result, matches = self.model.competition_detail(2026, "CMP-A")
        self.assertEqual("第一高校", result["champion_name"])
        self.assertEqual(["M1"], [row["match_id"] for row in matches])

    def test_school_search_and_detail(self):
        rows = self.model.search_schools(
            2026,
            text="第一",
            prefecture_code="01",
        )
        self.assertEqual(["S1"], [row["school_id"] for row in rows])
        record, matches = self.model.school_detail(2026, "S1")
        self.assertEqual(1, record["wins"])
        self.assertEqual("W", matches[0]["school_result"])
        self.assertEqual("第二高校", matches[0]["opponent_name"])

    def test_score_text(self):
        dated = self.model.matches_for_date_choice(2026, "2026-07-10")[0]
        self.assertEqual("5-2", self.model.score_text(dated))

    def test_result_symbol(self):
        self.assertEqual("○", self.model.result_symbol("W"))
        self.assertEqual("●", self.model.result_symbol("L"))
        self.assertEqual("不戦勝", self.model.result_symbol("BYE"))

    def test_missing_database_is_reported_before_gui_start(self):
        model = BrowseGuiModel(Path(self.tmp.name) / "missing.sqlite3")
        with self.assertRaises(FileNotFoundError):
            model.ensure_database_exists()

    def test_repository_has_gui_discovery_queries(self):
        self.assertEqual([2026], self.repository.list_years())
        self.assertEqual(
            ["2026-07-10", ""],
            self.repository.list_match_dates(2026, include_undated=True),
        )

    def test_gui_source_has_three_tabs_and_global_year(self):
        source = (ROOT / "phase2_engine" / "browse_gui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('text="日付別試合"', source)
        self.assertIn('text="大会結果"', source)
        self.assertIn('text="学校戦績"', source)
        self.assertIn('text="年度"', source)
        self.assertIn("ttk.Notebook", source)

    def test_gui_is_read_only_by_contract(self):
        source = (ROOT / "phase2_engine" / "browse_gui.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("replace_season_views(", source)
        self.assertNotIn("save_season_browse_repository(", source)
        self.assertNotIn("INSERT INTO", source)
        self.assertNotIn("UPDATE ", source)
        self.assertNotIn("DELETE FROM", source)

    def test_gui_main_checks_database_before_tk_root(self):
        source = (ROOT / "phase2_engine" / "browse_gui.py").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            source.index("model.ensure_database_exists()"),
            source.index("root = tk.Tk()"),
        )

    def test_gui_uses_standard_library_only(self):
        source = (ROOT / "phase2_engine" / "browse_gui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("import tkinter as tk", source)
        self.assertIn("from tkinter import ttk", source)
        self.assertNotIn("streamlit", source.lower())
        self.assertNotIn("flask", source.lower())


if __name__ == "__main__":
    unittest.main()
