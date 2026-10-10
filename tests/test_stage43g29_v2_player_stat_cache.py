"""Stage43G-29: separate sealed-v2 immutable stat cache integration tests."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_calendar_v2 import (
    CareerCalendarV2Archive, explicit_sandbox_plan,
)
from phase2_engine.career_history_scale_audit import synthetic_ability_record
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_player_records import BATTER, PITCHER
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_v2_option_a_archive import CareerV2OptionAArchive
from phase2_engine.career_v2_roster_attribution import CareerV2RosterAttribution
from phase2_engine.career_v2_player_stat_cache import (
    CareerV2PlayerStatCache, CareerV2StatsCacheConflict,
)
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
YEAR = 10000
COMP = "CMP000086"
SEED = 2026101101


class Stage43G29V2PlayerStatCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.v2 = self.root / "fictional_option_a_v2.sqlite3"
        self.calendar = self.root / "sandbox_calendar_v2.sqlite3"
        self.roster_file = self.root / "career_rosters.sqlite3"
        self.cache_file = self.root / "fictional_v2_player_stat_cache.sqlite3"
        self.old = self.root / "historical_matches.sqlite3"
        self.old_cache = self.root / "career_player_stats_cache.sqlite3"
        self.repo = DataRepository(ROOT / "data")
        self.a, self.b = sorted(self.repo.school_to_program)[:2]
        CareerCalendarV2Archive(self.calendar).record(
            explicit_sandbox_plan(
                YEAR, {COMP: ["04-01", "04-02"]},
                approved_for_fictional_game=True,
            )
        )
        self.rosters = CareerRosterArchive(self.roster_file)
        generator = PlayerRosterGenerator()
        for school in (self.a, self.b):
            self.rosters.save_initial_roster(
                generator.generate_for_school_id(
                    self.repo, school, YEAR, SEED,
                )
            )
        self.matches = CareerV2OptionAArchive(
            self.v2, self.calendar, legacy_archive_path=self.old,
        )
        self.view = CareerV2RosterAttribution(self.matches, self.rosters)
        self.cache = CareerV2PlayerStatCache(self.view, self.cache_file)

    def tearDown(self):
        self.temp.cleanup()

    def game(self, mid="G1", day="04-01"):
        row = synthetic_ability_record(
            YEAR, COMP, mid, self.a, self.b, int(day[-2:]),
        )
        row.pop("match_date")
        row["completed_on"] = ""
        row["game_day_token"] = f"G{YEAR}:{day}"
        row["date_source"] = "fictional_v2_day_slot"
        for school in (self.a, self.b):
            members = self.rosters.roster(YEAR, school).players
            bat = [
                x for x in row["ability_detail"]["batter_stats"]
                if x["school_id"] == school
            ]
            for stat, member in zip(bat, members[:9]):
                stat["player_id"] = member.player_id
                for k in BATTER:
                    stat.setdefault(k, 0)
                stat["plate_appearances"] = 4
            arm = next(p for p in members if p.primary_position == "P")
            for stat in row["ability_detail"]["pitcher_stats"]:
                if stat["school_id"] == school:
                    stat["player_id"] = arm.player_id
                    for k in PITCHER:
                        stat.setdefault(k, 0)
                    stat["outs_recorded"] = 27
                    stat["batters_faced"] = 30
                    stat["runs_allowed"] = stat["earned_runs"]
        return row

    def sealed(self):
        self.matches.append(YEAR, self.game())
        self.matches.append(YEAR, self.game("G2", "04-02"))
        self.matches.seal_year(YEAR, expected_match_count=2)

    def test_cache_creation_repeat_full_verification_and_archive_sha(self):
        self.sealed()
        source_paths = (self.v2, self.calendar, self.roster_file)
        before = [file_sha256(p) for p in source_paths]
        first = self.cache.materialize(YEAR, self.a)
        self.assertTrue(first["inserted"])
        self.assertEqual(2, first["team_match_count"])
        self.assertFalse(self.cache.materialize(YEAR, self.a)["inserted"])
        self.assertTrue(self.cache.materialize(YEAR, self.b)["inserted"])
        fast = self.cache.read_year(YEAR, self.a)
        deep = self.cache.read_year(YEAR, self.a, verify_source=True)
        self.assertEqual(fast["rows"], deep["rows"])
        self.assertTrue(deep["source_payloads_rechecked_on_read"])
        self.assertFalse(fast["source_payloads_rechecked_on_read"])
        pid = self.rosters.roster(YEAR, self.a).players[0].player_id
        line = next(x for x in fast["rows"] if x["player_id"] == pid)
        self.assertEqual(2, line["batting"]["games"])
        self.assertEqual(8, line["batting"]["at_bats"])
        self.assertEqual(2, line["batting"]["hits"])
        self.assertEqual(.250, line["batting"]["batting_average"])
        self.assertEqual(before, [file_sha256(p) for p in source_paths])
        self.assertTrue(self.cache_file.exists())
        self.assertFalse(self.old.exists())
        self.assertFalse(self.old_cache.exists())
        self.assertFalse(fast["merged_into_legacy_player_career"])

    def test_unsealed_year_and_no_cache_creation(self):
        self.matches.append(YEAR, self.game())
        with self.assertRaisesRegex(ValueError, "sealed"):
            self.cache.materialize(YEAR, self.a)
        self.assertFalse(self.cache_file.exists())

    def test_read_only_missing_cache_does_not_create_db(self):
        self.sealed()
        with self.assertRaises(FileNotFoundError):
            self.cache.read_year(YEAR, self.a)
        self.assertFalse(self.cache_file.exists())

    def test_missing_school_coverage_rejected(self):
        self.sealed()
        self.cache.materialize(YEAR, self.a)
        with self.assertRaisesRegex(CareerV2StatsCacheConflict, "no materialized"):
            self.cache.read_year(YEAR, self.b)

    def test_tamper_cache_player_checksum_rejected(self):
        self.sealed()
        self.cache.materialize(YEAR, self.a)
        with sqlite3.connect(self.cache_file) as con:
            con.execute(
                "UPDATE v2_player_year_stat_cache SET payload_sha256='WRONG' "
                "WHERE school_id=? AND year=? AND player_id=("
                "SELECT MIN(player_id) FROM v2_player_year_stat_cache "
                "WHERE school_id=? AND year=?)",
                (self.a, YEAR, self.a, YEAR),
            )
        with self.assertRaisesRegex(CareerV2StatsCacheConflict, "digest"):
            self.cache.read_year(YEAR, self.a)

    def test_tamper_cache_coverage_rejected(self):
        self.sealed()
        self.cache.materialize(YEAR, self.a)
        with sqlite3.connect(self.cache_file) as con:
            con.execute(
                "DELETE FROM v2_player_year_stat_cache WHERE "
                "school_id=? AND year=? AND player_id=("
                "SELECT MIN(player_id) FROM v2_player_year_stat_cache "
                "WHERE school_id=? AND year=?)",
                (self.a, YEAR, self.a, YEAR),
            )
        with self.assertRaisesRegex(CareerV2StatsCacheConflict, "coverage"):
            self.cache.read_year(YEAR, self.a)
        with self.assertRaisesRegex(CareerV2StatsCacheConflict, "immutable"):
            self.cache.materialize(YEAR, self.a)

    def test_tamper_sealed_ledger_metadata_rejected(self):
        self.sealed()
        self.cache.materialize(YEAR, self.a)
        with sqlite3.connect(self.v2) as con:
            con.execute(
                "UPDATE v2_game_years SET ledger_sha256='WRONG' WHERE year=?",
                (YEAR,),
            )
        with self.assertRaisesRegex(CareerV2StatsCacheConflict, "metadata"):
            self.cache.read_year(YEAR, self.a)

    def test_roster_identity_change_rejected_at_fast_read(self):
        self.sealed()
        self.cache.materialize(YEAR, self.a)
        with sqlite3.connect(self.roster_file) as con:
            con.execute(
                "UPDATE career_player_identities SET identity_sha256='BAD' "
                "WHERE player_id=(SELECT MIN(player_id) "
                "FROM career_player_identities WHERE school_id=?)", (self.a,),
            )
        with self.assertRaises(ValueError):
            self.cache.read_year(YEAR, self.a)

    def test_full_source_audit_detects_game_sha_tamper(self):
        self.sealed()
        self.cache.materialize(YEAR, self.a)
        with sqlite3.connect(self.v2) as con:
            con.execute(
                "UPDATE v2_option_a_matches SET record_sha256='BAD' "
                "WHERE match_id='G1'",
            )
        # Fast mode guarantees seal metadata + roster + cached-row
        # integrity, not rechecking every original match payload.
        self.assertFalse(self.cache.read_year(YEAR, self.a)[
            "source_payloads_rechecked_on_read"
        ])
        with self.assertRaises(ValueError):
            self.cache.read_year(YEAR, self.a, verify_source=True)

    def test_invalid_cache_path_or_read_arguments(self):
        for path in (
            self.old_cache, self.roster_file, self.v2,
        ):
            with self.assertRaises(ValueError):
                CareerV2PlayerStatCache(self.view, path)
        with self.assertRaises(ValueError):
            self.cache.read_year(YEAR, self.a, verify_source="yes")
        with self.assertRaises(ValueError):
            self.cache.read_year(True, self.a)
        with self.assertRaises(ValueError):
            self.cache.materialize(YEAR, "")

    def test_mutated_source_replay_refused_after_cache(self):
        self.sealed()
        self.cache.materialize(YEAR, self.a)
        replay = self.game()
        replay["ability_detail"]["batter_stats"][0]["hits"] = 2
        with self.assertRaises(ValueError):
            self.matches.append(YEAR, replay)
        self.assertFalse(self.cache.materialize(YEAR, self.a)["inserted"])


if __name__ == "__main__":
    unittest.main()
