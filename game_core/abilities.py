from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, field
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
    "quick",
)


PLATOON_TRAITS = ("vs_left_good", "vs_left_bad")


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
    # クイック（牽制とクイックをまとめたもの。盗塁の成否・牽制死）
    quick: int | None

    position_aptitude: tuple[tuple[str, int], ...]
    pitch_repertoire: tuple[PitchAbility, ...]
    # 投打の左右（Player と同じ。打は R・L・S（両打ち））と、一部の選手だけの左右の
    # 得意・不得意（野手は対左投手、投手は対左打者。PLATOON_TRAITS）
    bats: str = field(default="R", kw_only=True)
    throws: str = field(default="R", kw_only=True)
    platoon_trait: str | None = field(default=None, kw_only=True)

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


def _normalized_usage_weights(raw: list[float]) -> list[int]:
    """球種ごとの乱数（0〜1）から、合計100の投げる割合。"""
    if not raw:
        return []
    pitch_types = list(range(len(raw)))
    raw = [max(1e-12, value) for value in raw]

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

    def player_rng(self, player: Player, reference_year: int, base_seed: int):
        """選手ごとの乱数（1人に1個）。能力はこの列から決まった順に引く。"""
        return rng_for(base_seed, self.params["rng_namespace_policy"]["player"].format(
            reference_year=reference_year, player_id=player.player_id,
        ))

    def _scalar(
        self,
        player: Player,
        rng,
        params: dict,
        *,
        grade_adjustment: dict | None = None,
    ) -> int:
        """``rng`` が None なら乱数を引かず平均（学校ごとの生成で上書きする値）。"""
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
        value = rng.gauss(mean, stddev) if rng is not None else mean
        return _clamp_round(value, low, high)

    def _position_aptitudes(self, player: Player, rng) -> tuple[tuple[str, int], ...]:
        settings = self.params["position_aptitude"]
        out: list[tuple[str, int]] = []
        for position in FIELD_POSITIONS:
            source = (
                settings["primary"]
                if position == player.primary_position
                else settings["untrained"]
            )
            value = rng.gauss(float(source["mean"]), float(source["stddev"]))
            out.append((position, _clamp_round(value, int(source["min"]), int(source["max"]))))
        return tuple(out)

    def _pitch_repertoire(self, player: Player, rng, *, draw_quality: bool = True,
                          ) -> tuple[PitchAbility, ...]:
        """球種。投手でなくても、どの選手も同じ数だけ乱数を引く（守備位置が変わっても、
        このあとに同じ列から引く値が変わらない）。"""
        settings = self.params["pitch_repertoire"]
        count_settings = settings["pitch_count"]
        low, high = int(count_settings["min"]), int(count_settings["max"])
        all_types = list(settings["pitch_types"])
        mandatory = ["four_seam"] if "four_seam" in all_types else []
        remaining = [pitch_type for pitch_type in all_types if pitch_type not in mandatory]
        field_params = settings["per_pitch_fields"]

        count_roll = rng.random()
        order = {pitch_type: rng.random() for pitch_type in remaining}
        usage_roll = {pitch_type: rng.random() for pitch_type in all_types}
        drawn = {}
        for pitch_type in all_types:
            values = []
            for name in ("quality", "command"):
                rule = field_params[name]
                value = (rng.gauss(float(rule["mean"]), float(rule["stddev"]))
                         if draw_quality else float(rule["mean"]))
                values.append(_clamp_round(value, int(rule["min"]), int(rule["max"])))
            drawn[pitch_type] = values
        if player.primary_position != "P":
            return ()

        count = min(high, low + int(count_roll * (high - low + 1)))
        selected = mandatory + sorted(remaining, key=lambda t: (order[t], t))[
            :max(0, count - len(mandatory))]
        usages = _normalized_usage_weights([usage_roll[t] for t in selected])
        return tuple(
            PitchAbility(pitch_type=pitch_type, quality=drawn[pitch_type][0],
                         command=drawn[pitch_type][1], usage=usage)
            for pitch_type, usage in zip(selected, usages)
        )

    def generate(
        self,
        player: Player,
        reference_year: int,
        base_seed: int,
        *,
        rng=None,
        draw_scalars: bool = True,
    ) -> PlayerAbilitySnapshot:
        """``rng`` は選手ごとの乱数（省くと ``player_rng``）。``draw_scalars=False`` なら
        能力の値（打撃・捕手・投手・球種の質と制球）は乱数を引かず平均にする（学校ごとの
        生成が同じ乱数の続きで上書きする）。守備位置の適性・球種と割合は乱数で決める。"""
        rng = rng if rng is not None else self.player_rng(player, reference_year, base_seed)
        scalar_rng = rng if draw_scalars else None
        batter = {
            ability_id: self._scalar(
                player, scalar_rng, self.params["batter_abilities"][ability_id],
            )
            for ability_id in BATTER_ABILITIES
        }

        # 捕手・投手の能力は、その守備位置でなくても引いて捨てる（どの選手も同じ数だけ引く）
        catcher_drawn = {
            ability_id: self._scalar(
                player, scalar_rng, self.params["catcher_only_abilities"][ability_id],
            )
            for ability_id in CATCHER_ABILITIES
        }
        pitcher_drawn = {}
        for ability_id in PITCHER_ABILITIES:
            params = self.params["pitcher_abilities"][ability_id]
            pitcher_drawn[ability_id] = self._scalar(
                player, scalar_rng, params, grade_adjustment=params.get("grade_adjustment"),
            )
        catcher: dict[str, int | None] = (
            catcher_drawn if player.primary_position == "C"
            else {ability_id: None for ability_id in CATCHER_ABILITIES})
        pitcher: dict[str, int | None] = (
            pitcher_drawn if player.primary_position == "P"
            else {ability_id: None for ability_id in PITCHER_ABILITIES})

        # 打撃 → 捕手 → 投手 → 守備位置の適性 → 球種 の順に同じ列から引く
        aptitudes = self._position_aptitudes(player, rng)
        repertoire = self._pitch_repertoire(player, rng, draw_quality=draw_scalars)

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
            bats=player.bats,
            throws=player.throws,
            position_aptitude=aptitudes,
            pitch_repertoire=repertoire,
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
    if snapshot.bats not in ("R", "L", "S") or snapshot.throws not in ("R", "L"):
        raise ValueError(f"{snapshot.player_id}: invalid bats/throws")
    if snapshot.platoon_trait is not None and snapshot.platoon_trait not in PLATOON_TRAITS:
        raise ValueError(f"{snapshot.player_id}: invalid platoon trait")
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
        "intake_config_id",
        "intake_config_revision",
        "intake_config_sha256",
        "intake_program_quality_z",
        "intake_cohort_quality_z",
        "intake_quality_z",
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
