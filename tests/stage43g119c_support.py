"""Explicit heavy-test helpers and child transport; never unittest-discovered."""
from contextlib import ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[1]


def cap(cls, value):
    return cls(value['root'], tuple(value['root_identity']), tuple(value['file_identity']),
               tuple(value['lease_identity']), value['contract_json'])


def source_resume(data):
    from phase2_engine import yamanashi_annual_rosters as annual
    stack = ExitStack()
    try:
        item = data['source']
        source_cap = annual._SourceCapability(item['root'], tuple(item['root_identity']), item['demo_id'])
        source = annual.SelfCreated2026.resume(source_cap)
        stack.callback(source.close)
        item = data['annual']
        annual_cap = annual._AnnualCapability(item['root'], tuple(item['root_identity']), tuple(item['file_identity']),
            tuple(item['lease_identity']), source_cap, item['contract_json'])
        lab = annual.AnnualRosterLab.resume(annual_cap, source)
        stack.callback(lab.close)
        return stack, source, lab
    except BaseException:
        stack.close()
        raise


def child(data_path, action, output_path):
    from unittest.mock import patch
    from phase2_engine import saved_fictional_bracket_v3 as v3
    from phase2_engine import saved_fictional_bracket as v2
    data = json.loads(Path(data_path).read_text(encoding='utf-8'))
    with ExitStack() as outer:
        if action == 'crash_before_commit':
            connect = sqlite3.connect
            def spilling(*args, **kwargs):
                con = connect(*args, **kwargs)
                con.execute('PRAGMA cache_size=1')
                return con
            outer.enter_context(patch.object(sqlite3, 'connect', spilling))
        stack, source, lab = source_resume(data)
        with stack:
            module = v2 if data.get('version') == 2 else v3
            options = dict(anchor=v3.AppendReceipt(**data['anchor']) if data.get('anchor') else None) if module is v3 else {}
            began=perf_counter()
            store = module.FictionalBracketStore.resume(cap(module.BracketCapability, data['v3']), lab,
                fictional_opt_in=True, **options)
            resumed=perf_counter()-began
            stack.callback(store.close)
            if action == 'benchmark':
                out=benchmark(store,module)
                out['initial_resume_seconds']=resumed
                Path(output_path).write_text(json.dumps(out),encoding='utf-8')
                return
            before = len(store.snapshot().results)
            if action.startswith('crash_'):
                def fault(at):
                    if action == 'crash_' + at:
                        os._exit(73)
                store.play_next(fault=fault)
                raise AssertionError('hard-exit boundary not reached')
            if action == 'isolated_dependencies':
                # This action is run with a physically isolated engine/config/data tree.
                paths = [ROOT / 'config/match/match_simulation_v1.json',
                         next((ROOT / 'data').rglob('*.csv'))]
                refused = []
                for path in paths:
                    original = path.read_bytes()
                    path.write_bytes(original + b'\n')
                    try:
                        for operation in (store.snapshot, store.next_input, store.receipt):
                            try:
                                operation()
                            except ValueError:
                                assert store.state == 'REVOKED'
                            else:
                                raise AssertionError('changed dependency was accepted')
                        refused.append(str(path.relative_to(ROOT)))
                    finally:
                        path.write_bytes(original)
                    store.full_audit()
                # An added, unmanifested dynamic read must revoke before a result is exposed.
                unknown = ROOT / 'outside-dependency'
                unknown.write_bytes(b'unknown')
                def dynamic(*args):
                    return unknown.read_bytes()
                with patch.object(v3, '_run', dynamic):
                    try:
                        store.play_next()
                    except ValueError:
                        assert store.state == 'REVOKED'
                    else:
                        raise AssertionError('unmanifested read was accepted')
                out = dict(refused=refused, unknown_dynamic_read_refused=True)
            else:
                match = store.next_input()
                result = store.play_next()
                assert store.append(match, result) is False
                out = dict(before=before, after=len(store.snapshot().results),
                           idempotent=False, receipt=asdict(store.receipt()))
            Path(output_path).write_text(json.dumps(out), encoding='utf-8')


def worker(data, private, action, *, isolated=False):
    path, output = private / 'caps.json', private / 'result.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    root = ROOT
    if isolated:
        import shutil
        root = private / 'isolated'
        root.mkdir()
        for name in ('phase2_engine', 'game_core', 'config', 'data'):
            shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns('__pycache__'))
        (root / 'tests').mkdir()
        shutil.copy2(__file__, root / 'tests' / Path(__file__).name)
    command = [sys.executable, str(root / 'tests' / Path(__file__).name), str(path), action, str(output)]
    result = subprocess.run(command, cwd=root,
        env=dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True, text=True, encoding='utf-8', timeout=1800)
    expected = 73 if action.startswith('crash_') else 0
    if result.returncode != expected:
        raise AssertionError(f'v3 child {action}: exit {result.returncode}: {result.stderr[-4000:]}')
    return dict(exit_code=73) if expected else json.loads(output.read_text(encoding='utf-8'))


