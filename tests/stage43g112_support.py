"""Small reviewed master fixture and private exited-process transport."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NAGANO = ('SCH001636', 'SCH001637', 'SCH001638', 'SCH001639')
SEED = 430112


def source():
    from phase2_engine.repository import DataRepository
    from phase2_engine.school_roster_trial import MasterRosterSandbox
    return MasterRosterSandbox(DataRepository(ROOT / 'data'), NAGANO, year=2026, career_seed=SEED)


def worker(lab, private, crash=''):
    path = private / 'capability.json'
    path.write_text(json.dumps(asdict(lab.capability)), encoding='utf-8')
    p = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(path), crash],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
        env=dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(ROOT)))
    if crash:
        if p.returncode != 73:
            raise AssertionError('private worker did not reach injected crash')
    elif p.returncode:
        path.with_suffix('.private-error').write_text(p.stderr, encoding='utf-8')
        raise AssertionError('private roster worker resume failed; details stay in owned temporary root')
    else:
        return json.loads(p.stdout)


if __name__ == '__main__':
    from phase2_engine.school_roster_trial import SchoolRosterTrial, TrialCapability
    data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    for k in ('root_identity', 'file_identity', 'lease_identity'):
        data[k] = tuple(data[k])
    if sys.argv[2] == 'before_acceptance_commit':
        import sqlite3
        from unittest.mock import patch
        original = sqlite3.connect
        def connect(*args, **kwargs):
            con = original(*args, **kwargs)
            con.execute('PRAGMA cache_size=1')
            return con
        patcher = patch.object(sqlite3, 'connect', connect)
        patcher.start()
    trial = SchoolRosterTrial.resume(TrialCapability(**data), source())
    try:
        def fault(at, sid):
            if at == sys.argv[2]:
                os._exit(73)
        print(json.dumps(trial.advance(career_seed=SEED, fault=fault)))
    finally:
        trial.close()
