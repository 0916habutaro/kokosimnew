"""Stage104 fixed synthetic lab; no save path, writer, legacy adapter or engine.

The public validator requires the school authorities again, not a caller-supplied
digest. Ability school_id always means origin school, never competition team.
"""
from dataclasses import asdict, dataclass, fields, is_dataclass
import hashlib
import json
from statistics import fmean

from game_core.players import Player, PlayerRosterGenerator
from game_core.school_intake import (
    IntakeAdjustedPlayerAbilitySnapshot, SchoolAwarePlayerAbilityGenerator,
)
from .joint_team_fixture import (
    JointTeamFixture, YEAR, COMPETITION, ROSTER_SEED, ENTRIES,
)

VERSION = "stage43g104_registration_lab_v1"
SELECTION = "fixture_alternate_position20_v1"
ABILITY_RECIPE = "origin_school_intake_v1"
USAGE_RECIPE = "lab_primary_contact_control_v1"
PREFIX = f"LAB104:{YEAR}:{COMPETITION}:"
MATCH_SEED = 430104


class JointSimulationUnsupported(ValueError):
    """An origin-preserving full-A driver/result contract has not been adopted."""


def _sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _identical(actual, expected):
    """Reject bool-as-int, mutable containers and foreign/subclass records too."""
    if type(actual) is not type(expected):
        return False
    if is_dataclass(expected):
        return all(_identical(getattr(actual, f.name), getattr(expected, f.name))
                   for f in fields(expected))
    if type(expected) in (tuple, list):
        return len(actual) == len(expected) and all(
            _identical(a, b) for a, b in zip(actual, expected))
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(
            _identical(actual[key], expected[key]) for key in expected)
    return actual == expected


@dataclass(frozen=True)
class RegisteredPlayer:
    year: int
    competition_id: str
    team_id: str
    player_id: str
    origin_school_id: str
    team_slot: int
    source_roster_sha256: str
    # Immutable reference snapshot; entry_year, grade, position and roster_no.
    player: Player


@dataclass(frozen=True)
class RegisteredTeam:
    year: int
    competition_id: str
    team_id: str
    label: str
    source_version: str
    selection_recipe: str
    school_ids: tuple[str, ...]
    players: tuple[RegisteredPlayer, ...]


@dataclass(frozen=True)
class CompetitionRegistration:
    version: str
    year: int
    competition_id: str
    roster_seed: int
    roster_set_sha256: str
    school_fingerprints: tuple[tuple[str, str], ...]
    teams: tuple[RegisteredTeam, ...]

    def to_dict(self):
        return asdict(self)

    def school_participation(self, school_id):
        """Historical participation only; deliberately no school wins/ranking."""
        if school_id not in dict(self.school_fingerprints):
            raise ValueError("school outside fixed lab scope")
        return tuple((t.year, t.competition_id, t.team_id) for t in self.teams
                     if school_id in t.school_ids)

    def preview(self, team_id):
        team = next((t for t in self.teams if t.team_id == team_id), None)
        if team is None:
            raise ValueError("team outside fixed lab scope")
        return {**asdict(team), "match_result_status": "試合結果は未対応",
                "archived_results": None}


def registration_from_rosters(repo, rosters):
    """Only the Stage103 self-generated authorities are accepted, in memory."""
    rosters = tuple(rosters)
    source = JointTeamFixture.from_rosters(repo, rosters)
    generator = PlayerRosterGenerator()
    for roster in rosters:
        expected = generator.generate_for_school_id(repo, roster.school_id, YEAR, ROSTER_SEED)
        if not _identical(roster.to_dict(), expected.to_dict()):
            raise ValueError("school authority has changed values or scalar types")
    fingerprints = tuple(sorted((r.school_id, _sha(r.to_dict())) for r in rosters))
    by_school = dict(fingerprints)
    by_player = {p.player_id: p for p in source.players}
    teams = []
    for entry in ENTRIES:
        team_id = PREFIX + entry.team_id.rsplit(":", 1)[1]
        if team_id in repo.schools:
            raise ValueError("competition team collides with school namespace")
        rows = tuple(RegisteredPlayer(
            YEAR, COMPETITION, team_id, p["player_id"], p["school_id"],
            p["team_slot"], by_school[p["school_id"]], by_player[p["player_id"]])
            for p in source.preview(entry.team_id)["players"])
        teams.append(RegisteredTeam(YEAR, COMPETITION, team_id, entry.label,
                     VERSION, SELECTION, entry.school_ids, rows))
    return CompetitionRegistration(VERSION, YEAR, COMPETITION, ROSTER_SEED,
                                   source.roster_sha256, fingerprints, tuple(teams))


