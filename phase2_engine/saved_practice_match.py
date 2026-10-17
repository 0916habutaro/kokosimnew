"""Stage114 owned saved31 -> saved2027 -> fictional practice slice.

No product slot, official entry, calendar, ranking or historical writer adapter.
Capabilities establish consistency within a self-created trial, not authenticity.
"""
from contextlib import closing
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from statistics import fmean
import sqlite3

from game_core.school_intake import SchoolAwarePlayerAbilityGenerator
from . import yamanashi_annual_rosters as annual
from . import yamanashi_demo_store as guards
from . import registered_full_a_lab_store as codec
from .career_roster_archive import _decode
from .joint_team_registration_lab import RegisteredAbility, RegisteredTeamInput, LabTeamAbilitySummary, _sha, _identical
from .registered_match_driver import _run
from .registered_full_a_contract import decode_result
from .registered_full_a_oracle import event_oracle

VERSION = 'stage43g114_saved_practice_v1'
INPUT_VERSION = 'stage43g114_practice_input_v1'
KIND = 'fictional_practice'
YEAR, SEED, ABILITY_SEED = 2027, 430114, 430103
SCOPE = 'LAB114:PRACTICE'
MATCH = 'LAB114:2027:PRACTICE:match1'
DATABASE, LEASE = 'practice.sqlite3', 'practice.lease'
USAGE = 'saved2027_position9_returning_and_newcomer_v1'
TABLES = ('practice_contract', 'practice_matches', 'practice_schools', 'practice_players')
DDL = (
    'CREATE TABLE practice_contract (singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL) STRICT',
    'CREATE TABLE practice_matches (match_id TEXT PRIMARY KEY, year INTEGER NOT NULL CHECK(year=2027), '
    "record_kind TEXT NOT NULL CHECK(record_kind='fictional_practice'), input_json TEXT NOT NULL, "
    'input_sha256 TEXT NOT NULL, result_json TEXT NOT NULL, result_sha256 TEXT NOT NULL) STRICT',
    'CREATE TABLE practice_schools (school_id TEXT NOT NULL, year INTEGER NOT NULL, record_kind TEXT NOT NULL, '
    'match_id TEXT NOT NULL REFERENCES practice_matches(match_id), PRIMARY KEY(school_id,year,record_kind,match_id)) STRICT',
    'CREATE TABLE practice_players (player_id TEXT NOT NULL, origin_school_id TEXT NOT NULL, year INTEGER NOT NULL, '
    'record_kind TEXT NOT NULL, match_id TEXT NOT NULL REFERENCES practice_matches(match_id), '
    'PRIMARY KEY(player_id,year,record_kind,match_id)) STRICT',
) + tuple(f'CREATE TRIGGER practice_{table}_{action.lower()} BEFORE {action} ON {table} '
          "BEGIN SELECT RAISE(ABORT, 'append-only practice trial'); END"
          for table in TABLES for action in ('UPDATE', 'DELETE'))


