"""育成力は対象月の練習だけへ適用し、人物・成長特性・試合経験を変えない。"""
from dataclasses import replace
from datetime import date
import pickle
import random
import unittest

from game_core.coaches import CoachEvent
from game_core.injuries import Injury
from game_core.player_growth import PlayerGrowth, POTENTIAL_SCALE, SCALARS
from test_coach_intake import books, annual
from test_player_growth import _values, MONTHS

CONTACT = SCALARS.index('contact')
VELOCITY = SCALARS.index('velocity_kmh')


def fixture(development=80, *, zero=False):
    f = books(50)
    repo, coaches, _, rosters = f
    for cid, coach in list(coaches.coaches.items()):
        coaches.coaches[cid] = replace(coach, development=development)
    if zero:
        coaches.growth_config['max_abs_delta'] = 0.0
    rosters.school_ids = tuple(repo.schools)
    for sid in repo.schools:
        rosters.roster(2026, sid)
    return f


def states(book):
    return {sid: {key: (bytes(s.values), s.growth_type, s.potential, s.games,
                        s.season_games, list(s.injuries)) for key, s in rows.items()}
            for sid, rows in book._states.items()}


class CoachGrowthTests(unittest.TestCase):
    def test_configured_neutral_linear_and_clipped_multipliers(self):
        for development, expected in ((1,.9),(20,.91),(50,1.0),(80,1.09),(100,1.1)):
            f = fixture(development)
            annual(f, 2027)
            cid, ability, multiplier = f[1].practice_for('FAKE-A', date(2027,4,30))
            self.assertEqual(('C-FAKE-A', development, expected), (cid,ability,multiplier))
            self.assertEqual(1.0, f[1].practice_for('FAKE-A', date(2027,3,31))[2])

    def test_neutral_preserves_values_and_rng_consumption(self):
        model = PlayerGrowth()
        f = fixture(50)
        annual(f, 2027)
        multiplier = f[1].practice_for('FAKE-A', date(2027,4,1))[2]
        for position in ('SS','P','C'):
            for grade in (1,2,3):
                a = _values(60, pitcher=position=='P'); b=bytearray(a)
                if position=='C':
                    a[11:13]=b[11:13]=bytes((60,60))
                left, right = random.Random(17), random.Random(17)
                for month in MONTHS:
                    kwargs = dict(position=position,grade=grade,type_index=1,
                                  potential=83,games=3,month=month)
                    model.grow(a,rng=left,**kwargs)
                    model.grow(b,rng=right,practice_multiplier=multiplier,**kwargs)
                self.assertEqual(a,b)
                self.assertEqual(left.getstate(),right.getstate())

    def test_high_development_increases_practice_growth_in_all_grades(self):
        model = PlayerGrowth()
        for grade in (1,2,3):
            totals = {m: [0,0,0] for m in (.91,1.09)}
            for seed in range(300):
                for multiplier in totals:
                    v = _values(50,pitcher=True); rng=random.Random(seed)
                    for month in MONTHS:
                        model.grow(v,position='P',grade=grade,type_index=1,
                                   potential=POTENTIAL_SCALE,games=0,month=month,
                                   rng=rng,practice_multiplier=multiplier)
                    for i,value in enumerate((v[CONTACT]-50,v[VELOCITY]-140,v[-3]-50)):
                        totals[multiplier][i]+=value
            for low,high in zip(totals[.91],totals[1.09]):
                self.assertGreater(high,low)

    def test_match_experience_is_not_multiplied(self):
        model = PlayerGrowth()
        for position in ('SS','P','C'):
            results=[]; random_states=[]
            for multiplier in (.9,1.0,1.1):
                v=_values(50,pitcher=position=='P'); rng=random.Random(9)
                for month in MONTHS:
                    model.grow(v,position=position,grade=2,type_index=1,
                               potential=0,games=5,month=month,rng=rng,
                               practice_multiplier=multiplier)
                results.append(v);random_states.append(rng.getstate())
            self.assertEqual(results[0],results[1]);self.assertEqual(results[1],results[2])
            self.assertEqual(random_states[0],random_states[2])
            self.assertGreater(results[0][CONTACT],50)

    def test_2026_and_march_2027_are_unchanged(self):
        a,b=fixture(100),fixture(100,zero=True)
        for month in range(4,13):
            for f in (a,b): f[3].grow(date(2026,month,28))
            self.assertEqual(states(a[3]),states(b[3]))
        for f in (a,b):
            annual(f,2027)
            for month in (1,2,3): f[3].grow(date(2027,month,28))
        self.assertEqual(states(a[3]),states(b[3]))
        for f in (a,b): f[3].grow(date(2027,4,30))
        self.assertNotEqual(states(a[3]),states(b[3]))
        for sid,rows in a[3]._states.items():
            for key,s in rows.items():
                other=b[3]._states[sid][key]
                self.assertEqual((s.growth_type,s.potential),(other.growth_type,other.potential))

    def test_april_transfer_uses_old_person_in_march_and_new_person_in_april(self):
        f=fixture(50);repo,coaches,_,book=f
        coaches.coaches['C-FAKE-A']=replace(coaches.coaches['C-FAKE-A'],development=80)
        coaches.config['transfer']['public']=[[1,1.0]]
        initial=states(book)
        book.grow(date(2026,12,31))
        self.assertNotEqual(initial,states(book))
        before=states(book)
        annual(f,2027)
        destination=coaches.coaches['C-FAKE-A'].school_id
        self.assertNotEqual('FAKE-A',destination)
        self.assertEqual(('C-FAKE-A',80,1.0),coaches.practice_for('FAKE-A',date(2027,3,31)))
        self.assertEqual(('C-FAKE-A',80,1.09),coaches.practice_for(destination,date(2027,4,30)))
        self.assertEqual(50,coaches.practice_for('FAKE-A',date(2027,4,1))[1])
        self.assertEqual(before,states(book))
        self.assertEqual(80,coaches.for_school('FAKE-A',date(2027,3,1)).development)

    def test_month_start_rule_even_if_a_future_midmonth_transfer_is_added(self):
        f=fixture(50);annual(f,2027);coaches=f[1]
        for sid,value in (('FAKE-A',80),('FAKE-B',20)):
            cid='C-'+sid;coaches.coaches[cid]=replace(coaches.coaches[cid],development=value)
        for old,new in (('FAKE-A','FAKE-B'),('FAKE-B','FAKE-A')):
            cid='C-'+old
            coaches.events.append(CoachEvent('2027-04-15','transfer',cid,old,new,'2020-04-01'))
            coaches.coaches[cid]=replace(coaches.coaches[cid],school_id=new,appointment_year=2027)
        coaches._rebuild_indexes()
        self.assertEqual(('C-FAKE-A',80,1.09),coaches.practice_for('FAKE-A',date(2027,4,30)))
        self.assertEqual(('C-FAKE-B',20,.91),coaches.practice_for('FAKE-A',date(2027,5,1)))

    def test_injury_edit_and_resume_preserve_monthly_results_without_double_growth(self):
        f=fixture(80);annual(f,2027);repo,coaches,rep,book=f
        player=book.roster(2027,'FAKE-A').players[0]
        edited=replace(book.base_ability(player),contact=72,power=74)
        book.edit_abilities([player],[edited],day='2027-04-02',source='test')
        book.state(player).injuries.append(Injury(date(2027,4,1),30,1))
        potential=(book.state(player).growth_type,book.state(player).potential)
        loaded=pickle.loads(pickle.dumps(book));loaded.bind(repo.team)
        for b in (book,loaded):
            b.grow(date(2027,4,30))
            self.assertEqual(72,b.base_ability(player).contact) # 全休月の練習は0
            b.set_today(date(2027,5,1))
            self.assertIsNotNone(b.state(player).recovering(date(2027,5,1)))
            self.assertLess(b.ability(player).contact,b.base_ability(player).contact)
            snapshot=states(b);version=b.version
            b.grow(date(2027,4,1))
            self.assertEqual(snapshot,states(b));self.assertEqual(version,b.version)
            b.grow(date(2027,5,31))
            b.set_today(date(2027,5,31))
            self.assertEqual(b.base_ability(player).contact,b.ability(player).contact)
        self.assertEqual(states(book),states(loaded))
        self.assertEqual(potential,(book.state(player).growth_type,book.state(player).potential))
        self.assertEqual(coaches.growth_config,loaded.coaches.growth_config)
        again=pickle.loads(pickle.dumps(loaded));again.bind(repo.team)
        before=states(again);again.grow(date(2027,5,30))
        self.assertEqual(before,states(again))

    def test_caps_and_headroom_are_preserved(self):
        model=PlayerGrowth();v=_values(97,pitcher=True);v[VELOCITY]=159
        for year in range(3):
            for month in MONTHS:
                model.grow(v,position='P',grade=3,type_index=1,potential=224,
                           games=10,month=month,rng=random.Random(year*12+month),practice_multiplier=1.1)
        self.assertLessEqual(v[CONTACT],100);self.assertLessEqual(v[VELOCITY],model._velocity_head[0])
        self.assertLessEqual(v[-3],100);self.assertLessEqual(v[-2],100)
        self.assertLess(model._headroom(95,*model._head),model._headroom(50,*model._head))

    def test_unupdated_personnel_does_not_guess_future_coach(self):
        f=fixture(80)
        with self.assertRaisesRegex(ValueError,'not finalized'):
            f[1].practice_for('FAKE-A',date(2027,4,1))
