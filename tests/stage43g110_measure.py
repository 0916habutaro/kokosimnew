"""Paired pinned Stage109/current measurement; only generated fixtures leave RAM.

Both child processes use the same interpreter, machine, seeds and 31-game path.
Private SQL/byte payloads stay in TemporaryDirectory; published JSON has no paths
or per-original digests. Timers are inclusive (nested categories must not be added).
"""
import argparse
from contextlib import closing, ExitStack
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from time import perf_counter
from unittest.mock import patch

BASE = '750a2f716e3518948f3b74d5dd6dffd39bad6118'
ROOT = Path(__file__).resolve().parents[1]


def worker(source, namespace, output, gui, resume_id=None, handoff=False):
    sys.path.insert(0, str(source))
    from phase2_engine import yamanashi_demo_store as demo
    from phase2_engine.yamanashi_demo_controller import DemoController
    metrics = {}
    def timed(owner, name, label):
        original = getattr(owner, name)
        def call(*args, **kwargs):
            start = perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                entry = metrics.setdefault(label, dict(calls=0, seconds=0.0))
                entry['calls'] += 1
                entry['seconds'] += perf_counter() - start
        return patch.object(owner, name, call)
    def elapsed(fn):
        start = perf_counter(); value = fn()
        return value, round(perf_counter() - start, 6)
    with ExitStack() as stack:
        for owner, name, label in ((demo, '_audit', 'audit_inclusive'), (demo, '_run', 'new_match_calculation'),
                (demo, '_rows', 'row_serialization'), (demo.DemoReader, 'snapshot', 'ro_read_verify'),
                (demo, 'fixed_authorities', 'authority_generation')):
            stack.enter_context(timed(owner, name, label))
        c = DemoController()
        root = history = None
        if gui:
            import tkinter as tk
            from phase2_engine.yamanashi_demo_tk import DemoHistory
            root = tk.Tk(); root.geometry('1240x900')
            history = DemoHistory(root, guard=lambda: c.store.reader._guard(),
                                  on_error=lambda: (_ for _ in ()).throw(AssertionError('Tk refusal')))
            root.update(); assert root.winfo_ismapped()
        try:
            if resume_id:
                c.use_namespace(namespace)
                before = next(namespace.glob('demo-*/demo.sqlite3')).read_bytes()
                snap, seconds = elapsed(lambda: c.execute('resume', demo_id=resume_id))
                assert c.store.db_path.read_bytes() == before
                report = dict(resume_seconds=seconds, committed=len(snap.results), readonly_bytes_unchanged=True)
                payloads=[]
                if handoff:
                    assert len(snap.results)==1
                    for _ in range(30): c.execute('one')
                    with closing(sqlite3.connect(c.store.db_path.as_uri()+'?mode=ro',uri=True)) as con:
                        payloads.append({table:con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                                         for table in demo.TABLES if table!='demo_metadata'})
                    report['continued_to_31']=c.snapshot.complete
            else:
                _, namespace_seconds = elapsed(lambda: c.use_namespace(namespace, create=True))
                snap, create_seconds = elapsed(lambda: c.execute('new'))
                did = c.store.demo_id
                games, renders, resumes, payloads = [], [], [], []
                transaction = {}
                def boundary(at):
                    if at == 'before_transaction': transaction['start'] = perf_counter()
                    if at == 'after_commit': transaction['seconds'] = perf_counter()-transaction['start']
                def render():
                    if history is None: return None
                    _, seconds = elapsed(lambda: (history.show(c.snapshot), root.update()))
                    stats = history.tables['stats']
                    history.book.select(stats.master); root.update()
                    _, selection = elapsed(lambda: (history.select('team'), root.update()))
                    # Measure the stats table too; return to the lightweight ranks tab.
                    history.book.select(history.tables['ranks'].master); root.update()
                    return dict(show_seconds=seconds, stats_selection_seconds=selection)
                for index in range(1 if handoff else 31):
                    before_metrics = {k:v['seconds'] for k,v in metrics.items()}
                    _, seconds = elapsed(lambda: c.execute('one', fault=boundary))
                    games.append(dict(committed=index+1, total_seconds=seconds,
                        transaction_inclusive_seconds=round(transaction['seconds'],6),
                        phases={k:round(v['seconds']-before_metrics.get(k,0),6) for k,v in metrics.items()}))
                    if index in (0,15,30):
                        rendered=render()
                        if rendered: renders.append(dict(committed=index+1, **rendered))
                        # Raw SQL full A + SHA, not the UI's saved label.
                        with closing(sqlite3.connect(c.store.db_path.as_uri()+'?mode=ro', uri=True)) as con:
                            for raw, sha, inp, inp_sha in con.execute(
                                    'SELECT result_json,result_sha256,input_json,input_sha256 FROM matches'):
                                assert demo.codec.digest(raw)==sha and demo.codec.digest(inp)==inp_sha
                            payloads.append({table:con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                                             for table in demo.TABLES if table!='demo_metadata'})
                        db=c.store.db_path
                        size=db.stat().st_size
                        c.close(); before=db.read_bytes()
                        # A completely different Python reader opens the same Stage109 bytes.
                        child=output.with_name(output.stem+f'-reader-{index}.json')
                        run_worker(ROOT, namespace, child, False, did)
                        independent=json.loads(child.read_text(encoding='utf-8'))['report']
                        assert independent['committed']==index+1 and db.read_bytes()==before
                        c=DemoController(); c.use_namespace(namespace)
                        _, restart=elapsed(lambda:c.execute('resume',demo_id=did))
                        assert db.read_bytes()==before
                        resumes.append(dict(committed=index+1,seconds=restart,database_bytes=size,
                                            independent_current_reader=independent))
                report=dict(namespace_seconds=namespace_seconds,create_seconds=create_seconds,
                    games=games,renders=renders,resumes=resumes,metrics=metrics)
                # Compare a list-search reference and actual writer on byte-identical
                # SQLite clones, using all 31 real prefix row sets, same fixed metadata.
                from phase2_engine.yamanashi_tournament_store import TournamentSnapshot
                from phase2_engine.yamanashi_tournament_oracle import progression_oracle
                snap=c.snapshot; metadata=c.store.capability.metadata
                reference=sqlite3.connect(':memory:'); actual=sqlite3.connect(':memory:')
                try:
                    for con in (reference,actual):
                        for sql in demo.SCHEMA: con.execute(sql)
                    previous={t:[] for t in demo.TABLES}
                    byte_equal=True; diff_seconds={'list':0.0,'set':0.0}
                    for count in range(len(snap.results)+1):
                        results=snap.results[:count]
                        ledger,ranks=progression_oracle(snap.plan,snap.registration,results)
                        current=demo._rows(TournamentSnapshot(snap.registration,snap.rosters,results,
                            snap.repo,snap.plan,ledger,ranks),metadata)
                        for con,kind in ((reference,'list'),(actual,'set')):
                            start=perf_counter()
                            if kind=='set' and hasattr(demo,'_append_rows'):
                                demo._append_rows(con,previous,current,lambda at:None)
                            else:
                                for table,rows in current.items():
                                    for row in rows:
                                        if row not in previous[table]:
                                            con.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in row)})',row)
                            con.commit(); diff_seconds[kind]+=perf_counter()-start
                        assert reference.serialize()==actual.serialize()
                        previous=current
                    report['row_diff']=dict(sqlite_bytes_identical_all32_prefixes=byte_equal,
                                            seconds=diff_seconds)
                finally: reference.close(); actual.close()
            output.write_text(json.dumps(dict(report=report,payloads=payloads,
                                             demo_id=c.store.demo_id)),encoding='utf-8')
        finally:
            c.close()
            if root is not None:
                history.guard=history.on_error=None
                root.destroy()


