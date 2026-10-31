"""大会別ベスト8：確定結果、限定索引、複数年度の読み取り専用画面。"""
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import pickle
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from phase2_engine import DataRepository
from phase2_engine.career_state import CareerState
from phase2_engine.competition_history import best8_record, FINISHES, season_best8
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.screen.app import ScreenApi
from phase2_engine.screen.data import GameScreenData
from phase2_engine.screen.competition_names import CompetitionNames
from phase2_engine.screen.school_names import EditedNames
from phase2_engine.school_edits import SchoolEdits
from test_competition_records import tournament, CID, first_wins
from phase2_engine.tournament_runtime import MainTournamentRuntimeState


def sized_tournament(count):
    ids = [f'FAKE-{n}' for n in range(count)]
    main = MainTournamentRuntimeState.create(competition_id=CID, reference_year=2026,
        generation_seed=7, stage_id='FAKE-MAIN', entrants=ids, match_resolver=first_wins)
    main.resolve_all()
    matches = {mid: SimpleNamespace(match_date='2027-03-28', stage_code='MAIN',
        status='completed', team1_id=m.team1, team2_id=m.team2)
        for mid, m in main.matches.items() if m.status == 'completed'}
    scheduled = SimpleNamespace(runtime=main, matches=matches, is_complete=True,
                                competition_name='架空大会')
    return main, scheduled, {'start_date': '2027-03-20', 'end_date': '2027-03-28'}

ROOT = Path(__file__).resolve().parents[1]


def season(scheduled, calendar, year=2026):
    return SimpleNamespace(year=year, competitions={CID: scheduled},
        calendar_rows={CID: calendar}, annual_templates={CID: None},
        current_date=date(year + 1, 4, 5))


class Best8ProjectionTests(unittest.TestCase):
    def test_small_and_large_brackets_have_disjoint_actual_finishes(self):
        for count in (1, 2, 3, 4, 5, 7, 8, 10, 16, 49):
            with self.subTest(count=count):
                main, scheduled, calendar = sized_tournament(count)
                current = season(scheduled, calendar)
                before = pickle.dumps(current)
                row = best8_record(current, CID)
                self.assertEqual('完了', row['status'])
                ids = [s['school_id'] for rows in row['groups'].values() for s in rows]
                self.assertEqual(min(count, 8), len(ids))
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(main.champion_school_id, row['groups']['優勝'][0]['school_id'])
                for finish, offset in [('ベスト4', 1), ('ベスト8', 2)]:
                    expected = main.eliminated_by_round.get(main.total_rounds - offset, []) if main.total_rounds > offset else []
                    self.assertEqual(expected, [s['school_id'] for s in row['groups'][finish]])
                self.assertEqual(before, pickle.dumps(current))

    def test_incomplete_does_not_publish_even_existing_main_finalists(self):
        _, scheduled, calendar = tournament(complete=False)
        row = best8_record(season(scheduled, calendar), CID)
        self.assertEqual('進行中', row['status'])
        self.assertFalse(any(row['groups'].values()))

    def test_preliminary_only_upcoming_missing_and_cross_year(self):
        _, scheduled, calendar = tournament()
        current = season(scheduled, calendar)
        row = best8_record(current, CID)
        self.assertEqual(2026, row['school_year'])
        self.assertTrue(row['groups']['優勝'][0]['date'].startswith('2027-'))
        current.current_date = date(2026, 4, 1)
        current.competitions = {}
        self.assertEqual('未開催', best8_record(current, CID)['status'])
        current.competitions[CID] = SimpleNamespace(runtime=SimpleNamespace(main_runtime=None),
            matches=scheduled.matches, is_complete=False, competition_name='架空予選')
        row = best8_record(current, CID)
        self.assertEqual('進行中', row['status'])
        self.assertFalse(any(row['groups'].values()))
        current.competitions[CID].is_complete = True
        self.assertEqual('記録なし', best8_record(current, CID)['status'])

    def test_seed_qualifier_main_uses_nested_official_final(self):
        main, scheduled, calendar = tournament()
        scheduled.runtime = SimpleNamespace(main_runtime=None,
            qualifier_runtime=SimpleNamespace(main_runtime=main))
        row = best8_record(season(scheduled, calendar), CID)
        self.assertEqual('完了', row['status'])
        self.assertEqual(8, sum(len(s) for s in row['groups'].values()))

    def test_walkover_and_joint_team_are_school_results(self):
        main, scheduled, calendar = tournament()
        final = next(m for m in scheduled.matches.values() if m.round_no == main.total_rounds)
        final.score_source = 'walkover'
        final.team1_score = final.team2_score = None
        main.champion_school_id = 'FAKE-UNION-A-B'
        row = best8_record(season(scheduled, calendar), CID)
        self.assertEqual('FAKE-UNION-A-B', row['groups']['優勝'][0]['school_id'])
        self.assertEqual(main.runner_up_school_id, row['groups']['準優勝'][0]['school_id'])


