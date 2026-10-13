"""Existing GUI fixtures with explicit SQLite lifetime, before Windows cleanup.

Keep native connections, transactions and assertions. This fixture-only runner
does not patch a production writer or accept external files.
"""
from contextlib import contextmanager
import sqlite3
import unittest
from unittest.mock import patch


@contextmanager
def owned_gui_suite(tests):
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
        for case in suite:
            if isinstance(case, unittest.TestSuite):
                yield from cases(case)
            else:
                yield case
    suite = unittest.TestSuite()
    for pattern in ('test_stage43g75_*.py', 'test_stage43g77_*.py'):
        suite.addTests(unittest.defaultTestLoader.discover(str(tests),pattern=pattern))
    for case in cases(suite):
        teardown = case.tearDown
        def closed_teardown(teardown=teardown):
            close_handles()
            teardown()
        case.tearDown = closed_teardown
    with patch.object(sqlite3,'connect',connect):
        try:
            yield suite
        finally:
            close_handles()
