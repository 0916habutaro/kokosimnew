"""Gates B/C, SQL identity/full A and owned transaction/restart/failure evidence."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter
import unittest

from phase2_engine.yamanashi_tournament_store import OwnedTournamentStore,TournamentLabReader,TABLES,TRIGGERS
from phase2_engine.yamanashi_tournament_lab import _input,checkpoint,verify_prefix
from phase2_engine.yamanashi_tournament_oracle import progression_oracle
from phase2_engine.registered_full_a_lab_store import RegisteredFullALabReader
from phase2_engine.joint_tournament_store import TournamentLabReader as OldReader
from stage43g108_process_support import run_phase,crash_next
from stage43g99_fixture_support import retained_handles,assert_closed,rename_and_read

MEASUREMENTS={}


def audit_sql(test,store,snapshot):
    before=store.db_path.read_bytes()
    with retained_handles() as handles:
        with closing(sqlite3.connect(store.db_path.as_uri()+'?mode=ro',uri=True)) as con:
            counts={t:con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in TABLES}
            test.assertEqual((33,32,33,640,len(snapshot.results),len(snapshot.results),len(snapshot.plan.entries)),
                tuple(counts[t] for t in ('school_rosters','teams','memberships','registered_players','matches','advancement','team_ranks')))
            people={p.player_id:p for ros in snapshot.rosters for p in ros.players}
            for sid,raw,sha in con.execute('SELECT school_id,payload_json,sha256 FROM school_rosters'):
                test.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),sha)
                for p in json.loads(raw)['players']:test.assertEqual(asdict(people[p['player_id']]),p)
            for raw,sha,inp,inp_sha in con.execute('SELECT result_json,result_sha256,input_json,input_sha256 FROM matches'):
                test.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),sha)
                test.assertEqual(hashlib.sha256(inp.encode()).hexdigest(),inp_sha)
                game=json.loads(raw)
                for row in game['batter_stats']+game['pitcher_stats']:
                    origin,team=con.execute('SELECT origin_school_id,team_id FROM registered_players WHERE player_id=?',(row['player_id'],)).fetchone()
                    test.assertEqual((origin,team),(row['origin_school_id'],row['team_id']))
                    test.assertEqual(origin,people[row['player_id']].school_id)
                test.assertEqual(json.loads(inp)['match_seed'],game['run_seed'])
                for team in game['team_stats']:
                    test.assertEqual(team['runs'],sum(s['runs'] or 0 for s in game['inning_scores'] if s['team_id']==team['team_id']))
            test.assertEqual([],con.execute('''SELECT * FROM school_participation EXCEPT
                SELECT m.year,m.competition_id,m.match_id,m.version,t.team_id,t.school_id
                FROM matches m JOIN memberships t ON m.year=t.year AND m.competition_id=t.competition_id
                AND t.team_id IN(m.team1_id,m.team2_id)''').fetchall())
            test.assertEqual(sum(2+int('joint' in (r.team1_id+r.team2_id)) for r in snapshot.results),counts['school_participation'])
        assert_closed(test,handles);rename_and_read(test,Path(store.owner.name))
    test.assertEqual(before,store.db_path.read_bytes())
    return counts


class Stage108StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory(prefix='stage108-B-');cls.addClassCleanup(cls.fixture.cleanup)
        cls.complete=OwnedTournamentStore(cls.fixture,gate='B',opt_in=True)
        cap=cls.complete.resume_capability();phases=[]
        for start,stop in ((0,1),(1,4),(4,7)):
            phases.append(run_phase(cap,start,stop))
        cls.saved=TournamentLabReader(cls.complete.db_path).tournament()
        cls.matches=tuple(_input(cls.saved.plan,cls.saved.registration,cls.saved.results[:i]) for i in range(7))
        MEASUREMENTS['B']=dict(phases=phases,real_matches=7,database_bytes=cls.complete.db_path.stat().st_size)

    def setUp(self):
        self.owner=tempfile.TemporaryDirectory(prefix='stage108-owned-');self.addCleanup(self.owner.cleanup)
        self.store=OwnedTournamentStore(self.owner,gate='B',opt_in=True)
        self.reader=TournamentLabReader(self.store.db_path)

    def append(self,index,**kwargs):return self.store.append(self.saved.results[index],self.matches[index],**kwargs)

    def test_gate_b_three_processes_real7_shared_ranks_sql_all660_history(self):
        saved=self.saved
        self.assertEqual([1,4,7],[p['count'] for p in MEASUREMENTS['B']['phases']])
        self.assertTrue(all(p['pid']!=os.getpid() for p in MEASUREMENTS['B']['phases']))
        self.assertEqual(Counter({1:1,2:1,3:2,5:4}),Counter(r.rank for r in saved.ranks))
        self.assertTrue(any('joint' in r.team1_id+r.team2_id for r in saved.results))
        MEASUREMENTS['B']['rows']=audit_sql(self,self.complete,saved)
        snapshot,people=TournamentLabReader(self.complete.db_path).history()
        self.assertEqual(660,len(people))
        for ros in saved.rosters:
            for p in ros.players:
                view=people[p.player_id];self.assertEqual(p.school_id,view['origin_school_id'])
                for kind,attr in (('batting','batter_stats'),('pitching','pitcher_stats')):
                    expected={}
                    for result in snapshot.results:
                        for row in getattr(result,attr):
                            if row.player_id==p.player_id:
                                for key,value in asdict(row).items():
                                    if type(value) is int and key!='year':expected[key]=expected.get(key,0)+value
                    self.assertEqual(expected,view['totals'][kind])
        registered={p.player_id for t in saved.registration.teams for p in t.players}
        self.assertEqual(20,len(set(people)-registered))
        self.assertTrue(all(not people[pid]['appearances'] for pid in set(people)-registered))
        for sid in ('SCH000202','SCH000220','SCH000222'):
            view=TournamentLabReader(self.complete.db_path).school(sid)
            team=next(t for t in saved.registration.teams if sid in t.school_ids)
            self.assertEqual(tuple(r for r in saved.results if team.team_id in (r.team1_id,r.team2_id)),view['matches'])
            self.assertIsNone(view['school_standalone_outcomes'])

    def test_gate_c_after_b_full31_three_processes_round_boundary_complete(self):
        self.assertTrue(self.saved.complete)  # Gate C is conditional on successful Gate B.
        owner=tempfile.TemporaryDirectory(prefix='stage108-C-');self.addCleanup(owner.cleanup)
        begin=perf_counter();store=OwnedTournamentStore(owner,opt_in=True)
        phases=[]
        for start,stop in ((0,1),(1,16),(16,31)):
            phases.append(run_phase(store.resume_capability(),start,stop))
        before=store.db_path.read_bytes();read_start=perf_counter()
        snap=TournamentLabReader(store.db_path).tournament();read_seconds=perf_counter()-read_start
        self.assertEqual(31,len(snap.results));self.assertEqual(32,len(snap.ranks))
        self.assertEqual(Counter({1:1,2:1,3:2,5:4,9:8,17:16}),Counter(r.rank for r in snap.ranks))
        self.assertTrue(all(p['pid']!=os.getpid() for p in phases))
        self.assertEqual(before,store.db_path.read_bytes())
        rows=audit_sql(self,store,snap)
        # All 33 school memberships and every permanent player are retained.
        _,people=TournamentLabReader(store.db_path).history();self.assertEqual(660,len(people))
        for pid,view in people.items():
            for kind,attr in (('batting','batter_stats'),('pitching','pitcher_stats')):
                expected={}
                for game in snap.results:
                    for row in getattr(game,attr):
                        if row.player_id==pid:
                            for key,value in asdict(row).items():
                                if type(value) is int and key!='year':expected[key]=expected.get(key,0)+value
                self.assertEqual(expected,view['totals'][kind])
        for sid in (s for t in snap.registration.teams for s in t.school_ids):
            team=next(t for t in snap.registration.teams if sid in t.school_ids)
            games=[r for r in snap.results if team.team_id in (r.team1_id,r.team2_id)]
            self.assertTrue(games)
        MEASUREMENTS['C']=dict(phases=phases,real_matches=31,rounds=5,rows=rows,
            database_bytes=len(before),verified_read_seconds=round(read_seconds,6),seconds=round(perf_counter()-begin,6),
            reader_db_bytes_unchanged=True,ranks=[asdict(r) for r in snap.ranks],
            games=[dict(match_id=r.match_id,score=[r.team1_score,r.team2_score],winner=r.winner_id,
                        events=len(r.events),innings=r.last_inning) for r in snap.results])

    def test_fault_boundaries_first_round_end_next_round_and_final_rollback_retry(self):
        for i in range(7):
            if i in (0,3,4,6):
                before=self.store.db_path.read_bytes()
                for boundary in ('before_match','matches','school_participation','advancement','team_ranks','before_commit'):
                    def fault(at):
                        if at==boundary:raise RuntimeError('injected transaction failure')
                    with self.subTest(i=i,boundary=boundary),self.assertRaises(RuntimeError):self.append(i,fault=fault)
                    self.assertEqual(before,self.store.db_path.read_bytes())
                    self.assertEqual(i,len(self.reader.snapshot().results))
            self.append(i)
        self.assertTrue(self.reader.tournament().complete)

    def test_after_commit_idempotence_stale_checkpoint_and_precalculation_stop(self):
        def fault(at):
            if at=='after_commit':raise RuntimeError('lost acknowledgement')
        with self.assertRaises(RuntimeError):self.append(0,fault=fault)
        before=self.store.db_path.read_bytes();self.assertFalse(self.append(0));self.assertEqual(before,self.store.db_path.read_bytes())
        with self.assertRaises(ValueError):self.store.play_next(expected_checkpoint=checkpoint(()))
        def stop(at):
            if at=='before_calculation':raise RuntimeError('stopped before next game')
        with self.assertRaises(RuntimeError):self.store.play_next(fault=stop)
        self.assertEqual(before,self.store.db_path.read_bytes())
        for result,match in ((replace(self.saved.results[1],run_seed=1),self.matches[1]),
            (self.saved.results[1],replace(self.matches[1],prior_results_sha256='0'*64)),
            (self.saved.results[4],self.matches[4])):
            with self.assertRaises(ValueError):self.store.append(result,match)
        self.assertEqual(before,self.store.db_path.read_bytes())

    def test_mutated_rehashed_rows_origin_index_plan_rank_or_result_refused_ro(self):
        self.append(0);original=self.store.db_path.read_bytes()
        mutations=(('registered_players',"UPDATE registered_players SET origin_school_id='other' WHERE team_slot=1",()),
            ('memberships','DELETE FROM memberships',()),('school_participation','DELETE FROM school_participation',()),
            ('advancement',"UPDATE advancement SET team_id='loser'",()),('registrations','DELETE FROM registrations',()),
            ('matches',"UPDATE matches SET input_json='{}'",()),
            ('tournament_plan',"UPDATE tournament_plan SET payload_json='{}',sha256='bad'",()))
        for table,sql,args in mutations:
            self.store.db_path.write_bytes(original)
            with closing(sqlite3.connect(self.store.db_path)) as con,con:
                for action in ('update','delete'):con.execute(f'DROP TRIGGER {table}_no_{action}')
                con.execute(sql,args)
                for trigger in TRIGGERS:
                    if trigger.startswith(f'CREATE TRIGGER {table}_'):con.execute(trigger)
            before=self.store.db_path.read_bytes()
            with self.subTest(table=table),self.assertRaises(ValueError):self.reader.snapshot()
            self.assertEqual(before,self.store.db_path.read_bytes())
        for changed in (replace(self.saved.results[0],winner_id=self.saved.results[0].loser_id),replace(self.saved.results[0],team1_score=99)):
            self.store.db_path.write_bytes(original);raw=changed.to_json()
            with closing(sqlite3.connect(self.store.db_path)) as con,con:
                con.execute('DROP TRIGGER matches_no_update')
                con.execute('UPDATE matches SET result_json=?,result_sha256=?',(raw,hashlib.sha256(raw.encode()).hexdigest()))
                con.execute(next(t for t in TRIGGERS if t.startswith('CREATE TRIGGER matches_no_update ')))
            with self.assertRaises(ValueError):self.reader.snapshot()
        self.store.db_path.write_bytes(original)
        with closing(sqlite3.connect(self.store.db_path)) as con,con:
            con.execute('DROP TRIGGER tournament_plan_no_update')
            plan=self.saved.plan.to_dict();plan['entries']=list(reversed(plan['entries']))
            raw=json.dumps(plan,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            con.execute('UPDATE tournament_plan SET payload_json=?,sha256=?',(raw,hashlib.sha256(raw.encode()).hexdigest()))
            con.execute(next(t for t in TRIGGERS if t.startswith('CREATE TRIGGER tournament_plan_no_update ')))
        with self.assertRaises(ValueError):self.reader.snapshot()

    def test_append_only_legacy_readers_scope_existing_file_and_capability_identity(self):
        for i in range(7):self.append(i)
        before=self.store.db_path.read_bytes()
        with closing(sqlite3.connect(self.store.db_path)) as con:
            for table in TABLES:
                with self.assertRaises(sqlite3.IntegrityError):con.execute(f'DELETE FROM {table}')
                col=con.execute(f'PRAGMA table_info({table})').fetchone()[1]
                with self.assertRaises(sqlite3.IntegrityError):con.execute(f'UPDATE {table} SET {col}={col}')
                con.rollback()
        for reader in (RegisteredFullALabReader,OldReader):
            with self.assertRaises(ValueError):reader(self.store.db_path).snapshot()
        for invalid in (Path(self.owner.name),self.store.db_path,str(self.store.db_path)):
            with self.assertRaises(ValueError):OwnedTournamentStore(invalid,opt_in=True)
            with self.assertRaises(ValueError):OwnedTournamentStore.resume(invalid)
        with self.assertRaises(ValueError):OwnedTournamentStore(self.owner)
        with self.assertRaises(FileExistsError):OwnedTournamentStore(self.owner,opt_in=True)
        with self.assertRaises(ValueError):self.reader.school('unknown')
        with self.assertRaises(ValueError):self.reader.team(self.saved.results[0].team1_id,year=2027)
        self.assertEqual(before,self.store.db_path.read_bytes())
        cap=self.store.resume_capability();moved=self.store.db_path.with_suffix('.original');self.store.db_path.rename(moved)
        self.store.db_path.write_bytes(b'foreign replacement')
        with self.assertRaises(ValueError):OwnedTournamentStore.resume(cap)
        self.store.db_path.unlink();moved.rename(self.store.db_path);self.owner.cleanup()
        with self.assertRaises(ValueError):OwnedTournamentStore.resume(cap)

    def test_lock_delete_wal_concurrent_append_readonly_native_close_rename(self):
        for mode in ('DELETE','WAL'):
            owner=tempfile.TemporaryDirectory();self.addCleanup(owner.cleanup)
            store=OwnedTournamentStore(owner,gate='B',opt_in=True,journal_mode=mode)
            with closing(sqlite3.connect(store.db_path)) as lock:
                lock.execute('BEGIN EXCLUSIVE')
                with self.assertRaises(sqlite3.OperationalError):store.append(self.saved.results[0],self.matches[0])
                if mode=='DELETE':
                    with self.assertRaises(sqlite3.OperationalError):TournamentLabReader(store.db_path).snapshot()
                else:self.assertFalse(TournamentLabReader(store.db_path).snapshot().results)
                lock.rollback()
            store.timeout=10
            with ThreadPoolExecutor(max_workers=2) as pool:
                actual=list(pool.map(lambda _:store.append(self.saved.results[0],self.matches[0]),range(2)))
            self.assertEqual([False,True],sorted(actual))
            with retained_handles() as handles:
                before=store.db_path.read_bytes();TournamentLabReader(store.db_path).snapshot()
                with closing(sqlite3.connect(store.db_path.as_uri()+'?mode=ro',uri=True)) as con:
                    with self.assertRaises(sqlite3.OperationalError):con.execute("INSERT INTO lab_meta VALUES ('bad')")
                assert_closed(self,handles);rename_and_read(self,Path(owner.name))
                self.assertEqual(before,store.db_path.read_bytes())

    def test_round_boundary_abrupt_exit_hot_journal_refusal_owned_recovery_retry(self):
        for i in range(4):self.append(i)
        original=self.store.db_path.read_bytes()
        child=multiprocessing.get_context('spawn').Process(target=crash_next,args=(self.store.resume_capability(),));child.start();child.join(timeout=60)
        if child.is_alive():child.terminate();child.join(timeout=10)
        self.assertEqual(73,child.exitcode)
        before={p.name:p.read_bytes() for p in Path(self.owner.name).iterdir() if p.is_file()}
        self.assertTrue(any(n.endswith('-journal') for n in before))
        with self.assertRaises(sqlite3.OperationalError):self.reader.snapshot()
        self.assertEqual(before,{p.name:p.read_bytes() for p in Path(self.owner.name).iterdir() if p.is_file()})
        # Explicit recovery of our own fixture only, never a reader-side repair.
        with closing(sqlite3.connect(self.store.db_path)) as con:self.assertEqual([('ok',)],con.execute('PRAGMA integrity_check').fetchall())
        self.assertEqual(original,self.store.db_path.read_bytes());self.assertEqual(4,len(self.reader.snapshot().results))
        self.append(4)
