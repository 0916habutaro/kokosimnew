"""Stage43G-28: strict roster attribution of sealed fictional v2 A scores."""
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
from phase2_engine.career_v2_roster_attribution import (
    CareerV2AttributionConflict, CareerV2RosterAttribution,
)
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
YEAR = 10000
COMP = "CMP000086"
SEED = 2026101101


class Stage43G28V2RosterAttributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.roster_file = self.root / "career_rosters.sqlite3"
        self.v2_file = self.root / "fictional_option_a_v2.sqlite3"
        self.calendar_file = self.root / "sandbox_calendar_v2.sqlite3"
        self.legacy_file = self.root / "historical_matches.sqlite3"
        self.rosters = CareerRosterArchive(self.roster_file)
        self.sidecar = CareerV2OptionAArchive(
            self.v2_file, self.calendar_file,
            legacy_archive_path=self.legacy_file,
        )
        CareerCalendarV2Archive(self.calendar_file).record(
            explicit_sandbox_plan(
                YEAR, {COMP: ["04-01", "04-02"]},
                approved_for_fictional_game=True,
            )
        )
        self.repo = DataRepository(ROOT / "data")
        self.a, self.b = sorted(self.repo.school_to_program)[:2]
        generator = PlayerRosterGenerator()
        for school in (self.a, self.b):
            self.rosters.save_initial_roster(
                generator.generate_for_school_id(
                    self.repo, school, YEAR, SEED,
                )
            )
        self.audit = CareerV2RosterAttribution(self.sidecar, self.rosters)

    def tearDown(self):
        self.tmp.cleanup()

    def sample(self, match_id="FUTURE-A", day="04-01"):
        record = synthetic_ability_record(
            YEAR, COMP, match_id, self.a, self.b, int(day[-2:]),
        )
        record.pop("match_date")
        record["completed_on"] = ""
        record["game_day_token"] = f"G{YEAR}:{day}"
        record["date_source"] = "fictional_v2_day_slot"
        for school in (self.a, self.b):
            members = self.rosters.roster(YEAR, school).players
            batters = [
                x for x in record["ability_detail"]["batter_stats"]
                if x["school_id"] == school
            ]
            for stat, player in zip(batters, members[:9]):
                stat["player_id"] = player.player_id
                for key in BATTER:
                    stat.setdefault(key, 0)
                stat["plate_appearances"] = 4
            pitcher = next(p for p in members if p.primary_position == "P")
            for stat in record["ability_detail"]["pitcher_stats"]:
                if stat["school_id"] == school:
                    stat["player_id"] = pitcher.player_id
                    for key in PITCHER:
                        stat.setdefault(key, 0)
                    stat["outs_recorded"] = 27
                    stat["batters_faced"] = 30
                    stat["runs_allowed"] = stat["earned_runs"]
        return record

    def append_and_seal(self, rows):
        for item in rows:
            self.sidecar.append(YEAR, item)
        self.sidecar.seal_year(YEAR, expected_match_count=len(rows))

    def test_sealed_10000_attribution_stats_and_readonly_sources(self):
        self.append_and_seal([
            self.sample("FUTURE-A"),
            self.sample("FUTURE-B", "04-02"),
        ])
        before = [
            file_sha256(p) for p in
            (self.calendar_file, self.v2_file, self.roster_file)
        ]
        first = self.audit.school_year(YEAR, self.a)
        second = self.audit.school_year(YEAR, self.b)
        self.assertEqual(2, first["team_match_count"])
        self.assertEqual(2, first["source_match_count"])
        self.assertTrue(first["roster_id_attribution_verified"])
        self.assertFalse(first["merged_into_legacy_player_career"])
        self.assertFalse(first["real_tournament_runtime_connected"])
        self.assertEqual(len({p.player_id for p in self.rosters.roster(YEAR, self.a).players[:9]} | {next(p.player_id for p in self.rosters.roster(YEAR, self.a).players if p.primary_position == "P")}), first["player_count"])
        self.assertGreaterEqual(second["player_count"], 9)
        pid = self.rosters.roster(YEAR, self.a).players[0].player_id
        line = next(x for x in first["rows"] if x["player_id"] == pid)
        self.assertEqual(2, line["batting"]["games"])
        self.assertEqual(8, line["batting"]["at_bats"])
        self.assertEqual(2, line["batting"]["hits"])
        self.assertEqual(.250, line["batting"]["batting_average"])
        self.assertEqual(
            before, [file_sha256(p) for p in
                     (self.calendar_file, self.v2_file, self.roster_file)]
        )
        self.assertFalse(self.legacy_file.exists())

    def test_unsealed_year_rejected(self):
        self.sidecar.append(YEAR, self.sample())
        with self.assertRaisesRegex(CareerV2AttributionConflict, "sealed"):
            self.audit.school_year(YEAR, self.a)

    def test_no_roster_and_no_implicit_creation(self):
        empty = self.root / "absent_rosters.sqlite3"
        with self.assertRaises(FileNotFoundError):
            CareerV2RosterAttribution(
                self.sidecar, empty,
            ).school_year(YEAR, self.a)
        self.assertFalse(empty.exists())

    def test_opposing_school_roster_required(self):
        partial = CareerRosterArchive(self.root / "partial.sqlite3")
        gen = PlayerRosterGenerator()
        partial.save_initial_roster(
            gen.generate_for_school_id(self.repo, self.a, YEAR, SEED)
        )
        self.append_and_seal([self.sample()])
        before = file_sha256(partial.db_path)
        with self.assertRaisesRegex(CareerV2AttributionConflict, "not saved"):
            CareerV2RosterAttribution(
                self.sidecar, partial,
            ).school_year(YEAR, self.a)
        self.assertEqual(before, file_sha256(partial.db_path))

    def test_unknown_player_and_wrong_school_fail_closed(self):
        unknown = self.sample()
        unknown["ability_detail"]["batter_stats"][0]["player_id"] = "PLYUNKNOWN"
        self.append_and_seal([unknown])
        with self.assertRaisesRegex(CareerV2AttributionConflict, "attribution"):
            self.audit.school_year(YEAR, self.a)

    def test_missing_box_stat_rejected_not_filled_as_zero(self):
        record = self.sample()
        del record["ability_detail"]["batter_stats"][0]["walks"]
        self.append_and_seal([record])
        with self.assertRaisesRegex(CareerV2AttributionConflict, "nonnegative"):
            self.audit.school_year(YEAR, self.a)

    def test_duplicate_same_player_per_game_rejected(self):
        record = self.sample()
        record["ability_detail"]["batter_stats"].append(
            dict(record["ability_detail"]["batter_stats"][0])
        )
        self.append_and_seal([record])
        with self.assertRaisesRegex(CareerV2AttributionConflict, "attribution"):
            self.audit.school_year(YEAR, self.a)

    def test_identity_table_tamper_rejected_without_write(self):
        self.append_and_seal([self.sample()])
        player_id = self.rosters.roster(YEAR, self.a).players[0].player_id
        with sqlite3.connect(self.roster_file) as con:
            con.execute(
                "UPDATE career_player_identities SET identity_sha256='BAD' "
                "WHERE player_id=?", (player_id,),
            )
        before = file_sha256(self.roster_file)
        with self.assertRaisesRegex(CareerV2AttributionConflict, "identity"):
            self.audit.school_year(YEAR, self.a)
        self.assertEqual(before, file_sha256(self.roster_file))

    def test_v2_payload_tamper_refused_by_parent_archive(self):
        self.append_and_seal([self.sample()])
        with sqlite3.connect(self.v2_file) as con:
            con.execute(
                "UPDATE v2_option_a_matches SET record_sha256='BAD' "
                "WHERE year=?", (YEAR,),
            )
        before = file_sha256(self.v2_file)
        with self.assertRaises(ValueError):
            self.audit.school_year(YEAR, self.a)
        self.assertEqual(before, file_sha256(self.v2_file))

    def test_invalid_year_school_and_db_collision(self):
        for year, sid in ((True, self.a), (0, self.a), (YEAR, "")):
            with self.assertRaises(ValueError):
                self.audit.school_year(year, sid)
        with self.assertRaisesRegex(ValueError, "separate"):
            CareerV2RosterAttribution(self.sidecar, self.v2_file)


if __name__ == "__main__":
    unittest.main()
