from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
import math
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from phase2_engine.randomness import gauss_for, rng_for, uniform_for
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
    # 私立の上乗せ（quality_model.private_component。評判のランクごと）
    private_quality_z: float = 0.0

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
    # 入学時の頭打ち（entry_soft_cap）で抑えた点（能力ID, 点）。成長で取り戻す（player_growth_v1）
    intake_deferred: tuple = ()


def _clamp_round(value: float, low: int, high: int) -> int:
    return min(high, max(low, int(round(value))))


def soft_cap(value: float, knee: float, cap: float, rate: float = 1.0) -> float:
    """``knee`` までは変えず、それより上は ``cap`` に向かって緩やかに頭打ちにする
    （単調なので順番は変わらない。``knee`` での傾きは ``rate``）。"""
    if value <= knee:
        return value
    room = cap - knee
    return knee + room * (1.0 - math.exp(-(value - knee) * rate / room))


def interpolate(points, x: float) -> float:
    """[[x, y], …]（x の小さい順）の点の間を直線でつなぐ。範囲の外は端の値。"""
    points = [(float(a), float(b)) for a, b in points]
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


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
        # 学校 → 設置者（名簿の持ち主が DataRepository.ownership_type を渡す。ゲーム内の編集も反映）。
        # 渡されなければ学校マスターの設置者
        self.ownership = None
        self._master_ownership: dict[str, str] | None = None
        self._public_types: frozenset[str] | None = None

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
            program_z = gauss_for(base_seed, program_namespace,
                                  float(program["mean"]), float(program["stddev"]))
        # 学校・入学年度ごとに1つの値（乱数の生成器はつくらない）
        cohort_z = gauss_for(base_seed, cohort_namespace,
                             float(cohort["mean"]), float(cohort["stddev"]))
        combined = (
            program_z * float(program["weight"])
            + cohort_z * float(cohort["weight"])
        )
        coach_id, coach_reputation, coach_z = (
            self.coaches.intake_for(school_id, entry_year)
            if self.coaches is not None else (None, None, 0.0)
        )
        combined += coach_z
        private_z = self.private_z(school_id, program_z)
        combined += private_z
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
            private_quality_z=private_z,
        )


    def _ownership_of(self, school_id: str) -> str:
        if self.ownership is not None:
            return self.ownership(school_id) or ""
        if self._master_ownership is None:
            import csv

            path = self._root / "data" / "master" / "schools.csv"
            rows = csv.DictReader(path.open(encoding="utf-8-sig", newline="")) if path.is_file() else ()
            self._master_ownership = {row["school_id"]: row["ownership_type"] for row in rows}
        return self._master_ownership.get(school_id, "")

    def private_z(self, school_id: str, program_z: float) -> float:
        """私立の入部品質の上乗せ（``quality_model.private_component``）。

        公立（21世紀枠の設定 ``senbatsu_selection_v1`` の ``public_ownership_types``）でも国立などでもない
        私立（設置者 ``private``）だけ。全校の中の評判の順位（下からの割合。学校成分 z は順位の
        正規変換なので z から戻す）で、``z_by_share`` の点の間を直線でつないだ値（なだらかに変わる）。"""
        rule = self.params["quality_model"].get("private_component")
        if not rule:
            return 0.0
        if self._public_types is None:
            import json

            selection = json.loads((self._root / "config" / "selection" / "senbatsu_selection_v1.json")
                                   .read_text(encoding="utf-8"))
            self._public_types = frozenset(selection["century"]["public_ownership_types"])
        ownership = self._ownership_of(school_id)
        if ownership != "private" or ownership in self._public_types:
            return 0.0
        from statistics import NormalDist

        program = self.params["quality_model"]["program_component"]
        share = NormalDist(float(program["mean"]), float(program["stddev"])).cdf(program_z)
        return interpolate(rule["z_by_share"], share)

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

    def _entry_cap(self, value: float) -> float:
        """1年の4月の能力の上の方をさらに抑える（``entry_soft_cap``）。抑えた分は成長で取り戻す。"""
        rule = (self.params.get("entry_soft_cap") or {}).get("scalar")
        if not rule:
            return value
        return soft_cap(value, float(rule["knee"]), float(rule["cap"]), float(rule.get("rate", 1.0)))

    # ---- 素質 ----

    def _namespace(self, key: str, *, school_id: str, entry_year: int, roster_no: int = 0) -> str:
        return self.params["rng_namespace_policy"][key].format(
            school_id=school_id, entry_year=entry_year, roster_no=roster_no,
        )

    def prospect_mean(self, profile: SchoolIntakeProfile) -> float:
        rule = self.params["talent_model"]["prospects"]
        return min(
            float(rule["max_mean"]),
            float(rule["base_mean"]) * math.exp(float(rule["per_z"]) * profile.intake_quality_z),
        )

    def prospect_count(self, profile: SchoolIntakeProfile, base_seed: int) -> int:
        """その学校・年度の旧方式の抽選人数。全国プールの供給数にも使う。"""
        rng = rng_for(base_seed, self._namespace(
            "prospects", school_id=profile.school_id, entry_year=profile.entry_year,
        ))
        return poisson(rng, self.prospect_mean(profile))

    def prospect_slots(self, profile: SchoolIntakeProfile, cohort: Iterable[int],
                       base_seed: int, count: int) -> list[int]:
        if not count:
            return []
        return sorted(cohort, key=lambda roster_no: (
            uniform_for(base_seed, self._namespace(
                "priority", school_id=profile.school_id, entry_year=profile.entry_year,
                roster_no=roster_no,
            )),
            roster_no,
        ))[:count]

    def allocate_prospect_pool(
        self, entry_year: int, cohorts: Mapping[str, tuple[SchoolIntakeProfile, Sequence[int]]], base_seed: int,
    ) -> dict[str, dict[int, int]]:
        """同じ年の学校・部員番号へ候補番号を割り当てる。候補IDは (種, 入学年, 候補番号)。"""
        schools = sorted(cohorts)
        capacities = [len(cohorts[school][1]) for school in schools]
        rule = self.params["talent_model"]["prospects"]
        alpha = float(rule["pool_alpha"])
        leaves = 1 << (max(1, len(schools)) - 1).bit_length()
        weights = [0.0] * (2 * leaves)
        supply = 0
        for i, school in enumerate(schools):
            profile, slots = cohorts[school]
            capacity = capacities[i]
            supply += min(self.prospect_count(profile, base_seed), capacity)
            # E[min(P, N)] = Pr(P >= 1) + … + Pr(P >= N)。
            mean = self.prospect_mean(profile)
            mass = math.exp(-mean)
            tail = -math.expm1(-mean)
            expected = 0.0
            for k in range(1, capacity + 1):
                expected += tail
                mass *= mean / k
                tail = max(0.0, tail - mass)
            weights[leaves + i] = expected * math.exp(alpha * profile.intake_quality_z)
        for node in range(leaves - 1, 0, -1):
            weights[node] = weights[2 * node] + weights[2 * node + 1]

        allocated: dict[str, list[int]] = {}
        namespace = self.params["rng_namespace_policy"]["pool"]
        for candidate in range(supply):
            if weights[1] <= 0:
                raise ValueError(f"{entry_year}: no open prospect slots")
            draw = uniform_for(base_seed, namespace.format(entry_year=entry_year, candidate_index=candidate))
            ticket = min(draw * weights[1], math.nextafter(weights[1], 0.0))
            node = 1
            while node < leaves:
                node *= 2
                if ticket >= weights[node]:
                    ticket = min(ticket - weights[node], math.nextafter(weights[node + 1], 0.0))
                    node += 1
            school_index = node - leaves
            allocated.setdefault(schools[school_index], []).append(candidate)
            capacities[school_index] -= 1
            if capacities[school_index] == 0:
                # 満員校の葉だけを消し、根までの重みを更新する。
                weights[node] = 0.0
                while node > 1:
                    node //= 2
                    weights[node] = weights[2 * node] + weights[2 * node + 1]
        result = {}
        for school, candidates in allocated.items():
            profile, cohort = cohorts[school]
            slots = self.prospect_slots(profile, cohort, base_seed, len(candidates))
            result[school] = dict(zip(slots, candidates, strict=True))
        return result

    def prospects(
        self, profile: SchoolIntakeProfile, cohort: Iterable[int], base_seed: int,
    ) -> set[int]:
        """有望な新入生の部員番号：人数を引き、その年の新入生のうち選手ごとの順番の
        小さい順に割り当てる（部員の人数が変わっても1人あたりの確率にならない）。

        学校・入学年度・学年の顔ぶれごとに1回だけ決める（学年の全員で同じ答え）。"""
        cohort = tuple(cohort)
        memo = self.__dict__.setdefault("_prospects_memo", {})
        key = (base_seed, profile.school_id, profile.entry_year, profile.intake_quality_z, cohort)
        held = memo.get(key)
        if held is not None:
            return set(held)
        count = self.prospect_count(profile, base_seed)
        chosen = frozenset(self.prospect_slots(profile, cohort, base_seed, count))
        if len(memo) >= 4096:
            memo.clear()
        memo[key] = chosen
        return set(chosen)

    def talent(
        self, player: Player, profile: SchoolIntakeProfile, base_seed: int,
        *, prospect: bool, rng=None,
    ) -> PlayerTalent:
        model = self.params["talent_model"]
        rng = rng or self.player_rng(player, base_seed)
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

    def platoon_trait(self, player: Player, rng) -> str | None:
        """一部の選手だけの左右の得意・不得意（野手は対左投手、投手は対左打者）。
        ``rng`` は選手ごとの乱数（能力のあとに引く）。"""
        shares = self.params["platoon_traits"]["pitcher" if player.primary_position == "P" else "batter"]
        roll = rng.random()
        for trait in ("vs_left_good", "vs_left_bad"):
            if roll < float(shares[trait]):
                return trait
            roll -= float(shares[trait])
        return None

    def player_rng(self, player: Player, base_seed: int):
        """選手ごとの乱数（1人に1個）。守備位置の適性・球種 → 素質 → 能力 → 左右の特性の順に
        引き、名簿では続けて成長の型・開始前の成長に使う（roster_book.py）。"""
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
        is_prospect: bool | None = None,
        rng=None,
    ) -> IntakeAdjustedPlayerAbilitySnapshot:
        """入学（1年の4月）の能力：平均 ＋ 素質 × 重み × 型の倍率 ＋ 型の点 ＋ 乱数。

        能力ごとの乱数は選手ごとの乱数（入学年度・学校・部員番号）から決まった順に引く。
        守備位置の並び・球種は ``base``（基準の生成。同じ乱数の先に引いたもの）のものを使う。"""
        if is_prospect is None:
            slots = cohort if cohort is not None else (player.roster_no,)
            is_prospect = player.roster_no in self.prospects(profile, slots, profile.generation_seed)
        rng = rng if rng is not None else self.player_rng(player, base_seed=profile.generation_seed)
        talent = self.talent(
            player, profile, profile.generation_seed,
            prospect=is_prospect,
            rng=rng,
        )
        generation = self.base_generator.params
        per_talent = self.params["ability_per_talent"]
        payload = {
            field.name: getattr(base, field.name)
            for field in fields(PlayerAbilitySnapshot)
        }

        deferred: dict[str, int] = {}

        def value(ability_id: str, params: dict, weight: float, kind: str = "scalar",
                  low: int = 1, high: int = 100, defer: bool = False) -> int:
            noise = rng.gauss(0.0, 1.0)
            defaults = generation["scalar_defaults"]
            load, tilt = self._shape(talent, ability_id)
            raw = (
                float(params.get("mean", defaults["mean"]))
                + weight * load * talent.talent + tilt
                + float(params.get("stddev", defaults["stddev"])) * noise
            )
            full = _clamp_round(self._soft_cap(raw, kind), low, high)
            if not defer:
                return full
            entry = min(full, _clamp_round(self._entry_cap(self._soft_cap(raw, kind)), low, high))
            if entry < full:
                deferred[ability_id] = full - entry
            return entry

        for ability_id in BATTER_ABILITIES:
            payload[ability_id] = value(
                ability_id, generation["batter_abilities"][ability_id],
                float(per_talent["batter"][ability_id]), defer=True,
            )
        for ability_id in CATCHER_ABILITIES:
            drawn = value(
                ability_id, generation["catcher_only_abilities"][ability_id],
                float(per_talent["catcher"][ability_id]), defer=player.primary_position == "C",
            )
            payload[ability_id] = drawn if player.primary_position == "C" else None
        for ability_id in PITCHER_ABILITIES:
            velocity = ability_id == "velocity_kmh"
            params = generation["pitcher_abilities"][ability_id]
            drawn = value(
                ability_id, params, float(per_talent["pitcher"][ability_id]),
                kind="velocity_kmh" if velocity else "scalar",
                low=int(params.get("min", 1)), high=int(params.get("max", 100)),
                defer=not velocity and player.primary_position == "P",
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

        # 球種の質・制球は、投手でなくても全部の球種の分を引く（どの選手も同じ数だけ引くので、
        # 守備位置が変わってもこのあとに引く左右の特性・成長の型が変わらない）
        fields_params = generation["pitch_repertoire"]["per_pitch_fields"]
        pitch_values = {
            pitch_type: (
                value("pitch_quality", fields_params["quality"], float(per_talent["pitch_quality"])),
                value("pitch_command", fields_params["command"], float(per_talent["pitch_command"])),
            )
            for pitch_type in generation["pitch_repertoire"]["pitch_types"]
        }
        if player.primary_position == "P":
            payload["pitch_repertoire"] = tuple(
                PitchAbility(
                    pitch_type=pitch.pitch_type,
                    quality=pitch_values[pitch.pitch_type][0],
                    command=pitch_values[pitch.pitch_type][1],
                    usage=pitch.usage,
                )
                for pitch in base.pitch_repertoire
            )

        payload["platoon_trait"] = self.platoon_trait(player, rng)
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
            intake_deferred=tuple(sorted(deferred.items())),
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
        day: date | None = None,
        rng=None,
        profile: SchoolIntakeProfile | None = None,
        is_prospect: bool | None = None,
    ) -> PlayerAbilitySnapshot:
        """``cohort`` は同じ学校・入学年度の部員番号（有望な新入生を割り当てる）。
        全国プールで確定済みなら ``is_prospect`` を渡し、学校ごとの抽選を省く。
        どちらも省けばその選手1人の学年として扱う。``day`` は名簿の能力を見る日
        （試合の日。省くと名簿の今日）。``rng`` は選手ごとの乱数（省くと ``player_rng``。
        名簿は続けて成長の型に使うので渡す）。``profile`` はその学校・入学年度の入部品質
        （省くと ``intake_model.profile``。名簿を並列でつくるとき、親のプロセスで求めて渡す）。"""
        if self.source is not None:
            snapshot = (self.source.ability(player, day) if day is not None
                        else self.source.ability(player))
            # 3月に始まる大会は前の年度の名簿の能力で、大会の年度として戦う
            if snapshot.reference_year != reference_year:
                snapshot = replace(snapshot, reference_year=reference_year)
        else:
            rng = rng if rng is not None else self.player_rng(player, base_seed)
            snapshot = self._adjust_snapshot(
                base=self.base_generator.generate(
                    player, reference_year, base_seed, rng=rng, draw_scalars=False,
                ),
                player=player,
                profile=profile if profile is not None else self.intake_model.profile(
                    school_id=player.school_id,
                    entry_year=player.entry_year,
                    base_seed=base_seed,
                ),
                cohort=cohort,
                is_prospect=is_prospect,
                rng=rng,
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
