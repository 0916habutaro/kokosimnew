"""Independent SQL/JSON/SHA oracle over owned, self-generated school authorities."""
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from game_core.players import Player
from game_core.school_intake import SchoolAwarePlayerAbilityGenerator
from game_core.team_strength import TeamStrengthGenerator
from game_core.match_simulator import MatchSimulator
from phase2_engine import joint_team_registration_lab as lab
from stage43g103_fixture_support import fixture
from stage43g97_acceptance_support import pin
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


class Stage43G104RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stage104-owned-')
        self.addCleanup(self.temp.cleanup)
        self.slot = Path(self.temp.name)
        self.repo, self.rosters, self.old = fixture(self.slot)
        self.registry = lab.registration_from_rosters(self.repo, self.rosters)
        self.before = pin(self.slot)

    def tearDown(self):
        self.assertEqual(self.before, pin(self.slot))

    def match(self):
        return lab.match_input_from_registration(self.registry, self.repo, self.rosters,
            team1_id=self.registry.teams[0].team_id,
            team2_id=self.registry.teams[1].team_id, opt_in=True)

    def test_sql_all80_authorities_all60_registered_and_permanent_identity(self):
        # Query the archive directly, without using the product reader/preview.
        with closing(sqlite3.connect(self.slot/'career_rosters.sqlite3')) as conn:
            authorities = conn.execute('SELECT year,school_id,content_sha256,payload_json '
                                       'FROM career_school_rosters ORDER BY school_id').fetchall()
            identities = dict((pid, (sid, entry, json.loads(raw))) for pid,sid,entry,raw in
                conn.execute('SELECT player_id,school_id,entry_year,identity_json FROM career_player_identities'))
        self.assertEqual((4,80,3), (len(authorities),len(identities),len(self.registry.teams)))
        payloads = [json.loads(row[3]) for row in authorities]
        self.assertEqual(digest(payloads), self.registry.roster_set_sha256)
        self.assertEqual(tuple((sid, sha) for year,sid,sha,raw in authorities),
                         self.registry.school_fingerprints)
        all_players = [p for r in payloads for p in r['players']]
        self.assertEqual(80,len(all_players))
        for p in all_players:
            identity = dict(p)
            identity.pop('academic_year')
            self.assertEqual((p['school_id'],p['entry_year'],identity),identities[p['player_id']])
        memberships = (('SCH000202','SCH000220'),('SCH000196',),('SCH000197',))
        # Literal position recipe is independent of product POSITION_SLOTS/preview.
        positions = ('P',)*5 + ('C',)*2 + ('1B',) + ('2B',)*2 + ('3B',)*2 + ('SS',)*2 + ('LF',)*2 + ('CF',)*2 + ('RF',)*2
        registered = []
        for team, schools in zip(self.registry.teams, memberships):
            self.assertEqual(schools,team.school_ids)
            self.assertEqual((2026,'CMP000041',lab.VERSION,lab.SELECTION),
                             (team.year,team.competition_id,team.source_version,team.selection_recipe))
            used = set()
            for index, position in enumerate(positions):
                sid = schools[index % len(schools)]
                candidates = [p for p in all_players if p['school_id']==sid
                    and p['primary_position']==position and p['player_id'] not in used]
                p = min(candidates,key=lambda p:p['roster_no'])
                used.add(p['player_id'])
                row = team.players[index]
                self.assertEqual(p,row.player.to_dict())
                self.assertEqual((2026,'CMP000041',team.team_id,p['player_id'],sid,index+1,dict(self.registry.school_fingerprints)[sid]),
                    (row.year,row.competition_id,row.team_id,row.player_id,row.origin_school_id,row.team_slot,row.source_roster_sha256))
                registered.append(row.player_id)
        self.assertEqual(60,len(set(registered)))
        self.assertEqual(10,sum(r.origin_school_id=='SCH000202' for r in self.registry.teams[0].players))
        self.assertEqual(10,sum(r.origin_school_id=='SCH000220' for r in self.registry.teams[0].players))

    def test_registration_rejects_membership_namespace_version_year_and_missing(self):
        r = self.registry
        first, second, third = r.teams
        bad = [replace(r,version='other'),replace(r,year=2027),replace(r,competition_id='other'),
               replace(r,roster_seed=430104),replace(r,teams=r.teams[:-1]),replace(r,teams=list(r.teams)),
               replace(r,school_fingerprints=r.school_fingerprints[:-1]),replace(r,roster_set_sha256='0'*64)]
        for team in [replace(first,school_ids=second.school_ids),replace(first,school_ids=('unknown',)),
                     replace(first,team_id='SCH000202'),replace(first,source_version='v2'),
                     replace(first,selection_recipe='v2'),replace(first,school_ids=list(first.school_ids))]:
            bad.append(replace(r,teams=(team,second,third)))
        for value in bad:
            with self.subTest(value=type(value).__name__),self.assertRaises(ValueError):
                lab.validate_registration(value,self.repo,self.rosters)

    def test_registration_rejects_player_origin_slot_duplicate_identity_and_fingerprint(self):
        team = self.registry.teams[0]
        row = team.players[0]
        other = self.registry.teams[1].players[0]
        edits = [replace(row,origin_school_id='SCH000196'),replace(row,player_id=other.player_id),
                 replace(row,team_id='SCH000202'),replace(row,team_slot=2),replace(row,team_slot=True),
                 replace(row,year=2027),replace(row,competition_id='other'),
                 replace(row,source_roster_sha256='0'*64),
                 replace(row,player=replace(row.player,entry_year=2027)),
                 replace(row,player=replace(row.player,academic_year=1)),
                 replace(row,player=replace(row.player,primary_position='C'))]
        for new in edits:
            bad = replace(self.registry,teams=(replace(team,players=(new,)+team.players[1:]),)+self.registry.teams[1:])
            with self.subTest(edit=new.team_slot),self.assertRaises(ValueError):
                lab.validate_registration(bad,self.repo,self.rosters)
        for rows in (team.players[:-1],(row,row)+team.players[2:]):
            with self.assertRaises(ValueError):
                lab.validate_registration(replace(self.registry,teams=(replace(team,players=rows),)+self.registry.teams[1:]),self.repo,self.rosters)

    def test_rejects_tampered_and_missing_school_authorities(self):
        from copy import deepcopy
        for field,value in [('rng_seed',1),('reference_year',2027),('school_id','SCH000197')]:
            rosters=deepcopy(self.rosters)
            setattr(rosters[0],field,value)
            with self.subTest(field=field),self.assertRaises(ValueError):
                lab.registration_from_rosters(self.repo,rosters)
        rosters=deepcopy(self.rosters)
        rosters[0].players[0]=replace(rosters[0].players[0],player_id=rosters[1].players[0].player_id)
        with self.assertRaises(ValueError):
            lab.registration_from_rosters(self.repo,rosters)
        rosters=deepcopy(self.rosters)
        index=next(i for i,p in enumerate(rosters[0].players) if p.academic_year==1)
        rosters[0].players[index]=replace(rosters[0].players[index],academic_year=True)
        with self.assertRaises(ValueError):
            lab.registration_from_rosters(self.repo,rosters)
        with self.assertRaises(ValueError):
            lab.registration_from_rosters(self.repo,self.rosters[:-1])
        with patch.dict(self.repo.schools,{self.registry.teams[0].team_id:self.repo.schools['SCH000202']}):
            with self.assertRaises(ValueError):
                lab.registration_from_rosters(self.repo,self.rosters)

    def test_immutable_detached_same_name_distinct_ids_and_participation(self):
        row=self.registry.teams[0].players[0]
        with self.assertRaises(FrozenInstanceError):
            row.origin_school_id='other'
        payload=self.registry.to_dict()
        payload['teams'][0]['players'][0]['player']['school_id']='other'
        self.assertEqual('SCH000202',row.origin_school_id)
        names=[r.player.display_name for t in self.registry.teams for r in t.players]
        self.assertLess(len(set(names)),len(names))
        self.assertEqual(60,len({r.player_id for t in self.registry.teams for r in t.players}))
        for sid in ('SCH000202','SCH000220'):
            self.assertEqual(((2026,'CMP000041',self.registry.teams[0].team_id),),self.registry.school_participation(sid))
        with self.assertRaises(ValueError):
            self.registry.school_participation('other')
        with self.assertRaises(ValueError):
            self.registry.preview('other')

    def test_match_origin_abilities_usage_and_summary_independent_oracle(self):
        match=self.match()
        lab.validate_registered_match_input(match,self.registry,self.repo,self.rosters)
        self.assertEqual((430104,430103,True),(match.match_seed,match.ability_seed,match.opt_in))
        self.assertEqual(digest(self.registry.to_dict()),match.registration_sha256)
        for inp,team in zip((match.team1,match.team2),self.registry.teams):
            self.assertEqual(digest(__import__('dataclasses').asdict(team)),inp.registration_sha256)
            abilities = {r.player_id:SchoolAwarePlayerAbilityGenerator().generate(r.player,2026,430103) for r in team.players}
            for p in inp.players:
                self.assertEqual(abilities[p.player_id],p.snapshot)
                self.assertEqual(p.origin_school_id,p.snapshot.school_id)
                self.assertEqual(team.team_id,p.team_id)
            expected=[]
            for pos in ('P','C','1B','2B','3B','SS','LF','CF','RF'):
                expected.append(sorted((p for p in abilities.values() if p.primary_position==pos),key=lambda p:(-p.contact,p.player_id))[0])
            self.assertEqual(tuple((i,p.primary_position,p.player_id) for i,p in enumerate(sorted(expected,key=lambda p:(-p.contact,p.player_id)),1)),inp.lineup)
            pitchers=sorted((p for p in abilities.values() if p.primary_position=='P'),key=lambda p:(-p.control,p.player_id))
            self.assertEqual(tuple(p.player_id for p in pitchers),inp.pitching_order)
            self.assertEqual(5,len(pitchers))
            self.assertEqual(sum(p.contact for p in abilities.values())/20,inp.summary.mean_contact)
            self.assertEqual(sum(p.power for p in abilities.values())/20,inp.summary.mean_power)
            self.assertEqual(sum(p.fielding for p in abilities.values())/20,inp.summary.mean_fielding)
            self.assertEqual(sum(p.control for p in pitchers)/5,inp.summary.mean_pitcher_control)

    def test_match_requires_explicit_optin_and_distinct_registered_teams(self):
        for a,b,opt in [(0,1,False),(0,1,1),(0,0,True),(0,'SCH000202',True)]:
            with self.assertRaises(ValueError):
                lab.match_input_from_registration(self.registry,self.repo,self.rosters,
                    team1_id=self.registry.teams[a].team_id,
                    team2_id=self.registry.teams[b].team_id if type(b) is int else b,opt_in=opt)

    def test_match_rejects_seed_version_ability_origin_lineup_and_recipe_tamper(self):
        m=self.match()
        t=m.team1
        p=t.players[0]
        cases=[replace(m,match_seed=1),replace(m,ability_seed=1),replace(m,year=2027),replace(m,version='v2'),
               replace(m,competition_id='other'),replace(m,match_id='other'),replace(m,opt_in=1),
               replace(m,registration_sha256='0'*64),replace(m,team1=None)]
        teams=[replace(t,team_id='SCH000202'),replace(t,players=t.players[:-1]),
               replace(t,players=(p,p)+t.players[2:]),replace(t,lineup=t.lineup[::-1]),
               replace(t,pitching_order=t.pitching_order[::-1]),replace(t,ability_recipe='v2'),
               replace(t,usage_recipe='v2'),replace(t,registration_sha256='0'*64),
               replace(t,summary=replace(t.summary,mean_power=0.0))]
        for newp in (replace(p,origin_school_id='SCH000220'),replace(p,snapshot=replace(p.snapshot,school_id=t.team_id)),
                     replace(p,snapshot=replace(p.snapshot,contact=1)),replace(p,snapshot=replace(p.snapshot,generation_seed=1))):
            teams.append(replace(t,players=(newp,)+t.players[1:]))
        cases.extend(replace(m,team1=newt) for newt in teams)
        for bad in cases:
            with self.subTest(kind=bad.version),self.assertRaises(ValueError):
                lab.validate_registered_match_input(bad,self.registry,self.repo,self.rosters)

    def test_zero_matches_refusal_before_legacy_simulator_and_no_writer(self):
        m=self.match()
        with patch.object(MatchSimulator,'simulate',side_effect=AssertionError('no legacy engine')) as simulator:
            with self.assertRaises(lab.JointSimulationUnsupported):
                lab.simulate_registered_match(m,self.registry,self.repo,self.rosters)
            with self.assertRaises(lab.JointSimulationUnsupported):
                lab.legacy_match_input(m)
            simulator.assert_not_called()
        with self.assertRaises(ValueError):
            TeamStrengthGenerator().generate(tuple(p.snapshot for p in m.team1.players))
        self.assertFalse(hasattr(m.team1,'school_id'))
        self.assertEqual('試合結果は未対応',self.registry.preview(m.team1.team_id)['match_result_status'])

    def test_single_school_baseline_and_stage103_preview_unchanged(self):
        baseline=tuple(SchoolAwarePlayerAbilityGenerator().iter_roster(self.rosters[2].players,2026,430103))
        strength=TeamStrengthGenerator().generate(baseline)
        previews=[self.old.preview(t.team_id) for t in self.old.entries]
        self.match()
        self.assertEqual(strength,TeamStrengthGenerator().generate(baseline))
        self.assertEqual(previews,[self.old.preview(t.team_id) for t in self.old.entries])
        self.assertEqual('SCH000196',strength.school_id)

    def test_native_sqlite_close_rename_reopen_success_and_failure(self):
        with retained_handles() as handles:
            repo,rosters,_=fixture(self.slot)
            registry=lab.registration_from_rosters(repo,rosters)
            lab.validate_registration(registry,repo,rosters)
            with self.assertRaises(ValueError):
                lab.validate_registration(replace(registry,version='v2'),repo,rosters)
            assert_closed(self,handles)
            rename_and_read(self,self.slot)
