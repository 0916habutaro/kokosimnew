"""Gate A: exact official reconciliation, immutable 660/640 and fictional plan."""
from collections import Counter
from dataclasses import replace
import unittest
from unittest.mock import patch

from phase2_engine.yamanashi_tournament_registration import fixed_authorities,validate_registration,OFFICIAL,SCHOOLS
from phase2_engine.yamanashi_tournament_lab import (
    fixed_plan,next_match_input,simulate_tournament_match,validate_tournament_input,verify_prefix,
)
from phase2_engine.yamanashi_tournament_oracle import progression_oracle
from phase2_engine.joint_team_registration_lab import validate_registered_match_input
from phase2_engine.joint_tournament_lab import validate_tournament_input as old_validate


class Stage108ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo,cls.rosters,cls.reg=fixed_authorities()
        cls.plan=fixed_plan(cls.reg,cls.repo,cls.rosters)
        cls.first=next_match_input(cls.reg,cls.repo,cls.rosters,opt_in=True)
        cls.result=simulate_tournament_match(cls.first,cls.reg,cls.repo,cls.rosters)

    def test_gate_a_all32_official_rows33_ids660_permanent640_registered_origins(self):
        self.assertEqual(32,len(OFFICIAL));self.assertEqual(33,len(self.rosters))
        self.assertEqual(SCHOOLS,tuple(r.school_id for r in self.rosters))
        people={p.player_id:p for r in self.rosters for p in r.players}
        self.assertEqual(660,len(people));self.assertEqual(640,sum(len(t.players) for t in self.reg.teams))
        self.assertEqual(Counter(SCHOOLS),Counter(s for t in self.reg.teams for s in t.school_ids))
        self.assertEqual(640,len({p.player_id for t in self.reg.teams for p in t.players}))
        for (label,numbers),team in zip(OFFICIAL,self.reg.teams):
            self.assertEqual(label,team.label);self.assertNotIn(team.team_id,self.repo.schools)
            self.assertEqual(tuple(f'SCH{n:06d}' for n in numbers),team.school_ids)
            self.assertEqual(tuple(range(1,21)),tuple(p.team_slot for p in team.players))
            for p in team.players:
                self.assertEqual(people[p.player_id],p.player)
                self.assertEqual(p.origin_school_id,p.player.school_id)
                self.assertEqual(2027-p.player.academic_year,p.player.entry_year)
        self.assertEqual(Counter({'SCH000202':10,'SCH000220':10}),
                         Counter(p.origin_school_id for p in self.reg.teams[1].players))
        self.assertEqual(Counter({1:16,2:8,3:4,4:2,5:1}),Counter(g.round_no for g in self.plan.games))
        self.assertEqual(31,len({g.match_id for g in self.plan.games}))
        self.assertEqual(31,len({g.seed for g in self.plan.games}))
        self.assertEqual(32,len(set(self.plan.entries)));self.assertEqual(((),()),progression_oracle(self.plan,self.reg,()))

    def test_registration_seed_year_origin_missing_duplicate_type_collision_refused(self):
        r=self.reg;t=r.teams[0];p=t.players[0]
        for bad in (replace(r,year=2027),replace(r,roster_seed=1),replace(r,ability_seed=1),replace(r,selection_seed=1),
            replace(r,year=True),replace(r,teams=r.teams[:-1]),
            replace(r,teams=(replace(t,team_id=t.school_ids[0]),)+r.teams[1:]),
            replace(r,teams=(replace(t,school_ids=r.teams[1].school_ids),)+r.teams[1:]),
            replace(r,teams=(replace(t,players=(replace(p,origin_school_id='SCH000202'),)+t.players[1:]),)+r.teams[1:]),
            replace(r,teams=(replace(t,players=t.players[:-1]+t.players[:1]),)+r.teams[1:])):
            with self.subTest(bad=bad.version),self.assertRaises(ValueError):validate_registration(bad,self.repo,self.rosters)
        for ros in (self.rosters[:-1],self.rosters[::-1],list(self.rosters)):
            with self.assertRaises(ValueError):validate_registration(r,self.repo,ros)

    def test_plan_input_prefix_forgery_and_round_barrier_refused(self):
        for opt in (False,1,None):
            with self.assertRaises(ValueError):next_match_input(self.reg,self.repo,self.rosters,opt_in=opt)
        for bad in (replace(self.plan,entries=self.plan.entries[::-1]),replace(self.plan,bracket_seed=1),
            replace(self.plan,games=(replace(self.plan.games[0],team1_source='loser:x'),)+self.plan.games[1:])):
            with self.assertRaises(ValueError):verify_prefix(self.reg,self.repo,self.rosters,(),plan=bad)
        for bad in (replace(self.first,match_seed=1),replace(self.first,day='2027-01-01'),
            replace(self.first,team2=self.first.team1),replace(self.first,opt_in=1),
            replace(self.first,prior_results_sha256='0'*64),replace(self.first,plan_sha256='0'*64)):
            with self.assertRaises(ValueError):validate_tournament_input(bad,self.reg,self.repo,self.rosters)
        for results in ((self.result,self.result),(replace(self.result,winner_id=self.result.loser_id),),
            (replace(self.result,run_seed=1),),(replace(self.result,events=self.result.events[:-1]),),
            (replace(self.result,match_id=self.plan.games[16].match_id),)):
            with self.assertRaises(ValueError):verify_prefix(self.reg,self.repo,self.rosters,results)
        with patch('phase2_engine.registered_match_driver._run',side_effect=AssertionError('independent')):
            ledger,ranks=progression_oracle(self.plan,self.reg,(self.result,))
            self.assertEqual(self.result.winner_id,ledger[0].team_id);self.assertFalse(ranks)
        # Force a later round into first sequence; oracle must reject before factory.
        forged=replace(self.plan,games=(self.plan.games[16],)+self.plan.games[1:])
        with self.assertRaises(ValueError):progression_oracle(forged,self.reg,(self.result,))

    def test_old_fixed_apis_reject_new_type_without_widening(self):
        from phase2_engine.registered_full_a_lab_store import fixed_authorities as old_authorities
        repo,ros,reg=old_authorities()
        for validate in (validate_registered_match_input,old_validate):
            with self.assertRaises(ValueError):validate(self.first,reg,repo,ros)
