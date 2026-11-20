"""名簿づくりの並列化（game_core/roster_parallel.py）。架空の学校で確かめる。

子のプロセスの起こし方（spawn）はOSで違うので、windows-game-acceptance.yml でも流す。
"""
from __future__ import annotations

from datetime import date
import pickle
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from game_core import roster_parallel
from game_core.roster_book import RosterBook
from phase2_engine.career_state import CareerState
from phase2_engine.models import Team

TEAMS = {
    f"SCH-P{i}": Team(f"SCH-P{i}", f"PRG-P{i}", f"架空並列高校{i}", code)
    for i, code in enumerate(("13", "27", "47", "01", "23", "40"))
}


class _MarchEnd(SimpleNamespace):
    def play_today(self):
        return []


def _book(workers, school_ids=tuple(TEAMS)):
    book = RosterBook(TEAMS.__getitem__, first_year=2026, career_seed=11, school_ids=school_ids)
    book.parallel_workers = workers
    return book


def _content(book):
    return (
        {key: value for key, value in sorted(book._packed.items())},
        # 抑えた点のない選手は、読み込むと空か0の並びになる（どちらも同じ意味）
        {sid: {key: (bytes(s.values), s.growth_type, s.potential, s.velocity_potential, s.trait,
                     bytes(s.deferred) if any(s.deferred) else b"")
               for key, s in sorted(states.items())}
         for sid, states in sorted(book._states.items())},
        sorted(book.floor_hits.items()),
        book._prospect_pools,
    )


class ParallelRosterTests(unittest.TestCase):
    def test_parallel_build_matches_one_process_and_lazy_build(self):
        order = tuple(TEAMS)
        serial, parallel, lazy = _book(1), _book(None, order[::-1]), _book(1, order[::2] + order[1::2])
        with patch.object(roster_parallel, "settings",
                          return_value={**roster_parallel.settings(), "min_schools": 2, "max_workers": 2}), \
             patch("os.cpu_count", return_value=2):
            self.assertEqual(1, serial.build_rosters(2026))
            self.assertEqual(2, parallel.build_rosters(2026))
            for school_id in order[::-1]:
                lazy.roster(2026, school_id)
            self.assertEqual(_content(serial), _content(parallel))
            self.assertEqual(_content(serial), _content(lazy))
            self.assertEqual(2, parallel.build_rosters(2027))
        serial.build_rosters(2027)
        for school_id in order[1::2] + order[::2]:
            lazy.roster(2027, school_id)
        self.assertEqual(_content(serial), _content(parallel))
        self.assertEqual(_content(serial), _content(lazy))

    def test_pool_preserves_members_and_uses_the_old_supply_for_each_cohort(self):
        national, legacy = _book(1), _book(1, ())
        for year in (2026, 2027, 2028):
            with patch.object(national.ability_generator, "prospects", side_effect=AssertionError("local draw")):
                national.build_rosters(year)
            for sid in TEAMS:
                self.assertEqual(legacy.roster(year, sid), national.roster(year, sid))
            entries = (2024, 2025, 2026) if year == 2026 else (year,)
            for entry in entries:
                candidates = []
                supply = 0
                for sid in TEAMS:
                    players = [p for p in national.roster(year, sid).players if p.entry_year == entry]
                    assignments = national.prospect_assignments(entry, sid)
                    self.assertLessEqual(set(assignments), {p.roster_no for p in players})
                    profile = national.ability_generator.intake_model.profile(
                        school_id=sid, entry_year=entry, base_seed=national.career_seed,
                    )
                    supply += min(national.ability_generator.prospect_count(profile, national.career_seed), len(players))
                    candidates.extend(assignments.values())
                self.assertEqual(list(range(supply)), sorted(candidates))

    def test_partial_roster_save_restores_frozen_assignments_in_each_new_year(self):
        order = tuple(TEAMS)
        serial, lazy = _book(1), _book(1)
        for year in (2026, 2027, 2028):
            serial.build_rosters(year)
            lazy.roster(year, order[-1])
            self.assertEqual([order[-1]], lazy.schools(year))
            lazy = pickle.loads(pickle.dumps(lazy))
            lazy.bind(TEAMS.__getitem__)
            self.assertEqual([order[-1]], lazy.schools(year))
            with patch.object(lazy.ability_generator, "allocate_prospect_pool",
                              side_effect=AssertionError("repeated pool")):
                for school_id in order[-2::-1]:
                    lazy.roster(year, school_id)
            self.assertEqual(_content(serial), _content(lazy))
        survivor = lazy.roster(2028, order[0]).players[0]
        ability = lazy.ability(survivor)
        lazy.forget(2026)
        self.assertEqual({2025, 2026, 2027, 2028}, set(lazy._prospect_pools))
        lazy.forget(2027)
        self.assertEqual({2026, 2027, 2028}, set(lazy._prospect_pools))
        self.assertEqual(ability, lazy.ability(survivor))

    def test_career_crosses_april_the_same_after_saving_on_either_side(self):
        book = _book(1)
        book.build_rosters(2026)
        for year in (2027, 2028):
            last_day = date(year, 3, 31)
            book.set_today(last_day)
            season = _MarchEnd(current_date=last_day, start_date=date(year - 1, 4, 1),
                               calendar_rows={}, annual_templates={})
            career = CareerState({year - 1: season}, current_date=last_day, rosters=book)
            resumed = pickle.loads(pickle.dumps(career))
            resumed.rosters.bind(TEAMS.__getitem__)
            self.assertEqual(career.next_day(), resumed.next_day())
            self.assertEqual(date(year, 4, 1), resumed.current_date)
            self.assertEqual(_content(career.rosters), _content(resumed.rosters))
            after = pickle.loads(pickle.dumps(resumed))
            after.rosters.bind(TEAMS.__getitem__)
            with patch.object(after.rosters.ability_generator, "allocate_prospect_pool",
                              side_effect=AssertionError("repeated pool")):
                after.rosters.build_rosters(year)
            self.assertEqual(_content(career.rosters), _content(after.rosters))

    def test_saved_parallel_book_loads_and_continues_the_same(self):
        parallel = _book(2)
        parallel.build_rosters(2026)
        loaded = pickle.loads(pickle.dumps(parallel))
        loaded.bind(TEAMS.__getitem__)
        self.assertEqual(_content(parallel), _content(loaded))
        for book in (parallel, loaded):
            book.set_today(date(2026, 5, 1))
            book.grow(date(2026, 4, 30))
        self.assertEqual(_content(parallel), _content(loaded))

    def test_falls_back_to_one_process_when_processes_cannot_start(self):
        def broken(*args, **kwargs):
            raise OSError("no processes here")

        expected = _book(1)
        expected.build_rosters(2026)
        book = _book(2)
        with patch.object(roster_parallel, "ProcessPoolExecutor", broken):
            self.assertEqual(1, book.build_rosters(2026))
        self.assertEqual(_content(expected), _content(book))

    def test_worker_count_follows_cpus_and_the_config_limit(self):
        rule = roster_parallel.settings()
        self.assertEqual(1, roster_parallel.worker_count(rule["min_schools"] - 1))
        with patch("os.cpu_count", return_value=64):
            self.assertEqual(rule["max_workers"], roster_parallel.worker_count(5000))
        with patch("os.cpu_count", return_value=2):
            self.assertEqual(2, roster_parallel.worker_count(5000))
        self.assertEqual(3, roster_parallel.worker_count(3, requested=8))


if __name__ == "__main__":
    unittest.main()
