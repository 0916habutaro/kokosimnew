"""Explicit self-created 16/32-team scenarios and a measured child-process transport.

The parent retains every TemporaryDirectory owner. Entries are typed fictional
declarations; nothing copies a 2026 registration or joint team as 2027
authority. The joint pair is a scenario choice, not a 2027 continuation claim.
"""
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE32 = 'fictional:stage118-owned-thirty-two'
NAMESPACE16 = 'fictional:stage118-owned-sixteen'
SEED32, SEED16 = 430118, 430218
JOINT = ('SCH000202', 'SCH000220')
DATES32 = ('2027-07-09', '2027-07-11', '2027-07-13', '2027-07-15', '2027-07-17')
DATES16 = ('2027-07-20', '2027-07-22', '2027-07-24', '2027-07-26')


def groups(lab, singles):
    """`singles` standalone schools in saved-roster order plus one 10+10 joint."""
    from phase2_engine.saved_practice_match import saved_authority
    ids = sorted(r.school_id for r in saved_authority(lab)[1])
    rest = [sid for sid in ids if sid not in JOINT]
    if len(ids) != 33 or len(rest) != 31 or singles > 31:
        raise AssertionError('saved 2027 must hold exactly the 33 accepted schools')
    return tuple((sid,) for sid in rest[:singles]) + (JOINT,)


def scenario32(lab, **changes):
    from stage43g117_support import scenario
    options = dict(groups=groups(lab, 31), namespace=NAMESPACE32, size=32, dates=DATES32, seeds=4)
    options.update(changes)
    return scenario(lab, **options)


def scenario16(lab, **changes):
    from stage43g117_support import scenario
    options = dict(groups=groups(lab, 15), namespace=NAMESPACE16, size=16, dates=DATES16, seeds=4)
    options.update(changes)
    return scenario(lab, **options)


def worker(caps, private, *, action='read', timeout=1800):
    """Run one child; returns its verified state (crash) or final read JSON."""
    path = private / 'bracket118-capabilities.json'
    path.write_text(json.dumps({k: asdict(v) for k, v in caps.items()}), encoding='utf-8')
    state = private / 'bracket118-child-state.json'
    games = private / 'bracket118-child-games.jsonl'
    for item in (state, games):
        if item.exists():
            item.unlink()
    began = perf_counter()
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(path), action, str(state), str(games)],
        cwd=ROOT, env=dict(os.environ, PYTHONUTF8='1', PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT / 'tests')))),
        capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    expected = 73 if action.startswith('crash_') else 0
    if result.returncode != expected:
        raise AssertionError(f'owned fictional bracket child {action} failed ({result.returncode}): ' + result.stderr[-3000:])
    out = json.loads(state.read_text(encoding='utf-8')) if expected else json.loads(result.stdout)
    out['games_played'] = [json.loads(line) for line in games.read_text(encoding='utf-8').splitlines()] \
        if games.exists() else []
    out['wall_seconds'] = round(perf_counter() - began, 3)
    return out


def _capability(cls, item):
    return cls(item['root'], tuple(item['root_identity']), tuple(item['file_identity']),
               tuple(item['lease_identity']), item['contract_json'])


def resume(data):
    """Resume only the stores the parent released; each one re-audits itself."""
    from phase2_engine import yamanashi_annual_rosters as annual
    from phase2_engine.saved_practice_match import PracticeCapability, PracticeStore
    from phase2_engine.saved_fictional_tournament import TournamentCapability, FictionalTournamentStore
    from phase2_engine.saved_fictional_bracket import BracketCapability, FictionalBracketStore
    stack, out = ExitStack(), {}
    try:
        item = data['source']
        source_cap = annual._SourceCapability(item['root'], tuple(item['root_identity']), item['demo_id'])
        source = annual.SelfCreated2026.resume(source_cap)
        stack.callback(source.close)
        item = data['annual']
        cap = annual._AnnualCapability(item['root'], tuple(item['root_identity']), tuple(item['file_identity']),
            tuple(item['lease_identity']), source_cap, item['contract_json'])
        lab = out['lab'] = annual.AnnualRosterLab.resume(cap, source)
        stack.callback(lab.close)
        if 'practice' in data:
            out['practice'] = PracticeStore.resume(_capability(PracticeCapability, data['practice']), lab)
            stack.callback(out['practice'].close)
        if 'v1' in data:
            out['v1'] = FictionalTournamentStore.resume(_capability(TournamentCapability, data['v1']), lab,
                                                        fictional_opt_in=True)
            stack.callback(out['v1'].close)
        for key in ('eight', 'bracket'):
            if key in data:
                out[key] = FictionalBracketStore.resume(_capability(BracketCapability, data[key]), lab,
                                                        fictional_opt_in=True)
                stack.callback(out[key].close)
        return stack, out
    except BaseException:
        stack.close()
        raise


