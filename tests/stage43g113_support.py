"""Private exited-process transport; parent retains both TemporaryDirectory owners."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SEED = 430113


def worker(source, trial, private, *, at='', count=1):
    path = private / 'capability.json'
    path.write_text(json.dumps(dict(source=asdict(source.capability), target=asdict(trial.capability))), encoding='utf-8')
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(path), at, str(count)],
        cwd=ROOT, env=dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(ROOT)),
        capture_output=True, text=True, timeout=180)
    if result.returncode != (73 if at else 0):
        path.with_suffix('.private-error').write_text(result.stderr, encoding='utf-8')
        raise AssertionError('private saved-roster worker failed')
    return json.loads(result.stdout) if not at else None


def peak_rss_bytes():
    """Native OS process peak, including interpreter; not tracemalloc's peak."""
    if sys.platform != 'win32':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)] + [
            (name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize',
            'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi',use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes=(wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


if __name__ == '__main__':
    from contextlib import ExitStack
    from time import perf_counter
    import tracemalloc
    began=perf_counter();tracemalloc.start()
    from unittest.mock import patch
    import sqlite3
    from phase2_engine.repository import DataRepository
    from phase2_engine.saved_school_roster_source import SavedRosterCapability, SavedSchoolRosterSource, SavedSchoolRosterTrial
    from phase2_engine.school_roster_trial import TrialCapability
    data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    for item in data.values():
        for key in ('root_identity', 'file_identity', 'lease_identity'):
            item[key] = tuple(item[key])
    with ExitStack() as stack:
        if sys.argv[2] == 'before_acceptance_commit':
            original = sqlite3.connect
            def connect(*a, **kw):
                con = original(*a, **kw)
                con.execute('PRAGMA cache_size=1')
                return con
            stack.enter_context(patch.object(sqlite3, 'connect', connect))
        source = SavedSchoolRosterSource.resume(SavedRosterCapability(**data['source']), DataRepository(ROOT / 'data'))
        stack.callback(source.close)
        trial = SavedSchoolRosterTrial.resume(TrialCapability(**data['target']), source)
        stack.callback(trial.close)
        commits = 0
        def fault(at, sid):
            global commits
            if at == 'school_committed':
                commits += 1
            if at == sys.argv[2] and (at != 'school_committed' or commits == int(sys.argv[3])):
                os._exit(73)
        state=trial.advance(career_seed=SEED, fault=fault)
        state['resume_metrics']=dict(seconds=perf_counter()-began,
            traced_peak_bytes=tracemalloc.get_traced_memory()[1],process_peak_rss_bytes=peak_rss_bytes(),
            source_bytes=source.db_path.stat().st_size,target_bytes=trial.db_path.stat().st_size)
        print(json.dumps(state))
