"""Owned, append-only Stage106 SQLite experiment; no product save integration.

Readers close each native connection and verify fixed recipe + event oracle +
seeded execution. SHA means consistency, never authenticated provenance.
"""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from game_core.players import PlayerRosterGenerator
from .repository import DataRepository
from .joint_team_fixture import YEAR, COMPETITION, ROSTER_SEED, SCHOOLS
from .joint_team_registration_lab import (
    registration_from_rosters, match_input_from_registration, _identical,
    validate_registered_match_input,
)
from .registered_full_a_contract import VERSION, decode_result
from .registered_full_a_oracle import validate_registered_full_a

STORE_VERSION = 'stage43g106_owned_sqlite_v1'
FILENAME = 'registered_full_a_lab.sqlite3'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def strict_json(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate JSON key')
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid JSON') from exc


def identify_result_format(raw):
    """Dispatch only. Legacy identification does NOT certify or convert a game."""
    data = strict_json(raw)
    if type(data) is not dict:
        raise ValueError('result object required')
    if 'version' in data:
        if data['version'] != VERSION:
            raise ValueError('unsupported result version')
        decode_result(raw)  # Exact new structural keys, including all nested rows.
        return VERSION
    # Archived legacy school-keyed A. Do not accept an unversioned new payload.
    required = {'year', 'competition_id', 'match_id', 'team1_id', 'team2_id',
                'team1_score', 'team2_score', 'winner_id', 'loser_id',
                'score_source', 'inning_scores', 'team_stats', 'batter_stats', 'pitcher_stats'}
    if not required <= data.keys() or data['score_source'] != 'ability_model_v1':
        raise ValueError('unrecognized unversioned result')
    for name in ('inning_scores', 'team_stats', 'batter_stats', 'pitcher_stats'):
        if type(data[name]) is not list or not data[name]:
            raise ValueError('complete legacy A arrays required')
        for row in data[name]:
            key = 'batting_team_id' if name == 'inning_scores' else 'school_id'
            if type(row) is not dict or key not in row or 'origin_school_id' in row or 'team_id' in row:
                raise ValueError('legacy school-keyed rows required')
    return 'legacy_school_keyed_unversioned_a'


# SQLite owns the atomic boundary. All provenance and the derived index live
# here; no JSON file / second product database participates in the transaction.
DDL = (
    'CREATE TABLE lab_meta (version TEXT PRIMARY KEY) STRICT',
    'CREATE TABLE school_rosters (school_id TEXT PRIMARY KEY, year INTEGER NOT NULL, '
    'payload_json TEXT NOT NULL, sha256 TEXT NOT NULL) STRICT',
    'CREATE TABLE registrations (year INTEGER NOT NULL, competition_id TEXT NOT NULL, '
    'payload_json TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(year,competition_id)) STRICT',
    'CREATE TABLE teams (year INTEGER NOT NULL, competition_id TEXT NOT NULL, team_id TEXT NOT NULL, '
    'label TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(year,competition_id,team_id), '
    'FOREIGN KEY(year,competition_id) REFERENCES registrations(year,competition_id)) STRICT',
    'CREATE TABLE memberships (year INTEGER NOT NULL, competition_id TEXT NOT NULL, team_id TEXT NOT NULL, '
    'school_id TEXT NOT NULL REFERENCES school_rosters(school_id), '
    'PRIMARY KEY(year,competition_id,team_id,school_id), UNIQUE(year,competition_id,school_id), '
    'FOREIGN KEY(year,competition_id,team_id) REFERENCES teams(year,competition_id,team_id)) STRICT',
    'CREATE TABLE registered_players (year INTEGER NOT NULL, competition_id TEXT NOT NULL, '
    'team_id TEXT NOT NULL, player_id TEXT NOT NULL, origin_school_id TEXT NOT NULL, '
    'team_slot INTEGER NOT NULL CHECK(team_slot BETWEEN 1 AND 20), source_roster_sha256 TEXT NOT NULL, '
    'player_json TEXT NOT NULL, PRIMARY KEY(year,competition_id,player_id), '
    'UNIQUE(year,competition_id,team_id,team_slot), '
    'FOREIGN KEY(year,competition_id,team_id,origin_school_id) '
    'REFERENCES memberships(year,competition_id,team_id,school_id)) STRICT',
    'CREATE TABLE matches (year INTEGER NOT NULL, competition_id TEXT NOT NULL, match_id TEXT NOT NULL, '
    'version TEXT NOT NULL, team1_id TEXT NOT NULL, team2_id TEXT NOT NULL CHECK(team1_id<>team2_id), '
    'registration_sha256 TEXT NOT NULL, input_json TEXT NOT NULL, input_sha256 TEXT NOT NULL, '
    'model TEXT NOT NULL, run_seed INTEGER NOT NULL, probability_config_sha256 TEXT NOT NULL, '
    'result_json TEXT NOT NULL, result_sha256 TEXT NOT NULL, '
    'PRIMARY KEY(year,competition_id,match_id,version), '
    'FOREIGN KEY(year,competition_id,team1_id) REFERENCES teams(year,competition_id,team_id), '
    'FOREIGN KEY(year,competition_id,team2_id) REFERENCES teams(year,competition_id,team_id)) STRICT',
    'CREATE TABLE school_participation (year INTEGER NOT NULL, competition_id TEXT NOT NULL, '
    'match_id TEXT NOT NULL, version TEXT NOT NULL, team_id TEXT NOT NULL, school_id TEXT NOT NULL, '
    'PRIMARY KEY(year,competition_id,match_id,version,team_id,school_id), '
    'FOREIGN KEY(year,competition_id,match_id,version) REFERENCES matches(year,competition_id,match_id,version), '
    'FOREIGN KEY(year,competition_id,team_id,school_id) REFERENCES memberships(year,competition_id,team_id,school_id)) STRICT',
)
TABLES = tuple(sql.split()[2] for sql in DDL)
TRIGGERS = tuple(
    f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
    "BEGIN SELECT RAISE(ABORT, 'append-only lab'); END"
    for table in TABLES for action in ('UPDATE', 'DELETE'))
SCHEMA = DDL + TRIGGERS


def fixed_authorities():
    repo = DataRepository(Path(__file__).resolve().parents[1] / 'data')
    rosters = tuple(PlayerRosterGenerator().generate_for_school_id(repo, sid, YEAR, ROSTER_SEED)
                    for sid in SCHOOLS)
    return repo, rosters, registration_from_rosters(repo, rosters)


def _match(reg, repo, rosters, result):
    return match_input_from_registration(reg, repo, rosters, team1_id=result.team1_id,
                                        team2_id=result.team2_id, opt_in=True)


def _rows(reg, rosters, results, repo):
    rows = {name: [] for name in TABLES}
    rows['lab_meta'] = [(STORE_VERSION,)]
    if not results:
        return rows
    raw = canonical(reg.to_dict())
    rows['registrations'] = [(reg.year, reg.competition_id, raw, digest(raw))]
    for roster in rosters:
        raw = canonical(roster.to_dict())
        rows['school_rosters'].append((roster.school_id, YEAR, raw, digest(raw)))
    for team in reg.teams:
        from dataclasses import asdict
        rows['teams'].append((YEAR, COMPETITION, team.team_id, team.label, digest(canonical(asdict(team)))))
        rows['memberships'].extend((YEAR, COMPETITION, team.team_id, sid) for sid in team.school_ids)
        rows['registered_players'].extend((YEAR, COMPETITION, team.team_id, p.player_id, p.origin_school_id,
            p.team_slot, p.source_roster_sha256, canonical(p.player.to_dict())) for p in team.players)
    for result in results:
        match = _match(reg, repo, rosters, result)
        scope = result.year, result.competition_id, result.match_id, result.version
        raw = result.to_json()
        input_raw = canonical(match.to_dict())
        rows['matches'].append((*scope, result.team1_id, result.team2_id, match.registration_sha256,
            input_raw, result.input_sha256, result.model, result.run_seed,
            result.probability_config_sha256, raw, digest(raw)))
        rows['school_participation'].extend((*scope, team.team_id, sid) for team in reg.teams
            if team.team_id in (result.team1_id, result.team2_id) for sid in team.school_ids)
    return rows


def _schema_check(con):
    actual = con.execute("SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    if {row[0] for row in actual} != set(SCHEMA) or len(actual) != len(SCHEMA):
        raise ValueError('exact isolated lab schema required')
    if con.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or con.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('corrupt/orphaned lab database')


def _audit(con, repo, rosters, reg):
    """Verify all rows, not just a query hit. Reject extra/missing authorities."""
    _schema_check(con)
    results = []
    for raw, sha in con.execute('SELECT result_json,result_sha256 FROM matches ORDER BY year,competition_id,match_id,version'):
        if digest(raw) != sha or identify_result_format(raw) != VERSION:
            raise ValueError('result digest/version differs')
        result = decode_result(raw)
        match = _match(reg, repo, rosters, result)
        # Never trust decode or SQL totals alone. Fixed Stage105 seed is required.
        validate_registered_full_a(result, match, reg, repo, rosters)
        results.append(result)
    expected = _rows(reg, rosters, results, repo)
    for table, rows in expected.items():
        actual = con.execute(f'SELECT * FROM {table}').fetchall()
        if sorted(actual) != sorted(rows):
            raise ValueError(f'{table} provenance/contents differ')
    # Separately inspect derived index via relational membership, not JSON labels.
    derived = con.execute('''SELECT m.year,m.competition_id,m.match_id,m.version,t.team_id,t.school_id
        FROM matches m JOIN memberships t ON m.year=t.year AND m.competition_id=t.competition_id
        AND t.team_id IN (m.team1_id,m.team2_id) ORDER BY 1,2,3,4,5,6''').fetchall()
    indexed = con.execute('SELECT * FROM school_participation ORDER BY 1,2,3,4,5,6').fetchall()
    if derived != indexed:
        raise ValueError('derived school participation differs from membership')
    return tuple(results)


class RegisteredFullALabStore:
    """Writer capability is a live caller-owned TemporaryDirectory, never a path.

    Keep that owner alive until restart experiments end. Cleanup explicitly ends
    retention: this lab does not promise permanent product storage.
    """
    def __init__(self, owner, *, journal_mode='DELETE', timeout=0.1):
        if (type(owner) is not tempfile.TemporaryDirectory or not Path(owner.name).is_dir()
                or Path(owner.name).absolute() != Path(owner.name).resolve()):
            raise ValueError('live self-owned TemporaryDirectory required')
        if journal_mode not in ('DELETE', 'WAL'):
            raise ValueError('DELETE or WAL required')
        self.owner = owner
        self.db_path = Path(owner.name).resolve() / FILENAME
        self.timeout = timeout
        # Refuse ALL pre-existing files, including product DBs, without opening.
        fd = os.open(self.db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        stat = self.db_path.stat()
        self._file_identity = (stat.st_dev, stat.st_ino)
        with closing(sqlite3.connect(self.db_path, timeout=timeout)) as con:
            con.execute('PRAGMA foreign_keys=ON')
            con.execute(f'PRAGMA journal_mode={journal_mode}')
            with con:
                con.execute('BEGIN IMMEDIATE')
                for sql in SCHEMA:
                    con.execute(sql)
                con.execute('INSERT INTO lab_meta VALUES (?)', (STORE_VERSION,))

    def append(self, result, match, registration, repo, rosters, *, fault=None):
        if not Path(self.owner.name).is_dir() or self.db_path.is_symlink():
            raise ValueError('owned lab no longer available')
        stat = self.db_path.stat()
        if (stat.st_dev, stat.st_ino) != self._file_identity:
            raise ValueError('owned database was replaced')
        validate_registered_match_input(match, registration, repo, rosters)
        validate_registered_full_a(result, match, registration, repo, rosters)
        fixed_repo, fixed_rosters, fixed_reg = fixed_authorities()
        if not _identical(registration, fixed_reg):
            raise ValueError('fixed self-generated registration required')
        with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=rw', uri=True, timeout=self.timeout)) as con:
            con.execute('PRAGMA foreign_keys=ON')
            with con:
                con.execute('BEGIN IMMEDIATE')  # serialize read/check/insert races
                old = _audit(con, fixed_repo, fixed_rosters, fixed_reg)
                key = result.year, result.competition_id, result.match_id, result.version
                existing = next((r for r in old if (r.year,r.competition_id,r.match_id,r.version) == key), None)
                if existing is not None:
                    if not _identical(existing, result):
                        raise ValueError('immutable result conflict')
                    return False
                expected = _rows(fixed_reg, fixed_rosters, old + (result,), fixed_repo)
                previous = _rows(fixed_reg, fixed_rosters, old, fixed_repo)
                for table, rows in expected.items():
                    for row in rows:
                        if row not in previous[table]:
                            placeholders = ','.join('?' for _ in row)
                            con.execute(f'INSERT INTO {table} VALUES ({placeholders})', row)
                    if fault:
                        fault(table)  # test-only failure injection; transaction rolls back
                _audit(con, fixed_repo, fixed_rosters, fixed_reg)
                if fault:
                    fault('before_commit')
        return True


@dataclass(frozen=True)
class VerifiedLabSnapshot:
    registration: object
    rosters: tuple
    results: tuple
    repo: object


class RegisteredFullALabReader:
    """Every request revalidates a single read-only SQLite snapshot and closes it."""
    def __init__(self, db_path, *, timeout=0.1):
        self.db_path = Path(db_path).resolve()
        self.timeout = timeout

    def snapshot(self):
        repo, rosters, reg = fixed_authorities()
        with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True, timeout=self.timeout)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            results = _audit(con, repo, rosters, reg)
        return VerifiedLabSnapshot(reg, rosters, results, repo)

    @staticmethod
    def _scope(year, competition_id):
        if type(year) is not int or year != YEAR or type(competition_id) is not str or competition_id != COMPETITION:
            raise ValueError('outside fixed lab year/competition')

    def match(self, year, competition_id, match_id, *, version=VERSION):
        self._scope(year, competition_id)
        if type(match_id) is not str or version != VERSION:
            raise ValueError('unsupported result key/version')
        snapshot = self.snapshot()
        return next((r for r in snapshot.results if r.match_id == match_id), None)

    def team(self, team_id, *, year=YEAR, competition_id=COMPETITION):
        self._scope(year, competition_id)
        snapshot = self.snapshot()
        if not snapshot.results:
            raise ValueError('no saved registration')
        team = next((t for t in snapshot.registration.teams if t.team_id == team_id), None)
        if team is None:
            raise ValueError('unknown registered team')
        return dict(team=team, matches=tuple(r for r in snapshot.results if team_id in (r.team1_id,r.team2_id)))

    def school(self, school_id, *, year=YEAR, competition_id=COMPETITION):
        self._scope(year, competition_id)
        snapshot = self.snapshot()
        if not snapshot.results:
            raise ValueError('no saved registration')
        if school_id not in SCHOOLS:
            raise ValueError('unknown fixture school')
        teams = tuple(t for t in snapshot.registration.teams if school_id in t.school_ids)
        tids = {t.team_id for t in teams}
        return dict(school_id=school_id, participating_teams=teams,
                    matches=tuple(r for r in snapshot.results if tids.intersection((r.team1_id,r.team2_id))),
                    school_standalone_outcomes=None)

    def player(self, player_id, *, year=YEAR, competition_id=COMPETITION):
        self._scope(year, competition_id)
        snapshot = self.snapshot()
        if not snapshot.results:
            raise ValueError('no saved registration')
        origins = {p.player_id: p.school_id for roster in snapshot.rosters for p in roster.players}
        if player_id not in origins:
            raise ValueError('unknown permanent player')
        appearances = []
        for result in snapshot.results:
            bat = tuple(r for r in result.batter_stats if r.player_id == player_id)
            pitch = tuple(r for r in result.pitcher_stats if r.player_id == player_id)
            if bat or pitch:
                appearances.append(dict(result=result, batting=bat, pitching=pitch))
        return dict(player_id=player_id, origin_school_id=origins[player_id], appearances=tuple(appearances))
