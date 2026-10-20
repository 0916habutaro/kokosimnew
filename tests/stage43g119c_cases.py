"""Real v3 16/32 E2E, independent replay, faults, comparison and performance.

Deliberately excluded from test*.py discovery. Dedicated Linux/Windows CI only.
"""
from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from time import perf_counter, process_time
import unittest
from unittest.mock import patch

from phase2_engine import saved_fictional_bracket_v3 as v3
from phase2_engine import saved_fictional_bracket as v2
from phase2_engine import saved_fictional_tournament as v1
from phase2_engine import saved_practice_match as practice
from phase2_engine import yamanashi_annual_rosters as annual
from phase2_engine import registered_full_a_lab_store as codec
from phase2_engine import fictional_v3_dependencies as deps
from phase2_engine.registered_match_driver import _run
from phase2_engine.registered_full_a_oracle import event_oracle
from phase2_engine.manual_save_backup import _compatibility
from stage43g115_support import scenario as scenario1
from stage43g117_support import scenario as scenario8
from stage43g118_support import scenario16, scenario32, peak_rss_kib, Meter
import stage43g119c_support as support

ROOT = Path(__file__).resolve().parents[1]
MEASUREMENTS = {}


def owned_bytes(path, stores=()):
    for store in stores:
        lease=getattr(store,'_lease',None)
        if lease is not None and not lease.file.closed and Path(lease.file.name)==path:
            return deps.lease_bytes(store,require_valid=False)
    return path.read_bytes()


def pin(path, *, stores=()):
    return hashlib.sha256(owned_bytes(path,stores)).hexdigest()


def files(root, *, stores=()):
    return {str(p.relative_to(root)):owned_bytes(p,stores) for p in root.rglob('*') if p.is_file()}


