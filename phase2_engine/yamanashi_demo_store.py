"""Stage109 persistent, explicitly created demo namespace. No product save API.

Markers are consistency evidence, not authentication. Never adopt an arbitrary
SQLite, recover a journal, repair a marker, migrate, rotate or delete a demo.
"""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import uuid

from . import yamanashi_tournament_store as lab
from . import registered_full_a_lab_store as codec
from .yamanashi_tournament_registration import fixed_authorities, YEAR, COMPETITION
from .yamanashi_tournament_lab import verify_prefix, _input, _run, checkpoint
from .registered_full_a_contract import decode_result, VERSION as RESULT_VERSION, MODEL
from .registered_match_driver import config_digest, probability_model
from .joint_team_registration_lab import _identical
from .registered_full_a_oracle import event_oracle
from .yamanashi_tournament_oracle import progression_oracle

VERSION = 'stage43g109_persistent_demo_v1'
NAMESPACE_VERSION = 'stage43g109_namespace_v1'
ROOT_MARKER, MARKER, DATABASE, LEASE = 'namespace.json', 'demo.json', 'demo.sqlite3', 'session.lease'
ID = re.compile(r'demo-[0-9a-f]{32}\Z')
META_DDL = 'CREATE TABLE demo_metadata (metadata_json TEXT PRIMARY KEY, sha256 TEXT NOT NULL) STRICT'
SCHEMA = lab.SCHEMA + (META_DDL,) + tuple(
    f"CREATE TRIGGER demo_metadata_no_{action.lower()} BEFORE {action} ON demo_metadata "
    "BEGIN SELECT RAISE(ABORT, 'append-only demo'); END" for action in ('UPDATE', 'DELETE'))
TABLES = lab.TABLES + ('demo_metadata',)
FORBIDDEN = {'save', 'saves', 'backup', 'backups', 'data', '.git'}
SIGNATURES = ('slot_metadata.json', 'manual.json', 'autosave.json', 'evidence.json',
              'historical_matches.sqlite3', 'career_rosters.sqlite3', 'demo.json',
              'registered_full_a_lab.sqlite3', 'joint_tournament_107.sqlite3',
              'yamanashi_tournament_108.sqlite3')


def _identity(path):
    s = path.lstat()
    if s.st_ino <= 0:
        raise ValueError('実体IDを検証できるファイルシステムが必要です')
    return [s.st_dev, s.st_ino]


