"""Versioned origin-preserving lab results. No legacy serialization adapter."""
from dataclasses import asdict, dataclass, fields
import json

VERSION = 'registered_team_full_a_v1'
MODEL = 'lab105_partial_probability_fixed_advancement_v1'


@dataclass(frozen=True)
class MatchScope:
    year: int
    competition_id: str
    match_id: str


@dataclass(frozen=True)
class RegisteredBatterStatsV1(MatchScope):
    team_id: str
    player_id: str
    origin_school_id: str
    plate_appearances: int = 0
    at_bats: int = 0
    runs: int = 0
    hits: int = 0
    doubles: int = 0
    triples: int = 0
    home_runs: int = 0
    rbi: int = 0
    walks: int = 0
    strikeouts: int = 0
    hit_by_pitch: int = 0
    sacrifice_flies: int = 0
    sacrifice_bunts: int = 0
    stolen_bases: int = 0
    caught_stealing: int = 0


@dataclass(frozen=True)
class RegisteredPitcherStatsV1(MatchScope):
    team_id: str
    player_id: str
    origin_school_id: str
    outs_recorded: int = 0
    batters_faced: int = 0
    runs_allowed: int = 0
    earned_runs: int = 0
    hits_allowed: int = 0
    home_runs_allowed: int = 0
    walks: int = 0
    strikeouts: int = 0
    hit_batters: int = 0


@dataclass(frozen=True)
class RegisteredTeamStatsV1(MatchScope):
    team_id: str
    runs: int
    hits: int
    errors: int


@dataclass(frozen=True)
class RegisteredInningScoreV1(MatchScope):
    inning: int
    half: str
    team_id: str
    was_played: bool
    runs: int | None


@dataclass(frozen=True)
class RegisteredEventV1(MatchScope):
    event_no: int
    inning: int
    half: str
    offense_team_id: str
    defense_team_id: str
    batter_id: str
    pitcher_id: str
    batter_origin_school_id: str
    pitcher_origin_school_id: str
    event_type: str
    bases_before: tuple[str | None, ...]
    bases_after: tuple[str | None, ...]
    scored_player_ids: tuple[str, ...]
    outs_before: int
    outs_on_play: int
    rbi: int
    pitcher_staff_order: int
    # The removed starter/reliever leaves the batting order at the same slot.
    replaced_pitcher_id: str | None


@dataclass(frozen=True)
class RegisteredTeamFullAResultV1(MatchScope):
    version: str
    model: str
    input_sha256: str
    probability_config_sha256: str
    run_seed: int
    team1_id: str
    team2_id: str
    team1_score: int
    team2_score: int
    winner_id: str
    loser_id: str
    last_inning: int
    ending_half: str
    team_stats: tuple[RegisteredTeamStatsV1, ...]
    inning_scores: tuple[RegisteredInningScoreV1, ...]
    batter_stats: tuple[RegisteredBatterStatsV1, ...]
    pitcher_stats: tuple[RegisteredPitcherStatsV1, ...]
    events: tuple[RegisteredEventV1, ...]

    def to_dict(self):
        return asdict(self)

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False)


def _record(cls, value):
    if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
        raise ValueError('exact versioned record keys required')
    return cls(**value)


def decode_result(raw):
    """Structural decoding only. Public load_result also validates authorities."""
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate JSON key')
            out[key] = value
        return out
    try:
        data = json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        if type(data) is not dict or data.get('version') != VERSION:
            raise ValueError('registered full-A version required')
        nested = {'team_stats': RegisteredTeamStatsV1,
                  'inning_scores': RegisteredInningScoreV1,
                  'batter_stats': RegisteredBatterStatsV1,
                  'pitcher_stats': RegisteredPitcherStatsV1,
                  'events': RegisteredEventV1}
        for name, cls in nested.items():
            if type(data[name]) is not list:
                raise ValueError('JSON array required')
            rows = []
            for value in data[name]:
                if cls is RegisteredEventV1:
                    for key in ('bases_before', 'bases_after', 'scored_player_ids'):
                        if type(value[key]) is not list:
                            raise ValueError('event array required')
                        value[key] = tuple(value[key])
                rows.append(_record(cls, value))
            data[name] = tuple(rows)
        return _record(RegisteredTeamFullAResultV1, data)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid registered full-A JSON') from exc


def validate_shape(result):
    """Validate the versioned type tree without generating or simulating a game."""
    from types import UnionType
    from typing import get_args, get_origin

    def check(value, annotation):
        origin, args = get_origin(annotation), get_args(annotation)
        if origin is UnionType:
            if not any(valid(value, option) for option in args):
                raise ValueError('invalid optional scalar type')
        elif origin is tuple:
            if type(value) is not tuple or not all(valid(item, args[0]) for item in value):
                raise ValueError('immutable typed tuple required')
        elif hasattr(annotation, '__dataclass_fields__'):
            if type(value) is not annotation:
                raise ValueError('exact versioned record type required')
            for field in fields(annotation):
                check(getattr(value, field.name), field.type)
        elif type(value) is not annotation:
            raise ValueError('exact scalar type required')

    def valid(value, annotation):
        try:
            check(value, annotation)
            return True
        except ValueError:
            return False

    check(result, RegisteredTeamFullAResultV1)
    if result.version != VERSION or result.model != MODEL:
        raise ValueError('unsupported registered full-A version/model')
