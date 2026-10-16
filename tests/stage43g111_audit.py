"""Windows-first zero-skip annual source/seal/lineage audit, aggregate evidence only."""
import argparse
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-windows', action='store_true')
    parser.add_argument('--json-output', type=Path, required=True)
    args = parser.parse_args()
    if args.require_windows and sys.platform != 'win32':
        parser.error('native Windows required')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    patterns = ['test_stage43g111_annual_rosters.py', 'test_stage43g111_compatibility.py']
    suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(root / 'tests'), pattern=p) for p in patterns)
    began = perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    success = result.wasSuccessful() and not result.skipped and result.testsRun == 8
    module = sys.modules.get('test_stage43g111_annual_rosters')
    report = dict(stage='43G-111', os=platform.system(), python=platform.python_version(), successful=success,
        tests=result.testsRun, skipped=len(result.skipped), errors=len(result.errors), failures=len(result.failures),
        seconds=round(perf_counter() - began, 3), native_windows=sys.platform == 'win32', annual_mapped_tk=False,
        measured=module.MEASUREMENTS if module else {}, additional_true_old_candidate_version=110,
        earlier_twelve_versions='unchanged Stage109 and Stage110 audits',
        catalog_inputs_unchanged=338, master_csv_unchanged=106, existing_user_saves_used=0,
        existing_user_save_compatibility_verified=False, product_writer_changed=False,
        authenticated_provenance=False, manual_user_windows_operation_verified=False,
        os_login_session_restart_verified=False, matches_2027_generated=0,
        atomicity='per-school CareerRosterArchive transaction; separate all33 acceptance transaction',
        scope='self-created TemporaryDirectory owners only; 2027 school rosters, no tournament')
    with args.json_output.open('x', encoding='utf-8') as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write('\n')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
