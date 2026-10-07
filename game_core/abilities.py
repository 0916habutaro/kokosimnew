from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator

from phase2_engine.randomness import rng_for

from .ability_config import ConfigDocument, load_and_validate_ability_configs
from .players import Player, PlayerRosterGenerator
from phase2_engine.repository import DataRepository


FIELD_POSITIONS = ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
BATTER_ABILITIES = (
    "contact",
    "power",
    "plate_discipline",
    "strikeout_resistance",
    "bunt",
    "speed",
    "baserunning",
    "stealing",
    "arm_strength",
    "fielding",
    "throwing",
)
CATCHER_ABILITIES = ("catching", "game_calling")
PITCHER_ABILITIES = (
    "velocity_kmh",
    "control",
    "stamina",
    "stuff",
    "strikeout",
    "groundball",
    "composure",
)


@dataclass(frozen=True)
class PitchAbility:
    pitch_type: str
    quality: int
    command: int
    usage: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PlayerAbilitySnapshot:
    player_id: str
    school_id: str
    reference_year: int
    academic_year: int
    primary_position: str
    generation_seed: int

    catalog_config_id: str
    catalog_revision: int
    catalog_sha256: str
    scale_config_id: str
    scale_revision: int
    scale_sha256: str
    generation_config_id: str
    generation_revision: int
    generation_sha256: str

    contact: int
    power: int
    plate_discipline: int
    strikeout_resistance: int
    bunt: int
    speed: int
    baserunning: int
    stealing: int
    arm_strength: int
    fielding: int
    throwing: int

    catching: int | None
    game_calling: int | None

    velocity_kmh: int | None
    control: int | None
    stamina: int | None
    stuff: int | None
    strikeout: int | None
    groundball: int | None
    composure: int | None

    position_aptitude: tuple[tuple[str, int], ...]
    pitch_repertoire: tuple[PitchAbility, ...]

    def to_dict(self) -> dict:
        out = asdict(self)
        out["position_aptitude"] = dict(self.position_aptitude)
        out["pitch_repertoire"] = [
            pitch.to_dict() for pitch in self.pitch_repertoire
        ]
        return out

    def ability(self, ability_id: str) -> int | None:
        if ability_id == "position_aptitude":
            raise ValueError(
                "position_aptitude is position-specific; use aptitude(position)"
            )
        if ability_id == "pitch_repertoire":
            raise ValueError(
                "pitch_repertoire is structured; use pitch_repertoire"
            )
        if not hasattr(self, ability_id):
            raise KeyError(ability_id)
        return getattr(self, ability_id)

    def aptitude(self, position: str) -> int:
        values = dict(self.position_aptitude)
        if position not in values:
            raise KeyError(position)
        return values[position]


def _clamp_round(value: float, low: int, high: int) -> int:
    return min(high, max(low, int(round(value))))


def _normalized_usage_weights(
    pitch_types: list[str],
    *,
    base_seed: int,
    namespace_template: str,
    reference_year: int,
    player_id: str,
) -> list[int]:
    if not pitch_types:
        return []

    raw: list[float] = []
    for pitch_type in pitch_types:
        namespace = namespace_template.format(
            reference_year=reference_year,
            player_id=player_id,
            pitch_type=pitch_type,
        )
        raw.append(max(1e-12, rng_for(base_seed, namespace + ":usage").random()))

    available = 100 - len(pitch_types)
    total = sum(raw)
    exact = [value / total * available for value in raw]
    floor_values = [math.floor(value) for value in exact]
    usages = [1 + value for value in floor_values]
    leftover = 100 - sum(usages)

    remainders = sorted(
        range(len(pitch_types)),
        key=lambda index: (
            -(exact[index] - floor_values[index]),
            pitch_types[index],
        ),
    )
    for index in remainders[:leftover]:
        usages[index] += 1

    if sum(usages) != 100 or min(usages) < 1:
        raise AssertionError("pitch usage normalization failed")
    return usages


