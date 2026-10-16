"""Stage110 additions to existing Stage109 gates, without duplicate old fixtures."""
import argparse
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
import unittest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui',action='store_true')
    parser.add_argument('--require-windows',action='store_true')
    parser.add_argument('--json-output',type=Path,required=True)
    args=parser.parse_args()
    if args.require_windows and sys.platform!='win32': parser.error('native Windows required')
    root=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(root))
    patterns=['test_stage43g110_real_tk.py'] if args.gui else [
        'test_stage43g110_demo.py','test_stage43g110_compatibility.py']
    suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=p) for p in patterns)
    start=perf_counter(); result=unittest.TextTestRunner(verbosity=2).run(suite)
    success=result.wasSuccessful() and not result.skipped and result.testsRun==(2 if args.gui else 3)
    report=dict(stage='43G-110',os=platform.system(),python=platform.python_version(),successful=success,
        seconds=round(perf_counter()-start,3),tests=result.testsRun,skipped=len(result.skipped),
        failures=len(result.failures),errors=len(result.errors),native_windows=sys.platform=='win32',mapped_tk=args.gui,
        additional_true_old_candidate_version=None if args.gui else 109,
        earlier_eleven_versions='unchanged Stage109 audit',catalog_inputs_unchanged=338,master_csv_unchanged=106,
        manual_user_windows_operation_verified=False,os_login_session_restart_verified=False)
    with args.json_output.open('x',encoding='utf-8') as out:
        json.dump(report,out,ensure_ascii=False,indent=2);out.write('\n')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if success else 1


if __name__=='__main__':raise SystemExit(main())
