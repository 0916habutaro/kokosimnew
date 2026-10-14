"""Atomic owned SQLite + independent raw SQL/SHA + cross-process restart."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from phase2_engine.registered_full_a_lab_store import (
    RegisteredFullALabStore, RegisteredFullALabReader, fixed_authorities,
    FILENAME, VERSION, canonical, identify_result_format, TRIGGERS,
)
from phase2_engine.joint_team_registration_lab import match_input_from_registration
from phase2_engine.registered_match_driver import simulate_registered_full_a
from phase2_engine.registered_full_a_oracle import event_oracle
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'tests/stage43g106_restart_worker.py'


class Stage106StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.rosters, cls.reg = fixed_authorities()
        cls.match = match_input_from_registration(cls.reg, cls.repo, cls.rosters,
            team1_id=cls.reg.teams[0].team_id, team2_id=cls.reg.teams[1].team_id, opt_in=True)
        cls.result = simulate_registered_full_a(cls.match, cls.reg, cls.repo, cls.rosters)

    def setUp(self):
        # Preserve the actual owner object, not enterContext's returned path string.
        self.owner = tempfile.TemporaryDirectory(prefix='stage106-owned-')
        self.addCleanup(self.owner.cleanup)
        self.store = RegisteredFullALabStore(self.owner)
        self.reader = RegisteredFullALabReader(self.store.db_path)

    def save(self, **kwargs):
        return self.store.append(self.result,self.match,self.reg,self.repo,self.rosters,**kwargs)

    def mutate(self, table, sql, params=()):
        """Adversarial raw SQLite edit with triggers restored (SHA is no signature)."""
        with closing(sqlite3.connect(self.store.db_path)) as con, con:
            con.execute(f'DROP TRIGGER {table}_no_update')
            con.execute(f'DROP TRIGGER {table}_no_delete')
            con.execute(sql, params)
            for trigger in TRIGGERS:
                if trigger.startswith(f'CREATE TRIGGER {table}_'):
                    con.execute(trigger)

    def test_raw_sql_json_sha_oracle_restart_after_generating_process_exits(self):
        self.save()
        before = self.store.db_path.read_bytes()
        with closing(sqlite3.connect(self.store.db_path.as_uri()+'?mode=ro',uri=True)) as con:
            raw, sha, source, input_raw, input_sha = con.execute(
                'SELECT result_json,result_sha256,registration_sha256,input_json,input_sha256 FROM matches').fetchone()
            self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),sha)
            self.assertEqual(hashlib.sha256(input_raw.encode()).hexdigest(),input_sha)
            self.assertEqual(hashlib.sha256(canonical(self.reg.to_dict()).encode()).hexdigest(),source)
            self.assertEqual([8,1], [json.loads(raw)['team1_score'],json.loads(raw)['team2_score']])
            self.assertEqual((3,4,60,80,3), tuple(con.execute(sql).fetchone()[0] for sql in (
                'SELECT count(*) FROM teams', 'SELECT count(*) FROM memberships',
                'SELECT count(*) FROM registered_players',
                "SELECT sum(json_array_length(payload_json,'$.players')) FROM school_rosters",
                'SELECT count(*) FROM school_participation')))
            self.assertEqual([], con.execute('''SELECT * FROM school_participation EXCEPT
                SELECT m.year,m.competition_id,m.match_id,m.version,t.team_id,t.school_id
                FROM matches m JOIN memberships t ON m.year=t.year AND m.competition_id=t.competition_id
                AND t.team_id IN(m.team1_id,m.team2_id)''').fetchall())
            self.assertEqual([], con.execute('''SELECT p.player_id FROM registered_players p
                JOIN school_rosters s ON p.origin_school_id=s.school_id
                WHERE p.source_roster_sha256 <> s.sha256''').fetchall())
        output = subprocess.run([sys.executable,str(WORKER),'--read',str(self.store.db_path)],
            check=True,capture_output=True,text=True,timeout=60)
        evidence = json.loads(output.stdout)
        self.assertEqual([8,1], evidence['score'])
        self.assertEqual(sha,evidence['result_sha256'])
        self.assertEqual(79,evidence['oracle']['events'])
        self.assertEqual({'SCH000202':1,'SCH000220':1,'SCH000196':1},evidence['schools'])
        self.assertEqual(before,self.store.db_path.read_bytes())
        # Actual generator/writer exits. A third process opens its saved copy.
        copy = Path(self.owner.name)/'child-copy.sqlite3'
        created = subprocess.run([sys.executable,str(WORKER),'--generate-copy',str(copy)],
            check=True,capture_output=True,text=True,timeout=60)
        restarted = subprocess.run([sys.executable,str(WORKER),'--read',str(copy)],
            check=True,capture_output=True,text=True,timeout=60)
        self.assertEqual(json.loads(created.stdout),json.loads(restarted.stdout))
        self.assertEqual(before,copy.read_bytes())

    def test_same_result_idempotent_and_native_closed_rename_readonly(self):
        with retained_handles() as handles:
            self.assertTrue(self.save())
            before=self.store.db_path.read_bytes()
            self.assertFalse(self.save())
            self.assertEqual(self.result,self.reader.match(self.result.year,self.result.competition_id,self.result.match_id))
            assert_closed(self,handles)
            rename_and_read(self,Path(self.owner.name))
            self.assertEqual(before,self.store.db_path.read_bytes())
            moved=self.store.db_path.with_name('renamed.sqlite3')
            self.store.db_path.rename(moved)
            self.assertEqual((self.result,),RegisteredFullALabReader(moved).snapshot().results)
            assert_closed(self,handles)
            moved.rename(self.store.db_path)
            self.assertEqual(before,self.store.db_path.read_bytes())

    def test_conflicting_result_seed_source_membership_rejected_unchanged(self):
        self.save();before=self.store.db_path.read_bytes()
        other=simulate_registered_full_a(self.match,self.reg,self.repo,self.rosters,run_seed=1)
        for result in (other, replace(self.result,team1_score=9), replace(self.result,input_sha256='0'*64)):
            with self.assertRaises(ValueError):
                self.store.append(result,self.match,self.reg,self.repo,self.rosters)
        team=self.reg.teams[0]
        for reg in (replace(self.reg,roster_set_sha256='0'*64),
                    replace(self.reg,teams=(replace(team,school_ids=team.school_ids[:1]),)+self.reg.teams[1:]),
                    replace(self.reg,teams=(replace(team,players=(self.reg.teams[1].players[0],)+team.players[1:]),)+self.reg.teams[1:])):
            with self.assertRaises(ValueError):
                self.store.append(self.result,self.match,reg,self.repo,self.rosters)
        self.assertEqual(before,self.store.db_path.read_bytes())

    def test_fault_each_boundary_rolls_back_bytes_and_retry(self):
        for boundary in ('school_rosters','registrations','teams','memberships','registered_players','matches','school_participation','before_commit'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory(prefix='stage106-fault-') as unused:
                owner=tempfile.TemporaryDirectory(dir=unused)
                try:
                    store=RegisteredFullALabStore(owner)
                    before=store.db_path.read_bytes()
                    def fault(table):
                        if table == boundary:
                            raise RuntimeError('injected partial write')
                    with self.assertRaises(RuntimeError):
                        store.append(self.result,self.match,self.reg,self.repo,self.rosters,fault=fault)
                    self.assertEqual(before,store.db_path.read_bytes())
                    self.assertEqual((),RegisteredFullALabReader(store.db_path).snapshot().results)
                    self.assertTrue(store.append(self.result,self.match,self.reg,self.repo,self.rosters))
                finally:owner.cleanup()

    def test_abrupt_process_exit_uncommitted_journal_readonly_refuses_recovery(self):
        original=self.store.db_path.read_bytes()
        crashed=subprocess.run([sys.executable,str(WORKER),'--crash-fixture-db',str(self.store.db_path)],
            capture_output=True,text=True,timeout=60)
        self.assertEqual(73,crashed.returncode)
        path=self.store.db_path
        self.assertTrue(path.with_name(path.name+'-journal').exists())
        before={p.name:p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
        # A read-only reader cannot recover a hot rollback journal, nor may it try.
        with self.assertRaises(sqlite3.OperationalError):RegisteredFullALabReader(path).snapshot()
        self.assertEqual(before,{p.name:p.read_bytes() for p in path.parent.iterdir() if p.is_file()})
        # Explicit SQLite recovery only in this self-owned crash fixture, not the reader.
        with closing(sqlite3.connect(path)) as recovery:
            self.assertEqual([('ok',)],recovery.execute('PRAGMA integrity_check').fetchall())
        self.assertEqual((),RegisteredFullALabReader(path).snapshot().results)
        self.assertEqual(original,path.read_bytes())
        self.assertTrue(self.save())  # same owned writer retries the recovered empty DB

    def test_concurrent_insert_competition_serialized_and_idempotent(self):
        self.store.timeout=5
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.save(),range(2)))
        self.assertEqual([False,True],sorted(results))
        self.assertEqual((self.result,),self.reader.snapshot().results)

    def test_busy_write_and_locked_reader_fail_then_retry(self):
        before=self.store.db_path.read_bytes()
        with closing(sqlite3.connect(self.store.db_path)) as locker:
            locker.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(sqlite3.OperationalError):self.save()
            with self.assertRaises(sqlite3.OperationalError):self.reader.snapshot()
            locker.rollback()
        self.assertEqual(before,self.store.db_path.read_bytes())
        self.assertTrue(self.save())

    def test_delete_and_wal_snapshot_bytes_readonly_and_close(self):
        self.save()
        for mode in ('DELETE','WAL'):
            with self.subTest(mode=mode):
                owner=tempfile.TemporaryDirectory(prefix='stage106-journal-')
                try:
                    store=RegisteredFullALabStore(owner,journal_mode=mode)
                    with retained_handles() as handles:
                        store.append(self.result,self.match,self.reg,self.repo,self.rosters)
                        reader=RegisteredFullALabReader(store.db_path)
                        before=store.db_path.read_bytes()
                        self.assertEqual((self.result,),reader.snapshot().results)
                        self.assertEqual(before,store.db_path.read_bytes())
                        assert_closed(self,handles);rename_and_read(self,Path(owner.name))
                        # Writer held in WAL; read snapshot cannot see its uncommitted data.
                        if mode == 'WAL':
                            with closing(sqlite3.connect(store.db_path)) as writer:
                                writer.execute('BEGIN IMMEDIATE')
                                self.assertEqual((self.result,),reader.snapshot().results)
                                writer.rollback()
                        with closing(sqlite3.connect(store.db_path.as_uri()+'?mode=ro',uri=True)) as ro:
                            with self.assertRaises(sqlite3.OperationalError):
                                ro.execute("INSERT INTO lab_meta VALUES ('bad')")
                finally:owner.cleanup()

    def test_team_school_and_player_search_no_school_win_aggregation(self):
        self.save()
        for tid in (self.result.team1_id,self.result.team2_id):
            self.assertEqual((self.result,),self.reader.team(tid)['matches'])
        for sid in ('SCH000202','SCH000220'):
            school=self.reader.school(sid)
            self.assertEqual((self.result,),school['matches'])
            self.assertEqual(self.result.team1_id,school['participating_teams'][0].team_id)
            self.assertIsNone(school['school_standalone_outcomes'])
        self.assertEqual((),self.reader.school('SCH000197')['matches'])
        for row in self.result.batter_stats+self.result.pitcher_stats:
            view=self.reader.player(row.player_id)
            self.assertEqual(row.origin_school_id,view['origin_school_id'])
            self.assertEqual(1,len(view['appearances']))
            self.assertIn(row,view['appearances'][0]['batting']+view['appearances'][0]['pitching'])
        bench=next(p for p in self.reg.teams[0].players if p.player_id not in {r.player_id for r in self.result.batter_stats})
        self.assertEqual((),self.reader.player(bench.player_id)['appearances'])

    def test_unknown_query_scope_no_missing_file_creation(self):
        self.save()
        for call in (lambda:self.reader.team('unknown'),lambda:self.reader.school('unknown'),
                     lambda:self.reader.player('unknown'),lambda:self.reader.team(self.result.team1_id,year=2027),
                     lambda:self.reader.school('SCH000202',competition_id='other'),
                     lambda:self.reader.match(True,self.result.competition_id,self.result.match_id),
                     lambda:self.reader.match(2026,self.result.competition_id,self.result.match_id,version='future')):
            with self.assertRaises(ValueError):call()
        self.assertIsNone(self.reader.match(2026,self.result.competition_id,'unknown'))
        missing=Path(self.owner.name)/'missing.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):RegisteredFullALabReader(missing).snapshot()
        self.assertFalse(missing.exists())

    def test_writer_refuses_paths_existing_product_or_replacement(self):
        with self.assertRaises(ValueError):RegisteredFullALabStore(Path(self.owner.name))
        before=self.store.db_path.read_bytes()
        with self.assertRaises(FileExistsError):RegisteredFullALabStore(self.owner)
        self.assertEqual(before,self.store.db_path.read_bytes())
        original=self.store.db_path.with_suffix('.original')
        self.store.db_path.rename(original)
        try:
            self.store.db_path.write_bytes(b'foreign replacement')
            with self.assertRaises(ValueError):self.save()
            self.assertEqual(b'foreign replacement',self.store.db_path.read_bytes())
        finally:
            self.store.db_path.unlink();original.rename(self.store.db_path)
        fake=tempfile.TemporaryDirectory(prefix='stage106-foreign-')
        try:
            path=Path(fake.name)/FILENAME
            path.write_bytes(b'product database stand-in')
            with self.assertRaises(FileExistsError):RegisteredFullALabStore(fake)
            self.assertEqual(b'product database stand-in',path.read_bytes())
        finally:fake.cleanup()

    def test_append_only_triggers_all_tables(self):
        self.save();before=self.store.db_path.read_bytes()
        with closing(sqlite3.connect(self.store.db_path)) as con:
            for table in ('lab_meta','school_rosters','registrations','teams','memberships','registered_players','matches','school_participation'):
                with self.assertRaises(sqlite3.IntegrityError):con.execute(f'DELETE FROM {table}')
                column=con.execute(f'PRAGMA table_info({table})').fetchone()[1]
                with self.assertRaises(sqlite3.IntegrityError):con.execute(f'UPDATE {table} SET {column}={column}')
                con.rollback()
        self.assertEqual(before,self.store.db_path.read_bytes())

    def test_rehashed_json_seed_score_version_and_duplicate_keys_refused(self):
        self.save()
        original=self.result.to_json()
        for raw in (original[:-1],original.replace('"team1_score":8','"team1_score":9'),
                    original.replace('"version":"registered_team_full_a_v1"','"version":"future"'),
                    original.replace('"run_seed":430104','"run_seed":430104,"run_seed":430104'),
                    original.replace('"run_seed":430104','"run_seed":1')):
            self.mutate('matches','UPDATE matches SET result_json=?,result_sha256=?',
                (raw,hashlib.sha256(raw.encode()).hexdigest()))
            before=self.store.db_path.read_bytes()
            with self.assertRaises(ValueError):self.reader.snapshot()
            self.assertEqual(before,self.store.db_path.read_bytes())
        self.mutate('matches','UPDATE matches SET result_json=?,result_sha256=?',
                    (original,'0'*64))
        with self.assertRaises(ValueError):self.reader.snapshot()

    def test_missing_registration_orphan_index_collision_authority_refused(self):
        self.save()
        mutations=(('registrations','DELETE FROM registrations'),
            ('registered_players','DELETE FROM registered_players WHERE team_slot=20'),
            ('memberships',"UPDATE memberships SET school_id=team_id WHERE school_id='SCH000202'"),
            ('school_participation','DELETE FROM school_participation'),
            ('school_rosters',"UPDATE school_rosters SET payload_json='{}'"),
            ('matches',"UPDATE matches SET input_sha256='bad'"))
        original=self.store.db_path.read_bytes()
        for table,sql in mutations:
            self.store.db_path.write_bytes(original)
            self.mutate(table,sql)
            with self.subTest(table=table),self.assertRaises(ValueError):self.reader.snapshot()
        self.store.db_path.write_bytes(original)
        with closing(sqlite3.connect(self.store.db_path)) as con, con:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('INSERT INTO registered_players SELECT year,competition_id,team_id,player_id,origin_school_id,team_slot,source_roster_sha256,player_json FROM registered_players LIMIT 1')

    def test_sqlite_corrupt_or_unknown_schema_fail_closed(self):
        self.save();self.store.db_path.write_bytes(b'not a SQLite database')
        before=self.store.db_path.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):self.reader.snapshot()
        self.assertEqual(before,self.store.db_path.read_bytes())
        wrong=Path(self.owner.name)/'wrong.sqlite3'
        with closing(sqlite3.connect(wrong)) as con:
            con.execute('CREATE TABLE historical_matches (payload_json TEXT)')
        before=wrong.read_bytes()
        with self.assertRaises(ValueError):RegisteredFullALabReader(wrong).snapshot()
        self.assertEqual(before,wrong.read_bytes())

    def test_reader_independent_event_oracle_and_seeded_reexecution_required(self):
        self.save()
        with patch('phase2_engine.registered_full_a_oracle.event_oracle',wraps=event_oracle) as oracle, \
             patch('phase2_engine.registered_match_driver._run',side_effect=RuntimeError('reexecution required')):
            with self.assertRaises(RuntimeError):self.reader.snapshot()
            self.assertEqual(1,oracle.call_count)
        with patch('phase2_engine.registered_match_driver._advance',side_effect=AssertionError('oracle independent')):
            self.assertEqual(79,event_oracle(self.result,self.match)['events'])

    def test_explicit_new_legacy_version_dispatch_no_implicit_adapter(self):
        self.assertEqual(VERSION,identify_result_format(self.result.to_json()))
        for raw in ('{}', self.result.to_json().replace('"version":"registered_team_full_a_v1",',''),
                    self.result.to_json().replace('registered_team_full_a_v1','future')):
            with self.assertRaises(ValueError):identify_result_format(raw)
        from phase2_engine.registered_full_a_contract import decode_result
        from stage43g94_fixture_support import Fixture, owned_sqlite_handles
        with owned_sqlite_handles():
            f=Fixture('sealed')
            try:
                path=f.slot/'historical_matches.sqlite3'
                with closing(sqlite3.connect(path)) as con:
                    raw=con.execute('SELECT payload_json FROM historical_matches LIMIT 1').fetchone()[0]
                self.assertEqual('legacy_school_keyed_unversioned_a',identify_result_format(raw))
                with self.assertRaises(ValueError):decode_result(raw)
            finally:f.close()
