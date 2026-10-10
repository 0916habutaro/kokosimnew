from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from game_core.career_rosters import advance_school_roster, advance_rosters
from game_core.players import (
    GRADE_COUNTS, PlayerRosterGenerator, validate_school_roster, write_players_csv
)
from phase2_engine.career_roster_archive import (
    CareerRosterArchive, CareerRosterConflictError
)
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]


class Stage43ECareerRostersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.school_ids = sorted(cls.repo.school_to_program)[:2]
        cls.seed = 2026100701
        cls.generator = PlayerRosterGenerator()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.archive = CareerRosterArchive(
            Path(self.tmp.name) / "career_rosters.sqlite3"
        )
        self.school = self.school_ids[0]
        self.team = self.repo.team(self.school)
        self.initial = self.generator.generate_school(
            self.team, 2026, self.seed
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _step(self, previous, year):
        return advance_school_roster(
            previous, self.team, next_year=year,
            career_seed=self.seed, generator=self.generator,
        )

    def test_2026_bootstrap_is_unchanged(self):
        self.assertEqual("initial_v1", self.initial.cohort_policy)
        self.assertNotIn("cohort_policy", self.initial.to_dict())
        self.assertEqual(GRADE_COUNTS, {
            grade: sum(p.academic_year == grade for p in self.initial.players)
            for grade in (1, 2, 3)
        })
        second = self.generator.generate_school(self.team, 2026, self.seed)
        self.assertEqual(self.initial.to_dict(), second.to_dict())

    def test_yearly_progression_and_three_year_graduation(self):
        p26 = {p.player_id: p for p in self.initial.players}
        s27 = self._step(self.initial, 2027)
        self.assertEqual({1: 8, 2: 5, 3: 7}, s27.summary()["cohort_counts"])
        self.assertEqual(8, len(s27.graduated))
        self.assertEqual(12, len(s27.returning))
        self.assertEqual(8, len(s27.newcomers))
        s28 = self._step(s27.roster, 2028)
        self.assertEqual({1: 7, 2: 8, 3: 5}, s28.summary()["cohort_counts"])
        self.assertEqual(7, len(s28.graduated))
        s29 = self._step(s28.roster, 2029)
        self.assertEqual({1: 5, 2: 7, 3: 8}, s29.summary()["cohort_counts"])
        self.assertEqual(5, len(s29.graduated))
        initial_grade1_ids = {
            pid for pid, p in p26.items() if p.academic_year == 1
        }
        for year, roster in [(2027, s27.roster), (2028, s28.roster)]:
            returned = {
                p.player_id: p for p in roster.players
                if p.player_id in initial_grade1_ids
            }
            self.assertEqual(initial_grade1_ids, set(returned))
            for pid, p in returned.items():
                self.assertEqual(p26[pid].entry_year, p.entry_year)
                self.assertEqual(p26[pid].display_name, p.display_name)
                self.assertEqual(p26[pid].primary_position, p.primary_position)
                self.assertEqual(p26[pid].bats, p.bats)
                self.assertEqual(p26[pid].roster_no, p.roster_no)
                self.assertEqual(year - 2025, p.academic_year)
        self.assertFalse(
            initial_grade1_ids & {p.player_id for p in s29.roster.players}
        )

    def test_immutable_roster_numbers_and_positions_each_year(self):
        initial_slots = {p.roster_no: p.primary_position for p in self.initial.players}
        current = self.initial
        all_ids = {p.player_id for p in current.players}
        for year in range(2027, 2037):
            result = self._step(current, year)
            current = result.roster
            validate_school_roster(current)
            self.assertEqual(20, len(current.players))
            self.assertEqual(
                initial_slots,
                {p.roster_no: p.primary_position for p in current.players},
            )
            ids = {p.player_id for p in result.newcomers}
            self.assertFalse(ids & all_ids)
            all_ids.update(ids)

    def test_repeatable_seed_and_order_independent_of_other_schools(self):
        first = self._step(self.initial, 2027).roster.to_dict()
        second = self._step(self.initial, 2027).roster.to_dict()
        self.assertEqual(first, second)
        other_team = self.repo.team(self.school_ids[1])
        other = self.generator.generate_school(other_team, 2026, self.seed)
        other_result = advance_school_roster(
            other, other_team, next_year=2027, career_seed=self.seed
        )
        self.assertEqual(20, len(other_result.roster.players))
        self.assertFalse(
            {p.player_id for p in other_result.roster.players} &
            {p.player_id for p in first_players(first)}
        )

    def test_unsupported_year_jump_seed_or_school_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "adjacent"):
            self._step(self.initial, 2028)
        with self.assertRaisesRegex(ValueError, "seed differs"):
            advance_school_roster(
                self.initial, self.team, next_year=2027,
                career_seed=self.seed + 1
            )
        with self.assertRaisesRegex(ValueError, "team identity"):
            self._step_with_other_team()

    def _step_with_other_team(self):
        return advance_school_roster(
            self.initial, self.repo.team(self.school_ids[1]),
            next_year=2027, career_seed=self.seed,
        )

    def test_original_roster_is_not_mutated(self):
        original = self.initial.to_dict()
        result = self._step(self.initial, 2027)
        self.assertEqual(original, self.initial.to_dict())
        self.assertEqual("career_v1", result.roster.cohort_policy)
        self.assertEqual("career_v1", result.roster.to_dict()["cohort_policy"])

    def test_career_roster_csv_accepts_yearly_cohort_distribution(self):
        result = self._step(self.initial, 2027)
        dest = Path(self.tmp.name) / "players.csv"
        written = write_players_csv([result.roster], dest)
        self.assertEqual(20, written["player_count"])

    def test_streaming_many_schools_only_advances_received_rosters(self):
        inputs = (
            self.generator.generate_for_school_id(
                self.repo, school_id, 2026, self.seed
            )
            for school_id in self.school_ids
        )
        rows = list(advance_rosters(
            inputs, self.repo, next_year=2027, career_seed=self.seed,
        ))
        self.assertEqual(self.school_ids, [r.school_id for r in rows])

    def test_archive_roundtrip_and_player_memberships(self):
        first = self.archive.save_initial_roster(self.initial)
        self.assertTrue(first["inserted"])
        self.assertFalse(self.archive.save_initial_roster(self.initial)["inserted"])
        first_id = next(
            p.player_id for p in self.initial.players if p.academic_year == 1
        )
        for year in (2027, 2028, 2029):
            result = self.archive.advance_and_save(
                self.team, next_year=year, career_seed=self.seed,
            )
            self.assertTrue(result["inserted"])
        self.assertEqual(
            [2026, 2027, 2028, 2029],
            self.archive.school_years(self.school),
        )
        history = self.archive.player_history(first_id)
        self.assertEqual([2026, 2027, 2028], [r["year"] for r in history])
        self.assertEqual([1, 2, 3], [r["academic_year"] for r in history])
        self.assertEqual(self.initial.to_dict(),
                         self.archive.roster(2026, self.school).to_dict())
        self.assertEqual("career_v1",
                         self.archive.roster(2029, self.school).cohort_policy)

    def test_archive_repeated_year_is_idempotent(self):
        self.archive.save_initial_roster(self.initial)
        first = self.archive.advance_and_save(
            self.team, next_year=2027, career_seed=self.seed,
        )
        duplicate = self.archive.advance_and_save(
            self.team, next_year=2027, career_seed=self.seed,
        )
        self.assertTrue(first["inserted"])
        self.assertFalse(duplicate["inserted"])

    def test_archive_rejects_invalid_year_or_changed_newcomer_name(self):
        self.archive.save_initial_roster(self.initial)
        with self.assertRaisesRegex(CareerRosterConflictError, "missing previous"):
            self.archive.advance_and_save(
                self.team, next_year=2028, career_seed=self.seed
            )
        self.archive.advance_and_save(
            self.team, next_year=2027, career_seed=self.seed
        )
        def changed_name_provider(team, year, roster_no, rng):
            return f"別名{roster_no}", "changed_test"
        with self.assertRaises(CareerRosterConflictError):
            self.archive.advance_and_save(
                self.team, next_year=2027, career_seed=self.seed,
                generator=PlayerRosterGenerator(
                    name_provider=changed_name_provider
                )
            )
        self.assertEqual(2, len(self.archive.school_years(self.school)))

    def test_archive_detects_altered_fingerprint(self):
        self.archive.save_initial_roster(self.initial)
        with sqlite3.connect(self.archive.db_path) as conn:
            conn.execute(
                "UPDATE career_school_rosters SET payload_json='{}'"
            )
        with self.assertRaisesRegex(CareerRosterConflictError, "digest"):
            self.archive.roster(2026, self.school)

    def test_cross_year_identity_fingerprint_conflict_is_atomic(self):
        self.archive.save_initial_roster(self.initial)
        original = self._step(self.initial, 2027).roster
        prior_ids = {p.player_id for p in self.initial.players}
        returning = next(
            p for p in original.players if p.player_id in prior_ids
        )
        corrupt = replace(returning, display_name="偽の名前")
        broken = replace(
            original,
            players=[corrupt if p.player_id == returning.player_id else p
                     for p in original.players],
        )
        with sqlite3.connect(self.archive.db_path) as conn:
            # Simulate a damaged pre-existing identity reference.
            conn.execute(
                "UPDATE career_player_identities SET identity_sha256='bad' "
                "WHERE player_id=?", (corrupt.player_id,),
            )
        with self.assertRaises(CareerRosterConflictError):
            with self.archive._connect() as conn:
                conn.executescript(
                    "CREATE TABLE IF NOT EXISTS _noop(x INTEGER);"
                )
                with conn:
                    self.archive._insert(conn, broken)
        self.assertIsNone(self.archive.roster(2027, self.school))

    def test_unavailable_db_queries_do_not_create_file(self):
        self.assertIsNone(self.archive.roster(2026, self.school))
        self.assertEqual([], self.archive.school_years(self.school))
        self.assertEqual([], self.archive.player_history("any"))
        self.assertFalse(self.archive.db_path.exists())


def first_players(as_dict):
    from game_core.players import Player
    return [Player(**r) for r in as_dict["players"]]


if __name__ == "__main__":
    unittest.main()
