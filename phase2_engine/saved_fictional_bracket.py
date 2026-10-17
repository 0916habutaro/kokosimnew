"""Owned Stage117 trial: generic fictional bracket, one SQLite transaction per game.

Stage116 v1 (`saved_fictional_tournament`) is reused read-only and never
modified. No official-year, product slot, archive or outcomes adapter exists.
"""
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from pathlib import Path
import sqlite3
import threading

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

VERSION = 'stage43g117_fictional_bracket_v2'
INPUT_VERSION = 'stage43g117_fictional_bracket_match_input_v2'
KIND, YEAR, SEED, ABILITY_SEED = 'fictional_bracket_tournament', 2027, 430117, v1.ABILITY_SEED
DATABASE, LEASE = 'fictional_bracket_v2.sqlite3', 'fictional_bracket_v2.lease'
TABLES = ('bracket_contract', 'bracket_matches', 'bracket_advancement', 'bracket_checkpoints',
          'bracket_players', 'bracket_ranks', 'bracket_acceptance')
DDL = (
    'CREATE TABLE bracket_contract (singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL) STRICT',
    'CREATE TABLE bracket_matches (sequence INTEGER PRIMARY KEY CHECK(sequence BETWEEN 1 AND 31), '
    'match_id TEXT NOT NULL UNIQUE, round_no INTEGER NOT NULL CHECK(round_no BETWEEN 1 AND 5), '
    'year INTEGER NOT NULL CHECK(year=2027), '
    "record_kind TEXT NOT NULL CHECK(record_kind='fictional_bracket_tournament'), namespace TEXT NOT NULL, "
    'day TEXT NOT NULL, input_json TEXT NOT NULL, input_sha256 TEXT NOT NULL, '
    'result_json TEXT NOT NULL, result_sha256 TEXT NOT NULL) STRICT',
    'CREATE TABLE bracket_advancement (step INTEGER NOT NULL, round_no INTEGER NOT NULL, '
    "source TEXT NOT NULL CHECK(source IN ('BYE','WINNER')), team_id TEXT NOT NULL, "
    'PRIMARY KEY(step, team_id)) STRICT',
    'CREATE TABLE bracket_checkpoints (sequence INTEGER PRIMARY KEY REFERENCES bracket_matches(sequence), '
    'source_receipt_sha256 TEXT NOT NULL, contract_sha256 TEXT NOT NULL, '
    'previous_results_sha256 TEXT NOT NULL, prefix_results_sha256 TEXT NOT NULL) STRICT',
    'CREATE TABLE bracket_players (player_id TEXT NOT NULL, origin_school_id TEXT NOT NULL, '
    'entry_team_id TEXT NOT NULL, year INTEGER NOT NULL, record_kind TEXT NOT NULL, namespace TEXT NOT NULL, '
    'match_id TEXT NOT NULL REFERENCES bracket_matches(match_id), '
    'PRIMARY KEY(player_id,year,record_kind,namespace,match_id)) STRICT',
    'CREATE TABLE bracket_ranks (team_id TEXT PRIMARY KEY, rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 32), '
    'wins INTEGER NOT NULL, losses INTEGER NOT NULL) STRICT',
    'CREATE TABLE bracket_acceptance (singleton INTEGER PRIMARY KEY CHECK(singleton=1), '
    'champion_team_id TEXT NOT NULL, games INTEGER NOT NULL, checkpoint_sha256 TEXT NOT NULL) STRICT',
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
    previous_results_sha256: str
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
    rng = rng_for(seed, 'stage117:draw:' + request.namespace)
    slots = plan_slots([t.team_id for t in teams], request.seeds.seeds, rng, request.draw.bracket_size)
    bracket = Bracket(slots)
    scope = 'LAB117:2027:FICTIONAL:' + _sha((request.namespace, seed))[:16]
    games = tuple(GamePlan(g.sequence, g.round_no, g.position, f'{scope}:r{g.round_no}:g{g.position + 1}',
        request.schedule.round_dates[g.round_no - 1], rng_for(seed, f'stage117:match:{g.sequence}').randrange(2**63))
        for g in bracket.games)
    plan = BracketPlan(VERSION, request.namespace, scope, seed, slots, games)
    progression(plan, request, ())
    contract = codec.canonical(dict(version=VERSION, record_kind=KIND, year=YEAR,
        request=gates._payload(request), scenario_seed=seed, gates=report.to_dict(),
        source_receipt=authority[3], plan=asdict(plan), teams=[asdict(t) for t in teams]))
    return authority, plan, bracket, teams, contract


def _input(prepared, results):
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
        _sha([r.to_dict() for r in results]), *(by_id[tid] for tid in pair))


_validate = v1._validate


