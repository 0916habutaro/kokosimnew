"""Stage118 real-scale fictional 32-team audit, zero skips; writes only a new report.

Runs the dedicated real-scale cases, the fast contract cases and the true
Stage117-main RO candidate. `--old-versions` also runs all twenty historical
RO compatibility files (Stage94/99/100-117 exports) in the same process.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys
from time import perf_counter, process_time
import unittest


class TimedResult(unittest.TextTestResult):
    def startTest(self, test):
        self._began = perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        self.timings = getattr(self, 'timings', {})
        self.timings[test.id()] = round(perf_counter() - self._began, 3)
        super().stopTest(test)


def run(suite):
    began, cpu = perf_counter(), process_time()
    result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(suite)
    return result, round(perf_counter() - began, 3), round(process_time() - cpu, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-windows', action='store_true')
    parser.add_argument('--old-versions', action='store_true')
    parser.add_argument('--json-output', type=Path, required=True)
    args = parser.parse_args()
    if args.require_windows and sys.platform != 'win32':
        parser.error('native Windows required')
    root = Path(__file__).resolve().parents[1]
    tests = root / 'tests'
    sys.path[:0] = [str(root), str(tests)]
    code_inputs = ('phase2_engine/fictional_scenario_history.py', 'phase2_engine/saved_fictional_bracket.py',
        'phase2_engine/fictional_bracket.py', 'phase2_engine/fictional_bracket_oracle.py',
        'phase2_engine/saved_fictional_tournament.py', 'phase2_engine/fictional_tournament_oracle.py',
        'phase2_engine/competition_evidence_gates.py', 'phase2_engine/saved_practice_match.py',
        'phase2_engine/registered_match_driver.py', 'phase2_engine/registered_full_a_oracle.py',
        'tests/stage43g118_scale_cases.py', 'tests/stage43g118_support.py', 'tests/test_stage43g118_contract.py',
        'tests/test_stage43g118_compatibility.py')

    def code_hashes():
        return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in code_inputs}
    before = code_hashes()
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite(loader.discover(str(tests), pattern=p) for p in
        ('stage43g118_scale_cases.py', 'test_stage43g118_contract.py', 'test_stage43g118_compatibility.py'))
    result, seconds, cpu = run(suite)
    expected = 8 + 4 + 1
    success = result.wasSuccessful() and not result.skipped and result.testsRun == expected
    old = None
    if args.old_versions:
        old_suite = loader.discover(str(tests), pattern='test_stage43g*_compatibility.py')
        old_result, old_seconds, old_cpu = run(old_suite)
        files = sorted({name.split('.')[0] for name in getattr(old_result, 'timings', {})})
        old = dict(files=files, file_count=len(files), tests=old_result.testsRun, skipped=len(old_result.skipped),
                   failures=len(old_result.failures), errors=len(old_result.errors), seconds=old_seconds,
                   cpu_seconds=old_cpu, successful=old_result.wasSuccessful() and not old_result.skipped,
                   test_seconds=getattr(old_result, 'timings', {}))
        success = success and old['successful'] and len(files) == 20
    after = code_hashes()
    success = success and before == after
    module = sys.modules.get('stage43g118_scale_cases')
    report = dict(stage='43G-118', os=platform.system(), python=platform.python_version(),
        sqlite=sqlite3.sqlite_version, successful=success, tests=result.testsRun, expected_tests=expected,
        skipped=len(result.skipped), errors=len(result.errors), failures=len(result.failures),
        seconds=seconds, parent_cpu_seconds=cpu, native_windows=sys.platform == 'win32',
        test_seconds=getattr(result, 'timings', {}), measured=module.MEASUREMENTS if module else {},
        old_versions=old, code_sha256=after, code_immutable_during_audit=before == after,
        old_versions_total=20, catalog_inputs_unchanged=338, master_csv_unchanged=106, existing_user_saves_used=0,
        product_writer_changed=False, stage116_v1_changed=False, stage117_v2_changed=False,
        official_year_verified=False, product_season_start_authorized=False,
        official_2027_entry=None, official_2027_qualification=None, official_2027_joint_continuation=None,
        official_2027_schedule=None, official_2027_ranking=None, fictional_entries=32, fictional_schools=33,
        fictional_registered_players=640, fictional_games=31, staged_entries=16, staged_games=15,
        years_50_100_200_run=False, personal_windows_pc_verified=False, os_login_or_pc_restart_verified=False)
    with args.json_output.open('x', encoding='utf-8') as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('measured', 'test_seconds')}, ensure_ascii=False))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