def _path(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('絶対パスの専用保存先を指定してください（親経由は禁止）')
    return path


def _safe(path, *, directory=True):
    for p in (path, *path.parents):
        s = p.lstat()
        if (stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400
                or p.is_junction()):
            raise ValueError('リンク・junction・reparse経由は禁止です')
        if p != path and not stat.S_ISDIR(s.st_mode):
            raise ValueError('保存先の親がディレクトリではありません')
    s = path.lstat()
    if directory and not stat.S_ISDIR(s.st_mode):
        raise ValueError('専用ディレクトリが必要です')
    if not directory and (not stat.S_ISREG(s.st_mode) or s.st_nlink != 1):
        raise ValueError('専用の単一実体ファイルが必要です')


def _location(path):
    """Inspect names/signatures only; never load or enumerate product slots."""
    installed = Path(__file__).resolve().parents[1]
    if path == installed or path.is_relative_to(installed) or installed.is_relative_to(path):
        raise ValueError('Git・製品data領域にデモを作成できません')
    for p in (path, *path.parents):
        git = p / '.git'
        if (p.name.casefold() in FORBIDDEN or git.is_file() or (git / 'HEAD').exists()
                or (p != path and (p / ROOT_MARKER).exists())
                or any((p / name).exists() for name in SIGNATURES)):
            raise ValueError('製品save・backup・Git/data領域は利用できません')


def _read(path):
    _safe(path, directory=False)
    if path.stat().st_size > 32768:
        raise ValueError('未知のmarkerです')
    raw = path.read_text(encoding='utf-8')
    value = codec.strict_json(raw)
    if type(value) is not dict or codec.canonical(value) != raw:
        raise ValueError('固定markerの形式が違います')
    return value


def _exclusive(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as out:
        out.write(codec.canonical(value))
        out.flush()
        os.fsync(out.fileno())


class DemoNamespace:
    def __init__(self, path):
        self.path = _path(path)
        _safe(self.path)
        _location(self.path)
        self.marker = _read(self.path / ROOT_MARKER)
        self._check()
        self.marker_identity = _identity(self.path / ROOT_MARKER)

    @classmethod
    def create(cls, path, *, opt_in=False):
        if opt_in is not True:
            raise ValueError('専用保存先の明示的新規作成が必要です')
        path = _path(path)
        _safe(path.parent)
        _location(path)
        path.mkdir(mode=0o700)  # exclusive; never adopt an existing directory
        _exclusive(path / ROOT_MARKER, dict(version=NAMESPACE_VERSION,
            namespace_id=uuid.uuid4().hex, directory_identity=_identity(path),
            purpose='fictional_2026_yamanashi_only'))
        return cls(path)

    def _check(self):
        _safe(self.path)
        _location(self.path)
        value = _read(self.path / ROOT_MARKER)
        expected = dict(version=NAMESPACE_VERSION, namespace_id=self.marker.get('namespace_id'),
                        directory_identity=_identity(self.path), purpose='fictional_2026_yamanashi_only')
        if (not re.fullmatch('[0-9a-f]{32}', str(value.get('namespace_id', '')))
                or codec.canonical(value) != codec.canonical(expected)
                or value != self.marker
                or (hasattr(self, 'marker_identity') and
                    _identity(self.path / ROOT_MARKER) != self.marker_identity)):
            raise ValueError('専用保存先の版・実体・markerが違います')

    def demos(self):
        self._check()
        names = []
        for p in self.path.iterdir():
            if p.name == ROOT_MARKER:
                continue
            if not ID.fullmatch(p.name):
                raise ValueError('専用保存先に未知の項目があります')
            _safe(p)
            names.append(p.name)
        return tuple(sorted(names))


def _recipe():
    repo, rosters, reg = fixed_authorities()
    plan, _, _ = verify_prefix(reg, repo, rosters, (), gate='C')
    return dict(year=YEAR, competition=COMPETITION, registration_sha256=codec.digest(codec.canonical(reg.to_dict())),
        plan_sha256=plan.fingerprint, roster_seed=reg.roster_seed, ability_seed=reg.ability_seed,
        selection_seed=reg.selection_seed, bracket_seed=plan.bracket_seed, result_version=RESULT_VERSION,
        model=MODEL, probability_config_sha256=config_digest(probability_model()),
        schema_sha256=codec.digest(codec.canonical(SCHEMA)))


def _rows(snapshot, metadata):
    rows = lab._rows(snapshot.registration, snapshot.rosters, snapshot.results,
                     snapshot.plan, snapshot.ledger, snapshot.ranks)
    rows['lab_meta'] = [(VERSION,)]
    raw = codec.canonical(metadata)
    rows['demo_metadata'] = [(raw, codec.digest(raw))]
    return rows


def _audit(con, metadata):
    schema = con.execute("SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    if len(schema) != len(SCHEMA) or {r[0] for r in schema} != set(SCHEMA):
        raise ValueError('専用デモのschemaが違います')
    if con.execute('PRAGMA journal_mode').fetchone() != ('delete',):
        raise ValueError('DELETE journal専用です')
    if (con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
            or con.execute('PRAGMA foreign_key_check').fetchall()):
        raise ValueError('破損・参照不整合デモです')
    repo, rosters, reg = fixed_authorities()
    results = []
    for raw, sha in con.execute('SELECT result_json,result_sha256 FROM matches ORDER BY match_id'):
        if codec.digest(raw) != sha:
            raise ValueError('試合SHAが違います')
        results.append(decode_result(raw))
    plan, ledger, ranks = verify_prefix(reg, repo, rosters, tuple(results), gate='C')
    snapshot = lab.TournamentSnapshot(reg, rosters, tuple(results), repo, plan, ledger, ranks)
    for table, values in _rows(snapshot, metadata).items():
        if sorted(con.execute(f'SELECT * FROM {table}').fetchall()) != sorted(values):
            raise ValueError('専用デモの登録・入力・結果・進出・順位・metadataが違います: ' + table)
    # Every raw relational row is compared above, including membership-derived participation.
    return snapshot


class _Lease:
    """OS lock released by close/process death. No stale-lock deletion/recovery."""
    def __init__(self, path):
        self.file = path.open('r+b', buffering=0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.file.close()
            raise ValueError('このデモは別プロセスが使用中です') from None

    def close(self):
        self.file.close()


class _WindowsPins:
    """Deny DELETE sharing while a capability is active (native Windows only)."""
    def __init__(self, paths):
        self.handles = []
        if os.name != 'nt':
            return
        import ctypes
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = self.kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        try:
            for path in paths:
                handle = create(str(path), 0, 3, None, 3, 0x02000000 | 0x00200000, None)
                if handle == wintypes.HANDLE(-1).value:
                    raise OSError(ctypes.get_last_error(), '専用デモ実体を固定できません')
                self.handles.append(handle)
        except BaseException:
            self.close()
            raise

    def close(self):
        for handle in self.handles:
            self.kernel.CloseHandle(handle)
        self.handles.clear()


@dataclass(frozen=True)
class _DemoCapability:
    namespace: DemoNamespace
    demo_id: str
    metadata: dict
    identities: tuple


class DemoReader(lab.TournamentLabReader):
    def __init__(self, capability, *, timeout=0.1):
        if type(capability) is not _DemoCapability:
            raise ValueError('専用デモcapabilityが必要です。SQLiteパスは受け取りません')
        self.capability = capability
        self.db_path = capability.namespace.path / capability.demo_id / DATABASE
        self.timeout = timeout

    def _guard(self):
        cap = self.capability
        cap.namespace._check()
        root = self.db_path.parent
        _safe(root)
        if {p.name for p in root.iterdir()} != {MARKER, DATABASE, LEASE}:
            raise ValueError('未知ファイル・journal・未完了保存は再開できません（修復しません）')
        paths = (root, root / MARKER, self.db_path, root / LEASE)
        for path, identity in zip(paths, cap.identities):
            _safe(path, directory=path == root)
            if _identity(path) != identity:
                raise ValueError('専用デモの実体が差し替わっています')
        if (codec.canonical(_read(root / MARKER)) != codec.canonical(cap.metadata)
                or (root / LEASE).stat().st_size != 1):
            raise ValueError('固定markerまたはleaseが違います')

    def snapshot(self):
        self._guard()
        before = hashlib.sha256(self.db_path.read_bytes()).digest()
        # mode=ro deliberately keeps SQLite lock checks; immutable=1 would bypass them.
        with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True, timeout=self.timeout)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            value = _audit(con, self.capability.metadata)
        self._guard()
        if hashlib.sha256(self.db_path.read_bytes()).digest() != before:
            raise ValueError('読取検証中に保存物が変更されました')
        return value


class DemoStore:
    def __init__(self, *args, **kwargs):
        raise ValueError('create / resumeで専用デモを明示選択してください')

    @classmethod
    def create(cls, namespace, *, opt_in=False):
        if type(namespace) is not DemoNamespace or opt_in is not True:
            raise ValueError('専用namespaceへの明示的新規作成が必要です')
        namespace._check()
        recipe = _recipe()
        demo_id = 'demo-' + uuid.uuid4().hex
        root = namespace.path / demo_id
        root.mkdir(mode=0o700)
        db = root / DATABASE
        with db.open('xb'):
            pass
        with (root / LEASE).open('xb') as out:
            out.write(b'0')
        metadata = dict(version=VERSION, namespace=namespace.marker, demo_id=demo_id,
            directory_identity=_identity(root), database_identity=_identity(db), recipe=recipe)
        _exclusive(root / MARKER, metadata)
        repo, rosters, reg = fixed_authorities()
        plan, ledger, ranks = verify_prefix(reg, repo, rosters, (), gate='C')
        snapshot = lab.TournamentSnapshot(reg, rosters, (), repo, plan, ledger, ranks)
        with closing(sqlite3.connect(db.as_uri() + '?mode=rw', uri=True)) as con, con:
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('PRAGMA journal_mode=DELETE')
            con.execute('PRAGMA synchronous=FULL')
            con.execute('BEGIN IMMEDIATE')
            for sql in SCHEMA:
                con.execute(sql)
            for table, rows in _rows(snapshot, metadata).items():
                for row in rows:
                    con.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in row)})', row)
            _audit(con, metadata)
        return cls.resume(namespace, demo_id)

    @classmethod
    def resume(cls, namespace, demo_id):
        if type(namespace) is not DemoNamespace or type(demo_id) is not str or not ID.fullmatch(demo_id):
            raise ValueError('専用namespace内のデモIDを明示選択してください')
        namespace._check()
        root = namespace.path / demo_id
        _safe(root)
        metadata = _read(root / MARKER)
        expected = dict(version=VERSION, namespace=namespace.marker, demo_id=demo_id,
            directory_identity=_identity(root), database_identity=_identity(root / DATABASE), recipe=_recipe())
        if codec.canonical(metadata) != codec.canonical(expected):
            raise ValueError('自作デモの版・実体・seed・出典が違います')
        paths = (root, root / MARKER, root / DATABASE, root / LEASE)
        cap = _DemoCapability(namespace, demo_id, metadata, tuple(_identity(p) for p in paths))
        store = cls.__new__(cls)
        store.capability, store.demo_id, store.db_path = cap, demo_id, root / DATABASE
        store.reader, store.closed = DemoReader(cap), False
        store._mutex = threading.RLock()
        store._lease = store._pins = None
        try:
            store.reader._guard()
            store._pins = _WindowsPins((namespace.path, namespace.path / ROOT_MARKER, *paths))
            store._lease = _Lease(root / LEASE)
            store.reader.snapshot()  # All checks RO, before any SQLite rw connection.
        except BaseException:
            store.close()
            raise
        return store

    def snapshot(self):
        with self._mutex:
            if self.closed:
                raise ValueError('デモは終了しています')
            return self.reader.snapshot()

    def play_next(self, *, expected_checkpoint=None, cancel=None, fault=None):
        """Per-game transaction; cooperative cancel never discards a committed game."""
        with self._mutex:
            snapshot = self.snapshot()
            if snapshot.complete:
                raise ValueError('全31試合が完了しています')
            if expected_checkpoint is not None and expected_checkpoint != checkpoint(snapshot.results):
                raise ValueError('古い進行状況からは保存できません')
            def boundary(at):
                if fault:
                    fault(at)
                if cancel is not None and cancel.is_set():
                    raise InterruptedError('未commitの計算結果は未保存です。commit済みの試合だけ再開できます')
            boundary('before_calculation')
            match = _input(snapshot.plan, snapshot.registration, snapshot.results)
            result = _run(match, match.match_seed)
            event_oracle(result, match)
            boundary('before_transaction')
            self.reader._guard()
            with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=rw', uri=True, timeout=0.1)) as con:
                con.execute('PRAGMA foreign_keys=ON')
                con.execute('PRAGMA synchronous=FULL')
                with con:
                    con.execute('BEGIN IMMEDIATE')
                    previous = _audit(con, self.capability.metadata)
                    if checkpoint(previous.results) != checkpoint(snapshot.results):
                        raise ValueError('保存中に進行状況が変わりました')
                    ledger, ranks = progression_oracle(snapshot.plan, snapshot.registration, snapshot.results + (result,))
                    current = lab.TournamentSnapshot(snapshot.registration, snapshot.rosters,
                        snapshot.results + (result,), snapshot.repo, snapshot.plan, ledger, ranks)
                    before, after = _rows(snapshot, self.capability.metadata), _rows(current, self.capability.metadata)
                    for table, rows in after.items():
                        for row in rows:
                            if row not in before[table]:
                                con.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in row)})', row)
                        boundary(table)
                    _audit(con, self.capability.metadata)
                    boundary('before_commit')
            if fault:
                fault('after_commit')
            return result

    def close(self):
        with self._mutex:
            if self._lease is not None:
                self._lease.close()
                self._lease = None
            if self._pins is not None:
                self._pins.close()
                self._pins = None
            self.closed = True
