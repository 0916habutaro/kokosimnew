"""Owned Stage116 trial. No official-year, product slot or outcomes adapter.

The request is rechecked, never a caller-supplied GateReport. Each match and its
advancement/index rows commit atomically in one separate SQLite database.
"""
from contextlib import closing
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from statistics import fmean
import sqlite3
import threading

from game_core.school_intake import SchoolAwarePlayerAbilityGenerator
from . import competition_evidence_gates as gates
from . import saved_practice_match as practice
from . import yamanashi_annual_rosters as annual
from . import yamanashi_demo_store as guards
from . import registered_full_a_lab_store as codec
from .fictional_tournament_oracle import progression
from .joint_team_registration_lab import RegisteredAbility, RegisteredTeamInput, LabTeamAbilitySummary, _identical, _sha
from .randomness import rng_for
from .registered_match_driver import _run
from .registered_full_a_contract import decode_result
from .registered_full_a_oracle import event_oracle

VERSION = 'stage43g116_saved_fictional_tournament_v1'
INPUT_VERSION = 'stage43g116_fictional_match_input_v1'
KIND, YEAR, SEED, ABILITY_SEED = 'fictional_tournament', 2027, 430116, 430103
DATABASE, LEASE = 'fictional_tournament.sqlite3', 'fictional_tournament.lease'
USAGE = 'saved2027_explicit20_position_assignment_returning_newcomer_joint_v1'
TABLES = ('fictional_contract', 'fictional_matches', 'fictional_advancement',
          'fictional_ranks', 'fictional_acceptance', 'fictional_players')
DDL = (
    'CREATE TABLE fictional_contract (singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL) STRICT',
    'CREATE TABLE fictional_matches (sequence INTEGER PRIMARY KEY CHECK(sequence BETWEEN 1 AND 2), '
    'match_id TEXT NOT NULL UNIQUE, year INTEGER NOT NULL CHECK(year=2027), '
    "record_kind TEXT NOT NULL CHECK(record_kind='fictional_tournament'), namespace TEXT NOT NULL, "
    'day TEXT NOT NULL, input_json TEXT NOT NULL, input_sha256 TEXT NOT NULL, '
    'result_json TEXT NOT NULL, result_sha256 TEXT NOT NULL) STRICT',
    'CREATE TABLE fictional_advancement (sequence INTEGER PRIMARY KEY, match_id TEXT NOT NULL, '
    'source TEXT NOT NULL, team_id TEXT NOT NULL) STRICT',
    'CREATE TABLE fictional_ranks (rank INTEGER PRIMARY KEY CHECK(rank BETWEEN 1 AND 3), '
    'team_id TEXT NOT NULL UNIQUE, wins INTEGER NOT NULL, losses INTEGER NOT NULL) STRICT',
    'CREATE TABLE fictional_acceptance (singleton INTEGER PRIMARY KEY CHECK(singleton=1), '
    'champion_team_id TEXT NOT NULL, checkpoint_sha256 TEXT NOT NULL) STRICT',
    'CREATE TABLE fictional_players (player_id TEXT NOT NULL, origin_school_id TEXT NOT NULL, '
    'entry_team_id TEXT NOT NULL, year INTEGER NOT NULL, record_kind TEXT NOT NULL, namespace TEXT NOT NULL, '
    'match_id TEXT NOT NULL REFERENCES fictional_matches(match_id), '
    'PRIMARY KEY(player_id,year,record_kind,namespace,match_id)) STRICT',
) + tuple(f'CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} '
          "BEGIN SELECT RAISE(ABORT, 'append-only fictional tournament'); END"
          for table in TABLES for action in ('UPDATE', 'DELETE'))


