"""Windows-first Stage109 zero-skip audit; publication-safe aggregate evidence."""
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
    parser.add_argument('--json-output',required=True,type=Path)
    args=parser.parse_args()
    if args.require_windows and sys.platform!='win32':parser.error('native Windows required')
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    patterns=['test_stage43g109_real_tk.py'] if args.gui else ['test_stage43g109_demo.py'] + [
        f'test_stage43g{n}_compatibility.py' for n in range(103,110)]
    suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=p) for p in patterns)
    began=perf_counter();result=unittest.TextTestRunner(verbosity=2).run(suite)
    success=result.wasSuccessful() and not result.skipped and result.testsRun==(2 if args.gui else 16)
    module=sys.modules.get('test_stage43g109_real_tk' if args.gui else 'test_stage43g109_demo')
    report=dict(stage='43G-109',os=platform.system(),python=platform.python_version(),successful=success,
        tests=result.testsRun,skipped=len(result.skipped),errors=len(result.errors),failures=len(result.failures),
        seconds=round(perf_counter()-began,3),native_windows=sys.platform=='win32',mapped_tk=args.gui,
        measured=module.MEASUREMENTS,permanent_schools=33,permanent_players=660,teams=32,registered_slots=640,
        rounds=5,matches=31,old_self_generated_candidate_versions=0 if args.gui else 11,
        catalog_inputs_unchanged=338,master_csv_unchanged=106,existing_user_saves_used=0,
        existing_user_save_compatibility_verified=False,manual_user_windows_operation_verified=False,
        os_login_session_restart_verified=False,product_writer_changed=False,authenticated_provenance=False,
        atomicity='single SQLite transaction per committed game',
        scope='explicitly self-created persistent fictional 2026 Yamanashi demo namespace only')
    with args.json_output.open('x',encoding='utf-8') as out:
        json.dump(report,out,ensure_ascii=False,indent=2);out.write('\n')
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return 0 if success else 1


if __name__=='__main__':raise SystemExit(main())
