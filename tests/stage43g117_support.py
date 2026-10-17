"""Explicit self-created 8-team scenario and private child-process transport.

The parent retains every TemporaryDirectory owner. The scenario never copies
the 2026 registration, qualification or joint team as 2027 authority.
"""
from contextlib import ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = 'fictional:stage117-owned-eight'
# Real master schools, separately chosen for a fictional test. This is not an
# assertion that any of them enter, combine or qualify in 2027.
GROUPS = (('SCH000196',), ('SCH000197',), ('SCH000198',), ('SCH000199',), ('SCH000200',),
          ('SCH000201',), ('SCH000203',), ('SCH000202', 'SCH000220'))
DATES = ('2027-07-10', '2027-07-12', '2027-07-14')


def scenario(lab, *, groups=GROUPS, namespace=NAMESPACE, size=8, dates=DATES, seeds=2):
    from phase2_engine import competition_evidence_gates as gates
    from phase2_engine.saved_practice_match import saved_authority
    snap, rosters, _, _ = saved_authority(lab)
    by_id = {r.school_id: r for r in rosters}
    teams = []
    for n, ids in enumerate(groups, 1):
        members = tuple((sid, by_id[sid].program_id) for sid in ids)
        players = tuple(p.player_id for sid in ids for p in by_id[sid].players[:20 // len(ids)])
        teams.append(gates.EntryTeam(f'{namespace}:team{n}', members, players))
    teams = tuple(teams)

    def evidence(part):
        return gates.Evidence(gates.Authority.FICTIONAL_DECLARATION, 2027,
                              'self-created declaration/' + part, 'stage117_explicit_eight_v1')
    comp = snap.repo.competition('CMP000041')
    return gates.CompetitionRequest('CMP000041', 2027, comp['competition_type'], namespace,
        gates.EntrySet(evidence('entries'), teams),
        gates.JointComposition(evidence('joint'), tuple((t.entry_team_id, t.programs) for t in teams if len(t.programs) > 1)),
        gates.Qualification(evidence('qualification'), tuple(gates.QualificationDecision(t.entry_team_id, True,
                            'explicit_scenario', False) for t in teams), None),
        gates.DistrictRules(evidence('district'), 'fictional_yamanashi_v2', 'scenario-district',
            tuple((s, p, 'scenario-district') for t in teams for s, p in t.programs)),
        gates.SeedRules(evidence('seed'), 'fictional_seed_v2', tuple((teams[i].entry_team_id, i + 1) for i in range(seeds))),
        gates.DrawRules(evidence('draw'), 'single_elimination', len(teams), size, size - len(teams)),
        gates.Schedule(evidence('date-envelope'), dates))


def worker(caps, private, *, action='read'):
    path = private / 'bracket-capabilities.json'
    path.write_text(json.dumps({k: asdict(v) for k, v in caps.items()}), encoding='utf-8')
    state = private / 'bracket-child-state.json'
    if state.exists():
        state.unlink()
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(path), action, str(state)],
        cwd=ROOT, env=dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(ROOT)),
        capture_output=True, text=True, encoding='utf-8', timeout=600)
    expected = 73 if action.startswith('crash_') else 0
    if result.returncode != expected:
        raise AssertionError('owned fictional bracket child failed: ' + result.stderr[-3000:])
    # A crashed child records its verified starting state before hard exit.
    return json.loads(state.read_text(encoding='utf-8')) if expected else json.loads(result.stdout)


def resume(data):
    from phase2_engine import yamanashi_annual_rosters as annual
    from phase2_engine.saved_practice_match import PracticeCapability, PracticeStore
    from phase2_engine.saved_fictional_tournament import TournamentCapability, FictionalTournamentStore
    from phase2_engine.saved_fictional_bracket import BracketCapability, FictionalBracketStore
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
        old = FictionalTournamentStore.resume(capability(TournamentCapability, data['v1']), lab, fictional_opt_in=True)
        stack.callback(old.close)
        store = FictionalBracketStore.resume(capability(BracketCapability, data['bracket']), lab, fictional_opt_in=True)
        stack.callback(store.close)
        return stack, lab, practice, old, store
    except BaseException:
        stack.close()
        raise


def describe(view, store, began):
    from phase2_engine.joint_team_registration_lab import _sha
    return dict(pid=os.getpid(), matches=len(view.results), complete=view.complete,
        champion=view.fictional_scenario_champion, ranks=view.ranks, ledger=view.ledger,
        next_pair=view.next_pair(), result_sha256=[_sha(r.to_dict()) for r in view.results],
        winners=[r.winner_id for r in view.results], db_bytes=store.db_path.stat().st_size,
        seconds=perf_counter() - began, official_year_verified=False, product_season_start_authorized=False)


if __name__ == '__main__':
    import sqlite3
    from unittest.mock import patch
    began = perf_counter()
    with ExitStack() as outer:
        action, state = sys.argv[2], Path(sys.argv[3])
        if action == 'crash_before_commit':
            connect = sqlite3.connect

            def spilling(*args, **kwargs):
                con = connect(*args, **kwargs)
                con.execute('PRAGMA cache_size=1')
                return con
            outer.enter_context(patch.object(sqlite3, 'connect', spilling))
        stack, lab, practice, old, store = resume(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
        with stack:
            if action.startswith('crash_'):
                start = store.snapshot()
                state.write_text(json.dumps(describe(start, store, began)), encoding='utf-8')
                # crash_after:N plays forward and hard-exits right after game N commits.
                target = int(action.split(':')[1]) if action.startswith('crash_after:') else len(start.results) + 1
                boundary = 'after_commit' if action.startswith('crash_after:') else 'before_commit'
                while len(store.snapshot().results) < target - 1:
                    store.play_next()

                def fault(at):
                    if at == boundary:
                        os._exit(73)
                store.play_next(fault=fault)
                raise AssertionError('requested hard-exit boundary not reached')
            if action == 'finish':
                while not store.snapshot().complete:
                    store.play_next()
            before = store.db_path.read_bytes()
            view = store.snapshot(practice_store=practice, v1_store=old)
            assert before == store.db_path.read_bytes()
            out = describe(view, store, began)
            out.update(readonly_bytes_unchanged=True, source_matches=len(view._source.results),
                       practice_matches=len(practice.snapshot().results), v1_matches=len(old.snapshot().results))
            print(json.dumps(out))
