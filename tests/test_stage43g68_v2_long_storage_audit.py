"""Stage43G-68: up to 12 fictional v2 A years with independent sealed storage.

Only rosters genuinely advance annually through the normal save APIs.
Matches and approved logical calendars are SYNTHETIC test fixtures, not
gameplay tournament schedules or official winners. Legacy source stays apart.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_calendar_v2 import (
    CareerCalendarV2Archive, explicit_sandbox_plan,
)
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_long_storage_audit import (
    audit_saved_v2_storage, MAX_AUDIT_YEARS,
)
import test_stage43g31_cross_era_browse_model as stage31


class Stage43G68V2LongStorageAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage31.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.root = self.fixture.root

    def _hashes(self):
        return {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in sorted(self.root.glob("*.sqlite3*"))
            if p.is_file()
        }

    def _progress(self, final_year: int):
        """Advance only genuine per-school rosters, synthesize A match results."""
        calendar = CareerCalendarV2Archive(self.fixture.calendar)
        for year in range(10001, final_year + 1):
            for school in (self.fixture.a, self.fixture.b):
                self.fixture.rosters.advance_and_save(
                    self.fixture.repo.team(school),
                    next_year=year,
                    career_seed=stage31.SEED,
                )
            calendar.record(explicit_sandbox_plan(
                year, {stage31.COMP: ["04-01", "04-02"]},
                approved_for_fictional_game=True,
            ))
            for day in (1, 2):
                game = self.fixture.sample(
                    year, f"SYN-{year}-{day}",
                )
                # From year 10000 on the calendar is LOGICAL, never ISO.
                game.pop("match_date", None)
                game["completed_on"] = ""
                game["game_day_token"] = f"G{year}:04-{day:02d}"
                game["date_source"] = "fictional_v2_day_slot"
                self.fixture.future.append(year, game)
            self.fixture.future.seal_year(year, expected_match_count=2)
            for school in (self.fixture.a, self.fixture.b):
                self.fixture.cache.materialize(year, school)

    def test_twelve_v2_years_true_roster_progression_full_a_and_size(self):
        self._progress(10011)
        before = self._hashes()
        years = list(range(10000, 10012))
        result = audit_saved_v2_storage(self.root, years)
        self.assertEqual(years, result["selected_years"])
        self.assertEqual(12, result["selected_year_count"])
        self.assertEqual(12, len(result["year_rows"]))
        self.assertEqual(23, sum(x["match_count"] for x in result["year_rows"]))
        self.assertEqual(24, sum(
            x["v2_cached_school_count"] for x in result["year_rows"]
        ))
        self.assertTrue(all(
            x["school_roster_count"] == 2
            and x["v2_cached_school_count"] == 2
            and x["annual_logical_json_bytes"] > 0
            for x in result["year_rows"]
        ))
        self.assertTrue(all(
            x["source_sealed_and_calendar_sha_verified"]
            for x in result["year_rows"]
        ))
        self.assertEqual(
            sum(x["annual_logical_json_bytes"] for x in result["year_rows"]),
            result["selected_json_bytes_total"],
        )
        self.assertEqual(
            sum(r["file_bytes"] for r in result["sqlite_files"].values()),
            result["total_v2_roster_cache_calendar_sqlite_file_bytes"],
        )
        self.assertTrue(
            result["all_selected_years_original_match_and_cache_deep_verified"]
        )
        self.assertTrue(result["all_saved_files_sha256_unchanged"])
        self.assertFalse(result["complete_career_progression_to_10000_verified"])
        self.assertFalse(result["full_nation_or_official_tournament_results_verified"])
        self.assertEqual(before, self._hashes())

    def test_single_v2_year_does_not_access_or_edit_legacy_game(self):
        before = self._hashes()
        a = audit_saved_v2_storage(self.root, [10000])
        self.assertEqual([10000], a["selected_years"])
        self.assertEqual(1, a["year_rows"][0]["match_count"])
        self.assertEqual("G{year}:MM-DD", a["year_rows"][0]["logical_day_kind"])
        self.assertTrue(a["legacy_archive_unchanged_if_present"])
        self.assertTrue(a["original_legacy_stats_never_combined"])
        self.assertEqual(before, self._hashes())

    def test_corrupt_v2_match_fails_and_preserves_saved_files(self):
        with sqlite3.connect(self.fixture.v2) as db:
            db.execute(
                "UPDATE v2_option_a_matches SET record_sha256='BAD' "
                "WHERE year=10000",
            )
        before = self._hashes()
        with self.assertRaises(ValueError):
            audit_saved_v2_storage(self.root, [10000])
        self.assertEqual(before, self._hashes())

    def test_corrupt_v2_cache_row_fails_closed(self):
        with sqlite3.connect(self.fixture.cache.path) as db:
            db.execute(
                "UPDATE v2_player_year_stat_cache SET payload_sha256='BAD' "
                "WHERE year=10000 AND school_id=?", (self.fixture.a,),
            )
        before = self._hashes()
        with self.assertRaises(ValueError):
            audit_saved_v2_storage(self.root, [10000])
        self.assertEqual(before, self._hashes())

    def test_corrupt_calendar_provenance_fails_closed(self):
        with sqlite3.connect(self.fixture.calendar) as db:
            db.execute(
                "UPDATE sandbox_year_plans SET content_sha256='BAD' "
                "WHERE game_year=10000",
            )
        before = self._hashes()
        with self.assertRaises(ValueError):
            audit_saved_v2_storage(self.root, [10000])
        self.assertEqual(before, self._hashes())

    def test_missing_cache_or_unknown_year_never_creates_storage(self):
        with self.assertRaises(ValueError):
            audit_saved_v2_storage(self.root, [10001])
        self.fixture.cache.path.unlink()
        after = self._hashes()
        with self.assertRaises(FileNotFoundError):
            audit_saved_v2_storage(self.root, [10000])
        self.assertEqual(after, self._hashes())
        self.assertFalse(self.fixture.cache.path.exists())

    def test_bounded_year_selection_and_type_validation(self):
        for years in (
            [], [2026], [10000, 10000], [10001, 10000],
            [True], [10000.0], ["10000"],
            list(range(10000, 10000 + MAX_AUDIT_YEARS + 1)),
        ):
            with self.subTest(years=years):
                with self.assertRaises(ValueError):
                    audit_saved_v2_storage(self.root, years)
        self.assertTrue(self.fixture.old.is_file())
        self.assertFalse(
            (self.root / "career_player_stats_cache.sqlite3").exists()
        )


if __name__ == "__main__":
    unittest.main()
