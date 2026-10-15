"""Explicit fixed Stage108 8/32-team lab; Stage104-107 APIs remain unchanged."""
from dataclasses import asdict, dataclass
import random

from .yamanashi_tournament_registration import (
    YEAR, COMPETITION, ABILITY_SEED, PREFIX, validate_registration,
)
from .joint_team_registration_lab import RegisteredTeamInput, _team_input, _sha, _identical
from .registered_match_driver import _run
from .registered_full_a_oracle import event_oracle
from .yamanashi_tournament_oracle import progression_oracle

VERSION = 'stage43g108_annual_match_input_v1'
PLAN_VERSION = 'stage43g108_annual_plan_v1'
BRACKET_SEED = 430108
DAYS = ('2026-07-05','2026-07-09','2026-07-13','2026-07-18','2026-07-22')


@dataclass(frozen=True)
class PlannedGame:
    sequence: int
    match_id: str
    round_no: int
    slot: int
    day: str
    seed: int
    team1_source: str
    team2_source: str


@dataclass(frozen=True)
class AnnualTournamentPlan:
    version: str
    year: int
    competition_id: str
    registration_sha256: str
    bracket_seed: int
    gate: str
    entries: tuple[str, ...]
    games: tuple[PlannedGame, ...]

    def to_dict(self): return asdict(self)

    @property
    def fingerprint(self): return _sha(self.to_dict())


def _plan(reg, gate):
    if type(gate) is not str or gate not in ('B','C'):
        raise ValueError('reviewed Gate B/C only')
    entries = [t.team_id for t in reg.teams]
    if gate == 'B':
        entries = entries[:8]  # includes joint; remaining registration stays intact
    random.Random(BRACKET_SEED).shuffle(entries)
    sources = tuple(entries)
    games = []
    round_no = 1
    while len(sources) > 1:
        next_sources = []
        for slot in range(1,len(sources)//2+1):
            sequence = len(games)+1
            mid = PREFIX + f'{gate}:r{round_no}:m{slot:02d}'
            games.append(PlannedGame(sequence,mid,round_no,slot,DAYS[round_no-1],
                108000 + (100 if gate == 'C' else 0) + sequence,
                *sources[2*slot-2:2*slot]))
            next_sources.append('winner:'+mid)
        sources = tuple(next_sources); round_no += 1
    return AnnualTournamentPlan(PLAN_VERSION,YEAR,COMPETITION,_sha(reg.to_dict()),
                               BRACKET_SEED,gate,tuple(entries),tuple(games))


def fixed_plan(reg, repo, rosters, *, gate='C'):
    validate_registration(reg,repo,rosters)
    return _plan(reg,gate)


def checkpoint(results):
    return _sha(tuple((r.match_id,_sha(r.to_dict())) for r in results))


@dataclass(frozen=True)
class AnnualMatchInput:
    version: str
    year: int
    competition_id: str
    match_id: str
    match_seed: int
    ability_seed: int
    registration_sha256: str
    opt_in: bool
    plan_sha256: str
    prior_results_sha256: str
    day: str
    team1: RegisteredTeamInput
    team2: RegisteredTeamInput

    def to_dict(self): return asdict(self)


def _input(plan, reg, previous, *, teams=None, prior_sha=None):
    game = plan.games[len(previous)]
    winners = {r.match_id:r.winner_id for r in previous}
    def resolve(source):
        if source.startswith('winner:'):
            if source[7:] not in winners:
                raise ValueError('source winner not calculated')
            return winners[source[7:]]
        return source
    if teams is None:
        pair = (resolve(game.team1_source),resolve(game.team2_source))
        teams = {t.team_id:_team_input(t) for t in reg.teams if t.team_id in pair}
    return AnnualMatchInput(VERSION,YEAR,COMPETITION,game.match_id,game.seed,ABILITY_SEED,
        plan.registration_sha256,True,plan.fingerprint,
        checkpoint(previous) if prior_sha is None else prior_sha,game.day,
        teams[resolve(game.team1_source)],teams[resolve(game.team2_source)])


def _inputs(plan, reg, results):
    # Invocation-local reuse only. Every persisted result is still event/seed
    # replayed on every read. These hashes equal checkpoint(results[:i]).
    teams = {t.team_id:_team_input(t) for t in reg.teams if t.team_id in plan.entries}
    fingerprints = tuple((r.match_id,_sha(r.to_dict())) for r in results)
    return tuple(_input(plan,reg,results[:i],teams=teams,prior_sha=_sha(fingerprints[:i]))
                 for i in range(len(results)))


def verify_prefix(reg, repo, rosters, results, *, plan=None, gate='C'):
    if type(results) is not tuple:
        raise ValueError('immutable prefix required')
    expected = fixed_plan(reg,repo,rosters,gate=gate)
    if plan is not None and not _identical(plan,expected):
        raise ValueError('unknown plan/seed/source/date/entries')
    # Independent oracle checks complete prior rounds before factory resolution.
    ledger,ranks = progression_oracle(expected,reg,results)
    for result,match in zip(results,_inputs(expected,reg,results)):
        event_oracle(result,match)
        if not _identical(result,_run(match,match.match_seed)):
            raise ValueError('Stage108 seeded full-result replay differs')
    return expected,ledger,ranks


def next_match_input(reg, repo, rosters, results=(), *, opt_in=False, plan=None, gate='C'):
    if opt_in is not True:
        raise ValueError('explicit Stage108 opt-in required')
    checked,_,_ = verify_prefix(reg,repo,rosters,results,plan=plan,gate=gate)
    if len(results) == len(checked.games):
        raise ValueError('tournament complete')
    return _input(checked,reg,results)


def validate_tournament_input(match, reg, repo, rosters, results=(), *, plan=None, gate='C'):
    if not _identical(match,next_match_input(reg,repo,rosters,results,opt_in=True,plan=plan,gate=gate)):
        raise ValueError('exact Stage108 eligible teams/checkpoint/seed/input required')


def simulate_tournament_match(match, reg, repo, rosters, results=(), *, plan=None, gate='C'):
    validate_tournament_input(match,reg,repo,rosters,results,plan=plan,gate=gate)
    result = _run(match,match.match_seed)
    event_oracle(result,match)
    progression_oracle(_plan(reg,gate),reg,results+(result,))
    return result
