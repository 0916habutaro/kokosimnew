"""Independent saved SQL/JSON lineage, scope, failure and longevity oracles."""
from collections import Counter
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter
import tracemalloc
import unittest
from unittest.mock import patch

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.school_roster_contract import accept_roster_source, stream_school_transitions, RECIPE
from phase2_engine.school_roster_trial import SchoolRosterTrial, MasterRosterSandbox, VerifiedSavedSchoolSource
from phase2_engine import yamanashi_annual_rosters as yama
from stage43g99_fixture_support import retained_handles, assert_closed
from stage43g112_support import source, worker, SEED, NAGANO

MEASUREMENTS = {}


def pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sql(path, statement, args=()):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('PRAGMA query_only=ON')
        return con.execute(statement, args).fetchall()


class CrossPrefectureRosterTests(unittest.TestCase):
    def setUp(self):
        self.source = source()
        self.owner = tempfile.TemporaryDirectory(prefix='stage112-owned-trial-')
        self.addCleanup(self.owner.cleanup)
        self.lab = SchoolRosterTrial(self.source, self.owner, next_year=2027, career_seed=SEED, opt_in=True)
        self.addCleanup(lambda: self.lab.close())

    def check_lineage(self, lab, source, seed, count):
        old, receipt = source.snapshot()
        began = perf_counter()
        with retained_handles() as handles:
            state = lab.advance(career_seed=seed)
            assert_closed(self, handles)
        self.assertTrue(state['accepted'])
        self.assertEqual(dict(graduated=8*count, returning=12*count, newcomers=8*count),
            {k:state['summary'][k] for k in ('graduated', 'returning', 'newcomers')})
        before = pin(lab.db_path)
        with retained_handles() as handles:
            view = lab.browse()
            assert_closed(self, handles)
        self.assertFalse(view['season_start_authorized'])
        self.assertEqual('roster-only trial', view['scope'])
        self.assertEqual((), view['matches'])
        self.assertIsNone(view['school_standalone_outcomes'])
        rows = sql(lab.db_path, 'SELECT year,school_id,payload_json,content_sha256 FROM career_school_rosters')
        saved = {}
        for year,sid,raw,sha in rows:
            self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), sha)
            saved[year,sid] = json.loads(raw)
        identities = dict((pid, (sid,entry,json.loads(raw))) for pid,sid,entry,raw in
                          sql(lab.db_path,'SELECT player_id,school_id,entry_year,identity_json FROM career_player_identities'))
        self.assertEqual(28*count,len(identities))
        all_ids=set()
        for r in old:
            self.assertEqual(r.to_dict(), saved[2026,r.school_id])
            after=saved[2027,r.school_id]
            people={p['player_id']:p for p in after['players']}
            self.assertEqual(20,len(people))
            self.assertFalse(all_ids & people.keys()); all_ids.update(people)
            self.assertEqual(Counter({1:8,2:5,3:7}),Counter(p['academic_year'] for p in people.values()))
            for p in r.players:
                h=CareerRosterArchive(lab.db_path).player_history(p.player_id)
                self.assertEqual((r.school_id,p.entry_year),(identities[p.player_id][0],identities[p.player_id][1]))
                if p.academic_year==3:
                    self.assertNotIn(p.player_id,people)
                    self.assertEqual([2026],[x['year'] for x in h])
                    fresh=[q for q in people.values() if q['roster_no']==p.roster_no][0]
                    expected='PLY'+hashlib.sha256(f'{seed}:player_career_newcomer_v1:2027:{r.school_id}:{p.roster_no}'.encode()).hexdigest()[:20].upper()
                    self.assertEqual((expected,2027,1,p.primary_position),
                                     (fresh['player_id'],fresh['entry_year'],fresh['academic_year'],fresh['primary_position']))
                else:
                    self.assertEqual(replace(p,academic_year=p.academic_year+1).to_dict(),people[p.player_id])
                    self.assertEqual([2026,2027],[x['year'] for x in h])
        self.assertEqual(before,pin(lab.db_path))
        self.assertTrue(lab.advance(career_seed=seed)['accepted'])
        self.assertEqual(before,pin(lab.db_path))
        return dict(seconds=round(perf_counter()-began,6), schools=count,
                    identities=28*count, active=20*count, database_bytes=lab.db_path.stat().st_size,
                    graduated=8*count, returning=12*count, newcomers=8*count,
                    read_only_bytes_unchanged=True, native_handles_closed=True)

    def test_nagano_four_master_source_and_all_identity_lineage(self):
        repo=self.source.repo
        expected=('飯山高等学校','下高井農林高等学校','中野立志館高等学校','中野西高等学校')
        for sid,name in zip(NAGANO,expected):
            self.assertEqual(('20',name,'SRC000067'),tuple(repo.schools[sid][k] for k in ('prefecture_code','display_name','primary_source_id')))
            self.assertEqual('PRG'+sid[3:],repo.team(sid).program_id)
            memberships=[m for m in repo.tables['school_area_memberships.csv'] if m['program_id']==repo.team(sid).program_id]
            self.assertEqual({'AREA000032','AREA000075'},{m['area_id'] for m in memberships})
        MEASUREMENTS['nagano']=self.check_lineage(self.lab,self.source,SEED,4)

    def test_seed_recipe_source_year_partial_and_duplicate_refusal(self):
        old,receipt=self.source.snapshot(); repo=self.source.repo
        for kwargs in ({'next_year':2028,'career_seed':SEED}, {'next_year':2027,'career_seed':SEED+1},
                       {'next_year':2027,'career_seed':True}, {'next_year':2027,'career_seed':SEED,'recipe':'other'}):
            with self.assertRaises(ValueError): tuple(stream_school_transitions(old,repo,receipt,**kwargs))
        for bad in (old[:-1],old+(old[0],),tuple(reversed(old))):
            with self.assertRaises(ValueError): tuple(stream_school_transitions(bad,repo,receipt,next_year=2027,career_seed=SEED))
        changed=replace(old[0],players=[replace(p,name_source='other') for p in old[0].players])
        with self.assertRaises(ValueError): accept_roster_source((changed,),repo,year=2026,career_seed=SEED,evidence='x')
        duplicate=replace(old[1],players=[replace(p,player_id=old[0].players[i].player_id) for i,p in enumerate(old[1].players)])
        with self.assertRaises(ValueError): accept_roster_source((old[0],duplicate),repo,year=2026,career_seed=SEED,evidence='x')
        # Same name is legal; identity key remains the real school/program ID.
        for kwargs in ({'career_seed':SEED+1},{'career_seed':SEED,'recipe':'other'}):
            before=pin(self.lab.db_path)
            with self.assertRaises(ValueError): self.lab.advance(**kwargs)
            self.assertEqual(before,pin(self.lab.db_path))
        other=MasterRosterSandbox(repo,NAGANO,year=2026,career_seed=SEED+1)
        self.lab.close()
        with self.assertRaises(ValueError): SchoolRosterTrial.resume(self.lab.capability,other)
        self.lab=SchoolRosterTrial.resume(self.lab.capability,self.source)

    def test_partial_prefix_process_crash_resume_and_native_rename(self):
        self.assertFalse(self.lab.advance(career_seed=SEED,limit=1)['accepted'])
        with self.assertRaises(ValueError): self.lab.browse()
        cap=self.lab.capability; self.lab.close()
        moved=self.lab.db_path.with_suffix('.released')
        self.lab.db_path.rename(moved); moved.rename(self.lab.db_path)
        with tempfile.TemporaryDirectory(prefix='stage112-private-') as private:
            worker(self.lab,Path(private),crash='school_committed')
            self.assertTrue(worker(self.lab,Path(private))['accepted'])
        self.lab=SchoolRosterTrial.resume(cap,self.source)
        before=pin(self.lab.db_path)
        self.assertTrue(self.lab.advance(career_seed=SEED)['accepted'])
        self.assertEqual(before,pin(self.lab.db_path))
        self.assertEqual(112,sql(self.lab.db_path,'SELECT count(*) FROM career_player_identities')[0][0])

    def test_acceptance_rollback_lost_ack_and_sidecars_fail_closed(self):
        def fault(at,sid):
            if at=='before_acceptance_commit': raise RuntimeError('rollback')
        with self.assertRaises(RuntimeError): self.lab.advance(career_seed=SEED,fault=fault)
        self.assertEqual((False,4),(self.lab.status()['accepted'],self.lab.status()['generated_schools']))
        self.assertEqual([],sql(self.lab.db_path,'SELECT * FROM roster_trial_acceptance'))
        def lost(at,sid):
            if at=='after_acceptance_commit': raise RuntimeError('lost ack')
        with self.assertRaises(RuntimeError): self.lab.advance(career_seed=SEED,fault=lost)
        self.assertTrue(self.lab.status()['accepted'])
        for suffix in ('-journal','-wal','-shm'):
            side=Path(str(self.lab.db_path)+suffix); side.write_bytes(b'not adopted')
            before=pin(self.lab.db_path)
            try:
                with patch.object(sqlite3,'connect',side_effect=AssertionError('no SQLite recovery')):
                    with self.assertRaises(ValueError): self.lab.status()
                self.assertEqual(before,pin(self.lab.db_path)); self.assertEqual(b'not adopted',side.read_bytes())
            finally: side.unlink()

    def test_partial_acceptance_schema_payload_identity_corruption_refused(self):
        self.lab.advance(career_seed=SEED,limit=1)
        raw=self.lab.db_path.read_bytes()
        for mutation in ('acceptance','schema','identity','payload'):
            try:
                with closing(sqlite3.connect(self.lab.db_path)) as con,con:
                    if mutation=='acceptance': con.execute("INSERT INTO roster_trial_acceptance VALUES (2027,'{}')")
                    elif mutation=='schema': con.execute('CREATE TABLE unknown(x)')
                    elif mutation=='identity':
                        con.execute('DROP TRIGGER trial_career_player_identities_update')
                        con.execute("UPDATE career_player_identities SET school_id='wrong'")
                    else:
                        con.execute('DROP TRIGGER trial_career_school_rosters_update')
                        con.execute("UPDATE career_school_rosters SET payload_json='{}'")
                before=pin(self.lab.db_path)
                with self.assertRaises(ValueError): self.lab.status()
                self.assertEqual(before,pin(self.lab.db_path))
            finally: self.lab.db_path.write_bytes(raw)

    def test_archive_cross_school_collision_rolls_back_and_dirty_crash_refused(self):
        # Newcomer is forced to reuse another school's archived permanent ID.
        foreign=self.source.snapshot()[0][1].players[0].player_id
        before=pin(self.lab.db_path)
        with patch('game_core.career_rosters._newcomer_id',return_value=foreign):
            with self.assertRaises(ValueError): self.lab.advance(career_seed=SEED,limit=1)
        self.assertEqual(before,pin(self.lab.db_path))
        self.assertEqual(80,sql(self.lab.db_path,'SELECT count(*) FROM career_player_identities')[0][0])
        cap=self.lab.capability; self.lab.close()
        with tempfile.TemporaryDirectory(prefix='stage112-dirty-private-') as private:
            worker(self.lab,Path(private),crash='before_acceptance_commit')
        journal=Path(str(self.lab.db_path)+'-journal')
        self.assertGreater(journal.stat().st_size,512)
        anchors={p.name:pin(p) for p in self.lab.db_path.parent.iterdir()}
        with patch.object(sqlite3,'connect',side_effect=AssertionError('no dirty recovery')):
            with self.assertRaises(ValueError): SchoolRosterTrial.resume(cap,self.source)
        self.assertEqual(anchors,{p.name:pin(p) for p in self.lab.db_path.parent.iterdir()})

    def test_same_name_across_real_prefectures_ids_never_coalesce(self):
        repo=self.source.repo
        by_name={}
        pair=None
        for sid in sorted(repo.schools):
            t=repo.team(sid)
            if not t.program_id: continue
            old=by_name.get(t.display_name)
            if old and repo.team(old).prefecture_code!=t.prefecture_code:
                pair=(old,sid); break
            by_name[t.display_name]=sid
        self.assertIsNotNone(pair)
        other=MasterRosterSandbox(repo,pair,year=2031,career_seed=99112)
        rosters,receipt=other.snapshot()
        self.assertEqual(rosters[0].school_name,rosters[1].school_name)
        transitions=tuple(stream_school_transitions(rosters,repo,receipt,next_year=2032,career_seed=99112))
        self.assertEqual(40,len({p.player_id for t in transitions for p in t.roster.players}))
        MEASUREMENTS['same_name_master_ids']=sorted(pair)

    def test_long_roster_only_50_100_200_year_indexed_history(self):
        repo=self.source.repo; sid=NAGANO[0]
        with tempfile.TemporaryDirectory(prefix='stage112-long-only-') as tmp:
            path=Path(tmp)/'long.sqlite3'; archive=CareerRosterArchive(path)
            roster=self.source.snapshot()[0][0]
            archive.save_initial_roster(roster)
            first=roster.players[0]; began=perf_counter(); tracemalloc.start()
            try:
                for offset in range(1,201):
                    receipt=accept_roster_source((roster,),repo,year=2026+offset-1,career_seed=SEED,evidence='long roster-only')
                    t,=stream_school_transitions((roster,),repo,receipt,next_year=2026+offset,career_seed=SEED)
                    archive.advance_and_save(repo.team(sid),next_year=2026+offset,career_seed=SEED)
                    self.assertEqual(t.roster.to_dict(),archive.roster(2026+offset,sid).to_dict())
                    roster=t.roster
                    self.assertEqual(20,len(roster.players))
                    if offset in (50,100,200):
                        MEASUREMENTS[f'long_{offset}']=dict(seconds=round(perf_counter()-began,6),
                            snapshots=offset+1, database_bytes=path.stat().st_size,
                            identities=sql(path,'SELECT count(*) FROM career_player_identities')[0][0],
                            traced_peak_bytes=tracemalloc.get_traced_memory()[1], matches_generated=0)
            finally: tracemalloc.stop()
            before=pin(path)
            h=archive.player_history(first.player_id)
            self.assertTrue(1<=len(h)<=3)
            self.assertEqual(before,pin(path))
            with closing(sqlite3.connect(path)) as con:
                plan=con.execute('EXPLAIN QUERY PLAN SELECT year FROM career_school_rosters WHERE school_id=? AND year BETWEEN ? AND ?',(sid,2024,2026)).fetchall()
            self.assertTrue(any('INDEX' in str(r) for r in plan))


