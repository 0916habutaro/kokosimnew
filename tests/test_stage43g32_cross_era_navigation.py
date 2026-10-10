"""Stage43G-32: verified school/player navigation and unmodified save data."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_cross_era_navigation import (
    CareerCrossEraNavigationConflict, CareerCrossEraNavigator,
    MAX_SELECTED_YEARS,
)
from phase2_engine.career_history_scale_benchmark import file_sha256
import test_stage43g31_cross_era_browse_model as stage43g31_tests


class Stage43G32CrossEraNavigationTests(unittest.TestCase):
    def setUp(self):
        # Reuse the proven 2026 legacy + 10000 fictional v2 integration
        # fixture from Stage43G-31 without subclassing its test cases.
        self.fixture = stage43g31_tests.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.nav = CareerCrossEraNavigator(self.fixture.root)
        self.years = [2026, 10000]
        self.school = self.fixture.a

    def test_school_page_year_routing_and_roster_links_read_only(self):
        files = [
            self.fixture.old, self.fixture.v2, self.fixture.calendar,
            self.fixture.rosters.db_path, self.fixture.cache.path,
        ]
        before = [file_sha256(p) for p in files]
        result = self.nav.school_page(
            self.years, self.school, selected_year=2026,
        )
        self.assertEqual("cross_era_school", result["screen"])
        self.assertEqual("YYYY-MM-DD", result["date_kind"])
        self.assertEqual(1, result["match_total"])
        self.assertEqual(1, result["match_wins_from_saved_games"])
        self.assertEqual(
            "saved_roster_and_permanent_ids_verified",
            result["annual_roster_state"],
        )
        self.assertEqual(
            len(self.fixture.rosters.roster(2026, self.school).players),
            len(result["player_targets"]),
        )
        self.assertFalse(result["combined_career_stats_authorized"])
        self.assertFalse(result["official_gui_connected"])
        self.assertEqual(before, [file_sha256(p) for p in files])

    def test_school_year_links_keep_exact_explicit_selection(self):
        result = self.nav.school_page(
            self.years, self.school, selected_year=2026,
        )
        target = result["year_targets"][1]
        self.assertEqual(self.years, target["years"])
        future = self.nav.follow(target)
        self.assertEqual(10000, future["selected_year"])
        self.assertEqual("G{year}:MM-DD", future["date_kind"])
        self.assertEqual("G10000:04-01", future["match_page"][0]["date"])
        self.assertEqual(
            [{"from_year": 2027, "through_year": 9999}],
            future["unverified_intervening_year_intervals"],
        )

    def test_opponent_school_navigation_uses_id_not_display_name(self):
        page = self.nav.school_page(
            self.years, self.school, selected_year=2026,
        )
        link = page["opponent_school_targets"][0]["target"]
        self.assertEqual(self.fixture.b, link["school_id"])
        other = self.nav.follow(link)
        self.assertEqual(self.fixture.b, other["school_id"])
        self.assertEqual(1, other["match_total"])
        self.assertEqual(1, other["match_losses_from_saved_games"])

    def test_player_link_back_school_and_year_membership_disclosure(self):
        page = self.nav.school_page(
            self.years, self.school, selected_year=2026,
        )
        first = page["player_targets"][0]
        self.assertEqual(
            "player", first["target"]["view"],
        )
        viewed = self.nav.follow(first["target"])
        self.assertEqual(first["player_id"], viewed["player_id"])
        self.assertEqual("cross_era_player", viewed["screen"])
        self.assertIsNone(viewed["combined_career_totals"])
        self.assertFalse(viewed["identity_continuity_proven"])
        self.assertEqual(
            "cross_era_school",
            self.nav.follow(viewed["back_to_school_target"])["screen"],
        )
        future_view = self.nav.follow(viewed["year_targets"][1])
        self.assertEqual(10000, future_view["selected_year"])
        self.assertEqual(
            "not_on_saved_school_year_roster",
            future_view["selected_status"],
        )
        self.assertIsNone(future_view["selected_statistics"])

    def test_v2_player_link_only_uses_persisted_permanent_id(self):
        future = self.nav.school_page(
            self.years, self.school, selected_year=10000,
        )
        expected_id = self.fixture.rosters.roster(
            10000, self.school,
        ).players[0].player_id
        target = next(
            r["target"] for r in future["player_targets"]
            if r["player_id"] == expected_id
        )
        value = self.nav.follow(target)
        self.assertEqual("verified_box_score", value["selected_status"])
        self.assertEqual(expected_id, value["player_id"])
        self.assertIsNotNone(value["selected_statistics"])

    def test_page_limit_offset_only_applies_to_selected_year(self):
        page = self.nav.school_page(
            self.years, self.school, selected_year=2026,
            limit=1, offset=1,
        )
        self.assertEqual(1, page["match_total"])
        self.assertEqual([], page["match_page"])
        self.assertEqual([], page["opponent_school_targets"])
        self.assertGreater(len(page["player_targets"]), 0)

    def test_reject_malformed_navigation_target_without_writes(self):
        for target in (
            {}, {"view": "bad"}, {"view": "school", "years": self.years,
                                   "selected_year": 2026,
                                   "school_id": self.school, "extra": "x"},
            {"view": "player", "years": self.years, "selected_year": 2026,
             "school_id": self.school},
            {"view": "school", "years": [10000, 2026],
             "selected_year": 2026, "school_id": self.school},
        ):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    self.nav.follow(target)

    def test_reject_missing_year_large_year_selection_and_bool(self):
        invalid = (
            [], [2026, 2026], [10000, 2026],
            list(range(2026, 2026 + MAX_SELECTED_YEARS + 1)),
            [True, 10000],
        )
        for years in invalid:
            with self.subTest(years=years):
                with self.assertRaises(ValueError):
                    self.nav.school_page(
                        years, self.school, selected_year=2026,
                    )
        with self.assertRaises(ValueError):
            self.nav.school_page(
                self.years, self.school, selected_year=2027,
            )
        for kwargs in ({"limit": 0}, {"limit": 101},
                       {"offset": -1}, {"offset": True},
                       {"verify_source": "yes"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.nav.school_page(
                        self.years, self.school,
                        selected_year=2026, **kwargs,
                    )

    def test_tampered_roster_identity_blocks_player_links(self):
        affected = self.fixture.rosters.roster(
            2026, self.school,
        ).players[0].player_id
        with sqlite3.connect(self.fixture.rosters.db_path) as conn:
            conn.execute(
                "UPDATE career_player_identities SET identity_sha256='BAD' "
                "WHERE player_id=?",
                (affected,),
            )
        with self.assertRaises(ValueError):
            self.nav.school_page(
                self.years, self.school, selected_year=2026,
            )

    def test_no_year_roster_means_no_player_link_not_inferred(self):
        with sqlite3.connect(self.fixture.rosters.db_path) as conn:
            conn.execute(
                "DELETE FROM career_school_rosters "
                "WHERE year=2026 AND school_id=?",
                (self.school,),
            )
        value = self.nav.school_page(
            self.years, self.school, selected_year=2026,
        )
        self.assertEqual("missing_annual_roster", value["annual_roster_state"])
        self.assertEqual([], value["player_targets"])
        self.assertEqual(1, value["match_total"])

    def test_missing_v2_cache_does_not_break_school_and_is_not_created(self):
        self.fixture.cache.path.unlink()
        school = self.nav.school_page(
            self.years, self.school, selected_year=10000,
        )
        self.assertEqual(1, school["match_total"])
        with self.assertRaises(FileNotFoundError):
            self.nav.follow(school["player_targets"][0]["target"])
        self.assertFalse(self.fixture.cache.path.exists())

    def test_sealed_source_tamper_blocks_navigation(self):
        with sqlite3.connect(self.fixture.v2) as conn:
            conn.execute(
                "UPDATE v2_game_years SET ledger_sha256='BAD' "
                "WHERE year=10000",
            )
        with self.assertRaises(ValueError):
            self.nav.school_page(
                self.years, self.school, selected_year=2026,
            )


if __name__ == "__main__":
    unittest.main()