def saved_authority(lab):
    """Revalidate saved31 and acceptance, then decode the actual saved2027 JSON.

    AnnualRosterView uses expected transitions; it is deliberately not our input.
    A source_kind string or a Stage113 roster-only object cannot authorize this.
    """
    if type(lab) is not annual.AnnualRosterLab:
        raise ValueError('Stage111 owned saved31 annual authority required')
    with lab._mutex:
        snap, contract = lab.source.verified()
        state = lab._audit(snap, contract)
        if not state['accepted']:
            raise ValueError('all33 saved2027 acceptance required')
        before = annual._sha(lab.db_path)
        with closing(sqlite3.connect(lab.db_path.as_uri() + '?mode=ro', uri=True, timeout=.1)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            rows = con.execute('SELECT school_id,payload_json,content_sha256 FROM career_school_rosters '
                               'WHERE year=2027 ORDER BY school_id').fetchall()
            accepted = con.execute('SELECT * FROM annual_acceptance').fetchall()
        expected = {t.school_id: t.roster.to_dict() for t in state['transitions']}
        rosters = tuple(_decode(raw) for _, raw, _ in rows)
        if (len(rosters) != 33 or tuple(sid for sid, _, _ in rows) != tuple(sorted(expected))
                or any(r.reference_year != YEAR or r.school_id != sid or len(r.players) != 20
                       or codec.digest(raw) != sha or codec.canonical(r.to_dict()) != raw
                       or not _identical(r.to_dict(), expected[sid])
                       for r, (sid, raw, sha) in zip(rosters, rows))):
            raise ValueError('saved2027 SQL roster authority differs')
        lab._guard()
        if before != annual._sha(lab.db_path) or contract['source_bytes'] != lab.source._evidence():
            raise ValueError('saved authority changed during read')
        receipt = dict(version=VERSION, source_contract=contract,
            source_capability=asdict(lab.source.capability), annual_capability=asdict(lab.capability),
            annual_bytes_sha256=before, annual_acceptance=accepted,
            saved2027_rosters=tuple((sid, sha) for sid, _, sha in rows),
            season_start_authorized=False)
        return snap, rosters, state['lineage'], codec.canonical(receipt)


@dataclass(frozen=True)
class PracticeInput:
    version: str
    record_kind: str
    year: int
    competition_id: str  # internal calculation scope, never a master CMP ID
    match_id: str
    match_seed: int
    ability_seed: int
    source_receipt_sha256: str
    team1: RegisteredTeamInput
    team2: RegisteredTeamInput

    def to_dict(self):
        return asdict(self)


def _team(roster, prior_appeared):
    tid = f'LAB114:2027:SCHOOL:{roster.school_id}'
    generator = SchoolAwarePlayerAbilityGenerator()
    players = tuple(RegisteredAbility(tid, p.player_id, p.school_id,
                    generator.generate(p, YEAR, ABILITY_SEED)) for p in roster.players)
    positions = ('P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF')
    pitchers = sorted((p for p in players if p.snapshot.primary_position == 'P'),
                      key=lambda p: (-p.snapshot.control, p.player_id))
    choices = [(pitchers[0],)] + [tuple(p for p in players if p.snapshot.primary_position == pos)
                                 for pos in positions[1:]]
    freshmen = {p.player_id for p in roster.players if p.entry_year == YEAR}
    # Real saved prior appearance plus a freshman must enter the starting nine.
    options = (nine for nine in product(*choices)
               if {p.player_id for p in nine} & freshmen
               and {p.player_id for p in nine} & prior_appeared)
    chosen = max(options, key=lambda nine: (sum(p.snapshot.contact for p in nine),
                                           tuple(p.player_id for p in nine)), default=None)
    if chosen is None:
        raise ValueError('no position-valid returning/freshman lineup')
    starters = sorted(chosen, key=lambda p: (-p.snapshot.contact, p.player_id))
    lineup = tuple((i, p.snapshot.primary_position, p.player_id) for i, p in enumerate(starters, 1))
    return RegisteredTeamInput(tid, _sha(roster.to_dict()), 'origin_school_intake_v1', USAGE,
        players, lineup, tuple(p.player_id for p in pitchers),
        LabTeamAbilitySummary(tid, USAGE, fmean(p.snapshot.contact for p in players),
            fmean(p.snapshot.power for p in players), fmean(p.snapshot.fielding for p in players),
            fmean(p.snapshot.control for p in pitchers)))


def _input(authority):
    snap, rosters, _, receipt = authority
    singles = {t.school_ids[0] for t in snap.registration.teams if len(t.school_ids) == 1}
    appeared = {p.player_id for r in snap.results for p in r.batter_stats if p.plate_appearances > 0}
    teams = []
    for roster in rosters:
        if roster.school_id not in singles:
            continue
        master = snap.repo.team(roster.school_id)
        if (master.program_id, master.display_name) != (roster.program_id, roster.school_name):
            raise ValueError('saved school differs from master')
        teams.append(_team(roster, appeared))
        if len(teams) == 2:
            break
    if len(teams) != 2:
        raise ValueError('two saved standalone schools required')
    return PracticeInput(INPUT_VERSION, KIND, YEAR, SCOPE, MATCH, SEED, ABILITY_SEED,
                         codec.digest(receipt), *teams)


def practice_input(lab):
    return _input(saved_authority(lab))


def _validate(result, match):
    report = event_oracle(result, match)
    if not _identical(result, _run(match, match.match_seed)):
        raise ValueError('practice result differs from fixed seeded execution')
    # Prove actual batting appearances, beyond just activation of empty rows.
    roster = {p.player_id: p.snapshot for t in (match.team1, match.team2) for p in t.players}
    for team in (match.team1, match.team2):
        active = [r for r in result.batter_stats if r.team_id == team.team_id and r.plate_appearances > 0]
        if not any(roster[r.player_id].academic_year == 1 for r in active):
            raise ValueError('no actual freshman appearance')
        if not any(roster[r.player_id].academic_year in (2, 3) for r in active):
            raise ValueError('no actual returning appearance')
    return report


def simulate_practice(match, lab):
    expected = practice_input(lab)
    if not _identical(match, expected):
        raise ValueError('exact saved practice input required')
    result = _run(match, match.match_seed)
    _validate(result, match)
    return result


@dataclass(frozen=True)
class PracticeCapability:
    root: str
    root_identity: tuple
    file_identity: tuple
    lease_identity: tuple
    contract_json: str


def _rows(match, result):
    raw = result.to_json()
    matches = [(MATCH, YEAR, KIND, codec.canonical(match.to_dict()), _sha(match.to_dict()), raw, codec.digest(raw))]
    schools = sorted((t.players[0].origin_school_id, YEAR, KIND, MATCH) for t in (match.team1, match.team2))
    people = sorted({(e.batter_id, e.batter_origin_school_id, YEAR, KIND, MATCH) for e in result.events}
                    | {(e.pitcher_id, e.pitcher_origin_school_id, YEAR, KIND, MATCH) for e in result.events})
    return dict(practice_matches=matches, practice_schools=schools, practice_players=people)


class PracticeStore:
    """Separate owned append-only SQLite, explicit handles, one fixed practice."""
    close = annual.AnnualRosterLab.close

    def __init__(self, lab, owner, *, opt_in=False):
        if opt_in is not True:
            raise ValueError('explicit owned practice opt-in required')
        authority = saved_authority(lab)  # no target files before full acceptance
        match = _input(authority)
        root = annual._owner(owner)
        for source in (Path(lab.capability.root), Path(lab.source.capability.root)):
            if root == source or root.is_relative_to(source) or source.is_relative_to(root):
                raise ValueError('separate practice root required')
        self.lab, self.owner, self.db_path = lab, owner, root / DATABASE
        self.db_path.touch(exist_ok=False)
        (root / LEASE).write_bytes(b'0')
        raw = codec.canonical(dict(version=VERSION, source_receipt=authority[3], input=match.to_dict()))
        self.capability = PracticeCapability(str(root), tuple(guards._identity(root)),
            tuple(guards._identity(self.db_path)), tuple(guards._identity(root / LEASE)), raw)
        self._setup_handles()
        try:
            with closing(sqlite3.connect(self.db_path)) as con:
                for sql in DDL:
                    con.execute(sql)
                with con:
                    con.execute('INSERT INTO practice_contract VALUES (1,?)', (raw,))
            self.snapshot()
        except BaseException:
            self.close()
            raise

    # AnnualRosterLab._setup_handles hardcodes its lease name; practice pins
    # intentionally have their own explicit paths and the same native helpers.
    def _setup_handles(self):
        import threading
        self.closed = False
        self._mutex = threading.RLock()
        self._lease = self._pins = None
        try:
            self._pins = guards._WindowsPins((self.db_path.parent, self.db_path, self.db_path.parent / LEASE))
            self._lease = guards._Lease(self.db_path.parent / LEASE)
        except BaseException:
            self.close()
            raise

    @classmethod
    def resume(cls, capability, lab):
        if type(capability) is not PracticeCapability:
            raise ValueError('owned practice capability required')
        obj = cls.__new__(cls)
        obj.capability, obj.lab, obj.owner = capability, lab, None
        obj.db_path = Path(capability.root) / DATABASE
        obj._guard()
        obj._setup_handles()
        try:
            obj.snapshot()
        except BaseException:
            obj.close()
            raise
        return obj

    def _guard(self):
        if getattr(self, 'closed', False):
            raise ValueError('practice store closed')
        root = guards._path(self.capability.root)
        if self.db_path != root / DATABASE:
            raise ValueError('practice path differs from owned root')
        guards._safe(root)
        guards._location(root)
        if {p.name for p in root.iterdir()} != {DATABASE, LEASE}:
            raise ValueError('unknown practice file/sidecar/hot journal; no recovery')
        for path, identity in ((root, self.capability.root_identity), (self.db_path, self.capability.file_identity),
                               (root / LEASE, self.capability.lease_identity)):
            guards._safe(path, directory=path == root)
            if tuple(guards._identity(path)) != identity:
                raise ValueError('practice authority replaced')
        if (root / LEASE).stat().st_size != 1:
            raise ValueError('practice lease differs')
        with self.db_path.open('rb') as inp:
            header = inp.read(100)
        if len(header) != 100 or header[:16] != b'SQLite format 3\0' or header[18:20] != b'\x01\x01':
            raise ValueError('only DELETE journal practice SQLite accepted')

    def _audit(self, authority):
        self._guard()
        match = _input(authority)
        contract = codec.canonical(dict(version=VERSION, source_receipt=authority[3], input=match.to_dict()))
        if contract != self.capability.contract_json:
            raise ValueError('practice source/seed/recipe differs')
        before = annual._sha(self.db_path)
        with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True, timeout=.1)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            with closing(sqlite3.connect(':memory:')) as schema:
                for sql in DDL:
                    schema.execute(sql)
                expected_schema = annual._schema(schema)
            if (annual._schema(con) != expected_schema or con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                    or con.execute('PRAGMA foreign_key_check').fetchall()
                    or con.execute('PRAGMA journal_mode').fetchone() != ('delete',)
                    or con.execute('SELECT * FROM practice_contract').fetchall() != [(1, contract)]):
                raise ValueError('practice schema/contract differs')
            rows = con.execute('SELECT * FROM practice_matches').fetchall()
            if len(rows) > 1:
                raise ValueError('only one practice allowed')
            results = ()
            expected = dict(practice_matches=[], practice_schools=[], practice_players=[])
            if rows:
                result = decode_result(rows[0][5])
                _validate(result, match)
                expected = _rows(match, result)
                results = (result,)
            for table, wanted in expected.items():
                if sorted(con.execute(f'SELECT * FROM {table}').fetchall()) != wanted:
                    raise ValueError('practice rows/index/bytes differ')
        self._guard()
        if before != annual._sha(self.db_path):
            raise ValueError('practice changed during RO audit')
        return match, results

    def snapshot(self):
        with self._mutex:
            authority = saved_authority(self.lab)
            match, results = self._audit(authority)
            return PracticeView(authority, match, results)

    def append(self, match, result, *, fault=None):
        with self._mutex:
            authority = saved_authority(self.lab)
            expected, existing = self._audit(authority)
            if not _identical(match, expected):
                raise ValueError('exact practice input required')
            _validate(result, match)
            if existing:
                if not _identical(existing[0], result):
                    raise ValueError('conflicting practice result')
                return False
            self._guard()
            with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=rw', uri=True, timeout=.1)) as con, con:
                con.execute('PRAGMA foreign_keys=ON')
                con.execute('PRAGMA synchronous=FULL')
                con.execute('BEGIN IMMEDIATE')
                if con.execute('SELECT count(*) FROM practice_matches').fetchone() != (0,):
                    raise ValueError('concurrent practice append')
                for table, rows in _rows(match, result).items():
                    placeholders = ','.join('?' for _ in rows[0])
                    con.executemany(f'INSERT INTO {table} VALUES ({placeholders})', rows)
                if fault:
                    fault('before_commit')
            if fault:
                fault('after_commit')
            # Source verification after write detects cross-store changes; this
            # is not a multi-database atomic transaction or a repair facility.
            self.snapshot()
            return True

    def play(self, *, fault=None):
        match = practice_input(self.lab)
        result = _run(match, match.match_seed)
        self.append(match, result, fault=fault)
        return result


