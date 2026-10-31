"""Stage92: real legacy writer transactions on isolated WAL/DELETE databases."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
from time import perf_counter
import unittest
from unittest.mock import patch

from phase2_engine.historical_match_archive import (
    BUSY_TIMEOUT_SECONDS, HistoricalMatchArchive, HistoricalMatchConflictError, _SCHEMA,
)
from stage43g92_fixture_support import (SEAL_READ, REGISTER_READ, digest,
                                        oracle, ordered_pair, snapshot)
from test_stage43c_live_history_archive import make_record

MODES = ('DELETE', 'WAL')


def sync(archive, rows, *, year=2026, seed=42, plan=None):
    return archive.sync(year=year, rng_seed=seed, resolver_contract='fixture92',
                        plan_fingerprint=plan or 'plan92-' + str(year), completed=rows)


def register(archive, *, year=2027, seed=42, plan=None):
    return archive.register_next_year(year=year, rng_seed=seed,
        resolver_contract='fixture92', plan_fingerprint=plan or 'plan92-' + str(year))


class Stage43G92LegacyConcurrencyTests(unittest.TestCase):
    def fixture(self, mode, *, empty=False):
        temp = self.enterContext(tempfile.TemporaryDirectory(prefix='stage92-only-'))
        archive = HistoricalMatchArchive(Path(temp) / 'history.sqlite3')
        with closing(sqlite3.connect(archive.db_path)) as con:
            self.assertEqual(mode.lower(), con.execute('PRAGMA journal_mode=' + mode).fetchone()[0])
            con.executescript(_SCHEMA)
        if not empty:
            sync(archive, [make_record()])
        return archive

    def conflict(self, errors, role='second'):
        self.assertEqual({role}, set(errors))
        self.assertIsInstance(errors[role], HistoricalMatchConflictError)

    def test_sync_first_stale_count_refuses_then_exact_count_seals(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                results, errors = ordered_pair(self, a,
                    lambda a: sync(a, [make_record(), make_record('M2')]),
                    lambda a: a.seal_year(2026, expected_match_count=1))
                self.conflict(errors)
                self.assertEqual(1, results['first']['inserted'])
                rows, years = oracle(self, a)
                self.assertEqual(2, len(rows))
                self.assertEqual('active', years[0][1])
                a.seal_year(2026, expected_match_count=2)
                oracle(self, a)

    def test_sync_first_correct_count_seals_both_succeed(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                results, errors = ordered_pair(self, a,
                    lambda a: sync(a, [make_record('M2')]),
                    lambda a: a.seal_year(2026, expected_match_count=2))
                self.assertEqual({}, errors)
                self.assertEqual(2, results['second']['match_count'])
                self.assertEqual(2, len(oracle(self, a)[0]))

    def test_seal_first_new_match_refuses_and_full_a_is_immutable(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                old = oracle(self, a)[0]
                results, errors = ordered_pair(self, a,
                    lambda a: a.seal_year(2026, expected_match_count=1),
                    lambda a: sync(a, [make_record(), make_record('M2')]), SEAL_READ)
                self.conflict(errors)
                self.assertEqual(1, results['first']['match_count'])
                self.assertEqual(old, oracle(self, a)[0])
                before = snapshot(a), digest(a.db_path.read_bytes().hex())
                self.assertEqual({'inserted': 0, 'already_archived': 1}, sync(a, [make_record()]))
                self.assertEqual(before, (snapshot(a), digest(a.db_path.read_bytes().hex())))
                payload = a.get_match(2026, 'CMP-1', 'M1')
                for field in ('inning_scores', 'team_stats', 'batter_stats', 'pitcher_stats'):
                    self.assertTrue(payload[field])

    def test_seal_first_identical_sync_succeeds(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                old = oracle(self, a)[0]
                results, errors = ordered_pair(self, a,
                    lambda a: a.seal_year(2026, expected_match_count=1),
                    lambda a: sync(a, [make_record()]), SEAL_READ)
                self.assertEqual({}, errors)
                self.assertEqual({'inserted': 0, 'already_archived': 1}, results['second'])
                self.assertEqual(old, oracle(self, a)[0])

    def test_concurrent_duplicate_sync_is_idempotent(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                results, errors = ordered_pair(self, a,
                    lambda a: sync(a, [make_record('M2')]),
                    lambda a: sync(a, [make_record('M2')]))
                self.assertEqual({}, errors)
                self.assertEqual({'inserted': 1, 'already_archived': 0}, results['first'])
                self.assertEqual({'inserted': 0, 'already_archived': 1}, results['second'])
                self.assertEqual(2, len(oracle(self, a)[0]))

    def test_concurrent_initial_identity_same_and_different(self):
        for mode in MODES:
            for seed in (42, 99):
                with self.subTest(mode=mode, seed=seed):
                    a = self.fixture(mode, empty=True)
                    results, errors = ordered_pair(self, a,
                        lambda a: sync(a, [make_record()]),
                        lambda a: sync(a, [make_record()], seed=seed),
                        'SELECT metadata_json FROM archive_identity')
                    if seed == 42:
                        self.assertEqual({}, errors)
                        self.assertEqual(1, results['second']['already_archived'])
                    else:
                        self.conflict(errors)
                    self.assertEqual(1, len(oracle(self, a)[0]))

    def test_concurrent_seal_is_idempotent(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                results, errors = ordered_pair(self, a,
                    lambda a: a.seal_year(2026, expected_match_count=1),
                    lambda a: a.seal_year(2026, expected_match_count=1), SEAL_READ)
                self.assertEqual({}, errors)
                self.assertFalse(results['first']['already_sealed'])
                self.assertTrue(results['second']['already_sealed'])
                oracle(self, a)

    def test_seal_and_register_both_orders(self):
        for mode in MODES:
            for seal_first in (True, False):
                with self.subTest(mode=mode, seal_first=seal_first):
                    a = self.fixture(mode)
                    seal = lambda a: a.seal_year(2026, expected_match_count=1)
                    reg = lambda a: register(a)
                    results, errors = ordered_pair(self, a,
                        seal if seal_first else reg, reg if seal_first else seal,
                        SEAL_READ if seal_first else REGISTER_READ)
                    # 年度の重なり：どちらの順でも登録できる
                    self.assertEqual({}, errors)
                    registered = results['second' if seal_first else 'first']
                    self.assertTrue(registered['registered'])
                    self.assertEqual([2026, 2027], [r[0] for r in oracle(self, a)[1]])

    def test_registration_same_or_conflicting_identity(self):
        for mode in MODES:
            for seed in (42, 99):
                with self.subTest(mode=mode, seed=seed):
                    a = self.fixture(mode)
                    a.seal_year(2026, expected_match_count=1)
                    results, errors = ordered_pair(self, a,
                        lambda a: register(a), lambda a: register(a, seed=seed), REGISTER_READ)
                    self.assertTrue(results['first']['registered'])
                    if seed == 42:
                        self.assertEqual({}, errors)
                        self.assertFalse(results['second']['registered'])
                    else:
                        self.conflict(errors)
                    self.assertEqual([2026, 2027], [r[0] for r in oracle(self, a)[1]])

    def test_register_and_next_year_sync_both_orders(self):
        for mode in MODES:
            for reg_first in (True, False):
                with self.subTest(mode=mode, reg_first=reg_first):
                    a = self.fixture(mode)
                    a.seal_year(2026, expected_match_count=1)
                    old = oracle(self, a)[0]
                    row = make_record('Y2027', ability=False)
                    row['match_date'] = '2027-07-12'
                    reg = lambda a: register(a)
                    add = lambda a: sync(a, [row], year=2027)
                    results, errors = ordered_pair(self, a,
                        reg if reg_first else add, add if reg_first else reg,
                        REGISTER_READ if reg_first else 'SELECT metadata_json FROM archive_identity')
                    if reg_first:
                        self.assertEqual({}, errors)
                    else:
                        self.conflict(errors, 'first')
                        add(a)
                    self.assertEqual(old, [r for r in oracle(self, a)[0] if r[0] == 2026])
                    self.assertEqual(2, len(oracle(self, a)[0]))

    def test_nonadjacent_registration_refuses(self):
        # 年度の重なりで、前の年度が封印前でも翌年度は登録できる。
        # 年度を飛ばした登録は封印の前後どちらでも断る。
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                before = snapshot(a)
                with self.assertRaises(HistoricalMatchConflictError):
                    register(a, year=2028)
                self.assertEqual(before, snapshot(a))
                a.seal_year(2026, expected_match_count=1)
                before = snapshot(a)
                with self.assertRaises(HistoricalMatchConflictError):
                    register(a, year=2028)
                self.assertEqual(before, snapshot(a))

    def test_changed_full_a_and_sealed_new_record_refuse_without_write(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                a.seal_year(2026, expected_match_count=1)
                before = snapshot(a), a.db_path.read_bytes()
                edits = [make_record(score=5), make_record('M2')]
                detail = make_record()
                detail['ability_detail']['batter_stats'][0]['hits'] += 1
                edits.append(detail)
                for row in edits:
                    with self.assertRaises(HistoricalMatchConflictError):
                        sync(a, [row])
                    self.assertEqual(before, (snapshot(a), a.db_path.read_bytes()))
                oracle(self, a)

    def test_partial_batch_rolls_back_inserts_on_conflict(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                before = snapshot(a), a.db_path.read_bytes()
                with self.assertRaises(HistoricalMatchConflictError):
                    sync(a, [make_record('M2'), make_record(score=5)])
                self.assertEqual(before, (snapshot(a), a.db_path.read_bytes()))
                oracle(self, a)

    def test_write_fault_rolls_back_identity_year_and_rows_and_closes(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode, empty=True)
                before = snapshot(a)
                handles = []
                class Fault(sqlite3.Connection):
                    def execute(self, sql, parameters=()):
                        cursor = super().execute(sql, parameters)
                        if 'INSERT INTO historical_matches' in sql:
                            raise RuntimeError('injected after insert')
                        return cursor
                    def executemany(self, sql, parameters):
                        cursor = super().executemany(sql, parameters)
                        if 'INSERT INTO historical_matches' in sql:
                            raise RuntimeError('injected after insert')
                        return cursor
                def connect():
                    con = sqlite3.connect(a.db_path, factory=Fault)
                    con.row_factory = sqlite3.Row
                    handles.append(con)
                    return con
                with patch.object(a, '_connect', connect):
                    with self.assertRaisesRegex(RuntimeError, 'injected'):
                        sync(a, [make_record()])
                self.assertEqual(before, snapshot(a))
                for con in handles:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        con.execute('SELECT 1')
                sync(a, [make_record()])
                oracle(self, a)

    def test_seal_and_register_write_faults_roll_back_and_release_lock(self):
        for mode in MODES:
            for operation in ('seal', 'register'):
                with self.subTest(mode=mode, operation=operation):
                    a = self.fixture(mode)
                    if operation == 'register':
                        a.seal_year(2026, expected_match_count=1)
                    before = snapshot(a)
                    class Fault(sqlite3.Connection):
                        def execute(self, sql, parameters=()):
                            cursor = super().execute(sql, parameters)
                            if ('UPDATE career_years' in sql or 'INSERT INTO career_years' in sql):
                                raise RuntimeError('injected after year write')
                            return cursor
                    handles = []
                    def connect():
                        con = sqlite3.connect(a.db_path, factory=Fault)
                        con.row_factory = sqlite3.Row
                        handles.append(con)
                        return con
                    action = (lambda: a.seal_year(2026, expected_match_count=1)) if operation == 'seal' else lambda: register(a)
                    with patch.object(a, '_connect', connect):
                        with self.assertRaisesRegex(RuntimeError, 'injected'):
                            action()
                    self.assertEqual(before, snapshot(a))
                    for con in handles:
                        with self.assertRaises(sqlite3.ProgrammingError):
                            con.execute('SELECT 1')
                    action()
                    oracle(self, a)

    def test_expected_count_invalid_or_unexpected_never_seals(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                before = snapshot(a), a.db_path.read_bytes()
                for count in (-1, True, 1.0, '1', None, 0, 2):
                    with self.assertRaises(ValueError):
                        a.seal_year(2026, expected_match_count=count)
                    self.assertEqual(before, (snapshot(a), a.db_path.read_bytes()))
                a.seal_year(2026, expected_match_count=1)
                before = snapshot(a)
                with self.assertRaises(HistoricalMatchConflictError):
                    a.seal_year(2026, expected_match_count=2)
                self.assertEqual(before, snapshot(a))

    def test_sealed_corrupt_ledger_refuses_reseal(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                a.seal_year(2026, expected_match_count=1)
                with closing(sqlite3.connect(a.db_path)) as con, con:
                    con.execute("UPDATE career_years SET ledger_sha256='bad'")
                before = snapshot(a)
                with self.assertRaisesRegex(HistoricalMatchConflictError, 'ledger'):
                    a.seal_year(2026, expected_match_count=1)
                self.assertEqual(before, snapshot(a))

    def test_legacy_score_only_and_duplicate_batch_validation(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                a = self.fixture(mode)
                row = make_record('SCORE', ability=False)
                sync(a, [row])
                a.seal_year(2026, expected_match_count=2)
                before = snapshot(a), a.db_path.read_bytes()
                self.assertEqual(1, sync(a, [row])['already_archived'])
                with self.assertRaisesRegex(ValueError, 'duplicate'):
                    sync(a, [row, row])
                self.assertEqual(before, (snapshot(a), a.db_path.read_bytes()))
                payload = a.get_match(2026, 'CMP-1', 'SCORE')
                self.assertIsNone(payload['inning_scores'])
                self.assertIsNone(payload['batter_stats'])
                oracle(self, a)

    def test_busy_timeout_fails_closed_then_retry_succeeds(self):
        for mode in MODES:
            for operation in ('sync', 'seal', 'register'):
                with self.subTest(mode=mode, operation=operation):
                    a = self.fixture(mode)
                    if operation == 'register':
                        a.seal_year(2026, expected_match_count=1)
                    before = snapshot(a)
                    ready, release = threading.Event(), threading.Event()
                    lock_errors = []
                    def lock():
                        try:
                            with closing(sqlite3.connect(a.db_path)) as con, con:
                                con.execute('BEGIN IMMEDIATE')
                                ready.set()
                                if not release.wait(10):
                                    raise TimeoutError('busy boundary')
                        except BaseException as exc:
                            lock_errors.append(exc)
                    thread = threading.Thread(target=lock)
                    thread.start()
                    handles = []
                    def connect():
                        con = sqlite3.connect(a.db_path, timeout=0.05)
                        con.row_factory = sqlite3.Row
                        handles.append(con)
                        return con
                    action = {'sync': lambda: sync(a, [make_record('M2')]),
                              'seal': lambda: a.seal_year(2026, expected_match_count=1),
                              'register': lambda: register(a)}[operation]
                    try:
                        self.assertTrue(ready.wait(10))
                        start = perf_counter()
                        with patch.object(a, '_connect', connect):
                            with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                                action()
                        self.assertGreaterEqual(perf_counter() - start, 0.04)
                    finally:
                        release.set()
                        thread.join(10)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual([], lock_errors)
                    self.assertEqual(before, snapshot(a))
                    for con in handles:
                        with self.assertRaises(sqlite3.ProgrammingError):
                            con.execute('SELECT 1')
                    action()
                    oracle(self, a)

    def test_schema_failure_and_readers_close_handles(self):
        a = self.fixture('DELETE')
        handles = []
        real_connect = sqlite3.connect
        def capture(*args, **kwargs):
            con = real_connect(*args, **kwargs)
            handles.append(con)
            return con
        with patch('phase2_engine.historical_match_archive.sqlite3.connect', capture):
            # 年度を閉じるときの VACUUM の間も待てるように（historical_match_archive.BUSY_TIMEOUT_SECONDS）
            self.assertEqual(BUSY_TIMEOUT_SECONDS * 1000, a._connect().execute('PRAGMA busy_timeout').fetchone()[0])
            handles.pop().close()
            for action in (lambda: sync(a, [make_record()]),
                           lambda: a.list_years(), lambda: a.get_match(2026, 'CMP-1', 'M1'),
                           lambda: a.list_matches(2026, school_id='SCH-1')):
                action()
            with patch('phase2_engine.historical_match_archive._SCHEMA', 'INVALID SQL;'):
                with self.assertRaises(sqlite3.OperationalError):
                    sync(a, [])
        for con in handles:
            with self.assertRaises(sqlite3.ProgrammingError):
                con.execute('SELECT 1')
        oracle(self, a)


if __name__ == '__main__':
    unittest.main()
