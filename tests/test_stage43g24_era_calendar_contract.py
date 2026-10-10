"""Stage43G-24: preflight calendar / indefinite career-year design tests."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from phase2_engine.career_era_calendar_contract import (
    CAREER_START_YEAR, MAX_SQLITE_YEAR, CareerEraBoundaryConflict,
    calendar_day_preflight, career_coordinate, next_year_preflight,
)
from phase2_engine.historical_match_archive import (
    HistoricalMatchArchive, _SCHEMA,
)
from phase2_engine.career_history_scale_benchmark import file_sha256
from test_stage43g14_player_records import Stage43G14PlayerRecordTests


class Stage43G24EraCalendarContractTests(unittest.TestCase):
    def test_2026_50_100_era_coordinates(self):
        for year, elapsed in ((2026, 0), (2075, 49), (2125, 99),
                              (9999, 7973), (10000, 7974),
                              (1_000_000, 997974)):
            with self.subTest(year=year):
                row = career_coordinate(year)
                self.assertEqual(elapsed, row["career_year_index"])
                self.assertEqual(str(year), row["game_year_display"])
                self.assertFalse(row["official_schedule_inferred"])
                self.assertEqual(year <= 9999,
                                 row["gregorian_iso_year_supported"])

    def test_year_cohort_validation_rejects_bool_zero_and_sqlite_overflow(self):
        for year in (0, -1, True, "2027", MAX_SQLITE_YEAR + 1):
            with self.subTest(year=year):
                with self.assertRaises(ValueError):
                    career_coordinate(year)
        with self.assertRaises(ValueError):
            career_coordinate(2025, initial_year=2026)
        self.assertEqual(4, career_coordinate(
            2030, initial_year=2026
        )["career_year_index"])

    def test_calendar_date_is_a_candidate_not_synthetic_official_fixture(self):
        plan = calendar_day_preflight(2027, 5, 12)
        self.assertEqual("2027-05-12",
                         plan["gregorian_candidate_date"])
        self.assertEqual("G2027:05-12", plan["logical_day_token"])
        self.assertFalse(plan["is_game_schedule_approved"])
        self.assertFalse(plan["competition_dates_generated"])
        self.assertFalse(plan["master_season_calendar_recurrence_approved"])
        future = calendar_day_preflight(10000, 5, 12)
        self.assertIsNone(future["gregorian_candidate_date"])
        self.assertEqual("G10000:05-12", future["logical_day_token"])
        self.assertTrue(future["day_token_is_not_iso_date"])

    def test_leap_day_requires_year_specific_rule(self):
        feb29 = calendar_day_preflight(
            2028, 2, 29, template_year=2028
        )
        self.assertEqual("2028-02-29",
                         feb29["gregorian_candidate_date"])
        for year in (2027, 10000):
            with self.subTest(year=year):
                with self.assertRaises(CareerEraBoundaryConflict):
                    calendar_day_preflight(
                        year, 2, 29, template_year=2028
                    )
        with self.assertRaises(CareerEraBoundaryConflict):
            calendar_day_preflight(10000, 2, 30)
        with self.assertRaises(ValueError):
            calendar_day_preflight(2027, 13, 1, template_year=True)

    def _fixture(self):
        f = Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios"
        )
        f.setUp()
        return f

    def test_previous_active_year_fails_closed_then_seal_allows_only_archive(self):
        f = self._fixture()
        try:
            path = f.history.db_path
            before = file_sha256(path)
            status = next_year_preflight(path, requested_year=2028)
            self.assertEqual("blocked_unsealed_previous_year",
                             status["decision"])
            self.assertFalse(
                status["archive_year_registration_preflight_ok"]
            )
            self.assertFalse(status["runtime_season_start_authorized"])
            self.assertTrue(status["calendar_yyyy_supported"])
            self.assertEqual(before, file_sha256(path))
            f.history.seal_year(2027, expected_match_count=1)
            new_before = file_sha256(path)
            approved = next_year_preflight(path, requested_year=2028)
            self.assertTrue(
                approved["archive_year_registration_preflight_ok"]
            )
            self.assertEqual(
                "archive_only_requires_validated_new_season_plan",
                approved["decision"],
            )
            self.assertFalse(approved["runtime_season_start_authorized"])
            self.assertTrue(approved["previous_year_source_ledger_checked"])
            self.assertEqual(new_before, file_sha256(path))
            existing = next_year_preflight(path, requested_year=2026)
            self.assertEqual(
                "already_registered_or_past_year", existing["decision"]
            )
            skipped = next_year_preflight(path, requested_year=2029)
            self.assertEqual("blocked_nonadjacent_year",
                             skipped["decision"])
        finally:
            f.tearDown()

    def test_9999_to_10000_remains_calendar_blocked_even_if_archive_sealed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript(_SCHEMA)
                count, digest = HistoricalMatchArchive._ledger(conn, 9999)
                conn.execute(
                    "INSERT INTO career_years("
                    "year,metadata_json,status,match_count,ledger_sha256) "
                    "VALUES (?,?,'sealed',?,?)",
                    (9999, "{}", count, digest),
                )
                conn.commit()
            before = file_sha256(path)
            info = next_year_preflight(path, requested_year=10000)
            self.assertTrue(info["archive_year_registration_preflight_ok"])
            self.assertFalse(info["calendar_yyyy_supported"])
            self.assertFalse(info["runtime_season_start_authorized"])
            self.assertEqual(
                "archive_only_calendar_boundary_unresolved",
                info["decision"],
            )
            self.assertEqual(before, file_sha256(path))
            self.assertFalse(info["future_calendar_rule_verified"])

    def test_missing_corrupted_or_gapped_archive_never_auto_created(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "no_archive.sqlite3"
            with self.assertRaises(FileNotFoundError):
                next_year_preflight(db, requested_year=2027)
            self.assertFalse(db.exists())
            f = Path(d) / "broken.sqlite3"
            f.write_bytes(b"not SQLite")
            with self.assertRaises(CareerEraBoundaryConflict):
                next_year_preflight(f, requested_year=2027)
            path = Path(d) / "gapped.sqlite3"
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript(_SCHEMA)
                conn.executemany(
                    "INSERT INTO career_years(year,metadata_json,status)"
                    " VALUES (?,?,'active')",
                    [(2026, "{}"), (2028, "{}")],
                )
                conn.commit()
            with self.assertRaisesRegex(
                CareerEraBoundaryConflict, "nonadjacent"
            ):
                next_year_preflight(path, requested_year=2029)

    def test_sealed_ledger_modified_preflight_rejects(self):
        f = self._fixture()
        try:
            f.history.seal_year(2027, expected_match_count=1)
            with sqlite3.connect(f.history.db_path) as conn:
                conn.execute(
                    "UPDATE career_years SET ledger_sha256='TAMPERED'"
                    " WHERE year=2027"
                )
            with self.assertRaisesRegex(
                CareerEraBoundaryConflict, "ledger changed"
            ):
                next_year_preflight(
                    f.history.db_path, requested_year=2028
                )
        finally:
            f.tearDown()


if __name__ == "__main__":
    unittest.main()
