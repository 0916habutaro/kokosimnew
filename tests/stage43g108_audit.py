"""Stage108 Windows-first zero-skip gates and publication-safe measurements."""
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
    if args.require_windows and sys.platform!='win32':parser.error('native Windows required')
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    patterns=['test_stage43g108_real_tk.py'] if args.gui else [
        'test_stage43g108_contract.py','test_stage43g108_store.py','test_stage43g108_compatibility.py',
        'test_stage43g107_compatibility.py','test_stage43g106_compatibility.py','test_stage43g105_compatibility.py',
        'test_stage43g104_compatibility.py','test_stage43g103_compatibility.py']
    suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=p) for p in patterns)
    start=perf_counter();checked=unittest.TextTestRunner(verbosity=2).run(suite)
    success=checked.wasSuccessful() and not checked.skipped and checked.testsRun==(1 if args.gui else 19)
    measurements={} if args.gui else sys.modules['test_stage43g108_store'].MEASUREMENTS
    # PIDs prove process separation privately; do not publish host identifiers.
    for value in measurements.values():
        for phase in value.get('phases',[]):phase.pop('pid',None)
    report=dict(stage='43G-108',os=platform.system(),python=platform.python_version(),successful=success,
        tests=checked.testsRun,skipped=len(checked.skipped),errors=len(checked.errors),failures=len(checked.failures),
        seconds=round(perf_counter()-start,3),native_windows=sys.platform=='win32',mapped_tk=args.gui,
        gate_a=dict(schools=33,permanent_players=660,teams=32,registered_slots=640,rounds=5,bracket_matches=31,byes=0),
        measured_gates=measurements,old_self_generated_candidate_versions=0 if args.gui else 10,
        input_catalog_unchanged=338,master_csv_unchanged=106,existing_user_saves_used=0,
        existing_user_save_compatibility_verified=False,manual_user_windows_operation_verified=False,
        product_writer_changed=False,product_restore_changed=False,authenticated_provenance=False,
        atomicity='single SQLite transaction per game; not 31 games or multiple product DBs',
        scope='fictional 2026 lab, parent-owned TemporaryDirectory lifetime only')
    with args.json_output.open('x',encoding='utf-8') as out:json.dump(report,out,ensure_ascii=False,indent=2);out.write('\n')
    # Also make aggregate measurements reviewable in CI logs; no payload/ID/SHA.
    summary={k:report[k] for k in ('stage','os','python','successful','tests','skipped','seconds','native_windows','mapped_tk')}
    summary['measured_gates']={gate:{k:v for k,v in value.items() if k not in ('games','ranks')}
                               for gate,value in measurements.items()}
    print(json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return 0 if success else 1


if __name__=='__main__':raise SystemExit(main())