class Stage119CCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owners, cls.stores = [], []
        def owner():
            value = tempfile.TemporaryDirectory(prefix='stage119c-owned-')
            cls.owners.append(value)
            return value
        cls.owner = staticmethod(owner)
        cls.addClassCleanup(cls.cleanup)
        began = perf_counter()
        cls.source = annual.SelfCreated2026(owner(), opt_in=True)
        for _ in range(31):
            cls.source.store.play_next()
        cls.lab = annual.AnnualRosterLab(cls.source, owner(), opt_in=True)
        assert cls.lab.advance()['accepted']
        cls.practice = practice.PracticeStore(cls.lab, owner(), opt_in=True)
        cls.practice.play()
        cls.old = v1.FictionalTournamentStore(cls.lab, owner(), scenario1(cls.lab), fictional_opt_in=True)
        cls.old.play_next(); cls.old.play_next()
        cls.stores.extend((cls.practice, cls.old))
        cls.request8 = scenario8(cls.lab, namespace='fictional:stage119c-eight')
        cls.requests = {16: scenario16(cls.lab, namespace='fictional:stage119c-sixteen'),
                        32: scenario32(cls.lab, namespace='fictional:stage119c-thirty-two')}
        cls.source_pins = {str(p): pin(p,stores=(cls.lab,cls.source.store)) for root in (Path(cls.lab.capability.root),
            Path(cls.source.capability.root)) for p in root.rglob('*') if p.is_file()}
        cls.legacy_pins = {str(s.db_path): pin(s.db_path) for s in cls.stores}
        cls.catalog = _compatibility(ROOT)
        cls.master = {str(p): pin(p) for p in (ROOT / 'data').rglob('*') if p.is_file()}
        cls.completed, cls.bench = {}, {}
        MEASUREMENTS['fixture'] = dict(seconds=perf_counter() - began, saved2026_games=31,
            accepted2027_schools=33, active_players=660, permanent_ids=924, practice_games=1, v1_games=2)

    @classmethod
    def cleanup(cls):
        for store in reversed(cls.stores):
            store.close()
        if hasattr(cls, 'lab'):
            cls.lab.close()
        if hasattr(cls, 'source'):
            cls.source.close()
        for owner in reversed(cls.owners):
            owner.cleanup()

    def fresh(self, *, prefix=None):
        store = v3.FictionalBracketStore(self.lab, self.owner(), self.request8,
                                        fictional_opt_in=True)
        self.stores.append(store)
        if prefix is not None:
            store.db_path.write_bytes(prefix)
            store.full_audit()
        return store

    def verify_rows(self, store):
        before = pin(store.db_path)
        view = store.snapshot()
        expected, heads = v3._audit_rows(store._prepared, store.request, view.results)
        with closing(sqlite3.connect(store.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            for table, wanted in expected.items():
                self.assertEqual(wanted, sorted(con.execute(f'SELECT * FROM {table}').fetchall()), table)
        self.assertEqual(heads[-1], store.receipt().chain_head)
        self.assertEqual(before, pin(store.db_path))

    def test_01_real_16_32_e2e_and_same_environment_v2_v3_measurement(self):
        for size in (16, 32):
            for module in (v2, v3):
                label = f'v{2 if module is v2 else 3}_{size}'
                print('RUN', label, flush=True)
                began, cpu = perf_counter(), process_time()
                store = module.FictionalBracketStore(self.lab, self.owner(), self.requests[size],
                    scenario_seed=430119 + size, fictional_opt_in=True)
                self.stores.append(store)
                created = perf_counter() - began
                capability=store.capability
                data=dict(source=asdict(self.source.capability),annual=asdict(self.lab.capability),
                          v3=asdict(capability),version=2 if module is v2 else 3)
                store.close();self.lab.close();self.source.close()
                try:
                    with tempfile.TemporaryDirectory(prefix='stage119c-benchmark-') as private:
                        summary=support.worker(data,Path(private),'benchmark')
                finally:
                    stack,source,lab=support.source_resume(data)
                    type(self).source,type(self).lab=source,lab
                    stack.pop_all()
                    for existing in self.stores:existing.lab=lab
                summary['create_seconds']=created
                summary['parent_cpu_seconds']=process_time()-cpu
                reopened=module.FictionalBracketStore.resume(capability,self.lab,fictional_opt_in=True)
                self.stores.append(reopened)
                view=reopened.snapshot()
                self.assertTrue(view.complete)
                self.assertEqual(size-1,len(view.results));self.assertEqual(size,len(view.ranks))
                self.assertEqual(size-1,sum(row[2] for row in view.ranks))
                self.assertFalse(view.official_year_verified);self.assertFalse(view.product_season_start_authorized)
                if module is v2:
                    self.legacy_pins[str(reopened.db_path)]=pin(reopened.db_path)
                self.bench[label] = summary
                if module is v3:
                    self.completed[size] = reopened
                    self.assertEqual('COMPLETE', reopened.state)
            before, after = self.bench[f'v2_{size}']['play_seconds'], self.bench[f'v3_{size}']['play_seconds']
            self.bench[f'improvement_{size}'] = dict(measured_percent=(before - after) / before * 100,
                comparison='same runner/source/environment/request, distinct scenario scope and match IDs; no RNG equivalence claim')
        MEASUREMENTS['real_comparison'] = self.bench

    def test_02_trust_input_errors_k_boundary_final_audit_and_rollback_anchor(self):
        store = self.fresh()
        first = store.db_path.read_bytes()
        match = store.next_input()
        with self.assertRaises(ValueError):
            store.append(replace(match, day='2027-01-01'), _run(match, match.match_seed))
        self.assertEqual('REVOKED', store.state)
        for operation in (store.snapshot, store.next_input, store.receipt, store.play_next):
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(first, store.db_path.read_bytes())
        t = perf_counter(); store.full_audit(); revoked_cost = perf_counter() - t
        for bad in (replace(match,sequence=2),replace(match,namespace='fictional:foreign'),
                    replace(match,competition_id='LAB119:foreign'),replace(match,match_seed=match.match_seed+1),
                    replace(match,previous_chain_sha256='f'*64),replace(match,version=v2.INPUT_VERSION)):
            with self.assertRaises(ValueError):store.append(bad,_run(match,match.match_seed))
            self.assertEqual('REVOKED',store.state);self.assertEqual(first,store.db_path.read_bytes())
            store.full_audit()
        foreign=v3.FictionalBracketStore(self.lab,self.owner(),self.request8,
            scenario_seed=v3.SEED+1,fictional_opt_in=True)
        self.stores.append(foreign)
        capability=store.capability;store.close()
        before=files(store.db_path.parent, stores=(store,))
        with self.assertRaises(ValueError):
            v3.FictionalBracketStore.resume(replace(capability,contract_json=foreign.capability.contract_json),
                self.lab,fictional_opt_in=True)
        self.assertEqual(before,files(store.db_path.parent, stores=(store,)))
        store=v3.FictionalBracketStore.resume(capability,self.lab,fictional_opt_in=True)
        self.stores.append(store)
        mutable_request=replace(self.request8,seeds=replace(self.request8.seeds,
            seeds=tuple([team,rank] for team,rank in self.request8.seeds.seeds)))
        mutable=v3.FictionalBracketStore(self.lab,self.owner(),mutable_request,fictional_opt_in=True)
        self.stores.append(mutable);unchanged=mutable.db_path.read_bytes()
        detached=mutable.snapshot()
        with self.assertRaises(TypeError):detached.request.seeds.seeds[0][1]=99
        mutable.next_input()
        old_rank=mutable_request.seeds.seeds[0][1]
        mutable_request.seeds.seeds[0][1]=old_rank+1
        with self.assertRaises(ValueError):mutable.next_input()
        self.assertEqual('REVOKED',mutable.state);self.assertEqual(unchanged,mutable.db_path.read_bytes())
        mutable_request.seeds.seeds[0][1]=old_rank
        with self.assertRaises(ValueError):mutable.snapshot()
        mutable.full_audit()
        store.play_next(); receipt1 = store.receipt(); prefix1 = store.db_path.read_bytes()
        store.play_next(); latest = store.receipt()
        store.close(); store.db_path.write_bytes(prefix1)
        before = files(store.db_path.parent, stores=(store,))
        with self.assertRaises(ValueError):
            v3.FictionalBracketStore.resume(store.capability, self.lab, fictional_opt_in=True, anchor=latest)
        self.assertEqual(before, files(store.db_path.parent, stores=(store,)))
        for anchor in (None, receipt1):
            reopened = v3.FictionalBracketStore.resume(store.capability, self.lab,
                fictional_opt_in=True, anchor=anchor)
            self.assertEqual(1, len(reopened.snapshot().results)); reopened.close()
        # A 16-team store reaches K=8: use an unfinished, independently audited prefix.
        bound = v3.FictionalBracketStore(self.lab, self.owner(), self.requests[16], fictional_opt_in=True)
        self.stores.append(bound)
        counts, timings = [], []
        original = bound.full_audit
        def counted():
            t = perf_counter()
            result = original()
            timings.append(perf_counter() - t); counts.append(len(bound._results))
            return result
        with patch.object(bound, 'full_audit', counted):
            for _ in range(15): bound.play_next()
        self.assertEqual([8, 14, 15], counts)
        MEASUREMENTS['audit_boundaries'] = dict(K=v3.K, audited_sequences=counts, seconds=timings,
            exception_recovery_seconds=revoked_cost, anchor_latest_refused=True,
            anchor_missing_or_stale_rollback_detection=False)

    def test_03_schema_header_rows_chain_indexes_raw_write_refusals_preserve_bytes(self):
        store = self.fresh(); store.play_next()
        original = store.db_path.read_bytes()
        refused = []
        def sql_change(statements):
            with closing(sqlite3.connect(store.db_path)) as con:
                for sql, params in statements: con.execute(sql, params)
                con.commit()
        def edit(table, sql, params=()):
            trigger = table + '_update'
            definition = next(s for s in v3.DDL if s.startswith('CREATE TRIGGER ' + trigger + ' '))
            sql_change([(f'DROP TRIGGER {trigger}', ()), (sql, params), (definition, ())])
        def forge_result():
            match=v3._input(store._prepared,(),store._heads[0])
            other=_run(match,match.match_seed+1)
            forged=replace(other,run_seed=match.match_seed)
            event_oracle(forged,match)  # Valid events/full-A, but not the fixed seeded execution.
            raw=forged.to_json()
            row=store._heads[0]
            head=v3._chain(row,codec.digest(codec.canonical(match.to_dict())),codec.digest(raw))
            edit('v3_matches','UPDATE v3_matches SET result_json=?,result_sha256=?,chain_sha256=?',
                 (raw,codec.digest(raw),head))
            edit('v3_advancement','UPDATE v3_advancement SET team_id=?',(forged.winner_id,))
        cases = {
            'header_magic': lambda: store.db_path.write_bytes(b'BROKEN' + original[6:]),
            'header_journal': lambda: store.db_path.write_bytes(original[:18] + b'\x02\x02' + original[20:]),
            'application_id': lambda: sql_change([('PRAGMA application_id=0', ())]),
            'user_version': lambda: sql_change([('PRAGMA user_version=2', ())]),
            'drop_trigger': lambda: sql_change([('DROP TRIGGER v3_matches_update', ())]),
            'unknown_table': lambda: sql_change([('CREATE TABLE external_records (x)', ())]),
            'valid_events_result_rehashed_chain': forge_result,
            'chain_forgery': lambda: edit('v3_matches', "UPDATE v3_matches SET chain_sha256=?", ('a'*64,)),
            'input_forgery': lambda: edit('v3_matches', "UPDATE v3_matches SET input_json='{}',input_sha256=?", (codec.digest('{}'),)),
            'result_and_sha': lambda: edit('v3_matches', "UPDATE v3_matches SET result_json='{}',result_sha256=?", (codec.digest('{}'),)),
            'player_reattribution': lambda: edit('v3_players', "UPDATE v3_players SET origin_school_id='forged'"),
            'advancement': lambda: edit('v3_advancement', "UPDATE v3_advancement SET team_id='forged'"),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                mutate(); before = files(store.db_path.parent, stores=(store,))
                with self.assertRaises((ValueError, sqlite3.DatabaseError)):
                    store.snapshot()
                self.assertEqual('REVOKED', store.state)
                self.assertEqual(before, files(store.db_path.parent, stores=(store,)))
                with self.assertRaises((ValueError, sqlite3.DatabaseError, KeyError, TypeError)):
                    store.full_audit()
                self.assertEqual(before, files(store.db_path.parent, stores=(store,)))
                store.db_path.write_bytes(original); store.full_audit(); refused.append(name)
        # New final-only rows are not exempt from full-table rederivation.
        complete = self.completed[16]
        complete_bytes = complete.db_path.read_bytes()
        for table, column in (('v3_ranks', 'wins'), ('v3_acceptance', 'games')):
            trigger = table + '_update'
            with closing(sqlite3.connect(complete.db_path)) as con:
                con.execute(f'DROP TRIGGER {trigger}')
                con.execute(f'UPDATE {table} SET {column}={column}+1')
                con.execute(next(s for s in v3.DDL if s.startswith('CREATE TRIGGER '+trigger+' ')))
                con.commit()
            before = files(complete.db_path.parent, stores=(complete,))
            with self.assertRaises(ValueError): complete.snapshot()
            with self.assertRaises(ValueError): complete.full_audit()
            self.assertEqual(before, files(complete.db_path.parent, stores=(complete,)))
            complete.db_path.write_bytes(complete_bytes); complete.full_audit(); refused.append(table)
        # Raw write while the read transaction holds a SHARED lock must fail too.
        def raw(at):
            if at == 'during_readback':
                data = store.db_path.read_bytes()
                store.db_path.write_bytes(data[:-1] + bytes((data[-1] ^ 1,)))
        with self.assertRaises(ValueError): store.play_next(fault=raw)
        self.assertEqual('REVOKED', store.state)
        MEASUREMENTS['tamper_refusals'] = refused + ['raw_write_during_readback']

    def test_04_sidecars_identity_hardlinks_lease_and_version_capabilities(self):
        store = self.fresh()
        for name in (v3.DATABASE+'-journal', v3.DATABASE+'-wal', v3.DATABASE+'-shm', v2.DATABASE, v1.DATABASE, 'unknown'):
            path=store.db_path.parent/name; path.write_bytes(b'not recovered')
            before=files(store.db_path.parent, stores=(store,))
            with self.assertRaises(ValueError): store.next_input()
            self.assertEqual(before,files(store.db_path.parent, stores=(store,))); path.unlink(); store.full_audit()
        lease=store.db_path.parent/v3.LEASE
        stream=store._lease.file
        stream.seek(0);stream.write(b'1');stream.seek(0)
        before=files(store.db_path.parent, stores=(store,))
        with self.assertRaises(ValueError): store.snapshot()
        self.assertEqual(before,files(store.db_path.parent, stores=(store,)))
        stream.seek(0);stream.write(b'0');stream.seek(0);store.full_audit()
        old_v2=next(s for s in self.stores if type(s) is v2.FictionalBracketStore)
        with self.assertRaises(ValueError):
            v3.FictionalBracketStore.resume(old_v2.capability,self.lab,fictional_opt_in=True)
        for module in (v1, v2):
            with self.assertRaises(ValueError):
                module.FictionalTournamentStore.resume(store.capability,self.lab,fictional_opt_in=True) if module is v1 else module.FictionalBracketStore.resume(store.capability,self.lab,fictional_opt_in=True)
        with self.assertRaises(ValueError):
            v3.FictionalBracketStore.resume(self.old.capability,self.lab,fictional_opt_in=True)
        # Test actual wrong-format bytes under the expected filename, not only capability types.
        modern_copy=self.fresh();modern_bytes=modern_copy.db_path.read_bytes();modern_copy.close()
        for legacy in (self.old,old_v2):
            modern_copy.db_path.write_bytes(legacy.db_path.read_bytes())
            before=files(modern_copy.db_path.parent, stores=(modern_copy,))
            with self.assertRaises(ValueError):
                v3.FictionalBracketStore.resume(modern_copy.capability,self.lab,fictional_opt_in=True)
            self.assertEqual(before,files(modern_copy.db_path.parent, stores=(modern_copy,)))
        for module,cls,request in ((v1,v1.FictionalTournamentStore,self.old.request),
                                   (v2,v2.FictionalBracketStore,self.request8)):
            legacy_copy=cls(self.lab,self.owner(),request,fictional_opt_in=True)
            self.stores.append(legacy_copy);legacy_copy.close()
            legacy_copy.db_path.write_bytes(modern_bytes);before=files(legacy_copy.db_path.parent, stores=(legacy_copy,))
            with self.assertRaises(ValueError):
                cls.resume(legacy_copy.capability,self.lab,fictional_opt_in=True)
            self.assertEqual(before,files(legacy_copy.db_path.parent, stores=(legacy_copy,)))
        with self.assertRaises(ValueError):
            v3.FictionalBracketStore.resume(store.capability,self.lab,fictional_opt_in=True)
        with tempfile.TemporaryDirectory() as temp:
            alias=Path(temp)/'alias'
            if os.name=='nt':
                subprocess.run(['cmd','/c','mklink','/J',str(alias),str(store.db_path.parent)],check=True,capture_output=True)
            else:
                alias.symlink_to(store.db_path.parent,target_is_directory=True)
            fake=v3.FictionalBracketStore.__new__(v3.FictionalBracketStore)
            fake.db_path=alias/v3.DATABASE
            fake.capability=replace(store.capability,root=str(alias))
            try:
                with self.assertRaises(ValueError): fake._guard()
            finally:
                alias.rmdir() if os.name=='nt' else alias.unlink()
        with tempfile.TemporaryDirectory() as temp:
            linked=Path(temp)/'linked'
            os.link(store.db_path,linked)
            try:
                with self.assertRaises(ValueError): store.snapshot()
            finally: linked.unlink()
        store.full_audit()
        # PID rejection is exercised with a true fork where available, never skipped.
        if hasattr(os,'fork'):
            pid=os.fork()
            if pid==0:
                try: store.snapshot()
                except ValueError:
                    try: store.full_audit()
                    except ValueError: os._exit(0 if store.state=='REVOKED' else 2)
                    os._exit(4)
                os._exit(3)
            _, status=os.waitpid(pid,0); self.assertEqual(0,os.waitstatus_to_exitcode(status))
            fork='native fork refused'
        else:
            with patch.object(v3.os,'getpid',return_value=os.getpid()+1):
                with self.assertRaises(ValueError): store.snapshot()
            fork='Windows has no fork; PID mismatch simulated'
            store.full_audit()
        with tempfile.TemporaryDirectory() as temp:
            replacement=Path(temp)/'replacement'
            replacement.write_bytes(store.db_path.read_bytes())
            if os.name=='nt':
                with self.assertRaises(OSError): os.replace(replacement,store.db_path)
                windows_pin=True
            else:
                os.replace(replacement,store.db_path)
                with self.assertRaises(ValueError): store.snapshot()
                windows_pin=False
        MEASUREMENTS['platform_guards']=dict(fork=fork,native_windows_handle_pin=windows_pin,
            lease_double_open_refused=True,hardlink_refused=True,unknown_sidecars_refused=True)

    def test_05_transaction_rollback_postcommit_read_failure_ack_loss(self):
        store=self.fresh(); match=store.next_input(); result=_run(match,match.match_seed)
        original=store.db_path.read_bytes()
        def before(at):
            if at=='before_commit': raise RuntimeError('precommit fault')
        with self.assertRaises(RuntimeError): store.append(match,result,fault=before)
        self.assertEqual(original,store.db_path.read_bytes()); self.assertEqual('REVOKED',store.state)
        store.full_audit()
        def after(at):
            if at=='after_commit': raise RuntimeError('ACK lost')
        with self.assertRaises(RuntimeError): store.append(match,result,fault=after)
        self.assertEqual('REVOKED',store.state); store.full_audit()
        self.assertIs(False,store.append(match,result))
        match=store.next_input(); result=_run(match,match.match_seed)
        with patch.object(store,'_readback',side_effect=OSError('postcommit read failure')):
            with self.assertRaises(OSError): store.append(match,result)
        self.assertEqual('REVOKED',store.state); store.full_audit()
        self.assertEqual(2,len(store.snapshot().results)); self.assertIs(False,store.append(match,result))

    def test_06_controlled_fixture_content_comparison_and_readonly_history(self):
        store=self.fresh()
        wanted=store.next_input();detached=store.snapshot();detached.bracket.games=()
        self.assertEqual(wanted,store.next_input())
        controlled=v2.BracketMatchInput(v2.INPUT_VERSION,**{k:v for k,v in asdict(store.next_input()).items()
            if k not in ('version','previous_chain_sha256','team1','team2')},
            previous_results_sha256='controlled',team1=store.next_input().team1,team2=store.next_input().team2)
        modern=store.next_input()
        old_result,new_result=_run(controlled,controlled.match_seed),_run(modern,modern.match_seed)
        event_oracle(old_result,controlled); event_oracle(new_result,modern)
        left,right=old_result.to_dict(),new_result.to_dict()
        left.pop('input_sha256');right.pop('input_sha256');self.assertEqual(left,right)
        complete=self.completed[32]
        before=pin(complete.db_path)
        view=complete.snapshot(practice_store=self.practice,v1_store=self.old)
        for entry in view.request.entries.teams:
            record=view.team(entry.entry_team_id)
            for sid,_ in entry.programs:
                school=view.school(sid)
                if record['joint']:
                    self.assertEqual(0,school['standalone_wins']); self.assertEqual(0,school['standalone_losses'])
            for pid in entry.player_ids:
                person=view.player(pid)
                self.assertEqual(pid,person['player_id']); self.assertIn(person['origin_school_id'],[s for s,_ in entry.programs])
        from phase2_engine.fictional_scenario_history_v3 import scenario_history
        history=scenario_history((self.completed[16],complete),practice_store=self.practice,v1_store=self.old)
        self.assertEqual([31,1,2,15,31],[row['matches'] for row in history.stream_summary()])
        for entry in view.request.entries.teams:
            for sid,_ in entry.programs: history.school(sid)
        history.player(view.request.entries.teams[0].player_ids[0])
        self.assertEqual(before,pin(complete.db_path))
        MEASUREMENTS['comparison_oracles']=dict(controlled_fixture_content_equal=True,
            real_v2_v3_random_equivalence_claimed=False, real_v3_sizes=[16,32],
            checked=['participants','score','innings','all events','full-A batting/pitching',
                     'school/player permanent IDs','joint win separation','all advancement/ranks'])

    def test_07_legacy_saved_db_master_and_catalog_bytes_unchanged(self):
        for path,digest in {**self.source_pins,**self.legacy_pins,**self.master}.items():
            self.assertEqual(digest,pin(Path(path),stores=(self.lab,self.source.store,*self.stores)),path)
        self.assertEqual(self.catalog,_compatibility(ROOT))
        self.assertEqual(338,len(self.catalog))
        self.assertEqual(106,sum(Path(p).suffix=='.csv' for p in self.master))
        self.assertEqual(2,len(self.old.snapshot().results))
        self.assertEqual(1,len(self.practice.snapshot().results))
        for store in self.stores:
            if type(store) is v2.FictionalBracketStore and not store.closed:
                before=pin(store.db_path);self.assertTrue(store.snapshot().complete)
                self.assertEqual(before,pin(store.db_path))
        MEASUREMENTS['legacy_bytes']=dict(catalog_files=338,master_csv=106,source_v1_db_bytes_unchanged=True)
        manifest=[]
        for row in self.completed[32]._manifest:
            path=Path(row.path)
            if path.is_relative_to(ROOT):label='project/'+str(path.relative_to(ROOT))
            elif path.is_relative_to(Path(self.lab.capability.root)):
                label='annual/'+str(path.relative_to(Path(self.lab.capability.root)))
            else:label='saved2026/'+str(path.relative_to(Path(self.source.capability.root)))
            manifest.append(dict(path=label,identity=row.identity,size=row.size,sha256=row.sha256))
        MEASUREMENTS['dependency_manifest']=dict(strategy='conservative closed inventory + reject undeclared open/sqlite reads',
            roots=['phase2_engine','game_core','config','data','owned annual','owned saved2026'],entries=manifest)


    def test_08_child_kill_hot_journal_ack_and_isolated_source_dependency_changes(self):
        store=self.fresh(); original=store.db_path.read_bytes(); capability=store.capability
        data=dict(source=asdict(self.source.capability),annual=asdict(self.lab.capability),v3=asdict(capability))
        store.close(); self.lab.close(); self.source.close()
        outcomes={}
        try:
            with tempfile.TemporaryDirectory(prefix='stage119c-worker-') as temp:
                private=Path(temp)
                outcomes['before_commit']=support.worker(data,private,'crash_before_commit')
                sidecar=store.db_path.parent/(v3.DATABASE+'-journal')
                self.assertTrue(sidecar.exists())
                before=files(store.db_path.parent, stores=(store,))
                stack,source,lab=support.source_resume(data)
                with stack:
                    with self.assertRaises(ValueError):
                        v3.FictionalBracketStore.resume(capability,lab,fictional_opt_in=True)
                self.assertEqual(before,files(store.db_path.parent, stores=(store,)))
                # This deletion/restoration belongs to the destructive test owner, never the API.
                sidecar.unlink(); store.db_path.write_bytes(original)
                outcomes['after_commit']=support.worker(data,private,'crash_after_commit')
                stack,source,lab=support.source_resume(data)
                with stack:
                    resumed=v3.FictionalBracketStore.resume(capability,lab,fictional_opt_in=True)
                    try:
                        self.assertEqual(1,len(resumed.snapshot().results))
                        match=v3._input(resumed._prepared,(),resumed._heads[0])
                        self.assertIs(False,resumed.append(match,_run(match,match.match_seed)))
                    finally: resumed.close()
                store.db_path.write_bytes(original)
                outcomes['isolated_dependencies']=support.worker(data,private,'isolated_dependencies',isolated=True)
        finally:
            stack,source,lab=support.source_resume(data)
            # Transfer reopened fixture handles to class cleanup, retaining original owners.
            type(self).source,type(self).lab=source,lab
            stack.pop_all()
            self.practice.lab,self.old.lab=lab,lab
            for s in self.completed.values(): s.lab=lab
        MEASUREMENTS['child_faults']=outcomes

    def test_09_every_public_read_idempotency_and_source_bytes_recheck(self):
        store=self.fresh();match=store.next_input();result=store.play_next()
        original=store.db_path.read_bytes()
        damaged=original[:-1]+bytes((original[-1]^1,))
        for label,operation in (('snapshot',store.snapshot),('next_input',store.next_input),
                                ('receipt',store.receipt),('idempotent',lambda:store.append(match,result))):
            store.db_path.write_bytes(damaged);before=files(store.db_path.parent, stores=(store,))
            with self.assertRaises(ValueError):operation()
            self.assertEqual('REVOKED',store.state);self.assertEqual(before,files(store.db_path.parent, stores=(store,)))
            store.db_path.write_bytes(original)
            with self.assertRaises(ValueError):store.snapshot()  # Restoration alone cannot reinstate trust.
            store.full_audit()
        source_path=self.lab.db_path;source_bytes=source_path.read_bytes()
        source_path.write_bytes(source_bytes[:-1]+bytes((source_bytes[-1]^1,)))
        before=source_path.read_bytes()
        try:
            with self.assertRaises(ValueError):store.snapshot()
            self.assertEqual('REVOKED',store.state);self.assertEqual(before,source_path.read_bytes())
        finally:source_path.write_bytes(source_bytes)
        store.full_audit()
        complete=self.completed[32]
        saved=complete.db_path.read_bytes()
        complete.db_path.write_bytes(saved[:-1]+bytes((saved[-1]^1,)))
        try:
            with self.assertRaises(ValueError):complete.snapshot()
            self.assertEqual('REVOKED',complete.state)
        finally:complete.db_path.write_bytes(saved)
        complete.full_audit()
        # Documented commit/readback gap: an old row can be changed before the read lock.
        # A pre-final full audit must prevent completion even if the new rows read back correctly.
        def gap(at):
            if at=='after_commit':
                with closing(sqlite3.connect(store.db_path)) as con:
                    con.execute('DROP TRIGGER v3_players_update')
                    con.execute("UPDATE v3_players SET origin_school_id='gap-forgery' WHERE match_id=?",(match.match_id,))
                    con.execute(next(sql for sql in v3.DDL if sql.startswith('CREATE TRIGGER v3_players_update ')))
                    con.commit()
        store.play_next(fault=gap)
        for _ in range(4):store.play_next()
        self.assertEqual(6,len(store.snapshot().results))
        before=files(store.db_path.parent, stores=(store,))
        with self.assertRaises(ValueError):store.play_next()
        self.assertEqual('REVOKED',store.state);self.assertEqual(before,files(store.db_path.parent, stores=(store,)))
        MEASUREMENTS['residual_window']=dict(old_row_write_can_pass_new_row_readback=True,
            final_acceptance_prevented_by_full_audit=True,absolute_cryptographic_authenticity_claimed=False)
