from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from .abilities import PlayerAbilitySnapshot
from .match_config import load_and_validate_match_configs
from .team_strength import TeamStrengthSnapshot


SCORE_SOURCE_ABILITY_MODEL_V1 = "ability_model_v1"
HALVES = ("top", "bottom")


@dataclass(frozen=True)
class TeamMatchInput:
    school_id: str
    team_strength: TeamStrengthSnapshot
    player_abilities: tuple[PlayerAbilitySnapshot, ...]

    def to_dict(self) -> dict:
        return {
            "school_id": self.school_id,
            "team_strength": self.team_strength.to_dict(),
            "player_abilities": [
                player.to_dict()
                for player in self.player_abilities
            ],
        }


@dataclass(frozen=True)
class MatchSimulationInput:
    match_id: str
    competition_id: str
    reference_year: int
    generation_seed: int
    team1: TeamMatchInput
    team2: TeamMatchInput
    team_generation_seed: int | None = None

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "competition_id": self.competition_id,
            "reference_year": self.reference_year,
            "generation_seed": self.generation_seed,
            "team_generation_seed": self.team_generation_seed,
            "team1": self.team1.to_dict(),
            "team2": self.team2.to_dict(),
        }


@dataclass(frozen=True)
class MatchEvent:
    event_no: int
    plate_appearance_no: int
    inning: int
    half: str
    offense_school_id: str
    defense_school_id: str
    batter_id: str
    pitcher_id: str
    event_type: str
    runs_scored: int = 0
    outs_on_play: int = 0
    rbi: int = 0
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        out = asdict(self)
        out["metadata"] = dict(self.metadata)
        return out