def _rows(prepared, request, results):
    authority, plan, bracket, _, contract = prepared
    ledger, ranks = progression(plan, request, results)
    # Two independent derivations of participants and standings must agree.
    if [(r, t) for r, t, _, _ in ranks] != bracket.ranks(results):
        raise ValueError('bracket graph and progression oracle disagree')
    rows = {table: [] for table in TABLES if table != 'bracket_contract'}
    receipt = codec.digest(authority[3])
    for i, result in enumerate(results):
        match = _input(prepared, results[:i])
        if (result.team1_id, result.team2_id) != (match.team1.team_id, match.team2.team_id):
            raise ValueError('bracket graph and progression oracle disagree')
        _validate(result, match)
        raw = result.to_json()
        rows['bracket_matches'].append((i + 1, result.match_id, match.round_no, YEAR, KIND, plan.namespace,
            match.day, codec.canonical(match.to_dict()), _sha(match.to_dict()), raw, codec.digest(raw)))
        rows['bracket_checkpoints'].append((i + 1, receipt, codec.digest(contract), match.previous_results_sha256,
            _sha([r.to_dict() for r in results[:i + 1]])))
        rows['bracket_players'].extend(sorted({(e.batter_id, e.batter_origin_school_id, e.offense_team_id,
            YEAR, KIND, plan.namespace, result.match_id) for e in result.events} |
            {(e.pitcher_id, e.pitcher_origin_school_id, e.defense_team_id,
            YEAR, KIND, plan.namespace, result.match_id) for e in result.events}))
    rows['bracket_advancement'] = ledger
    rows['bracket_ranks'] = [(tid, rank, w, l) for rank, tid, w, l in ranks]
    if ranks:
        rows['bracket_acceptance'] = [(1, ranks[0][1], len(results), rows['bracket_checkpoints'][-1][4])]
    return {key: sorted(value) for key, value in rows.items()}


@dataclass(frozen=True)
class BracketCapability:
    root: str
    root_identity: tuple
    file_identity: tuple
    lease_identity: tuple
    contract_json: str


