"""Two real commits, process exit/resume, raw SQL and failure boundaries."""
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
import unittest
from unittest.mock import patch

from phase2_engine.registered_full_a_lab_store import fixed_authorities, RegisteredFullALabReader
from phase2_engine.joint_tournament_lab import next_match_input, simulate_tournament_match
from phase2_engine.joint_tournament_store import (
    OwnedTournamentStore, TournamentLabReader, FILENAME, TABLES, TRIGGERS,
)
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read
from stage43g107_process_support import run_phase, crash_final


class Stage107StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.rosters, cls.reg = fixed_authorities()
        cls.m1 = next_match_input(cls.reg, cls.repo, cls.rosters, opt_in=True)
        cls.r1 = simulate_tournament_match(cls.m1, cls.reg, cls.repo, cls.rosters)
        cls.m2 = next_match_input(cls.reg, cls.repo, cls.rosters, (cls.r1,), opt_in=True)
        cls.r2 = simulate_tournament_match(cls.m2, cls.reg, cls.repo, cls.rosters, (cls.r1,))

    def setUp(self):
        self.owner = tempfile.TemporaryDirectory(prefix='stage107-owned-')
        self.addCleanup(self.owner.cleanup)
        self.store = OwnedTournamentStore(self.owner)
        self.reader = TournamentLabReader(self.store.db_path)

    def first(self):
        return self.store.append(self.r1, self.m1)

    def final(self, **kwargs):
        return self.store.append(self.r2, self.m2, **kwargs)

    def mutate(self, table, sql, params=()):
        with closing(sqlite3.connect(self.store.db_path)) as con, con:
            for action in ('update', 'delete'):
                con.execute(f'DROP TRIGGER {table}_no_{action}')
            con.execute(sql, params)
            for trigger in TRIGGERS:
                if trigger.startswith(f'CREATE TRIGGER {table}_'):
                    con.execute(trigger)

    def test_first_process_commit_exit_second_process_read_resume_final(self):
        capability = self.store.resume_capability()
        first = run_phase(capability, 0)
        self.assertNotEqual(os.getpid(), first['pid'])
        self.assertEqual(1, first['count'])
        self.assertFalse(first['complete'])
        saved = self.reader.snapshot()
        self.assertEqual((self.r1,), saved.results)
        before = self.store.db_path.read_bytes()
        with self.assertRaises(ValueError):
            self.reader.tournament()
        self.assertEqual(before, self.store.db_path.read_bytes())
        final = run_phase(capability, 1)
        self.assertNotEqual(os.getpid(), final['pid'])
        self.assertTrue(final['complete'])
        self.assertEqual((self.r1, self.r2), self.reader.tournament().results)
        self.assertEqual(self.r1.winner_id, self.r2.team1_id)

    def test_raw_sql_json_hash_membership_player_origins_and_team_ranks(self):
        self.first(); self.final()
        before = self.store.db_path.read_bytes()
        with retained_handles() as handles:
            with closing(sqlite3.connect(self.store.db_path.as_uri()+'?mode=ro', uri=True)) as con:
                self.assertEqual((3,4,60,2,3,3), tuple(con.execute(sql).fetchone()[0] for sql in (
                    'SELECT count(*) FROM teams', 'SELECT count(*) FROM memberships',
                    'SELECT count(*) FROM registered_players', 'SELECT count(*) FROM matches',
                    'SELECT count(*) FROM advancement', 'SELECT count(*) FROM team_ranks')))
                for raw, sha, inp, inp_sha in con.execute('SELECT result_json,result_sha256,input_json,input_sha256 FROM matches ORDER BY match_id'):
                    self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), sha)
                    self.assertEqual(hashlib.sha256(inp.encode()).hexdigest(), inp_sha)
                    result = json.loads(raw)
                    for kind in ('batter_stats', 'pitcher_stats'):
                        for row in result[kind]:
                            origin, team = con.execute('SELECT origin_school_id,team_id FROM registered_players WHERE player_id=?', (row['player_id'],)).fetchone()
                            self.assertEqual((origin, team), (row['origin_school_id'], row['team_id']))
                    inp = json.loads(inp)
                    self.assertEqual(430103, inp['ability_seed'])
                    self.assertEqual(result['run_seed'], inp['match_seed'])
                self.assertEqual([], con.execute('''SELECT * FROM school_participation EXCEPT
                    SELECT m.year,m.competition_id,m.match_id,m.version,t.team_id,t.school_id
                    FROM matches m JOIN memberships t ON m.year=t.year AND m.competition_id=t.competition_id
                    AND t.team_id IN(m.team1_id,m.team2_id)''').fetchall())
                self.assertEqual(6, con.execute('SELECT count(*) FROM school_participation').fetchone()[0])
                self.assertEqual(80, con.execute("SELECT sum(json_array_length(payload_json,'$.players')) FROM school_rosters").fetchone()[0])
                self.assertEqual([(1,self.r2.winner_id),(2,self.r2.loser_id),(3,self.r1.loser_id)],
                    con.execute('SELECT rank,team_id FROM team_ranks ORDER BY rank').fetchall())
                first_raw=con.execute('SELECT result_json FROM matches WHERE match_id=?',(self.r1.match_id,)).fetchone()[0]
                final_input=json.loads(con.execute('SELECT input_json FROM matches WHERE match_id=?',(self.r2.match_id,)).fetchone()[0])
                self.assertEqual(hashlib.sha256(first_raw.encode()).hexdigest(), final_input['prior_result_sha256'])
            snapshot = self.reader.tournament()
            self.assertEqual((1,2,3), tuple(r.rank for r in snapshot.ranks))
            assert_closed(self, handles)
            rename_and_read(self, Path(self.owner.name))
        self.assertEqual(before, self.store.db_path.read_bytes())

    def test_team_school_match_and_all80_permanent_player_cumulative_search(self):
        self.first(); self.final()
        snapshot = self.reader.tournament()
        for team in self.reg.teams:
            expected = tuple(r for r in snapshot.results if team.team_id in (r.team1_id,r.team2_id))
            self.assertEqual(expected, self.reader.team(team.team_id)['matches'])
            for sid in team.school_ids:
                view = self.reader.school(sid)
                self.assertEqual(expected, view['matches'])
                self.assertIsNone(view['school_standalone_outcomes'])
                self.assertEqual((team,), view['participating_teams'])
        for roster in self.rosters:
            for p in roster.players:
                view = self.reader.player(p.player_id)
                self.assertEqual(p.school_id, view['origin_school_id'])
                for kind, attr in (('batting','batter_stats'), ('pitching','pitcher_stats')):
                    expected = {}
                    for result in snapshot.results:
                        for row in getattr(result, attr):
                            if row.player_id == p.player_id:
                                for key, value in asdict(row).items():
                                    if type(value) is int and key != 'year':
                                        expected[key] = expected.get(key, 0) + value
                    self.assertEqual(expected, view['totals'][kind])
                for appearance in view['appearances']:
                    self.assertTrue(appearance['batting'] or appearance['pitching'])
        for result in snapshot.results:
            self.assertEqual(result, self.reader.match(result.year,result.competition_id,result.match_id))

    def test_each_first_and_final_failure_boundary_rollback_and_retry(self):
        # Reuse owned stores; no test uses a pre-existing save.
        for index, pair in enumerate(((self.r1,self.m1),(self.r2,self.m2))):
            if index:
                self.first()
            before = self.store.db_path.read_bytes()
            for boundary in ('before_match2', 'matches', 'school_participation', 'advancement', 'team_ranks', 'before_commit'):
                if boundary == 'before_match2' and not index:
                    continue
                def fault(at):
                    if at == boundary:
                        raise RuntimeError('injected transaction failure')
                with self.subTest(game=index+1, boundary=boundary), self.assertRaises(RuntimeError):
                    self.store.append(*pair, fault=fault)
                self.assertEqual(before, self.store.db_path.read_bytes())
                self.assertEqual(index, len(self.reader.snapshot().results))
        self.assertTrue(self.final())

    def test_committed_before_response_ambiguous_retry_is_idempotent_both_games(self):
        for result, match in ((self.r1,self.m1),(self.r2,self.m2)):
            def fault(at):
                if at == 'after_commit':
                    raise RuntimeError('acknowledgement lost')
            with self.assertRaises(RuntimeError):
                self.store.append(result, match, fault=fault)
            before = self.store.db_path.read_bytes()
            self.assertFalse(self.store.append(result, match))
            self.assertEqual(before, self.store.db_path.read_bytes())
        self.assertTrue(self.reader.tournament().complete)

    def test_uncommitted_first_or_before_final_does_not_calculate_final(self):
        from phase2_engine import joint_tournament_lab as lab
        original = lab._run
        computed = []
        def record(match, seed):
            computed.append(match.match_id)
            return original(match, seed)
        def fault(at):
            if at == 'before_commit':
                raise RuntimeError('first commit refused')
        with patch.object(lab, '_run', record), self.assertRaises(RuntimeError):
            self.store.play_next(fault=fault)
        self.assertTrue(computed)
        self.assertEqual({self.m1.match_id}, set(computed))
        self.assertEqual((), self.reader.snapshot().results)
        self.first()
        def stop(at):
            if at == 'before_final_calculation':
                raise RuntimeError('final not started')
        with patch('phase2_engine.joint_tournament_lab.simulate_tournament_match', side_effect=AssertionError('must not calculate final')):
            with self.assertRaises(RuntimeError):
                self.store.play_next(fault=stop)
        self.assertEqual((self.r1,), self.reader.snapshot().results)

    def test_seed_result_source_and_final_without_first_refused_bytes_unchanged(self):
        before = self.store.db_path.read_bytes()
        with self.assertRaises(ValueError):
            self.final()
        self.assertEqual(before, self.store.db_path.read_bytes())
        self.first(); before = self.store.db_path.read_bytes()
        for result, match in ((replace(self.r2, run_seed=1), self.m2),
            (replace(self.r2, winner_id=self.r2.loser_id),self.m2),
            (self.r2,replace(self.m2, prior_result_sha256='0'*64)),
            (self.r2,replace(self.m2, team1=self.m1.team2))):
            with self.assertRaises(ValueError):
                self.store.append(result,match)
        self.assertEqual(before, self.store.db_path.read_bytes())

    def test_rehashed_plan_bye_ledger_ranks_input_seed_origin_and_missing_refused(self):
        self.first(); self.final()
        original = self.store.db_path.read_bytes()
        mutations = (
            ('tournament_plan', "UPDATE tournament_plan SET payload_json='{}',sha256='bad'", ()),
            ('advancement', "UPDATE advancement SET team_id=? WHERE source='BYE'", (self.r1.loser_id,)),
            ('team_ranks', 'UPDATE team_ranks SET wins=99 WHERE rank=1', ()),
            ('school_participation', 'DELETE FROM school_participation', ()),
            ('registered_players', "UPDATE registered_players SET origin_school_id='other' WHERE team_slot=1", ()),
            ('matches', "UPDATE matches SET input_json='{}'", ()),
            ('memberships', 'DELETE FROM memberships', ()),
            ('registrations', 'DELETE FROM registrations', ()),
        )
        for table,sql,params in mutations:
            self.store.db_path.write_bytes(original)
            self.mutate(table,sql,params)
            before=self.store.db_path.read_bytes()
            with self.subTest(table=table), self.assertRaises(ValueError):
                self.reader.snapshot()
            self.assertEqual(before,self.store.db_path.read_bytes())
        for changed in (replace(self.r2,run_seed=1),replace(self.r2,team1_score=99),
                        replace(self.r2,winner_id=self.r2.loser_id)):
            self.store.db_path.write_bytes(original)
            raw=changed.to_json()
            self.mutate('matches','UPDATE matches SET result_json=?,result_sha256=? WHERE match_id=?',
                        (raw,hashlib.sha256(raw.encode()).hexdigest(),self.r2.match_id))
            with self.assertRaises(ValueError):
                self.reader.snapshot()
        # Even a rehashed, structurally valid alternate BYE is not this plan.
        self.store.db_path.write_bytes(original)
        plan=self.reader.snapshot().plan.to_dict()
        plan['bye_team_id']=self.r1.loser_id
        raw=json.dumps(plan,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        self.mutate('tournament_plan','UPDATE tournament_plan SET payload_json=?,sha256=?',
                    (raw,hashlib.sha256(raw.encode()).hexdigest()))
        with self.assertRaises(ValueError):self.reader.snapshot()

    def test_append_only_all_tables_and_stage106_reader_refuses(self):
        self.first(); self.final()
        before = self.store.db_path.read_bytes()
        with closing(sqlite3.connect(self.store.db_path)) as con:
            for table in TABLES:
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute(f'DELETE FROM {table}')
                col = con.execute(f'PRAGMA table_info({table})').fetchone()[1]
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute(f'UPDATE {table} SET {col}={col}')
                con.rollback()
        with self.assertRaises(ValueError):
            RegisteredFullALabReader(self.store.db_path).snapshot()
        self.assertEqual(before,self.store.db_path.read_bytes())

    def test_busy_delete_wal_close_rename_readonly_and_concurrent_final(self):
        for mode in ('DELETE','WAL'):
            owner=tempfile.TemporaryDirectory(prefix='stage107-lock-')
            try:
                store=OwnedTournamentStore(owner,journal_mode=mode)
                reader=TournamentLabReader(store.db_path)
                store.append(self.r1,self.m1)
                with closing(sqlite3.connect(store.db_path)) as lock:
                    lock.execute('BEGIN EXCLUSIVE')
                    with self.assertRaises(sqlite3.OperationalError):store.append(self.r2,self.m2)
                    if mode=='DELETE':
                        with self.assertRaises(sqlite3.OperationalError):reader.snapshot()
                    else:
                        self.assertEqual((self.r1,),reader.snapshot().results)
                    lock.rollback()
                store.timeout=5
                # retained_handles patches a global connector, so concurrent
                # writers use normal native closure; retain sequential handles below.
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results=list(pool.map(lambda _:store.append(self.r2,self.m2),range(2)))
                self.assertEqual([False,True],sorted(results))
                with retained_handles() as handles:
                    self.assertFalse(store.append(self.r2,self.m2))
                    before=store.db_path.read_bytes()
                    self.assertTrue(reader.tournament().complete)
                    with closing(sqlite3.connect(store.db_path.as_uri()+'?mode=ro',uri=True)) as ro:
                        with self.assertRaises(sqlite3.OperationalError):ro.execute("INSERT INTO lab_meta VALUES ('bad')")
                    assert_closed(self,handles); rename_and_read(self,Path(owner.name))
                    moved=store.db_path.with_suffix('.released')
                    store.db_path.rename(moved)
                    self.assertTrue(TournamentLabReader(moved).tournament().complete)
                    assert_closed(self,handles)
                    moved.rename(store.db_path)
                    self.assertEqual(before,store.db_path.read_bytes())
            finally:owner.cleanup()

    def test_abrupt_final_exit_hot_journal_ro_refusal_and_owned_recovery_retry(self):
        self.first(); original=self.store.db_path.read_bytes()
        process=multiprocessing.get_context('spawn').Process(target=crash_final,args=(self.store.resume_capability(),))
        process.start(); process.join(timeout=60)
        if process.is_alive():
            process.terminate();process.join(timeout=10)
        self.assertEqual(73,process.exitcode)
        before={p.name:p.read_bytes() for p in Path(self.owner.name).iterdir() if p.is_file()}
        self.assertTrue(any(name.endswith('-journal') for name in before))
        with self.assertRaises(sqlite3.OperationalError):self.reader.snapshot()
        self.assertEqual(before,{p.name:p.read_bytes() for p in Path(self.owner.name).iterdir() if p.is_file()})
        with closing(sqlite3.connect(self.store.db_path)) as con:
            self.assertEqual([('ok',)],con.execute('PRAGMA integrity_check').fetchall())
        self.assertEqual(original,self.store.db_path.read_bytes())
        self.assertEqual((self.r1,),self.reader.snapshot().results)
        self.assertTrue(self.final())

    def test_owner_capability_existing_file_replacement_missing_corrupt_and_scope(self):
        for invalid in (Path(self.owner.name), self.store.db_path, str(self.store.db_path)):
            with self.assertRaises(ValueError):OwnedTournamentStore(invalid)
            with self.assertRaises(ValueError):OwnedTournamentStore.resume(invalid)
        with self.assertRaises(FileExistsError):OwnedTournamentStore(self.owner)
        before=self.store.db_path.read_bytes()
        for call in (lambda:self.reader.team('unknown'),lambda:self.reader.school('unknown'),
                     lambda:self.reader.player('unknown'),lambda:self.reader.team(self.r1.team1_id,year=2027)):
            with self.assertRaises(ValueError):call()
        missing=Path(self.owner.name)/'missing.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):TournamentLabReader(missing).snapshot()
        self.assertFalse(missing.exists())
        original=self.store.db_path.with_suffix('.original')
        self.store.db_path.rename(original)
        self.store.db_path.write_bytes(b'foreign replacement')
        with self.assertRaises(ValueError):self.first()
        with self.assertRaises(sqlite3.DatabaseError):self.reader.snapshot()
        self.assertEqual(b'foreign replacement',self.store.db_path.read_bytes())
        self.store.db_path.unlink();original.rename(self.store.db_path)
        self.assertEqual(before,self.store.db_path.read_bytes())
        cap=self.store.resume_capability()
        self.owner.cleanup()
        with self.assertRaises(ValueError):OwnedTournamentStore.resume(cap)