class PlayerAbilityGenerator:
    def __init__(self, config_dir: str | Path = "config/abilities"):
        self.configs = load_and_validate_ability_configs(config_dir)
        self.catalog = self.configs["ability_catalog_v1"]
        self.scale = self.configs["ability_scale_v1"]
        self.generation = self.configs["player_generation_v1"]
        self.params = self.generation.payload

    @staticmethod
    def _config_fields(
        document: ConfigDocument,
    ) -> tuple[str, int, str]:
        return (
            document.config_id,
            document.revision,
            document.canonical_sha256,
        )

    def _scalar(
        self,
        player: Player,
        reference_year: int,
        base_seed: int,
        ability_id: str,
        params: dict,
        *,
        grade_adjustment: dict | None = None,
    ) -> int:
        defaults = self.params["scalar_defaults"]
        mean = float(params.get("mean", defaults["mean"]))
        stddev = float(params.get("stddev", defaults["stddev"]))
        low = int(params.get("min", defaults["min"]))
        high = int(params.get("max", defaults["max"]))

        grade_map = (
            grade_adjustment
            if grade_adjustment is not None
            else self.params["grade_adjustment"]
        )
        mean += float(grade_map[str(player.academic_year)])

        namespace = self.params["rng_namespace_policy"][
            "scalar_ability"
        ].format(
            reference_year=reference_year,
            player_id=player.player_id,
            ability_id=ability_id,
        )
        value = rng_for(base_seed, namespace).gauss(mean, stddev)
        return _clamp_round(value, low, high)

    def _position_aptitudes(
        self,
        player: Player,
        reference_year: int,
        base_seed: int,
    ) -> tuple[tuple[str, int], ...]:
        policy = self.params["rng_namespace_policy"]["position_aptitude"]
        settings = self.params["position_aptitude"]
        out: list[tuple[str, int]] = []
        for position in FIELD_POSITIONS:
            source = (
                settings["primary"]
                if position == player.primary_position
                else settings["untrained"]
            )
            namespace = policy.format(
                reference_year=reference_year,
                player_id=player.player_id,
                position=position,
            )
            value = rng_for(base_seed, namespace).gauss(
                float(source["mean"]),
                float(source["stddev"]),
            )
            out.append(
                (
                    position,
                    _clamp_round(
                        value,
                        int(source["min"]),
                        int(source["max"]),
                    ),
                )
            )
        return tuple(out)

    def _pitch_repertoire(
        self,
        player: Player,
        reference_year: int,
        base_seed: int,
    ) -> tuple[PitchAbility, ...]:
        if player.primary_position != "P":
            return ()

        settings = self.params["pitch_repertoire"]
        count_settings = settings["pitch_count"]
        latent_template = self.params["rng_namespace_policy"]["latent_trait"]
        count_namespace = latent_template.format(
            reference_year=reference_year,
            player_id=player.player_id,
            trait_id="pitch_count",
        )
        count = rng_for(base_seed, count_namespace).randint(
            int(count_settings["min"]),
            int(count_settings["max"]),
        )

        all_types = list(settings["pitch_types"])
        mandatory = ["four_seam"] if "four_seam" in all_types else []
        remaining = [
            pitch_type for pitch_type in all_types
            if pitch_type not in mandatory
        ]
        select_namespace = latent_template.format(
            reference_year=reference_year,
            player_id=player.player_id,
            trait_id="pitch_types",
        )
        selected = mandatory + rng_for(
            base_seed,
            select_namespace,
        ).sample(
            remaining,
            k=max(0, count - len(mandatory)),
        )

        pitch_template = self.params["rng_namespace_policy"][
            "pitch_repertoire"
        ]
        field_params = settings["per_pitch_fields"]
        usages = _normalized_usage_weights(
            selected,
            base_seed=base_seed,
            namespace_template=pitch_template,
            reference_year=reference_year,
            player_id=player.player_id,
        )

        out: list[PitchAbility] = []
        for pitch_type, usage in zip(selected, usages):
            base_namespace = pitch_template.format(
                reference_year=reference_year,
                player_id=player.player_id,
                pitch_type=pitch_type,
            )
            quality_params = field_params["quality"]
            command_params = field_params["command"]
            quality = _clamp_round(
                rng_for(base_seed, base_namespace + ":quality").gauss(
                    float(quality_params["mean"]),
                    float(quality_params["stddev"]),
                ),
                int(quality_params["min"]),
                int(quality_params["max"]),
            )
            command = _clamp_round(
                rng_for(base_seed, base_namespace + ":command").gauss(
                    float(command_params["mean"]),
                    float(command_params["stddev"]),
                ),
                int(command_params["min"]),
                int(command_params["max"]),
            )
            out.append(
                PitchAbility(
                    pitch_type=pitch_type,
                    quality=quality,
                    command=command,
                    usage=usage,
                )
            )
        return tuple(out)

    def generate(
        self,
        player: Player,
        reference_year: int,
        base_seed: int,
    ) -> PlayerAbilitySnapshot:
        batter = {
            ability_id: self._scalar(
                player,
                reference_year,
                base_seed,
                ability_id,
                self.params["batter_abilities"][ability_id],
            )
            for ability_id in BATTER_ABILITIES
        }

        catcher: dict[str, int | None] = {
            ability_id: None for ability_id in CATCHER_ABILITIES
        }
        if player.primary_position == "C":
            catcher = {
                ability_id: self._scalar(
                    player,
                    reference_year,
                    base_seed,
                    ability_id,
                    self.params["catcher_only_abilities"][ability_id],
                )
                for ability_id in CATCHER_ABILITIES
            }

        pitcher: dict[str, int | None] = {
            ability_id: None for ability_id in PITCHER_ABILITIES
        }
        if player.primary_position == "P":
            pitcher = {}
            for ability_id in PITCHER_ABILITIES:
                params = self.params["pitcher_abilities"][ability_id]
                pitcher[ability_id] = self._scalar(
                    player,
                    reference_year,
                    base_seed,
                    ability_id,
                    params,
                    grade_adjustment=params.get("grade_adjustment"),
                )

        catalog_id, catalog_rev, catalog_sha = self._config_fields(
            self.catalog
        )
        scale_id, scale_rev, scale_sha = self._config_fields(self.scale)
        generation_id, generation_rev, generation_sha = self._config_fields(
            self.generation
        )

        snapshot = PlayerAbilitySnapshot(
            player_id=player.player_id,
            school_id=player.school_id,
            reference_year=reference_year,
            academic_year=player.academic_year,
            primary_position=player.primary_position,
            generation_seed=base_seed,
            catalog_config_id=catalog_id,
            catalog_revision=catalog_rev,
            catalog_sha256=catalog_sha,
            scale_config_id=scale_id,
            scale_revision=scale_rev,
            scale_sha256=scale_sha,
            generation_config_id=generation_id,
            generation_revision=generation_rev,
            generation_sha256=generation_sha,
            **batter,
            **catcher,
            **pitcher,
            position_aptitude=self._position_aptitudes(
                player,
                reference_year,
                base_seed,
            ),
            pitch_repertoire=self._pitch_repertoire(
                player,
                reference_year,
                base_seed,
            ),
        )
        validate_ability_snapshot(snapshot)
        return snapshot

    def iter_roster(
        self,
        players: Iterable[Player],
        reference_year: int,
        base_seed: int,
    ) -> Iterator[PlayerAbilitySnapshot]:
        for player in players:
            yield self.generate(player, reference_year, base_seed)

    def iter_all_schools(
        self,
        repo: DataRepository,
        reference_year: int,
        base_seed: int,
        *,
        roster_generator: PlayerRosterGenerator | None = None,
    ) -> Iterator[PlayerAbilitySnapshot]:
        roster_generator = roster_generator or PlayerRosterGenerator()
        for roster in roster_generator.iter_all_rosters(
            repo,
            reference_year,
            base_seed,
        ):
            yield from self.iter_roster(
                roster.players,
                reference_year,
                base_seed,
            )


