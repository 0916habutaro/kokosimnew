"""Parent-owned Stage108 capability transport across actual spawn process exits."""
import multiprocessing
import os
import sqlite3
from time import perf_counter
from unittest.mock import patch


def play_phase(capability, start, stop, output):
    from phase2_engine.yamanashi_tournament_store import OwnedTournamentStore,TournamentLabReader
    began=perf_counter()
    store=OwnedTournamentStore.resume(capability,timeout=10)
    if len(TournamentLabReader(store.db_path).snapshot().results)!=start:
        raise ValueError('unexpected committed prefix')
    for _ in range(start,stop):store.play_next()
    checked=TournamentLabReader(store.db_path).snapshot()
    output.put(dict(pid=os.getpid(),start=start,count=len(checked.results),complete=checked.complete,
        seconds=round(perf_counter()-began,6),database_bytes=store.db_path.stat().st_size))


def run_phase(capability,start,stop):
    context=multiprocessing.get_context('spawn');output=context.Queue()
    child=context.Process(target=play_phase,args=(capability,start,stop,output));child.start()
    try:
        # Bound timeout, parent caller remains able to report progress.
        evidence=output.get(timeout=600);child.join(timeout=20)
        if child.is_alive() or child.exitcode!=0:raise AssertionError('Stage108 worker failed')
        return evidence
    finally:
        if child.is_alive():child.terminate();child.join(timeout=10)
        output.close();output.join_thread()


def crash_next(capability):
    from phase2_engine.yamanashi_tournament_store import OwnedTournamentStore
    store=OwnedTournamentStore.resume(capability)
    original=sqlite3.connect
    def connect(*args,**kwargs):
        con=original(*args,**kwargs);con.execute('PRAGMA cache_size=1');return con
    def fault(boundary):
        if boundary=='before_commit':os._exit(73)
    with patch.object(sqlite3,'connect',connect):store.play_next(fault=fault)
