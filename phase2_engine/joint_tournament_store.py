"""Stage107 owned append-only SQLite. No product save path or restore API.

A parent retains TemporaryDirectory ownership across spawned workers. Only a
capability minted by that store permits resumption; readers accept paths RO.
"""
from contextlib import closing
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import sqlite3
import tempfile

from . import registered_full_a_lab_store as old
from .joint_team_registration_lab import _identical
from .registered_full_a_contract import VERSION, decode_result
from .joint_tournament_lab import fixed_plan, next_match_input, verify_prefix, validate_tournament_input
from .joint_tournament_oracle import player_totals

STORE_VERSION = 'stage43g107_owned_tournament_sqlite_v1'
FILENAME = 'joint_tournament_107.sqlite3'
DDL = old.DDL + (
    'CREATE TABLE tournament_plan (year INTEGER NOT NULL, competition_id TEXT NOT NULL, '
    'payload_json TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(year,competition_id), '
    'FOREIGN KEY(year,competition_id) REFERENCES registrations(year,competition_id)) STRICT',
    'CREATE TABLE advancement (sequence INTEGER PRIMARY KEY, match_id TEXT NOT NULL, '
    'source TEXT NOT NULL, team_id TEXT NOT NULL) STRICT',
    'CREATE TABLE team_ranks (rank INTEGER PRIMARY KEY CHECK(rank BETWEEN 1 AND 3), '
    'team_id TEXT NOT NULL UNIQUE, wins INTEGER NOT NULL, losses INTEGER NOT NULL) STRICT',
)
TABLES = tuple(sql.split()[2] for sql in DDL)
TRIGGERS = tuple(
    f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
    "BEGIN SELECT RAISE(ABORT, 'append-only lab'); END"
    for table in TABLES for action in ('UPDATE', 'DELETE'))
SCHEMA = DDL + TRIGGERS


def _rows(reg, rosters, results, plan, ledger, ranks):
    """Independent Stage107 serialization; never use Stage106 fixed _match."""
    rows = {name: [] for name in TABLES}
    rows['lab_meta'] = [(STORE_VERSION,)]
    raw = old.canonical(reg.to_dict())
    rows['registrations'] = [(reg.year, reg.competition_id, raw, old.digest(raw))]
    for roster in rosters:
        raw = old.canonical(roster.to_dict())
        rows['school_rosters'].append((roster.school_id, reg.year, raw, old.digest(raw)))
    for team in reg.teams:
        rows['teams'].append((reg.year, reg.competition_id, team.team_id, team.label,
                              old.digest(old.canonical(asdict(team)))))
        rows['memberships'].extend((reg.year, reg.competition_id, team.team_id, sid) for sid in team.school_ids)
        rows['registered_players'].extend((reg.year, reg.competition_id, team.team_id,
            p.player_id, p.origin_school_id, p.team_slot, p.source_roster_sha256,
            old.canonical(p.player.to_dict())) for p in team.players)
    raw = old.canonical(plan.to_dict())
    rows['tournament_plan'] = [(reg.year, reg.competition_id, raw, old.digest(raw))]
    # _input is safe only after verify_prefix. It is never a general reader.
    from .joint_tournament_lab import _input
    for i, result in enumerate(results):
        match = _input(plan, reg, results[:i])
        scope = result.year, result.competition_id, result.match_id, result.version
        raw = result.to_json()
        rows['matches'].append((*scope, result.team1_id, result.team2_id,
            match.registration_sha256, old.canonical(match.to_dict()), result.input_sha256,
            result.model, result.run_seed, result.probability_config_sha256, raw, old.digest(raw)))
        rows['school_participation'].extend((*scope, t.team_id, sid) for t in reg.teams
            if t.team_id in (result.team1_id, result.team2_id) for sid in t.school_ids)
    rows['advancement'] = [tuple(asdict(row).values()) for row in ledger]
    rows['team_ranks'] = [tuple(asdict(row).values()) for row in ranks]
    return rows


@dataclass(frozen=True)
class TournamentSnapshot:
    registration: object
    rosters: tuple
    results: tuple
    repo: object
    plan: object
    ledger: tuple
    ranks: tuple

    @property
    def complete(self):
        return len(self.results) == 2 and len(self.ranks) == 3


