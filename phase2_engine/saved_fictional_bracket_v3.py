"""Stage119-C independent v3 trial: guarded SQLite, explicit trust and hash chain.

Stage116 v1 (`saved_fictional_tournament`) is reused read-only and never
modified. No official-year, product slot, archive or outcomes adapter exists.
"""
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from pathlib import Path
import hashlib
import os
from functools import wraps
import sqlite3
import threading

from . import fictional_v3_dependencies as dependencies
from . import competition_evidence_gates as gates
from . import saved_fictional_tournament as v1
from . import saved_practice_match as practice
from . import yamanashi_annual_rosters as annual
from . import yamanashi_demo_store as guards
from . import registered_full_a_lab_store as codec
from .fictional_bracket import Bracket, plan_slots
from .fictional_bracket_oracle import progression
from .joint_team_registration_lab import RegisteredTeamInput, _identical, _sha
from .randomness import rng_for
from .registered_full_a_contract import RegisteredBatterStatsV1, RegisteredPitcherStatsV1, decode_result
from .registered_match_driver import _run

VERSION = 'stage43g119_fictional_bracket_v3'
INPUT_VERSION = 'stage43g119_fictional_bracket_match_input_v3'
KIND, YEAR, SEED, ABILITY_SEED = 'fictional_bracket_tournament', 2027, 430119, v1.ABILITY_SEED
DATABASE, LEASE = 'fictional_bracket_v3.sqlite3', 'fictional_bracket_v3.lease'
APPLICATION_ID, USER_VERSION, K = 0x4B563303, 3, 8
TABLES = ('v3_contract', 'v3_matches', 'v3_advancement', 
          'v3_players', 'v3_ranks', 'v3_acceptance')
DDL = (
    'CREATE TABLE v3_contract (singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL) STRICT',
    'CREATE TABLE v3_matches (sequence INTEGER PRIMARY KEY CHECK(sequence BETWEEN 1 AND 31), '
    'match_id TEXT NOT NULL UNIQUE, round_no INTEGER NOT NULL CHECK(round_no BETWEEN 1 AND 5), '
    'year INTEGER NOT NULL CHECK(year=2027), '
    "record_kind TEXT NOT NULL CHECK(record_kind='fictional_bracket_tournament'), namespace TEXT NOT NULL, "
    'day TEXT NOT NULL, input_json TEXT NOT NULL, input_sha256 TEXT NOT NULL, '
    'result_json TEXT NOT NULL, result_sha256 TEXT NOT NULL, '
    'previous_chain_sha256 TEXT NOT NULL, chain_sha256 TEXT NOT NULL UNIQUE) STRICT',
    'CREATE TABLE v3_advancement (step INTEGER NOT NULL, round_no INTEGER NOT NULL, '
    "source TEXT NOT NULL CHECK(source IN ('BYE','WINNER')), team_id TEXT NOT NULL, "
    'PRIMARY KEY(step, team_id)) STRICT',
    'CREATE TABLE v3_players (player_id TEXT NOT NULL, origin_school_id TEXT NOT NULL, '
    'entry_team_id TEXT NOT NULL, year INTEGER NOT NULL, record_kind TEXT NOT NULL, namespace TEXT NOT NULL, '
    'match_id TEXT NOT NULL REFERENCES v3_matches(match_id), '
    'PRIMARY KEY(player_id,year,record_kind,namespace,match_id)) STRICT',
    'CREATE TABLE v3_ranks (team_id TEXT PRIMARY KEY, rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 32), '
    'wins INTEGER NOT NULL, losses INTEGER NOT NULL) STRICT',
    'CREATE TABLE v3_acceptance (singleton INTEGER PRIMARY KEY CHECK(singleton=1), '
    'champion_team_id TEXT NOT NULL, games INTEGER NOT NULL, chain_sha256 TEXT NOT NULL) STRICT',
    'CREATE INDEX v3_players_match ON v3_players(match_id)'
) + tuple(f'CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} '
          "BEGIN SELECT RAISE(ABORT, 'append-only fictional bracket'); END"
          for table in TABLES for action in ('UPDATE', 'DELETE'))
GATES = ('entries', 'joints', 'qualification', 'districts', 'seeds', 'draw', 'schedule')


@dataclass(frozen=True)
class GamePlan:
    sequence: int
    round_no: int
    position: int
    match_id: str
    day: str
    seed: int


@dataclass(frozen=True)
class BracketPlan:
    version: str
    namespace: str
    scope: str
    scenario_seed: int
    slots: tuple
    games: tuple[GamePlan, ...]