def decode_request(value):
    """Decode our canonical capability payload; dry_run still verifies its body."""
    d = dict(value)
    fields = (('entries', gates.EntrySet), ('joints', gates.JointComposition),
              ('qualification', gates.Qualification), ('districts', gates.DistrictRules),
              ('seeds', gates.SeedRules), ('draw', gates.DrawRules), ('schedule', gates.Schedule))
    def tuples(v):
        return tuple(tuples(x) for x in v) if isinstance(v, list) else v
    for name, cls in fields:
        item = {k: tuples(v) for k, v in d[name].items()}
        e = dict(item['evidence'])
        e['authority'] = gates.Authority(e['authority'])
        item['evidence'] = gates.Evidence(**e)
        if name == 'entries':
            item['teams'] = tuple(gates.EntryTeam(t['entry_team_id'], tuples(t['programs']),
                                                 tuples(t['player_ids'])) for t in item['teams'])
        elif name == 'qualification':
            item['decisions'] = tuple(gates.QualificationDecision(**x) for x in item['decisions'])
        d[name] = cls(**item)
    return gates.CompetitionRequest(**d)


@dataclass(frozen=True)
class GamePlan:
    sequence: int
    match_id: str
    day: str
    seed: int


@dataclass(frozen=True)
class TournamentPlan:
    version: str
    namespace: str
    scope: str
    scenario_seed: int
    slots: tuple
    games: tuple[GamePlan, ...]


@dataclass(frozen=True)
class FictionalInput:
    version: str
    record_kind: str
    year: int
    namespace: str
    competition_id: str
    match_id: str
    day: str
    sequence: int
    scenario_seed: int
    match_seed: int
    ability_seed: int
    contract_sha256: str
    previous_results_sha256: str
    team1: RegisteredTeamInput
    team2: RegisteredTeamInput

    def to_dict(self):
        return asdict(self)


def _team(entry, rosters, prior_appeared):
    people = {p.player_id: p for r in rosters for p in r.players}
    selected = tuple(people[pid] for pid in entry.player_ids)
    generator = SchoolAwarePlayerAbilityGenerator()
    tid = entry.entry_team_id
    players = tuple(RegisteredAbility(tid, p.player_id, p.school_id,
                    generator.generate(p, YEAR, ABILITY_SEED)) for p in selected)
    pitchers = sorted((p for p in players if p.snapshot.primary_position == 'P'),
                      key=lambda p: (-p.snapshot.control, p.player_id))
    if not pitchers:
        raise ValueError('registered pitcher required')
    positions = ('P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF')
    # Primary positions first. Missing field positions use an explicit scenario
    # assignment, preserving the saved primary position and school in profiles.
    options = [(pitchers[0],)]
    for pos in positions[1:]:
        primary = tuple(p for p in players if p.snapshot.primary_position == pos)
        fallback = tuple(p for p in players if p.snapshot.primary_position != 'P')
        options.append(primary or fallback)
    freshmen = {p.player_id for p in selected if p.entry_year == YEAR}
    schools = {sid for sid, _ in entry.programs}
    candidates = (nine for nine in product(*options)
                  if len({p.player_id for p in nine}) == 9
                  and {p.player_id for p in nine} & freshmen
                  and {p.player_id for p in nine} & prior_appeared
                  and {p.origin_school_id for p in nine} == schools)
    chosen = max(candidates, key=lambda nine: (sum(p.snapshot.contact for p in nine),
                 tuple(p.player_id for p in nine)), default=None)
    if chosen is None:
        raise ValueError('registered20 cannot form returning/newcomer/origin nine')
    starters = sorted(zip(positions, chosen), key=lambda pair: (-pair[1].snapshot.contact, pair[1].player_id))
    lineup = tuple((i, pos, p.player_id) for i, (pos, p) in enumerate(starters, 1))
    # A relief pitcher must enter the pitcher's batting slot, never another slot.
    staff = tuple(p.player_id for p in pitchers if p == pitchers[0] or p not in chosen)
    return RegisteredTeamInput(tid, _sha([p.to_dict() for p in selected]),
        'origin_school_intake_v1', USAGE, players, lineup, staff,
        LabTeamAbilitySummary(tid, USAGE, fmean(p.snapshot.contact for p in players),
            fmean(p.snapshot.power for p in players), fmean(p.snapshot.fielding for p in players),
            fmean(p.snapshot.control for p in pitchers)))


