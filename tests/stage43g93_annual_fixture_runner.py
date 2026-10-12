"""Run existing annual tests with explicit lifetime for owned SQLite handles.

SQLite Connection.__exit__ commits/rolls back but does not close. These older
fixtures rely on garbage collection, which can leave Windows files open during
TemporaryDirectory cleanup. Keep native connections/transactions/assertions;
close fixture handles before teardown, never patch a product entry point.
"""
from contextlib import contextmanager
import sqlite3
import unittest
from unittest.mock import patch


@contextmanager
def annual_fixture_suite(tests):
    original_connect = sqlite3.connect
    handles = []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        handles.append(connection)
        return connection

    def close_handles():
        for connection in reversed(handles):
            connection.close()
        handles.clear()

    def cases(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                yield from cases(item)
            else:
                yield item

    suite = unittest.TestSuite()
    for pattern in ('test_stage43g11_*.py', 'test_stage43g12_*.py', 'test_stage43c*_*.py'):
        suite.addTests(unittest.defaultTestLoader.discover(str(tests), pattern=pattern))
    for case in cases(suite):
        teardown = case.tearDown
        def closed_teardown(teardown=teardown):
            close_handles()
            teardown()
        case.tearDown = closed_teardown
    with patch.object(sqlite3, 'connect', connect):
        try:
            yield suite
        finally:
            close_handles()