@dataclass(frozen=True)
class BracketMatchInput:
    version: str
    record_kind: str
    year: int
    namespace: str
    competition_id: str
    match_id: str
    day: str
    sequence: int
    round_no: int
    scenario_seed: int
    match_seed: int
    ability_seed: int
    contract_sha256: str
    previous_chain_sha256: str
    team1: RegisteredTeamInput
    team2: RegisteredTeamInput

    def to_dict(self):
        return asdict(self)


def _prepare(lab, request, seed, opt_in):
    if opt_in is not True or type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError('explicit fictional opt-in and independent scenario seed required')
    report = gates.dry_run(lab, request, fictional_opt_in=opt_in)
    if not report.fictional_scenario_ready or report.official_year_verified or report.product_season_start_authorized:
        raise ValueError('all individual fictional evidence gates required')
    for name in GATES:
        source = getattr(request, name).evidence.source.casefold()
        if (not source.startswith('self-created declaration/')
                or any(s in source for s in ('official', 'verified', 'http:', 'https:', '公式', '認証'))):
            raise ValueError('execution requires an unambiguous self-created source label')
    if any(d.basis != 'explicit_scenario' for d in request.qualification.decisions):
        # A 2026 game history is never a 2027 qualification in this stage.
        raise ValueError('explicit scenario qualification required for every entry')
    authority = practice.saved_authority(lab)
    if codec.digest(authority[3]) != dict(report.evidence_digests)['prior_sealed_year']:
        raise ValueError('source changed between gate and SQL authority')
    people = {p.player_id: p for r in authority[1] for p in r.players}
    for entry in request.entries.teams:
        counts = [sum(people[pid].school_id == sid for pid in entry.player_ids) for sid, _ in entry.programs]
        if len(entry.programs) > 2 or counts != [20 // len(entry.programs)] * len(entry.programs):
            raise ValueError('explicit separate20 or joint10+10 registration required')
    appeared = {r.player_id for g in authority[0].results for r in g.batter_stats if r.plate_appearances}
    teams = tuple(v1._team(t, authority[1], appeared) for t in request.entries.teams)
    rng = rng_for(seed, 'stage119:draw:' + request.namespace)
    slots = plan_slots([t.team_id for t in teams], request.seeds.seeds, rng, request.draw.bracket_size)
    bracket = Bracket(slots)
    scope = 'LAB119:2027:FICTIONAL:' + _sha((request.namespace, seed))[:16]
    games = tuple(GamePlan(g.sequence, g.round_no, g.position, f'{scope}:r{g.round_no}:g{g.position + 1}',
        request.schedule.round_dates[g.round_no - 1], rng_for(seed, f'stage119:match:{g.sequence}').randrange(2**63))
        for g in bracket.games)
    plan = BracketPlan(VERSION, request.namespace, scope, seed, slots, games)
    progression(plan, request, ())
    contract = codec.canonical(dict(version=VERSION, record_kind=KIND, year=YEAR,
        fast_path_limit=K, request=gates._payload(request), scenario_seed=seed, gates=report.to_dict(),
        source_receipt=authority[3], plan=asdict(plan), teams=[asdict(t) for t in teams]))
    return authority, plan, bracket, teams, contract


def _chain(previous, input_sha='', result_sha=''):
    return hashlib.sha256(('kokosim-v3-chain\0' + previous + input_sha + result_sha).encode('ascii')).hexdigest()


def _input(prepared, results, previous):
    _, plan, bracket, teams, contract = prepared
    if len(results) >= len(plan.games):
        raise ValueError('fictional bracket already complete')
    game = plan.games[len(results)]
    pair = bracket.pair(game.sequence, results)
    if pair is None:
        raise ValueError('previous actual winners required')
    by_id = {t.team_id: t for t in teams}
    return BracketMatchInput(INPUT_VERSION, KIND, YEAR, plan.namespace, plan.scope, game.match_id, game.day,
        game.sequence, game.round_no, plan.scenario_seed, game.seed, ABILITY_SEED, codec.digest(contract),
        previous, *(by_id[tid] for tid in pair))


def _audit_rows(prepared, request, results):
    """Full independent derivation. Never calls incremental row builders.

    Only input/result SHA for the current game is serialized in the loop;
    no previous-results prefix JSON is constructed.
    """
    _, plan, bracket, _, contract = prepared
    ledger, ranks = progression(plan, request, results)
    if [(r, t) for r, t, _, _ in ranks] != bracket.ranks(results):
        raise ValueError('bracket graph and progression oracle disagree')
    rows = {table: [] for table in TABLES if table != 'v3_contract'}
    heads = [_chain(codec.digest(contract))]
    prefix = []
    for i, result in enumerate(results):
        match = _input(prepared, prefix, heads[-1])
        if (result.team1_id, result.team2_id) != (match.team1.team_id, match.team2.team_id):
            raise ValueError('participant oracle differs')
        v1._validate(result, match)
        raw, input_raw = result.to_json(), codec.canonical(match.to_dict())
        input_sha, result_sha = codec.digest(input_raw), codec.digest(raw)
        head = _chain(heads[-1], input_sha, result_sha)
        rows['v3_matches'].append((i + 1, result.match_id, match.round_no, YEAR, KIND, plan.namespace,
            match.day, input_raw, input_sha, raw, result_sha, heads[-1], head))
        people = set()
        for event in result.events:
            people.add((event.batter_id, event.batter_origin_school_id, event.offense_team_id,
                        YEAR, KIND, plan.namespace, result.match_id))
            people.add((event.pitcher_id, event.pitcher_origin_school_id, event.defense_team_id,
                        YEAR, KIND, plan.namespace, result.match_id))
        rows['v3_players'].extend(people)
        heads.append(head)
        prefix.append(result)
    rows['v3_advancement'] = ledger
    rows['v3_ranks'] = [(tid, rank, w, l) for rank, tid, w, l in ranks]
    if ranks:
        rows['v3_acceptance'] = [(1, ranks[0][1], len(results), heads[-1])]
    return {key: sorted(value) for key, value in rows.items()}, tuple(heads)


def _public(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._mutex:
            try:
                if self.closed:
                    raise ValueError('v3 store closed')
                return method(self, *args, **kwargs)
            except BaseException:
                if not self.closed:
                    self.state = 'REVOKED'
                raise
    return guarded


@dataclass(frozen=True)
class BracketCapability:
    root: str
    root_identity: tuple
    file_identity: tuple
    lease_identity: tuple
    contract_json: str


class FictionalBracketStore:
    """Separate v3 capability; never adopts or migrates a legacy save."""
    def __init__(self, lab, owner, request, *, scenario_seed=SEED, fictional_opt_in=False):
        manifest = dependencies.capture(lab)
        with dependencies.read_boundary(manifest):
            prepared = _prepare(lab, request, scenario_seed, fictional_opt_in)
        dependencies.check(lab, manifest)
        root = annual._owner(owner)
        for source in (Path(lab.capability.root), Path(lab.source.capability.root)):
            if root == source or root.is_relative_to(source) or source.is_relative_to(root):
                raise ValueError('separate fictional v3 root required')
        self.lab, self.owner, self.request, self.scenario_seed = lab, owner, request, scenario_seed
        self.db_path = root / DATABASE
        self.db_path.touch(exist_ok=False)
        (root / LEASE).write_bytes(b'0')
        self.capability = BracketCapability(str(root), tuple(guards._identity(root)),
            tuple(guards._identity(self.db_path)), tuple(guards._identity(root / LEASE)), prepared[4])
        self._setup_handles()
        try:
            with closing(sqlite3.connect(self.db_path)) as con:
                con.execute('PRAGMA journal_mode=DELETE')
                con.execute('PRAGMA synchronous=FULL')
                con.execute(f'PRAGMA application_id={APPLICATION_ID}')
                con.execute(f'PRAGMA user_version={USER_VERSION}')
                con.execute('BEGIN IMMEDIATE')
                for sql in DDL:
                    con.execute(sql)
                con.execute('INSERT INTO v3_contract VALUES (1,?,?)',
                            (prepared[4], codec.digest(prepared[4])))
                con.executemany('INSERT INTO v3_advancement VALUES (?,?,?,?)',
                                progression(prepared[1], request, ())[0])
                con.commit()
            self.full_audit()
        except BaseException:
            self.close()
            raise

    def _setup_handles(self):
        self.closed, self._mutex, self._lease, self._pins = False, threading.RLock(), None, None
        self.state, self._pid = 'REVOKED', os.getpid()
        try:
            root = self.db_path.parent
            self._pins = guards._WindowsPins((root, self.db_path, root / LEASE))
            self._lease = guards._Lease(root / LEASE)
        except BaseException:
            self.close()
            raise

    @classmethod
    def resume(cls, capability, lab, *, fictional_opt_in=False):
        if type(capability) is not BracketCapability or fictional_opt_in is not True:
            raise ValueError('owned v3 capability and explicit opt-in required')
        obj = cls.__new__(cls)
        obj.capability, obj.lab, obj.owner = capability, lab, None
        obj.db_path = Path(capability.root) / DATABASE
        obj._guard()
        data = codec.strict_json(capability.contract_json)
        if data.get('version') != VERSION:
            raise ValueError('v3 contract version differs')
        obj.request, obj.scenario_seed = v1.decode_request(data['request']), data['scenario_seed']
        obj._setup_handles()
        try:
            obj.full_audit()
        except BaseException:
            obj.close()
            raise
        return obj

    def close(self):
        with self._mutex:
            if self._lease is not None:
                self._lease.close()
                self._lease = None
            if self._pins is not None:
                self._pins.close()
                self._pins = None
            self.closed, self.state = True, 'CLOSED'

    @_public
    def invalidate(self):
        self.state = 'REVOKED'

    def _check_pid(self):
        if self._pid != os.getpid():
            raise ValueError('forked v3 capability must not inherit trust or lease')

    def _check_trust(self):
        self._check_pid()
        if self.state not in ('TRUSTED', 'COMPLETE'):
            raise ValueError('explicit successful full_audit required after revocation')
        self._guard()
        if annual._sha(self.db_path) != self._digest:
            raise ValueError('v3 DB bytes changed since trusted boundary')
        dependencies.check(self.lab, self._manifest)
        if self.request != self._request or self.scenario_seed != self._seed:
            raise ValueError('request/seed changed after audit')

    @_public
    def full_audit(self):
        """Read-only independent replay; failure leaves bytes untouched and trust revoked."""
        self._check_pid()
        self.state = 'REVOKED'
        self._guard()
        before = annual._sha(self.db_path)
        manifest = dependencies.capture(self.lab)
        with dependencies.read_boundary(manifest, (self.db_path,)):
            prepared = _prepare(self.lab, self.request, self.scenario_seed, True)
            if prepared[4] != self.capability.contract_json:
                raise ValueError('v3 source/request/seed/contract differs')
            with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True, timeout=.1)) as con:
                con.execute('PRAGMA query_only=ON')
                con.execute('BEGIN')
                with closing(sqlite3.connect(':memory:')) as schema:
                    for sql in DDL:
                        schema.execute(sql)
                    expected_schema = annual._schema(schema)
                if (annual._schema(con) != expected_schema
                        or con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                        or con.execute('PRAGMA foreign_key_check').fetchall()
                        or con.execute('PRAGMA journal_mode').fetchone() != ('delete',)
                        or con.execute('SELECT * FROM v3_contract').fetchall()
                        != [(1, prepared[4], codec.digest(prepared[4]))]):
                    raise ValueError('v3 schema/contract/integrity differs')
                saved = con.execute('SELECT sequence,result_json FROM v3_matches ORDER BY sequence').fetchall()
                if [i for i, _ in saved] != list(range(1, len(saved) + 1)) or len(saved) > len(prepared[1].games):
                    raise ValueError('only contiguous v3 prefix accepted')
                results = tuple(decode_result(raw) for _, raw in saved)
                expected, heads = _audit_rows(prepared, self.request, results)
                for table, wanted in expected.items():
                    if sorted(con.execute(f'SELECT * FROM {table}').fetchall()) != wanted:
                        raise ValueError('v3 result/chain/derived rows differ: ' + table)
                # Holding the SHARED lock binds the trusted bytes to this audited snapshot.
                digest = annual._sha(self.db_path)
                if before != digest:
                    raise ValueError('v3 bytes changed during full audit')
        self._guard()
        dependencies.check(self.lab, manifest)
        if digest != annual._sha(self.db_path):
            raise ValueError('v3 bytes changed after audit')
        self._prepared, self._results, self._heads = prepared, results, heads
        self._manifest, self._digest, self._fast_count = manifest, digest, 0
        self._request, self._seed = self.request, self.scenario_seed
        self.state = 'COMPLETE' if len(results) == len(prepared[1].games) else 'TRUSTED'
        return len(results)

    def _guard(self):
        if getattr(self, 'closed', False):
            raise ValueError('fictional bracket store closed')
        root = guards._path(self.capability.root)
        if self.db_path != root / DATABASE:
            raise ValueError('fictional path differs from owned root')
        guards._safe(root)
        guards._location(root)
        if {p.name for p in root.iterdir()} != {DATABASE, LEASE}:
            raise ValueError('unknown sidecar/hot journal; automatic recovery forbidden')
        for path, identity in ((root, self.capability.root_identity), (self.db_path, self.capability.file_identity),
                               (root / LEASE, self.capability.lease_identity)):
            guards._safe(path, directory=path == root)
            if tuple(guards._identity(path)) != identity:
                raise ValueError('fictional file/root/lease authority replaced')
        if (root / LEASE).stat().st_size != 1:
            raise ValueError('fictional lease differs')
        with self.db_path.open('rb') as inp:
            header = inp.read(100)
        if len(header) != 100 or header[:16] != b'SQLite format 3\0' or header[18:20] != b'\x01\x01':
            raise ValueError('only DELETE journal fictional SQLite accepted')

        if (int.from_bytes(header[68:72], 'big') != APPLICATION_ID
                or int.from_bytes(header[60:64], 'big') != USER_VERSION):
            raise ValueError('v3 application_id/user_version required')
