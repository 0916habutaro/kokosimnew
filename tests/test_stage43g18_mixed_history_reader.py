"""Stage43G-18 mixed sealed cached+active raw A history read tests."""
from __future__ import annotations

import sqlite3
import unittest

from test_stage43g17_readonly_cache_browse import (
    Stage43G17ReadonlyCacheBrowseTests,
)
from phase2_engine.career_history_browse_model import HistoryRoute
from phase2_engine.career_player_stat_cache import CareerStatsCacheConflict
import test_stage43g14_player_records as fixture


class Stage43G18MixedReadTests(unittest.TestCase):
    def setUp(self):
        self.seed = Stage43G17ReadonlyCacheBrowseTests(
            "test_cache_absent_never_created_and_raw_is_fully_checked"
        )
        self.seed.setUp()
        self.model = self.seed.model
        self.a = self.seed.a
        self.hitter = self.seed.hitter
        self.cache_path = self.seed.cache_path
        self.seed.build(2026)

    def tearDown(self):
        self.seed.tearDown()

    def test_mixed_years_player_and_leaders_match_full_raw(self):
        raw_player = self.model.stats.player_seasons(
            self.hitter, start_year=2026, end_year=2027
        )
        raw_leaders = self.model.stats.school_leaders(
            self.a, start_year=2026, end_year=2027,
            category="batting_hits",
        )
        player = self.model.player_page(2027, self.hitter)
        leaders = self.model.leaders_page(2027, self.a)
        self.assertEqual("mixed_cache_ledger_and_raw_A_verified",
                         player["source_validation"])
        self.assertEqual("mixed_cache_ledger_and_raw_A_verified",
                         leaders["source_validation"])
        self.assertEqual((1, 1), (
            player["cached_year_count"], player["raw_year_count"]
        ))
        self.assertEqual((1, 1), (
            leaders["cached_year_count"], leaders["raw_year_count"]
        ))
        self.assertFalse(player["source_payloads_rechecked_on_read"])
        self.assertEqual(raw_player["seasons"], player["season_stats"])
        self.assertEqual(raw_player["totals"], player["career_stats"])
        self.assertEqual(raw_player["games_without_box_scores"],
                         player["missing_box_score_games"])
        self.assertEqual(raw_leaders["rows"], leaders["records"]["rows"])
        self.assertEqual(raw_leaders["candidate_count"],
                         leaders["records"]["candidate_count"])

    def test_mixed_gui_browse_does_not_modify_any_database(self):
        paths = (
            self.seed.seed.fixture.history.db_path,
            self.seed.seed.fixture.rosters.db_path,
            self.cache_path,
        )
        before = [path.read_bytes() for path in paths]
        self.model.player_page(2027, self.hitter)
        self.model.leaders_page(2027, self.a)
        self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_missing_score_only_game_in_raw_segment_not_fabricated(self):
        only_score = {
            "competition_id": "CMP000092",
            "match_id": "MIXED-SCORE-ONLY",
            "competition_name": "混合集計検証",
            "match_date": "2027-05-08",
            "completed_on": "2027-05-08",
            "date_source": "game_projection_v1",
            "status": "completed",
            "stage_code": "MAIN",
            "phase_code": "MAIN_BRACKET",
            "round_no": 1,
            "team1_id": self.a, "team2_id": self.seed.seed.fixture.b,
            "team1_score": 3, "team2_score": 1,
            "winner_id": self.a, "loser_id": self.seed.seed.fixture.b,
            "score_source": "generated_v1",
        }
        self.seed.seed.fixture.history.sync(
            year=2027, rng_seed=fixture.SEED,
            resolver_contract="synthetic_test_v1",
            plan_fingerprint="stage43g14-year-2027",
            completed=[only_score],
        )
        expected = self.model.stats.player_seasons(
            self.hitter, start_year=2026, end_year=2027
        )
        page = self.model.player_page(2027, self.hitter)
        self.assertEqual(1, page["missing_box_score_games"])
        self.assertEqual(expected["totals"], page["career_stats"])
        self.assertEqual(1, self.model.leaders_page(
            2027, self.a
        )["records"]["missing_box_score_games"])

    def test_mixed_cached_row_corruption_fails_without_changing_route(self):
        before = self.seed.seed.nav.current
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute(
                "UPDATE player_year_stat_cache SET payload_sha256='TAMPERED' "
                "WHERE year=2026 AND player_id=?",
                (self.hitter,),
            )
        with self.assertRaises(CareerStatsCacheConflict):
            self.seed.seed.nav.open(HistoryRoute(
                "player", 2027, player_id=self.hitter
            ))
        self.assertEqual(before, self.seed.seed.nav.current)
        with self.assertRaises(CareerStatsCacheConflict):
            self.model.leaders_page(2027, self.a)

    def test_mixed_ledger_mismatch_is_not_hidden_by_active_year(self):
        with sqlite3.connect(self.seed.seed.fixture.history.db_path) as conn:
            conn.execute(
                "UPDATE career_years SET ledger_sha256='ALTERED' "
                "WHERE year=2026"
            )
        with self.assertRaisesRegex(CareerStatsCacheConflict, "source changed"):
            self.model.player_page(2027, self.hitter)

    def test_all_sealed_and_cached_returns_fast_path(self):
        self.seed.seed.fixture.history.seal_year(
            2027, expected_match_count=1
        )
        self.seed.build(2027)
        row = self.model.player_page(2027, self.hitter)
        self.assertEqual("sealed_cache_ledger_checked",
                         row["source_validation"])
        self.assertEqual((2, 0), (
            row["cached_year_count"], row["raw_year_count"],
        ))

    def test_cache_row_for_active_year_is_an_error(self):
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute(
                "INSERT INTO school_year_stat_cache "
                "(school_id,year,source_ledger_sha256,source_match_count,"
                "school_missing_box_score_games,player_count,fact_sha256) "
                "VALUES(?,?,?,?,?,?,?)",
                (self.a, 2027, "invalid", 0, 0, 0, "invalid"),
            )
        with self.assertRaisesRegex(CareerStatsCacheConflict, "unsealed"):
            self.model.player_page(2027, self.hitter)


if __name__ == "__main__":
    unittest.main()