def _prepare(lab, request, seed, opt_in):
    if opt_in is not True or type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError('explicit fictional opt-in and independent scenario seed required')
    report = gates.dry_run(lab, request, fictional_opt_in=opt_in)
    if not report.fictional_scenario_ready or report.official_year_verified or report.product_season_start_authorized:
        raise ValueError('all individual fictional evidence gates required')
    # Stage115 permits arbitrary source *labels*, but execution accepts only
    # clearly self-created declarations. A label cannot become official authority.
    for name in ('entries', 'joints', 'qualification', 'districts', 'seeds', 'draw', 'schedule'):
        evidence = getattr(request, name).evidence
        source = evidence.source.casefold()
        if (not source.startswith('self-created declaration/')
                or any(s in source for s in ('official', 'verified', 'http:', 'https:', '公式', '認証'))):
            raise ValueError('execution requires an unambiguous self-created source label')
    groups = tuple(tuple(sid for sid, _ in t.programs) for t in request.entries.teams)
    if (groups != (('SCH000196',), ('SCH000197',), ('SCH000202', 'SCH000220'))
            or (request.draw.participant_slots, request.draw.bracket_size, request.draw.bye_count) != (3, 4, 1)):
        raise ValueError('only the explicit Stage115 single2/joint1 fictional fixture is supported')
    authority = practice.saved_authority(lab)
    if codec.digest(authority[3]) != dict(report.evidence_digests)['prior_sealed_year']:
        raise ValueError('source changed between gate and SQL authority')
    people = {p.player_id: p for r in authority[1] for p in r.players}
    for entry in request.entries.teams:
        counts = [sum(people[pid].school_id == sid for pid in entry.player_ids) for sid, _ in entry.programs]
        if counts != [20 // len(entry.programs)] * len(entry.programs):
            raise ValueError('explicit separate20 or joint10+10 registration required')
    appeared = {r.player_id for g in authority[0].results for r in g.batter_stats if r.plate_appearances}
    teams = tuple(_team(t, authority[1], appeared) for t in request.entries.teams)
    ids = [t.team_id for t in teams]
    rng = rng_for(seed, 'stage116:draw:' + request.namespace)
    rng.shuffle(ids)
    if request.seeds.seeds:
        seeded = request.seeds.seeds[0][0]
        ids.remove(seeded)
        ids.insert(0, seeded)
    scope = 'LAB116:2027:FICTIONAL:' + _sha((request.namespace, seed))[:16]
    games = tuple(GamePlan(i, scope + f':match{i}', day,
        rng_for(seed, f'stage116:match:{i}').randrange(2**63))
        for i, day in enumerate(request.schedule.round_dates, 1))
    plan = TournamentPlan(VERSION, request.namespace, scope, seed, (ids[0], None, *ids[1:]), games)
    progression(plan, request, ())
    contract = codec.canonical(dict(version=VERSION, record_kind=KIND, year=YEAR,
        request=gates._payload(request), scenario_seed=seed, gates=report.to_dict(),
        source_receipt=authority[3], plan=asdict(plan), teams=[asdict(t) for t in teams]))
    return authority, plan, teams, contract


def _input(plan, teams, contract, results):
    if len(results) >= 2:
        raise ValueError('fictional tournament already complete')
    game = plan.games[len(results)]
    pair = plan.slots[2:] if not results else (results[0].winner_id, plan.slots[0])
    by_id = {t.team_id: t for t in teams}
    return FictionalInput(INPUT_VERSION, KIND, YEAR, plan.namespace, plan.scope,
        game.match_id, game.day, game.sequence, plan.scenario_seed, game.seed, ABILITY_SEED,
        codec.digest(contract), _sha([r.to_dict() for r in results]), *(by_id[tid] for tid in pair))


def _validate(result, match):
    report = event_oracle(result, match)
    if not _identical(result, _run(match, match.match_seed)):
        raise ValueError('fictional result differs from bound seeded execution')
    return report


def _rows(plan, teams, contract, request, results):
    ledger, ranks = progression(plan, request, results)
    rows = {table: [] for table in TABLES if table != 'fictional_contract'}
    for i, result in enumerate(results):
        match = _input(plan, teams, contract, results[:i])
        _validate(result, match)
        raw = result.to_json()
        rows['fictional_matches'].append((i + 1, result.match_id, YEAR, KIND, plan.namespace,
            match.day, codec.canonical(match.to_dict()), _sha(match.to_dict()), raw, codec.digest(raw)))
        rows['fictional_players'].extend(sorted({(e.batter_id, e.batter_origin_school_id, e.offense_team_id,
            YEAR, KIND, plan.namespace, result.match_id) for e in result.events} |
            {(e.pitcher_id, e.pitcher_origin_school_id, e.defense_team_id,
            YEAR, KIND, plan.namespace, result.match_id) for e in result.events}))
    rows['fictional_advancement'] = ledger
    rows['fictional_ranks'] = ranks
    if len(results) == 2:
        rows['fictional_acceptance'] = [(1, results[1].winner_id, _sha([r.to_dict() for r in results]))]
    return {key: sorted(value) for key, value in rows.items()}


@dataclass(frozen=True)
class TournamentCapability:
    root: str
    root_identity: tuple
    file_identity: tuple
    lease_identity: tuple
    contract_json: str


class FictionalTournamentStore:
    """Only a TemporaryDirectory owner can create a trial; no path adoption."""
    close = annual.AnnualRosterLab.close

    def __init__(self, lab, owner, request, *, scenario_seed=SEED, fictional_opt_in=False):
        prepared = _prepare(lab, request, scenario_seed, fictional_opt_in)
        root = annual._owner(owner)
        for source in (Path(lab.capability.root), Path(lab.source.capability.root)):
            if root == source or root.is_relative_to(source) or source.is_relative_to(root):
                raise ValueError('separate fictional tournament root required')
        self.lab, self.owner, self.request, self.scenario_seed = lab, owner, request, scenario_seed
        self.db_path = root / DATABASE
        self.db_path.touch(exist_ok=False)
        (root / LEASE).write_bytes(b'0')
        self.capability = TournamentCapability(str(root), tuple(guards._identity(root)),
            tuple(guards._identity(self.db_path)), tuple(guards._identity(root / LEASE)), prepared[3])
        self._setup_handles()
        try:
            with closing(sqlite3.connect(self.db_path)) as con, con:
                for sql in DDL:
                    con.execute(sql)
                con.execute('INSERT INTO fictional_contract VALUES (1,?)', (prepared[3],))
                con.executemany('INSERT INTO fictional_advancement VALUES (?,?,?,?)',
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
        if type(capability) is not TournamentCapability or fictional_opt_in is not True:
            raise ValueError('owned fictional capability and explicit opt-in required')
        obj = cls.__new__(cls)
        obj.capability, obj.lab, obj.owner = capability, lab, None
        obj.db_path = Path(capability.root) / DATABASE
        obj._guard()
        data = codec.strict_json(capability.contract_json)
        obj.request, obj.scenario_seed = decode_request(data['request']), data['scenario_seed']
        obj._setup_handles()
        try:
            obj.snapshot()
        except BaseException:
            obj.close()
            raise
        return obj

    def _guard(self):
        if getattr(self, 'closed', False):
            raise ValueError('fictional store closed')
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
        authority, plan, teams, contract = prepared
        if contract != self.capability.contract_json:
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
                    or con.execute('SELECT * FROM fictional_contract').fetchall() != [(1, contract)]):
                raise ValueError('fictional schema/contract differs')
            matches = con.execute('SELECT sequence,result_json FROM fictional_matches ORDER BY sequence').fetchall()
            if [i for i, _ in matches] != list(range(1, len(matches) + 1)) or len(matches) > 2:
                raise ValueError('only contiguous zero/one/two game prefix accepted')
            results = tuple(decode_result(raw) for _, raw in matches)
            expected = _rows(plan, teams, contract, self.request, results)
            for table, wanted in expected.items():
                if sorted(con.execute(f'SELECT * FROM {table}').fetchall()) != wanted:
                    raise ValueError('fictional saved rows/index/advancement/acceptance differ')
        self._guard()
        if before != annual._sha(self.db_path):
            raise ValueError('fictional SQLite changed during RO audit')
        return results

    def snapshot(self, *, practice_store=None):
        with self._mutex:
            prepared = self._prepare()
            results = self._audit(prepared)
            practice_view = None
            if practice_store is not None:
                if type(practice_store) is not practice.PracticeStore or practice_store.lab is not self.lab:
                    raise ValueError('same owned saved-year practice source required')
                practice_view = practice_store.snapshot()
            return FictionalTournamentView(prepared, self.request, results, practice_view)

    def next_input(self):
        with self._mutex:
            prepared = self._prepare()
            results = self._audit(prepared)
            return _input(prepared[1], prepared[2], prepared[3], results)

    def append(self, match, result, *, fault=None):
        with self._mutex:
            prepared = self._prepare()  # rerun actual request at every start
            results = self._audit(prepared)
            if type(match) is not FictionalInput or type(match.sequence) is not int or match.sequence not in (1, 2):
                raise ValueError('typed fictional match required')
            index = match.sequence - 1
            if index > len(results):
                raise ValueError('previous result must be committed before next round')
            expected = _input(prepared[1], prepared[2], prepared[3], results[:index])
            if not _identical(match, expected):
                raise ValueError('exact bound fictional input required')
            _validate(result, match)
            if index < len(results):
                if not _identical(results[index], result):
                    raise ValueError('conflicting fictional result')
                return False
            old = _rows(prepared[1], prepared[2], prepared[3], self.request, results)
            new = _rows(prepared[1], prepared[2], prepared[3], self.request, results + (result,))
            self._guard()
            with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=rw', uri=True, timeout=.1)) as con, con:
                con.execute('PRAGMA foreign_keys=ON')
                con.execute('PRAGMA synchronous=FULL')
                con.execute('BEGIN IMMEDIATE')
                for table, rows in old.items():
                    if sorted(con.execute(f'SELECT * FROM {table}').fetchall()) != rows:
                        raise ValueError('concurrent fictional append')
                for table, rows in new.items():
                    additions = [r for r in rows if r not in old[table]]
                    if additions:
                        placeholders = ','.join('?' for _ in additions[0])
                        con.executemany(f'INSERT INTO {table} VALUES ({placeholders})', additions)
                if fault:
                    fault('before_commit')
            if fault:
                fault('after_commit')
            # Cross-store verification is deliberately not multi-DB atomicity.
            self.snapshot()
            return True

    def play_next(self, *, fault=None):
        match = self.next_input()
        result = _run(match, match.match_seed)
        self.append(match, result, fault=fault)
        return result


class FictionalTournamentView:
    """Detached verified history. Joint wins belong exclusively to entry teams."""
    def __init__(self, prepared, request, results, practice_view):
        authority, self.plan, self.teams, _ = prepared
        self._source, self._rosters, self._lineage, _ = authority
        self.request, self.results = request, results
        self.ledger, self.ranks = progression(self.plan, request, results)
        self.complete = len(results) == 2
        self.fictional_scenario_champion = results[-1].winner_id if self.complete else None
        self.official_year_verified = self.product_season_start_authorized = False
        self._streams = [(2026, KIND, self._source.results[0].competition_id, self._source.results)]
        if practice_view:
            self._streams.append((2027, practice.KIND, practice.SCOPE, practice_view.results))
        self._streams.append((2027, KIND, self.plan.namespace, results))
        self._people = {p.player_id: p for r in (*self._source.rosters, *self._rosters) for p in r.players}

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
        history = []
        for year, kind, namespace, games in self._streams:
            rosters = self._source.rosters if year == 2026 else self._rosters
            history.append(dict(year=year, record_kind=kind, namespace=namespace,
                roster=next(r.to_dict() for r in rosters if r.school_id == school_id),
                matches=[self._record(g, kind, namespace) for g in games if tids.intersection((g.team1_id, g.team2_id))]))
        return dict(school_id=school_id, history=history, fictional_team_records=records,
            standalone_wins=sum(r['wins'] for r in records if not r['joint']),
            standalone_losses=sum(r['losses'] for r in records if not r['joint']),
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
                                            batting=batting, pitching=pitching))
            history.append(dict(year=year, record_kind=kind, namespace=namespace,
                state='active' if current else ('not_yet_enrolled' if year < person.entry_year else 'graduated'),
                profile=current.to_dict() if current else None, appearances=appearances))
        return dict(player_id=player_id, origin_school_id=person.school_id, program_id=person.program_id,
            entry_year=person.entry_year, transition=next(state for pid, _, state, _, _ in self._lineage if pid == player_id),
            history=history, product_season_start_authorized=False)
