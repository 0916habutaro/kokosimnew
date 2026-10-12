"""Run only self-generated Stage94 fixtures; accepts no save-root input."""
from contextlib import nullcontext
import argparse
import json
from pathlib import Path
import platform
import sqlite3
from time import perf_counter
import unittest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json-output', type=Path)
    parser.add_argument('--gui-regressions', action='store_true')
    args = parser.parse_args(argv)
    with args.json_output.open('x', encoding='utf-8') if args.json_output else nullcontext(None) as out:
        tests = Path(__file__).resolve().parents[1]/'tests'
        suite = unittest.defaultTestLoader.discover(str(tests), pattern='test_stage43g94_*.py')
        from stage43g94_fixture_support import METRICS
        from stage43g94_gui_fixture_runner import owned_gui_suite
        METRICS.clear()
        start = perf_counter()
        with owned_gui_suite(tests) if args.gui_regressions else nullcontext(suite) as selected:
            result = unittest.TextTestRunner(verbosity=2).run(selected)
        evidence = dict(stage='43G-94', tests=result.testsRun, failures=len(result.failures),
            errors=len(result.errors), skipped=len(result.skipped), successful=result.wasSuccessful(),
            seconds=round(perf_counter()-start,3), os=platform.system(), python=platform.python_version(),
            sqlite=sqlite3.sqlite_version, fixture_only=True, metrics=METRICS,
            gui_fixture_teardown=args.gui_regressions,
            restoration_authorized=False, whole_game_restore_proven=False,
            production_writers_changed=False, generation_adopted=False)
        encoded = json.dumps(evidence, ensure_ascii=False, indent=2)
        if out:
            out.write(encoded+'\n')
        print(encoded)
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
