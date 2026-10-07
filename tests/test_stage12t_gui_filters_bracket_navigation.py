from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phase2_engine.browse_gui_model import (
    ALL_COMPETITIONS_LABEL,
    ALL_PREFECTURES_LABEL,
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


class Stage12TGuiFiltersBracketNavigationTests(unittest.TestCase):
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
    def _views() -> SeasonBrowseViews:
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
                phase_code="SF",
                round_no=1,
                round_name="準決勝",
                group_id="",
                group_name="",
                team1_id="S1",
                team1_name="第一高校",
                team1_score=5,
                team2_id="S3",
                team2_name="第三高校",
                team2_score=2,
                winner_id="S1",
                winner_name="第一高校",
                loser_id="S3",
                loser_name="第三高校",
                is_bye=False,
                score_source="generated_v1",
                result_text="第一高校 5-2 第三高校",
            ),
            DatedMatchRow(
                match_date="2026-07-10",
                date_source="projected_v1",
                competition_id="CMP-A",
                competition_name="A大会",
                season_segment="summer",
                competition_type="summer_local",
                competition_level="prefectural",
                match_id="M2",
                stage_code="MAIN",
                phase_code="SF",
                round_no=1,
                round_name="準決勝",
                group_id="",
                group_name="",
                team1_id="S2",
                team1_name="第二高校",
                team1_score=4,
                team2_id="S4",
                team2_name="第四高校",
                team2_score=1,
                winner_id="S2",
                winner_name="第二高校",
                loser_id="S4",
                loser_name="第四高校",
                is_bye=False,
                score_source="generated_v1",
                result_text="第二高校 4-1 第四高校",
            ),
            DatedMatchRow(
                match_date="2026-07-12",
                date_source="projected_v1",
                competition_id="CMP-A",
                competition_name="A大会",
                season_segment="summer",
                competition_type="summer_local",
                competition_level="prefectural",
                match_id="M3",
                stage_code="MAIN",
                phase_code="F",
                round_no=2,
                round_name="決勝",
                group_id="",
                group_name="",
                team1_id="S1",
                team1_name="第一高校",
                team1_score=6,
                team2_id="S2",
                team2_name="第二高校",
                team2_score=3,
                winner_id="S1",
                winner_name="第一高校",
                loser_id="S2",
                loser_name="第二高校",
                is_bye=False,
                score_source="generated_v1",
                result_text="第一高校 6-3 第二高校",
            ),
            DatedMatchRow(
                match_date="",
                date_source="undated",
                competition_id="CMP-B",
                competition_name="B大会",
                season_segment="autumn",
                competition_type="national",
                competition_level="national",
                match_id="M4",
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
                end_date="2026-07-12",
                calendar_status="official_schedule",
                scheduled_date_count=2,
                first_match_date="2026-07-10",
                last_match_date="2026-07-12",
                date_sources="projected_v1",
                match_count=3,
                played_match_count=3,
                bye_count=0,
                participant_count=4,
                champion_id="S1",
                champion_name="第一高校",
                runner_up_id="S2",
                runner_up_name="第二高校",
                total_runs=21,
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
                school_id="S1", school_name="第一高校",
                prefecture_code="11", competition_count=1,
                competition_ids="CMP-A", games=2, wins=2, losses=0,
                win_pct=1.0, runs_for=11, runs_against=5,
                run_differential=6, titles=1, runner_up_finishes=0,
                last_game_date="2026-07-12",
            ),
            SchoolRecordRow(
                school_id="S2", school_name="第二高校",
                prefecture_code="11", competition_count=1,
                competition_ids="CMP-A", games=2, wins=1, losses=1,
                win_pct=0.5, runs_for=7, runs_against=7,
                run_differential=0, titles=0, runner_up_finishes=1,
                last_game_date="2026-07-12",
            ),
            SchoolRecordRow(
                school_id="S3", school_name="第三高校",
                prefecture_code="13", competition_count=2,
                competition_ids="CMP-A;CMP-B", games=2, wins=1, losses=1,
                win_pct=0.5, runs_for=3, runs_against=5,
                run_differential=-2, titles=1, runner_up_finishes=0,
                last_game_date="2026-07-10",
            ),
            SchoolRecordRow(
                school_id="S4", school_name="第四高校",
                prefecture_code="13", competition_count=2,
                competition_ids="CMP-A;CMP-B", games=2, wins=0, losses=2,
                win_pct=0.0, runs_for=1, runs_against=5,
                run_differential=-4, titles=0, runner_up_finishes=1,
                last_game_date="2026-07-10",
            ),
        ]
        return SeasonBrowseViews(
            matches_by_date=matches,
            competition_results=competitions,
            school_records=schools,
        )

    def test_prefecture_choices(self):
        self.assertEqual(
            ["11", "13"],
            self.model.prefecture_choices(2026),
        )

    def test_date_filter_by_prefecture(self):
        rows = self.model.matches_for_date_choice(
            2026,
            "2026-07-10",
            prefecture_code="13",
        )
        self.assertEqual({"M1", "M2"}, {row["match_id"] for row in rows})

    def test_date_filter_by_competition(self):
        rows = self.model.matches_for_date_choice(
            2026,
            "2026-07-10",
            competition_id="CMP-A",
        )
        self.assertEqual(["M1", "M2"], [row["match_id"] for row in rows])

    def test_undated_filter(self):
        rows = self.model.matches_for_date_choice(
            2026,
            UNDATED_LABEL,
        )
        self.assertEqual(["M4"], [row["match_id"] for row in rows])

    def test_bracket_rounds(self):
        _, matches = self.model.competition_detail(2026, "CMP-A")
        rounds = self.model.bracket_rounds(matches)
        self.assertEqual([1, 2], [round_.round_no for round_ in rounds])
        self.assertEqual([2, 1], [len(round_.matches) for round_ in rounds])
        self.assertEqual(["準決勝", "決勝"], [
            round_.round_name for round_ in rounds
        ])

    def test_filter_labels_are_explicit(self):
        self.assertEqual("すべての大会", ALL_COMPETITIONS_LABEL)
        self.assertEqual("すべての都道府県", ALL_PREFECTURES_LABEL)

    def test_enhanced_gui_source_has_navigation_and_bracket(self):
        source = (
            ROOT / "phase2_engine" / "browse_gui_enhanced.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_navigate_to_competition", source)
        self.assertIn("_navigate_to_school", source)
        self.assertIn('text="トーナメント表"', source)
        self.assertIn("date_pref_combo", source)
        self.assertIn("date_comp_combo", source)

    def test_base_gui_starts_current_readonly_app(self):
        source = (
            ROOT / "phase2_engine" / "browse_gui.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "from .browse_gui_stage12u import Stage12UBrowseApp",
            source,
        )
        self.assertIn("Stage12UBrowseApp(root, model)", source)

    def test_enhanced_gui_is_read_only(self):
        source = (
            ROOT / "phase2_engine" / "browse_gui_enhanced.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "INSERT INTO",
            "UPDATE ",
            "DELETE FROM",
            "replace_season_views(",
            "save_season_browse_repository(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
