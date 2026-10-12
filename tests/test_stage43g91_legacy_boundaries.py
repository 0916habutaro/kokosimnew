"""Reproduce existing legacy boundaries without changing production writers."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from stage43g91_fixture_support import closed_archive_connection

from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.save_inventory_audit import inventory_slot


def record(mid):
    return {
        'competition_id': 'AUDIT91', 'match_id': mid,
        'team1_id': 'FIXTURE91-A', 'team2_id': 'FIXTURE91-B',
        'winner_id': 'FIXTURE91-A', 'loser_id': 'FIXTURE91-B',
        'status': 'completed', 'match_date': '2026-07-12',
        'date_source': 'fixture_only_iso', 'score_source': 'generated_v1',
        'team1_score': 4, 'team2_score': 2,
    }


def sync(archive, rows, year=2026):
    return archive.sync(year=year, rng_seed=43,
                        resolver_contract='fixture91',
                        plan_fingerprint='fixture91-' + str(year), completed=rows)


class Stage43G91LegacyBoundaryTests(unittest.TestCase):
    def setUp(self):
        lifetime = patch.object(HistoricalMatchArchive, '_connect', closed_archive_connection)
        lifetime.start()
        self.addCleanup(lifetime.stop)
        self.temp = tempfile.TemporaryDirectory(prefix='stage91-boundary-')
        self.addCleanup(self.temp.cleanup)
        self.slot = Path(self.temp.name) / 'fixture91'
        self.archive = HistoricalMatchArchive(self.slot / 'historical_matches.sqlite3')
        sync(self.archive, [record('M1')])

    def audit(self):
        return inventory_slot(self.slot, slot_id='fixture91', contract='legacy_history', authorized_read=True)

    def test_old_a_sync_seal_interleaving_exposes_ledger_breach_and_inventory_refuses(self):
        # Captured status read is deliberately BEFORE the first write. The
        # existing legacy sync has no BEGIN IMMEDIATE covering this read.
        read = threading.Event()
        resume = threading.Event()
        errors = []
        class OneRow:
            def __init__(self, row):
                self.row = row
            def fetchone(self):
                return self.row
        class OrderedConnection(sqlite3.Connection):
            depth = 0
            def __enter__(self):
                self.depth += 1
                return super().__enter__()
            def execute(self, sql, parameters=()):
                cursor = super().execute(sql, parameters)
                normalized = ' '.join(sql.split())
                if normalized.startswith('SELECT metadata_json, status FROM career_years WHERE year='):
                    row = cursor.fetchone()
                    cursor.fetchall()  # release the SQLite read statement
                    read.set()
                    if not resume.wait(10):
                        raise TimeoutError('fixture status boundary')
                    return OneRow(row)
                return cursor
            def __exit__(self, *args):
                try:
                    return super().__exit__(*args)
                finally:
                    self.depth -= 1
                    if not self.depth:
                        self.close()
        writer = HistoricalMatchArchive(self.archive.db_path)
        def connect():
            con = sqlite3.connect(writer.db_path, factory=OrderedConnection)
            con.row_factory = sqlite3.Row
            return con
        writer._connect = connect  # fixture-local, no production hooks
        def append():
            try:
                sync(writer, [record('M1'), record('M2')])
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=append, daemon=True)
        thread.start()
        try:
            self.assertTrue(read.wait(10), 'writer did not reach known status read')
            sealed = self.archive.seal_year(2026, expected_match_count=1)
        finally:
            resume.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)
        self.assertEqual(1, sealed['match_count'])
        with closing(sqlite3.connect(self.archive.db_path)) as con:
            status, count = con.execute('SELECT status,match_count FROM career_years').fetchone()
            actual = con.execute('SELECT COUNT(*) FROM historical_matches').fetchone()[0]
        # Observation of the UNFIXED current contract, not an accepted behavior.
        self.assertEqual(('sealed', 1, 2), (status, count, actual))
        result = self.audit()
        self.assertFalse(result['contract_consistent'])
        self.assertIn('original_contract_invalid:legacy_history', result['blockers'])

    def test_year_rollover_requires_sealed_adjacent_source_and_retains_history(self):
        with self.assertRaises(ValueError):
            self.archive.register_next_year(year=2027, rng_seed=43,
                resolver_contract='fixture91', plan_fingerprint='fixture91-2027')
        self.archive.seal_year(2026, expected_match_count=1)
        self.archive.register_next_year(year=2027, rng_seed=43,
            resolver_contract='fixture91', plan_fingerprint='fixture91-2027')
        next_row = record('Y2027')
        next_row['match_date'] = '2027-07-12'
        sync(self.archive, [next_row], year=2027)
        sync(self.archive, [record('M1')])
        with closing(sqlite3.connect(self.archive.db_path)) as con:
            rows = con.execute('SELECT year,payload_json FROM historical_matches ORDER BY year').fetchall()
        self.assertEqual([2026, 2027], [r[0] for r in rows])
        self.assertEqual(4, json.loads(rows[0][1])['team1_score'])
        result = self.audit()
        self.assertTrue(result['contract_consistent'])
        self.assertEqual(1, result['counts']['legacy_sealed_years'])
        self.assertFalse(result['whole_game_restore_proven'])
