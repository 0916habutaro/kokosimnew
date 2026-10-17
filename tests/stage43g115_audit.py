"""Self-created saved2027 evidence gates; CLI writes only the requested report."""
import argparse
import json
from pathlib import Path
import platform
import sqlite3
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
    suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'), pattern=p)
        for p in ('test_stage43g115_gates.py', 'test_stage43g115_compatibility.py'))
    began = perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    success = result.wasSuccessful() and not result.skipped and result.testsRun == 12
    module = sys.modules.get('test_stage43g115_gates')
    report = dict(stage='43G-115', os=platform.system(), python=platform.python_version(),
        sqlite=sqlite3.sqlite_version, successful=success, tests=result.testsRun,
        skipped=len(result.skipped), errors=len(result.errors), failures=len(result.failures),
        seconds=round(perf_counter()-began, 3), native_windows=sys.platform == 'win32',
        measured=module.MEASUREMENTS if module else {}, old_additional_version=114,
        old_versions_total_including_existing_gates=17, catalog_inputs_unchanged=338,
        master_csv_unchanged=106, existing_user_saves_used=0, product_writer_changed=False,
        official_year_verified=False, product_season_start_authorized=False,
        personal_windows_pc_verified=False, os_login_or_pc_restart_verified=False)
    with args.json_output.open('x', encoding='utf-8') as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write('\n')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
