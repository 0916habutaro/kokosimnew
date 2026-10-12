"""Stage43G-89: bounded, deterministic test-only SQLite interleavings.

No user DB paths are accepted. Writers run on a separate thread/connection;
Events set exact order, never random sleep. Production code has no test hooks.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import platform
import sqlite3
import threading
from time import perf_counter
import unittest

TIMEOUT = 10


class OrderedWriter:
    """Start one writer, then explicitly dispatch and await its completion."""

    def __init__(self, action):
        self.action = action
        self.go = threading.Event()
        self.done = threading.Event()
        self.errors = []
        self.thread = threading.Thread(target=self._work, daemon=True)

    def _work(self):
        try:
            if not self.go.wait(TIMEOUT):
                raise TimeoutError("writer dispatch timed out")
            self.action()
        except BaseException as exc:
            self.errors.append(exc)
        finally:
            self.done.set()

    def __enter__(self):
        self.thread.start()
        return self

    def run(self):
        self.go.set()
        if not self.done.wait(TIMEOUT):
            raise TimeoutError("writer completion timed out")
        if self.errors:
            raise self.errors[0]

    def __exit__(self, *args):
        self.go.set()
        self.thread.join(TIMEOUT)
        if self.thread.is_alive():
            raise TimeoutError("writer join timed out")


class ReadProbe:
    """Transparent connection proxy with per-statement before/after hooks."""

    def __init__(self, db, path, hook):
        object.__setattr__(self, "db", db)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "hook", hook)
        object.__setattr__(self, "versions", 0)

    def __getattr__(self, name):
        return getattr(self.db, name)

    def __setattr__(self, name, value):
        setattr(self.db, name, value)

    def execute(self, sql, *args):
        if sql == "PRAGMA data_version":
            object.__setattr__(self, "versions", self.versions + 1)
        self.hook(self, sql, "before")
        cursor = self.db.execute(sql, *args)
        self.hook(self, sql, "after")
        return cursor


def wal_probe(path):
    with closing(sqlite3.connect(path, timeout=TIMEOUT)) as db:
        if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
            raise AssertionError("WAL unavailable")
        db.execute("CREATE TABLE concurrency_probe (n INTEGER)")
        db.commit()


def commit_probe(path):
    with closing(sqlite3.connect(path, timeout=TIMEOUT)) as db:
        db.execute("INSERT INTO concurrency_probe VALUES (89)")
        db.commit()


def main():
    """Run disposable-fixture regressions and emit machine-readable evidence."""
    root = Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(
        str(root / "tests"), pattern="test_stage43g89_*.py")
    class EvidenceResult(unittest.TextTestResult):
        def __init__(self, *args):
            super().__init__(*args)
            self.schedules = []

        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            self.schedules.append({"test": test.id(), "schedule": str(subtest),
                                   "successful": err is None})

    started = perf_counter()
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    print(json.dumps({
        "stage": "43G-89", "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version, "tests": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "successful": result.wasSuccessful(),
        "seconds": round(perf_counter() - started, 3),
        "subtest_schedules": len(result.schedules), "schedules": result.schedules,
        "ordering": "threading.Event + exact SQL/API boundaries; no sleeps",
        "fixtures": "temporary full-A synthetic data, never user saves",
    }, ensure_ascii=False, indent=2))
    raise SystemExit(not result.wasSuccessful())


if __name__ == "__main__":
    main()
