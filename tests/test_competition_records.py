"""学校別の大会結果索引は年度封印と一緒に保存し、閲覧では変更しない。"""
from pathlib import Path
from dataclasses import replace
from datetime import date, timedelta
import pickle
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from phase2_engine.competition_records import competition_records, season_records
from phase2_engine.competition_schedule_runtime import ScheduledRuntimeMatch
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.models import MatchResolution
from phase2_engine.tournament_runtime import MainTournamentRuntimeState
from phase2_engine.screen.school_views import normalized_rows, year_results
from test_screen_coaches import screen
from test_coach_personnel import fixture


CID = 'FAKE-NATIONAL'
META = {'competition_type': 'national_invitational', 'competition_level': 'national',
        'season_segment': 'spring', 'competition_name': '架空春全国大会'}


def first_wins(*, team1, team2, **kwargs):
    return MatchResolution(team1, team2, 3, 1, 'ability_model_v1')


def tournament(*, count=32, complete=True, days=None, a_slot=0):
    entrants = ['A'] + [f'FAKE-{n:02}' for n in range(1, count)]
    entrants[0], entrants[a_slot] = entrants[a_slot], entrants[0]
    main = MainTournamentRuntimeState.create(competition_id=CID, reference_year=2026,
        generation_seed=7, stage_id='FAKE-MAIN', entrants=entrants,
        slot_override=entrants, match_resolver=first_wins)
    main.resolve_all()
    rows = {}
    for mid, m in main.matches.items():
        if m.status != 'completed' or (not complete and m.round_no > 1):
            continue
        day = (days or {}).get(m.round_no, (date(2027, 3, 25) + timedelta(days=m.round_no)).isoformat())
        rows[mid] = ScheduledRuntimeMatch(CID, META['competition_name'], mid, day,
            'national_day_plan_v1', 'MAIN', 'MAIN', m.round_no, '', '', '',
            m.team1, m.team1, m.team2, m.team2, status='completed', completed_on=day,
            winner_id=m.winner, loser_id=m.loser, team1_score=3, team2_score=1,
            score_source='ability_model_v1')
    scheduled = SimpleNamespace(runtime=main, is_complete=complete, matches=rows,
                               competition_name=META['competition_name'])
    calendar = {'start_date': min((m.match_date for m in rows.values()), default='2027-03-26'),
                'end_date': max((m.match_date for m in rows.values()), default='2027-03-30')}
    return main, scheduled, calendar


class CompetitionRecordArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'history.sqlite3'
        self.archive = HistoricalMatchArchive(self.path)

    @staticmethod
    def record(year=2027, school='FAKE-A', competition='FAKE-CUP'):
        return {'year': year, 'competition_id': competition, 'school_id': school,
                'finish': '優勝', 'decision_date': f'{year}-08-01'}

    def test_empty_read_does_not_create_database(self):
        self.assertEqual([], self.archive.school_competition_records('FAKE-A'))
        self.assertFalse(self.path.exists())

    def test_school_query_is_readonly_and_snapshot_is_not_opened(self):
        a, b = self.record(), self.record(school='FAKE-B')
        self.archive.store_closed_season(2027, b'not a runtime snapshot', {}, school_records=[a, b])
        before = self.path.read_bytes()
        self.assertEqual([a], self.archive.school_competition_records('FAKE-A'))
        self.assertEqual([], self.archive.school_competition_records('UNKNOWN'))
        self.assertEqual(before, self.path.read_bytes())

    def test_resealing_replaces_index_without_duplicates(self):
        a, b = self.record(), self.record(competition='FAKE-OTHER')
        for _ in range(2):
            self.archive.store_closed_season(2027, b'snapshot', {}, school_records=[a])
        self.assertEqual([a], self.archive.school_competition_records('FAKE-A'))
        self.archive.store_closed_season(2027, b'snapshot2', {}, school_records=[b])
        self.assertEqual([b], self.archive.school_competition_records('FAKE-A'))

    def test_duplicate_result_rolls_back_snapshot_and_index_together(self):
        a = self.record()
        self.archive.store_closed_season(2027, b'original', {}, school_records=[a])
        with self.assertRaises(sqlite3.IntegrityError):
            self.archive.store_closed_season(2027, b'new', {}, school_records=[a, a])
        self.assertEqual([a], self.archive.school_competition_records('FAKE-A'))
        self.assertEqual(b'original', self.archive.closed_season(2027)[0])

    def test_wrong_year_is_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            self.archive.store_closed_season(2028, b'snapshot', {}, school_records=[self.record()])
        self.assertFalse(self.path.exists())


class TournamentRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo, self.book = fixture()
        self.repo.competitions = {CID: dict(META)}
        self.archive = HistoricalMatchArchive(Path(self.tmp.name) / 'history.sqlite3')
        self.data = screen(self.book, self.repo, self.archive, date(2027, 4, 5))
        self.main, self.scheduled, self.calendar = tournament()
        self.live()

    def live(self):
        self.data.state.seasons = {2026: SimpleNamespace(year=2026,
            competitions={CID: self.scheduled}, calendar_rows={CID: self.calendar},
            current_date=self.data.state.current_date)}

    def records(self):
        return competition_records(2026, CID, self.scheduled, self.repo.competitions[CID],
                                   self.calendar, confirmed_on=self.data.state.current_date.isoformat())

    def profile(self, coach='COACH-A'):
        return self.data.coach(coach)['tournament_record']

    def summary(self, coach='COACH-A', key='spring_koshien'):
        return next(r for r in self.profile(coach)['summary'] if r['key'] == key)

    def test_champion_runnerup_best4_best8_and_first_round_match_school_results(self):
        rows = self.records()
        expected = year_results(normalized_rows([m.public_dict() for m in self.scheduled.matches.values()]),
                                self.repo.competitions, {CID: self.main.total_rounds}, lambda c, n: n)
        self.assertEqual(32, len(rows))
        for row in rows:
            self.assertEqual(expected[row['school_id']][0]['finish'], row['finish'])
            self.assertTrue(row['decision_date'])
        finishes = [r['finish'] for r in rows]
        for label, count in [('優勝', 1), ('準優勝', 1), ('ベスト4', 2), ('ベスト8', 4), ('1回戦敗退', 16)]:
            self.assertEqual(count, finishes.count(label))
        self.assertEqual((1, 1, '優勝'), tuple(self.summary()[k] for k in ('appearances', 'championships', 'best_finish')))

    def test_incomplete_tournament_counts_appearance_without_final_finish(self):
        self.main, self.scheduled, self.calendar = tournament(complete=False)
        self.live()
        self.assertEqual((1, 0, None), tuple(self.summary()[k] for k in ('appearances', 'championships', 'best_finish')))
        self.assertTrue(self.profile()['records'][0]['appearance'])
        self.assertIsNone(self.profile()['records'][0]['personal_finish'])

    def test_cross_april_transfer_splits_first_appearance_and_final_result(self):
        self.main, self.scheduled, self.calendar = tournament(days={5: '2027-04-03'})
        self.book.update(date(2027, 4, 1), self.repo)
        self.live()
        new = self.book.for_school('A').coach_id
        self.assertNotEqual('COACH-A', new)
        self.assertEqual((1, 0, None), tuple(self.summary()[k] for k in ('appearances', 'championships', 'best_finish')))
        self.assertEqual((0, 1, '優勝'), tuple(self.summary(new)[k] for k in ('appearances', 'championships', 'best_finish')))
        self.assertEqual('2027-04-03', self.profile(new)['records'][0]['decision_date'])

    def test_prestart_appearance_is_not_inferred_from_generated_prior_tenure(self):
        for m in self.scheduled.matches.values():
            m.match_date = m.completed_on = '2026-03-31' if m.round_no < 5 else '2026-04-02'
        self.calendar = {'start_date': '2026-03-31', 'end_date': '2026-04-02'}
        self.data.state.current_date = date(2026, 4, 3)
        self.live()
        self.assertEqual((0, 1), tuple(self.summary()[k] for k in ('appearances', 'championships')))

    def test_walkover_final_retains_school_champion_but_only_reference_for_coach(self):
        final = next(m for m in self.scheduled.matches.values() if m.round_no == 5)
        final.score_source = 'walkover'
        p = self.profile()
        self.assertEqual((1, 0, None), tuple(self.summary()[k] for k in ('appearances', 'championships', 'best_finish')))
        self.assertEqual(('不戦決着・帰属未確定', '不戦勝', '優勝'),
            tuple(p['references'][0][k] for k in ('label', 'resolution', 'finish')))
        self.assertEqual('A', self.main.champion_school_id)
        loser_row = next(r for r in self.records() if r['school_id'] == final.loser_id)
        self.assertEqual(('準優勝', '不戦敗', None), tuple(loser_row[k] for k in ('finish', 'resolution', 'decision_date')))
        for match in self.scheduled.matches.values():
            match.score_source = 'walkover'
        self.assertEqual((0, 0, None), tuple(self.summary()[k] for k in ('appearances', 'championships', 'best_finish')))
        self.assertEqual('優勝', self.profile()['references'][0]['finish'])

    def test_single_entrant_without_played_final_has_no_appearance_or_title(self):
        self.main, self.scheduled, self.calendar = tournament(count=1)
        self.live()
        self.assertEqual((0, 0, None), tuple(self.summary()[k] for k in ('appearances', 'championships', 'best_finish')))
        self.assertEqual('不戦勝（決勝未実施）', self.profile()['references'][0]['resolution'])

    def test_unknown_date_does_not_guess_participation_or_result(self):
        for m in self.scheduled.matches.values():
            if 'A' in (m.team1_id, m.team2_id):
                m.date_source = ''
        self.assertEqual((0, 0, None), tuple(self.summary()[k] for k in ('appearances', 'championships', 'best_finish')))
        self.assertEqual('実施・日付未確定', self.profile()['references'][0]['label'])

    def test_unknown_final_date_preserves_confirmed_first_appearance(self):
        final = next(m for m in self.scheduled.matches.values() if m.round_no == 5)
        final.date_source = ''
        self.assertEqual((1, 0, None), tuple(self.summary()[k] for k in ('appearances', 'championships', 'best_finish')))

    def test_elimination_before_transfer_belongs_to_old_coach_not_final_day_coach(self):
        self.book.update(date(2027, 4, 1), self.repo)
        for slot, label in [(16, '準優勝'), (8, 'ベスト4'), (4, 'ベスト8'), (1, '1回戦敗退')]:
            with self.subTest(finish=label):
                self.main, self.scheduled, self.calendar = tournament(a_slot=slot)
                self.live()
                self.assertEqual(label, self.summary()['best_finish'])
                self.assertIsNone(self.summary(self.book.for_school('A').coach_id)['best_finish'])

    def test_same_tournament_at_two_schools_counts_only_once_for_person(self):
        self.book.update(date(2027, 4, 1), self.repo)
        new_school = self.book.coaches['COACH-A'].school_id
        a = next(r for r in self.records() if r['school_id'] == 'A')
        a.update(finish='準優勝', depth=50, decision_date='2027-04-03')
        b = {**a, 'school_id': new_school, 'first_game_date': '2027-04-03',
             'finish': '優勝', 'depth': 100}
        self.archive.store_closed_season(2026, b'snapshot', {}, school_records=[a, b])
        self.data.state.seasons = {}
        self.assertEqual((1, 1, '優勝'), tuple(self.summary()[k] for k in ('appearances', 'championships', 'best_finish')))
        self.assertEqual(2, len(self.profile()['records']))

    def test_all_seven_categories_and_qualifier_not_double_counted(self):
        from phase2_engine.competition_records import CATEGORIES
        for kind, category in CATEGORIES.items():
            with self.subTest(kind=kind):
                self.repo.competitions[CID]['competition_type'] = kind
                s = self.summary(key=category)
                self.assertEqual(1, s['championships'])
                self.assertEqual(1 if 'koshien' in category else None, s['appearances'])
        self.repo.competitions[CID] = dict(META)
        pre = replace(next(iter(self.scheduled.matches.values())), match_id='FAKE-QUALIFIER',
                      stage_code='QUAL', match_date='2027-03-01')
        self.scheduled.matches[pre.match_id] = pre
        self.assertEqual('2027-03-26', next(r for r in self.records() if r['school_id'] == 'A')['first_game_date'])
        self.assertEqual(1, self.summary()['appearances'])

    def test_archive_reload_rename_same_name_and_readonly(self):
        self.archive.store_closed_season(2026, b'snapshot', {}, school_records=self.records())
        self.data.state.seasons = {}
        before = self.profile()
        self.book = pickle.loads(pickle.dumps(self.book))
        self.data.state.coaches = self.book
        self.assertEqual(before, self.profile())
        for cid, coach in list(self.book.coaches.items()):
            self.book.coaches[cid] = replace(coach, display_name='架空 同姓同名')
        self.assertNotEqual(self.profile(), self.profile('COACH-B'))
        self.data.names.edits.set_info('A', '2027-04-01', {'short_name': '架空改称校'})
        r = self.profile()['records'][0]
        self.assertEqual(('A', '架空校A', '架空改称校'), tuple(r[k] for k in ('school_id', 'school_name', 'current_school_name')))
        saved, db = pickle.dumps(self.book.__getstate__()), self.archive.db_path.read_bytes()
        with patch.object(self.book, 'update', side_effect=AssertionError('人事を実行しない')):
            self.profile()
        self.assertEqual(saved, pickle.dumps(self.book.__getstate__()))
        self.assertEqual(db, self.archive.db_path.read_bytes())

    def test_live_year_replaces_archived_future_results_without_duplicates(self):
        self.archive.store_closed_season(2026, b'snapshot', {}, school_records=self.records())
        self.assertEqual(1, len(self.profile()['records']))
        self.scheduled.is_complete = False
        self.assertIsNone(self.summary()['best_finish'])
        self.data.state.seasons[2026].competitions = {}
        self.assertEqual([], self.profile()['records'])

    def test_read_does_not_change_runtime_or_call_result_generation(self):
        before = pickle.dumps((self.book.__getstate__(), self.main, self.scheduled.matches))
        with patch.object(self.main, 'to_competition_run', side_effect=AssertionError('順位の再抽選をしない')):
            self.profile()
        self.assertEqual(before, pickle.dumps((self.book.__getstate__(), self.main, self.scheduled.matches)))



if __name__ == '__main__':
    unittest.main()