class VerifiedYamanashiCommonContractTests(unittest.TestCase):
    def test_saved31_source_all33_same_api_and_existing_history_bytes(self):
        owner=tempfile.TemporaryDirectory(prefix='stage112-own-source-')
        target=tempfile.TemporaryDirectory(prefix='stage112-own-target-')
        self.addCleanup(owner.cleanup); self.addCleanup(target.cleanup)
        source=yama.SelfCreated2026(owner,opt_in=True); self.addCleanup(source.close)
        adapter=VerifiedSavedSchoolSource(source)
        with self.assertRaises(ValueError): SchoolRosterTrial(adapter,target,next_year=2027,career_seed=430103,opt_in=True)
        self.assertEqual([],list(Path(target.name).iterdir()))
        for _ in range(31): source.store.play_next()
        snap,_=source.verified(); before=source._evidence()
        lab=SchoolRosterTrial(adapter,target,next_year=2027,career_seed=430103,opt_in=True)
        self.addCleanup(lab.close)
        MEASUREMENTS['yamanashi']=CrossPrefectureRosterTests.check_lineage(self,lab,adapter,430103,33)
        # Existing Stage111 read view still attributes joint outcomes to team.
        transitions,_=yama._expected(snap); view=yama.AnnualRosterView(snap,transitions)
        self.assertEqual(640,len({p.player_id for t in snap.registration.teams for p in t.players}))
        self.assertEqual(660,len({p.player_id for r in snap.rosters for p in r.players}))
        for sid in ('SCH000202','SCH000220'):
            self.assertIsNone(view.school(sid,year=2026)['school_standalone_outcomes'])
            self.assertEqual(20,len(view.school(sid,year=2027)['roster']['players']))
        self.assertEqual(before,source._evidence())
        MEASUREMENTS['yamanashi']['saved_matches_preserved']=31
