"""Stage43G-31: source separated historical school/player year read models."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_calendar_v2 import (
    CareerCalendarV2Archive, explicit_sandbox_plan,
)
from phase2_engine.career_cross_era_browse_model import (
    CareerCrossEraBrowseConflict, CareerCrossEraBrowseModel,
)
from phase2_engine.career_history_scale_audit import synthetic_ability_record
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_player_records import BATTER, PITCHER
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_v2_option_a_archive import CareerV2OptionAArchive
from phase2_engine.career_v2_roster_attribution import CareerV2RosterAttribution
from phase2_engine.career_v2_player_stat_cache import CareerV2PlayerStatCache
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
COMP = "CMP000086"
SEED = 2026101101


class Stage43G31CrossEraBrowseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = DataRepository(ROOT / "data")
        self.a, self.b = sorted(self.repo.school_to_program)[:2]
        self.old = self.root / "historical_matches.sqlite3"
        self.v2 = self.root / "fictional_option_a_v2.sqlite3"
        self.calendar = self.root / "sandbox_calendar_v2.sqlite3"
        self.rosters = CareerRosterArchive(
            self.root / "career_rosters.sqlite3"
        )
        self.legacy = HistoricalMatchArchive(self.old)
        self.future = CareerV2OptionAArchive(
            self.v2, self.calendar, legacy_archive_path=self.old,
        )
        self.cache = CareerV2PlayerStatCache(
            CareerV2RosterAttribution(self.future, self.rosters),
            self.root / "fictional_v2_player_stat_cache.sqlite3",
        )
        self.model = CareerCrossEraBrowseModel(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def setup_rosters(self):
        generator = PlayerRosterGenerator()
        # Two intentionally disconnected synthetic calendar eras; DO NOT
        # imply that the game advanced 7,974 years of roster transitions.
        for school in (self.a, self.b):
            self.rosters.save_initial_roster(
                generator.generate_for_school_id(
                    self.repo, school, 2026, SEED,
                )
            )
        with self.rosters._connect() as conn:
            for school in (self.a, self.b):
                CareerRosterArchive._insert(
                    conn,
                    generator.generate_for_school_id(
                        self.repo, school, 10000, SEED,
                    ),
                )

    def sample(self, year, match_id):
        row = synthetic_ability_record(
            year, COMP, match_id, self.a, self.b, 1,
        )
        for school in (self.a, self.b):
            players = self.rosters.roster(year, school).players
            batters = [
                b for b in row["ability_detail"]["batter_stats"]
                if b["school_id"] == school
            ]
            for item, player in zip(batters, players[:9]):
                item["player_id"] = player.player_id
                for key in BATTER:
                    item.setdefault(key, 0)
                item["plate_appearances"] = 4
            pitcher = next(p for p in players if p.primary_position == "P")
            for item in row["ability_detail"]["pitcher_stats"]:
                if item["school_id"] == school:
                    item["player_id"] = pitcher.player_id
                    for key in PITCHER:
                        item.setdefault(key, 0)
                    item["outs_recorded"] = 27
                    item["batters_faced"] = 30
                    item["runs_allowed"] = item["earned_runs"]
        if year == 10000:
            row.pop("match_date")
            row["completed_on"] = ""
            row["game_day_token"] = "G10000:04-01"
            row["date_source"] = "fictional_v2_day_slot"
        return row

    def setup_both(self):
        self.setup_rosters()
        self.legacy.sync(
            year=2026, rng_seed=17, resolver_contract="stage43g31_test",
            plan_fingerprint="legacy-2026",
            completed=[self.sample(2026, "OLD")],
        )
        self.legacy.seal_year(2026, expected_match_count=1)
        CareerCalendarV2Archive(self.calendar).record(
            explicit_sandbox_plan(
                10000, {COMP: ["04-01"]},
                approved_for_fictional_game=True,
            )
        )
        self.future.append(10000, self.sample(10000, "FUTURE"))
        self.future.seal_year(10000, expected_match_count=1)
        self.cache.materialize(10000, self.a)
        self.cache.materialize(10000, self.b)

    def test_school_years_provenance_and_score_only_per_year(self):
        self.setup_both()
        files = [self.old, self.v2, self.calendar,
                 self.rosters.db_path, self.cache.path]
        before = [file_sha256(p) for p in files]
        result = self.model.school_years([2026, 10000], self.a)
        self.assertEqual([2026, 10000],
                         [r["year"] for r in result["sections"]])
        self.assertEqual(1, result["sections"][0]["wins_from_saved_games"])
        self.assertEqual(1, result["sections"][1]["wins_from_saved_games"])
        self.assertEqual("YYYY-MM-DD",
                         result["sections"][0]["matches"][0]["date_kind"])
        self.assertEqual("G10000:04-01",
                         result["sections"][1]["matches"][0]["date"])
        self.assertFalse(result["combined_career_stats_authorized"])
        self.assertEqual(
            [{"from_year": 2027, "through_year": 9999}],
            result["unverified_intervening_year_intervals"],
        )
        self.assertEqual(before, [file_sha256(p) for p in files])

    def test_player_legacy_member_not_automatically_future_member(self):
        self.setup_both()
        old_id = self.rosters.roster(2026, self.a).players[0].player_id
        newer_id = self.rosters.roster(10000, self.a).players[0].player_id
        self.assertNotEqual(old_id, newer_id)
        old = self.model.player_years([2026, 10000], self.a, old_id)
        self.assertEqual("verified_box_score", old["sections"][0]["status"])
        self.assertEqual("not_on_saved_school_year_roster",
                         old["sections"][1]["status"])
        self.assertEqual(1, old["sections"][0]["statistics"]["batting"]["hits"])
        self.assertIsNone(old["combined_career_totals"])
        self.assertFalse(old["cross_year_player_identity_continuity_proven"])
        newer = self.model.player_years([2026, 10000], self.a, newer_id)
        self.assertEqual("not_on_saved_school_year_roster",
                         newer["sections"][0]["status"])
        self.assertEqual("verified_box_score", newer["sections"][1]["status"])
        self.assertEqual(1, newer["sections"][1]["statistics"]["batting"]["hits"])

    def test_unknown_player_rejected_not_guessed_by_name(self):
        self.setup_both()
        with self.assertRaisesRegex(
            CareerCrossEraBrowseConflict, "not on any"
        ):
            self.model.player_years([2026, 10000], self.a, "PLY-UNKNOWN")

    def test_missing_v2_cache_does_not_autocreate_on_read(self):
        self.setup_both()
        self.cache.path.unlink()
        pid = self.rosters.roster(10000, self.a).players[0].player_id
        with self.assertRaises(FileNotFoundError):
            self.model.player_years([2026, 10000], self.a, pid)
        self.assertFalse(self.cache.path.exists())

    def test_tampered_v2_cache_refused(self):
        self.setup_both()
        with sqlite3.connect(self.cache.path) as con:
            con.execute(
                "UPDATE v2_player_year_stat_cache SET payload_sha256='BAD' "
                "WHERE year=10000 AND school_id=?",
                (self.a,),
            )
        pid = self.rosters.roster(10000, self.a).players[0].player_id
        with self.assertRaises(ValueError):
            self.model.player_years([2026, 10000], self.a, pid)

    def test_unsealed_year_cannot_be_displayed(self):
        self.setup_rosters()
        self.legacy.sync(
            year=2026, rng_seed=17, resolver_contract="stage43g31_test",
            plan_fingerprint="legacy-2026",
            completed=[self.sample(2026, "UNSEALED")],
        )
        with self.assertRaisesRegex(ValueError, "not sealed"):
            self.model.school_years([2026], self.a)

    def test_missing_year_and_invalid_inputs(self):
        with self.assertRaises(ValueError):
            self.model.school_years([], self.a)
        with self.assertRaises(ValueError):
            self.model.school_years([2026], "")
        with self.assertRaises(ValueError):
            self.model.player_years([2026], self.a, "")
        with self.assertRaisesRegex(ValueError, "not saved"):
            self.model.school_years([2026], self.a)
        self.assertFalse(self.old.exists())
        self.assertFalse(self.v2.exists())

    def test_browse_v2_year_without_legacy_creates_no_old_db(self):
        self.setup_rosters()
        CareerCalendarV2Archive(self.calendar).record(
            explicit_sandbox_plan(
                10000, {COMP: ["04-01"]},
                approved_for_fictional_game=True,
            )
        )
        self.future.append(10000, self.sample(10000, "FUTURE"))
        self.future.seal_year(10000, expected_match_count=1)
        result = self.model.school_years([10000], self.a)
        self.assertEqual(1, result["sections"][0]["match_count"])
        self.assertFalse(self.old.exists())


if __name__ == "__main__":
    unittest.main()
