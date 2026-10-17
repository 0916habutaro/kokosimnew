"""Private capability transport; parent owns all three isolated directories."""
from contextlib import ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def worker(lab, store, private, *, action='read'):
    path = private / 'practice-capabilities.json'
    path.write_text(json.dumps(dict(source=asdict(lab.source.capability), annual=asdict(lab.capability),
                                   practice=asdict(store.capability))), encoding='utf-8')
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(path), action],
        cwd=ROOT, env=dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(ROOT)),
        capture_output=True, text=True, encoding='utf-8', timeout=180)
    if result.returncode != (73 if action.startswith('crash_') else 0):
        path.with_suffix('.private-error').write_text(result.stderr, encoding='utf-8')
        raise AssertionError('owned practice subprocess failed: ' + result.stderr[-2000:])
    return json.loads(result.stdout) if result.returncode == 0 else None


def resume(data):
    from phase2_engine.yamanashi_annual_rosters import SelfCreated2026, AnnualRosterLab, _SourceCapability, _AnnualCapability
    from phase2_engine.saved_practice_match import PracticeCapability, PracticeStore
    source_data = data['source']
    source_cap = _SourceCapability(source_data['root'], tuple(source_data['root_identity']), source_data['demo_id'])
    item = data['annual']
    cap = _AnnualCapability(item['root'], tuple(item['root_identity']), tuple(item['file_identity']),
                           tuple(item['lease_identity']), source_cap, item['contract_json'])
    item = data['practice']
    practice_cap = PracticeCapability(item['root'], tuple(item['root_identity']), tuple(item['file_identity']),
                                     tuple(item['lease_identity']), item['contract_json'])
    stack = ExitStack()
    try:
        source = SelfCreated2026.resume(source_cap); stack.callback(source.close)
        lab = AnnualRosterLab.resume(cap, source); stack.callback(lab.close)
        store = PracticeStore.resume(practice_cap, lab); stack.callback(store.close)
        return stack, lab, store
    except BaseException:
        stack.close()
        raise


if __name__ == '__main__':
    from time import perf_counter
    from unittest.mock import patch
    import sqlite3
    from phase2_engine.saved_practice_match import _sha, _validate
    began = perf_counter()
    with ExitStack() as outer:
        if sys.argv[2] == 'crash_before_commit':
            original = sqlite3.connect
            def connect(*a, **kw):
                con = original(*a, **kw)
                con.execute('PRAGMA cache_size=1')
                return con
            outer.enter_context(patch.object(sqlite3, 'connect', connect))
        stack, lab, store = resume(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
        with stack:
            if sys.argv[2].startswith('crash_'):
                def fault(at):
                    if sys.argv[2] == 'crash_' + at:
                        os._exit(73)
                store.play(fault=fault)
                raise AssertionError('crash boundary not reached')
            view = store.snapshot()
            game = view.results[0]
            report = _validate(game, view.match)
            print(json.dumps(dict(result_sha256=_sha(game.to_dict()), oracle=report,
                match_id=game.match_id, year=game.year, record_kind='fictional_practice',
                seconds=perf_counter()-began, matches=1,
                school_histories=[view.school(t.players[0].origin_school_id) for t in (view.match.team1, view.match.team2)],
                player_histories=[view.player(p.player_id) for p in game.batter_stats if p.plate_appearances > 0])))
