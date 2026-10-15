"""Separate process: actual calculation/save or read-only restart evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phase2_engine.registered_full_a_lab_store import RegisteredFullALabStore, RegisteredFullALabReader, fixed_authorities
from phase2_engine.joint_team_registration_lab import match_input_from_registration
from phase2_engine.registered_match_driver import simulate_registered_full_a
from phase2_engine.registered_full_a_oracle import event_oracle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read', type=Path)
    parser.add_argument('--generate-copy', type=Path)
    parser.add_argument('--crash-fixture-db', type=Path)
    args = parser.parse_args()
    if sum(bool(x) for x in (args.read,args.generate_copy,args.crash_fixture_db)) != 1:
        parser.error('one operation required')
    if args.crash_fixture_db:
        import os
        repo, rosters, reg = fixed_authorities()
        match = match_input_from_registration(reg, repo, rosters, team1_id=reg.teams[0].team_id,
            team2_id=reg.teams[1].team_id, opt_in=True)
        result = simulate_registered_full_a(match, reg, repo, rosters)
        # Test plumbing only: parent created and owns this exact empty lab DB.
        # The public writer still never accepts paths or pre-existing files.
        from phase2_engine.registered_full_a_lab_store import _rows
        import sqlite3
        path = args.crash_fixture_db
        if RegisteredFullALabReader(path).snapshot().results:
            raise ValueError('empty self-owned crash fixture required')
        con = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA cache_size=1')  # Force dirty-page spill before abrupt exit.
        con.execute('BEGIN IMMEDIATE')
        rows = _rows(reg, rosters, (result,), repo)
        for table, values in rows.items():
            if table == 'lab_meta':
                continue
            for row in values:
                placeholders = ','.join('?' for _ in row)
                con.execute(f'INSERT INTO {table} VALUES ({placeholders})', row)
        os._exit(73)
        raise AssertionError('crash was not injected')
    if args.generate_copy:
        import shutil
        repo, rosters, reg = fixed_authorities()
        match = match_input_from_registration(reg, repo, rosters, team1_id=reg.teams[0].team_id,
            team2_id=reg.teams[1].team_id, opt_in=True)
        result = simulate_registered_full_a(match, reg, repo, rosters)
        owner = tempfile.TemporaryDirectory(prefix='stage106-child-owned-')
        try:
            store = RegisteredFullALabStore(owner)
            store.append(result, match, reg, repo, rosters)
            # Disposable evidence transport to the parent-owned temp; not a writer API.
            if args.generate_copy.exists():
                raise ValueError('copy destination exists')
            shutil.copyfile(store.db_path, args.generate_copy)
        finally:
            owner.cleanup()
        path = args.generate_copy
    else:
        path = args.read
    reader = RegisteredFullALabReader(path)
    snapshot = reader.snapshot()
    result, = snapshot.results
    match = match_input_from_registration(snapshot.registration, snapshot.repo, snapshot.rosters,
        team1_id=result.team1_id, team2_id=result.team2_id, opt_in=True)
    # Publication-safe evidence: no paths, permanent player digests or user data.
    evidence = dict(score=[result.team1_score,result.team2_score], seed=result.run_seed,
        result_sha256=hashlib.sha256(result.to_json().encode()).hexdigest(),
        oracle=event_oracle(result, match),
        teams=len(reader.team(result.team1_id)['matches']),
        schools={sid:len(reader.school(sid)['matches']) for sid in ('SCH000202','SCH000220','SCH000196')},
        appearances=len(reader.player(result.batter_stats[0].player_id)['appearances']))
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
