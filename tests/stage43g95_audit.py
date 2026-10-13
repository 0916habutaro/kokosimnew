"""Dedicated fixture-only test CLI; accepts no save or candidate path."""
import argparse
import json
from pathlib import Path
import platform
import sqlite3
import sys
from time import perf_counter
import unittest


def main(argv=None):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json-output',type=Path,required=True)
    args = parser.parse_args(argv)
    # Reserve report before running; no report overwrite either.
    with args.json_output.open('x',encoding='utf-8') as out:
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_stage43g95_*.py')
        from stage43g95_isolated_harness import METRICS
        METRICS.clear()
        start = perf_counter()
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        report = dict(stage='43G-95',tests=result.testsRun,failures=len(result.failures),
            errors=len(result.errors),skipped=len(result.skipped),successful=result.wasSuccessful(),
            seconds=round(perf_counter()-start,3),os=platform.system(),python=platform.python_version(),
            sqlite=sqlite3.sqlite_version,fixture_only=True,metrics=METRICS,
            restoration_authorized=False,whole_game_restore_proven=False,
            production_writers_changed=False,evidence_authenticated=False,
            persistent_trust_anchor=False)
        json.dump(report,out,ensure_ascii=False,indent=2)
        out.write('\n')
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
