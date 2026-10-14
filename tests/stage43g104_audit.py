"""Windows-first gates; publish only aggregate fixture evidence, no paths/digests."""
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
    if args.require_windows and sys.platform!='win32':
        parser.error('Windows native runner required')
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    patterns=['test_stage43g104_real_tk.py'] if args.gui else [
        'test_stage43g104_registration.py','test_stage43g104_compatibility.py',
        'test_stage43g103_compatibility.py']
    suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=p) for p in patterns)
    start=perf_counter()
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    success=result.wasSuccessful() and not result.skipped and result.testsRun==(1 if args.gui else 14)
    report=dict(stage='43G-104',os=platform.system(),python=platform.python_version(),
        tests=result.testsRun,skipped=len(result.skipped),errors=len(result.errors),failures=len(result.failures),
        successful=success,seconds=round(perf_counter()-start,3),native_windows=sys.platform=='win32',
        mapped_tk=args.gui,fixture_only=True,source_schools=4,permanent_players=80,
        competition_teams=3,registered_players=60,registered_match_input=True,
        mixed_school_matches_executed=0,joint_full_a_supported=False,
        simulation_blocker='元学校を維持するteam別完全A出力・validator・driverが未成立',
        joint_writer_supported=False,old_real_candidate_versions=0 if args.gui else 6,
        legacy_catalog_inputs_unchanged=0 if args.gui else 338,master_csv_unchanged=0 if args.gui else 106,
        existing_saves_used=0,existing_save_verification='未検証・試験入力利用なし',
        production_restore_supported=False,multiple_store_atomicity_guaranteed=False,
        official_results_reproduced=False,manual_user_windows_operation_verified=False)
    with args.json_output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    return 0 if success else 1


if __name__=='__main__':
    raise SystemExit(main())