def validate_ability_snapshot(snapshot: PlayerAbilitySnapshot) -> None:
    for ability_id in BATTER_ABILITIES:
        value = snapshot.ability(ability_id)
        if value is None or not 1 <= value <= 100:
            raise ValueError(
                f"{snapshot.player_id}: invalid {ability_id}={value}"
            )

    is_catcher = snapshot.primary_position == "C"
    for ability_id in CATCHER_ABILITIES:
        value = snapshot.ability(ability_id)
        if is_catcher:
            if value is None or not 1 <= value <= 100:
                raise ValueError(
                    f"{snapshot.player_id}: invalid {ability_id}={value}"
                )
        elif value is not None:
            raise ValueError(
                f"{snapshot.player_id}: non-catcher has {ability_id}"
            )

    is_pitcher = snapshot.primary_position == "P"
    for ability_id in PITCHER_ABILITIES:
        value = snapshot.ability(ability_id)
        if is_pitcher:
            low, high = (100, 165) if ability_id == "velocity_kmh" else (1, 100)
            if value is None or not low <= value <= high:
                raise ValueError(
                    f"{snapshot.player_id}: invalid {ability_id}={value}"
                )
        elif value is not None:
            raise ValueError(
                f"{snapshot.player_id}: non-pitcher has {ability_id}"
            )

    aptitudes = dict(snapshot.position_aptitude)
    if set(aptitudes) != set(FIELD_POSITIONS):
        raise ValueError(
            f"{snapshot.player_id}: position aptitude keys mismatch"
        )
    if not all(1 <= value <= 100 for value in aptitudes.values()):
        raise ValueError(
            f"{snapshot.player_id}: invalid position aptitude"
        )
    if aptitudes[snapshot.primary_position] < 60:
        raise ValueError(
            f"{snapshot.player_id}: primary aptitude below 60"
        )

    repertoire = snapshot.pitch_repertoire
    if is_pitcher:
        if not 2 <= len(repertoire) <= 4:
            raise ValueError(
                f"{snapshot.player_id}: invalid pitch count {len(repertoire)}"
            )
        if "four_seam" not in {pitch.pitch_type for pitch in repertoire}:
            raise ValueError(
                f"{snapshot.player_id}: four_seam is required"
            )
        if sum(pitch.usage for pitch in repertoire) != 100:
            raise ValueError(
                f"{snapshot.player_id}: pitch usage must sum to 100"
            )
        if len({pitch.pitch_type for pitch in repertoire}) != len(repertoire):
            raise ValueError(
                f"{snapshot.player_id}: duplicate pitch type"
            )
        for pitch in repertoire:
            if not 1 <= pitch.quality <= 100:
                raise ValueError(
                    f"{snapshot.player_id}: invalid pitch quality"
                )
            if not 1 <= pitch.command <= 100:
                raise ValueError(
                    f"{snapshot.player_id}: invalid pitch command"
                )
            if not 1 <= pitch.usage <= 100:
                raise ValueError(
                    f"{snapshot.player_id}: invalid pitch usage"
                )
    elif repertoire:
        raise ValueError(
            f"{snapshot.player_id}: non-pitcher has pitch repertoire"
        )


