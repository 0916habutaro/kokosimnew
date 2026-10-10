"""Stage43G-16 career history pilot/headless navigation contracts.

Uses real Stage43G-14 A history fixture; no Tk display required in CI.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

import test_stage43g14_player_records as fixture
from phase2_engine.career_history_browse_model import (
    CareerHistoryBrowseModel, CareerHistoryNavigator, HistoryRoute, SOURCE,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_player_records import CareerPlayerRecordView


class Stage43G16HistoryGuiNavigationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios"
        )
        self.fixture.setUp()
        # The Stage43G-14 fixture names its SQLite files matches.sqlite3
        # and rosters.sqlite3. A real career slot uses canonical filenames.
        # Copy the populated fixture into the *actual* save layout and bind
        # subsequent tamper/score-only tests to this same canonical slot.
        work = Path(self.fixture.temp.name)
        self.root = work / "career_slot"
        self.root.mkdir()
        match_path = self.root / "historical_matches.sqlite3"
        roster_path = self.root / "career_rosters.sqlite3"
        shutil.copy2(self.fixture.history.db_path, match_path)
        shutil.copy2(self.fixture.rosters.db_path, roster_path)
        self.fixture.history = HistoricalMatchArchive(match_path)
        self.fixture.rosters = CareerRosterArchive(roster_path)
        self.fixture.view = CareerPlayerRecordView(
            self.fixture.history, self.fixture.rosters
        )
        self.model = CareerHistoryBrowseModel(
            fixture.ROOT / "data", self.root
        )
        self.nav = CareerHistoryNavigator(self.model, year=2027)

    def tearDown(self):
        self.fixture.tearDown()

    def test_gui_pilot_module_imports_without_creating_a_window(self):
        from phase2_engine.career_history_gui_pilot import (
            APP_NAME, CareerHistoryGuiPilot,
        )
        self.assertIn("試験版", APP_NAME)
        self.assertTrue(callable(CareerHistoryGuiPilot))

    def test_home_years_and_provenance_never_claim_official_results(self):
        years = self.model.years()
        self.assertEqual([2026, 2027], [y["year"] for y in years])
        self.assertEqual(["sealed", "active"], [y["state"] for y in years])
        self.assertEqual(SOURCE, self.nav.render()["source_kind"])
        self.assertEqual(2, len(self.nav.render()["years"]))

    def test_school_search_details_players_and_historical_year_stats(self):
        results = self.model.find_schools(self.fixture.a)
        self.assertTrue(any(r["school_id"] == self.fixture.a for r in results))
        school = self.nav.open(HistoryRoute(
            "school", 2027, school_id=self.fixture.a
        ))
        self.assertEqual("school", school["screen"])
        self.assertEqual(2, school["year_results"]["total_groups"])
        self.assertGreaterEqual(school["historical_players"]["total"], 20)
        self.assertIn(self.fixture.hitter, school["links"]["player_ids"]
                      + [p["player_id"] for p in
                         self.model.school.school_player_index(
                             self.fixture.a, limit=100
                         )["players"]])
        self.assertFalse(school["historical_players"]["status_is_graduation_proof"])

    def test_school_history_as_of_year_excludes_future_newcomers(self):
        older = self.model.school_page(2026, self.fixture.a)
        newer = self.model.school_page(2027, self.fixture.a)
        self.assertEqual(20, older["historical_players"]["total"])
        self.assertEqual(28, newer["historical_players"]["total"])
        self.assertTrue(all(
            item["entry_year"] <= 2026
            for item in older["historical_players"]["players"]
        ))
        self.assertTrue(any(
            item["entry_year"] == 2027
            for item in newer["historical_players"]["players"]
        ))
        self.assertTrue(all(
            item["selected_roster_year"] == 2026
            for item in older["historical_players"]["players"]
        ))

    def test_school_to_player_to_school_backstack_preserves_year(self):
        self.nav.open(HistoryRoute("school", 2027, school_id=self.fixture.a))
        result = self.nav.open(HistoryRoute(
            "player", 2027, player_id=self.fixture.hitter
        ))
        self.assertEqual(self.fixture.a, result["school_id"])
        self.assertEqual([2026, 2027],
                         [row["year"] for row in result["membership"]])
        self.assertEqual(2, result["career_stats"]["batting"]["games"])
        self.assertFalse(result["pitcher_wins_losses_inferred"])
        self.assertEqual("school", self.nav.back()["screen"])
        self.assertEqual(2027, self.nav.current.year)
        self.assertEqual("years", self.nav.back()["screen"])

    def test_school_and_competition_pages_remain_offset_addressable(self):
        school = self.model.school_page(
            2027, self.fixture.a, offset=1, limit=1,
        )
        self.assertEqual(2, school["year_results"]["total_groups"])
        self.assertEqual(2027, school["year_results"]["records"][0]["year"])
        games = self.model.competition_page(
            2027, "CMP000086", offset=1, limit=1,
        )
        self.assertEqual(1, games["matches"]["total"])
        self.assertEqual([], games["matches"]["rows"])
        self.nav.open(HistoryRoute(
            "school", 2027, school_id=self.fixture.a, offset=1,
        ))
        self.assertEqual(1, self.nav.current.offset)
        self.nav.back()
        self.assertEqual("years", self.nav.current.screen)

    def test_competition_and_exact_composite_match_navigation(self):
        comp = self.nav.open(HistoryRoute(
            "competition", 2027, competition_id="CMP000086"
        ))
        self.assertEqual(1, comp["matches"]["total"])
        self.assertFalse(comp["bracket_champion_verified"])
        r = comp["matches"]["rows"][0]
        self.assertEqual("ARCHIVE-2027", r["match_id"])
        full = self.nav.open(HistoryRoute(
            "match", 2027, competition_id=r["competition_id"],
            match_id=r["match_id"]
        ))
        self.assertEqual("recorded", full["inning_score_status"])
        self.assertEqual("recorded", full["box_score_status"])
        self.assertEqual(18, len(full["game"]["inning_scores"]))
        self.assertTrue(full["game"]["batter_stats"])
        self.assertFalse(full["plate_appearance_events_archived"])
        self.assertEqual("competition", self.nav.back()["screen"])

    def test_year_change_never_guesses_missing_match_or_player(self):
        self.nav.open(HistoryRoute(
            "competition", 2027, competition_id="CMP000086",
        ))
        self.assertEqual("years", self.nav.open(
            HistoryRoute("years", 2026)
        )["screen"])
        old = self.nav.open(HistoryRoute(
            "match", 2026, competition_id="CMP000086",
            match_id="ARCHIVE-2026"
        ))
        self.assertEqual(2026, old["year"])
        original = self.nav.current
        with self.assertRaisesRegex(ValueError, "no such saved"):
            self.nav.open(HistoryRoute(
                "match", 2026, competition_id="CMP000086",
                match_id="ARCHIVE-2027"
            ))
        self.assertEqual(original, self.nav.current)
        with self.assertRaises(ValueError):
            self.nav.open(HistoryRoute(
                "player", 2027, player_id="UNKNOWN-PLAYER"
            ))
        self.assertEqual(original, self.nav.current)

    def test_missing_line_score_is_not_faked_and_source_is_game_only(self):
        only_score = {
            "competition_id": "CMP000092", "match_id": "ONLY-SCORE",
            "competition_name": "試験用試合", "match_date": "2027-05-08",
            "completed_on": "2027-05-08",
            "date_source": "game_projection_v1",
            "status": "completed", "stage_code": "MAIN",
            "phase_code": "MAIN_BRACKET", "round_no": 1,
            "team1_id": self.fixture.a, "team2_id": self.fixture.b,
            "team1_score": 2, "team2_score": 1,
            "winner_id": self.fixture.a, "loser_id": self.fixture.b,
            "score_source": "generated_v1",
        }
        self.fixture.history.sync(
            year=2027, rng_seed=fixture.SEED,
            resolver_contract="synthetic_test_v1",
            plan_fingerprint="stage43g14-year-2027",
            completed=[only_score]
        )
        row = self.model.match_page(2027, "CMP000092", "ONLY-SCORE")
        self.assertEqual("not_recorded", row["inning_score_status"])
        self.assertEqual("not_recorded", row["box_score_status"])
        self.assertIsNone(row["game"]["inning_scores"])
        self.assertIsNone(row["game"]["batter_stats"])
        self.assertEqual(SOURCE, row["source_kind"])

    def test_leaderboard_is_verified_A_data_and_player_links(self):
        result = self.nav.open(HistoryRoute(
            "leaders", 2027, school_id=self.fixture.a,
            metric="batting_hits"
        ))
        self.assertEqual("leaders", result["screen"])
        self.assertTrue(result["records"]["rows"])
        self.assertFalse(result["ranking_qualification_inferred"])
        self.assertEqual(2, result["records"]["rows"][0]["stat_value"])

    def test_bad_ids_invalid_page_and_record_sha_rejected(self):
        with self.assertRaises(ValueError):
            self.model.school_page(2027, "BOGUS")
        with self.assertRaises(ValueError):
            self.model.school_page(2027, self.fixture.a, limit=0)
        with self.assertRaises(ValueError):
            self.model.competition_page(2027, "NONEXISTENT")
        with self.assertRaises(ValueError):
            self.model.match_page(2027, "CMP000086", "OTHER-YEAR")
        with sqlite3.connect(self.fixture.history.db_path) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='TAMPERED' "
                "WHERE year=2027 AND competition_id='CMP000086'"
            )
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.model.match_page(2027, "CMP000086", "ARCHIVE-2027")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.model.competition_page(2027, "CMP000086")

    def test_gui_browse_never_creates_cache_or_rewrites_archives(self):
        original_history = self.fixture.history.db_path.read_bytes()
        original_rosters = self.fixture.rosters.db_path.read_bytes()
        self.model.years()
        self.model.school_page(2027, self.fixture.a)
        self.model.player_page(2027, self.fixture.hitter)
        self.model.match_page(2027, "CMP000086", "ARCHIVE-2027")
        self.model.leaders_page(2027, self.fixture.a)
        self.assertFalse(
            (self.root / "derived_player_stats.sqlite3").exists()
        )
        self.assertEqual(original_history, self.fixture.history.db_path.read_bytes())
        self.assertEqual(original_rosters, self.fixture.rosters.db_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
