"""監督の采配は選考・交代だけへ作用し、能力と公式戦規定を変えない。"""
from dataclasses import replace
from datetime import date
import pickle
from types import SimpleNamespace
import unittest

from game_core.coaches import CoachEvent, CoachTactics
from game_core.match_contract import MatchSimulationInput, TeamMatchInput, validate_match_simulation_result
from game_core.match_simulator import GameRules, MatchSimulator
from game_core.team_strength import TeamStrengthGenerator, validate_team_strength_snapshot
from game_core.tournament_bridge import AbilityMatchResolver
from test_coach_intake import books, annual
from test_stage13b3_team_strength import make_roster_abilities


def policy(value=50, selection=50):
    f=books(50)
    annual(f,2027)
    c=f[1].coaches['C-FAKE-A']
    f[1].coaches[c.coach_id]=replace(c,pitching_change=value,player_selection=selection)
    return f[1].tactics_for('FAKE-A',date(2027,4,1))


def resolver(f, day):
    repo,coaches,rep,rosters=f
    rosters.bind(repo.team)
    members=lambda cid,sid: SimpleNamespace(players=rosters.roster(2026,sid).players)
    r=AbilityMatchResolver(repo,member_provider=members,team_generation_seed=7)
    r.ability_generator.source=rosters
    r.season_state=SimpleNamespace(current_date=day,pitch_log={})
    r.rules_for=lambda *args: GameRules(tiebreak_start_inning=10)
    return r


class CoachTacticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator=TeamStrengthGenerator()
        cls.sim=MatchSimulator()
        cls.teams=[]
        for sid in ('FAKE-A','FAKE-B'):
            players=tuple(replace(p,player_id=sid+"-"+p.player_id) for p in make_roster_abilities(school_id=sid))
            cls.teams.append(TeamMatchInput(sid,cls.generator.generate(players),players))

    def match(self,i):
        return MatchSimulationInput(f'MATCH-{i}','FAKE-CUP',2026,2026100701,*self.teams)

    def test_config_neutral_ranges_and_start_date(self):
        self.assertEqual(CoachTactics(),policy())
        self.assertEqual(CoachTactics(.94,1,.3),policy(80,80))
        self.assertEqual(CoachTactics(1.06,-1,-.3),policy(20,20))
        self.assertEqual(CoachTactics(.9,1,.5),policy(100,100))
        f=books();annual(f,2027)
        c=f[1].coaches['C-FAKE-A'];f[1].coaches[c.coach_id]=replace(c,pitching_change=100,player_selection=100)
        for d in (date(2026,7,1),date(2027,3,31)):
            self.assertEqual(CoachTactics(),f[1].tactics_for('FAKE-A',d))
        self.assertEqual(CoachTactics(),f[1].tactics_for('ABSENT',date(2027,4,1)))
        with self.assertRaises(ValueError):f[1].tactics_for('FAKE-A',date(2028,4,1))

    def test_neutral_identical_lineup_strength_full_match_and_stats(self):
        neutral=policy()
        for t in self.teams:
            self.assertEqual(t.team_strength,self.generator.generate(t.player_abilities,selection_grade_bias=neutral.selection_grade_bias))
        for i in range(12):
            inp=self.match(i)
            self.assertEqual(self.sim.simulate(inp).to_dict(),self.sim.simulate(inp,tactics={s:neutral for s in ('FAKE-A','FAKE-B')}).to_dict())

    def test_pitching_80_is_earlier_in_actual_games(self):
        totals={}
        for value in (20,80):
            pitches=outs=pitchers=0
            tactics={t.school_id:policy(value) for t in self.teams}
            for i in range(80):
                inp=self.match(i)
                result=self.sim.simulate(inp,tactics=tactics)
                validate_match_simulation_result(result,inp)
                for sid in ('FAKE-A','FAKE-B'):
                    rows=[p for p in result.pitcher_stats if p.school_id==sid and p.batters_faced]
                    pitches+=rows[0].pitches;outs+=rows[0].outs_recorded;pitchers+=len(rows)
            totals[value]=(pitches,outs,pitchers)
        self.assertLess(totals[80][0],totals[20][0])
        self.assertLess(totals[80][1],totals[20][1])
        self.assertGreater(totals[80][2],totals[20][2])

    def equal_players(self):
        players=list(self.teams[0].player_abilities)
        # 同じ守備位置内で実能力を等しくし、1年と3年を比べる。
        for pos in {p.primary_position for p in players}:
            base=next(p for p in players if p.primary_position==pos)
            indexes=[i for i,p in enumerate(players) if p.primary_position==pos]
            for j,i in enumerate(indexes):
                players[i]=replace(base,player_id=players[i].player_id,academic_year=1 if j==0 else 3)
        return tuple(players)

    def test_selection_youth_seniority_and_pitcher_consistency(self):
        players=self.equal_players();before=tuple(p.to_dict() for p in players)
        ages=[]
        for v in (20,80):
            strength=self.generator.generate(players,selection_grade_bias=policy(selection=v).selection_grade_bias)
            validate_team_strength_snapshot(strength)
            by_id={p.player_id:p for p in players}
            ages.append(sum(by_id[p].academic_year for p in strength.starting_lineup.starter_ids))
            self.assertEqual(strength.starting_lineup.player_for_position('P'),strength.pitching_staff.ace_player_id)
            self.assertEqual(9,len(set(strength.starting_lineup.starter_ids)))
            for entry in strength.starting_lineup.entries:
                self.assertEqual(entry.defensive_position,by_id[entry.player_id].primary_position)
        self.assertLess(ages[1],ages[0]);self.assertEqual(before,tuple(p.to_dict() for p in players))

    def test_large_ability_gap_is_not_overturned_and_no_direct_bonus(self):
        players=self.equal_players()
        players=tuple(replace(p,contact=1,power=1,arm_strength=1,fielding=1,throwing=1,
                              control=1 if p.primary_position=='P' else p.control,
                              stuff=1 if p.primary_position=='P' else p.stuff)
                      if p.academic_year==1 else p for p in players)
        neutral=self.generator.generate(players)
        for v in (1,100):
            actual=self.generator.generate(players,selection_grade_bias=policy(selection=v).selection_grade_bias)
            self.assertEqual(neutral,actual)

    def test_near_equal_pitchers_keep_quality_order_contract(self):
        players=self.equal_players()
        # 旧テストの全員同点では見つからなかった、わずかな実能力差。
        older=next(p for p in players if p.primary_position=='P' and p.academic_year==3)
        players=tuple(replace(p,control=p.control+1) if p.player_id==older.player_id else p for p in players)
        for v in (1,20,50,80,100):
            strength=self.generator.generate(players,selection_grade_bias=policy(selection=v).selection_grade_bias)
            validate_team_strength_snapshot(strength)
            self.assertEqual(older.player_id,strength.starting_lineup.player_for_position('P'))
            qualities=[p.quality for p in strength.pitching_staff.entries]
            self.assertEqual(sorted(qualities,reverse=True),qualities)

    def test_pitch_allowance_has_priority_over_both_tendencies(self):
        inp=self.match(180)
        allowances={p.player_id:80 for t in self.teams for p in t.player_abilities}
        for v in (20,80):
            r=self.sim.simulate(inp,pitch_allowances=allowances,tactics={t.school_id:policy(v) for t in self.teams})
            validate_match_simulation_result(r,inp)
            # 上限を越えた打席までは許可される。次の打席へ進まない。
            self.assertTrue(all(s.pitches<=85 for s in r.pitcher_stats))
            self.assertTrue(all(s.batters_faced>0 for s in r.pitcher_stats))

    def test_dated_transfer_and_cache_in_cross_year_competition(self):
        f=books();annual(f,2027)
        book=f[1]
        for sid,value in (('FAKE-A',80),('FAKE-B',20)):
            c=book.coaches['C-'+sid];book.coaches[c.coach_id]=replace(c,pitching_change=value,player_selection=value)
        old=book.tactics_for('FAKE-A',date(2027,4,1))
        r=resolver(f,date(2027,4,1))
        kwargs=dict(school_id='FAKE-A',reference_year=2026,generation_seed=7,competition_id='MARCH-CUP')
        before=r.team_input(**kwargs)
        book.events.extend([CoachEvent('2027-04-15','transfer','C-FAKE-A','FAKE-A','FAKE-B'),CoachEvent('2027-04-15','transfer','C-FAKE-B','FAKE-B','FAKE-A')])
        for cid,sid in (('C-FAKE-A','FAKE-B'),('C-FAKE-B','FAKE-A')):
            book.coaches[cid]=replace(book.coaches[cid],school_id=sid,appointment_year=2027)
        book._rebuild_indexes()
        self.assertEqual(old,book.tactics_for('FAKE-A',date(2027,4,14)))
        self.assertEqual(old,book.tactics_for('FAKE-B',date(2027,4,15)))
        r.season_state.current_date=date(2027,4,15)
        after=r.team_input(**kwargs)
        self.assertIsNot(before,after)
        self.assertEqual(self.generator.generate(after.player_abilities,selection_grade_bias=-.3),after.team_strength)
        r.season_state.current_date=date(2027,4,14)
        self.assertEqual(before,r.team_input(**kwargs))

    def test_2026_bridge_and_stats_identical_with_or_without_coaches(self):
        f=books()
        for cid,c in list(f[1].coaches.items()):
            f[1].coaches[cid]=replace(c,pitching_change=100,player_selection=100)
        # 新入生・成長は両側同じ。2026年の采配参照だけを有無で比較する。
        for sid in f[0].schools:f[3].roster(2026,sid)
        left=resolver(f,date(2026,7,5))
        other=pickle.loads(pickle.dumps(f));other[3].coaches=None
        right=resolver(other,date(2026,7,5))
        args=dict(match_id='INITIAL',competition_id='FAKE-CUP',reference_year=2026,
                  generation_seed=7,team1='FAKE-A',team2='FAKE-B')
        self.assertEqual(left(**args),right(**args))
        self.assertEqual(left.season_state.pitch_log,right.season_state.pitch_log)

    def test_production_bridge_injury_save_resume_and_reproducibility(self):
        f=books();annual(f,2027)
        for cid,c in list(f[1].coaches.items()):f[1].coaches[cid]=replace(c,pitching_change=80,player_selection=80)
        r=resolver(f,date(2027,4,5))
        inp=r.team_input(school_id='FAKE-A',reference_year=2026,generation_seed=7,competition_id='MARCH-CUP')
        from game_core.injuries import Injury
        hurt=inp.team_strength.starting_lineup.starter_ids[0]
        player=next(p for p in f[3].roster(2026,'FAKE-A').players if p.player_id==hurt)
        f[3].state(player).injuries.append(Injury(date(2027,4,2),18,1))
        r.clear_cache()
        inp=r.team_input(school_id='FAKE-A',reference_year=2026,generation_seed=7,competition_id='MARCH-CUP')
        self.assertNotIn(hurt,inp.team_strength.starting_lineup.starter_ids)
        self.assertNotIn(hurt,[p.player_id for p in inp.team_strength.pitching_staff.entries])
        saved=pickle.dumps(f)
        args=dict(match_id='RESTART',competition_id='MARCH-CUP',reference_year=2026,generation_seed=7,team1='FAKE-A',team2='FAKE-B')
        a=r(**args)
        loaded=pickle.loads(saved);b=resolver(loaded,date(2027,4,5))(**args)
        self.assertEqual(a,b)
        self.assertEqual(f[1].tactics_config,loaded[1].tactics_config)
        from test_coach_growth import states
        self.assertEqual(states(f[3]),states(loaded[3]))


if __name__=='__main__':unittest.main()