@dataclass(frozen=True)
class BatterGameStats:
    player_id: str
    school_id: str
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

    @property
    def singles(self) -> int:
        return (
            self.hits
            - self.doubles
            - self.triples
            - self.home_runs
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        out["singles"] = self.singles
        return out


@dataclass(frozen=True)
class PitcherGameStats:
    player_id: str
    school_id: str
    outs_recorded: int = 0
    batters_faced: int = 0
    runs_allowed: int = 0
    earned_runs: int = 0
    hits_allowed: int = 0
    home_runs_allowed: int = 0
    walks: int = 0
    strikeouts: int = 0
    hit_batters: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TeamGameStats:
    school_id: str
    runs: int
    hits: int
    errors: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class InningScore:
    """An explicitly played or skipped half-inning in a completed game."""

    inning: int
    half: str
    batting_team_id: str
    was_played: bool
    runs: int | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MatchSimulationResult:
    match_id: str
    competition_id: str
    reference_year: int
    generation_seed: int
    team1_school_id: str
    team2_school_id: str
    team1_score: int
    team2_score: int
    winner_id: str
    loser_id: str
    last_inning: int
    ending_half: str
    score_source: str

    match_config_id: str
    match_config_revision: int
    match_config_sha256: str
    event_catalog_id: str
    event_catalog_revision: int
    event_catalog_sha256: str
    stats_config_id: str
    stats_config_revision: int
    stats_config_sha256: str

    team_stats: tuple[TeamGameStats, ...]
    events: tuple[MatchEvent, ...]
    batter_stats: tuple[BatterGameStats, ...]
    pitcher_stats: tuple[PitcherGameStats, ...]
    # None is a legacy result with no line-score data; an empty tuple is invalid.
    inning_scores: tuple[InningScore, ...] | None = None

    def to_dict(self) -> dict:
        out = asdict(self)
        out["team_stats"] = [
            item.to_dict() for item in self.team_stats
        ]
        out["events"] = [
            item.to_dict() for item in self.events
        ]
        out["batter_stats"] = [
            item.to_dict() for item in self.batter_stats
        ]
        out["pitcher_stats"] = [
            item.to_dict() for item in self.pitcher_stats
        ]
        out["inning_scores"] = (
            None if self.inning_scores is None else [
                item.to_dict() for item in self.inning_scores
            ]
        )
        return out


@dataclass(frozen=True)
class MatchContractProvenance:
    match_config_id: str
    match_config_revision: int
    match_config_sha256: str
    event_catalog_id: str
    event_catalog_revision: int
    event_catalog_sha256: str
    stats_config_id: str
    stats_config_revision: int
    stats_config_sha256: str
    score_source: str

    def to_dict(self) -> dict:
        return asdict(self)


def match_contract_provenance(
    config_dir: str | Path = "config/match",
) -> MatchContractProvenance:
    configs = load_and_validate_match_configs(config_dir)
    match = configs["match_simulation_v1"]
    events = configs["event_catalog_v1"]
    stats = configs["game_stats_contract_v1"]
    return MatchContractProvenance(
        match_config_id=match.config_id,
        match_config_revision=match.revision,
        match_config_sha256=match.canonical_sha256,
        event_catalog_id=events.config_id,
        event_catalog_revision=events.revision,
        event_catalog_sha256=events.canonical_sha256,
        stats_config_id=stats.config_id,
        stats_config_revision=stats.revision,
        stats_config_sha256=stats.canonical_sha256,
        score_source=str(match.payload["score_source"]),
    )


def _player_map(team: TeamMatchInput) -> dict[str, PlayerAbilitySnapshot]:
    return {
        player.player_id: player
        for player in team.player_abilities
    }


def validate_team_match_input(team: TeamMatchInput) -> None:
    if not team.school_id:
        raise ValueError("team match input: school_id required")
    strength = team.team_strength
    if strength.school_id != team.school_id:
        raise ValueError(
            "team match input: TeamStrength school_id mismatch"
        )

    players = list(team.player_abilities)
    if len(players) < 12:
        raise ValueError(
            f"{team.school_id}: at least 12 player abilities required"
        )
    ids = [player.player_id for player in players]
    if len(ids) != len(set(ids)):
        raise ValueError(
            f"{team.school_id}: duplicate player ability"
        )
    if {player.school_id for player in players} != {team.school_id}:
        raise ValueError(
            f"{team.school_id}: player school_id mismatch"
        )
    if {player.reference_year for player in players} != {
        strength.reference_year
    }:
        raise ValueError(
            f"{team.school_id}: player reference_year mismatch"
        )
    if {player.generation_seed for player in players} != {
        strength.generation_seed
    }:
        raise ValueError(
            f"{team.school_id}: player generation_seed mismatch"
        )
    if {player.generation_sha256 for player in players} != {
        strength.player_generation_sha256
    }:
        raise ValueError(
            f"{team.school_id}: player generation config mismatch"
        )

    intake_ids = {
        getattr(player, "intake_config_id", None)
        for player in players
    }
    intake_revisions = {
        getattr(player, "intake_config_revision", None)
        for player in players
    }
    intake_shas = {
        getattr(player, "intake_config_sha256", None)
        for player in players
    }
    expected_intake = (
        strength.school_intake_config_id,
        strength.school_intake_config_revision,
        strength.school_intake_config_sha256,
    )
    if (
        len(intake_ids) != 1
        or len(intake_revisions) != 1
        or len(intake_shas) != 1
        or (
            next(iter(intake_ids)),
            next(iter(intake_revisions)),
            next(iter(intake_shas)),
        )
        != expected_intake
    ):
        raise ValueError(
            f"{team.school_id}: school intake provenance mismatch"
        )

    known_ids = set(ids)
    starter_ids = set(strength.starting_lineup.starter_ids)
    pitcher_ids = {
        item.player_id
        for item in strength.pitching_staff.entries
    }
    if not starter_ids.issubset(known_ids):
        raise ValueError(
            f"{team.school_id}: lineup references unknown player"
        )
    if not pitcher_ids.issubset(known_ids):
        raise ValueError(
            f"{team.school_id}: pitching staff references unknown player"
        )


def validate_match_simulation_input(
    match_input: MatchSimulationInput,
) -> None:
    if not match_input.match_id:
        raise ValueError("match simulation input: match_id required")
    if not match_input.competition_id:
        raise ValueError(
            "match simulation input: competition_id required"
        )
    if match_input.reference_year < 1:
        raise ValueError(
            "match simulation input: reference_year must be positive"
        )
    if match_input.team1.school_id == match_input.team2.school_id:
        raise ValueError(
            "match simulation input: teams must differ"
        )

    validate_team_match_input(match_input.team1)
    validate_team_match_input(match_input.team2)

    expected_team_seed = (
        match_input.generation_seed
        if match_input.team_generation_seed is None
        else match_input.team_generation_seed
    )
    if (
        not isinstance(expected_team_seed, int)
        or isinstance(expected_team_seed, bool)
    ):
        raise ValueError(
            "match simulation input: team_generation_seed must be integer"
        )

    for label, team in (
        ("team1", match_input.team1),
        ("team2", match_input.team2),
    ):
        strength = team.team_strength
        if strength.reference_year != match_input.reference_year:
            raise ValueError(
                f"match simulation input: {label} reference_year mismatch"
            )
        if strength.generation_seed != expected_team_seed:
            raise ValueError(
                f"match simulation input: {label} team generation_seed mismatch"
            )


def validate_batter_game_stats(stats: BatterGameStats) -> None:
    values = asdict(stats)
    for key, value in values.items():
        if key in {"player_id", "school_id"}:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"{stats.player_id}: invalid batter stat {key}={value}"
            )

    expected_pa = (
        stats.at_bats
        + stats.walks
        + stats.hit_by_pitch
        + stats.sacrifice_flies
        + stats.sacrifice_bunts
    )
    if stats.plate_appearances != expected_pa:
        raise ValueError(
            f"{stats.player_id}: plate appearance formula mismatch"
        )
    if stats.hits > stats.at_bats:
        raise ValueError(
            f"{stats.player_id}: hits cannot exceed at_bats"
        )
    if stats.singles < 0:
        raise ValueError(
            f"{stats.player_id}: extra-base hits exceed total hits"
        )
    if stats.strikeouts > stats.at_bats:
        raise ValueError(
            f"{stats.player_id}: strikeouts cannot exceed at_bats"
        )


