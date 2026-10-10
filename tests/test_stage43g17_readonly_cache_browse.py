"""Stage43G-17: no-write cache routing and fail-closed history GUI tests."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import unittest

from test_stage43g16_history_gui_navigation import (
    Stage43G16HistoryGuiNavigationTests,
)
from phase2_engine.career_history_browse_model import HistoryRoute
from phase2_engine.career_player_stat_cache import (
    CareerPlayerStatCache, CareerStatsCacheConflict,
)


class Stage43G17ReadonlyCacheBrowseTests(unittest.TestCase):
    def setUp(self):
        # Reuse the canonical game-slot fixture and its real A-history.
        self.seed = Stage43G16HistoryGuiNavigationTests(
            "test_home_years_and_provenance_never_claim_official_results"
        )
        self.seed.setUp()
        self.model = self.seed.model
        self.a = self.seed.fixture.a
        self.hitter = self.seed.fixture.hitter
        self.cache_path = self.seed.root / "derived_player_stats.sqlite3"
        self.builder = CareerPlayerStatCache(self.model.stats, self.cache_path)

    def tearDown(self):
        self.seed.tearDown()

    def build(self, *years):
        for year in years:
            self.builder.materialize(self.a, year=year)

    def test_cache_absent_never_created_and_raw_is_fully_checked(self):
        originals = (
            self.seed.fixture.history.db_path.read_bytes(),
            self.seed.fixture.rosters.db_path.read_bytes(),
        )
        player = self.model.player_page(2026, self.hitter)
        leaders = self.model.leaders_page(2026, self.a)
        self.assertEqual("raw_archived_A_verified", player["source_validation"])
        self.assertEqual("raw_archived_A_verified", leaders["source_validation"])
        self.assertTrue(player["source_payloads_rechecked_on_read"])
        self.assertFalse(self.cache_path.exists())
        self.assertEqual(originals, (
            self.seed.fixture.history.db_path.read_bytes(),
            self.seed.fixture.rosters.db_path.read_bytes(),
        ))

    def test_sealed_cache_matches_original_and_changes_no_database_bytes(self):
        expected = self.model.stats.player_seasons(
            self.hitter, start_year=2026, end_year=2026
        )
        expected_leaders = self.model.stats.school_leaders(
            self.a, start_year=2026, end_year=2026,
            category="batting_hits",
        )
        self.build(2026)
        before = tuple(path.read_bytes() for path in (
            self.cache_path, self.seed.fixture.history.db_path,
            self.seed.fixture.rosters.db_path,
        ))
        player = self.model.player_page(2026, self.hitter)
        leaders = self.model.leaders_page(2026, self.a)
        self.assertEqual("sealed_cache_ledger_checked",
                         player["source_validation"])
        self.assertEqual("sealed_cache_ledger_checked",
                         leaders["source_validation"])
        self.assertFalse(player["source_payloads_rechecked_on_read"])
        self.assertFalse(leaders["source_payloads_rechecked_on_read"])
        self.assertEqual(expected["seasons"], player["season_stats"])
        self.assertEqual(expected["totals"], player["career_stats"])
        self.assertEqual(expected_leaders["rows"], leaders["records"]["rows"])
        after = tuple(path.read_bytes() for path in (
            self.cache_path, self.seed.fixture.history.db_path,
            self.seed.fixture.rosters.db_path,
        ))
        self.assertEqual(before, after)

    def test_active_or_unmaterialized_year_uses_verified_raw(self):
        self.build(2026)
        # Active 2027: no source materialization, even if 2026 was cached.
        player = self.model.player_page(2027, self.hitter)
        self.assertEqual("mixed_cache_ledger_and_raw_A_verified",
                         player["source_validation"])
        self.assertEqual((1, 1), (
            player["cached_year_count"], player["raw_year_count"]
        ))
        self.assertEqual(2, player["career_stats"]["batting"]["games"])
        # Newly sealed 2027 remains raw within mixed mode until cached.
        self.seed.fixture.history.seal_year(2027, expected_match_count=1)
        incomplete = self.model.player_page(2027, self.hitter)
        self.assertEqual("mixed_cache_ledger_and_raw_A_verified",
                         incomplete["source_validation"])
        self.build(2027)
        complete = self.model.player_page(2027, self.hitter)
        self.assertEqual("sealed_cache_ledger_checked",
                         complete["source_validation"])
        self.assertEqual(incomplete["career_stats"], complete["career_stats"])

    def test_stale_source_ledger_never_silently_falls_back(self):
        self.build(2026)
        previous = self.seed.nav.current
        with sqlite3.connect(self.seed.fixture.history.db_path) as conn:
            conn.execute(
                "UPDATE career_years SET ledger_sha256='TAMPERED' "
                "WHERE year=2026"
            )
        with self.assertRaisesRegex(CareerStatsCacheConflict, "source changed"):
            self.seed.nav.open(HistoryRoute(
                "player", 2026, player_id=self.hitter,
            ))
        self.assertEqual(previous, self.seed.nav.current)
        with self.assertRaises(CareerStatsCacheConflict):
            self.model.leaders_page(2026, self.a)

    def test_cache_row_tamper_is_rejected_not_disguised_as_raw(self):
        self.build(2026)
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute(
                "UPDATE player_year_stat_cache SET payload_sha256='BROKEN' "
                "WHERE year=2026 AND player_id=?",
                (self.hitter,),
            )
        with self.assertRaises(CareerStatsCacheConflict):
            self.model.player_page(2026, self.hitter)
        with self.assertRaises(CareerStatsCacheConflict):
            self.model.leaders_page(2026, self.a)

    def test_read_adapter_refuses_writes_and_schema_creation(self):
        self.build(2026)
        before = self.cache_path.read_bytes()
        with self.assertRaises(PermissionError):
            self.model.stats_cache.materialize(self.a, year=2026)
        with self.assertRaises(PermissionError):
            self.model.stats_cache.player_seasons(
                self.hitter, start_year=2026, end_year=2026,
                verify_source=True,
            )
        with self.model.stats_cache._connection() as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE should_not_exist(x INTEGER)")
        self.assertEqual(before, self.cache_path.read_bytes())

    def test_present_broken_cache_schema_refuses_gui_read(self):
        # Unlike an absent cache, an existing malformed cache cannot be
        # silently interpreted as a normal cache miss.
        self.cache_path.write_bytes(b"not sqlite")
        with self.assertRaises(CareerStatsCacheConflict):
            self.model.player_page(2026, self.hitter)


if __name__ == "__main__":
    unittest.main()