def run_worker(source, namespace, output, gui, did=None, handoff=False):
    args=[sys.executable,str(Path(__file__).resolve()),'--worker',str(source),str(namespace),str(output)]
    if gui: args+=['--gui']
    if did: args+=['--resume-id',did]
    if handoff: args+=['--handoff']
    run=subprocess.run(args,cwd=source,capture_output=True,timeout=1200,
        env=dict(os.environ,PYTHONUTF8='1'))
    if run.returncode:
        # Child traceback is kept local; never publish arbitrary payloads/paths.
        output.with_suffix('.private-error').write_bytes(run.stderr)
        raise AssertionError('paired generated-fixture measurement failed (private child diagnostics retained locally)')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',nargs=3,type=Path)
    parser.add_argument('--resume-id')
    parser.add_argument('--handoff',action='store_true')
    parser.add_argument('--gui',action='store_true')
    parser.add_argument('--require-windows',action='store_true')
    parser.add_argument('--json-output',type=Path)
    args=parser.parse_args()
    if args.worker:
        worker(*args.worker,args.gui,args.resume_id,args.handoff); return
    if args.require_windows and sys.platform!='win32': parser.error('native Windows required')
    if not args.json_output: parser.error('--json-output required')
    with tempfile.TemporaryDirectory(prefix='stage110-paired-') as temp:
        root=Path(temp); old=root/'old-main'; old.mkdir(); archive=root/'old.tar'
        with archive.open('wb') as out:
            subprocess.run(['git','archive',BASE],cwd=ROOT,stdout=out,check=True)
        with tarfile.open(archive) as inp: inp.extractall(old,filter='data')
        reports=[]; payloads=[]
        for label,source in (('baseline109',old),('stage110',ROOT)):
            output=root/(label+'.json')
            run_worker(source,root/(label+'-namespace'),output,args.gui)
            value=json.loads(output.read_text(encoding='utf-8'))
            reports.append(dict(version=label,**value['report'])); payloads.append(value['payloads'])
        assert payloads[0]==payloads[1], '31-game SQL/full-A/rank/history bytes differ'
        # True pinned Stage109 producer fully exits after one commit. The current
        # reader first proves zero writes, then appends the remaining 30 games.
        handoff_ns=root/'handoff-namespace'; handoff_output=root/'handoff-old.json'
        run_worker(old,handoff_ns,handoff_output,False,handoff=True)
        handoff=json.loads(handoff_output.read_text(encoding='utf-8'))
        run_worker(ROOT,handoff_ns,root/'handoff-new.json',False,handoff['demo_id'],handoff=True)
        continued=json.loads((root/'handoff-new.json').read_text(encoding='utf-8'))
        assert continued['report']['continued_to_31']
        assert continued['payloads'][0]==payloads[0][-1]
        report=dict(stage='43G-110',os=platform.system(),python=platform.python_version(),
            native_windows=sys.platform=='win32',mapped_tk=args.gui,paired=reports,
            all31_full_a_sql_bytes_equal=True,stage109_readonly_1_16_31_compatible=True,
            true_stage109_one_to_current31_sql_bytes_equal=True,
            private_metadata_excluded_from_cross_namespace_comparison=True,
            manual_user_windows_operation_verified=False,os_login_session_restart_verified=False,
            timer_categories='inclusive; do not add nested values',successful=True)
        with args.json_output.open('x',encoding='utf-8') as out:
            json.dump(report,out,ensure_ascii=False,indent=2);out.write('\n')
        # Same publication-safe aggregate as the artifact; no private payloads,
        # original digests, demo IDs or absolute paths enter the job log.
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
