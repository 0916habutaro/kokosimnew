"""Explicit Stage107 two-game opt-in. Stage104/105/106 APIs stay fixed."""
from dataclasses import asdict, dataclass

from .joint_team_fixture import YEAR, COMPETITION, ROSTER_SEED
from .joint_team_registration_lab import (
    RegisteredTeamInput, _team_input, _sha, _identical, validate_registration,
)
from .registered_match_driver import _run
from .registered_full_a_oracle import event_oracle
from .joint_tournament_oracle import progression_oracle

VERSION = 'stage43g107_two_game_input_v1'
PLAN_VERSION = 'stage43g107_three_team_plan_v1'
PREFIX = f'LAB107:{YEAR}:{COMPETITION}:'


@dataclass(frozen=True)
class PlannedGame:
    sequence: int
    match_id: str
    day: str
    seed: int
    team1_source: str
    team2_source: str


@dataclass(frozen=True)
class ThreeTeamPlan:
    version: str
    year: int
    competition_id: str
    registration_sha256: str
    entries: tuple[str, ...]
    bye_team_id: str
    games: tuple[PlannedGame, ...]

    def to_dict(self):
        return asdict(self)

    @property
    def fingerprint(self):
        return _sha(self.to_dict())


def fixed_plan(registration, repo, rosters):
    validate_registration(registration, repo, rosters)
    entries = tuple(t.team_id for t in registration.teams)
    return ThreeTeamPlan(PLAN_VERSION, YEAR, COMPETITION, _sha(registration.to_dict()),
        entries, entries[2], (
            PlannedGame(1, PREFIX + 'match1', '2026-07-01', 430107, entries[0], entries[1]),
            PlannedGame(2, PREFIX + 'match2', '2026-07-02', 430108, 'winner:' + PREFIX + 'match1', entries[2]),
        ))


@dataclass(frozen=True)
class TournamentMatchInput:
    version: str
    year: int
    competition_id: str
    match_id: str
    match_seed: int
    ability_seed: int
    registration_sha256: str
    opt_in: bool
    plan_sha256: str
    prior_result_sha256: str | None
    day: str
    team1: RegisteredTeamInput
    team2: RegisteredTeamInput

    def to_dict(self):
        return asdict(self)


def _input(plan, registration, previous):
    game = plan.games[len(previous)]
    known = {t.team_id: t for t in registration.teams}
    first = previous[0].winner_id if previous else plan.entries[0]
    second = plan.bye_team_id if previous else plan.entries[1]
    return TournamentMatchInput(VERSION, YEAR, COMPETITION, game.match_id, game.seed,
        ROSTER_SEED, plan.registration_sha256, True, plan.fingerprint,
        _sha(previous[0].to_dict()) if previous else None, game.day,
        _team_input(known[first]), _team_input(known[second]))


def _validate_result(result, match):
    report = event_oracle(result, match)
    if not _identical(result, _run(match, match.match_seed)):
        raise ValueError('Stage107 result differs from fixed seeded execution')
    return report


def verify_prefix(registration, repo, rosters, results, *, plan=None):
    """Full seed/event replay, then independent tournament progression oracle."""
    if type(results) is not tuple or len(results) > 2:
        raise ValueError('immutable zero/one/two game prefix required')
    expected = fixed_plan(registration, repo, rosters)
    if plan is not None and not _identical(plan, expected):
        raise ValueError('unknown plan/BYE/source/seed/date')
    for i, result in enumerate(results):
        _validate_result(result, _input(expected, registration, results[:i]))
    ledger, ranks = progression_oracle(expected, registration, results)
    return expected, ledger, ranks


def next_match_input(registration, repo, rosters, results=(), *, opt_in=False, plan=None):
    if opt_in is not True:
        raise ValueError('explicit Stage107 lab opt-in required')
    checked, _, _ = verify_prefix(registration, repo, rosters, results, plan=plan)
    if len(results) == 2:
        raise ValueError('two-game plan already complete')
    return _input(checked, registration, results)


def validate_tournament_input(match, registration, repo, rosters, results=(), *, plan=None):
    expected = next_match_input(registration, repo, rosters, results, opt_in=True, plan=plan)
    if not _identical(match, expected):
        raise ValueError('Stage107 exact plan/eligible teams/ID/seeds/abilities required')


def simulate_tournament_match(match, registration, repo, rosters, results=(), *, plan=None):
    validate_tournament_input(match, registration, repo, rosters, results, plan=plan)
    result = _run(match, match.match_seed)
    verify_prefix(registration, repo, rosters, results + (result,), plan=plan)
    return result