class FictionalBracketStore:
    """Only a TemporaryDirectory owner can create a trial; no path adoption."""
    close = annual.AnnualRosterLab.close

    def __init__(self, lab, owner, request, *, scenario_seed=SEED, fictional_opt_in=False):
        prepared = _prepare(lab, request, scenario_seed, fictional_opt_in)
        root = annual._owner(owner)
        for source in (Path(lab.capability.root), Path(lab.source.capability.root)):
            if root == source or root.is_relative_to(source) or source.is_relative_to(root):
                raise ValueError('separate fictional bracket root required')
        self.lab, self.owner, self.request, self.scenario_seed = lab, owner, request, scenario_seed
        self.db_path = root / DATABASE
        self.db_path.touch(exist_ok=False)
        (root / LEASE).write_bytes(b'0')
        self.capability = BracketCapability(str(root), tuple(guards._identity(root)),
            tuple(guards._identity(self.db_path)), tuple(guards._identity(root / LEASE)), prepared[4])
        self._setup_handles()
        try:
            with closing(sqlite3.connect(self.db_path)) as con, con:
                for sql in DDL:
                    con.execute(sql)
                con.execute('INSERT INTO bracket_contract VALUES (1,?)', (prepared[4],))
                con.executemany('INSERT INTO bracket_advancement VALUES (?,?,?,?)',
                                progression(prepared[1], request, ())[0])
            self._audit(prepared)
        except BaseException:
            self.close()
            raise

    def _setup_handles(self):
        self.closed, self._mutex, self._lease, self._pins = False, threading.RLock(), None, None
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
            raise ValueError('owned fictional bracket capability and explicit opt-in required')
        obj = cls.__new__(cls)
        obj.capability, obj.lab, obj.owner = capability, lab, None
        obj.db_path = Path(capability.root) / DATABASE
        obj._guard()
        data = codec.strict_json(capability.contract_json)
        if data.get('version') != VERSION:
            raise ValueError('fictional bracket contract version differs')
        obj.request, obj.scenario_seed = v1.decode_request(data['request']), data['scenario_seed']
        obj._setup_handles()
        try:
            obj.snapshot()
        except BaseException:
            obj.close()
            raise
        return obj

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

    def _prepare(self):
        self._guard()  # before any SQLite call, including source validation
        return _prepare(self.lab, self.request, self.scenario_seed, True)

    def _audit(self, prepared):
        self._guard()
        if prepared[4] != self.capability.contract_json:
            raise ValueError('fictional source/request/seed/contract differs')
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
                    or con.execute('SELECT * FROM bracket_contract').fetchall() != [(1, prepared[4])]):
                raise ValueError('fictional bracket schema/contract differs')
            matches = con.execute('SELECT sequence,result_json FROM bracket_matches ORDER BY sequence').fetchall()
            if [i for i, _ in matches] != list(range(1, len(matches) + 1)) or len(matches) > len(prepared[1].games):
                raise ValueError('only a contiguous saved game prefix accepted')
            results = tuple(decode_result(raw) for _, raw in matches)
            expected = _rows(prepared, self.request, results)
            for table, wanted in expected.items():
                if sorted(con.execute(f'SELECT * FROM {table}').fetchall()) != wanted:
                    raise ValueError('fictional saved rows/index/advancement/checkpoint/acceptance differ')
        self._guard()
        if before != annual._sha(self.db_path):
            raise ValueError('fictional SQLite changed during RO audit')
        return results

    def snapshot(self, *, practice_store=None, v1_store=None):
        with self._mutex:
            prepared = self._prepare()
            results = self._audit(prepared)
            practice_view = v1_view = None
            if practice_store is not None:
                if type(practice_store) is not practice.PracticeStore or practice_store.lab is not self.lab:
                    raise ValueError('same owned saved-year practice source required')
                practice_view = practice_store.snapshot()
            if v1_store is not None:
                if type(v1_store) is not v1.FictionalTournamentStore or v1_store.lab is not self.lab:
                    raise ValueError('same owned saved-year Stage116 v1 source required')
                v1_view = v1_store.snapshot()
                if v1_view.plan.namespace == self.request.namespace:
                    raise ValueError('separate scenario namespace required')
            return FictionalBracketView(prepared, self.request, results, practice_view, v1_view)

    def next_input(self):
        with self._mutex:
            prepared = self._prepare()
            return _input(prepared, self._audit(prepared))

    def append(self, match, result, *, fault=None):
        with self._mutex:
            prepared = self._prepare()  # rerun the actual request at every start
            return self._append(prepared, self._audit(prepared), match, result, fault)

    def _append(self, prepared, results, match, result, fault):
        games = len(prepared[1].games)
        if (type(match) is not BracketMatchInput or type(match.sequence) is not int
                or not 1 <= match.sequence <= games):
            raise ValueError('typed fictional bracket match required')
        index = match.sequence - 1
        if index > len(results):
            raise ValueError('previous results must be committed in order; no skipped game')
        expected = _input(prepared, results[:index])
        if not _identical(match, expected):
            raise ValueError('exact bound fictional bracket input required')
        _validate(result, match)
        if index < len(results):
            if not _identical(results[index], result):
                raise ValueError('conflicting fictional bracket result')
            return False
        old = _rows(prepared, self.request, results)
        new = _rows(prepared, self.request, results + (result,))
        self._guard()
        with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=rw', uri=True, timeout=.1)) as con, con:
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('PRAGMA synchronous=FULL')
            con.execute('BEGIN IMMEDIATE')
            for table, rows in old.items():
                if sorted(con.execute(f'SELECT * FROM {table}').fetchall()) != rows:
                    raise ValueError('concurrent fictional bracket append')
            for table, rows in new.items():
                additions = [r for r in rows if r not in old[table]]
                if additions:
                    placeholders = ','.join('?' for _ in additions[0])
                    con.executemany(f'INSERT INTO {table} VALUES ({placeholders})', additions)
            if fault:
                fault('before_commit')
        if fault:
            fault('after_commit')
        # Cross-store verification after commit; never multi-DB atomicity.
        self.snapshot()
        return True

    def play_next(self, *, fault=None):
        """One source recheck before, one full re-audit after; nothing skipped."""
        with self._mutex:
            prepared = self._prepare()
            results = self._audit(prepared)
            match = _input(prepared, results)
            result = _run(match, match.match_seed)
            self._append(prepared, results, match, result, fault)
            return result


def _totals(rows, cls):
    names = [f.name for f in fields(cls) if f.type in (int, 'int') and f.name != 'year']
    return {name: sum(getattr(r, name) for r in rows) for name in names}


