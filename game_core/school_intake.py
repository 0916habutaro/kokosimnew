from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterable, Iterator

from phase2_engine.randomness import rng_for
from phase2_engine.repository import DataRepository

from .abilities import (
    BATTER_ABILITIES,
    CATCHER_ABILITIES,
    PITCHER_ABILITIES,
    PitchAbility,
    PlayerAbilityGenerator,
    PlayerAbilitySnapshot,
    validate_ability_snapshot,
)
from .ability_config import ConfigDocument, load_and_validate_ability_configs
from .players import Player, PlayerRosterGenerator


@dataclass(frozen=True)
class SchoolIntakeProfile:
    school_id: str
    entry_year: int
    generation_seed: int
    intake_config_id: str
    intake_config_revision: int
    intake_config_sha256: str
    program_quality_z: float
    cohort_quality_z: float
    intake_quality_z: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class IntakeAdjustedPlayerAbilitySnapshot(PlayerAbilitySnapshot):
    intake_config_id: str
    intake_config_revision: int
    intake_config_sha256: str
    intake_program_quality_z: float
    intake_cohort_quality_z: float
    intake_quality_z: float


def _clamp_round(value: float, low: int, high: int) -> int:
    return min(high, max(low, int(round(value))))


def _clamp_float(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


class SchoolIntakeModel:
    def __init__(self, config_dir: str | Path = "config/abilities"):
        self.configs = load_and_validate_ability_configs(config_dir)
        self.config = self.configs["school_intake_v1"]
        self.params = self.config.payload

    @staticmethod
    def _config_fields(
        document: ConfigDocument,
    ) -> tuple[str, int, str]:
        return (
            document.config_id,
            document.revision,
            document.canonical_sha256,
        )

    def profile(
        self,
        *,
        school_id: str,
        entry_year: int,
        base_seed: int,
    ) -> SchoolIntakeProfile:
        quality = self.params["quality_model"]
        program = quality["program_component"]
        cohort = quality["cohort_component"]
        namespaces = self.params["rng_namespace_policy"]

        program_namespace = namespaces["program"].format(
            school_id=school_id,
        )
        cohort_namespace = namespaces["cohort"].format(
            school_id=school_id,
            entry_year=entry_year,
        )
        program_z = rng_for(base_seed, program_namespace).gauss(
            float(program["mean"]),
            float(program["stddev"]),
        )
        cohort_z = rng_for(base_seed, cohort_namespace).gauss(
            float(cohort["mean"]),
            float(cohort["stddev"]),
        )
        combined = (
            program_z * float(program["weight"])
            + cohort_z * float(cohort["weight"])
        )
        clip = quality["combined_clip"]
        combined = _clamp_float(
            combined,
            float(clip["min"]),
            float(clip["max"]),
        )

        config_id, revision, config_sha = self._config_fields(self.config)
        return SchoolIntakeProfile(
            school_id=school_id,
            entry_year=entry_year,
            generation_seed=base_seed,
            intake_config_id=config_id,
            intake_config_revision=revision,
            intake_config_sha256=config_sha,
            program_quality_z=round(program_z, 6),
            cohort_quality_z=round(cohort_z, 6),
            intake_quality_z=round(combined, 6),
        )


class SchoolAwarePlayerAbilityGenerator:
    def __init__(self, config_dir: str | Path = "config/abilities"):
        self.config_dir = Path(config_dir)
        self.base_generator = PlayerAbilityGenerator(self.config_dir)
        self.intake_model = SchoolIntakeModel(self.config_dir)
        self.params = self.intake_model.params

    def _adjust_scalar(
        self,
        value: int | None,
        *,
        adjustment_per_z: float,
        quality_z: float,
        low: int = 1,
        high: int = 100,
    ) -> int | None:
        if value is None:
            return None
        return _clamp_round(
            float(value) + adjustment_per_z * quality_z,
            low,
            high,
        )

    def _adjust_snapshot(
        self,
        *,
        base: PlayerAbilitySnapshot,
        player: Player,
        profile: SchoolIntakeProfile,
    ) -> IntakeAdjustedPlayerAbilitySnapshot:
        payload = {
            field.name: getattr(base, field.name)
            for field in fields(PlayerAbilitySnapshot)
        }
        adjustment = self.params["ability_adjustment_per_quality_z"]
        quality_z = profile.intake_quality_z

        for ability_id in BATTER_ABILITIES:
            payload[ability_id] = self._adjust_scalar(
                getattr(base, ability_id),
                adjustment_per_z=float(
                    adjustment["batter"][ability_id]
                ),
                quality_z=quality_z,
            )

        if player.primary_position == "C":
            for ability_id in CATCHER_ABILITIES:
                payload[ability_id] = self._adjust_scalar(
                    getattr(base, ability_id),
                    adjustment_per_z=float(
                        adjustment["catcher"][ability_id]
                    ),
                    quality_z=quality_z,
                )

        if player.primary_position == "P":
            for ability_id in PITCHER_ABILITIES:
                low, high = (
                    (100, 165)
                    if ability_id == "velocity_kmh"
                    else (1, 100)
                )
                payload[ability_id] = self._adjust_scalar(
                    getattr(base, ability_id),
                    adjustment_per_z=float(
                        adjustment["pitcher"][ability_id]
                    ),
                    quality_z=quality_z,
                    low=low,
                    high=high,
                )

        aptitudes = dict(base.position_aptitude)
        aptitudes[player.primary_position] = _clamp_round(
            float(aptitudes[player.primary_position])
            + float(adjustment["primary_position_aptitude"])
            * quality_z,
            60,
            100,
        )
        payload["position_aptitude"] = tuple(
            (position, aptitudes[position])
            for position, _ in base.position_aptitude
        )

        if player.primary_position == "P":
            payload["pitch_repertoire"] = tuple(
                PitchAbility(
                    pitch_type=pitch.pitch_type,
                    quality=_clamp_round(
                        float(pitch.quality)
                        + float(adjustment["pitch_quality"])
                        * quality_z,
                        1,
                        100,
                    ),
                    command=_clamp_round(
                        float(pitch.command)
                        + float(adjustment["pitch_command"])
                        * quality_z,
                        1,
                        100,
                    ),
                    usage=pitch.usage,
                )
                for pitch in base.pitch_repertoire
            )

        snapshot = IntakeAdjustedPlayerAbilitySnapshot(
            **payload,
            intake_config_id=profile.intake_config_id,
            intake_config_revision=profile.intake_config_revision,
            intake_config_sha256=profile.intake_config_sha256,
            intake_program_quality_z=profile.program_quality_z,
            intake_cohort_quality_z=profile.cohort_quality_z,
            intake_quality_z=profile.intake_quality_z,
        )
        validate_ability_snapshot(snapshot)
        return snapshot

    def generate(
        self,
        player: Player,
        reference_year: int,
        base_seed: int,
    ) -> IntakeAdjustedPlayerAbilitySnapshot:
        base = self.base_generator.generate(
            player,
            reference_year,
            base_seed,
        )
        profile = self.intake_model.profile(
            school_id=player.school_id,
            entry_year=player.entry_year,
            base_seed=base_seed,
        )
        return self._adjust_snapshot(
            base=base,
            player=player,
            profile=profile,
        )

    def iter_roster(
        self,
        players: Iterable[Player],
        reference_year: int,
        base_seed: int,
    ) -> Iterator[IntakeAdjustedPlayerAbilitySnapshot]:
        for player in players:
            yield self.generate(player, reference_year, base_seed)

    def iter_all_schools(
        self,
        repo: DataRepository,
        reference_year: int,
        base_seed: int,
        *,
        roster_generator: PlayerRosterGenerator | None = None,
    ) -> Iterator[IntakeAdjustedPlayerAbilitySnapshot]:
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
