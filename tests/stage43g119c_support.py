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
            store = v3.FictionalBracketStore.resume(cap(v3.BracketCapability, data['v3']), lab,
                fictional_opt_in=True, anchor=v3.AppendReceipt(**data['anchor']) if data.get('anchor') else None)
            stack.callback(store.close)
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
        capture_output=True, text=True, encoding='utf-8', timeout=600)
    expected = 73 if action.startswith('crash_') else 0
    if result.returncode != expected:
        raise AssertionError(f'v3 child {action}: exit {result.returncode}: {result.stderr[-4000:]}')
    return dict(exit_code=73) if expected else json.loads(output.read_text(encoding='utf-8'))


if __name__ == '__main__':
    child(*sys.argv[1:4])
