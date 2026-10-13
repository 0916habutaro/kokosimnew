"""Windows-first Stage98 gate: zero skips, no private paths/hashes in report."""
import argparse
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
import unittest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--require-windows', action='store_true')
    parser.add_argument('--json-output', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.require_windows and sys.platform != 'win32':
        parser.error('Windows native Tk runner required')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    pattern = 'test_stage43g98_real_tk.py' if args.gui else 'test_stage43g98_controller.py'
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern=pattern)
    start = perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    success = result.wasSuccessful() and not result.skipped and result.testsRun == (1 if args.gui else 6)
    # Only count existing candidates; NEVER open or use them as test inputs.
    existing = sum(p.is_dir() for p in (root / 'out' / 'saves').glob('*'))
    report = dict(stage='43G-98', os=platform.system(), python=platform.python_version(),
        tests=result.testsRun, skipped=len(result.skipped), errors=len(result.errors),
        failures=len(result.failures), successful=success, seconds=round(perf_counter()-start,3),
        fixture_only=True, native_windows=sys.platform=='win32', mapped_tk=args.gui,
        existing_save_candidates=existing, existing_saves_used=0,
        existing_save_verification='未検証・入力として使用しない',
        manual_user_windows_operation_verified=False, product_sqlite_lifetime_fixed=False,
        production_restore_added=False, official_national_game_gui_complete=False,
        next_year_gameplay_started=False)
    with args.json_output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
