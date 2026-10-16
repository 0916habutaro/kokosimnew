"""Private capability transport between exited Python processes, test fixtures only."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def worker_input(source, annual):
    return dict(source=asdict(source.capability), annual=asdict(annual.capability))


def run_worker(payload, private_root, *, limit=33, crash=None):
    path = private_root / 'capabilities.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(path), str(limit), crash or ''],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=180,
        env=dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(ROOT)))
    if crash:
        if result.returncode != 73:
            raise AssertionError('自己生成年度試験のprocess crashに失敗')
        return None
    if result.returncode:
        path.with_suffix('.private-error').write_text(result.stderr, encoding='utf-8')
        raise AssertionError('自己生成年度試験の別プロセス再開に失敗（詳細は一時領域内のみ）')
    return json.loads(result.stdout)


def resume(payload):
    from phase2_engine.yamanashi_annual_rosters import (
        SelfCreated2026, AnnualRosterLab, _SourceCapability, _AnnualCapability,
    )
    src = payload['source']
    source_cap = _SourceCapability(src['root'], tuple(src['root_identity']), src['demo_id'])
    target = payload['annual']
    target_cap = _AnnualCapability(target['root'], tuple(target['root_identity']), tuple(target['file_identity']),
        tuple(target['lease_identity']), source_cap, target['contract_json'])
    source = SelfCreated2026.resume(source_cap)
    try:
        return source, AnnualRosterLab.resume(target_cap, source)
    except BaseException:
        source.close()
        raise


if __name__ == '__main__':
    source, annual = resume(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
    try:
        crash = sys.argv[3]
        if crash == 'before_acceptance_commit':
            import sqlite3
            from unittest.mock import patch
            original = sqlite3.connect
            def connect(*args, **kwargs):
                con = original(*args, **kwargs)
                con.execute('PRAGMA cache_size=1')
                return con
            patcher = patch.object(sqlite3, 'connect', connect)
            patcher.start()
        def fault(at, school):
            if at == crash:
                os._exit(73)
        result = annual.advance(limit=int(sys.argv[2]), fault=fault)
        if result['accepted']:
            view = annual.browse()
            result['browsed_schools'] = len([view.school(sid, year=2027) for sid in view._rosters[2027]])
        print(json.dumps(result))
    finally:
        annual.close()
        source.close()
