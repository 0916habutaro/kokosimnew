"""Stage119-C real/fault/performance audit; dedicated Linux/native Windows runner."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys
from time import perf_counter,process_time
import unittest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-windows',action='store_true')
    parser.add_argument('--old-versions',action='store_true')
    parser.add_argument('--json-output',type=Path,required=True)
    args=parser.parse_args()
    if args.require_windows and sys.platform!='win32':parser.error('native Windows required')
    root=Path(__file__).resolve().parents[1];tests=root/'tests';sys.path[:0]=[str(root),str(tests)]
    from stage43g117_audit import TimedResult
    from stage43g119c_synthetic import run as synthetic
    import stage43g119c_cases as cases
    loader=unittest.defaultTestLoader
    suite=loader.loadTestsFromModule(cases)
    suite.addTests(loader.discover(str(tests),pattern='test_stage43g119c_contract.py'))
    began,cpu=perf_counter(),process_time()
    result=unittest.TextTestRunner(verbosity=2,resultclass=TimedResult).run(suite)
    old=None
    if args.old_versions:
        old_suite=loader.discover(str(tests),pattern='test_stage43g*_compatibility.py')
        t=perf_counter();old_result=unittest.TextTestRunner(verbosity=2,resultclass=TimedResult).run(old_suite)
        names=sorted({name.split('.')[0] for name in getattr(old_result,'timings',{})})
        old=dict(tests=old_result.testsRun,skipped=len(old_result.skipped),failures=len(old_result.failures),
            errors=len(old_result.errors),files=names,file_count=len(names),seconds=perf_counter()-t,
            successful=old_result.wasSuccessful() and not old_result.skipped and len(names)==20)
    success=result.wasSuccessful() and not result.skipped and (old is None or old['successful'])
    report=dict(stage='43G-119-C',successful=success,tests=result.testsRun,skipped=len(result.skipped),
        failures=len(result.failures),errors=len(result.errors),failure_details=result.failures+result.errors,
        seconds=perf_counter()-began,parent_cpu_seconds=process_time()-cpu,os=platform.system(),
        python=platform.python_version(),sqlite=sqlite3.sqlite_version,native_windows=sys.platform=='win32',
        cpu_count=__import__('os').cpu_count(),peak_rss_kib=cases.peak_rss_kib(),
        test_seconds=getattr(result,'timings',{}),measured=cases.MEASUREMENTS,old_versions=old,
        synthetic=synthetic(),personal_windows_pc_verified=False,official_year_verified=False,
        product_season_start_authorized=False,real_max_teams=32,real_max_games=31,
        anchor_without_latest_receipt_prevents_rollback=False,
        code_sha256={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root/'phase2_engine').glob('*v3*.py')})
    report['failure_details']=[(str(test),trace) for test,trace in report['failure_details']]
    args.json_output.parent.mkdir(parents=True,exist_ok=True)
    with args.json_output.open('x',encoding='utf-8') as out:json.dump(report,out,ensure_ascii=False,indent=2);out.write('\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('measured','synthetic','failure_details','test_seconds')},ensure_ascii=False))
    return 0 if success else 1


if __name__=='__main__':raise SystemExit(main())
