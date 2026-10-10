"""Stage43G-26: legacy Option-A read compatibility with fictional v2 day slots."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from phase2_engine.career_calendar_v2 import (
    CareerCalendarV2Archive, SandboxCalendarConflict,
    explicit_sandbox_plan,
)
from phase2_engine.career_calendar_v2_read_model import (
    CareerCalendarV2MatchReadModel,
)
from phase2_engine.career_full_a_benchmark import run_full_a_benchmark
from phase2_engine.career_history_browse_model import CareerHistoryBrowseModel
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.historical_match_archive import HistoricalMatchArchive

DATA = Path(__file__).resolve().parents[1] / "data"
COMP = "CMP000086"


class Stage43G26CalendarReadCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.match_path = root / "historical_matches.sqlite3"
        self.calendar_path = root / "sandbox_calendar_v2.sqlite3"
        self.matches = HistoricalMatchArchive(self.match_path)
        self.calendar = CareerCalendarV2Archive(self.calendar_path)
        self.model = CareerCalendarV2MatchReadModel(
            self.calendar_path, self.match_path
        )
        self.calendar.record(explicit_sandbox_plan(
            2026, {COMP: ["04-01", "04-02"]},
            approved_for_fictional_game=True,
        ))
        self.matches.sync(
            year=2026, rng_seed=55,
            resolver_contract="read_fixture_v1",
            plan_fingerprint="stage43g26_fixture",
            completed=[
                self._fixture("MATCH-A", "2026-04-01"),
                self._fixture("MATCH-B", "2026-04-01"),
            ],
        )
        self.matches.seal_year(2026, expected_match_count=2)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _fixture(match_id: str, day: str) -> dict:
        return {
            "competition_id": COMP, "match_id": match_id,
            "match_date": day, "date_source": "test_synthetic",
            "status": "completed", "team1_id": "SCH-A",
            "team2_id": "SCH-B", "team1_score": 3,
            "team2_score": 2, "winner_id": "SCH-A",
            "loser_id": "SCH-B", "score_source": "fixture_only",
        }

    def test_year_days_and_paginated_date_matches_are_verified(self):
        before = (file_sha256(self.calendar_path),
                  file_sha256(self.match_path))
        year = self.model.year_dates(2026)
        self.assertEqual("fictional_calendar_year", year["screen"])
        self.assertEqual(2, year["archived_match_count"])
        self.assertEqual(
            ["G2026:04-01", "G2026:04-02"],
            [d["game_day_token"] for d in year["days"]],
        )
        self.assertEqual([2, 0], [
            d["archived_match_count"] for d in year["days"]
        ])
        first = self.model.date_page("G2026:04-01", limit=1)
        self.assertEqual(2, first["total"])
        self.assertEqual(["MATCH-A"], [
            item["match_id"] for item in first["rows"]
        ])
        second = self.model.date_page(
            "G2026:04-01", limit=1, offset=1,
            competition_id=COMP,
        )
        self.assertEqual(["MATCH-B"], [
            item["match_id"] for item in second["rows"]
        ])
        self.assertEqual(2, second["total"])
        self.assertEqual(0, self.model.date_page(
            "G2026:04-02"
        )["total"])
        self.assertFalse(year["official_schedule_inferred"])
        self.assertFalse(year["post_9999_gameplay_supported"])
        self.assertEqual(before, (
            file_sha256(self.calendar_path),
            file_sha256(self.match_path),
        ))

    def test_new_read_api_reachable_from_existing_history_browse_model(self):
        browse = CareerHistoryBrowseModel(DATA, self.tmp.name)
        a = browse.fictional_calendar_year(2026)
        b = browse.fictional_calendar_day(
            "G2026:04-01", competition_id=COMP
        )
        self.assertEqual(2, a["archived_match_count"])
        self.assertEqual(2, b["total"])
        self.assertEqual(
            {"MATCH-A", "MATCH-B"},
            {row["match_id"] for row in b["rows"]},
        )

    def test_unknown_calendar_day_and_bad_pagination_rejected(self):
        with self.assertRaisesRegex(
            SandboxCalendarConflict, "not in saved"
        ):
            self.model.date_page("G2026:04-03")
        with self.assertRaisesRegex(
            SandboxCalendarConflict, "not scheduled"
        ):
            self.model.date_page(
                "G2026:04-01", competition_id="CMP-OTHER"
            )
        for count, offset in ((0, 0), (101, 0), (10, -1),
                              (True, 0), (1, False)):
            with self.subTest(count=count, offset=offset):
                with self.assertRaises(ValueError):
                    self.model.date_page(
                        "G2026:04-01", limit=count, offset=offset
                    )
        with self.assertRaises(ValueError):
            self.model.date_page("2026-04-01")
        with self.assertRaises(SandboxCalendarConflict):
            self.model.year_dates(2027)

    def test_tampered_source_payload_digest_rejected_not_repaired(self):
        with sqlite3.connect(self.match_path) as con:
            con.execute(
                "UPDATE historical_matches SET record_sha256='WRONG' "
                "WHERE match_id='MATCH-B'"
            )
        before = file_sha256(self.match_path)
        with self.assertRaisesRegex(
            SandboxCalendarConflict, "checksum differs"
        ):
            self.model.date_page("G2026:04-01", limit=1)
        self.assertEqual(before, file_sha256(self.match_path))

    def test_source_row_payload_mismatch_and_unapproved_date_rejected(self):
        with sqlite3.connect(self.match_path) as con:
            con.execute(
                "UPDATE historical_matches SET match_date='2026-04-02' "
                "WHERE match_id='MATCH-B'"
            )
        with self.assertRaisesRegex(
            SandboxCalendarConflict, "identity differs"
        ):
            self.model.year_dates(2026)

    def test_saved_plan_digest_rejected(self):
        with sqlite3.connect(self.calendar_path) as con:
            con.execute(
                "UPDATE sandbox_year_plans SET content_sha256='CORRUPT'"
            )
        with self.assertRaisesRegex(
            SandboxCalendarConflict, "digest differs"
        ):
            self.model.year_dates(2026)

    def test_post_9999_is_plan_only_not_legacy_gameplay(self):
        self.calendar.record(explicit_sandbox_plan(
            10000, {COMP: ["02-29", "04-01"]},
            approved_for_fictional_game=True,
        ))
        view = self.model.year_dates(10000)
        self.assertEqual(0, view["archived_match_count"])
        self.assertEqual([None, None], [
            day["gregorian_iso_date"] for day in view["days"]
        ])
        self.assertIsNone(
            self.model.date_page("G10000:02-29")[
                "gregorian_iso_date"
            ]
        )
        self.assertFalse(view["post_9999_gameplay_supported"])
        with sqlite3.connect(self.match_path) as con:
            con.execute(
                "UPDATE historical_matches SET year=10000 "
                "WHERE match_id='MATCH-A'"
            )
        with self.assertRaisesRegex(
            SandboxCalendarConflict, "unsupported"
        ):
            self.model.year_dates(10000)

    def test_benchmark_full_a_five_year_browse_readonly(self):
        stats = run_full_a_benchmark(
            DATA, schools=2, years=5,
            games_per_school_year=3, repeats=1,
            include_sandbox_calendar=True,
        )
        result = stats["sandbox_calendar_v2"]
        self.assertTrue(result["strict_v2_read_model_verified"])
        self.assertEqual(15, result["v2_archived_matches_read"])
        self.assertEqual(10, result["v2_day_pages_checked"])
        self.assertTrue(stats["all_db_hashes_unchanged_on_read"])
        self.assertEqual(10, stats["counts"]["cached_school_years"])
        self.assertEqual(15, stats["counts"]["full_option_a_matches"])


if __name__ == "__main__":
    unittest.main()
