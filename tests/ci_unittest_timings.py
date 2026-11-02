"""Python の全件テストを、テストのファイルごとに複数のプロセスで流し、1件ごとの時間を記録する。

    python tests/ci_unittest_timings.py --workers 4 --json-output out/unittest-timings.json

``tests/test*.py`` を1ファイルずつ別のプロセスで実行する（ファイルの中の setUpClass は分けない）。
重いファイルを先に始めるよう、前回の記録（``--previous``）があればその時間の長い順に、
なければ新規開始・日付を進める呼び出しの多い順に配る。結果の JSON には1件ごとの時間とファイルごとの合計が入る。
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import platform
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
FORMAT_VERSION = 2


class TimedTextResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.timings, self._starts, self._statuses = [], {}, {}

    def startTest(self, test):
        self._starts[test] = time.perf_counter()
        super().startTest(test)

    def _status(self, test, status):
        self._statuses[test] = status

    def addSuccess(self, test):
        self._status(test, "success")
        super().addSuccess(test)

    def addSkip(self, test, reason):
        self._status(test, "skipped")
        super().addSkip(test, reason)

    def addFailure(self, test, err):
        self._status(test, "failure")
        super().addFailure(test, err)

    def addError(self, test, err):
        self._status(test, "error")
        super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self._status(test, "failure")
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        started = self._starts.pop(test, None)
        if started is not None:
            self.timings.append(dict(id=test.id(), status=self._statuses.pop(test, "success"),
                                     seconds=round(time.perf_counter() - started, 3)))
        super().stopTest(test)


def run_file(name: str) -> dict:
    """1つのテストファイルを流す（別のプロセスで呼ぶ）。"""
    sys.path[:0] = [str(TESTS), str(ROOT)]
    os.chdir(ROOT)
    stream = io.StringIO()
    started = time.perf_counter()
    suite = unittest.TestLoader().discover(start_dir=str(TESTS), pattern=name,
                                           top_level_dir=str(TESTS))
    result = unittest.TextTestRunner(stream=stream, verbosity=2,
                                     resultclass=TimedTextResult).run(suite)
    return dict(file=name, seconds=round(time.perf_counter() - started, 3),
                output=stream.getvalue(), tests=result.testsRun,
                failures=len(result.failures), errors=len(result.errors),
                skipped=len(result.skipped), successful=result.wasSuccessful(),
                per_test=result.timings)


def test_files() -> list[str]:
    return sorted(path.name for path in TESTS.glob("test*.py"))


HEAVY_CALLS = ("new_game(", "advance_through(", "advance_to(", "next_day(")


def ordered(files: list[str], previous: Path | None) -> list[str]:
    if previous is None or not previous.is_file():
        def calls(name):
            text = (TESTS / name).read_text(encoding="utf-8")
            return -sum(text.count(call) for call in HEAVY_CALLS)
        return sorted(files, key=lambda name: (calls(name), name))
    seconds = json.loads(previous.read_text(encoding="utf-8")).get("per_file", {})
    return sorted(files, key=lambda name: -float(seconds.get(name, {}).get("seconds", 0)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--previous", type=Path, help="前回の結果（重いファイルを先に始める）")
    args = parser.parse_args(argv)

    files = ordered(test_files(), args.previous)
    started = time.perf_counter()
    reports = []
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(run_file, name) for name in files]
        for future in as_completed(futures):
            report = future.result()
            reports.append(report)
            print(f"=== {report['file']} ({report['seconds']:.1f}秒)\n{report['output']}", flush=True)
    elapsed = time.perf_counter() - started

    total = defaultdict(int)
    for report in reports:
        for key in ("tests", "failures", "errors", "skipped"):
            total[key] += report[key]
    ok = all(report["successful"] for report in reports)
    summary = dict(
        schema=FORMAT_VERSION, captured_at_utc=datetime.now(timezone.utc).isoformat(),
        workers=args.workers, successful=ok, elapsed_seconds=round(elapsed, 1), **total,
        python=platform.python_version(), cpu_count=os.cpu_count(),
        per_file={r["file"]: dict(seconds=r["seconds"], tests=r["tests"])
                  for r in sorted(reports, key=lambda r: -r["seconds"])},
        per_test=sorted((row for r in reports for row in r["per_test"]),
                        key=lambda row: -row["seconds"]),
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")

    slow = list(summary["per_file"].items())[:12]
    lines = [f"### Python の全件テスト（{args.workers}プロセス）",
             f"- {total['tests']}件、スキップ {total['skipped']}、失敗 {total['failures']}、"
             f"エラー {total['errors']}",
             f"- 時間: {elapsed / 60:.1f}分", "", "| ファイル | 件数 | 秒 |", "|---|---:|---:|"]
    lines += [f"| {name} | {row['tests']} | {row['seconds']:.1f} |" for name, row in slow]
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    failed = [r["file"] for r in reports if not r["successful"]]
    print(f"Ran {total['tests']} tests in {elapsed:.1f}s with {args.workers} workers: "
          + ("OK" if ok else f"FAILED {failed}"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
