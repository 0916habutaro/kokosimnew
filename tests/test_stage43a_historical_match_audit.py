from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from phase2_engine.browse_repository import BrowseRepository
from phase2_engine.historical_match_audit import audit_historical_matches


class Stage43AHistoricalMatchAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "history.sqlite3"
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""
                CREATE TABLE browse_seasons (year INTEGER PRIMARY KEY);
                CREATE TABLE matches_by_date (
                    year INTEGER NOT NULL, competition_id TEXT NOT NULL,
                    match_id TEXT NOT NULL, is_bye INTEGER NOT NULL,
                    team1_score INTEGER, team2_score INTEGER,
                    PRIMARY KEY (year, competition_id, match_id)
                );
                CREATE TABLE ability_matches (
                    year INTEGER, competition_id TEXT, match_id TEXT,
                    team1_score INTEGER, team2_score INTEGER,
                    PRIMARY KEY (year, competition_id, match_id)
                );
                CREATE TABLE team_game_stats (
                    year INTEGER, competition_id TEXT, match_id TEXT,
                    school_id TEXT,
                    PRIMARY KEY (year, competition_id, match_id, school_id)
                );
                CREATE TABLE batter_game_stats (
                    year INTEGER, competition_id TEXT, match_id TEXT,
                    player_id TEXT,
                    PRIMARY KEY (year, competition_id, match_id, player_id)
                );
                CREATE TABLE pitcher_game_stats (
                    year INTEGER, competition_id TEXT, match_id TEXT,
                    player_id TEXT,
                    PRIMARY KEY (year, competition_id, match_id, player_id)
                );
                INSERT INTO browse_seasons VALUES (2026), (2027);
                INSERT INTO matches_by_date VALUES
                    (2026, 'A', 'M1', 0, 4, 3),
                    (2026, 'A', 'M2', 0, NULL, NULL),
                    (2026, 'A', 'BYE', 1, NULL, NULL),
                    (2027, 'A', 'M1', 0, 1, 0);
                INSERT INTO ability_matches VALUES
                    (2026, 'A', 'M1', 4, 3),
                    (2027, 'A', 'M1', 5, 0);
                INSERT INTO team_game_stats VALUES
                    (2026, 'A', 'M1', 'S1'),
                    (2026, 'A', 'M1', 'S2');
                INSERT INTO batter_game_stats VALUES
                    (2026, 'A', 'M1', 'B1');
                INSERT INTO pitcher_game_stats VALUES
                    (2026, 'A', 'M1', 'P1');
            """)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_db_does_not_create_database(self):
        missing = Path(self.temp.name) / "nonexistent.sqlite3"
        with self.assertRaises(FileNotFoundError):
            audit_historical_matches(missing)
        self.assertFalse(missing.exists())

    def test_score_bye_and_optional_stats_coverage_without_innings(self):
        before = self.db.read_bytes()
        report = audit_historical_matches(self.db)
        self.assertTrue(report["readonly"])
        self.assertEqual("absent", report["inning_score_schema"])
        self.assertTrue(report["stats_tables_present"])
        self.assertEqual([2026, 2027], [r["year"] for r in report["years"]])
        first, second = report["years"]
        self.assertEqual(3, first["total_match_rows"])
        self.assertEqual(1, first["bye_rows"])
        self.assertEqual(2, first["non_bye_rows"])
        self.assertEqual(1, first["scored_match_rows"])
        self.assertEqual(1, first["unscored_non_bye_rows"])
        self.assertEqual(1, first["match_rows_with_game_stats"])
        self.assertEqual(0, first["match_rows_with_reconciled_inning_totals"])
        self.assertFalse(first["full_a_claimed"])
        self.assertEqual(1, second["score_conflicts_between_sources"])
        self.assertEqual(0, second["match_rows_with_game_stats"])
        self.assertEqual(before, self.db.read_bytes())

    def test_year_filter_and_missing_year(self):
        report = audit_historical_matches(self.db, year=2027)
        self.assertEqual([2027], [row["year"] for row in report["years"]])
        with self.assertRaisesRegex(ValueError, "year not found"):
            audit_historical_matches(self.db, year=2028)
        with self.assertRaisesRegex(ValueError, "positive"):
            audit_historical_matches(self.db, year=-3)

    def test_inning_score_totals_do_not_imply_full_a(self):
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""
                CREATE TABLE match_inning_scores (
                    year INTEGER, competition_id TEXT, match_id TEXT,
                    inning INTEGER, half TEXT, runs INTEGER,
                    was_played INTEGER
                );
                INSERT INTO match_inning_scores VALUES
                    (2026, 'A', 'M1', 1, 'top', 4, 1),
                    (2026, 'A', 'M1', 1, 'bottom', 3, 1),
                    (2027, 'A', 'M1', 1, 'top', 1, 1),
                    (2027, 'A', 'M1', 1, 'bottom', 2, 1);
            """)
        report = audit_historical_matches(self.db)
        self.assertEqual("recognized", report["inning_score_schema"])
        self.assertEqual(1, report["years"][0]["match_rows_with_reconciled_inning_totals"])
        self.assertEqual(0, report["years"][1]["match_rows_with_reconciled_inning_totals"])
        self.assertFalse(report["years"][0]["full_a_claimed"])

    def test_missing_optional_tables_are_not_reported_as_zero_stats(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TABLE pitcher_game_stats")
        report = audit_historical_matches(self.db, year=2026)
        self.assertFalse(report["stats_tables_present"])
        self.assertEqual(0, report["years"][0]["match_rows_with_game_stats"])

    def test_actual_schema_is_supported_without_side_effects(self):
        other = Path(self.temp.name) / "real.sqlite3"
        BrowseRepository(other).initialize_schema()
        before = other.read_bytes()
        payload = audit_historical_matches(other)
        self.assertEqual([], payload["years"])
        self.assertEqual("absent", payload["inning_score_schema"])
        self.assertTrue(payload["stats_tables_present"])
        self.assertEqual(before, other.read_bytes())


if __name__ == "__main__":
    unittest.main()
