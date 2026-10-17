"""Private child-process transport; parent retains all TemporaryDirectory owners."""
from contextlib import ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def worker(lab, practice, tournament, private, *, action='read'):
    path = private / 'fictional-capabilities.json'
    path.write_text(json.dumps(dict(source=asdict(lab.source.capability), annual=asdict(lab.capability),
        practice=asdict(practice.capability), tournament=asdict(tournament.capability))), encoding='utf-8')
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(path), action],
        cwd=ROOT, env=dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(ROOT)),
        capture_output=True, text=True, encoding='utf-8', timeout=240)
    expected = 73 if action.startswith('crash_') else 0
    if result.returncode != expected:
        raise AssertionError('owned fictional child failed: ' + result.stderr[-3000:])
    return json.loads(result.stdout) if expected == 0 else None


def resume(data):
    from phase2_engine import yamanashi_annual_rosters as annual
    from phase2_engine.saved_practice_match import PracticeCapability, PracticeStore
    from phase2_engine.saved_fictional_tournament import TournamentCapability, FictionalTournamentStore
    stack = ExitStack()
    try:
        item = data['source']
        source_cap = annual._SourceCapability(item['root'], tuple(item['root_identity']), item['demo_id'])
        source = annual.SelfCreated2026.resume(source_cap)
        stack.callback(source.close)
        item = data['annual']
        cap = annual._AnnualCapability(item['root'], tuple(item['root_identity']), tuple(item['file_identity']),
            tuple(item['lease_identity']), source_cap, item['contract_json'])
        lab = annual.AnnualRosterLab.resume(cap, source)
        stack.callback(lab.close)
        def capability(cls, item):
            return cls(item['root'], tuple(item['root_identity']), tuple(item['file_identity']),
                       tuple(item['lease_identity']), item['contract_json'])
        practice = PracticeStore.resume(capability(PracticeCapability, data['practice']), lab)
        stack.callback(practice.close)
        store = FictionalTournamentStore.resume(capability(TournamentCapability, data['tournament']),
                                               lab, fictional_opt_in=True)
        stack.callback(store.close)
        return stack, lab, practice, store
    except BaseException:
        stack.close()
        raise


if __name__ == '__main__':
    from time import perf_counter
    import sqlite3
    from unittest.mock import patch
    from phase2_engine.saved_fictional_tournament import _input, _validate, _sha
    began = perf_counter()
    with ExitStack() as outer:
        action = sys.argv[2]
        if action == 'crash_before_commit':
            connect = sqlite3.connect
            def spilling(*args, **kwargs):
                con = connect(*args, **kwargs)
                con.execute('PRAGMA cache_size=1')
                return con
            outer.enter_context(patch.object(sqlite3, 'connect', spilling))
        stack, lab, practice, store = resume(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
        with stack:
            if action.startswith('crash_'):
                def fault(at):
                    if action == 'crash_' + at:
                        os._exit(73)
                store.play_next(fault=fault)
                raise AssertionError('requested hard-exit boundary not reached')
            if action == 'finish':
                while not store.snapshot().complete:
                    store.play_next()
            before = store.db_path.read_bytes()
            view = store.snapshot(practice_store=practice)
            prepared = store._prepare()
            reports = [_validate(result, _input(view.plan, view.teams, prepared[3], view.results[:i]))
                       for i, result in enumerate(view.results)]
            assert before == store.db_path.read_bytes()
            print(json.dumps(dict(pid=os.getpid(), matches=len(view.results), complete=view.complete,
                champion=view.fictional_scenario_champion, ranks=view.ranks,
                result_sha256=[_sha(r.to_dict()) for r in view.results], oracle=reports,
                source_matches=len(view._source.results), practice_matches=len(practice.snapshot().results),
                readonly_bytes_unchanged=True, seconds=perf_counter()-began,
                official_year_verified=False, product_season_start_authorized=False)))
