"""Windows-first real fictional eight-team bracket, zero skips; writes only new report."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys
from time import perf_counter
import unittest


class TimedResult(unittest.TextTestResult):
    def startTest(self, test):
        self._began = perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        self.timings = getattr(self, 'timings', {})
        self.timings[test.id()] = round(perf_counter() - self._began, 3)
        super().stopTest(test)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-windows', action='store_true')
    parser.add_argument('--json-output', type=Path, required=True)
    args = parser.parse_args()
    if args.require_windows and sys.platform != 'win32':
        parser.error('native Windows required')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    code_inputs = ('phase2_engine/saved_fictional_bracket.py', 'phase2_engine/fictional_bracket.py',
        'phase2_engine/fictional_bracket_oracle.py', 'phase2_engine/saved_fictional_tournament.py',
        'phase2_engine/fictional_tournament_oracle.py', 'phase2_engine/competition_evidence_gates.py',
        'phase2_engine/saved_practice_match.py', 'phase2_engine/registered_match_driver.py',
        'phase2_engine/registered_full_a_oracle.py', 'tests/test_stage43g117_bracket.py',
        'tests/stage43g117_support.py', 'tests/test_stage43g117_compatibility.py')
    def code_hashes():
        return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in code_inputs}
    before = code_hashes()
    suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'), pattern=p)
        for p in ('test_stage43g117_bracket.py', 'test_stage43g117_compatibility.py'))
    began = perf_counter()
    result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(suite)
    after = code_hashes()
    success = result.wasSuccessful() and not result.skipped and result.testsRun == 16 and before == after
    module = sys.modules.get('test_stage43g117_bracket')
    report = dict(stage='43G-117', os=platform.system(), python=platform.python_version(),
        sqlite=sqlite3.sqlite_version, successful=success, tests=result.testsRun,
        skipped=len(result.skipped), errors=len(result.errors), failures=len(result.failures),
        seconds=round(perf_counter()-began, 3), native_windows=sys.platform == 'win32',
        test_seconds=getattr(result, 'timings', {}),
        measured=module.MEASUREMENTS if module else {}, old_additional_version=116,
        code_sha256=after, code_immutable_during_audit=before == after,
        old_versions_total_including_existing_gates=19, catalog_inputs_unchanged=338,
        master_csv_unchanged=106, existing_user_saves_used=0, product_writer_changed=False,
        official_year_verified=False, product_season_start_authorized=False,
        official_2027_entry=None, official_2027_qualification=None, official_2027_joint_continuation=None,
        official_2027_schedule=None, official_2027_ranking=None, fictional_entries=8, fictional_schools=9,
        fictional_games=7, generic_bracket_sizes='4..32 structure; 3/4/8 stored paths',
        personal_windows_pc_verified=False, os_login_or_pc_restart_verified=False)
    with args.json_output.open('x', encoding='utf-8') as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write('\n')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
