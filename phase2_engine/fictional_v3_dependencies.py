"""Conservative transitive read manifest for v3; no undeclared dynamic reads.

All engine Python, config and master files plus every owned source file are
bound by identity/size/SHA. Enumeration detects new dependencies. The audit hook
is inert outside the current thread's explicit read boundary. This is a
consistency guard, not a sandbox against hostile process-memory modification.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import threading
from urllib.parse import unquote, urlsplit

from . import yamanashi_annual_rosters as annual
from . import yamanashi_demo_store as guards

ROOT = Path(__file__).resolve().parents[1]
_LOCAL = threading.local()


@dataclass(frozen=True)
class FileDigest:
    path: str
    identity: tuple
    size: int
    sha256: str


def _files(lab):
    roots = tuple(ROOT / name for name in ('phase2_engine', 'game_core', 'config', 'data')) + (
        Path(lab.capability.root), Path(lab.source.capability.root))
    files = set()
    for root in roots:
        guards._safe(root)
        for path in root.rglob('*'):
            if '__pycache__' in path.parts:
                continue
            if path.is_dir():
                guards._safe(path)
            else:
                guards._safe(path, directory=False)
                files.add(path.absolute())
    return tuple(sorted(files))


def capture(lab):
    values = []
    for path in _files(lab):
        before = path.stat()
        digest = annual._sha(path)
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('source changed while building dependency manifest')
        values.append(FileDigest(str(path), (after.st_dev, after.st_ino), after.st_size, digest))
    return tuple(values)


def check(lab, manifest):
    if capture(lab) != manifest:
        raise ValueError('transitive source/code/config/master manifest changed or grew')


def _audit(event, args):
    allowed = getattr(_LOCAL, 'allowed', None)
    if allowed is None or event not in ('open', 'sqlite3.connect'):
        return
    raw = args[0]
    if isinstance(raw, int):
        # File descriptors cannot establish a manifested path.
        raise ValueError('unmanifested file descriptor read')
    raw = os.fsdecode(raw)
    if event == 'sqlite3.connect':
        if raw == ':memory:':
            return
        if raw.startswith('file:'):
            parsed = urlsplit(raw)
            raw = unquote(parsed.path)
            if os.name == 'nt' and raw.startswith('/') and len(raw) > 2 and raw[2] == ':':
                raw = raw[1:]
    path = Path(raw).absolute()
    if path in allowed:
        return
    # Lazy standard-library imports are runtime code, not scenario inputs.
    if path.is_relative_to(Path(sys.base_prefix)):
        if path.suffix in ('.py', '.pyc', '.so', '.pyd'):
            return
    raise ValueError('read dependency missing from v3 manifest: ' + str(path))


sys.addaudithook(_audit)


@contextmanager
def read_boundary(manifest, extra=()):
    previous = getattr(_LOCAL, 'allowed', None)
    allowed = frozenset(Path(item.path) for item in manifest) | frozenset(Path(p).absolute() for p in extra)
    _LOCAL.allowed = allowed if previous is None else previous & allowed
    try:
        yield
    finally:
        _LOCAL.allowed = previous