def validate_registration(registration, repo, rosters):
    expected = registration_from_rosters(repo, rosters)
    if not _identical(registration, expected):
        raise ValueError("registration differs from fixed school authorities/recipe")


@dataclass(frozen=True)
class RegisteredAbility:
    team_id: str
    player_id: str
    origin_school_id: str
    snapshot: IntakeAdjustedPlayerAbilitySnapshot


@dataclass(frozen=True)
class LabTeamAbilitySummary:
    """Lab means, not TeamStrengthSnapshot metrics or a simulation probability."""
    team_id: str
    recipe: str
    mean_contact: float
    mean_power: float
    mean_fielding: float
    mean_pitcher_control: float


@dataclass(frozen=True)
class RegisteredTeamInput:
    team_id: str
    registration_sha256: str
    ability_recipe: str
    usage_recipe: str
    players: tuple[RegisteredAbility, ...]
    # (batting order, defensive position, permanent player ID)
    lineup: tuple[tuple[int, str, str], ...]
    pitching_order: tuple[str, ...]
    summary: LabTeamAbilitySummary


@dataclass(frozen=True)
class RegisteredMatchInput:
    version: str
    year: int
    competition_id: str
    match_id: str
    match_seed: int
    ability_seed: int
    registration_sha256: str
    opt_in: bool
    team1: RegisteredTeamInput
    team2: RegisteredTeamInput

    def to_dict(self):
        return asdict(self)


def _team_input(team):
    generator = SchoolAwarePlayerAbilityGenerator()
    players = tuple(RegisteredAbility(team.team_id, r.player_id, r.origin_school_id,
                    generator.generate(r.player, YEAR, ROSTER_SEED)) for r in team.players)
    positions = ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
    # The starting P must also be the first pitcher; never create two starters.
    chosen = [min((p for p in players if p.snapshot.primary_position == position),
                  key=lambda p: (-(p.snapshot.control if position == "P"
                                   else p.snapshot.contact), p.player_id)) for position in positions]
    starters = sorted(chosen, key=lambda p: (-p.snapshot.contact, p.player_id))
    lineup = tuple((i, p.snapshot.primary_position, p.player_id)
                   for i, p in enumerate(starters, 1))
    pitchers = sorted((p for p in players if p.snapshot.primary_position == "P"),
                      key=lambda p: (-p.snapshot.control, p.player_id))
    summary = LabTeamAbilitySummary(team.team_id, USAGE_RECIPE,
        fmean(p.snapshot.contact for p in players), fmean(p.snapshot.power for p in players),
        fmean(p.snapshot.fielding for p in players), fmean(p.snapshot.control for p in pitchers))
    return RegisteredTeamInput(team.team_id, _sha(asdict(team)), ABILITY_RECIPE,
                               USAGE_RECIPE, players, lineup,
                               tuple(p.player_id for p in pitchers), summary)


def match_input_from_registration(registration, repo, rosters, *, team1_id,
                                  team2_id, opt_in=False):
    validate_registration(registration, repo, rosters)
    if opt_in is not True:
        raise ValueError("explicit lab opt-in required")
    known = {t.team_id: t for t in registration.teams}
    if (type(team1_id) is not str or type(team2_id) is not str
            or team1_id == team2_id or team1_id not in known or team2_id not in known):
        raise ValueError("two distinct registered teams required")
    return RegisteredMatchInput(VERSION, YEAR, COMPETITION, PREFIX + "match1",
        MATCH_SEED, ROSTER_SEED, _sha(registration.to_dict()), True,
        _team_input(known[team1_id]), _team_input(known[team2_id]))


def validate_registered_match_input(match_input, registration, repo, rosters):
    if type(match_input) is not RegisteredMatchInput:
        raise ValueError("versioned registered match input required")
    if (type(match_input.team1) is not RegisteredTeamInput
            or type(match_input.team2) is not RegisteredTeamInput):
        raise ValueError("versioned registered teams required")
    expected = match_input_from_registration(registration, repo, rosters,
        team1_id=match_input.team1.team_id, team2_id=match_input.team2.team_id, opt_in=True)
    if not _identical(match_input, expected):
        raise ValueError("match input differs from registered origin abilities/recipe/seeds")


def legacy_match_input(*args, **kwargs):
    raise JointSimulationUnsupported("legacy school-keyed stats cannot retain origin school and team")


def simulate_registered_match(match_input, registration, repo, rosters):
    validate_registered_match_input(match_input, registration, repo, rosters)
    raise JointSimulationUnsupported(
        "0 matches: new team-keyed full-A result/event/stats and driver required; no writer adopted")
