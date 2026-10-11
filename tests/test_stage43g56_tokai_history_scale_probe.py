"""Stage43G-56: bounded source-only performance measurement of the Tk paths."""
from __future__ import annotations

import unittest

from phase2_engine.career_tokai_history_scale_probe import (
    run_tokai_history_scale_probe,
)
from phase2_engine.career_tokai_season_browse_model import (
    TOKAI, TokaiSeasonBrowseConflict,
)
from test_stage43g54_tokai_season_history_browse import (
    Stage43G54TokaiHistoryReadOnly,
)


class Stage43G56TokaiScaleProbe(unittest.TestCase):
    def setUp(self):
        self.source = Stage43G54TokaiHistoryReadOnly(
            "test_season_index_shows_only_saved_tokai_games_and_source_warning",
        )
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.model = self.source.model

    def test_first_and_next_pages_are_bounded_and_proven_read_only(self):
        previous_sha = self.source._sha()
        result = run_tokai_history_scale_probe(
            self.model, years=[2027], school_id=self.source.a,
            competition_id=TOKAI, limit=1, repeats=2,
        )
        self.assertEqual([2027], result["sampled_years"])
        self.assertEqual(4, result["coverage"][0]["archived_match_count"])
        self.assertEqual(1, result["coverage"][0]["competition_first_total"])
        self.assertEqual(0, result["measurements"]["competition_next"]["max_returned_rows"])
        self.assertEqual(1, result["measurements"]["competition_first"]["max_returned_rows"])
        self.assertTrue(result["source_sqlite_and_sidecars_unchanged"])
        self.assertFalse(result["nationwide_3000_schools_tested"])
        self.assertFalse(result["unlimited_year_progression_proven"])
        for item in result["measurements"].values():
            self.assertEqual(2, item["sample_count"])
            self.assertGreaterEqual(item["median_ms"], 0)
        self.assertEqual(previous_sha, self.source._sha())
        self.assertFalse((self.source.slot / "derived_player_stats.sqlite3").exists())

    def test_bad_year_identity_and_bounds_are_rejected(self):
        for years, limit, repeats in (
            ([2027, 2027], 30, 1), ([True], 30, 1),
            ([2028], 30, 1), ([2027], 0, 1),
            ([2027], 101, 1), ([2027], 30, 6),
        ):
            with self.subTest(years=years, limit=limit, repeats=repeats):
                with self.assertRaises((ValueError, TokaiSeasonBrowseConflict)):
                    run_tokai_history_scale_probe(
                        self.model, years=years, school_id=self.source.a,
                        limit=limit, repeats=repeats,
                    )
        with self.assertRaises(TokaiSeasonBrowseConflict):
            run_tokai_history_scale_probe(
                self.model, years=[2027], school_id="FAKE-SCHOOL",
            )
        with self.assertRaises(ValueError):
            run_tokai_history_scale_probe(
                self.model, years=[2027], school_id=self.source.a,
                competition_id="NOT-A-TOKAI-COMPETITION",
            )


if __name__ == "__main__":
    unittest.main()
