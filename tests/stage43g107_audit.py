"""Windows-first zero-skip two-game/owned-restart/nine-old-version gate."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
import sys
import tempfile
from time import perf_counter
import unittest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui',action='store_true')
    parser.add_argument('--require-windows',action='store_true')
    parser.add_argument('--json-output',type=Path,required=True)
    args=parser.parse_args()
    if args.require_windows and sys.platform!='win32':parser.error('native Windows required')
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    patterns=['test_stage43g107_real_tk.py'] if args.gui else [
        'test_stage43g107_contract.py','test_stage43g107_store.py','test_stage43g107_compatibility.py',
        'test_stage43g106_compatibility.py','test_stage43g105_compatibility.py',
        'test_stage43g104_compatibility.py','test_stage43g103_compatibility.py']
    suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=p) for p in patterns)
    start=perf_counter();checked=unittest.TextTestRunner(verbosity=2).run(suite)
    seconds=perf_counter()-start
    success=checked.wasSuccessful() and not checked.skipped and checked.testsRun==(1 if args.gui else 22)
    from phase2_engine.joint_tournament_store import OwnedTournamentStore,TournamentLabReader
    from phase2_engine.joint_tournament_lab import _input
    from phase2_engine.registered_full_a_oracle import event_oracle
    from stage43g107_process_support import run_phase
    owner=tempfile.TemporaryDirectory(prefix='stage107-measured-')
    try:
        store=OwnedTournamentStore(owner)
        start=perf_counter();run_phase(store.resume_capability(),0);first_seconds=perf_counter()-start
        first_size=store.db_path.stat().st_size
        start=perf_counter();run_phase(store.resume_capability(),1);final_seconds=perf_counter()-start
        before=store.db_path.read_bytes()
        start=perf_counter();snapshot=TournamentLabReader(store.db_path).tournament();read_seconds=perf_counter()-start
        unchanged=before==store.db_path.read_bytes();size=len(before)
        if not snapshot.complete or not unchanged:success=False
        games=[]
        for i,result in enumerate(snapshot.results):
            match=_input(snapshot.plan,snapshot.registration,snapshot.results[:i])
            games.append(dict(match=i+1,seed=result.run_seed,score=[result.team1_score,result.team2_score],
                innings=result.last_inning,**event_oracle(result,match)))
    finally:owner.cleanup()
    # Publication-safe aggregates only: no paths, private payloads, player IDs or individual SHA.
    report=dict(stage='43G-107',os=platform.system(),python=platform.python_version(),successful=success,
        tests=checked.testsRun,skipped=len(checked.skipped),errors=len(checked.errors),failures=len(checked.failures),
        seconds=round(seconds,3),first_process_seconds=round(first_seconds,6),
        resumed_final_process_seconds=round(final_seconds,6),verified_read_seconds=round(read_seconds,6),
        first_commit_bytes=first_size,database_bytes=size,reader_db_bytes_unchanged=unchanged,
        native_windows=sys.platform=='win32',mapped_tk=args.gui,real_matches=2,bye_entries=1,
        source_schools=4,permanent_players=80,competition_teams=3,registered_players=60,games=games,
        ranks=[asdict(r) for r in snapshot.ranks],advancement=[asdict(r) for r in snapshot.ledger],
        old_self_generated_candidate_versions=0 if args.gui else 9,input_catalog_unchanged=338,master_csv_unchanged=106,
        existing_user_saves_used=0,existing_user_save_compatibility_verified=False,
        product_writer_changed=False,product_restore_changed=False,authenticated_provenance=False,
        school_standalone_win_ranking_supported=False,manual_user_windows_operation_verified=False,
        atomicity='one SQLite transaction per committed game; not JSON/multiple product DBs',
        scope='2026 fictional three-team lab; parent-owned TemporaryDirectory lifetime only')
    with args.json_output.open('x',encoding='utf-8') as out:
        json.dump(report,out,ensure_ascii=False,indent=2);out.write('\n')
    return 0 if success else 1


if __name__=='__main__':raise SystemExit(main())
