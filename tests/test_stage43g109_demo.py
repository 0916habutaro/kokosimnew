"""Persistent namespace provenance, RO fail closed and full31 process restart."""
from collections import Counter
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from phase2_engine import yamanashi_demo_store as demo
from phase2_engine.yamanashi_demo_controller import DemoController
from phase2_engine.yamanashi_tournament_lab import _input, _run, checkpoint
from phase2_engine.joint_tournament_oracle import player_totals
from stage43g109_support import run_cli
from stage43g99_fixture_support import retained_handles, assert_closed

MEASUREMENTS = {}


def anchor(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).digest()
            for p in root.rglob('*') if p.is_file()}


class Stage109DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stage109-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ns = demo.DemoNamespace.create(self.root / 'dedicated', opt_in=True)
        self.store = None

    def create(self):
        self.store = demo.DemoStore.create(self.ns, opt_in=True)
        self.addCleanup(self.store.close)
        return self.store

    def test_fully_exited_processes_1_16_31_option_a_all660_raw_sql_and_history(self):
        path = self.root / 'process-demo'
        phases = [run_cli(path, create=True, games=1)]
        did = phases[0]['demo_id']
        for games in (15, 15):
            phases.append(run_cli(path, demo_id=did, games=games))
        self.assertEqual([1,16,31], [p['committed'] for p in phases])
        # No parent temp lease/capability/connection: open by persistent markers only.
        before = anchor(path)
        with retained_handles() as handles:
            store = demo.DemoStore.resume(demo.DemoNamespace(path), did)
            self.addCleanup(store.close)
            snapshot, people = store.reader.history()
            self.assertTrue(snapshot.complete)
            self.assertEqual(660, len(people))
            self.assertEqual(Counter({1:1,2:1,3:2,5:4,9:8,17:16}), Counter(r.rank for r in snapshot.ranks))
            registered = {p.player_id for t in snapshot.registration.teams for p in t.players}
            self.assertEqual(640,len(registered))
            for pid, view in people.items():
                for kind, attr in (('batting','batter_stats'),('pitching','pitcher_stats')):
                    totals = {}
                    for result in snapshot.results:
                        for row in getattr(result, attr):
                            if row.player_id == pid:
                                for key, value in asdict(row).items():
                                    if type(value) is int and key != 'year':
                                        totals[key] = totals.get(key,0) + value
                    self.assertEqual(totals, view['totals'][kind])
                if pid not in registered:
                    self.assertFalse(view['appearances'])
            for sid in (s for t in snapshot.registration.teams for s in t.school_ids):
                view = store.reader.school(sid)
                self.assertTrue(view['matches'])
                self.assertIsNone(view['school_standalone_outcomes'])
            with closing(sqlite3.connect(store.db_path.as_uri()+'?mode=ro', uri=True)) as con:
                counts = {t:con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in demo.TABLES}
                self.assertEqual((33,32,33,640,31,31,32,1), tuple(counts[t] for t in
                    ('school_rosters','teams','memberships','registered_players','matches','advancement','team_ranks','demo_metadata')))
                self.assertEqual([], con.execute('''SELECT * FROM school_participation EXCEPT
                    SELECT m.year,m.competition_id,m.match_id,m.version,t.team_id,t.school_id
                    FROM matches m JOIN memberships t ON m.year=t.year AND m.competition_id=t.competition_id
                    AND t.team_id IN(m.team1_id,m.team2_id)''').fetchall())
                for raw, sha, inp, inp_sha in con.execute('SELECT result_json,result_sha256,input_json,input_sha256 FROM matches'):
                    self.assertEqual(demo.codec.digest(raw),sha)
                    self.assertEqual(demo.codec.digest(inp),inp_sha)
                    for row in json.loads(raw)['batter_stats']+json.loads(raw)['pitcher_stats']:
                        origin,team=con.execute('SELECT origin_school_id,team_id FROM registered_players WHERE player_id=?',
                            (row['player_id'],)).fetchone()
                        self.assertEqual((origin,team),(row['origin_school_id'],row['team_id']))
                        self.assertEqual(origin,people[row['player_id']]['origin_school_id'])
            with closing(sqlite3.connect(store.db_path.as_uri()+'?mode=rw', uri=True)) as con:
                for table in demo.TABLES:
                    with self.assertRaises(sqlite3.IntegrityError):
                        con.execute(f'DELETE FROM {table}')
            assert_closed(self,handles)
        store.close()
        self.assertEqual(before,anchor(path))
        MEASUREMENTS['headless'] = dict(phases=[{k:v for k,v in p.items() if k!='demo_id'} for p in phases],
            rows=counts, all660_history=True, read_only_bytes_unchanged=True)

    def test_exclusive_namespace_and_new_id_never_adopts_existing_product_or_arbitrary_db(self):
        before = anchor(self.root)
        for path in (self.ns.path, self.root, self.ns.path/'nested'):
            with self.assertRaises((ValueError, FileExistsError)):
                demo.DemoNamespace.create(path, opt_in=True)
        with self.assertRaises(ValueError): demo.DemoNamespace.create(self.root/'no-optin')
        for name in ('saves','backups','data'):
            p = self.root/name; p.mkdir()
            (p/'old.sqlite3').write_bytes(b'never load')
            with self.assertRaises(ValueError): demo.DemoNamespace.create(p/'new', opt_in=True)
        with self.assertRaises(ValueError): demo.DemoNamespace.create(demo.Path(__file__).resolve().parents[1]/'new-demo',opt_in=True)
        with self.assertRaises(ValueError): demo.DemoReader(self.root/'arbitrary.sqlite3')
        with self.assertRaises(ValueError): demo.DemoStore.resume(self.ns,'../outside')
        store = self.create(); a = store.demo_id; store.close()
        other = demo.DemoStore.create(self.ns,opt_in=True); self.addCleanup(other.close)
        self.assertNotEqual(a,other.demo_id)
        self.assertEqual(2,len(self.ns.demos()))
        self.assertTrue(all(anchor(self.root)[k] == v for k,v in before.items()))

    def test_lock_unknown_marker_seed_schema_extra_file_and_ro_refusal_bytes_unchanged(self):
        store = self.create(); store.play_next(); did = store.demo_id
        with self.assertRaises(ValueError): demo.DemoStore.resume(self.ns,did)
        store.close()
        marker = store.db_path.parent/demo.MARKER
        original = marker.read_bytes()
        for field, value in (('version','unknown'),('recipe',{}),('directory_identity',[0,0])):
            data = json.loads(original); data[field]=value
            marker.write_text(demo.codec.canonical(data),encoding='utf-8')
            before = anchor(self.ns.path)
            with self.assertRaises(ValueError): demo.DemoStore.resume(self.ns,did)
            self.assertEqual(before,anchor(self.ns.path))
        marker.write_bytes(original)
        for suffix in ('-journal','-wal','-shm'):
            side = Path(str(store.db_path)+suffix); side.write_bytes(b'crash')
            before=anchor(self.ns.path)
            with self.assertRaises(ValueError): demo.DemoStore.resume(self.ns,did)
            self.assertEqual(before,anchor(self.ns.path)); side.unlink()  # test-owned injected file only
        with closing(sqlite3.connect(store.db_path)) as con:
            self.assertEqual(('wal',),con.execute('PRAGMA journal_mode=WAL').fetchone())
        before=anchor(self.ns.path)
        with patch.object(demo.sqlite3,'connect',side_effect=AssertionError('do not open WAL DB')):
            with self.assertRaises(ValueError):demo.DemoStore.resume(self.ns,did)
        self.assertEqual(before,anchor(self.ns.path))
        with closing(sqlite3.connect(store.db_path)) as con:
            con.execute('PRAGMA journal_mode=DELETE')
            con.execute('CREATE INDEX forbidden ON matches(match_id)')
        before=anchor(self.ns.path)
        with self.assertRaises(ValueError): demo.DemoStore.resume(self.ns,did)
        self.assertEqual(before,anchor(self.ns.path))
        with closing(sqlite3.connect(store.db_path)) as con, con:
            con.execute('DROP INDEX forbidden')
            trigger=con.execute("SELECT sql FROM sqlite_master WHERE name='matches_no_update'").fetchone()[0]
            con.execute('DROP TRIGGER matches_no_update')
            raw=con.execute('SELECT result_json FROM matches').fetchone()[0]
            payload=json.loads(raw);payload['run_seed']+=1
            raw=demo.codec.canonical(payload)
            con.execute('UPDATE matches SET result_json=?,result_sha256=?',(raw,demo.codec.digest(raw)))
            con.execute(trigger)
        before=anchor(self.ns.path)
        with self.assertRaises(ValueError):demo.DemoStore.resume(self.ns,did)
        self.assertEqual(before,anchor(self.ns.path))

    def test_symlink_hardlink_copy_and_runtime_replacement_refused(self):
        store = self.create(); did=store.demo_id; store.close()
        copied = self.root/'copied'; shutil.copytree(self.ns.path,copied)
        with self.assertRaises(ValueError): demo.DemoNamespace(copied)
        db=store.db_path; moved=db.with_suffix('.original'); db.rename(moved)
        try:
            os.link(moved,db)
            before=anchor(self.ns.path)
            with self.assertRaises(ValueError): demo.DemoStore.resume(self.ns,did)
            self.assertEqual(before,anchor(self.ns.path))
            db.unlink()
        finally: moved.rename(db)
        link=self.root/'linked'
        try:
            link.symlink_to(self.ns.path,target_is_directory=True)
        except OSError:
            if os.name != 'nt': raise
            # Windows junction does not require Developer Mode symlink privilege.
            import subprocess
            subprocess.run(['cmd','/c','mklink','/J',str(link),str(self.ns.path)],check=True,capture_output=True)
        with self.assertRaises(ValueError): demo.DemoNamespace(link)
        link.unlink() if link.is_symlink() else link.rmdir()
        store=demo.DemoStore.resume(self.ns,did); self.addCleanup(store.close)
        marker=db.parent/demo.MARKER
        raw=marker.read_bytes()
        marker.write_bytes(raw+b' ')
        before=anchor(self.ns.path)
        with self.assertRaises(ValueError): store.play_next()
        self.assertEqual(before,anchor(self.ns.path))

    def test_cancellation_and_mid_transaction_rollback_after_commit_restart(self):
        store=self.create()
        original=anchor(self.ns.path)
        cancelled=threading.Event(); cancelled.set()
        with self.assertRaises(InterruptedError): store.play_next(cancel=cancelled)
        self.assertEqual(original,anchor(self.ns.path))
        for boundary in ('before_transaction','matches','advancement','team_ranks','before_commit'):
            def fault(at):
                if at==boundary: raise RuntimeError('test rollback')
            with self.assertRaises(RuntimeError): store.play_next(fault=fault)
            self.assertEqual(original,anchor(self.ns.path))
        def lost(at):
            if at=='after_commit':raise RuntimeError('lost acknowledgement')
        with self.assertRaises(RuntimeError):store.play_next(fault=lost)
        self.assertEqual(1,len(store.snapshot().results))
        before=anchor(self.ns.path)
        with self.assertRaises(ValueError):store.play_next(expected_checkpoint=checkpoint(()))
        self.assertEqual(before,anchor(self.ns.path))
        did=store.demo_id;store.close()
        resumed=demo.DemoStore.resume(demo.DemoNamespace(self.ns.path),did);self.addCleanup(resumed.close)
        self.assertEqual(1,len(resumed.snapshot().results))

    def test_exclusive_sqlite_lock_refused_without_rw_or_recovery(self):
        store=self.create();did=store.demo_id;store.close()
        with closing(sqlite3.connect(store.db_path)) as con:
            con.execute('BEGIN EXCLUSIVE')
            before=anchor(self.ns.path)
            with patch.object(demo.sqlite3,'connect',wraps=sqlite3.connect) as connect:
                with self.assertRaises(sqlite3.OperationalError): demo.DemoStore.resume(self.ns,did)
                self.assertTrue(all('mode=ro' in str(call.args[0]) for call in connect.call_args_list))
            self.assertEqual(before,anchor(self.ns.path))
            con.rollback()

    def test_controller_round_same_contract_and_reject_clears_view(self):
        c=DemoController();self.addCleanup(c.close)
        c.use_namespace(self.ns.path)
        snap=c.execute('new');self.assertEqual(0,len(snap.results))
        c.execute('one');self.assertEqual(1,len(c.snapshot.results))
        c.store.close()
        with self.assertRaises(ValueError):c.execute('resume',demo_id='../bad')
        self.assertIsNone(c.snapshot);self.assertIsNone(c.store)

    def test_actual_process_crash_hot_journal_is_refused_without_recovery_or_source_change(self):
        import subprocess
        import sys
        store=self.create();did=store.demo_id;store.close()
        code='''
import os, sqlite3, sys
from unittest.mock import patch
from phase2_engine.yamanashi_demo_store import DemoNamespace, DemoStore
store=DemoStore.resume(DemoNamespace(sys.argv[1]),sys.argv[2])
original=sqlite3.connect
def connect(*args,**kwargs):
    con=original(*args,**kwargs);con.execute('PRAGMA cache_size=1');return con
def crash(at):
    if at=='before_commit':os._exit(73)
with patch.object(sqlite3,'connect',connect):store.play_next(fault=crash)
'''
        crashed=subprocess.run([sys.executable,'-c',code,str(self.ns.path),did],capture_output=True,timeout=120)
        self.assertEqual(73,crashed.returncode)
        journal=Path(str(store.db_path)+'-journal')
        self.assertTrue(journal.exists());self.assertGreater(journal.stat().st_size,512)
        before=anchor(self.ns.path)
        with patch.object(demo.sqlite3,'connect',side_effect=AssertionError('do not open dirty DB')):
            with self.assertRaises(ValueError):demo.DemoStore.resume(self.ns,did)
        self.assertEqual(before,anchor(self.ns.path))
