from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean
from typing import Iterable, Iterator

from phase2_engine.repository import DataRepository

from .abilities import PlayerAbilityGenerator, PlayerAbilitySnapshot
from .ability_config import ConfigDocument, load_and_validate_ability_configs
from .players import PlayerRosterGenerator

STARTING_POSITIONS = ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
TEAM_STRENGTH_METRICS = (
    "batting_strength",
    "contact_strength",
    "power_strength",
    "discipline_strength",
    "running_strength",
    "defense_strength",
    "ace_strength",
    "pitching_depth_strength",
    "bullpen_strength",
    "pitching_strength",
)


@dataclass(frozen=True)
class LineupEntry:
    batting_order: int
    defensive_position: str
    player_id: str
    selection_score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StartingLineup:
    school_id: str
    reference_year: int
    entries: tuple[LineupEntry, ...]

    @property
    def starter_ids(self) -> tuple[str, ...]:
        return tuple(entry.player_id for entry in self.entries)

    def player_for_position(self, position: str) -> str:
        for entry in self.entries:
            if entry.defensive_position == position:
                return entry.player_id
        raise KeyError(position)

    def to_dict(self) -> dict:
        return {
            "school_id": self.school_id,
            "reference_year": self.reference_year,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class PitchingStaffEntry:
    order: int
    role: str
    player_id: str
    quality: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PitchingStaff:
    school_id: str
    reference_year: int
    entries: tuple[PitchingStaffEntry, ...]

    @property
    def ace_player_id(self) -> str:
        return self.entries[0].player_id

    def to_dict(self) -> dict:
        return {
            "school_id": self.school_id,
            "reference_year": self.reference_year,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class TeamStrengthSnapshot:
    school_id: str
    reference_year: int
    generation_seed: int
    roster_size: int

    team_config_id: str
    team_config_revision: int
    team_config_sha256: str
    player_generation_sha256: str

    starting_lineup: StartingLineup
    pitching_staff: PitchingStaff

    batting_strength: float
    contact_strength: float
    power_strength: float
    discipline_strength: float
    running_strength: float
    defense_strength: float
    ace_strength: float
    pitching_depth_strength: float
    bullpen_strength: float
    pitching_strength: float

    school_intake_config_id: str | None = None
    school_intake_config_revision: int | None = None
    school_intake_config_sha256: str | None = None

    def to_dict(self) -> dict:
        out = asdict(self)
        out["starting_lineup"] = self.starting_lineup.to_dict()
        out["pitching_staff"] = self.pitching_staff.to_dict()
        return out


def _round_strength(value: float) -> float:
    return round(min(100.0, max(1.0, float(value))), 2)


def _weighted(values: dict[str, float], weights: dict[str, float]) -> float:
    return sum(float(values[key]) * float(weight) for key, weight in weights.items())


class TeamStrengthGenerator:
    def __init__(self, config_dir: str | Path = "config/abilities"):
        self.config_dir = Path(config_dir)
        self.configs = load_and_validate_ability_configs(self.config_dir)
        self.team_config = self.configs["team_strength_v1"]
        self.params = self.team_config.payload

    @staticmethod
    def _config_fields(document: ConfigDocument) -> tuple[str, int, str]:
        return (
            document.config_id,
            document.revision,
            document.canonical_sha256,
        )

    def _batting_composite(self, player: PlayerAbilitySnapshot) -> float:
        weights = dict(self.params["batting"]["lineup_weights"])
        weights.pop("bench_depth", None)
        denominator = sum(float(value) for value in weights.values())
        if denominator <= 0:
            raise ValueError("batting lineup weights must have positive player weight")
        values = {
            ability_id: float(player.ability(ability_id))
            for ability_id in weights
        }
        return _weighted(values, weights) / denominator

    def _running_composite(self, player: PlayerAbilitySnapshot) -> float:
        weights = self.params["running"]["weights"]
        values = {
            ability_id: float(player.ability(ability_id))
            for ability_id in weights
        }
        return _weighted(values, weights)

    def _defense_composite(
        self,
        player: PlayerAbilitySnapshot,
        position: str,
    ) -> float:
        if (
            position == "C"
            and self.params["defense"]["catcher_override"]["enabled"]
        ):
            weights = self.params["defense"]["catcher_override"]["weights"]
        else:
            weights = self.params["defense"]["player_formula_weights"]

        values: dict[str, float] = {}
        for ability_id in weights:
            if ability_id == "position_aptitude":
                values[ability_id] = float(player.aptitude(position))
            else:
                value = player.ability(ability_id)
                if value is None:
                    raise ValueError(
                        f"{player.player_id}: {ability_id} required for {position}"
                    )
                values[ability_id] = float(value)
        return _weighted(values, weights)

    @staticmethod
    def _velocity_component(velocity_kmh: int | None) -> float:
        if velocity_kmh is None:
            raise ValueError("pitcher velocity is required")
        return min(
            100.0,
            max(1.0, 1.0 + (float(velocity_kmh) - 100.0) * 99.0 / 65.0),
        )

    def _pitcher_quality(self, player: PlayerAbilitySnapshot) -> float:
        if player.primary_position != "P":
            raise ValueError(f"{player.player_id}: pitcher quality requires P")
        weights = self.params["pitching"]["pitcher_quality_weights"]
        values: dict[str, float] = {
            "velocity_component": self._velocity_component(player.velocity_kmh)
        }
        for ability_id in weights:
            if ability_id == "velocity_component":
                continue
            value = player.ability(ability_id)
            if value is None:
                raise ValueError(
                    f"{player.player_id}: pitcher ability {ability_id} is required"
                )
            values[ability_id] = float(value)
        return _weighted(values, weights)

    def _selection_score(
        self,
        player: PlayerAbilitySnapshot,
        position: str,
    ) -> float:
        if position == "P":
            return self._pitcher_quality(player)

        batting = self._batting_composite(player)
        defense = self._defense_composite(player, position)
        if position == "C":
            weights = self.params["selection"]["catcher_weights"]
            return (
                batting * float(weights["batting"])
                + defense * float(weights["defense"])
            )

        running = self._running_composite(player)
        weights = self.params["selection"]["position_player_weights"]
        return (
            batting * float(weights["batting"])
            + defense * float(weights["defense"])
            + running * float(weights["running"])
        )

    def _batting_order_score(self, player: PlayerAbilitySnapshot) -> float:
        weights = self.params["selection"]["batting_order_weights"]
        values = {
            ability_id: float(player.ability(ability_id))
            for ability_id in weights
        }
        return _weighted(values, weights)

    def select_starting_lineup(
        self,
        snapshots: Iterable[PlayerAbilitySnapshot],
    ) -> StartingLineup:
        players = list(snapshots)
        school_id, reference_year, *_ = self._validate_source(players)

        by_position = {
            position: [
                player
                for player in players
                if player.primary_position == position
            ]
            for position in STARTING_POSITIONS
        }
        missing = [
            position for position, pool in by_position.items() if not pool
        ]
        if missing:
            raise ValueError(
                f"{school_id}: missing primary-position candidates {missing}"
            )

        chosen: list[tuple[str, PlayerAbilitySnapshot, float]] = []
        for position in STARTING_POSITIONS:
            ranked = sorted(
                by_position[position],
                key=lambda player: (
                    -self._selection_score(player, position),
                    player.player_id,
                ),
            )
            player = ranked[0]
            chosen.append(
                (
                    position,
                    player,
                    self._selection_score(player, position),
                )
            )

        ordered = sorted(
            chosen,
            key=lambda item: (
                -self._batting_order_score(item[1]),
                item[1].player_id,
            ),
        )
        batting_order = {
            player.player_id: index
            for index, (_, player, _) in enumerate(ordered, start=1)
        }
        entries = tuple(
            LineupEntry(
                batting_order=batting_order[player.player_id],
                defensive_position=position,
                player_id=player.player_id,
                selection_score=round(score, 4),
            )
            for position, player, score in chosen
        )
        lineup = StartingLineup(
            school_id=school_id,
            reference_year=reference_year,
            entries=entries,
        )
        validate_starting_lineup(lineup)
        return lineup

    def select_pitching_staff(
        self,
        snapshots: Iterable[PlayerAbilitySnapshot],
    ) -> PitchingStaff:
        players = list(snapshots)
        school_id, reference_year, _, _ = self._validate_source(players)
        pitchers = [
            player for player in players if player.primary_position == "P"
        ]
        if len(pitchers) < 3:
            raise ValueError(f"{school_id}: at least three pitchers are required")

        ranked = sorted(
            pitchers,
            key=lambda player: (
                -self._pitcher_quality(player),
                player.player_id,
            ),
        )
        role_names = ("ace", "second", "third")
        entries: list[PitchingStaffEntry] = []
        for index, player in enumerate(ranked, start=1):
            role = (
                role_names[index - 1]
                if index <= len(role_names)
                else f"depth_{index - len(role_names)}"
            )
            entries.append(
                PitchingStaffEntry(
                    order=index,
                    role=role,
                    player_id=player.player_id,
                    quality=round(self._pitcher_quality(player), 4),
                )
            )

        staff = PitchingStaff(
            school_id=school_id,
            reference_year=reference_year,
            entries=tuple(entries),
        )
        validate_pitching_staff(staff)
        return staff

    def generate(
        self,
        snapshots: Iterable[PlayerAbilitySnapshot],
    ) -> TeamStrengthSnapshot:
        players = list(snapshots)
        (
            school_id,
            reference_year,
            generation_seed,
            generation_sha,
            intake_config_id,
            intake_config_revision,
            intake_config_sha,
        ) = self._validate_source(players)
        lineup = self.select_starting_lineup(players)
        staff = self.select_pitching_staff(players)
        by_id = {player.player_id: player for player in players}
        starters = [by_id[player_id] for player_id in lineup.starter_ids]

        contact_strength = fmean(
            float(player.contact) for player in starters
        )
        power_strength = fmean(
            float(player.power) for player in starters
        )
        plate_discipline = fmean(
            float(player.plate_discipline) for player in starters
        )
        strikeout_resistance = fmean(
            float(player.strikeout_resistance) for player in starters
        )
        speed_strength = fmean(
            float(player.speed) for player in starters
        )

        starter_ids = set(lineup.starter_ids)
        nonstarters = [
            player
            for player in players
            if player.player_id not in starter_ids
        ]
        bench_weights = self.params["batting"]["bench_depth"][
            "composite_weights"
        ]
        bench_ranked = sorted(
            nonstarters,
            key=lambda player: (
                -_weighted(
                    {
                        ability_id: float(player.ability(ability_id))
                        for ability_id in bench_weights
                    },
                    bench_weights,
                ),
                player.player_id,
            ),
        )
        if len(bench_ranked) < 3:
            raise ValueError(
                f"{school_id}: at least three bench players are required"
            )
        bench_depth = fmean(
            _weighted(
                {
                    ability_id: float(player.ability(ability_id))
                    for ability_id in bench_weights
                },
                bench_weights,
            )
            for player in bench_ranked[:3]
        )

        batting_values = {
            "contact": contact_strength,
            "power": power_strength,
            "plate_discipline": plate_discipline,
            "strikeout_resistance": strikeout_resistance,
            "speed": speed_strength,
            "bench_depth": bench_depth,
        }
        batting_strength = _weighted(
            batting_values,
            self.params["batting"]["lineup_weights"],
        )

        discipline_strength = (
            plate_discipline + strikeout_resistance
        ) / 2.0
        running_strength = fmean(
            self._running_composite(player) for player in starters
        )

        importance = self.params["defense"]["position_importance"]
        defense_numerator = 0.0
        defense_denominator = 0.0
        for entry in lineup.entries:
            position = entry.defensive_position
            if position == "P":
                continue
            player = by_id[entry.player_id]
            weight = float(importance[position])
            defense_numerator += (
                self._defense_composite(player, position) * weight
            )
            defense_denominator += weight
        if defense_denominator <= 0:
            raise ValueError(
                "defense position importance must be positive"
            )
        defense_strength = defense_numerator / defense_denominator

        qualities = [entry.quality for entry in staff.entries]
        remaining_depth = (
            fmean(qualities[3:])
            if len(qualities) > 3
            else qualities[-1]
        )
        staff_values = {
            "ace": qualities[0],
            "second": qualities[1],
            "third": qualities[2],
            "remaining_depth": remaining_depth,
        }
        pitching_strength = _weighted(
            staff_values,
            self.params["pitching"]["staff_weights"],
        )
        non_ace_weight = sum(
            float(weight)
            for role, weight in self.params["pitching"][
                "staff_weights"
            ].items()
            if role != "ace"
        )
        if non_ace_weight <= 0:
            raise ValueError(
                "pitching non-ace staff weight must be positive"
            )
        pitching_depth_strength = (
            sum(
                staff_values[role] * float(weight)
                for role, weight in self.params["pitching"][
                    "staff_weights"
                ].items()
                if role != "ace"
            )
            / non_ace_weight
        )
        bullpen_strength = fmean(qualities[2:])

        config_id, config_revision, config_sha = self._config_fields(
            self.team_config
        )
        snapshot = TeamStrengthSnapshot(
            school_id=school_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            roster_size=len(players),
            team_config_id=config_id,
            team_config_revision=config_revision,
            team_config_sha256=config_sha,
            player_generation_sha256=generation_sha,
            starting_lineup=lineup,
            pitching_staff=staff,
            batting_strength=_round_strength(batting_strength),
            contact_strength=_round_strength(contact_strength),
            power_strength=_round_strength(power_strength),
            discipline_strength=_round_strength(discipline_strength),
            running_strength=_round_strength(running_strength),
            defense_strength=_round_strength(defense_strength),
            ace_strength=_round_strength(qualities[0]),
            pitching_depth_strength=_round_strength(
                pitching_depth_strength
            ),
            bullpen_strength=_round_strength(bullpen_strength),
            pitching_strength=_round_strength(pitching_strength),
            school_intake_config_id=intake_config_id,
            school_intake_config_revision=intake_config_revision,
            school_intake_config_sha256=intake_config_sha,
        )
        validate_team_strength_snapshot(snapshot)
        return snapshot

    @staticmethod
    def _validate_source(
        players: list[PlayerAbilitySnapshot],
    ) -> tuple[
        str,
        int,
        int,
        str,
        str | None,
        int | None,
        str | None,
    ]:
        if len(players) < 12:
            raise ValueError(
                "team strength requires at least 12 player snapshots"
            )
        school_ids = {player.school_id for player in players}
        years = {player.reference_year for player in players}
        seeds = {player.generation_seed for player in players}
        generation_shas = {
            player.generation_sha256 for player in players
        }
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
        player_ids = [player.player_id for player in players]
        if len(school_ids) != 1:
            raise ValueError(
                "player snapshots must belong to one school"
            )
        if len(years) != 1:
            raise ValueError(
                "player snapshots must share reference_year"
            )
        if len(seeds) != 1:
            raise ValueError(
                "player snapshots must share generation_seed"
            )
        if len(generation_shas) != 1:
            raise ValueError(
                "player snapshots must share generation config"
            )
        if (
            len(intake_ids) != 1
            or len(intake_revisions) != 1
            or len(intake_shas) != 1
        ):
            raise ValueError(
                "player snapshots must share school intake config"
            )
        if len(player_ids) != len(set(player_ids)):
            raise ValueError(
                "duplicate player_id in team strength input"
            )
        return (
            next(iter(school_ids)),
            next(iter(years)),
            next(iter(seeds)),
            next(iter(generation_shas)),
            next(iter(intake_ids)),
            next(iter(intake_revisions)),
            next(iter(intake_shas)),
        )

    def iter_all_schools(
        self,
        repo: DataRepository,
        reference_year: int,
        base_seed: int,
        *,
        roster_generator: PlayerRosterGenerator | None = None,
        ability_generator: PlayerAbilityGenerator | None = None,
    ) -> Iterator[TeamStrengthSnapshot]:
        roster_generator = (
            roster_generator or PlayerRosterGenerator()
        )
        if ability_generator is None:
            from .school_intake import SchoolAwarePlayerAbilityGenerator

            ability_generator = SchoolAwarePlayerAbilityGenerator(
                self.config_dir
            )
        for roster in roster_generator.iter_all_rosters(
            repo,
            reference_year,
            base_seed,
        ):
            abilities = list(
                ability_generator.iter_roster(
                    roster.players,
                    reference_year,
                    base_seed,
                )
            )
            yield self.generate(abilities)


def validate_starting_lineup(lineup: StartingLineup) -> None:
    if len(lineup.entries) != 9:
        raise ValueError(
            f"{lineup.school_id}: starting lineup must contain 9 players"
        )
    positions = [
        entry.defensive_position for entry in lineup.entries
    ]
    if set(positions) != set(STARTING_POSITIONS):
        raise ValueError(
            f"{lineup.school_id}: starting positions mismatch"
        )
    player_ids = [entry.player_id for entry in lineup.entries]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError(
            f"{lineup.school_id}: duplicate starter"
        )
    orders = sorted(
        entry.batting_order for entry in lineup.entries
    )
    if orders != list(range(1, 10)):
        raise ValueError(
            f"{lineup.school_id}: batting order must be 1..9"
        )


def validate_pitching_staff(staff: PitchingStaff) -> None:
    if len(staff.entries) < 3:
        raise ValueError(
            f"{staff.school_id}: pitching staff requires at least 3 pitchers"
        )
    orders = [entry.order for entry in staff.entries]
    if orders != list(range(1, len(staff.entries) + 1)):
        raise ValueError(
            f"{staff.school_id}: pitching staff order mismatch"
        )
    player_ids = [entry.player_id for entry in staff.entries]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError(
            f"{staff.school_id}: duplicate pitcher"
        )
    qualities = [entry.quality for entry in staff.entries]
    if any(
        not 1.0 <= value <= 100.0
        for value in qualities
    ):
        raise ValueError(
            f"{staff.school_id}: pitching quality out of range"
        )
    if qualities != sorted(qualities, reverse=True):
        raise ValueError(
            f"{staff.school_id}: pitching staff must be quality ordered"
        )
    if staff.entries[0].role != "ace":
        raise ValueError(
            f"{staff.school_id}: first pitcher must be ace"
        )


def validate_team_strength_snapshot(
    snapshot: TeamStrengthSnapshot,
) -> None:
    if snapshot.roster_size < 12:
        raise ValueError(
            f"{snapshot.school_id}: roster_size too small"
        )
    validate_starting_lineup(snapshot.starting_lineup)
    validate_pitching_staff(snapshot.pitching_staff)
    if snapshot.starting_lineup.school_id != snapshot.school_id:
        raise ValueError(
            "starting lineup school_id mismatch"
        )
    if snapshot.pitching_staff.school_id != snapshot.school_id:
        raise ValueError(
            "pitching staff school_id mismatch"
        )
    lineup_pitcher = snapshot.starting_lineup.player_for_position(
        "P"
    )
    if lineup_pitcher != snapshot.pitching_staff.ace_player_id:
        raise ValueError(
            f"{snapshot.school_id}: lineup pitcher must match pitching staff ace"
        )
    for metric in TEAM_STRENGTH_METRICS:
        value = getattr(snapshot, metric)
        if not 1.0 <= value <= 100.0:
            raise ValueError(
                f"{snapshot.school_id}: invalid {metric}={value}"
            )


def write_team_strength_csv(
    snapshots: Iterable[TeamStrengthSnapshot],
    path: str | Path,
) -> dict:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "school_id",
        "reference_year",
        "generation_seed",
        "roster_size",
        "team_config_id",
        "team_config_revision",
        "team_config_sha256",
        "player_generation_sha256",
        "school_intake_config_id",
        "school_intake_config_revision",
        "school_intake_config_sha256",
        *TEAM_STRENGTH_METRICS,
        "starting_lineup_json",
        "pitching_staff_json",
    ]
    count = 0
    with output.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        for snapshot in snapshots:
            validate_team_strength_snapshot(snapshot)
            row = {
                key: getattr(snapshot, key)
                for key in fieldnames
                if hasattr(snapshot, key)
            }
            row["starting_lineup_json"] = json.dumps(
                snapshot.starting_lineup.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
            )
            row["pitching_staff_json"] = json.dumps(
                snapshot.pitching_staff.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
            )
            writer.writerow(row)
            count += 1
    return {
        "team_count": count,
        "output": str(output),
    }
