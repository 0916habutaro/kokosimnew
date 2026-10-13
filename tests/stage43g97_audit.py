"""Windows-first acceptance runner; fixture-only and zero skips in each gate."""
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
        parser.error('Windows native runner required')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    pattern = 'test_stage43g97_real_tk.py' if args.gui else 'test_stage43g97_windows_acceptance.py'
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern=pattern)
    start = perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    expected_count = 1 if args.gui else 3
    success = result.wasSuccessful() and not result.skipped and result.testsRun == expected_count
    metrics = []
    if not args.gui:
        from test_stage43g97_windows_acceptance import METRICS
        metrics = METRICS
        success = success and len(metrics) == 2
    report = dict(stage='43G-97', os=platform.system(), python=platform.python_version(),
        tests=result.testsRun, skipped=len(result.skipped), errors=len(result.errors),
        failures=len(result.failures), successful=bool(success), seconds=round(perf_counter()-start,3),
        fixture_only=True, metrics=metrics, native_windows=sys.platform=='win32',
        real_tk=args.gui, gui_close_restart_cycles=2 if args.gui and success else 0,
        production_restore_added=False, official_game_gui_complete=False,
        real_user_manual_operation_verified=False)
    # Public report contains no paths, private SHA, or fixture content.
    with args.json_output.open('x', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2);output.write('\n')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
