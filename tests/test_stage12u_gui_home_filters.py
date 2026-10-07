from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phase2_engine.browse_gui_model import (
    ALL_SEASONS_LABEL,
    ALL_TYPES_LABEL,
    BrowseGuiModel,
    COMPETITION_TYPE_LABELS,
    SEASON_SEGMENT_LABELS,
)
from phase2_engine.browse_repository import BrowseRepository
from phase2_engine.browse_views import (
    CompetitionResultRow,
    DatedMatchRow,
    SchoolRecordRow,
    SeasonBrowseViews,
)

ROOT = Path(__file__).resolve().parents[1]


class Stage12UGuiHomeFiltersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "browse.sqlite3"
        self.repository = BrowseRepository(self.db)
        self.repository.replace_season_views(
            2026,
            2026100701,
            self._views(),
        )
        self.model = BrowseGuiModel(self.db, ROOT / "data")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _views() -> SeasonBrowseViews:
        matches = [
            DatedMatchRow(
                match_date="2026-07-10",
                date_source="projected_v1",
                competition_id="CMP-SUMMER",
                competition_name="夏地方大会",
                season_segment="summer",
                competition_type="summer_local_qualifier",
                competition_level="prefectural",
                match_id="SUM-M1",
                stage_code="MAIN",
                phase_code="SF",
                round_no=1,
                round_name="準決勝",
                group_id="",
                group_name="",
                team1_id="S11A",
                team1_name="埼玉第一",
                team1_score=5,
                team2_id="S13A",
                team2_name="東京第一",
                team2_score=2,
                winner_id="S11A",
                winner_name="埼玉第一",
                loser_id="S13A",
                loser_name="東京第一",
                is_bye=False,
                score_source="generated_v1",
                result_text="埼玉第一 5-2 東京第一",
            ),
            DatedMatchRow(
                match_date="2026-07-10",
                date_source="projected_v1",
                competition_id="CMP-SUMMER",
                competition_name="夏地方大会",
                season_segment="summer",
                competition_type="summer_local_qualifier",
                competition_level="prefectural",
                match_id="SUM-M2",
                stage_code="MAIN",
                phase_code="SF",
                round_no=1,
                round_name="準決勝",
                group_id="",
                group_name="",
                team1_id="S11B",
                team1_name="埼玉第二",
                team1_score=4,
                team2_id="S13B",
                team2_name="東京第二",
                team2_score=1,
                winner_id="S11B",
                winner_name="埼玉第二",
                loser_id="S13B",
                loser_name="東京第二",
                is_bye=False,
                score_source="generated_v1",
                result_text="埼玉第二 4-1 東京第二",
            ),
            DatedMatchRow(
                match_date="2026-07-12",
                date_source="projected_v1",
                competition_id="CMP-SUMMER",
                competition_name="夏地方大会",
                season_segment="summer",
                competition_type="summer_local_qualifier",
                competition_level="prefectural",
                match_id="SUM-F",
                stage_code="MAIN",
                phase_code="F",
                round_no=2,
                round_name="決勝",
                group_id="",
                group_name="",
                team1_id="S11A",
                team1_name="埼玉第一",
                team1_score=6,
                team2_id="S11B",
                team2_name="埼玉第二",
                team2_score=3,
                winner_id="S11A",
                winner_name="埼玉第一",
                loser_id="S11B",
                loser_name="埼玉第二",
                is_bye=False,
                score_source="generated_v1",
                result_text="埼玉第一 6-3 埼玉第二",
            ),
            DatedMatchRow(
                match_date="2026-10-20",
                date_source="projected_v1",
                competition_id="CMP-AUTUMN",
                competition_name="秋季地区大会",
                season_segment="autumn",
                competition_type="autumn_regional",
                competition_level="regional",
                match_id="AUT-M1",
                stage_code="MAIN",
                phase_code="F",
                round_no=1,
                round_name="決勝",
                group_id="",
                group_name="",
                team1_id="S13A",
                team1_name="東京第一",
                team1_score=3,
                team2_id="S13B",
                team2_name="東京第二",
                team2_score=2,
                winner_id="S13A",
                winner_name="東京第一",
                loser_id="S13B",
                loser_name="東京第二",
                is_bye=False,
                score_source="generated_v1",
                result_text="東京第一 3-2 東京第二",
            ),
        ]
        competitions = [
            CompetitionResultRow(
                competition_id="CMP-SUMMER",
                competition_name="夏地方大会",
                season_segment="summer",
                competition_type="summer_local_qualifier",
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
                champion_id="S11A",
                champion_name="埼玉第一",
                runner_up_id="S11B",
                runner_up_name="埼玉第二",
                total_runs=21,
                average_total_runs=7.0,
                score_sources="generated_v1",
            ),
            CompetitionResultRow(
                competition_id="CMP-AUTUMN",
                competition_name="秋季地区大会",
                season_segment="autumn",
                competition_type="autumn_regional",
                competition_level="regional",
                start_date="2026-10-20",
                end_date="2026-10-20",
                calendar_status="official_schedule",
                scheduled_date_count=1,
                first_match_date="2026-10-20",
                last_match_date="2026-10-20",
                date_sources="projected_v1",
                match_count=1,
                played_match_count=1,
                bye_count=0,
                participant_count=2,
                champion_id="S13A",
                champion_name="東京第一",
                runner_up_id="S13B",
                runner_up_name="東京第二",
                total_runs=5,
                average_total_runs=5.0,
                score_sources="generated_v1",
            ),
        ]
        schools = [
            SchoolRecordRow(
                school_id="S11A", school_name="埼玉第一",
                prefecture_code="11", competition_count=1,
                competition_ids="CMP-SUMMER", games=2, wins=2, losses=0,
                win_pct=1.0, runs_for=11, runs_against=5,
                run_differential=6, titles=1, runner_up_finishes=0,
                last_game_date="2026-07-12",
            ),
            SchoolRecordRow(
                school_id="S11B", school_name="埼玉第二",
                prefecture_code="11", competition_count=1,
                competition_ids="CMP-SUMMER", games=2, wins=1, losses=1,
                win_pct=0.5, runs_for=7, runs_against=7,
                run_differential=0, titles=0, runner_up_finishes=1,
                last_game_date="2026-07-12",
            ),
            SchoolRecordRow(
                school_id="S13A", school_name="東京第一",
                prefecture_code="13", competition_count=2,
                competition_ids="CMP-AUTUMN;CMP-SUMMER",
                games=2, wins=1, losses=1, win_pct=0.5,
                runs_for=5, runs_against=7, run_differential=-2,
                titles=1, runner_up_finishes=0,
                last_game_date="2026-10-20",
            ),
            SchoolRecordRow(
                school_id="S13B", school_name="東京第二",
                prefecture_code="13", competition_count=2,
                competition_ids="CMP-AUTUMN;CMP-SUMMER",
                games=2, wins=0, losses=2, win_pct=0.0,
                runs_for=3, runs_against=7, run_differential=-4,
                titles=0, runner_up_finishes=1,
                last_game_date="2026-10-20",
            ),
        ]
        return SeasonBrowseViews(
            matches_by_date=matches,
            competition_results=competitions,
            school_records=schools,
        )

    def test_prefecture_names_are_loaded_from_master(self):
        self.assertEqual("埼玉県", self.model.prefecture_label("11"))
        self.assertEqual("東京都", self.model.prefecture_label("13"))
        labels = [x.label for x in self.model.prefecture_options(2026)]
        self.assertEqual(["埼玉県", "東京都"], labels)

    def test_season_segment_labels(self):
        options = self.model.season_segment_options(2026)
        values = {item.value: item.label for item in options}
        self.assertEqual("夏", values["summer"])
        self.assertEqual("秋", values["autumn"])
        self.assertEqual("春", SEASON_SEGMENT_LABELS["spring"])

    def test_competition_type_labels(self):
        options = self.model.competition_type_options(
            2026,
            season_segment="summer",
        )
        self.assertEqual(1, len(options))
        self.assertEqual("summer_local_qualifier", options[0].value)
        self.assertEqual("夏地方大会", options[0].label)
        self.assertEqual(
            "秋季地区大会",
            COMPETITION_TYPE_LABELS["autumn_regional"],
        )

    def test_date_filter_by_season(self):
        summer = self.model.matches_for_date_choice(
            2026,
            "2026-07-10",
            season_segment="summer",
        )
        autumn = self.model.matches_for_date_choice(
            2026,
            "2026-07-10",
            season_segment="autumn",
        )
        self.assertEqual(2, len(summer))
        self.assertEqual([], autumn)

    def test_date_filter_by_competition_type(self):
        rows = self.model.matches_for_date_choice(
            2026,
            "2026-10-20",
            competition_type="autumn_regional",
        )
        self.assertEqual(["AUT-M1"], [row["match_id"] for row in rows])

    def test_competition_options_can_be_filtered(self):
        summer = self.model.competition_options(
            2026,
            season_segment="summer",
        )
        autumn = self.model.competition_options(
            2026,
            competition_type="autumn_regional",
        )
        self.assertEqual(["CMP-SUMMER"], [x.competition_id for x in summer])
        self.assertEqual(["CMP-AUTUMN"], [x.competition_id for x in autumn])

    def test_home_summary_for_today(self):
        summary = self.model.home_summary(
            2026,
            today="2026-07-10",
        )
        self.assertEqual(4, summary["match_count"])
        self.assertEqual(2, summary["competition_count"])
        self.assertEqual(4, summary["school_count"])
        self.assertEqual(2, summary["today_match_count"])
        self.assertEqual("2026-07-10", summary["previous_match_date"])
        self.assertEqual("2026-07-10", summary["next_match_date"])
        self.assertEqual(1, summary["segment_counts"]["summer"])
        self.assertEqual(1, summary["segment_counts"]["autumn"])

    def test_home_summary_next_date(self):
        summary = self.model.home_summary(
            2026,
            today="2026-07-11",
        )
        self.assertEqual(0, summary["today_match_count"])
        self.assertEqual("2026-07-10", summary["previous_match_date"])
        self.assertEqual("2026-07-12", summary["next_match_date"])

    def test_filter_constants(self):
        self.assertEqual("すべての季節", ALL_SEASONS_LABEL)
        self.assertEqual("すべての大会種別", ALL_TYPES_LABEL)

    def test_repository_exposes_filter_discovery(self):
        self.assertEqual(
            ["autumn", "summer"],
            self.repository.list_season_segments(2026),
        )
        self.assertEqual(
            ["summer_local_qualifier"],
            self.repository.list_competition_types(
                2026,
                season_segment="summer",
            ),
        )

    def test_stage12u_gui_has_home_and_named_filters(self):
        source = (
            ROOT / "phase2_engine" / "browse_gui_stage12u.py"
        ).read_text(encoding="utf-8")
        self.assertIn('text="ホーム"', source)
        self.assertIn('text="季節"', source)
        self.assertIn('text="大会種別"', source)
        self.assertIn('text="都道府県"', source)
        self.assertIn("self.model.prefecture_label", source)

    def test_bracket_school_names_are_clickable(self):
        source = (
            ROOT / "phase2_engine" / "browse_gui_stage12u.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _bind_bracket_school(", source)
        self.assertIn('"<Button-1>"', source)
        self.assertIn("_navigate_to_school(sid)", source)

    def test_browse_gui_launches_stage12u(self):
        source = (
            ROOT / "phase2_engine" / "browse_gui.py"
        ).read_text(encoding="utf-8")
        self.assertIn("--data-dir", source)
        self.assertIn("Stage12UBrowseApp(root, model)", source)

    def test_stage12u_remains_read_only(self):
        source = (
            ROOT / "phase2_engine" / "browse_gui_stage12u.py"
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
