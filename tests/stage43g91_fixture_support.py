"""Fixture-local connection lifetime; never installed into production APIs."""
from contextlib import closing, contextmanager
import sqlite3


@contextmanager
def closed_archive_connection(archive):
    archive.db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(archive.db_path)) as connection:
        connection.row_factory = sqlite3.Row
        yield connection