def validate_pitcher_game_stats(stats: PitcherGameStats) -> None:
    values = asdict(stats)
    for key, value in values.items():
        if key in {"player_id", "school_id"}:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"{stats.player_id}: invalid pitcher stat {key}={value}"
            )

    if stats.earned_runs > stats.runs_allowed:
        raise ValueError(
            f"{stats.player_id}: earned_runs cannot exceed runs_allowed"
        )
    if stats.home_runs_allowed > stats.hits_allowed:
        raise ValueError(
            f"{stats.player_id}: home_runs_allowed cannot exceed hits_allowed"
        )
    if stats.strikeouts > stats.batters_faced:
        raise ValueError(
            f"{stats.player_id}: strikeouts cannot exceed batters_faced"
        )
    if (
        stats.hits_allowed
        + stats.walks
        + stats.hit_batters
        > stats.batters_faced
    ):
        raise ValueError(
            f"{stats.player_id}: reach events exceed batters_faced"
        )
    if stats.outs_recorded > stats.batters_faced * 3:
        raise ValueError(
            f"{stats.player_id}: outs_recorded inconsistent with batters_faced"
        )


def validate_team_game_stats(stats: TeamGameStats) -> None:
    for key in ("runs", "hits", "errors"):
        value = getattr(stats, key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"{stats.school_id}: invalid team stat {key}={value}"
            )


def _event_type_map(
    config_dir: str | Path,
) -> dict[str, dict]:
    configs = load_and_validate_match_configs(config_dir)
    return {
        str(item["event_type"]): item
        for item in configs["event_catalog_v1"].payload["event_types"]
    }


