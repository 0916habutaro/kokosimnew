"""複数年度のMAIN登録校：進出情報、限定読取、接続の解放。"""
from contextlib import closing
import json
import pickle
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from phase2_engine.competition_history import entrants_record
import test_screen_best8 as fixtures
from test_screen_best8 import season
from test_competition_records import tournament, CID


class EntrantsHistoryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.Best8ScreenTests.setUpClass.__func__)
    setUp = fixtures.Best8ScreenTests.setUp

    def record(self, year=2144):
        main, scheduled, calendar = tournament()
        current = season(scheduled, calendar, year)
        return entrants_record(current, CID, self.repo), main, current

    def test_official_main_registration_finishes_and_no_mutation(self):
        row, main, current = self.record()
        before = pickle.dumps(current)
        self.assertEqual(set(main.entrant_school_ids), {e['school_id'] for e in row['entrants']})
        self.assertEqual(32, len(row['entrants']))
        self.assertEqual(1, sum(e['finish'] == '優勝' for e in row['entrants']))
        self.assertTrue(all(e['entry_type'] == 'MAIN' for e in row['entrants']))
        self.assertEqual(before, pickle.dumps(current))
        current.competitions[CID].is_complete = False
        active = entrants_record(current, CID, self.repo)
        self.assertEqual('進行中', active['status'])
        self.assertTrue(all(not e['finish'] for e in active['entrants']))
        current.competitions[CID].runtime = SimpleNamespace(main_runtime=None)
        missing = entrants_record(current, CID, self.repo)
        self.assertFalse(missing['main_confirmed'])
        self.assertEqual([], missing['entrants'])

    def test_saved_routes_union_and_duplicate_registration(self):
        row, main, current = self.record()
        main.entrant_school_ids = ['FAKE-UNION', 'FAKE-UNION', 'A']
        current.qualification_resolutions = [SimpleNamespace(destination_competition_id=CID,
            status='PASS', source_competition_id='FAKE-SUMMER-NORTH', resolved_school_ids=('FAKE-UNION',))]
        current.regional_feeder_resolutions = [SimpleNamespace(destination_competition_id=CID,
            status='PASS', source_competition_id='FAKE-PREF', source_prefecture_code='01',
            resolved_school_ids=('A',))]
        row = entrants_record(current, CID, self.repo)
        self.assertEqual(2, len(row['entrants']))
        self.assertEqual('FAKE-SUMMER-NORTH', row['entrants'][0]['routes'][0]['competition_id'])
        self.assertEqual('01', row['entrants'][1]['routes'][0]['prefecture_code'])

    def test_120_years_162_competitions_bounded_read_and_cleanup(self):
        row, _, _ = self.record()
        for year in range(2026, 2146):
            self.archive.store_closed_season(year, b'not a snapshot', {}, entrant_records=[
                {**row, 'school_year': year, 'competition_id': cid} for cid in self.repo.competitions])
        before = self.archive.db_path.read_bytes()
        for count in (5, 10, 20):
            with patch('phase2_engine.historical_match_archive.json.loads', wraps=json.loads) as decode:
                data = self.data.records_entrants({'competition_id': self.cid, 'end': 2145, 'count': count})
                self.assertEqual(count, len(data['rows']))
                self.assertEqual(count, decode.call_count)
        self.assertEqual(before, self.archive.db_path.read_bytes())
        with closing(sqlite3.connect(self.archive.db_path)) as conn:
            plan = str(conn.execute('EXPLAIN QUERY PLAN SELECT record_json FROM competition_entrants WHERE competition_id=? AND year BETWEEN ? AND ?', (self.cid, 2126, 2145)).fetchall())
        self.assertIn('SEARCH', plan)
        self.assertIn('competition_id=? AND year>? AND year<?', plan)
        self.tmp.cleanup()  # Windowsで開いた接続が残っていれば失敗する

    def test_entrant_index_transaction_rolls_back_and_historical_name(self):
        row, _, _ = self.record()
        row['competition_id'] = self.cid
        self.archive.store_closed_season(2144, b'original', {}, entrant_records=[row])
        with self.assertRaises(sqlite3.IntegrityError):
            self.archive.store_closed_season(2144, b'new', {}, entrant_records=[row, row])
        self.assertEqual([row], self.archive.competition_entrants(self.cid, 2144, 2144))
        self.data.names.edits.set_info('A', '2145-01-01', {'short_name': '架空新校名'})
        rows = self.data.records_entrants({'competition_id': self.cid, 'start':2144, 'end':2145})['rows']
        self.assertEqual('記録なし', rows[0]['status'])
        self.assertEqual('架空校A', rows[1]['entrants'][0]['name'])
