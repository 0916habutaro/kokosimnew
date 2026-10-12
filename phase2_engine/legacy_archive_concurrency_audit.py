"""Stage43G-92 fixture-only concurrency evidence; accepts no save paths."""
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
    args = parser.parse_args(argv)
    tests = Path(__file__).resolve().parents[1] / 'tests'
    class EvidenceResult(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.schedules = []

        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            self.schedules.append({'test': test.id(), 'schedule': str(subtest),
                                   'successful': err is None})
    with (args.json_output.open('x', encoding='utf-8') if args.json_output
          else nullcontext(None)) as output:
        suite = unittest.defaultTestLoader.discover(str(tests), pattern='test_stage43g92_*.py')
        start = perf_counter()
        result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
        evidence = dict(stage='43G-92', tests=result.testsRun, failures=len(result.failures),
            errors=len(result.errors), skipped=len(result.skipped), successful=result.wasSuccessful(),
            subtest_schedules=len(result.schedules), schedules=result.schedules,
            seconds=round(perf_counter()-start, 3), python=platform.python_version(),
            sqlite=sqlite3.sqlite_version, fixture_only=True, schema_changed=False,
            generation_adopted=False, ordering='threading.Event at SQLite state reads / BEGIN IMMEDIATE')
        encoded = json.dumps(evidence, ensure_ascii=False, indent=2)
        if output:
            output.write(encoded + '\n')
        print(encoded)
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
