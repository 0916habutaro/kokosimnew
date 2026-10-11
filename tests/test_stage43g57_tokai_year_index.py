"""Stage43G-57: verify index-driven year gates and single-pass summary.

Uses fictional Stage43G-54 fixtures, never official 2027 schedules or scores.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import sqlite3
import unittest

from phase2_engine.career_tokai_season_browse_model import (
    TokaiSeasonBrowseConflict, TOKAI_SEASON_IDS, GIFU, TOKAI,
)
from test_stage43g54_tokai_season_history_browse import (
    Stage43G54TokaiHistoryReadOnly,
)


class Stage43G57TokaiYearIndex(unittest.TestCase):
    def setUp(self):
        self.fixture = Stage43G54TokaiHistoryReadOnly(
            "test_season_index_shows_only_saved_tokai_games_and_source_warning",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.model = self.fixture.model

    def test_year_gate_avoids_all_years_materialization_and_uses_pk(self):
        before = self.fixture._sha()
        with patch.object(self.model.source, "years",
                          side_effect=AssertionError("all-year query is forbidden")):
            page = self.model.overview(2027)
            self.assertEqual(4, page["archived_match_count"])
            with self.assertRaises(TokaiSeasonBrowseConflict):
                self.model.overview(2028)
        path = Path(self.model.path)
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            plan = [
                row[3] for row in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT 1 FROM career_years "
                    "WHERE year=? LIMIT 1", (2027,),
                )
            ]
        self.assertTrue(any(
            "SEARCH career_years" in row and
            "INTEGER PRIMARY KEY" in row for row in plan
        ), plan)
        self.assertEqual(before, self.fixture._sha())

    def test_one_pass_summary_preserves_counts_unique_schools_and_dates(self):
        before = self.fixture._sha()
        overview = self.model.overview(2027)
        events = {row["competition_id"]: row for row in overview["events"]}
        self.assertEqual(set(TOKAI_SEASON_IDS), set(events))
        self.assertEqual(4, overview["archived_match_count"])
        self.assertEqual(1, events[TOKAI]["archived_match_count"])
        self.assertEqual(2, events[TOKAI]["schools_seen_in_saved_games"])
        self.assertEqual("2027-04-07", events[TOKAI]["latest_saved_game_date"])
        self.assertEqual("2027-04-05", events[GIFU]["latest_saved_game_date"])
        self.assertTrue(all(
            not x["bracket_completed_or_advancement_proven"]
            for x in overview["events"]
        ))
        self.assertFalse(overview["official_future_results"])
        self.assertEqual(before, self.fixture._sha())

    def test_missing_archive_is_error_not_new_sqlite(self):
        before = self.fixture._sha()
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.overview(2050)
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.overview(True)
        self.assertEqual(before, self.fixture._sha())


if __name__ == "__main__":
    unittest.main()
