from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
import math
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
from .school_reputation import reputation_for


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
    coach_id: str | None = None
    coach_reputation: int | None = None
    coach_quality_z: float = 0.0

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
    intake_coach_id: str | None = None
    intake_coach_reputation: int | None = None
    intake_coach_quality_z: float = 0.0
    # 選手ごとの素質・有望な新入生か・型（talent_model・player_types）
    intake_talent: float = 0.0
    intake_prospect: bool = False
    batter_type: str | None = None
    pitcher_type: str | None = None


def _clamp_round(value: float, low: int, high: int) -> int:
    return min(high, max(low, int(round(value))))


def soft_cap(value: float, knee: float, cap: float, rate: float = 1.0) -> float:
    """``knee`` までは変えず、それより上は ``cap`` に向かって緩やかに頭打ちにする
    （単調なので順番は変わらない。``knee`` での傾きは ``rate``）。"""
    if value <= knee:
        return value
    room = cap - knee
    return knee + room * (1.0 - math.exp(-(value - knee) * rate / room))


def _clamp_float(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


class SchoolIntakeModel:
    def __init__(self, config_dir: str | Path = "config/abilities"):
        self.configs = load_and_validate_ability_configs(config_dir)
        self.config = self.configs["school_intake_v1"]
        self.params = self.config.payload
        # 学校成分は学校の評判から（game_core/school_reputation.py）。リポジトリ
        # （config・data・historical_data のある所）は config/abilities の2つ上
        self._root = Path(config_dir).resolve().parent.parent
        self.reputation = None
        self.coaches = None

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
        program_z = None
        if program.get("source") == "reputation":
            program_z = (
                self.reputation.program_z(school_id, entry_year)
                if self.reputation is not None
                else reputation_for(str(self._root)).program_z(school_id, base_seed)
            )
        if program_z is None:
            # 評判のない学校（学校マスターにない架空の学校など）は乱数
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
        coach_id, coach_reputation, coach_z = (
            self.coaches.intake_for(school_id, entry_year)
            if self.coaches is not None else (None, None, 0.0)
        )
        combined += coach_z
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
            coach_id=coach_id,
            coach_reputation=coach_reputation,
            coach_quality_z=coach_z,
        )


@dataclass(frozen=True)
class PlayerTalent:
    """選手ごとの素質と型（入学のときに決まる。§3.1）。"""

    talent: float
    prospect: bool
    batter_type: str
    pitcher_type: str | None


def poisson(rng, mean: float) -> int:
    """平均 ``mean`` の Poisson 乱数（小さい平均だけを使う）。"""
    if mean <= 0:
        return 0
    limit = math.exp(-mean)
    count, product = 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


def _pick_type(types: dict, roll: float) -> str:
    names = list(types)
    for name in names:
        share = float(types[name]["share"])
        if roll < share:
            return name
        roll -= share
    return names[-1]


