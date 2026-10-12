"""Stage43G-87: independent full-A oracle, source preservation and fail-closed."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_calendar_v2 import CareerCalendarV2Archive, explicit_sandbox_plan
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_option_a_storage_profile import _read_only
from phase2_engine.career_v2_national_storage_audit import (
    COMPETITIONS, SEED, _box_score, audit_fixture, run_national_storage_audit,
    survey_2026_master, synthetic_storage_fixture,
)
from phase2_engine.career_v2_school_century_shards import (
    build_v2_school_century_shards, read_v2_school_century_page,
)
import random

DATA = Path(__file__).resolve().parents[1] / "data"


class Stage43G87StorageTests(unittest.TestCase):
    def make_fixture(self, **kwargs):
        fixture = self.enterContext(synthetic_storage_fixture(DATA, schools=4, **kwargs))
        made = build_v2_school_century_shards(
            fixture.source, fixture.calendar,
            start_year=fixture.years[0], end_year=fixture.years[-1])
        return fixture, [Path(x["index_path"]) for x in made["shards"]]

    def read(self, fixture, indexes, **kwargs):
        return read_v2_school_century_page(
            fixture.source, fixture.calendar, indexes, fixture.schools[0],
            start_year=fixture.years[0], end_year=fixture.years[-1], **kwargs)

    def test_cross_century_first_last_pages_filters_zero_school_and_oracle(self):
        fixture, indexes = self.make_fixture(years=2, rounds=34, first_year=10099)
        report = audit_fixture(fixture, indexes, repeats=1)
        self.assertEqual(36, report["verified_page_calls"])
        self.assertTrue(report["source_calendar_legacy_indexes_sha_unchanged"])
        middle = self.read(fixture, indexes, offset=30)
        self.assertEqual(68, middle["total"])
        self.assertEqual([10099] * 4 + [10100] * 26, [r["year"] for r in middle["records"]])
        last = self.read(fixture, indexes, offset=60)
        self.assertEqual(8, len(last["records"]))
        self.assertEqual([r["match_id"] for r in fixture.expected[fixture.schools[0]][60:]],
                         [r["match_id"] for r in last["records"]])

    def test_seed_replays_full_payload_bytes_not_wall_clock(self):
        kwargs = dict(schools=4, years=2, rounds=2, repeats=1)
        a = run_national_storage_audit(DATA, **kwargs)
        b = run_national_storage_audit(DATA, **kwargs)
        c = run_national_storage_audit(DATA, seed=SEED + 1, **kwargs)
        self.assertEqual(a["full_a"], b["full_a"])
        self.assertNotEqual(a["full_a"]["content_sha256"], c["full_a"]["content_sha256"])
        self.assertEqual(8, a["full_a"]["matches"])
        self.assertEqual(16, a["indexed_memberships"])
        self.assertEqual(18 * 8, a["full_a"]["field_counts_and_bytes"]["batter_stats_rows"])
        self.assertIn("sacrifice_bunts", a["full_a"]["field_shapes"]["batter_stats"][0])
        self.assertIn("hit_batters", a["full_a"]["field_shapes"]["pitcher_stats"][0])
        self.assertEqual(a["full_a"]["payload_bytes"],
                         a["full_a"]["metadata_and_json_syntax_bytes"] + sum(
                             v for k, v in a["full_a"]["field_counts_and_bytes"].items() if k.endswith("_value_bytes")))
        self.assertTrue(a["temporary_fixture_deleted"])
        self.assertFalse(a["national_100_or_200_year_full_tournaments_verified"])
        self.assertFalse(a["game_save_year_limit_imposed"])
        self.assertTrue(any("school_id=?" in s for s in a["sql_plans"]["school_page"]))

    def test_all_mixed_schools_stats_match_their_original_payload(self):
        fixture, indexes = self.make_fixture(years=1, rounds=3)
        with closing(_read_only(fixture.source)) as db:
            for (raw,) in db.execute("SELECT payload_json FROM v2_option_a_matches"):
                row = json.loads(raw)
                teams = {row["team1_id"], row["team2_id"]}
                self.assertEqual(teams, {x["school_id"] for x in row["batter_stats"]})
                for sid, score in ((row["team1_id"], row["team1_score"]), (row["team2_id"], row["team2_score"])):
                    self.assertEqual(score, sum(x["runs"] for x in row["inning_scores"] if x["batting_team_id"] == sid))
                    own = [x for x in row["batter_stats"] if x["school_id"] == sid]
                    self.assertEqual(9, len(own))
                    self.assertTrue(all(sid in x["player_id"] for x in own))
                    self.assertEqual(score, sum(x["runs"] for x in own))
                    self.assertEqual(score, sum(x["hits"] for x in own))
                    self.assertEqual(27, sum(x["at_bats"] - x["hits"] for x in own))
                    arm = next(x for x in row["pitcher_stats"] if x["school_id"] != sid)
                    self.assertEqual(sum(x["plate_appearances"] for x in own), arm["batters_faced"])
                    self.assertEqual(score, arm["home_runs_allowed"])
        for sid in fixture.schools:
            page = read_v2_school_century_page(fixture.source, fixture.calendar, indexes, sid,
                start_year=fixture.years[0], end_year=fixture.years[-1], verify_scope="selected_years")
            self.assertEqual(3, page["total"])
            self.assertTrue(all(x["school_id"] == sid for x in page["records"]))

    def test_missing_shard_file_and_existing_index_overwrite_are_rejected(self):
        fixture, indexes = self.make_fixture(years=2, rounds=2, year_step=100)
        before = {p: file_sha256(p) for p in (fixture.source, fixture.calendar, fixture.legacy, *indexes)}
        with self.assertRaises(ValueError):
            self.read(fixture, indexes[:1], verify_scope="selected_years")
        missing = fixture.source.parent / "missing.sqlite3"
        with self.assertRaises(FileNotFoundError):
            self.read(fixture, [indexes[0], missing])
        self.assertFalse(missing.exists())
        with self.assertRaises(FileExistsError):
            build_v2_school_century_shards(fixture.source, fixture.calendar,
                start_year=fixture.years[0], end_year=fixture.years[-1])
        self.assertEqual(before, {p: file_sha256(p) for p in before})

    def test_stale_index_new_year_unsealed_then_sealed_both_rejected(self):
        fixture, indexes = self.make_fixture(years=1, rounds=2)
        next_year = fixture.years[-1] + 1
        CareerCalendarV2Archive(fixture.calendar).record(explicit_sandbox_plan(
            next_year, {COMPETITIONS[0]: ["04-01"]}, approved_for_fictional_game=True))
        fixture.archive.append(next_year, _box_score(next_year, "NEW87", COMPETITIONS[0],
            fixture.schools[0], fixture.schools[1], "04-01", random.Random(SEED)))
        for sealed in (False, True):
            if sealed:
                fixture.archive.seal_year(next_year, expected_match_count=1)
            before = file_sha256(fixture.source)
            with self.assertRaises(ValueError):
                read_v2_school_century_page(fixture.source, fixture.calendar, indexes, fixture.schools[0],
                    start_year=fixture.years[0], end_year=next_year, verify_scope="selected_years")
            self.assertEqual(before, file_sha256(fixture.source))

    def test_corrupt_sqlite_fails_without_changing_original_or_legacy(self):
        fixture, indexes = self.make_fixture(years=1, rounds=2)
        original = [file_sha256(p) for p in (fixture.source, fixture.calendar, fixture.legacy)]
        indexes[0].write_bytes(b"broken audit-only index")
        with self.assertRaises(sqlite3.DatabaseError):
            self.read(fixture, indexes)
        self.assertEqual(original, [file_sha256(p) for p in (fixture.source, fixture.calendar, fixture.legacy)])

    def test_hidden_other_school_source_checksum_detected_by_strict_zero_query(self):
        fixture, indexes = self.make_fixture(years=1, rounds=3)
        target = fixture.schools[0]
        with sqlite3.connect(fixture.source) as db:
            db.execute("UPDATE v2_option_a_matches SET payload_json='{}' WHERE match_id=("
                       "SELECT match_id FROM v2_option_a_matches WHERE json_extract(payload_json,'$.team1_id')!=? "
                       "AND json_extract(payload_json,'$.team2_id')!=? LIMIT 1)", (target, target))
        changed = file_sha256(fixture.source)
        with self.assertRaisesRegex(ValueError, "checksum"):
            read_v2_school_century_page(fixture.source, fixture.calendar, indexes, "AUDIT87-ZERO-SCHOOL",
                start_year=fixture.years[0], end_year=fixture.years[-1], verify_scope="selected_years")
        self.assertEqual(changed, file_sha256(fixture.source))

    def test_removed_or_foreign_membership_detected_on_strict_empty_query(self):
        for corrupt in ("delete", "foreign"):
            with self.subTest(corrupt=corrupt):
                fixture, indexes = self.make_fixture(years=1, rounds=2)
                with sqlite3.connect(indexes[0]) as db:
                    if corrupt == "delete":
                        db.execute("DELETE FROM school_game WHERE rowid=(SELECT MAX(rowid) FROM school_game)")
                    else:
                        db.execute("UPDATE school_game SET school_id='FOREIGN87' WHERE rowid=(SELECT MAX(rowid) FROM school_game)")
                before = file_sha256(indexes[0])
                with self.assertRaises(ValueError):
                    read_v2_school_century_page(fixture.source, fixture.calendar, indexes, "AUDIT87-ZERO-SCHOOL",
                        start_year=fixture.years[0], end_year=fixture.years[-1], verify_scope="selected_years")
                self.assertEqual(before, file_sha256(indexes[0]))

    def test_calendar_digest_tamper_is_rejected_without_repair(self):
        fixture, indexes = self.make_fixture(years=1, rounds=2)
        with sqlite3.connect(fixture.calendar) as db:
            db.execute("UPDATE sandbox_year_plans SET content_sha256='BAD87'")
        before = {p: file_sha256(p) for p in (fixture.source, fixture.calendar, fixture.legacy, *indexes)}
        with self.assertRaises(ValueError):
            self.read(fixture, indexes)
        self.assertEqual(before, {p: file_sha256(p) for p in before})

    def test_bounds_are_audit_budget_and_do_not_limit_game_year(self):
        for kwargs in ({"schools": True}, {"schools": 3}, {"years": 0}, {"rounds": 41},
                       {"repeats": 0}, {"seed": False}, {"year_step": 0},
                       {"first_year": 9999}, {"years": 33, "year_step": 100},
                       {"schools": 3746, "years": 200, "allow_large": True},
                       {"schools": 1000}, {"schools": 4000, "years": 1, "rounds": 1, "allow_large": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                run_national_storage_audit(DATA, **kwargs)
        report = run_national_storage_audit(DATA, schools=4, years=2, rounds=1,
                                          first_year=1000000, repeats=1)
        self.assertEqual([1000000, 1000001], report["saved_years"])
        self.assertFalse(report["game_save_year_limit_imposed"])

    def test_master_census_and_current_structural_game_counts_have_sources(self):
        report = survey_2026_master(DATA)
        self.assertEqual((3746, 3746, 47, 162),
                         tuple(report[k] for k in ("schools", "hardball_schools", "prefectures", "master_competitions")))
        self.assertEqual(162, report["structural_competition_runs"])
        self.assertEqual(report["structural_matches"], sum(x["matches"] for x in report["competition_counts"]))
        self.assertGreater(report["structural_matches"], 10000)
        self.assertIn("master/schools.csv", report["master_csv_sha256"])
        self.assertFalse(report["live_calendar_progression_verified"])
        self.assertFalse(report["actual_historical_results"])


if __name__ == "__main__":
    unittest.main()
