"""Stage119-C independent v3 trial: guarded SQLite, explicit trust and hash chain.

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


@dataclass(frozen=True)
class BracketCapability:
    root: str
    root_identity: tuple
    file_identity: tuple
    lease_identity: tuple
    contract_json: str


class FictionalBracketStore:
    """Separate v3 capability; never adopts or migrates a legacy save."""
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
