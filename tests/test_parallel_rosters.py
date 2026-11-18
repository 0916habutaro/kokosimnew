"""名簿づくりの並列化（game_core/roster_parallel.py）。架空の学校で確かめる。

子のプロセスの起こし方（spawn）はOSで違うので、windows-game-acceptance.yml でも流す。
"""
from __future__ import annotations

from datetime import date
import pickle
import unittest
from unittest.mock import patch

from game_core import roster_parallel
from game_core.roster_book import RosterBook
from phase2_engine.models import Team

TEAMS = {
    f"SCH-P{i}": Team(f"SCH-P{i}", f"PRG-P{i}", f"架空並列高校{i}", code)
    for i, code in enumerate(("13", "27", "47", "01", "23", "40"))
}


def _book(workers):
    book = RosterBook(TEAMS.__getitem__, first_year=2026, career_seed=11, school_ids=tuple(TEAMS))
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
    )


class ParallelRosterTests(unittest.TestCase):
    def test_parallel_build_matches_one_process_and_lazy_build(self):
        serial, parallel, lazy = _book(1), _book(2), _book(1)
        self.assertEqual(1, serial.build_rosters(2026))
        self.assertEqual(2, parallel.build_rosters(2026))
        for school_id in reversed(tuple(TEAMS)):  # 1校ずつ、別の順で
            lazy.roster(2026, school_id)
        self.assertEqual(_content(serial), _content(parallel))
        self.assertEqual(_content(serial), _content(lazy))
        # 年度替わり（新入生・2・3年生の進級）も同じ
        self.assertEqual(2, parallel.build_rosters(2027))
        serial.build_rosters(2027)
        self.assertEqual(_content(serial), _content(parallel))

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

    def test_child_process_that_cannot_start_more_processes_falls_back_quietly(self):
        """種を並べて進める balance_report の子のプロセスなど、起動の途中で孫のプロセスを起こせない
        ときは、警告なしで1プロセス（ほかの理由では警告を出す）。"""
        import contextlib
        import io

        expected = _book(1)
        expected.build_rosters(2026)
        for message, warned in (("An attempt has been made to start a new process before the "
                                 "current process has finished its bootstrapping phase.", False),
                                ("something else", True)):
            def broken(*args, **kwargs):
                raise RuntimeError(message)

            book = _book(2)
            err = io.StringIO()
            with patch.object(roster_parallel, "ProcessPoolExecutor", broken), \
                    contextlib.redirect_stderr(err):
                self.assertEqual(1, book.build_rosters(2026))
            self.assertEqual(warned, "1プロセスに戻しました" in err.getvalue())
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