def install_sql_meter(stack, meter, store):
    """Measure only this target DB's transaction operations, not source SQL."""
    from unittest.mock import patch
    original = sqlite3.connect
    class Connection(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            t=perf_counter()
            try: return super().execute(sql,parameters)
            finally:
                if getattr(self,'target',False):
                    label='insert' if sql.startswith('INSERT') else 'begin_lock' if sql=='BEGIN IMMEDIATE' else 'select' if sql.startswith('SELECT') else 'sql_other'
                    meter.calls[label]+=1;meter.seconds[label]+=perf_counter()-t
        def executemany(self, sql, parameters, /):
            t=perf_counter()
            try: return super().executemany(sql,parameters)
            finally:
                if getattr(self,'target',False):
                    meter.calls['insert']+=1;meter.seconds['insert']+=perf_counter()-t
        def commit(self):
            t=perf_counter()
            try: return super().commit()
            finally:
                if getattr(self,'target',False):
                    meter.calls['commit']+=1;meter.seconds['commit']+=perf_counter()-t
        def __exit__(self,*args):
            active=self.in_transaction;t=perf_counter()
            try: return super().__exit__(*args)
            finally:
                if active and getattr(self,'target',False):
                    meter.calls['commit_or_rollback']+=1;meter.seconds['commit_or_rollback']+=perf_counter()-t
    def connect(database,*args,**kwargs):
        kwargs.setdefault('factory',Connection)
        con=original(database,*args,**kwargs)
        if isinstance(con,Connection):
            raw=str(database).split('?')[0]
            con.target=raw in (str(store.db_path),store.db_path.as_uri())
        return con
    stack.enter_context(patch.object(sqlite3,'connect',connect))


def benchmark(store,module):
    """One benchmark per fresh child; RSS includes that child's source/replay fixture."""
    from stage43g118_support import Meter,peak_rss_kib
    from phase2_engine import saved_fictional_bracket_v3 as v3
    from phase2_engine import saved_fictional_tournament as v1
    from phase2_engine import yamanashi_annual_rosters as annual
    from phase2_engine import fictional_v3_dependencies as deps
    from phase2_engine.registered_match_driver import _run
    from phase2_engine.registered_full_a_oracle import event_oracle
    meter=Meter(); games=[];cpu=process_time()
    size=len(store._prepared[1].slots) if module is v3 else len(store.snapshot().plan.slots)
    with ExitStack() as stack:
        if module is not v3:
            meter.install(stack)
        else:
            for name in ('_guard','_check_trust','full_audit','_readback'):
                meter.wrap(stack,store,name,name)
            meter.wrap(stack,deps,'check','source_manifest')
            meter.wrap(stack,annual,'_sha','file_digest_inclusive')
            meter.wrap(stack,v3,'_incremental_rows','incremental_rows')
            meter.wrap(stack,v3,'progression','progression')
            meter.wrap(stack,v1,'_validate','new_or_audit_validation')
            meter.wrap(stack,v3,'_run','new_game_compute')
        from unittest.mock import patch
        digest_original=annual._sha
        def digest(path):
            t=perf_counter()
            try:return digest_original(path)
            finally:
                if Path(path)==store.db_path:
                    meter.calls['db_digest']+=1;meter.seconds['db_digest']+=perf_counter()-t
        stack.enter_context(patch.object(annual,'_sha',digest))
        install_sql_meter(stack,meter,store)
        for sequence in range(1,size):
            match=store.next_input();meter.take()
            t,c=perf_counter(),process_time();result=store.play_next()
            games.append(dict(sequence=sequence,seconds=perf_counter()-t,cpu_seconds=process_time()-c,
                db_bytes=store.db_path.stat().st_size,layers=meter.take()))
            assert result==_run(match,match.match_seed)
            event_oracle(result,match)
            if module is v3:
                before=annual._sha(store.db_path)
                view=store.snapshot()
                expected,heads=v3._audit_rows(store._prepared,store.request,view.results)
                with __import__('contextlib').closing(sqlite3.connect(store.db_path.as_uri()+'?mode=ro',uri=True)) as con:
                    for table,wanted in expected.items():
                        assert wanted==sorted(con.execute(f'SELECT * FROM {table}').fetchall()),table
                assert heads[-1]==store.receipt().chain_head
                assert before==annual._sha(store.db_path)
            if sequence==1:assert store.append(match,result) is False
    t=perf_counter();view=store.snapshot();snapshot=perf_counter()-t
    assert view.complete and len(view.results)==size-1 and len(view.ranks)==size
    capability,lab=store.capability,store.lab
    options=dict(anchor=store.receipt()) if module is v3 else {}
    store.close();t=perf_counter()
    reopened=module.FictionalBracketStore.resume(capability,lab,fictional_opt_in=True,**options)
    resumed=perf_counter()-t
    try:
        with __import__('contextlib').closing(sqlite3.connect(reopened.db_path.as_uri()+'?mode=ro',uri=True)) as con:
            capacity=dict(page_count=con.execute('PRAGMA page_count').fetchone()[0],
                page_size=con.execute('PRAGMA page_size').fetchone()[0],
                rows={table:con.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in module.TABLES})
        return dict(games=games,play_seconds=sum(g['seconds'] for g in games),snapshot_seconds=snapshot,
            resume_seconds=resumed,db_bytes=reopened.db_path.stat().st_size,capacity=capacity,
            child_cpu_seconds=process_time()-cpu,child_peak_rss_kib=peak_rss_kib(),child_pid=os.getpid(),
            rss_scope='fresh benchmark child including source/resume/oracle; cumulative process high-water',
            first_seconds=games[0]['seconds'],middle_seconds=games[(size-1)//2]['seconds'],
            final_seconds=games[-1]['seconds'],source_fixture='same owned source',runner='registered_match_driver._run')
    finally:reopened.close()


if __name__ == '__main__':
    child(*sys.argv[1:4])
