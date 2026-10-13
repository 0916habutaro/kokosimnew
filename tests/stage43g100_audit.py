"""Windows-first Stage100 gate; aggregate-only artifacts, zero target skips."""
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
    if args.require_windows and sys.platform!='win32': parser.error('Windows native runner required')
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    patterns=['test_stage43g100_real_tk.py'] if args.gui else ['test_stage43g100_persistence.py','test_stage43g100_compatibility.py']
    suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=p) for p in patterns)
    start=perf_counter();result=unittest.TextTestRunner(verbosity=2).run(suite)
    successful=result.wasSuccessful() and not result.skipped and result.testsRun==(1 if args.gui else 14)
    report=dict(stage='43G-100',os=platform.system(),python=platform.python_version(),
        tests=result.testsRun,skipped=len(result.skipped),errors=len(result.errors),failures=len(result.failures),
        successful=successful,seconds=round(perf_counter()-start,3),native_windows=sys.platform=='win32',
        mapped_tk=args.gui,fixture_only=True,old_real_candidate_versions=2,
        explicit_product_persistence=True,multiple_store_atomicity_guaranteed=False,
        current_code_replay_authorized=False,production_restore_added=False,
        official_national_game_gui_complete=False,next_year_gameplay_started=False,
        existing_save_candidates=sum(p.is_dir() for p in (root/'out'/'saves').glob('*')),
        existing_saves_used=0,existing_save_verification='0件の場合も未検証・入力利用なし',
        manual_user_windows_operation_verified=False)
    with args.json_output.open('x',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    return 0 if successful else 1


if __name__=='__main__': raise SystemExit(main())