def peak_rss_kib():
    from test_stage43g117_bracket import peak_rss_kib as measure
    return measure()


class Meter:
    """Inclusive wall time and call counts of the verification layers."""

    def __init__(self):
        self.calls, self.seconds = Counter(), Counter()

    def wrap(self, stack, owner, name, label):
        from unittest.mock import patch
        original = getattr(owner, name)

        def timed(*args, **kwargs):
            began = perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                self.calls[label] += 1
                self.seconds[label] += perf_counter() - began
        stack.enter_context(patch.object(owner, name, timed))

    def install(self, stack):
        from phase2_engine import competition_evidence_gates as gates
        from phase2_engine import saved_fictional_bracket as trial
        from phase2_engine import saved_fictional_tournament as v1
        from phase2_engine import saved_practice_match as practice
        self.wrap(stack, trial, '_prepare', 'prepare')
        self.wrap(stack, gates, 'dry_run', 'dry_run')
        self.wrap(stack, practice, 'saved_authority', 'saved_authority')
        self.wrap(stack, trial, '_rows', 'rows_full_reaudit')
        self.wrap(stack, v1, '_run', 'validate_rerun')
        self.wrap(stack, v1, 'event_oracle', 'validate_event_oracle')
        self.wrap(stack, trial, '_run', 'new_game_compute')

    def take(self):
        out = {k: dict(calls=self.calls[k], seconds=round(self.seconds[k], 3)) for k in sorted(self.calls)}
        self.calls.clear()
        self.seconds.clear()
        return out


def describe(view, store, began):
    from phase2_engine.joint_team_registration_lab import _sha
    return dict(pid=os.getpid(), namespace=view.plan.namespace, matches=len(view.results), complete=view.complete,
        champion=view.fictional_scenario_champion, ranks=view.ranks, ledger=view.ledger,
        next_pair=view.next_pair(), result_sha256=[_sha(r.to_dict()) for r in view.results],
        winners=[r.winner_id for r in view.results], db_bytes=store.db_path.stat().st_size,
        seconds=round(perf_counter() - began, 3), cpu_seconds=round(process_time(), 3),
        peak_rss_kib=peak_rss_kib(), official_year_verified=False, product_season_start_authorized=False)


def _child(capabilities, action, state, games_log):
    import sqlite3
    from unittest.mock import patch
    began = perf_counter()
    with ExitStack() as outer:
        if action == 'crash_before_commit':
            connect = sqlite3.connect

            def spilling(*args, **kwargs):
                con = connect(*args, **kwargs)
                con.execute('PRAGMA cache_size=1')
                return con
            outer.enter_context(patch.object(sqlite3, 'connect', spilling))
        stack, opened = resume(json.loads(Path(capabilities).read_text(encoding='utf-8')))
        resumed = round(perf_counter() - began, 3)
        meter = Meter()
        meter.install(outer)
        with stack:
            store = opened['bracket']

            def play(fault=None):
                t, cpu = perf_counter(), process_time()
                meter.take()

                def record(boundary):
                    with open(games_log, 'a', encoding='utf-8') as out:
                        out.write(json.dumps(dict(sequence=sequence, seconds=round(perf_counter() - t, 3),
                            cpu_seconds=round(process_time() - cpu, 3), boundary=boundary,
                            db_bytes=store.db_path.stat().st_size, layers=meter.take(), pid=os.getpid())) + '\n')

                def hook(at):
                    if fault and fault(at):
                        record(at)
                        os._exit(73)
                sequence = len(store.snapshot().results) + 1
                meter.take()
                t, cpu = perf_counter(), process_time()
                store.play_next(fault=hook)
                record('complete')

            if action.startswith('crash_'):
                start = store.snapshot()
                out = describe(start, store, began)
                out['resume_seconds'] = resumed
                Path(state).write_text(json.dumps(out), encoding='utf-8')
                target = int(action.split(':')[1]) if action.startswith('crash_after:') else len(start.results) + 1
                boundary = 'after_commit' if action.startswith('crash_after:') else 'before_commit'
                while len(store.snapshot().results) < target - 1:
                    play()
                play(lambda at: at == boundary)
                raise AssertionError('requested hard-exit boundary not reached')
            if action == 'finish':
                while not store.snapshot().complete:
                    play()
            before = store.db_path.read_bytes()
            out = describe(store.snapshot(), store, began)
            if 'eight' in opened:
                from phase2_engine.fictional_scenario_history import scenario_history
                history = scenario_history((store, opened['eight']), practice_store=opened.get('practice'),
                                           v1_store=opened.get('v1'))
                out['streams'] = history.stream_summary()
            out['readonly_bytes_unchanged'] = before == store.db_path.read_bytes()
            out['resume_seconds'] = resumed
            print(json.dumps(out))


if __name__ == '__main__':
    _child(*sys.argv[1:5])
