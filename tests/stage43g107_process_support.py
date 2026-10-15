"""Spawn-only fixture workers. Capabilities never come from a user save/path."""
import multiprocessing
import os
import sqlite3
from unittest.mock import patch


def play_phase(capability, expected_count, output):
    from phase2_engine.joint_tournament_store import OwnedTournamentStore, TournamentLabReader
    store = OwnedTournamentStore.resume(capability, timeout=5)
    before = TournamentLabReader(store.db_path).snapshot()
    if len(before.results) != expected_count:
        raise ValueError('unexpected saved prefix')
    result = store.play_next()
    checked = TournamentLabReader(store.db_path).snapshot()
    output.put(dict(pid=os.getpid(), count=len(checked.results),
        score=[result.team1_score, result.team2_score], winner=result.winner_id,
        events=len(result.events), complete=checked.complete))


def run_phase(capability, expected_count):
    context = multiprocessing.get_context('spawn')
    output = context.Queue()
    child = context.Process(target=play_phase, args=(capability, expected_count, output))
    child.start()
    try:
        evidence = output.get(timeout=60)
        child.join(timeout=60)
        if child.is_alive() or child.exitcode != 0:
            raise AssertionError('isolated tournament worker failed')
        return evidence
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=10)
        output.close()
        output.join_thread()


def crash_final(capability):
    from phase2_engine.joint_tournament_store import OwnedTournamentStore
    store = OwnedTournamentStore.resume(capability)
    original = sqlite3.connect

    def connect(*args, **kwargs):
        con = original(*args, **kwargs)
        con.execute('PRAGMA cache_size=1')
        return con

    def fault(boundary):
        if boundary == 'before_commit':
            os._exit(73)

    with patch.object(sqlite3, 'connect', connect):
        store.play_next(fault=fault)
    raise AssertionError('crash not injected')
