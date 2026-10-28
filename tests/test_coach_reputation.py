"""監督本人の年度評価、確定時期、人事・入学との順序、保存再開。"""
from dataclasses import replace
from datetime import date
import pickle
import random
from types import SimpleNamespace
import unittest

from phase2_engine.career_state import CareerState
from test_coach_personnel import fixture
from test_competition_records import tournament, CID, META


class CoachReputationTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.book = fixture()
        self.repo.competitions = {CID: dict(META)}
        self.main, self.scheduled, self.calendar = tournament()
        self.season = SimpleNamespace(repo=self.repo, competitions={CID: self.scheduled},
                                     calendar_rows={CID: self.calendar})

    @property
    def ratings(self):
        return self.book.annual_reputation

    def collect(self, day='2027-03-31'):
        self.ratings.collect(self.book, {2026: self.season}, date.fromisoformat(day))

    def update(self, year=2027):
        return self.ratings.update(self.book, date(year, 4, 1))

    def test_national_champion_rises_with_bounded_change_without_double_rewards(self):
        self.collect()
        self.update()
        row = self.ratings.history['COACH-A'][0]
        self.assertEqual((50, 52, 100), (row.before, row.after, row.target))
        self.assertEqual({'A': {'wins': 5, 'losses': 0}}, row.schools)
        self.assertEqual(('2026-04-01', '2027-03-31'), (row.period_start, row.period_end))
        self.assertEqual({'appearance', 'finish'}, {a['kind'] for a in row.achievements})
        self.assertEqual({}, self.ratings.pending)

    def test_prefectural_regional_and_national_achievements_are_distinct(self):
        targets = []
        for kind in ('spring_prefectural', 'spring_regional', 'national_invitational'):
            self.setUp()
            self.repo.competitions[CID]['competition_type'] = kind
            self.collect(); self.update()
            targets.append(self.ratings.history['COACH-A'][0].target)
        self.assertLess(targets[0], targets[1])
        self.assertLess(targets[1], targets[2])

    def test_match_signal_is_shrunk_and_does_not_reward_game_count_at_equal_win_rate(self):
        for wins, losses, expected in ((20, 0, 51), (0, 20, 49), (1, 1, 50), (100, 100, 50)):
            with self.subTest(wins=wins, losses=losses):
                _, book = fixture()
                r = book.annual_reputation
                r.pending = {2026: {'COACH-A': {'schools': {'A': {'wins': wins, 'losses': losses}}, 'achievements': []}}}
                r.update(book, date(2027, 4, 1))
                self.assertEqual(expected, book.coaches['COACH-A'].reputation)

    def test_no_activity_preserves_reputation_and_does_not_copy_every_person(self):
        before = dict(self.book.coaches)
        self.update()
        self.assertEqual(before, self.book.coaches)
        self.assertEqual({}, self.ratings.history)
        self.assertEqual(2027, self.ratings.updated_year)

    def test_walkovers_unknown_dates_and_prestart_are_not_evaluated(self):
        for case in ('walkover', 'unknown', 'prestart'):
            with self.subTest(case=case):
                self.setUp()
                for m in self.scheduled.matches.values():
                    if case == 'walkover':m.score_source = 'walkover'
                    if case == 'unknown':m.date_source = ''
                    if case == 'prestart':m.match_date = m.completed_on = '2026-03-31'
                self.collect();self.update()
                self.assertEqual(50, self.book.coaches['COACH-A'].reputation)
                self.assertEqual({}, self.ratings.history)

    def test_unfinished_appearance_is_evaluated_but_title_is_not_anticipated(self):
        self.scheduled.is_complete = False
        self.collect();self.update()
        row = self.ratings.history['COACH-A'][0]
        self.assertEqual(70, row.target)
        self.assertEqual(['appearance'], [a['kind'] for a in row.achievements])

    def test_cross_april_title_uses_new_coach_and_next_confirmation_period(self):
        self.main, self.scheduled, self.calendar = tournament(days={5: '2027-04-03'})
        final = next(m for m in self.scheduled.matches.values() if m.round_no == 5)
        del self.scheduled.matches[final.match_id]
        self.scheduled.is_complete = False
        self.season.competitions[CID] = self.scheduled
        self.collect();self.update()
        self.book.update(date(2027,4,1),self.repo)
        self.book.finalize_intake(2027)
        new = self.book.for_school('A').coach_id
        self.scheduled.matches[final.match_id] = final
        self.scheduled.is_complete = True
        self.collect('2027-04-03')
        self.update(2028)
        self.assertEqual(70, self.ratings.history['COACH-A'][0].target)
        row = self.ratings.history[new][-1]
        self.assertEqual((2028, 100, 'A'), (row.update_year, row.target, row.achievements[0]['school_id']))
        self.assertEqual(('2027-04-03', '2027-04-03'),
                         (row.achievements[0]['commanded_on'], row.achievements[0]['confirmed_on']))

    def test_late_confirmed_march_elimination_stays_with_old_coach_and_school(self):
        self.main, self.scheduled, self.calendar = tournament(a_slot=4, days={5:'2027-04-03'})
        final = next(m for m in self.scheduled.matches.values() if m.round_no == 5)
        del self.scheduled.matches[final.match_id]
        self.scheduled.is_complete=False
        self.season.competitions[CID]=self.scheduled
        self.collect();self.update()
        self.book.update(date(2027,4,1),self.repo)
        self.scheduled.matches[final.match_id]=final;self.scheduled.is_complete=True
        self.collect('2027-04-03');self.update(2028)
        row=self.ratings.history['COACH-A'][-1]
        self.assertEqual((2028,80), (row.update_year,row.target))
        self.assertEqual(('A','2027-03-28','2027-04-03'), tuple(row.achievements[0][k] for k in ('school_id','commanded_on','confirmed_on')))
        self.assertNotEqual('A',self.book.coaches['COACH-A'].school_id)

    def test_duplicate_collect_and_update_do_not_change_any_state(self):
        self.collect();self.update()
        before=pickle.dumps(self.book.__getstate__())
        self.collect()
        self.assertFalse(self.update())
        self.assertEqual(before,pickle.dumps(self.book.__getstate__()))

    def test_save_load_resume_is_identical_and_random_state_is_untouched(self):
        self.scheduled.is_complete=False
        before=random.getstate()
        self.collect()
        loaded=pickle.loads(pickle.dumps(self.book))
        self.scheduled.is_complete=True
        for book in (self.book,loaded):
            book.annual_reputation.collect(book,{2026:self.season},date(2027,3,31))
            book.annual_reputation.update(book,date(2027,4,1))
            book.update(date(2027,4,1),self.repo);book.finalize_intake(2027)
        self.assertEqual(self.book.__getstate__(),loaded.__getstate__())
        self.assertEqual(before,random.getstate())

    def test_previous_intake_is_immutable_after_next_assessment_and_transfer(self):
        self.collect();self.update()
        self.book.update(date(2027,4,1),self.repo);self.book.finalize_intake(2027)
        before={s:self.book.intake_for(s,2027) for s in self.repo.schools}
        for m in self.scheduled.matches.values():
            m.match_date=m.completed_on='2027-07-01'
        self.ratings.collect(self.book,{2027:self.season},date(2027,7,1))
        self.update(2028)
        self.book.update(date(2028,4,1),self.repo);self.book.finalize_intake(2028)
        self.assertEqual(before,{s:self.book.intake_for(s,2027) for s in self.repo.schools})
        for s in self.repo.schools:
            self.assertEqual(self.book.for_school(s).reputation,self.book.intake_for(s,2028)[1])

    def test_boundary_updates_old_coach_before_retirement_and_uses_new_successor_initial_rating(self):
        self.book.coaches['COACH-A']=replace(self.book.coaches['COACH-A'],birth_year=1940)
        self.season.start_date=self.season.current_date=date(2027,3,31)
        self.season.play_today=lambda:[]
        self.season.annual_templates={}
        self.season.calendar_rows={}
        career=CareerState({2026:self.season},current_date=date(2027,3,31),coaches=self.book)
        career.next_day()
        old=self.book.coaches['COACH-A'];new=self.book.for_school('A')
        self.assertEqual((52,'2027-04-01'),(old.reputation,old.retired_on))
        self.assertNotEqual(old.coach_id,new.coach_id)
        self.assertNotIn(new.coach_id,self.ratings.history)
        self.assertEqual(new.reputation,self.book.intake_for('A',2027)[1])

    def test_disabled_update_preserves_all_ratings_and_configuration_rejects_invalid_values(self):
        self.ratings.config['enabled']=False
        self.collect();self.update()
        self.assertEqual(50,self.book.coaches['COACH-A'].reputation)
        for key,value in (('response',float('nan')),('match_prior_games',0),('max_annual_change',2.5)):
            _, book=fixture()
            book.annual_reputation.config[key]=value
            with self.assertRaises(ValueError):book.annual_reputation._validate()


if __name__=='__main__':unittest.main()