class PracticeView:
    """Request-scoped verified view, with explicit year/kind in every record."""
    def __init__(self, authority, match, results):
        self._source, self._rosters, self._lineage, _ = authority
        self.match, self.results = match, results
        self._people = {p.player_id: p for r in (*self._source.rosters, *self._rosters) for p in r.players}

    def _games(self, year):
        if type(year) is not int or year not in (2026, YEAR):
            raise ValueError('only verified2026 and practice2027 years')
        return (self._source.results, 'fictional_tournament') if year == 2026 else (self.results, KIND)

    @staticmethod
    def _record(game, kind):
        return dict(year=game.year, record_kind=kind, match_id=game.match_id, result=game.to_dict())

    def school(self, school_id):
        if school_id not in {r.school_id for r in self._rosters}:
            raise ValueError('unknown saved school')
        tids = {t.team_id for t in self._source.registration.teams if school_id in t.school_ids}
        tids.add(f'LAB114:2027:SCHOOL:{school_id}')
        history = []
        for year in (2026, YEAR):
            games, kind = self._games(year)
            rosters = self._source.rosters if year == 2026 else self._rosters
            history.append(dict(year=year, record_kind=kind,
                roster=next(r.to_dict() for r in rosters if r.school_id == school_id),
                matches=[self._record(g, kind) for g in games if tids.intersection((g.team1_id, g.team2_id))]))
        return dict(school_id=school_id, history=history, season_start_authorized=False,
                    official_2027_outcomes=None, official_2027_schedule=None, official_2027_qualification=None)

    def player(self, player_id):
        person = self._people.get(player_id)
        if person is None:
            raise ValueError('unknown permanent player ID')
        lineage = {pid: state for pid, _, state, _, _ in self._lineage}
        history = []
        for year in (2026, YEAR):
            games, kind = self._games(year)
            rosters = self._source.rosters if year == 2026 else self._rosters
            current = next((p for r in rosters for p in r.players if p.player_id == player_id), None)
            appearances = []
            for game in games:
                batting = [asdict(r) for r in game.batter_stats if r.player_id == player_id and r.plate_appearances > 0]
                pitching = [asdict(r) for r in game.pitcher_stats if r.player_id == player_id and r.batters_faced > 0]
                if batting or pitching:
                    appearances.append(dict(year=year, record_kind=kind, match_id=game.match_id,
                                            batting=batting, pitching=pitching))
            history.append(dict(year=year, record_kind=kind,
                state='active' if current else ('not_yet_enrolled' if year < person.entry_year else 'graduated'),
                profile=current.to_dict() if current else None, appearances=appearances))
        return dict(player_id=player_id, origin_school_id=person.school_id, entry_year=person.entry_year,
                    transition=lineage[player_id], history=history, season_start_authorized=False)