class SchoolAwarePlayerAbilityGenerator:
    def __init__(self, config_dir: str | Path = "config/abilities"):
        self.config_dir = Path(config_dir)
        self.base_generator = PlayerAbilityGenerator(self.config_dir)
        self.intake_model = SchoolIntakeModel(self.config_dir)
        self.params = self.intake_model.params
        # セーブに入った名簿（game_core/roster_book.py）。つなぐと能力をつくらずに
        # 名簿に保存された現在の能力を使う
        self.source = None

    def _soft_cap(self, value: float, kind: str) -> float:
        """入学時の能力の上の方を頭打ちにする（``upper_soft_cap``）。"""
        caps = self.params.get("upper_soft_cap")
        if not caps:
            return value
        rule = caps[kind]
        return soft_cap(
            value, float(rule["knee"]), float(rule["cap"]), float(rule.get("rate", 1.0)),
        )

    # ---- 素質 ----

    def _namespace(self, key: str, *, school_id: str, entry_year: int, roster_no: int = 0) -> str:
        return self.params["rng_namespace_policy"][key].format(
            school_id=school_id, entry_year=entry_year, roster_no=roster_no,
        )

    def prospect_count(self, profile: SchoolIntakeProfile, base_seed: int) -> int:
        """その学校・年度の有望な新入生の人数（入部品質 z が高いほど多い）。"""
        rule = self.params["talent_model"]["prospects"]
        mean = min(
            float(rule["max_mean"]),
            float(rule["base_mean"]) * math.exp(float(rule["per_z"]) * profile.intake_quality_z),
        )
        rng = rng_for(base_seed, self._namespace(
            "prospects", school_id=profile.school_id, entry_year=profile.entry_year,
        ))
        return poisson(rng, mean)

    def prospects(
        self, profile: SchoolIntakeProfile, cohort: Iterable[int], base_seed: int,
    ) -> set[int]:
        """有望な新入生の部員番号：人数を引き、その年の新入生のうち選手ごとの順番の
        小さい順に割り当てる（部員の人数が変わっても1人あたりの確率にならない）。"""
        count = self.prospect_count(profile, base_seed)
        if not count:
            return set()
        order = sorted(
            cohort,
            key=lambda roster_no: (
                rng_for(base_seed, self._namespace(
                    "priority", school_id=profile.school_id,
                    entry_year=profile.entry_year, roster_no=roster_no,
                )).random(),
                roster_no,
            ),
        )
        return set(order[:count])

    def talent(
        self, player: Player, profile: SchoolIntakeProfile, base_seed: int,
        *, prospect: bool, rng=None,
    ) -> PlayerTalent:
        model = self.params["talent_model"]
        rng = rng or self._player_rng(player, base_seed)
        value = (
            profile.intake_quality_z * float(model["school_weight"])
            + rng.gauss(0.0, float(model["player_stddev"]))
        )
        bonus = rng.gauss(
            float(model["prospects"]["bonus_mean"]), float(model["prospects"]["bonus_stddev"]),
        )
        if prospect:
            value += max(0.0, bonus)
        clip = model["clip"]
        value = _clamp_float(value, float(clip["min"]), float(clip["max"]))
        types = self.params["player_types"]
        batter_type = _pick_type(types["batter"], rng.random())
        pitcher_roll = rng.random()
        pitcher_type = (
            _pick_type(types["pitcher"], pitcher_roll)
            if player.primary_position == "P" else None
        )
        return PlayerTalent(round(value, 6), prospect, batter_type, pitcher_type)

    def _player_rng(self, player: Player, base_seed: int):
        return rng_for(base_seed, self._namespace(
            "player", school_id=player.school_id, entry_year=player.entry_year,
            roster_no=player.roster_no,
        ))

    def _shape(self, talent: PlayerTalent, ability_id: str) -> tuple[float, float]:
        """(素質の効き方の倍率, 型の長所・短所の点)。"""
        load, tilt = 1.0, 0.0
        types = self.params["player_types"]
        for group, name in (("batter", talent.batter_type), ("pitcher", talent.pitcher_type)):
            if name is None:
                continue
            rule = types[group][name]
            load *= float(rule["load"].get(ability_id, 1.0))
            tilt += float(rule["tilt"].get(ability_id, 0.0))
        return load, tilt

    # ---- 能力 ----

    def _adjust_snapshot(
        self,
        *,
        base: PlayerAbilitySnapshot,
        player: Player,
        profile: SchoolIntakeProfile,
        cohort: Iterable[int] | None = None,
    ) -> IntakeAdjustedPlayerAbilitySnapshot:
        """入学（1年の4月）の能力：平均 ＋ 素質 × 重み × 型の倍率 ＋ 型の点 ＋ 乱数。

        能力ごとの乱数は選手ごとの乱数（入学年度・学校・部員番号）から決まった順に引く。
        守備位置の並び・球種は ``base``（基準の生成）のものを使う。"""
        cohort = tuple(cohort) if cohort is not None else (player.roster_no,)
        rng = self._player_rng(player, base_seed=profile.generation_seed)
        talent = self.talent(
            player, profile, profile.generation_seed,
            prospect=player.roster_no in self.prospects(profile, cohort, profile.generation_seed),
            rng=rng,
        )
        generation = self.base_generator.params
        per_talent = self.params["ability_per_talent"]
        payload = {
            field.name: getattr(base, field.name)
            for field in fields(PlayerAbilitySnapshot)
        }

        def value(ability_id: str, params: dict, weight: float, kind: str = "scalar",
                  low: int = 1, high: int = 100) -> int:
            noise = rng.gauss(0.0, 1.0)
            defaults = generation["scalar_defaults"]
            load, tilt = self._shape(talent, ability_id)
            raw = (
                float(params.get("mean", defaults["mean"]))
                + weight * load * talent.talent + tilt
                + float(params.get("stddev", defaults["stddev"])) * noise
            )
            return _clamp_round(self._soft_cap(raw, kind), low, high)

        for ability_id in BATTER_ABILITIES:
            payload[ability_id] = value(
                ability_id, generation["batter_abilities"][ability_id],
                float(per_talent["batter"][ability_id]),
            )
        for ability_id in CATCHER_ABILITIES:
            drawn = value(
                ability_id, generation["catcher_only_abilities"][ability_id],
                float(per_talent["catcher"][ability_id]),
            )
            payload[ability_id] = drawn if player.primary_position == "C" else None
        for ability_id in PITCHER_ABILITIES:
            velocity = ability_id == "velocity_kmh"
            params = generation["pitcher_abilities"][ability_id]
            drawn = value(
                ability_id, params, float(per_talent["pitcher"][ability_id]),
                kind="velocity_kmh" if velocity else "scalar",
                low=int(params.get("min", 1)), high=int(params.get("max", 100)),
            )
            payload[ability_id] = drawn if player.primary_position == "P" else None

        aptitudes = dict(base.position_aptitude)
        aptitudes[player.primary_position] = _clamp_round(
            float(aptitudes[player.primary_position])
            + float(per_talent["primary_position_aptitude"]) * talent.talent,
            60,
            100,
        )
        payload["position_aptitude"] = tuple(
            (position, aptitudes[position])
            for position, _ in base.position_aptitude
        )

        if player.primary_position == "P":
            fields_params = generation["pitch_repertoire"]["per_pitch_fields"]
            payload["pitch_repertoire"] = tuple(
                PitchAbility(
                    pitch_type=pitch.pitch_type,
                    quality=value(
                        "pitch_quality", fields_params["quality"], float(per_talent["pitch_quality"]),
                    ),
                    command=value(
                        "pitch_command", fields_params["command"], float(per_talent["pitch_command"]),
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
            intake_coach_id=profile.coach_id,
            intake_coach_reputation=profile.coach_reputation,
            intake_coach_quality_z=profile.coach_quality_z,
            intake_talent=talent.talent,
            intake_prospect=talent.prospect,
            batter_type=talent.batter_type,
            pitcher_type=talent.pitcher_type,
        )
        validate_ability_snapshot(snapshot)
        return snapshot

    def generate(
        self,
        player: Player,
        reference_year: int,
        base_seed: int,
        *,
        cohort: Iterable[int] | None = None,
    ) -> PlayerAbilitySnapshot:
        """``cohort`` は同じ学校・入学年度の部員番号（有望な新入生を割り当てる）。
        渡さなければその選手1人の学年として扱う。"""
        if self.source is not None:
            snapshot = self.source.ability(player)
            # 3月に始まる大会は前の年度の名簿の能力で、大会の年度として戦う
            if snapshot.reference_year != reference_year:
                snapshot = replace(snapshot, reference_year=reference_year)
        else:
            snapshot = self._adjust_snapshot(
                base=self.base_generator.generate(
                    player,
                    reference_year,
                    base_seed,
                ),
                player=player,
                profile=self.intake_model.profile(
                    school_id=player.school_id,
                    entry_year=player.entry_year,
                    base_seed=base_seed,
                ),
                cohort=cohort,
            )
        return snapshot

    def iter_roster(
        self,
        players: Iterable[Player],
        reference_year: int,
        base_seed: int,
    ) -> Iterator[IntakeAdjustedPlayerAbilitySnapshot]:
        players = list(players)
        cohorts: dict[tuple[str, int], list[int]] = {}
        for player in players:
            cohorts.setdefault((player.school_id, player.entry_year), []).append(player.roster_no)
        for player in players:
            yield self.generate(
                player, reference_year, base_seed,
                cohort=cohorts[(player.school_id, player.entry_year)],
            )

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
