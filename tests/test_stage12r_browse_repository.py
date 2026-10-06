from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from phase2_engine.browse_repository import (
    BrowseRepository,
    SCHEMA_VERSION,
)
from phase2_engine.browse_views import (
    CompetitionResultRow,
    DatedMatchRow,
    SchoolRecordRow,
    SeasonBrowseViews,
)

ROOT = Path(__file__).resolve().parents[1]


class Stage12RBrowseRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "browse.sqlite3"
        self.repo = BrowseRepository(self.db)
        self.views = self._views()

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
                team1_name="第一",
                team1_score=5,
                team2_id="S2",
                team2_name="第二",
                team2_score=2,
                winner_id="S1",
                winner_name="第一",
                loser_id="S2",
                loser_name="第二",
                is_bye=False,
                score_source="generated_v1",
                result_text="第一 5-2 第二",
            ),
            DatedMatchRow(
                match_date="2026-07-11",
                date_source="projected_v1",
                competition_id="CMP-A",
                competition_name="A大会",
                season_segment="summer",
                competition_type="summer_local",
                competition_level="prefectural",
                match_id="M2",
                stage_code="MAIN",
                phase_code="F",
                round_no=2,
                round_name="決勝",
                group_id="",
                group_name="",
                team1_id="S1",
                team1_name="第一",
                team1_score=3,
                team2_id="S3",
                team2_name="第三",
                team2_score=4,
                winner_id="S3",
                winner_name="第三",
                loser_id="S1",
                loser_name="第一",
                is_bye=False,
                score_source="generated_v1",
                result_text="第一 3-4 第三",
            ),
            DatedMatchRow(
                match_date="",
                date_source="undated",
                competition_id="CMP-B",
                competition_name="B大会",
                season_segment="autumn",
                competition_type="national",
                competition_level="national",
                match_id="M3",
                stage_code="MAIN",
                phase_code="F",
                round_no=1,
                round_name="決勝",
                group_id="",
                group_name="",
                team1_id="S4",
                team1_name="第四",
                team1_score=1,
                team2_id="S5",
                team2_name="第五",
                team2_score=0,
                winner_id="S4",
                winner_name="第四",
                loser_id="S5",
                loser_name="第五",
                is_bye=False,
                score_source="override",
                result_text="第四 1-0 第五",
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
                last_match_date="2026-07-11",
                date_sources="projected_v1",
                match_count=2,
                played_match_count=2,
                bye_count=0,
                participant_count=3,
                champion_id="S3",
                champion_name="第三",
                runner_up_id="S1",
                runner_up_name="第一",
                total_runs=14,
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
                champion_id="S4",
                champion_name="第四",
                runner_up_id="S5",
                runner_up_name="第五",
                total_runs=1,
                average_total_runs=1.0,
                score_sources="override",
            ),
        ]
        schools = [
            SchoolRecordRow(
                school_id="S1", school_name="第一", prefecture_code="01",
                competition_count=1, competition_ids="CMP-A",
                games=2, wins=1, losses=1, win_pct=0.5,
                runs_for=8, runs_against=6, run_differential=2,
                titles=0, runner_up_finishes=1, last_game_date="2026-07-11",
            ),
            SchoolRecordRow(
                school_id="S2", school_name="第二", prefecture_code="01",
                competition_count=1, competition_ids="CMP-A",
                games=1, wins=0, losses=1, win_pct=0.0,
                runs_for=2, runs_against=5, run_differential=-3,
                titles=0, runner_up_finishes=0, last_game_date="2026-07-10",
            ),
            SchoolRecordRow(
                school_id="S3", school_name="第三", prefecture_code="02",
                competition_count=1, competition_ids="CMP-A",
                games=1, wins=1, losses=0, win_pct=1.0,
                runs_for=4, runs_against=3, run_differential=1,
                titles=1, runner_up_finishes=0, last_game_date="2026-07-11",
            ),
            SchoolRecordRow(
                school_id="S4", school_name="第四", prefecture_code="03",
                competition_count=1, competition_ids="CMP-B",
                games=1, wins=1, losses=0, win_pct=1.0,
                runs_for=1, runs_against=0, run_differential=1,
                titles=1, runner_up_finishes=0, last_game_date="",
            ),
            SchoolRecordRow(
                school_id="S5", school_name="第五", prefecture_code="04",
                competition_count=1, competition_ids="CMP-B",
                games=1, wins=0, losses=1, win_pct=0.0,
                runs_for=0, runs_against=1, run_differential=-1,
                titles=0, runner_up_finishes=1, last_game_date="",
            ),
        ]
        return SeasonBrowseViews(
            matches_by_date=matches,
            competition_results=competitions,
            school_records=schools,
        )

    def test_schema_and_indexes_are_created(self):
        self.repo.initialize_schema()
        with sqlite3.connect(self.db) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            indexes = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
        self.assertEqual(SCHEMA_VERSION, version)
        self.assertTrue({
            "browse_seasons",
            "matches_by_date",
            "competition_results",
            "school_records",
        }.issubset(tables))
        self.assertIn("idx_matches_year_date", indexes)
        self.assertIn("idx_matches_year_competition", indexes)
        self.assertIn("idx_schools_year_prefecture", indexes)

    def test_replace_and_season_meta(self):
        summary = self.repo.replace_season_views(
            2026, 2026100701, self.views
        )
        meta = self.repo.season_meta(2026)
        self.assertEqual(3, summary["match_count"])
        self.assertEqual(2, summary["competition_count"])
        self.assertEqual(5, summary["school_count"])
        self.assertEqual(2026100701, meta["rng_seed"])
        self.assertEqual(3, meta["match_count"])

    def test_matches_by_date_and_undated(self):
        self.repo.replace_season_views(2026, 1, self.views)
        dated = self.repo.matches_on_date(2026, "2026-07-10")
        undated = self.repo.undated_matches(2026)
        self.assertEqual(["M1"], [row["match_id"] for row in dated])
        self.assertEqual(["M3"], [row["match_id"] for row in undated])

    def test_competition_queries(self):
        self.repo.replace_season_views(2026, 1, self.views)
        result = self.repo.competition_result(2026, "CMP-A")
        matches = self.repo.competition_matches(2026, "CMP-A")
        listing = self.repo.list_competitions(2026)
        self.assertEqual("第三", result["champion_name"])
        self.assertEqual(["M1", "M2"], [row["match_id"] for row in matches])
        self.assertEqual(["CMP-A", "CMP-B"], [
            row["competition_id"] for row in listing
        ])

    def test_school_record_and_match_history(self):
        self.repo.replace_season_views(2026, 1, self.views)
        record = self.repo.school_record(2026, "S1")
        history = self.repo.school_matches(2026, "S1")
        self.assertEqual(1, record["wins"])
        self.assertEqual(1, record["losses"])
        self.assertEqual(["W", "L"], [
            row["school_result"] for row in history
        ])
        self.assertEqual(["第二", "第三"], [
            row["opponent_name"] for row in history
        ])

    def test_school_search_filters(self):
        self.repo.replace_season_views(2026, 1, self.views)
        by_text = self.repo.search_school_records(
            2026, text="第三"
        )
        by_pref = self.repo.search_school_records(
            2026, prefecture_code="01"
        )
        self.assertEqual(["S3"], [row["school_id"] for row in by_text])
        self.assertEqual({"S1", "S2"}, {
            row["school_id"] for row in by_pref
        })

    def test_replace_same_year_is_idempotent(self):
        self.repo.replace_season_views(2026, 1, self.views)
        self.repo.replace_season_views(2026, 2, self.views)
        with sqlite3.connect(self.db) as conn:
            matches = conn.execute(
                "SELECT COUNT(*) FROM matches_by_date WHERE year=2026"
            ).fetchone()[0]
            competitions = conn.execute(
                "SELECT COUNT(*) FROM competition_results WHERE year=2026"
            ).fetchone()[0]
        self.assertEqual(3, matches)
        self.assertEqual(2, competitions)
        self.assertEqual(2, self.repo.season_meta(2026)["rng_seed"])

    def test_multiple_years_are_isolated(self):
        self.repo.replace_season_views(2026, 1, self.views)
        self.repo.replace_season_views(2027, 2, self.views)
        self.assertEqual(3, self.repo.season_meta(2026)["match_count"])
        self.assertEqual(3, self.repo.season_meta(2027)["match_count"])
        self.assertEqual(1, len(self.repo.matches_on_date(
            2027, "2026-07-10"
        )))

    def test_invalid_duplicate_match_key_does_not_replace_existing(self):
        self.repo.replace_season_views(2026, 7, self.views)
        broken = SeasonBrowseViews(
            matches_by_date=[
                self.views.matches_by_date[0],
                self.views.matches_by_date[0],
            ],
            competition_results=self.views.competition_results,
            school_records=self.views.school_records,
        )
        with self.assertRaises(ValueError):
            self.repo.replace_season_views(2026, 9, broken)
        self.assertEqual(7, self.repo.season_meta(2026)["rng_seed"])
        self.assertEqual(3, self.repo.season_meta(2026)["match_count"])

    def test_missing_school_reference_is_rejected(self):
        broken = SeasonBrowseViews(
            matches_by_date=self.views.matches_by_date,
            competition_results=self.views.competition_results,
            school_records=self.views.school_records[:-1],
        )
        with self.assertRaises(ValueError):
            self.repo.replace_season_views(2026, 1, broken)

    def test_search_limit_is_guarded(self):
        self.repo.replace_season_views(2026, 1, self.views)
        with self.assertRaises(ValueError):
            self.repo.search_school_records(2026, limit=0)
        with self.assertRaises(ValueError):
            self.repo.search_school_records(2026, limit=1001)

    def test_season_cli_exposes_sqlite_db_option(self):
        source = (ROOT / "phase2_engine" / "season_cli.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("--sqlite-db", source)
        self.assertIn("save_season_browse_repository(", source)


if __name__ == "__main__":
    unittest.main()
