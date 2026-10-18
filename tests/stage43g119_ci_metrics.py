"""Stage119-A: full unittest discover with structured per-test wall/CPU timings.

No test filter, retries, changed skip rules, parallelism, or extra full-suite run.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
FORMAT_VERSION = 1
PUBLIC_KEYS = ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion",
               "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA",
               "GITHUB_REF", "GITHUB_EVENT_NAME")


def module_of(test_id):
    return ".".join(test_id.split(".")[:-2]) or "(unknown)"


class TimedTextResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.timings, self._starts, self._statuses = [], {}, {}
        self._id_occurrences = defaultdict(int)

    def startTest(self, test):
        self._starts[test] = time.perf_counter(), time.process_time()
        super().startTest(test)

    def addSuccess(self, test):
        self._statuses[test] = "success"
        super().addSuccess(test)

    def addSkip(self, test, reason):
        self._statuses[test] = "skipped"
        super().addSkip(test, reason)

    def addFailure(self, test, err):
        self._statuses[test] = "failure"
        super().addFailure(test, err)

    def addError(self, test, err):
        self._statuses[test] = "error"
        super().addError(test, err)

    def addExpectedFailure(self, test, err):
        self._statuses[test] = "expected_failure"
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self._statuses[test] = "unexpected_success"
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self._statuses[test] = "failure_or_error_subtest"
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        before_wall, before_cpu = self._starts.pop(test)
        self._id_occurrences[test.id()] += 1
        self.timings.append(dict(
            id=test.id(), occurrence=self._id_occurrences[test.id()],
            module=module_of(test.id()),
            status=self._statuses.pop(test, "success"),
            seconds=round(time.perf_counter() - before_wall, 6),
            process_cpu_seconds=round(time.process_time() - before_cpu, 6)))
        super().stopTest(test)


def aggregate(cases):
    grouped = defaultdict(lambda: [0, 0.0, 0.0])
    for row in cases:
        v = grouped[row["module"]]
        v[0] += 1
        v[1] += row["seconds"]
        v[2] += row["process_cpu_seconds"]
    return {name: dict(count=v[0], seconds=round(v[1], 4),
                       process_cpu_seconds=round(v[2], 4))
            for name, v in sorted(grouped.items())}


def environment():
    return dict(os=platform.system(), architecture=platform.machine(),
                python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                cpu_count=os.cpu_count(),
                github={key: os.environ[key] for key in PUBLIC_KEYS if key in os.environ})


def make_report(result, *, elapsed_seconds, process_cpu_seconds, env=None):
    cases = sorted(result.timings, key=lambda row: row["id"])
    if len(cases) != result.testsRun:
        raise RuntimeError("all discovered tests must have a timing")
    # TestCase.id() is not necessarily unique across an entire suite.
    # Every executed instance must retain its own stable (id, occurrence) key.
    _index_instances(cases)
    return dict(schema=FORMAT_VERSION, stage="43G-119-A",
                captured_at_utc=datetime.now(timezone.utc).isoformat(),
                discovery="python -m unittest discover -s tests -v",
                successful=result.wasSuccessful(), tests=result.testsRun,
                skipped=len(result.skipped), failures=len(result.failures),
                errors=len(result.errors),
                expected_failures=len(result.expectedFailures),
                unexpected_successes=len(result.unexpectedSuccesses),
                elapsed_seconds=round(elapsed_seconds, 4),
                process_cpu_seconds=round(process_cpu_seconds, 4),
                environment=environment() if env is None else env,
                per_module=aggregate(cases), per_test=cases)


def _index_instances(rows):
    """Map (unittest ID, 1-based occurrence) to each execution.

    Stage119-A's first CI artifact has schema=1 and no occurrence field.
    Derive occurrence from its stored per_test order to keep it comparable.
    A newer artifact explicitly records occurrence; validate that it is
    positive, unique and contiguous for each ID to reject corrupted reports.
    """
    count = defaultdict(int)
    ordinals = defaultdict(set)
    indexed = {}
    for row in rows:
        test_id = row["id"]
        if not isinstance(test_id, str) or not test_id:
            raise ValueError("nonempty test ID required")
        count[test_id] += 1
        ordinal = row.get("occurrence", count[test_id])
        if type(ordinal) is not int or ordinal < 1:
            raise ValueError("positive integer occurrence required")
        key = test_id, ordinal
        if key in indexed:
            raise ValueError("duplicate test instance ID and occurrence")
        indexed[key] = row
        ordinals[test_id].add(ordinal)
    for test_id, total in count.items():
        if ordinals[test_id] != set(range(1, total + 1)):
            raise ValueError("noncontiguous test occurrences")
    return indexed


def _instance_label(key):
    test_id, ordinal = key
    return test_id if ordinal == 1 else f"{test_id}#{ordinal}"


def compare_reports(before, after):
    if before.get("schema") != FORMAT_VERSION or after.get("schema") != FORMAT_VERSION:
        raise ValueError("incompatible report schema")
    old = _index_instances(before["per_test"])
    new = _index_instances(after["per_test"])
    if before["tests"] != len(old) or after["tests"] != len(new):
        raise ValueError("reported test count differs from recorded instances")
    common = sorted(old.keys() & new.keys())
    changes = sorted((dict(id=key[0], occurrence=key[1],
                           module=new[key]["module"],
                           before_seconds=old[key]["seconds"],
                           after_seconds=new[key]["seconds"],
                           delta_seconds=round(new[key]["seconds"]-old[key]["seconds"], 4))
                      for key in common),
                     key=lambda row: row["delta_seconds"], reverse=True)
    modules = sorted((dict(module=name,
                           before_seconds=before["per_module"].get(name, {}).get("seconds", 0),
                           after_seconds=after["per_module"].get(name, {}).get("seconds", 0),
                           delta_seconds=round(
                               after["per_module"].get(name, {}).get("seconds", 0) -
                               before["per_module"].get(name, {}).get("seconds", 0), 4))
                      for name in before["per_module"].keys() | after["per_module"].keys()),
                     key=lambda row: row["delta_seconds"], reverse=True)
    added, removed = sorted(new.keys()-old.keys()), sorted(old.keys()-new.keys())
    return dict(schema=FORMAT_VERSION, stage="43G-119-A-comparison",
                before_tests=before["tests"], after_tests=after["tests"],
                common_tests=len(common),
                added_tests=[_instance_label(key) for key in added],
                removed_tests=[_instance_label(key) for key in removed],
                added_instances=[dict(id=key[0], occurrence=key[1]) for key in added],
                removed_instances=[dict(id=key[0], occurrence=key[1]) for key in removed],
                before_elapsed_seconds=before["elapsed_seconds"],
                after_elapsed_seconds=after["elapsed_seconds"],
                elapsed_delta_seconds=round(after["elapsed_seconds"]-before["elapsed_seconds"], 4),
                environment_before=before["environment"], environment_after=after["environment"],
                module_deltas=modules, test_deltas=changes,
                cause_not_inferable_from_single_comparison=True)


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
        output.write("\n")


def emit_summary(report):
    slow = sorted(report["per_module"].items(),
                  key=lambda row: row[1]["seconds"], reverse=True)[:12]
    lines = ["### Stage119-A full unittest timing",
             f"- Tests: {report['tests']}, skipped: {report['skipped']}, "
             f"failures: {report['failures']}, errors: {report['errors']}",
             f"- Wall time: {report['elapsed_seconds']/60:.2f} min (CI limit 120 min)",
             f"- Python: {report['environment']['python']}",
             "", "| Module | Tests | Wall (seconds) |", "|---|---:|---:|"]
    lines += [f"| {name} | {v['count']} | {v['seconds']:.2f} |" for name, v in slow]
    if report["elapsed_seconds"] >= 110 * 60:
        lines.append("\nWarning: full unittest is within 10 minutes of the 120-minute CI limit.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError as exc:
            print(f"Summary write warning: {exc}", file=sys.stderr)
    print(f"Stage119-A: {report['tests']} tests, {report['elapsed_seconds']:.1f}s, "
          f"failures={report['failures']}, errors={report['errors']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--compare-base", type=Path)
    parser.add_argument("--compare-current", type=Path)
    args = parser.parse_args(argv)
    if args.compare_base or args.compare_current:
        if not (args.compare_base and args.compare_current):
            parser.error("both comparison files are required")
        with args.compare_base.open(encoding="utf-8") as handle:
            before = json.load(handle)
        with args.compare_current.open(encoding="utf-8") as handle:
            after = json.load(handle)
        write_new(args.json_output, compare_reports(before, after))
        return 0

    sys.path.insert(0, str(TESTS))
    sys.path.insert(0, str(ROOT))
    suite = unittest.TestLoader().discover(start_dir=str(TESTS), pattern="test*.py",
                                          top_level_dir=str(TESTS))
    wall, cpu = time.perf_counter(), time.process_time()
    result = unittest.TextTestRunner(verbosity=2, resultclass=TimedTextResult).run(suite)
    report = make_report(result, elapsed_seconds=time.perf_counter()-wall,
                         process_cpu_seconds=time.process_time()-cpu)
    write_new(args.json_output, report)
    emit_summary(report)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