class Best8ScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / 'data')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = HistoricalMatchArchive(Path(self.tmp.name) / 'history.sqlite3')
        self.data = GameScreenData.__new__(GameScreenData)
        current = CareerState.__new__(CareerState)
        current.seasons = {2146: SimpleNamespace(year=2146, annual_templates={}, competitions={})}
        current.current_date = date(2146, 4, 1)
        self.data.session = SimpleNamespace(state=current, slot_id='fake')
        self.data.service = SimpleNamespace(repo=self.repo, _history_archive=lambda slot: self.archive)
        self.data.prefectures = {'01': '架空県'}
        self.data.competition_names = CompetitionNames(ROOT / 'config')
        self.data.names = EditedNames(lambda sid: '架空校' + sid, SchoolEdits())
        self.cid = next(iter(self.repo.competitions))

    def store(self, year, cid=None):
        row = {'school_year': year, 'competition_id': cid or self.cid, 'status': '完了',
               'competition_name': f'第{year}回架空大会',
               'groups': {f: ([{'school_id': 'FAKE-A', 'date': f'{year}-08-01'}] if f == '優勝' else []) for f in FINISHES}}
        self.archive.store_closed_season(year, b'not a snapshot', {}, best8_records=[row])
        return row

    def test_empty_read_creates_no_database_and_api_validates_range(self):
        result = ScreenApi(self.data).records_best8()
        self.assertEqual(162, len(result['catalog']))
        # 既定の範囲はゲーム開始の年度から（開始前の年度は並べない）
        self.assertEqual([2146], [r['school_year'] for r in result['rows']])
        self.assertIsNone(result['before_start'])
        self.assertFalse(self.archive.db_path.exists())
        self.assertIn('error', ScreenApi(self.data).records_best8({'count': 6}))
        self.assertIn('error', ScreenApi(self.data).records_best8({'start': 2147, 'end': 2146}))

    def test_120_years_only_selected_competition_and_range_are_decoded(self):
        for year in range(2026, 2146):
            row = self.store(year)
            self.archive.store_closed_season(year, b'not a snapshot', {},
                best8_records=[{**row, 'competition_id': cid} for cid in self.repo.competitions])
        before = self.archive.db_path.read_bytes()
        state_before = pickle.dumps(self.data.state.__dict__)
        for count in (5, 10, 20):
            with patch('phase2_engine.historical_match_archive.json.loads', wraps=json.loads) as decode:
                result = self.data.records_best8({'competition_id': self.cid, 'count': count, 'end': 2145})
                self.assertEqual(count, len(result['rows']))
                self.assertEqual(count, decode.call_count)
                self.assertEqual(list(range(2145, 2145 - count, -1)), [r['school_year'] for r in result['rows']])
        self.assertEqual(before, self.archive.db_path.read_bytes())
        self.assertEqual(state_before, pickle.dumps(self.data.state.__dict__))
        with closing(sqlite3.connect(self.archive.db_path)) as conn:
            plan = str(conn.execute('EXPLAIN QUERY PLAN SELECT record_json FROM competition_best8 WHERE competition_id=? AND year BETWEEN ? AND ?', (self.cid, 2126, 2145)).fetchall())
        self.assertIn('SEARCH', plan)
        self.assertIn('competition_id=? AND year>? AND year<?', plan)

    def test_catalog_all_162_filters_and_stable_range(self):
        catalog = self.data.records_best8()['catalog']
        self.assertEqual(162, len({c['competition_id'] for c in catalog}))
        for c in catalog:
            filters = {'competition_id': c['competition_id'], 'segment': c['segment'],
                'level': c['level'], 'prefecture': c['prefecture'],
                'start': 2130, 'end': 2140}
            for region in c['regions'] or ['']:
                result = self.data.records_best8({**filters, 'region': region})
                self.assertEqual(c['competition_id'], result['filters']['competition_id'])
                self.assertEqual((2130, 2140), (result['start'], result['end']))
        self.assertEqual(49, sum(c['segment'] == 'summer' and c['level'] == 'local' for c in catalog))
        self.assertEqual([], self.data.records_best8({'region': 'invalid'})['rows'])

    def test_historical_names_missing_year_and_reopen(self):
        self.store(2144)
        self.data.names.edits.set_info('FAKE-A', '2145-01-01', {'short_name': '架空新校名'})
        result = self.data.records_best8({'competition_id': self.cid, 'start': 2144, 'end': 2145})
        self.assertEqual('記録なし', result['rows'][0]['status'])
        self.assertFalse(result['rows'][0]['can_open'])
        old = result['rows'][1]
        self.assertTrue(old['can_open'])
        self.assertEqual('架空校FAKE-A', old['groups']['優勝'][0]['name'])
        self.data.service._history_archive = lambda slot: HistoricalMatchArchive(self.archive.db_path)
        self.assertEqual(result, self.data.records_best8(result['filters']))

    def test_years_before_game_start_are_one_range(self):
        result = self.data.records_best8({'competition_id': self.cid, 'start': 2140, 'end': 2146})
        self.assertEqual([2146], [r['school_year'] for r in result['rows']])
        self.assertEqual({'start': 2140, 'end': 2145}, result['before_start'])
        only_before = self.data.records_entrants({'competition_id': self.cid, 'start': 2140, 'end': 2142})
        self.assertEqual([], only_before['rows'])
        self.assertEqual({'start': 2140, 'end': 2142}, only_before['before_start'])

    def test_live_runtime_has_priority_over_archive(self):
        self.store(2144)
        main, scheduled, calendar = tournament()
        live = season(scheduled, calendar, 2144)
        live.annual_templates = {self.cid: None}
        live.competitions = {self.cid: scheduled}
        live.calendar_rows = {self.cid: calendar}
        self.data.state.seasons = {2144: live}
        self.data.state.plans = {2144: SimpleNamespace(entries={})}
        row = self.data.records_best8({'competition_id': self.cid,
                                      'start': 2144, 'end': 2144})['rows'][0]
        self.assertEqual(main.champion_school_id, row['groups']['優勝'][0]['school_id'])
        self.assertNotEqual('FAKE-A', row['groups']['優勝'][0]['school_id'])

    def test_sealing_replaces_index_and_duplicate_rolls_back(self):
        old = self.store(2145)
        with self.assertRaises(sqlite3.IntegrityError):
            self.archive.store_closed_season(2145, b'new', {}, best8_records=[old, old])
        self.assertEqual([old], self.archive.competition_best8(self.cid, 2145, 2145))
        self.store(2145)
        self.assertEqual(1, len(self.archive.competition_best8(self.cid, 2145, 2145)))


if __name__ == '__main__':
    unittest.main()
