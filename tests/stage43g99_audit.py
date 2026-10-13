"""Windows-primary Stage99 gate; only aggregate, non-sensitive JSON output."""
import argparse
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
import unittest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui',action='store_true')
    parser.add_argument('--require-windows',action='store_true')
    parser.add_argument('--json-output',type=Path,required=True)
    args = parser.parse_args(argv)
    if args.require_windows and sys.platform != 'win32':
        parser.error('native Windows runner required')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    patterns = ['test_stage43g99_real_tk.py'] if args.gui else [
        'test_stage43g99_compatibility.py','test_stage43g99_lifetime.py']
    suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=p) for p in patterns)
    start = perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    success = result.wasSuccessful() and not result.skipped and result.testsRun == (1 if args.gui else 13)
    report = dict(stage='43G-99',os=platform.system(),python=platform.python_version(),
        tests=result.testsRun,skipped=len(result.skipped),errors=len(result.errors),failures=len(result.failures),
        successful=success,seconds=round(perf_counter()-start,3),native_windows=sys.platform=='win32',
        mapped_tk=args.gui,fixture_only=True,product_handles_observed_before_fixture_cleanup=True,
        existing_save_candidates=sum(p.is_dir() for p in (root/'out'/'saves').glob('*')),
        existing_saves_used=0,existing_save_verification='未検証・入力として使用しない',
        candidate_content_and_current_replay_separate=True,current_code_replay_authorized=False,
        production_restore_added=False,all_product_sqlite_paths_fixed=False,
        manual_user_windows_operation_verified=False)
    with args.json_output.open('x',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
