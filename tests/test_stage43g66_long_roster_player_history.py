"""Stage43G-66: archived school/player read performance over long histories.

Tests mix valid 100-year roster progression for ONE school and index-only
metadata for up to 3000 synthetic schools × 50 years. The latter rows are
deliberately not treated as valid rosters or real gameplay records.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_long_roster_player_probe import (
    probe_roster_player_history,
)
from phase2_engine.career_roster_archive import (
    CareerRosterArchive, CareerRosterConflictError,
)
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]


class Stage43G66LongRosterPlayerHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.school_id = sorted(cls.repo.school_to_program)[0]
        cls.team = cls.repo.team(cls.school_id)
        cls.generator = PlayerRosterGenerator()
        cls.seed = 2026101201

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "career_rosters.sqlite3"
        self.archive = CareerRosterArchive(self.file)
        self.initial = self.generator.generate_school(
            self.team, 2026, self.seed,
        )
        self.archive.save_initial_roster(self.initial)

    def _hash(self):
        return sha256(self.file.read_bytes()).hexdigest()

    def _progress(self, final):
        for year in range(2027, final + 1):
            self.archive.advance_and_save(
                self.team, next_year=year, career_seed=self.seed,
            )

    def test_grade_1_2_3_yearly_membership_stays_correct(self):
        self._progress(2030)
        before = self._hash()
        for grade in (1, 2, 3):
            player = next(p for p in self.initial.players
                          if p.academic_year == grade)
            years = [x["year"] for x in
                     self.archive.player_history(player.player_id)]
            self.assertEqual(
                [2026 + i for i in range(4 - grade)], years,
            )
            self.assertEqual([grade + i for i in range(4 - grade)], [
                x["academic_year"] for x in
                self.archive.player_history(player.player_id)
            ])
        self.assertEqual(before, self._hash())

    def test_long_school_100_actual_generated_rosters_index_bounded(self):
        self._progress(2125)
        player = next(p for p in self.initial.players
                      if p.academic_year == 1)
        before = self._hash()
        years = self.archive.player_history(player.player_id)
        self.assertEqual([2026, 2027, 2028],
                         [x["year"] for x in years])
        self.assertEqual([1, 2, 3],
                         [x["academic_year"] for x in years])
        with sqlite3.connect(self.file) as db:
            self.assertEqual(100, db.execute(
                "SELECT COUNT(*) FROM career_school_rosters "
                "WHERE school_id=?", (self.school_id,),
            ).fetchone()[0])
        report = probe_roster_player_history(
            self.file, player.player_id, repeats=3,
        )
        self.assertEqual(100, report["total_saved_school_year_rows"])
        self.assertEqual(1, report["distinct_saved_school_ids"])
        self.assertEqual(3, report["verified_membership_snapshots"])
        self.assertEqual(3, report["bounded_grade_window_years"])
        self.assertTrue(report["source_sha256_unchanged"])
        self.assertFalse(report["verified_all_schools_or_years"])
        self.assertEqual(before, self._hash())

    def test_3000_school_50_year_index_metadata_does_not_force_player_scan(self):
        self._progress(2028)
        player = next(p for p in self.initial.players
                      if p.academic_year == 1)
        # Only index-shape metadata for unrelated schools; payloads are
        # intentionally invalid and MUST NEVER be rendered as real rosters.
        with sqlite3.connect(self.file) as db:
            db.executemany(
                "INSERT INTO career_school_rosters "
                "(year,school_id,content_sha256,payload_json) "
                "VALUES (?,?,?,?)",
                ((year, f"INDEX-ONLY-{school:04d}",
                  "NOT_A_REAL_ROSTER_SHA", "{}")
                 for year in range(2026, 2076)
                 for school in range(1, 3001)),
            )
        before = self._hash()
        report = probe_roster_player_history(
            self.file, player.player_id, repeats=2,
        )
        self.assertEqual(150003, report["total_saved_school_year_rows"])
        self.assertEqual(3001, report["distinct_saved_school_ids"])
        self.assertEqual([2026, 2027, 2028],
                         report["player_membership_years"])
        self.assertEqual(3, report["verified_membership_snapshots"])
        self.assertTrue(any(
            "idx_career_rosters_school_year" in x
            for x in report["query_plan"]
        ))
        self.assertEqual(before, self._hash())

    def test_known_permanent_identity_checksum_mismatch_fails_closed(self):
        target = self.initial.players[0].player_id
        with sqlite3.connect(self.file) as db:
            db.execute(
                "UPDATE career_player_identities SET identity_sha256='BAD' "
                "WHERE player_id=?", (target,),
            )
        before = self._hash()
        with self.assertRaisesRegex(
            CareerRosterConflictError, "identity digest",
        ):
            self.archive.player_history(target)
        self.assertEqual(before, self._hash())

    def test_future_unrelated_roster_not_scanned_but_member_roster_checked(self):
        self._progress(2030)
        target = next(p.player_id for p in self.initial.players
                      if p.academic_year == 3)
        with sqlite3.connect(self.file) as db:
            db.execute(
                "UPDATE career_school_rosters SET content_sha256='BAD' "
                "WHERE year=2030 AND school_id=?", (self.school_id,),
            )
        before = self._hash()
        self.assertEqual([2026], [
            x["year"] for x in self.archive.player_history(target)
        ])
        with sqlite3.connect(self.file) as db:
            db.execute(
                "UPDATE career_school_rosters SET content_sha256='BAD' "
                "WHERE year=2026 AND school_id=?", (self.school_id,),
            )
        altered = self._hash()
        with self.assertRaisesRegex(
            CareerRosterConflictError, "digest",
        ):
            self.archive.player_history(target)
        self.assertNotEqual(before, altered)
        self.assertEqual(altered, self._hash())

    def test_absent_player_and_read_only_empty_archive_no_creation(self):
        before = self._hash()
        self.assertEqual([], self.archive.player_history("UNSAVED_PLAYER"))
        self.assertEqual(before, self._hash())
        never_created = self.file.with_name("missing_rosters.sqlite3")
        other = CareerRosterArchive(never_created)
        self.assertEqual([], other.player_history("UNSAVED_PLAYER"))
        self.assertFalse(never_created.exists())
        for wrong in (True, "", 7, None):
            with self.assertRaises(ValueError):
                self.archive.player_history(wrong)


if __name__ == "__main__":
    unittest.main()
