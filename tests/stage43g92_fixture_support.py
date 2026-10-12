"""Owned SQLite fixtures: deterministic writer order and independent oracle."""
from contextlib import closing
import hashlib
import json
import sqlite3
import threading

from phase2_engine.historical_match_archive import HistoricalMatchArchive

TIMEOUT = 10
STATUS_READ = 'SELECT metadata_json, status FROM career_years WHERE year='
SEAL_READ = 'SELECT status, match_count, ledger_sha256 FROM career_years'
REGISTER_READ = 'SELECT metadata_json, status FROM career_years WHERE year='


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def oracle(case, archive):
    """Never call the production _ledger/_canonical/_history_payload helpers."""
    with closing(sqlite3.connect(archive.db_path)) as con:
        rows = con.execute('SELECT year,competition_id,match_id,record_sha256,payload_json '
                           'FROM historical_matches ORDER BY 1,2,3').fetchall()
        headers = con.execute('SELECT year,status,match_count,ledger_sha256 '
                              'FROM career_years ORDER BY year').fetchall()
        for year, cid, mid, sha, raw in rows:
            case.assertEqual(sha, digest(raw))
            payload = json.loads(raw)
            case.assertEqual((year, cid, mid), (payload['year'], payload['competition_id'], payload['match_id']))
        for year, status, count, ledger in headers:
            if status == 'sealed':
                items = [(cid, mid, sha) for y, cid, mid, sha, raw in rows if y == year]
                raw = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                case.assertEqual((len(items), digest(raw)), (count, ledger))
        return rows, headers


def snapshot(archive):
    with closing(sqlite3.connect(archive.db_path)) as con:
        return {table: con.execute('SELECT * FROM ' + table + ' ORDER BY 1,2').fetchall()
                for table in ('archive_identity', 'career_years', 'historical_matches')}


def ordered_pair(case, archive, first, second, boundary=STATUS_READ):
    """Pause first writer at a state read; second attempts BEGIN before release.

    Instrument only owned, independent connections. No sleeps, production
    hooks, daemon threads or shared connections. Always join both workers.
    """
    paused, release, attempted = (threading.Event() for _ in range(3))
    handles, results, errors = [], {}, {}
    def connect(role):
        class Probe(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                normalized = ' '.join(sql.split())
                if role == 'second' and normalized == 'BEGIN IMMEDIATE':
                    attempted.set()
                cursor = super().execute(sql, parameters)
                if normalized.startswith('SELECT'):
                    # Every decision must use the reserved writer transaction.
                    case.assertTrue(self.in_transaction, normalized)
                if role == 'first' and normalized.startswith(boundary) and not paused.is_set():
                    paused.set()
                    if not release.wait(TIMEOUT):
                        raise TimeoutError('first writer boundary')
                return cursor
        con = sqlite3.connect(archive.db_path, factory=Probe)
        con.row_factory = sqlite3.Row
        handles.append(con)
        return con
    def worker(role, operation):
        target = HistoricalMatchArchive(archive.db_path)
        target._connect = lambda: connect(role)
        try:
            results[role] = operation(target)
        except BaseException as exc:
            errors[role] = exc
    first_thread = threading.Thread(target=worker, args=('first', first))
    second_thread = threading.Thread(target=worker, args=('second', second))
    first_thread.start()
    started_second = False
    try:
        case.assertTrue(paused.wait(TIMEOUT), 'first writer did not reach state read')
        # An independent zero-timeout writer proves the reservation exists.
        with closing(sqlite3.connect(archive.db_path, timeout=0)) as probe:
            with case.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                probe.execute('BEGIN IMMEDIATE')
        second_thread.start()
        started_second = True
        case.assertTrue(attempted.wait(TIMEOUT), 'second writer did not attempt reservation')
    finally:
        release.set()
        first_thread.join(TIMEOUT)
        if started_second:
            second_thread.join(TIMEOUT)
    case.assertFalse(first_thread.is_alive())
    case.assertFalse(second_thread.is_alive())
    for con in handles:
        with case.assertRaises(sqlite3.ProgrammingError):
            con.execute('SELECT 1')
    return results, errors
