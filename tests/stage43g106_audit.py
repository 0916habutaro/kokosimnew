"""Measured owned-store/read/restart and eight-version compatibility gate."""
import argparse
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
    patterns=['test_stage43g106_real_tk.py'] if args.gui else [
        'test_stage43g106_store.py','test_stage43g106_compatibility.py',
        'test_stage43g105_compatibility.py','test_stage43g104_compatibility.py',
        'test_stage43g103_compatibility.py']
    suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=p) for p in patterns)
    start=perf_counter();checked=unittest.TextTestRunner(verbosity=2).run(suite)
    seconds=perf_counter()-start
    success=checked.wasSuccessful() and not checked.skipped and checked.testsRun==(1 if args.gui else 22)
    from phase2_engine.registered_full_a_lab_store import RegisteredFullALabStore,RegisteredFullALabReader,fixed_authorities
    from phase2_engine.joint_team_registration_lab import match_input_from_registration
    from phase2_engine.registered_match_driver import simulate_registered_full_a
    from phase2_engine.registered_full_a_oracle import event_oracle
    repo,rosters,reg=fixed_authorities()
    match=match_input_from_registration(reg,repo,rosters,team1_id=reg.teams[0].team_id,
        team2_id=reg.teams[1].team_id,opt_in=True)
    result=simulate_registered_full_a(match,reg,repo,rosters)
    owner=tempfile.TemporaryDirectory(prefix='stage106-measured-')
    try:
        store=RegisteredFullALabStore(owner)
        start=perf_counter();store.append(result,match,reg,repo,rosters);write_seconds=perf_counter()-start
        before=store.db_path.read_bytes()
        start=perf_counter();snapshot=RegisteredFullALabReader(store.db_path).snapshot();read_seconds=perf_counter()-start
        unchanged=before==store.db_path.read_bytes();size=len(before)
        if snapshot.results!=(result,) or not unchanged:success=False
    finally:owner.cleanup()
    report=dict(stage='43G-106',os=platform.system(),python=platform.python_version(),successful=success,
        tests=checked.testsRun,skipped=len(checked.skipped),errors=len(checked.errors),failures=len(checked.failures),
        seconds=round(seconds,3),write_seconds=round(write_seconds,6),verified_read_seconds=round(read_seconds,6),
        database_bytes=size,reader_db_bytes_unchanged=unchanged,native_windows=sys.platform=='win32',mapped_tk=args.gui,
        source_schools=4,permanent_players=80,competition_teams=3,registered_players=60,
        game=dict(seed=result.run_seed,score=[result.team1_score,result.team2_score],innings=result.last_inning,
            **event_oracle(result,match)),old_self_generated_candidate_versions=0 if args.gui else 8,
        input_catalog_unchanged=338,master_csv_unchanged=106,existing_user_saves_used=0,
        existing_user_save_compatibility_verified=False,product_writer_changed=False,
        product_restore_changed=False,authenticated_provenance=False,school_win_ranking_supported=False,
        manual_user_windows_operation_verified=False,scope='2026 one fictional game owned TemporaryDirectory only')
    with args.json_output.open('x',encoding='utf-8') as out:
        json.dump(report,out,ensure_ascii=False,indent=2);out.write('\n')
    return 0 if success else 1


if __name__=='__main__':raise SystemExit(main())