def _audit(con):
    actual = con.execute("SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    if len(actual) != len(SCHEMA) or {row[0] for row in actual} != set(SCHEMA):
        raise ValueError('exact Stage107 schema required')
    if con.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or con.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('corrupt/orphaned tournament')
    repo, rosters, reg = old.fixed_authorities()
    results = []
    for raw, sha in con.execute('SELECT result_json,result_sha256 FROM matches ORDER BY match_id'):
        if old.digest(raw) != sha or old.identify_result_format(raw) != VERSION:
            raise ValueError('result digest/version differs')
        results.append(decode_result(raw))
    results = tuple(results)
    plan, ledger, ranks = verify_prefix(reg, repo, rosters, results)
    expected = _rows(reg, rosters, results, plan, ledger, ranks)
    for table, rows in expected.items():
        if sorted(con.execute(f'SELECT * FROM {table}').fetchall()) != sorted(rows):
            raise ValueError(f'{table} authority/contents differ')
    derived = con.execute('''SELECT m.year,m.competition_id,m.match_id,m.version,t.team_id,t.school_id
        FROM matches m JOIN memberships t ON m.year=t.year AND m.competition_id=t.competition_id
        AND t.team_id IN(m.team1_id,m.team2_id) ORDER BY 1,2,3,4,5,6''').fetchall()
    if derived != con.execute('SELECT * FROM school_participation ORDER BY 1,2,3,4,5,6').fetchall():
        raise ValueError('school participation relational index differs')
    return TournamentSnapshot(reg, rosters, results, repo, plan, ledger, ranks)


@dataclass(frozen=True)
class _ResumeCapability:
    directory: str
    directory_identity: tuple
    file_identity: tuple


def _identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino


class OwnedTournamentStore:
    def __init__(self, owner, *, journal_mode='DELETE', timeout=0.1):
        if (type(owner) is not tempfile.TemporaryDirectory or not Path(owner.name).is_dir()
                or Path(owner.name).is_symlink() or Path(owner.name).is_junction()):
            raise ValueError('live self-owned TemporaryDirectory required')
        if journal_mode not in ('DELETE', 'WAL'):
            raise ValueError('DELETE or WAL required')
        self.owner = owner
        root = Path(owner.name).resolve()
        self.db_path = root / FILENAME
        self.timeout = timeout
        fd = os.open(self.db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        self._capability = _ResumeCapability(str(root), _identity(root), _identity(self.db_path))
        repo, rosters, reg = old.fixed_authorities()
        plan, ledger, ranks = verify_prefix(reg, repo, rosters, ())
        rows = _rows(reg, rosters, (), plan, ledger, ranks)
        with closing(sqlite3.connect(self.db_path, timeout=timeout)) as con, con:
            con.execute('PRAGMA foreign_keys=ON')
            con.execute(f'PRAGMA journal_mode={journal_mode}')
            con.execute('BEGIN IMMEDIATE')
            for sql in SCHEMA:
                con.execute(sql)
            for table, values in rows.items():
                for row in values:
                    con.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in row)})', row)
            _audit(con)

    def resume_capability(self):
        """Private fixture transport; parent must keep original owner alive."""
        self._owned()
        return self._capability

    @classmethod
    def resume(cls, capability, *, timeout=0.1):
        if type(capability) is not _ResumeCapability:
            raise ValueError('owned Stage107 capability required, never a path')
        store = cls.__new__(cls)
        store.owner = None  # The parent retains the TemporaryDirectory lease.
        store._capability = capability
        store.db_path = Path(capability.directory) / FILENAME
        store.timeout = timeout
        store._owned()
        TournamentLabReader(store.db_path).snapshot()
        return store

    def _owned(self):
        root = Path(self._capability.directory)
        if (not root.is_dir() or root.is_symlink() or root.is_junction()
                or self.db_path.is_symlink() or self.db_path.is_junction()
                or _identity(root) != self._capability.directory_identity
                or _identity(self.db_path) != self._capability.file_identity):
            raise ValueError('owned tournament directory/database unavailable or replaced')

    def append(self, result, match, *, fault=None):
        self._owned()
        with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=rw', uri=True, timeout=self.timeout)) as con:
            con.execute('PRAGMA foreign_keys=ON')
            with con:
                con.execute('BEGIN IMMEDIATE')
                old_snapshot = _audit(con)
                reg, repo, rosters = old_snapshot.registration, old_snapshot.repo, old_snapshot.rosters
                previous = old_snapshot.results
                index = next((i for i, r in enumerate(previous) if r.match_id == result.match_id), len(previous))
                validate_tournament_input(match, reg, repo, rosters, previous[:index])
                if index < len(previous):
                    if not _identical(result, previous[index]):
                        raise ValueError('immutable tournament result conflict')
                    return False
                if len(previous) == 1 and fault:
                    fault('before_match2')
                current = previous + (result,)
                plan, ledger, ranks = verify_prefix(reg, repo, rosters, current)
                expected = _rows(reg, rosters, current, plan, ledger, ranks)
                before = _rows(reg, rosters, previous, old_snapshot.plan, old_snapshot.ledger, old_snapshot.ranks)
                for table, rows in expected.items():
                    for row in rows:
                        if row not in before[table]:
                            con.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in row)})', row)
                    if fault:
                        fault(table)
                _audit(con)
                if fault:
                    fault('before_commit')
        # Failure here means committed-but-unacknowledged; retry is a no-op.
        if fault:
            fault('after_commit')
        return True

    def play_next(self, *, fault=None):
        self._owned()
        snapshot = TournamentLabReader(self.db_path).snapshot()
        reg, repo, rosters = snapshot.registration, snapshot.repo, snapshot.rosters
        if len(snapshot.results) == 1 and fault:
            fault('before_final_calculation')
        match = next_match_input(reg, repo, rosters, snapshot.results, opt_in=True)
        from .joint_tournament_lab import simulate_tournament_match
        result = simulate_tournament_match(match, reg, repo, rosters, snapshot.results)
        self.append(result, match, fault=fault)
        return result


class TournamentLabReader(old.RegisteredFullALabReader):
    """Same origin/participation search semantics, new exact reader and totals."""
    def snapshot(self):
        with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True, timeout=self.timeout)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            return _audit(con)

    def tournament(self):
        snapshot = self.snapshot()
        if not snapshot.complete:
            raise ValueError('tournament incomplete; final ranks unavailable')
        return snapshot

    def player(self, player_id, **scope):
        view = super().player(player_id, **scope)
        # super() validates the same single snapshot for every appearance.
        view['totals'] = player_totals(tuple(a['result'] for a in view['appearances']), player_id)
        return view