def validate_match_event(
    event: MatchEvent,
    match_input: MatchSimulationInput,
    *,
    config_dir: str | Path = "config/match",
) -> None:
    if event.event_no < 1:
        raise ValueError("match event: event_no must be >= 1")
    if event.plate_appearance_no < 1:
        raise ValueError(
            "match event: plate_appearance_no must be >= 1"
        )
    if event.inning < 1:
        raise ValueError("match event: inning must be >= 1")
    if event.half not in HALVES:
        raise ValueError(
            f"match event: invalid half {event.half}"
        )

    expected_offense = (
        match_input.team1.school_id
        if event.half == "top"
        else match_input.team2.school_id
    )
    expected_defense = (
        match_input.team2.school_id
        if event.half == "top"
        else match_input.team1.school_id
    )
    if (
        event.offense_school_id != expected_offense
        or event.defense_school_id != expected_defense
    ):
        raise ValueError(
            f"match event {event.event_no}: offense/defense order mismatch"
        )

    catalog = _event_type_map(config_dir)
    if event.event_type not in catalog:
        raise ValueError(
            f"match event {event.event_no}: unknown event_type "
            f"{event.event_type}"
        )

    offense_team = (
        match_input.team1
        if event.offense_school_id == match_input.team1.school_id
        else match_input.team2
    )
    defense_team = (
        match_input.team1
        if event.defense_school_id == match_input.team1.school_id
        else match_input.team2
    )
    batter = _player_map(offense_team).get(event.batter_id)
    pitcher = _player_map(defense_team).get(event.pitcher_id)
    if batter is None:
        raise ValueError(
            f"match event {event.event_no}: batter not on offense team"
        )
    if pitcher is None:
        raise ValueError(
            f"match event {event.event_no}: pitcher not on defense team"
        )
    if pitcher.primary_position != "P":
        raise ValueError(
            f"match event {event.event_no}: pitcher_id must reference P"
        )

    if event.runs_scored < 0:
        raise ValueError(
            f"match event {event.event_no}: runs_scored must be >= 0"
        )
    if not 0 <= event.outs_on_play <= 3:
        raise ValueError(
            f"match event {event.event_no}: outs_on_play must be 0..3"
        )
    if not 0 <= event.rbi <= event.runs_scored:
        raise ValueError(
            f"match event {event.event_no}: rbi must be 0..runs_scored"
        )


def _validate_unique_player_stats(
    rows: Iterable[BatterGameStats | PitcherGameStats],
    *,
    label: str,
) -> None:
    ids = [row.player_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label}: duplicate player stats row")


