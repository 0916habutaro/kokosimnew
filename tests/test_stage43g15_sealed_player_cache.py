"""Stage43G-15: materialized school-year player stats cache on real A-fixture."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

import test_stage43g14_player_records as fixture
from phase2_engine.career_player_stat_cache import (
    CareerPlayerStatCache, CareerStatsCacheConflict,
)


class Stage43G15SealedPlayerCacheTests(unittest.TestCase):
    def setUp(self):
        self.seed = fixture.Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios"
        )
        self.seed.setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.cache = CareerPlayerStatCache(
            self.seed.view, Path(self.temp.name) / "derived_player_stats.sqlite3",
        )

    def tearDown(self):
        self.temp.cleanup()
        self.seed.tearDown()

    def seal_all(self):
        self.seed.history.seal_year(2027, expected_match_count=1)

    def test_only_sealed_years_may_be_materialized(self):
        with self.assertRaisesRegex(CareerStatsCacheConflict, "sealed"):
            self.cache.materialize(self.seed.a, year=2027)
        a = self.cache.materialize(self.seed.a, year=2026)
        self.assertTrue(a["source_year_sealed"])
        self.assertTrue(a["inserted"])
        self.assertGreater(a["player_count"], 0)
        again = self.cache.materialize(self.seed.a, year=2026)
        self.assertFalse(again["inserted"])
        self.assertEqual(a["fact_sha256"], again["fact_sha256"])

    def test_immutable_two_year_cache_matches_original_A_seasons_and_leaders(self):
        self.seal_all()
        for y in (2026, 2027):
            self.cache.materialize(self.seed.a, year=y)
        for pid in (self.seed.hitter, self.seed.pitcher):
            read = self.cache.player_seasons(
                pid, start_year=2026, end_year=2027,
            )
            original = self.seed.view.player_seasons(
                pid, start_year=2026, end_year=2027,
            )
            self.assertEqual(original["seasons"], read["seasons"])
            self.assertEqual(original["totals"], read["totals"])
            self.assertFalse(read["source_payloads_rechecked_on_read"])
            strict = self.cache.player_seasons(
                pid, start_year=2026, end_year=2027,
                verify_source=True,
            )
            self.assertEqual(read["totals"], strict["totals"])
            self.assertTrue(strict["source_payloads_rechecked_on_read"])
        for category in ("batting_hits", "pitching_strikeouts"):
            source = self.seed.view.school_leaders(
                self.seed.a, start_year=2026, end_year=2027,
                category=category,
            )
            cached = self.cache.school_leaders(
                self.seed.a, start_year=2026, end_year=2027,
                category=category, verify_source=True,
            )
            self.assertEqual(source["rows"], cached["rows"])
            self.assertEqual(source["candidate_count"], cached["candidate_count"])

    def test_cache_refuses_unmaterialized_year_and_unknown_period(self):
        self.cache.materialize(self.seed.a, year=2026)
        with self.assertRaisesRegex(CareerStatsCacheConflict, "unavailable"):
            self.cache.player_seasons(
                self.seed.hitter, start_year=2026, end_year=2027,
            )
        with self.assertRaises(CareerStatsCacheConflict):
            self.cache.school_leaders(
                self.seed.a, start_year=2026, end_year=2027,
                category="batting_hits",
            )

    def test_score_only_games_are_missing_evidence_not_zero(self):
        missing = {
            "competition_id": "CMP000092", "match_id": "SCORE-ONLY-CACHE",
            "competition_name": "合成スコアのみ", "match_date": "2027-05-08",
            "completed_on": "2027-05-08", "date_source": "game_projection_v1",
            "status": "completed", "stage_code": "MAIN",
            "phase_code": "MAIN_BRACKET", "round_no": 1,
            "team1_id": self.seed.a, "team2_id": self.seed.b,
            "team1_score": 2, "team2_score": 1,
            "winner_id": self.seed.a, "loser_id": self.seed.b,
            "score_source": "generated_v1",
        }
        self.seed.history.sync(
            year=2027, rng_seed=fixture.SEED,
            resolver_contract="synthetic_test_v1",
            plan_fingerprint="stage43g14-year-2027",
            completed=[missing],
        )
        self.seed.history.seal_year(2027, expected_match_count=2)
        for year in (2026, 2027):
            self.cache.materialize(self.seed.a, year=year)
        cached = self.cache.player_seasons(
            self.seed.hitter, start_year=2026, end_year=2027,
        )
        self.assertEqual(1, cached["games_without_box_scores"])
        self.assertEqual(2, cached["totals"]["batting"]["games"])
        self.assertEqual(1, self.cache.school_leaders(
            self.seed.a, start_year=2026, end_year=2027,
            category="batting_hits",
        )["missing_box_score_games"])

    def test_source_year_ledger_change_blocks_even_fast_read(self):
        self.seal_all()
        for year in (2026, 2027):
            self.cache.materialize(self.seed.a, year=year)
        with sqlite3.connect(self.seed.history.db_path) as conn:
            conn.execute(
                "UPDATE career_years SET ledger_sha256='TAMPERED' WHERE year=2026"
            )
        with self.assertRaises(CareerStatsCacheConflict):
            self.cache.player_seasons(
                self.seed.hitter, start_year=2026, end_year=2027,
            )
        with self.assertRaises(CareerStatsCacheConflict):
            self.cache.school_leaders(
                self.seed.a, start_year=2026, end_year=2027,
                category="batting_hits",
            )

    def test_raw_score_change_requires_explicit_audit_and_never_mutates_cache(self):
        self.seal_all()
        self.cache.materialize(self.seed.a, year=2026)
        old = self.cache.player_seasons(
            self.seed.hitter, start_year=2026, end_year=2026,
        )
        with sqlite3.connect(self.seed.history.db_path) as conn:
            conn.execute(
                "UPDATE historical_matches SET payload_json='{}' WHERE year=2026"
            )
        # Fast mode trusts the source's sealed metadata. It intentionally
        # does not claim to verify all source payload bytes on each read.
        fast = self.cache.player_seasons(
            self.seed.hitter, start_year=2026, end_year=2026,
        )
        self.assertEqual(old["totals"], fast["totals"])
        self.assertFalse(fast["source_payloads_rechecked_on_read"])
        with self.assertRaises(ValueError):
            self.cache.player_seasons(
                self.seed.hitter, start_year=2026, end_year=2026,
                verify_source=True,
            )
        with self.assertRaises(ValueError):
            self.cache.materialize(self.seed.a, year=2026)

    def test_missing_other_player_cache_row_is_detected_on_fast_read(self):
        self.cache.materialize(self.seed.a, year=2026)
        with sqlite3.connect(self.cache.path) as conn:
            conn.execute(
                "DELETE FROM player_year_stat_cache WHERE school_id=? "
                "AND year=2026 AND player_id != ? "
                "AND player_id IN (SELECT player_id FROM player_year_stat_cache "
                "WHERE school_id=? AND year=2026 AND player_id != ? LIMIT 1)",
                (self.seed.a, self.seed.hitter, self.seed.a, self.seed.hitter),
            )
        with self.assertRaisesRegex(CareerStatsCacheConflict, "coverage"):
            self.cache.player_seasons(
                self.seed.hitter, start_year=2026, end_year=2026,
            )

    def test_cache_row_checksum_and_wrong_database_target_rejected(self):
        self.cache.materialize(self.seed.a, year=2026)
        with sqlite3.connect(self.cache.path) as conn:
            conn.execute(
                "UPDATE player_year_stat_cache SET payload_json='{}' "
                "WHERE year=2026 AND player_id=?", (self.seed.hitter,),
            )
        with self.assertRaises(CareerStatsCacheConflict):
            self.cache.player_seasons(
                self.seed.hitter, start_year=2026, end_year=2026,
            )
        with self.assertRaises(CareerStatsCacheConflict):
            self.cache.materialize(self.seed.a, year=2026)
        with self.assertRaises(ValueError):
            CareerPlayerStatCache(self.seed.view, self.seed.history.db_path)
        with self.assertRaises(ValueError):
            CareerPlayerStatCache(self.seed.view, self.seed.rosters.db_path)


if __name__ == "__main__":
    unittest.main()
