"""Stage43G-25: fictional calendar v2 day slots and 2/5-year E2E."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from phase2_engine.career_calendar_v2 import (
    CareerCalendarV2Archive, GameDaySlot, SandboxCalendarConflict,
    explicit_sandbox_plan, verify_sandbox_match_dates,
)
from phase2_engine.career_era_calendar_contract import MAX_SQLITE_YEAR
from phase2_engine.career_full_a_benchmark import run_full_a_benchmark
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.historical_match_archive import HistoricalMatchArchive, _SCHEMA

DATA = Path(__file__).resolve().parents[1] / "data"


class Stage43G25CalendarV2SandboxTests(unittest.TestCase):
    def test_day_slots_at_2026_2125_9999_10000_and_sort_order(self):
        dates = [
            GameDaySlot(10000, 1, 1), GameDaySlot(9999, 12, 31),
            GameDaySlot(2026, 6, 1), GameDaySlot(2026, 4, 2),
        ]
        ordered = sorted(dates)
        self.assertEqual(
            [d.token for d in ordered],
            ["G2026:04-02", "G2026:06-01", "G9999:12-31",
             "G10000:01-01"],
        )
        self.assertEqual("2026-04-02", ordered[0].iso_date)
        self.assertIsNone(ordered[-1].iso_date)
        self.assertEqual(92, ordered[0].day_of_year)
        self.assertEqual(
            GameDaySlot(10000, 1, 1),
            GameDaySlot.from_token("G10000:01-01"),
        )
        self.assertEqual(
            GameDaySlot(2125, 6, 1),
            GameDaySlot.from_iso("2125-06-01"),
        )
        self.assertEqual(366, GameDaySlot(10000, 12, 31).day_of_year)
        self.assertEqual(365, GameDaySlot(9999, 12, 31).day_of_year)

    def test_invalid_days_tokens_dates_and_sqlite_year_overflow(self):
        for year, month, day in (
            (2027, 2, 29), (2026, 0, 1), (2026, 13, 1),
            (2026, 1, 32), (10001, 2, 29),
            (MAX_SQLITE_YEAR + 1, 1, 1), (True, 1, 1),
            (2026, False, 1), (2026, 1, 0),
        ):
            with self.subTest(year=year, month=month, day=day):
                with self.assertRaises(ValueError):
                    GameDaySlot(year, month, day)
        for token in ("G0001:01-01", "G2026:2-01", "G2027:02-29",
                      "G0:01-01", "2026-01-01", "G2026:01-01tail"):
            with self.subTest(token=token):
                with self.assertRaises(ValueError):
                    GameDaySlot.from_token(token)
        for iso in ("10000-01-01", "2026-2-01", "2026-13-01",
                    "0000-01-01"):
            with self.subTest(iso=iso):
                with self.assertRaises(ValueError):
                    GameDaySlot.from_iso(iso)

    def test_explicit_policy_required_and_reference_is_not_reused(self):
        with self.assertRaises(SandboxCalendarConflict):
            explicit_sandbox_plan(2027, {"CMP000086": ["04-01"]})
        with self.assertRaises(SandboxCalendarConflict):
            explicit_sandbox_plan(
                2027, {"CMP000086": ["04-01"]},
                approved_for_fictional_game=True,
                policy_id="official_2027",
            )
        with self.assertRaises(ValueError):
            explicit_sandbox_plan(
                2027, {"UNLISTED": ["04-01"]},
                approved_for_fictional_game=True,
                allowed_competitions={"CMP000086"},
            )
        plan = explicit_sandbox_plan(
            2027,
            {"CMP000088": ["04-02"], "CMP000086": ["04-03", "04-01"]},
            approved_for_fictional_game=True,
        )
        self.assertEqual(
            ["G2027:04-01", "G2027:04-03"],
            plan["competition_days"]["CMP000086"],
        )
        self.assertFalse(plan["official_dates_proven"])
        with self.assertRaises(SandboxCalendarConflict):
            explicit_sandbox_plan(
                2027, {"CMP000086": ["04-01", "04-01"]},
                approved_for_fictional_game=True,
            )
        with self.assertRaises(ValueError):
            explicit_sandbox_plan(
                2027, {"CMP000086": ["02-29"]},
                approved_for_fictional_game=True,
            )

    def test_sqlite_plan_idempotent_immutable_and_readonly(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "sandbox.sqlite3"
            archive = CareerCalendarV2Archive(file)
            self.assertEqual([], archive.list_years())
            self.assertIsNone(archive.read(2026))
            self.assertFalse(file.exists())
            plan = explicit_sandbox_plan(
                2026, {"CMP000086": ["04-01", "04-03"]},
                approved_for_fictional_game=True,
            )
            first = archive.record(plan)
            self.assertTrue(first["inserted"])
            self.assertFalse(archive.record(plan)["inserted"])
            before = file_sha256(file)
            self.assertEqual(plan, archive.read(2026))
            self.assertEqual([2026], archive.list_years())
            self.assertEqual(before, file_sha256(file))
            changed = explicit_sandbox_plan(
                2026, {"CMP000086": ["04-02"]},
                approved_for_fictional_game=True,
            )
            with self.assertRaisesRegex(
                SandboxCalendarConflict, "immutable"
            ):
                archive.record(changed)
            self.assertEqual(before, file_sha256(file))
            with sqlite3.connect(file) as con:
                con.execute(
                    "UPDATE sandbox_year_plans SET content_sha256='BAD' "
                    "WHERE game_year=2026"
                )
            with self.assertRaisesRegex(
                SandboxCalendarConflict, "digest differs"
            ):
                archive.read(2026)

    def test_unapproved_and_forged_calendar_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = CareerCalendarV2Archive(
                Path(directory) / "unapproved.sqlite3"
            )
            plan = explicit_sandbox_plan(
                2026, {"CMP000086": ["04-01"]},
                approved_for_fictional_game=True,
            )
            plan["official_dates_proven"] = True
            with self.assertRaises(SandboxCalendarConflict):
                archive.record(plan)
            self.assertFalse(archive.path.exists())

    def test_2year_roster_a_cache_and_calendar_seal_e2e(self):
        result = run_full_a_benchmark(
            DATA, schools=2, years=2,
            games_per_school_year=2, repeats=1,
            include_sandbox_calendar=True,
        )
        v2 = result["sandbox_calendar_v2"]
        self.assertEqual([2026, 2027], v2["game_years"])
        self.assertEqual(4, v2["checked_archived_matches"])
        self.assertTrue(
            v2["all_match_dates_within_approved_sandbox_plans"]
        )
        self.assertTrue(result["all_db_hashes_unchanged_on_read"])
        self.assertTrue(result["temporary_fixture_deleted_after_run"])
        self.assertTrue(result["genuine_roster_identity_attribution"])
        self.assertEqual(4, result["counts"]["full_option_a_matches"])
        self.assertEqual(4, result["counts"]["cached_school_years"])
        self.assertFalse(result["real_game_tournament_progression_verified"])

    def test_5year_roster_a_cache_and_calendar_seal_e2e(self):
        result = run_full_a_benchmark(
            DATA, schools=2, years=5,
            games_per_school_year=3, repeats=1,
            include_sandbox_calendar=True,
        )
        v2 = result["sandbox_calendar_v2"]
        self.assertEqual([2026, 2027, 2028, 2029, 2030],
                         v2["game_years"])
        self.assertEqual(15, v2["checked_archived_matches"])
        self.assertEqual(10, result["counts"]["school_year_rosters"])
        self.assertEqual(10, result["counts"]["cached_school_years"])
        self.assertEqual(15, result["counts"]["full_option_a_matches"])
        self.assertGreater(
            result["counts"]["player_identities"], 40
        )
        self.assertTrue(all(
            item["cached_matches_raw"] for item in result["reads"]
        ))
        self.assertEqual(5, result["annual_growth"]["sealed_year_count"])

    def test_calendar_date_mismatch_fails_closed_and_never_repairs_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            match = root / "history.sqlite3"
            with closing(sqlite3.connect(match)) as con:
                con.executescript(_SCHEMA)
                con.execute(
                    "INSERT INTO historical_matches "
                    "(year,competition_id,match_id,match_date,date_source,"
                    "team1_id,team2_id,score_source,record_sha256,payload_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (2026, "CMP000086", "X", "2026-04-02", "synthetic",
                     "SCH-A", "SCH-B", "synthetic", "digest", "{}"),
                )
                con.commit()
            calendar = CareerCalendarV2Archive(root / "calendar.sqlite3")
            calendar.record(explicit_sandbox_plan(
                2026, {"CMP000086": ["04-01"]},
                approved_for_fictional_game=True,
            ))
            before = file_sha256(match)
            with self.assertRaisesRegex(
                SandboxCalendarConflict, "no approved fictional calendar slot"
            ):
                verify_sandbox_match_dates(calendar.path, match)
            self.assertEqual(before, file_sha256(match))

    def test_year_10000_token_persists_but_legacy_match_date_is_not_upgraded(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = CareerCalendarV2Archive(
                Path(directory) / "sandbox_10000.sqlite3"
            )
            plan = explicit_sandbox_plan(
                10000, {"CMP000086": ["02-29", "04-01"]},
                approved_for_fictional_game=True,
            )
            self.assertTrue(archive.record(plan)["inserted"])
            self.assertEqual(plan, archive.read(10000))
            self.assertIn("G10000:02-29",
                          plan["competition_days"]["CMP000086"])
            self.assertIsNone(GameDaySlot(10000, 2, 29).iso_date)


if __name__ == "__main__":
    unittest.main()