class FictionalBracketView:
    """Detached verified history. Joint wins belong exclusively to entry teams."""
    def __init__(self, prepared, request, results, practice_view, v1_view):
        authority, self.plan, self.bracket, self.teams, _ = prepared
        self._source, self._rosters, self._lineage, _ = authority
        self.request, self.results, self.v1 = request, results, v1_view
        self.ledger, self.ranks = progression(self.plan, request, results)
        self.complete = len(results) == len(self.plan.games)
        self.fictional_scenario_champion = self.ranks[0][1] if self.complete else None
        self.official_year_verified = self.product_season_start_authorized = False
        self._streams = [(2026, v1.KIND, self._source.results[0].competition_id, self._source.results)]
        if practice_view:
            self._streams.append((2027, practice.KIND, practice.SCOPE, practice_view.results))
        if v1_view:
            self._streams.append((2027, v1.KIND, v1_view.plan.namespace, v1_view.results))
        self._streams.append((2027, KIND, self.plan.namespace, results))
        self._people = {p.player_id: p for r in (*self._source.rosters, *self._rosters) for p in r.players}

    def next_pair(self):
        if self.complete:
            return None
        return self.bracket.pair(len(self.results) + 1, self.results)

    @staticmethod
    def _record(game, kind, namespace):
        return dict(year=game.year, record_kind=kind, namespace=namespace,
                    match_id=game.match_id, result=game.to_dict())

    def team(self, entry_team_id):
        entry = next((t for t in self.request.entries.teams if t.entry_team_id == entry_team_id), None)
        if entry is None:
            raise ValueError('unknown fictional entry team')
        games = [g for g in self.results if entry_team_id in (g.team1_id, g.team2_id)]
        return dict(entry_team_id=entry_team_id, year=YEAR, record_kind=KIND, namespace=self.plan.namespace,
            programs=entry.programs, joint=len(entry.programs) > 1,
            bye=entry_team_id in self.bracket.byes,
            wins=sum(g.winner_id == entry_team_id for g in games), losses=sum(g.loser_id == entry_team_id for g in games),
            matches=[self._record(g, KIND, self.plan.namespace) for g in games],
            scenario_rank=next((r[0] for r in self.ranks if r[1] == entry_team_id), None),
            official_2027_ranking=None)

    def school(self, school_id):
        if school_id not in {r.school_id for r in self._rosters}:
            raise ValueError('unknown saved school')
        tids = {t.team_id for t in self._source.registration.teams if school_id in t.school_ids}
        tids.add(f'LAB114:2027:SCHOOL:{school_id}')
        records = [self.team(t.entry_team_id) for t in self.request.entries.teams
                   if school_id in {sid for sid, _ in t.programs}]
        tids.update(r['entry_team_id'] for r in records)
        v1_records = []
        if self.v1:
            v1_records = [self.v1.team(t.entry_team_id) for t in self.v1.request.entries.teams
                          if school_id in {sid for sid, _ in t.programs}]
            tids.update(r['entry_team_id'] for r in v1_records)
        history = []
        for year, kind, namespace, games in self._streams:
            rosters = self._source.rosters if year == 2026 else self._rosters
            history.append(dict(year=year, record_kind=kind, namespace=namespace,
                roster=next(r.to_dict() for r in rosters if r.school_id == school_id),
                matches=[self._record(g, kind, namespace) for g in games if tids.intersection((g.team1_id, g.team2_id))]))
        return dict(school_id=school_id, history=history, fictional_team_records=records,
            v1_fictional_team_records=v1_records,
            standalone_wins=sum(r['wins'] for r in records if not r['joint']),
            standalone_losses=sum(r['losses'] for r in records if not r['joint']),
            v1_standalone_wins=sum(r['wins'] for r in v1_records if not r['joint']),
            v1_standalone_losses=sum(r['losses'] for r in v1_records if not r['joint']),
            product_season_start_authorized=False, official_2027_outcomes=None, official_2027_schedule=None,
            official_2027_entry=None, official_2027_ranking=None,
            official_2027_qualification=None, official_2027_joint_continuation=None)

    def player(self, player_id):
        person = self._people.get(player_id)
        if person is None:
            raise ValueError('unknown permanent player ID')
        history = []
        for year, kind, namespace, games in self._streams:
            rosters = self._source.rosters if year == 2026 else self._rosters
            current = next((p for r in rosters for p in r.players if p.player_id == player_id), None)
            appearances = []
            for game in games:
                batting = [asdict(r) for r in game.batter_stats if r.player_id == player_id and r.plate_appearances]
                pitching = [asdict(r) for r in game.pitcher_stats if r.player_id == player_id and r.batters_faced]
                if batting or pitching:
                    appearances.append(dict(year=year, record_kind=kind, namespace=namespace, match_id=game.match_id,
                                            entry_team_id=(batting or pitching)[0]['team_id'],
                                            batting=batting, pitching=pitching))
            history.append(dict(year=year, record_kind=kind, namespace=namespace,
                state='active' if current else ('not_yet_enrolled' if year < person.entry_year else 'graduated'),
                profile=current.to_dict() if current else None, appearances=appearances))
        batting = [r for g in self.results for r in g.batter_stats if r.player_id == player_id]
        pitching = [r for g in self.results for r in g.pitcher_stats if r.player_id == player_id]
        return dict(player_id=player_id, origin_school_id=person.school_id, program_id=person.program_id,
            entry_year=person.entry_year, transition=next(state for pid, _, state, _, _ in self._lineage if pid == player_id),
            history=history, scenario_namespace=self.plan.namespace,
            scenario_batting_totals=_totals(batting, RegisteredBatterStatsV1),
            scenario_pitching_totals=_totals(pitching, RegisteredPitcherStatsV1),
            product_season_start_authorized=False)
