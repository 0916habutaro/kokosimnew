"""Legacy inventory boundaries; Stage92 requires safe sync/seal serialization."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from stage43g91_fixture_support import closed_archive_connection

from stage43g92_fixture_support import ordered_pair, oracle

from phase2_engine.historical_match_archive import HistoricalMatchArchive, HistoricalMatchConflictError
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

    def test_old_a_sync_seal_interleaving_preserves_ledger_and_inventory_accepts(self):
        results, errors = ordered_pair(
            self, self.archive,
            lambda archive: sync(archive, [record('M1'), record('M2')]),
            lambda archive: archive.seal_year(2026, expected_match_count=1),
        )
        self.assertEqual({'inserted': 1, 'already_archived': 1}, results['first'])
        self.assertEqual({'second'}, set(errors))
        self.assertIsInstance(errors['second'], HistoricalMatchConflictError)
        rows, headers = oracle(self, self.archive)
        self.assertEqual(2, len(rows))
        self.assertEqual([(2026, 'active', None, None)], headers)
        self.archive.seal_year(2026, expected_match_count=2)
        oracle(self, self.archive)
        result = self.audit()
        self.assertTrue(result['contract_consistent'], result['blockers'])
        self.assertEqual(1, result['counts']['legacy_sealed_years'])

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
