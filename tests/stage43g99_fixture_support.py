"""Private, self-generated fixtures; never accept an external save/candidate."""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OLD_MAIN = '37f39378af7e8cb5ff27c36cbaeb559d0ad05a58'


@contextmanager
def retained_handles():
    """Observe without closing inside the operation; disable accidental GC wins.

    The caller must assert native closure BEFORE this fixture's final cleanup.
    Retaining connection/exception references makes leaks deterministic on Linux
    too. This is never used to repair product behavior during an assertion.
    """
    original, handles = sqlite3.connect, []
    def connect(*args, **kwargs):
        con = original(*args, **kwargs)
        handles.append(con)
        return con
    with patch.object(sqlite3, 'connect', connect):
        try:
            yield handles
        finally:
            for con in reversed(handles):
                con.close()


def assert_closed(test, handles):
    test.assertTrue(handles, 'operation did not open a native connection')
    for con in handles:
        with test.assertRaises(sqlite3.ProgrammingError):
            con.execute('SELECT 1')


def rename_and_read(test, slot):
    """Keep connection references alive while proving Windows handle release."""
    for path in sorted(slot.glob('*.sqlite3')):
        moved = path.with_name(path.name + '.released')
        path.rename(moved)
        moved.rename(path)
        with closing(sqlite3.connect(path)) as con:
            test.assertEqual([('ok',)], con.execute('PRAGMA integrity_check').fetchall())


def old_candidate(root):
    """Real pre-change export in a pinned checkout and another Python process.

    Git history is required, never fetch arbitrary code or relabel new evidence.
    Old source is private test plumbing, not shipped as a product dependency.
    """
    repo = root / 'old-main'
    repo.mkdir()
    archive = root / 'old-main.tar'
    with archive.open('xb') as out:
        subprocess.run(['git', 'archive', OLD_MAIN], cwd=ROOT, stdout=out, check=True)
    with tarfile.open(archive) as inp:
        inp.extractall(repo, filter='data')
    destination = root / 'old-candidate'
    code = '''
from pathlib import Path
import shutil, sys
from stage43g94_fixture_support import Fixture, owned_sqlite_handles
from phase2_engine.manual_save_backup import export_backup, verify_candidate, _compatibility
with owned_sqlite_handles():
    f = Fixture('sealed')
    try:
        assert len(_compatibility(Path.cwd())) == 338
        export_backup(**f.args())
        assert verify_candidate(candidate=f.destination)['candidate_consistent']
        shutil.copytree(f.destination, sys.argv[1])
    finally:
        f.close()
'''
    env = dict(os.environ, PYTHONUTF8='1', PYTHONPATH=os.pathsep.join((str(repo/'tests'), str(repo))))
    result = subprocess.run([sys.executable, '-c', code, str(destination)],
                            cwd=repo, env=env, capture_output=True, timeout=180)
    if result.returncode:
        # Do not publish private paths, source digests or arbitrary child errors.
        raise AssertionError('pinned pre-change fixture export failed')
    return destination
