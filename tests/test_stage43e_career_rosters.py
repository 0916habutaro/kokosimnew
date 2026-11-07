from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest

from game_core.career_rosters import advance_school_roster, advance_rosters
from game_core.tournament_bridge import AbilityMatchResolver
from game_core.player_names import PlayerIdentity
from game_core.players import (
    PlayerRosterGenerator, validate_school_roster, write_players_csv
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
        second = self.generator.generate_school(self.team, 2026, self.seed)
        self.assertEqual(self.initial.to_dict(), second.to_dict())

    def test_yearly_progression_and_three_year_graduation(self):
        p26 = {p.player_id: p for p in self.initial.players}
        current = self.initial
        initial_grade1_ids = {
            pid for pid, p in p26.items() if p.academic_year == 1
        }
        kept = set(initial_grade1_ids)
        for year in (2027, 2028, 2029):
            step = self._step(current, year)
            before = current.players
            # 3年生は全員卒業、1・2年生は退部した選手を除いて進級する
            self.assertEqual({p.player_id for p in before if p.academic_year == 3},
                             {p.player_id for p in step.graduated})
            self.assertEqual({p.player_id for p in before if p.academic_year < 3},
                             {p.player_id for p in step.returning}
                             | {p.player_id for p in step.withdrawn})
            self.assertEqual(len(step.returning) + len(step.newcomers), len(step.roster.players))
            self.assertTrue(all(p.academic_year == 1 for p in step.newcomers))
            kept -= {p.player_id for p in step.withdrawn}
            current = step.roster
            returned = {p.player_id: p for p in current.players if p.player_id in initial_grade1_ids}
            if year < 2029:
                self.assertEqual(kept, set(returned))
            for pid, p in returned.items():
                self.assertEqual(p26[pid].entry_year, p.entry_year)
                self.assertEqual(p26[pid].display_name, p.display_name)
                self.assertEqual(p26[pid].primary_position, p.primary_position)
                self.assertEqual(p26[pid].bats, p.bats)
                self.assertEqual(p26[pid].roster_no, p.roster_no)
                self.assertEqual(year - 2025, p.academic_year)
        self.assertFalse(initial_grade1_ids & {p.player_id for p in current.players})

    def test_roster_numbers_stay_unique_and_new_team_meets_minimum(self):
        current = self.initial
        all_ids = {p.player_id for p in current.players}
        for year in range(2027, 2037):
            result = self._step(current, year)
            numbers = {p.player_id: p.roster_no for p in result.returning}
            current = result.roster
            validate_school_roster(current)
            # 進級した選手は番号・守備位置を変えない
            for p in current.players:
                if p.player_id in numbers:
                    self.assertEqual(numbers[p.player_id], p.roster_no)
            new_team = [p for p in current.players if p.academic_year <= 2]
            self.assertGreaterEqual(len(new_team), 10)
            self.assertGreaterEqual(sum(p.primary_position == "P" for p in new_team), 2)
            self.assertGreaterEqual(sum(p.primary_position == "C" for p in new_team), 1)
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
        self.assertGreaterEqual(len(other_result.roster.players), 10)
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
        self.assertEqual(len(result.roster.players), written["player_count"])

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
        for year in (2027, 2028, 2029):
            result = self.archive.advance_and_save(
                self.team, next_year=year, career_seed=self.seed,
            )
            self.assertTrue(result["inserted"])
        # 退部しなかった1年生
        stayed = {p.player_id for p in self.archive.roster(2028, self.school).players}
        first_id = next(
            p.player_id for p in self.initial.players
            if p.academic_year == 1 and p.player_id in stayed
        )
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
        def changed_name_provider(team, base_seed, rng, taken):
            return PlayerIdentity(
                f"別名{len(taken)}", "changed_test", team.prefecture_code,
            )
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
        with closing(sqlite3.connect(self.archive.db_path)) as conn, conn:
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
        with closing(sqlite3.connect(self.archive.db_path)) as conn, conn:
            # Simulate a damaged pre-existing identity reference.
            conn.execute(
                "UPDATE career_player_identities SET identity_sha256='bad' "
                "WHERE player_id=?", (corrupt.player_id,),
            )
        with self.assertRaises(CareerRosterConflictError):
            with closing(self.archive._connect()) as conn:
                conn.executescript(
                    "CREATE TABLE IF NOT EXISTS _noop(x INTEGER);"
                )
                with conn:
                    self.archive._insert(conn, broken)
        self.assertIsNone(self.archive.roster(2027, self.school))

    def test_ability_resolver_uses_stable_id_roster_provider(self):
        self.archive.save_initial_roster(self.initial)
        self.archive.advance_and_save(
            self.team, next_year=2027, career_seed=self.seed,
        )
        resolver = AbilityMatchResolver(
            self.repo,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
            roster_provider=self.archive.roster,
        )
        old_ids = {
            p.player_id for p in self.initial.players
            if p.academic_year in (1, 2)
        }
        ability_team = resolver.team_input(
            school_id=self.school,
            reference_year=2027,
            generation_seed=self.seed,
        )
        current_ids = {p.player_id for p in ability_team.player_abilities}
        saved = self.archive.roster(2027, self.school)
        self.assertEqual({p.player_id for p in saved.players}, current_ids)
        self.assertTrue(old_ids >= {
                p.player_id for p in saved.players if p.academic_year in (2, 3)})
        self.assertEqual(
            old_ids & current_ids, {
                p.player_id for p in self.archive.roster(2027, self.school).players
                if p.academic_year in (2, 3)
            }
        )

    def test_ability_resolver_does_not_regenerate_missing_year(self):
        self.archive.save_initial_roster(self.initial)
        resolver = AbilityMatchResolver(
            self.repo, roster_provider=self.archive.roster,
        )
        with self.assertRaisesRegex(ValueError, "missing historical roster"):
            resolver.team_input(
                school_id=self.school,
                reference_year=2027,
                generation_seed=self.seed,
            )

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
