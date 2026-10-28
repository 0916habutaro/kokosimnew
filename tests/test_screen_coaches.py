"""正式画面の監督ID遷移と、日付に基づく読み取り専用の在任・勝敗表示。"""
from contextlib import closing
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import pickle
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from game_core.coaches import Coach, CoachEvent
from phase2_engine.career_state import CareerState
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.school_edits import SchoolEdits
from phase2_engine.screen.app import ScreenApi
from phase2_engine.screen.coach_views import CoachHistory
from phase2_engine.screen.data import GameScreenData
from phase2_engine.screen.school_names import EditedNames
from test_coach_personnel import fixture


def screen(book, repo, archive, today=date(2026,4,1)):
    state=CareerState.__new__(CareerState)
    state.coaches=book;state.current_date=today;state.seasons={}
    data=GameScreenData.__new__(GameScreenData)
    data.session=SimpleNamespace(state=state,slot_id='fake')
    data.service=SimpleNamespace(repo=repo,_history_archive=lambda slot:archive)
    data._coach_history=None
    data.names=EditedNames(lambda sid:'架空校'+sid,SchoolEdits())
    return data


def match(mid,day,**extra):
    return dict(year=int(day[:4])-int(day[5:7]<'04'),competition_id='FAKE-CUP',
                match_id=mid,match_date=day,date_source='runtime_wave_v1',
                team1_id='A',team2_id='B',team1_score=3,team2_score=1,
                score_source='ability_model_v1',**extra)


class CoachScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo,self.book=fixture()
        self.archive=HistoricalMatchArchive(Path(self.tmp.name)/'history.sqlite3')
        self.data=screen(self.book,self.repo,self.archive)

    def archive_rows(self,rows):
        with closing(sqlite3.connect(self.archive.db_path)) as c, c:
            c.executescript('''CREATE TABLE historical_matches (
              year INTEGER, competition_id TEXT, match_id TEXT, match_date TEXT,
              date_source TEXT, team1_id TEXT, team2_id TEXT, team1_score INTEGER,
              team2_score INTEGER, score_source TEXT);
              CREATE INDEX idx_one ON historical_matches(team1_id,year);
              CREATE INDEX idx_two ON historical_matches(team2_id,year);''')
            c.executemany('INSERT INTO historical_matches VALUES (?,?,?,?,?,?,?,?,?,?)',
                          [tuple(r[k] for k in ('year','competition_id','match_id','match_date','date_source',
                           'team1_id','team2_id','team1_score','team2_score','score_source')) for r in rows])

    def test_profile_abilities_initial_setting_and_active_tenure(self):
        d=ScreenApi(self.data).coach('COACH-A')
        self.assertEqual(('COACH-A',50,1976,'現役'),(d['coach_id'],d['age'],d['birth_year'],d['status']))
        self.assertEqual({'school_id':'A','name':'架空校A'},d['current_school'])
        self.assertEqual((2016,11),(d['appointment_year'],d['tenure_years']))
        self.assertEqual([50,40,60,30],[r['value'] for r in d['abilities']])
        self.assertTrue(all(r['description'] for r in d['abilities']))
        self.assertTrue(d['periods'][0]['configured_past'])
        self.assertEqual('開始時',d['periods'][0]['name_basis'])
        self.assertEqual(0,d['official_record']['games'])
        self.assertFalse(self.archive.db_path.exists())

    def test_transfer_identity_history_and_exact_boundary(self):
        self.book.update(date(2027,4,1),self.repo)
        self.data.state.current_date=date(2027,3,31)
        before=self.data.coach('COACH-A')
        self.assertEqual('A',before['current_school']['school_id'])
        self.assertIsNone(before['periods'][0]['end_date'])
        self.data.state.current_date=date(2027,4,1)
        after=self.data.coach('COACH-A')
        self.assertNotEqual('A',after['current_school']['school_id'])
        old,new=after['periods']
        self.assertEqual(('2027-04-01','2027-03-31','異動',11),
                         (old['end_date'],old['last_day'],old['status'],old['tenure_years']))
        self.assertEqual(('2027-04-01',1),(new['start_date'],new['tenure_years']))
        self.assertEqual('COACH-A',new['coach_id'])
        self.assertEqual('現役',after['status'])

    def test_school_history_order_and_same_name_uses_person_id(self):
        self.book.update(date(2027,4,1),self.repo)
        self.data.state.current_date=date(2027,4,1)
        rows=self.data.school_coaches('A')['coaches']
        self.assertEqual(['2016-04-01','2027-04-01'],[r['start_date'] for r in rows])
        self.assertEqual(['異動','現任'],[r['status'] for r in rows])
        for cid,c in list(self.book.coaches.items()):self.book.coaches[cid]=replace(c,display_name='架空 同名')
        a=self.data.coach(rows[0]['coach_id']);b=self.data.coach(rows[1]['coach_id'])
        self.assertEqual(a['name'],b['name']);self.assertNotEqual(a['coach_id'],b['coach_id'])
        self.assertNotEqual(a['periods'],b['periods'])

    def test_retired_person_kept_without_current_school_or_growing_tenure(self):
        old=self.book.coaches['COACH-A'];self.book.coaches['COACH-A']=replace(old,birth_year=1940)
        self.book.update(date(2027,4,1),self.repo)
        self.data.state.current_date=date(2030,4,1)
        d=self.data.coach('COACH-A')
        self.assertEqual('退任済み',d['status']);self.assertIsNone(d['current_school'])
        self.assertIsNone(d['appointment_year']);self.assertIsNone(d['tenure_years'])
        self.assertEqual(('退任',11),(d['periods'][0]['status'],d['periods'][0]['tenure_years']))
        self.assertEqual('COACH-A',self.data.school_coaches('A')['coaches'][0]['coach_id'])

    def test_rename_keeps_school_id_and_both_names(self):
        self.data.names.edits.set_info('A','2026-06-01',{'short_name':'架空改称校'})
        self.data.state.current_date=date(2026,7,1)
        d=self.data.coach('COACH-A')
        self.assertEqual({'school_id':'A','name':'架空改称校'},d['current_school'])
        self.assertEqual(('A','架空校A','架空改称校'),tuple(d['periods'][0][k] for k in ('school_id','school_name','current_school_name')))
        self.assertEqual('A',self.data.school_coaches('A')['coaches'][0]['school_id'])

    def test_save_load_readonly_and_no_calculation_calls(self):
        self.book.update(date(2027,4,1),self.repo);self.data.state.current_date=date(2027,4,1)
        before=pickle.dumps(self.book.__getstate__())
        with patch.object(self.book,'update',side_effect=AssertionError('人事を呼ばない')), \
             patch.object(self.book,'practice_for',side_effect=AssertionError('成長を呼ばない')), \
             patch.object(self.book,'intake_for',side_effect=AssertionError('入部品質を呼ばない')):
            original=self.data.coach('COACH-A');rows=self.data.school_coaches('A')
        self.assertEqual(before,pickle.dumps(self.book.__getstate__()))
        restored=pickle.loads(pickle.dumps(self.book))
        other=screen(restored,self.repo,self.archive,self.data.state.current_date)
        self.assertEqual(original,other.coach('COACH-A'));self.assertEqual(rows,other.school_coaches('A'))

    def test_cache_invalidation_after_personnel_and_session_switch(self):
        self.data.coach('COACH-A');old=self.data._coach_history
        self.data.coach('COACH-A');self.assertIs(old,self.data._coach_history)
        self.book.update(date(2027,4,1),self.repo);self.data.state.current_date=date(2027,4,1)
        self.data.coach('COACH-A');self.assertIsNot(old,self.data._coach_history)
        old=self.data._coach_history
        self.data.state.coaches=pickle.loads(pickle.dumps(self.book))
        self.data.coach('COACH-A');self.assertIsNot(old,self.data._coach_history)

    def test_api_unknown_person_school_and_busy(self):
        api=ScreenApi(self.data)
        self.assertIn('error',api.coach('UNKNOWN'))
        self.assertIn('error',api.school_coaches('UNKNOWN'))
        api._advancing=True
        self.assertTrue(api.coach('COACH-A')['busy'])
        self.assertTrue(api.school_coaches('A')['busy'])

    def test_official_records_skip_prestart_walkovers_unknown_dates_and_future(self):
        rows=[match('PRE','2026-03-31'),match('WIN','2026-04-02'),
              match('LOSS','2026-04-03'),match('BYE','2026-04-04'),
              match('UNKNOWN','2026-04-05'),match('FUTURE','2026-07-01')]
        rows[2].update(team1_score=1,team2_score=2)
        rows[3]['score_source']='walkover';rows[4]['date_source']=''
        self.archive_rows(rows);self.data.state.current_date=date(2026,6,1)
        before=self.archive.db_path.read_bytes()
        self.assertEqual((1,1,2),tuple(self.data.coach('COACH-A')['official_record'][k] for k in ('wins','losses','games')))
        self.assertEqual(before,self.archive.db_path.read_bytes())

    def test_live_results_override_archive_and_deduplicate(self):
        row=match('SAME','2026-04-02');self.archive_rows([row]);self.data.state.current_date=date(2026,4,2)
        live=SimpleNamespace(**row,status='completed')
        live.public_dict=lambda:dict(row)
        self.data.state.seasons={2026:SimpleNamespace(competitions={'FAKE-CUP':SimpleNamespace(matches={'SAME':live})})}
        self.assertEqual(1,self.data.coach('COACH-A')['official_record']['games'])
        live.status='pending'
        self.assertEqual(0,self.data.coach('COACH-A')['official_record']['games'])

    def test_cross_year_cup_uses_game_day_coach_not_tournament_year(self):
        self.book.update(date(2027,4,1),self.repo)
        new=self.book.for_school('A').coach_id
        rows=[match('MARCH','2027-03-31'),match('APRIL','2027-04-01')]
        rows[1]['year']=2026
        self.archive_rows(rows);self.data.state.current_date=date(2027,4,2)
        self.assertEqual(1,self.data.coach('COACH-A')['official_record']['wins'])
        self.assertEqual(1,self.data.coach(new)['official_record']['wins'])

    def test_warm_index_does_not_scan_all_events(self):
        for year in range(2027,2127):self.book.update(date(year,4,1),self.repo)
        self.data.state.current_date=date(2126,4,1)
        self.data.school_coaches('A')
        class NoScan(list):
            def __iter__(self):raise AssertionError('索引作成後は全イベントを走査しない')
        self.book.events=NoScan(self.book.events)
        self.assertTrue(self.data.school_coaches('A')['coaches'])
        self.assertTrue(self.data.coach(self.book.for_school('A').coach_id)['periods'])


if __name__=='__main__':unittest.main()
