"""監督の采配は選考・交代だけへ作用し、能力と公式戦規定を変えない。"""
from dataclasses import replace
from datetime import date
import pickle
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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
    r=AbilityMatchResolver(repo,member_provider=members,team_generation_seed=7,dh_enabled=False)
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

    def test_neutral_preserves_legacy_zero_run_hook_setting(self):
        sim=MatchSimulator()
        pitcher=next(p for p in self.teams[0].player_abilities if p.primary_position=='P')
        minimum=int(sim.params['pitching_usage']['minimum_bf_before_change'])
        with patch.dict(sim.params['pitching_usage'],runs_allowed_quick_hook=0):
            for tactics in (CoachTactics(),policy(50)):
                self.assertFalse(sim._should_change_pitcher(pitcher=pitcher,
                    stats={'batters_faced':minimum-1,'runs_allowed':0},starter=True,
                    has_next=True,tactics=tactics))
                self.assertTrue(sim._should_change_pitcher(pitcher=pitcher,
                    stats={'batters_faced':minimum,'runs_allowed':0},starter=True,
                    has_next=True,tactics=tactics))

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



class StarterUsageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        CoachTacticsTests.setUpClass.__func__(cls)

    match = CoachTacticsTests.match

    def pitcher(self, stamina=80):
        return replace(next(p for p in self.teams[0].player_abilities
                            if p.primary_position == 'P'), stamina=stamina)

    def test_stamina_gives_a_good_starter_room_to_finish(self):
        stats = {'batters_faced': 30, 'runs_allowed': 1}
        self.assertTrue(self.sim._should_change_pitcher(
            pitcher=self.pitcher(20), stats=stats, starter=True, has_next=True))
        self.assertFalse(self.sim._should_change_pitcher(
            pitcher=self.pitcher(90), stats=stats, starter=True, has_next=True))

    def test_six_runs_still_trigger_an_early_hook(self):
        self.assertTrue(self.sim._should_change_pitcher(
            pitcher=self.pitcher(90), stats={'batters_faced': 8, 'runs_allowed': 6},
            starter=True, has_next=True))
        self.assertFalse(self.sim._should_change_pitcher(
            pitcher=self.pitcher(90), stats={'batters_faced': 2, 'runs_allowed': 6},
            starter=True, has_next=True))
        self.assertFalse(self.sim._should_change_pitcher(
            pitcher=self.pitcher(90), stats={'batters_faced': 50, 'runs_allowed': 6},
            starter=True, has_next=False))

    def test_good_starters_finish_nine_innings_with_relief_available(self):
        choices = iter(['home_run'] + ['field_out'] * 100)
        with patch.object(self.sim, '_weighted_choice', side_effect=lambda *_: next(choices)):
            teams = []
            for team in self.teams:
                players = tuple(replace(p, stamina=80) if p.primary_position == 'P' else p
                                for p in team.player_abilities)
                teams.append(TeamMatchInput(team.school_id, self.generator.generate(players), players))
            inp = replace(self.match(900), team1=teams[0], team2=teams[1])
            result = self.sim.simulate(inp)
        validate_match_simulation_result(result, inp, config_dir=self.sim.config_dir)
        self.assertEqual(9, result.last_inning)
        self.assertEqual(2, len(result.pitcher_stats))
        self.assertTrue(all(p.outs_recorded == 27 for p in result.pitcher_stats))
        self.assertTrue(all(len(t.team_strength.pitching_staff.entries) > 1 for t in self.teams))
        self.assertTrue(all(not p.changes for p in result.team_participation))

    def test_bad_start_is_hooked_before_recording_an_out(self):
        choices = iter(['home_run'] * 6 + ['field_out'] * 100)
        with patch.object(self.sim, '_weighted_choice', side_effect=lambda *_: next(choices)):
            inp = self.match(901)
            result = self.sim.simulate(inp)
        validate_match_simulation_result(result, inp, config_dir=self.sim.config_dir)
        rows = [p for p in result.pitcher_stats if p.school_id == self.teams[1].school_id]
        self.assertGreater(len(rows), 1)
        self.assertEqual(0, rows[0].outs_recorded)
        self.assertEqual(6, rows[0].runs_allowed)
        self.assertEqual(6, rows[0].batters_faced)

    def test_pitch_limit_overrides_a_good_starter_and_prevents_reentry(self):
        choices = iter(['home_run'] + ['field_out'] * 100)
        team = self.teams[0]
        with patch.object(self.sim, '_weighted_choice', side_effect=lambda *_: next(choices)):
            inp = self.match(902)
            result = self.sim.simulate(inp, pitch_allowances={p.player_id: 30
                for p in team.team_strength.pitching_staff.entries})
        validate_match_simulation_result(result, inp, config_dir=self.sim.config_dir)
        rows = [p for p in result.pitcher_stats if p.school_id == team.school_id]
        self.assertGreater(len(rows), 1)
        self.assertLessEqual(rows[0].pitches, 35)
        order = [e.pitcher_id for e in result.events if e.defense_school_id == team.school_id]
        switches = [pid for i, pid in enumerate(order) if i == 0 or pid != order[i-1]]
        self.assertEqual(len(switches), len(set(switches)))

    def test_pitching_quality_affects_how_many_outs_the_starter_gets(self):
        totals = {}
        for quality in (20, 90):
            players = tuple(replace(p, stuff=quality, control=quality, strikeout=quality,
                                    groundball=quality, stamina=80, pitch_repertoire=())
                            if p.primary_position == 'P' else p
                            for p in self.teams[0].player_abilities)
            team = TeamMatchInput(self.teams[0].school_id, self.generator.generate(players), players)
            outs = 0
            for i in range(12):
                inp = replace(self.match(910+i), team1=team)
                r = self.sim.simulate(inp)
                outs += next(p.outs_recorded for p in r.pitcher_stats if p.school_id == team.school_id)
            totals[quality] = outs
        self.assertGreater(totals[90], totals[20])


class NationalDHSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = TeamStrengthGenerator()

    def team(self, sid='FAKE-DH-A', *, ace_bat=90, other_bat=30):
        players = tuple(replace(p, player_id=sid+'-'+p.player_id)
                        for p in make_roster_abilities(school_id=sid))
        ace = self.generator.generate(players).starting_lineup.player_for_position('P')
        players = tuple(replace(p, **{key: ace_bat if p.player_id == ace else other_bat
                                     for key in ('contact','power','plate_discipline',
                                                 'strikeout_resistance','speed','baserunning')})
                        for p in players)
        return TeamMatchInput(sid, self.generator.generate(players), players)

    def live(self, enabled=True):
        r = resolver(books(), date(2026,7,1))
        r.dh_enabled = enabled
        r.ability_generator.source = None
        return r

    @staticmethod
    def mode(team):
        lineup = team.team_strength.starting_lineup
        return ('none' if lineup.designated_hitter_id is None else
                'pitcher' if lineup.designated_hitter_id == lineup.player_for_position('P') else 'normal')

    def test_ability_comparison_selects_normal_and_pitcher(self):
        live = self.live()
        for values, expected in (((20,80),'normal'),((90,30),'pitcher')):
            team = self.team(ace_bat=values[0],other_bat=values[1])
            selected = live._select_dh_input(team, None, CoachTactics())
            self.assertEqual(expected, self.mode(selected))
            self.assertEqual(team.team_strength.starting_lineup.player_for_position('P'),
                             selected.team_strength.starting_lineup.player_for_position('P'))
            validate_team_strength_snapshot(selected.team_strength)
            self.assertEqual('none', self.mode(team))

    def test_nine_available_players_and_one_pitcher_with_good_bat_keep_none(self):
        team = self.team()
        by_id = {p.player_id:p for p in team.player_abilities}
        nine = tuple(by_id[e.player_id] for e in team.team_strength.starting_lineup.entries)
        registered=frozenset(by_id)
        small = replace(team, player_abilities=nine, team_strength=self.generator.generate(nine),
                        registered_player_ids=registered)
        self.assertIs(small,self.live()._select_dh_input(small,None,CoachTactics()))
        ace=team.team_strength.starting_lineup.player_for_position('P')
        players=tuple(p for p in team.player_abilities if p.primary_position!='P' or p.player_id==ace)
        one=replace(team,player_abilities=players,team_strength=self.generator.generate(players))
        self.assertIs(one,self.live()._select_dh_input(one,None,CoachTactics()))

    def test_pitch_allowance_changes_starter_and_choice_without_mutating_input(self):
        live=self.live();team=self.team();before=team.to_dict()
        ace=team.team_strength.starting_lineup.player_for_position('P')
        self.assertEqual('pitcher',self.mode(live._select_dh_input(team,None,CoachTactics())))
        selected=live._select_dh_input(team,{ace:60},CoachTactics())
        self.assertEqual('normal',self.mode(selected))
        self.assertNotEqual(ace,selected.team_strength.starting_lineup.player_for_position('P'))
        self.assertEqual(ace,selected.team_strength.starting_lineup.designated_hitter_id)
        self.assertEqual(before,team.to_dict())

    def test_emergency_fielder_start_and_disabled_mode_keep_input(self):
        team=self.team();pitchers={p.player_id for p in team.player_abilities if p.primary_position=='P'}
        live=self.live()
        self.assertIs(team,live._select_dh_input(team,{pid:0 for pid in pitchers},CoachTactics()))
        live.dh_enabled=False
        self.assertIs(team,live._select_dh_input(team,None,CoachTactics()))

    def test_disabled_keeps_full_result(self):
        live=self.live(False);teams=(self.team(),self.team('FAKE-DH-B'))
        inp=MatchSimulationInput('FAKE-DH-OFF','FAKE-CUP',2026,20261022,*teams,
                                 team_generation_seed=teams[0].team_strength.generation_seed)
        before=live.simulator.simulate(inp)
        live.team_input=lambda **kw: next(t for t in teams if t.school_id==kw['school_id'])
        live._record_pitches=lambda *a:None;live._record_games=lambda *a:None
        live.rules_for=lambda *a:GameRules();live._pitch_allowances=lambda *a:None
        row=live(match_id=inp.match_id,competition_id=inp.competition_id,reference_year=2026,
                 generation_seed=inp.generation_seed,team1=teams[0].school_id,team2=teams[1].school_id)
        for key,value in before.to_dict().items():self.assertEqual(value,row.detail[key])

    def test_mixed_modes_are_reproducible_and_saveable(self):
        from game_core.match_contract import validated_match_history
        from phase2_engine.historical_match_archive import compact_payload,expand_payload,_history_payload
        live=self.live();original=(self.team(),self.team('FAKE-DH-B',ace_bat=20,other_bat=80))
        teams=tuple(live._select_dh_input(t,None,CoachTactics()) for t in original)
        self.assertEqual(('pitcher','normal'),tuple(map(self.mode,teams)))
        inp=MatchSimulationInput('FAKE-DH-MIX','FAKE-CUP',2026,20261022,*teams,
                                 team_generation_seed=teams[0].team_strength.generation_seed)
        a=live.simulator.simulate(inp);b=live.simulator.simulate(inp)
        self.assertEqual(a,b);validate_match_simulation_result(a,inp)
        detail=validated_match_history(a,inp)
        row=dict(competition_id=inp.competition_id,competition_name='架空杯',match_id=inp.match_id,
                 match_date='2026-07-01',round_name='決勝',status='completed',team1_id=teams[0].school_id,
                 team2_id=teams[1].school_id,team1_score=a.team1_score,team2_score=a.team2_score,
                 winner_id=a.winner_id,loser_id=a.loser_id,score_source=a.score_source,ability_detail=detail)
        payload=_history_payload(2026,row)
        self.assertEqual(payload,expand_payload(compact_payload(payload)))

    def test_injury_shortage_does_not_add_optional_dh(self):
        live=self.live();team=self.team(ace_bat=20,other_bat=80)
        live.ability_generator.source=SimpleNamespace(condition=lambda p,day:(True,0))
        live.member_provider=lambda *a:SimpleNamespace(players=team.player_abilities)
        self.assertIs(team,live._select_dh_input(team,None,CoachTactics()))

    def test_two_way_candidate_needs_batting_fit_among_starting_fielders(self):
        team=self.team(ace_bat=45,other_bat=20)
        # 守備の先発8人を強打者にする。控えとの僅かな比較だけでは兼任にしない。
        fielders={e.player_id for e in team.team_strength.starting_lineup.entries if e.defensive_position!='P'}
        players=tuple(replace(p,contact=80,power=80,plate_discipline=80,strikeout_resistance=80,speed=80)
                      if p.player_id in fielders else p for p in team.player_abilities)
        team=replace(team,player_abilities=players,team_strength=self.generator.generate(players))
        live=self.live()
        self.assertEqual('none',self.mode(live._select_dh_input(team,None,CoachTactics())))
        live._dh_two_way_lineup_bat=False
        self.assertEqual('pitcher',self.mode(live._select_dh_input(team,None,CoachTactics())))

    def test_all_modes_record_one_experience_and_injury_exposure_per_player(self):
        from game_core.team_strength import DHSelection
        for mode in ('none','normal','pitcher'):
            with self.subTest(mode=mode):
                f=books();live=resolver(f,date(2026,7,1));live.dh_enabled=True
                source=f[3]
                members={sid:live.member_provider('FAKE-CUP',sid).players for sid in ('FAKE-A','FAKE-B')}
                before={p.player_id:source.state(p).games for ps in members.values() for p in ps}
                with (patch.object(live.team_generator,'select_dh_mode',return_value=DHSelection(mode,'test')),
                      patch.object(source,'after_game',wraps=source.after_game) as injury):
                    row=live(match_id='FAKE-EXPERIENCE',competition_id='FAKE-CUP',reference_year=2026,
                             generation_seed=20261022,team1='FAKE-A',team2='FAKE-B')
                detail=row.detail
                expected={s['player_id'] for s in detail['batter_stats'] if s['plate_appearances']}
                expected|={s['player_id'] for s in detail['pitcher_stats'] if s['batters_faced']}
                expected|={pid for record in detail['team_participation'] for pid in record['fielding_player_ids']}
                for ps in members.values():
                    for p in ps:self.assertEqual(before[p.player_id]+(p.player_id in expected),source.state(p).games)
                exposures=injury.call_args.args[0]
                self.assertEqual(expected,{p.player_id for p,_,_,_ in exposures})
                self.assertEqual(len(expected),len(exposures))
                for s in detail['pitcher_stats']:
                    if s['pitches']:self.assertEqual(s['pitches'],live.season_state.pitch_log[s['player_id']]['2026-07-01'])


if __name__ == "__main__":
    unittest.main()