def write_ability_snapshots_csv(
    snapshots: Iterable[PlayerAbilitySnapshot],
    path: str | Path,
) -> dict:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    scalar_fields = [
        *BATTER_ABILITIES,
        *CATCHER_ABILITIES,
        *PITCHER_ABILITIES,
    ]
    fieldnames = [
        "player_id",
        "school_id",
        "reference_year",
        "academic_year",
        "primary_position",
        "generation_seed",
        "catalog_config_id",
        "catalog_revision",
        "catalog_sha256",
        "scale_config_id",
        "scale_revision",
        "scale_sha256",
        "generation_config_id",
        "generation_revision",
        "generation_sha256",
        *scalar_fields,
        "position_aptitude_json",
        "pitch_repertoire_json",
    ]

    count = 0
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for snapshot in snapshots:
            validate_ability_snapshot(snapshot)
            row = {
                key: getattr(snapshot, key)
                for key in fieldnames
                if hasattr(snapshot, key)
            }
            row["position_aptitude_json"] = json.dumps(
                dict(snapshot.position_aptitude),
                ensure_ascii=False,
                sort_keys=True,
            )
            row["pitch_repertoire_json"] = json.dumps(
                [pitch.to_dict() for pitch in snapshot.pitch_repertoire],
                ensure_ascii=False,
                sort_keys=True,
            )
            writer.writerow(row)
            count += 1

    return {"snapshot_count": count, "output": str(output)}