def validate_match_simulation_result(
    result: MatchSimulationResult,
    match_input: MatchSimulationInput,
    *,
    config_dir: str | Path = "config/match",
) -> None:
    validate_match_simulation_input(match_input)

    if result.match_id != match_input.match_id:
        raise ValueError("match result: match_id mismatch")
    if result.competition_id != match_input.competition_id:
        raise ValueError("match result: competition_id mismatch")
    if result.reference_year != match_input.reference_year:
        raise ValueError("match result: reference_year mismatch")
    if result.generation_seed != match_input.generation_seed:
        raise ValueError("match result: generation_seed mismatch")

    team1_id = match_input.team1.school_id
    team2_id = match_input.team2.school_id
    if (
        result.team1_school_id != team1_id
        or result.team2_school_id != team2_id
    ):
        raise ValueError("match result: team order mismatch")

    if result.team1_score < 0 or result.team2_score < 0:
        raise ValueError("match result: scores must be non-negative")
    if result.team1_score == result.team2_score:
        raise ValueError("match result: completed game cannot be tied")

    expected_winner = (
        team1_id
        if result.team1_score > result.team2_score
        else team2_id
    )
    expected_loser = team2_id if expected_winner == team1_id else team1_id
    if (
        result.winner_id != expected_winner
        or result.loser_id != expected_loser
    ):
        raise ValueError("match result: winner/loser inconsistent with score")
    if result.last_inning < 1:
        raise ValueError("match result: last_inning must be >= 1")
    if result.ending_half not in HALVES:
        raise ValueError("match result: ending_half must be top/bottom")

    if result.inning_scores is not None:
        # Every played half is explicit. The last bottom may be skipped when
        # the home team is already ahead; this is not the same as zero runs.
        line = list(result.inning_scores)
        expected = [
            (inning, half)
            for inning in range(1, result.last_inning + 1)
            for half in HALVES
        ]
        if [(row.inning, row.half) for row in line] != expected:
            raise ValueError("match result: inning score order/coverage mismatch")
        totals = {"top": 0, "bottom": 0}
        skipped = []
        for row in line:
            expected_batting = team1_id if row.half == "top" else team2_id
            if row.batting_team_id != expected_batting:
                raise ValueError("match result: inning score batting team mismatch")
            if not isinstance(row.was_played, bool):
                raise ValueError("match result: inning score was_played invalid")
            if row.was_played:
                if (not isinstance(row.runs, int) or isinstance(row.runs, bool)
                        or row.runs < 0):
                    raise ValueError("match result: played inning runs invalid")
                totals[row.half] += row.runs
            else:
                if row.runs is not None:
                    raise ValueError("match result: unplayed inning must have null runs")
                skipped.append((row.inning, row.half))
        if skipped and (skipped != [(result.last_inning, "bottom")]
                        or result.ending_half != "top"):
            raise ValueError("match result: invalid skipped half-inning")
        if result.ending_half == "top" and not skipped:
            raise ValueError("match result: top ending requires skipped bottom")
        if (totals["top"], totals["bottom"]) != (
            result.team1_score, result.team2_score
        ):
            raise ValueError("match result: inning score totals mismatch")

    provenance = match_contract_provenance(config_dir)
    actual_provenance = MatchContractProvenance(
        match_config_id=result.match_config_id,
        match_config_revision=result.match_config_revision,
        match_config_sha256=result.match_config_sha256,
        event_catalog_id=result.event_catalog_id,
        event_catalog_revision=result.event_catalog_revision,
        event_catalog_sha256=result.event_catalog_sha256,
        stats_config_id=result.stats_config_id,
        stats_config_revision=result.stats_config_revision,
        stats_config_sha256=result.stats_config_sha256,
        score_source=result.score_source,
    )
    if actual_provenance != provenance:
        raise ValueError("match result: config provenance mismatch")

    team_rows = list(result.team_stats)
    if len(team_rows) != 2:
        raise ValueError("match result: exactly two team stats rows required")
    if {row.school_id for row in team_rows} != {team1_id, team2_id}:
        raise ValueError("match result: team stats school ids mismatch")
    for row in team_rows:
        validate_team_game_stats(row)
    team_by_id = {row.school_id: row for row in team_rows}
    if team_by_id[team1_id].runs != result.team1_score:
        raise ValueError("match result: team1 runs != score")
    if team_by_id[team2_id].runs != result.team2_score:
        raise ValueError("match result: team2 runs != score")

    events = list(result.events)
    if not events:
        raise ValueError("match result: at least one event required")
    if [event.event_no for event in events] != list(
        range(1, len(events) + 1)
    ):
        raise ValueError("match result: event_no must be contiguous")
    if [event.plate_appearance_no for event in events] != list(
        range(1, len(events) + 1)
    ):
        raise ValueError(
            "match result: plate_appearance_no must be contiguous in v1"
        )
    for event in events:
        validate_match_event(
            event,
            match_input,
            config_dir=config_dir,
        )
    if result.inning_scores is not None:
        actual_by_half: dict[tuple[int, str], int] = {}
        for event in events:
            key = (event.inning, event.half)
            actual_by_half[key] = (
                actual_by_half.get(key, 0) + event.runs_scored
            )
        for row in result.inning_scores:
            if row.was_played and actual_by_half.get((row.inning, row.half), 0) != row.runs:
                raise ValueError("match result: inning score differs from events")

    event_runs = {team1_id: 0, team2_id: 0}
    for event in events:
        event_runs[event.offense_school_id] += event.runs_scored
    if event_runs[team1_id] != result.team1_score:
        raise ValueError("match result: team1 event runs != score")
    if event_runs[team2_id] != result.team2_score:
        raise ValueError("match result: team2 event runs != score")

    batters = list(result.batter_stats)
    pitchers = list(result.pitcher_stats)
    _validate_unique_player_stats(batters, label="batter stats")
    _validate_unique_player_stats(pitchers, label="pitcher stats")
    for row in batters:
        validate_batter_game_stats(row)
    for row in pitchers:
        validate_pitcher_game_stats(row)

    known = {
        team1_id: _player_map(match_input.team1),
        team2_id: _player_map(match_input.team2),
    }
    for row in batters:
        if row.school_id not in known or row.player_id not in known[row.school_id]:
            raise ValueError(
                f"batter stats: unknown player {row.player_id}"
            )
    for row in pitchers:
        if row.school_id not in known or row.player_id not in known[row.school_id]:
            raise ValueError(
                f"pitcher stats: unknown player {row.player_id}"
            )
        if known[row.school_id][row.player_id].primary_position != "P":
            raise ValueError(
                f"pitcher stats: player {row.player_id} is not P"
            )

    batter_ids = {row.player_id for row in batters}
    pitcher_ids = {row.player_id for row in pitchers}
    if not {event.batter_id for event in events}.issubset(batter_ids):
        raise ValueError(
            "match result: event batter missing batter stats"
        )
    if not {event.pitcher_id for event in events}.issubset(pitcher_ids):
        raise ValueError(
            "match result: event pitcher missing pitcher stats"
        )

    batter_by_school = {
        team1_id: [row for row in batters if row.school_id == team1_id],
        team2_id: [row for row in batters if row.school_id == team2_id],
    }
    pitcher_by_school = {
        team1_id: [row for row in pitchers if row.school_id == team1_id],
        team2_id: [row for row in pitchers if row.school_id == team2_id],
    }

    for school_id, opponent_id in (
        (team1_id, team2_id),
        (team2_id, team1_id),
    ):
        team = team_by_id[school_id]
        batter_rows = batter_by_school[school_id]
        opponent_pitchers = pitcher_by_school[opponent_id]

        if sum(row.runs for row in batter_rows) != team.runs:
            raise ValueError(
                f"match result: {school_id} batter runs mismatch"
            )
        if sum(row.hits for row in batter_rows) != team.hits:
            raise ValueError(
                f"match result: {school_id} batter hits mismatch"
            )
        plate_appearances = sum(
            row.plate_appearances for row in batter_rows
        )
        opponent_bf = sum(
            row.batters_faced for row in opponent_pitchers
        )
        if plate_appearances != opponent_bf:
            raise ValueError(
                f"match result: {school_id} PA != opponent BF"
            )
        if sum(
            row.runs_allowed for row in opponent_pitchers
        ) != team.runs:
            raise ValueError(
                f"match result: {school_id} runs != opponent pitcher runs"
            )
        if sum(
            row.hits_allowed for row in opponent_pitchers
        ) != team.hits:
            raise ValueError(
                f"match result: {school_id} hits != opponent pitcher hits"
            )


def result_score_pair(
    result: MatchSimulationResult,
) -> tuple[int, int]:
    if result.score_source != SCORE_SOURCE_ABILITY_MODEL_V1:
        raise ValueError(
            "match result: score_source must be ability_model_v1"
        )
    return result.team1_score, result.team2_score
