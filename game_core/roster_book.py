"""全国の名簿：年度ごとの部員と、選手ごとの名前・出身・能力・成長の状態。セーブに入る。

乱数の種から作るのは最初の年度の名簿と新入生だけ（新規開始と入学のとき）。
進級した選手は前の年度の名簿から名前・出身を引き継ぐ。能力と成長の状態（成長の型・
潜在能力・その月の公式戦の出場数）は選手ごとに1つ持ち、毎月の初めに成長で変わる
（``player_growth.py``）。試合と画面はそのときの能力を使う。

セーブを小さくするため、書き出すときは詰めた形にする（選手IDは乱数の種・学校・
入学年度・番号から作り直す。能力は1項目1バイト）。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import json
import threading
import zlib
from typing import Callable, Iterable

from phase2_engine.models import Team
from phase2_engine.randomness import rng_for
from phase2_engine.school_year import school_year_of

from .abilities import (
    BATTER_ABILITIES,
    CATCHER_ABILITIES,
    FIELD_POSITIONS,
    PITCHER_ABILITIES,
    PitchAbility,
    PlayerAbilitySnapshot,
)
from .career_rosters import _newcomer_id, advance_school_roster
from .injuries import Injury, injury_model
from .player_growth import PlayerGrowth
from .players import Player, PlayerRosterGenerator, SchoolRoster, _player_id, _position_group


SCALARS = BATTER_ABILITIES + CATCHER_ABILITIES + PITCHER_ABILITIES
PITCH_FIELDS = 4


def pack_abilities(snapshot: PlayerAbilitySnapshot, pitch_types: list[str]) -> bytes:
    """能力を1項目1バイトに詰める（ない項目は0。値は1〜165）。"""
    values = [getattr(snapshot, name) or 0 for name in SCALARS]
    values.extend(value for _, value in snapshot.position_aptitude)
    for pitch in snapshot.pitch_repertoire:
        values.extend((
            pitch_types.index(pitch.pitch_type), pitch.quality,
            pitch.command, pitch.usage,
        ))
    return bytes(values)


def unpack_abilities(
    data: bytes, player: Player, *, config_fields: dict, pitch_types: list[str],
) -> PlayerAbilitySnapshot:
    scalars = {name: (data[i] or None) for i, name in enumerate(SCALARS)}
    offset = len(SCALARS)
    aptitude = tuple(
        (position, data[offset + i]) for i, position in enumerate(FIELD_POSITIONS)
    )
    offset += len(FIELD_POSITIONS)
    pitches = tuple(
        PitchAbility(
            pitch_type=pitch_types[data[i]], quality=data[i + 1],
            command=data[i + 2], usage=data[i + 3],
        )
        for i in range(offset, len(data), PITCH_FIELDS)
    )
    return PlayerAbilitySnapshot(
        player_id=player.player_id,
        school_id=player.school_id,
        reference_year=player.entry_year + player.academic_year - 1,
        academic_year=player.academic_year,
        primary_position=player.primary_position,
        generation_seed=player.generation_seed,
        **config_fields,
        **scalars,
        position_aptitude=aptitude,
        pitch_repertoire=pitches,
    )


POSITIONS = FIELD_POSITIONS
BATS = ("R", "L", "S")
THROWS = ("R", "L")


def pack_school(roster: SchoolRoster, *, first_year: int) -> tuple:
    """学校・年度の名簿を詰める：名前は改行でつなぎ、小さい項目は1バイトずつ
    （同じ種類の値をまとめると圧縮が効く）。"""
    sources = {p.name_source for p in roster.players}
    if len(sources) != 1:
        raise ValueError(f"{roster.school_id}: mixed name sources")
    small = bytearray()
    for p in roster.players:
        small.extend((
            p.entry_year - first_year + 2, p.roster_no,
            int(p.hometown_prefecture_code), POSITIONS.index(p.primary_position),
            BATS.index(p.bats), THROWS.index(p.throws),
        ))
    return (
        roster.school_name,
        roster.program_id,
        roster.cohort_policy,
        sources.pop(),
        "\n".join(p.display_name for p in roster.players),
        bytes(small),
    )


def unpack_school(packed: tuple, *, first_year: int) -> list[tuple]:
    """(入学年度, 番号, 名前, 名前の出典, 出身, 守備位置, 打, 投) の並び。"""
    _, _, _, source, names, small = packed
    rows = []
    for index, name in enumerate(names.split("\n")):
        entry, roster_no, hometown, position, bats, throws = small[index * 6:index * 6 + 6]
        rows.append((
            entry + first_year - 2, roster_no, name, source, f"{hometown:02d}",
            POSITIONS[position], BATS[bats], THROWS[throws],
        ))
    return rows


DAY_ZERO = date(2000, 1, 1)


def _day(value: date) -> int:
    return (value - DAY_ZERO).days


def _from_day(value: int) -> date:
    return DAY_ZERO + timedelta(days=value)


class PlayerState:
    """選手ごとの能力（1項目1バイト）と成長の状態・怪我。

    ``games`` はその月の公式戦の出場数（成長で使って0に戻す）、``season_games`` は
    その年度の出場数（怪我の起きやすさ）。``injuries`` は怪我の履歴（最後が今か直近）。
    """

    __slots__ = (
        "values", "growth_type", "potential", "velocity_potential", "games", "season_games",
        "injuries",
    )

    def __init__(
        self, values: bytearray, growth_type: int, potential: int, games: int = 0,
        season_games: int = 0, injuries: list[Injury] | None = None,
        velocity_potential: int | None = None,
    ):
        self.values = values
        self.growth_type = growth_type
        self.potential = potential
        # 球速の伸びしろ（×80。player_growth.py）
        self.velocity_potential = potential if velocity_potential is None else velocity_potential
        self.games = games
        self.season_games = season_games
        self.injuries = injuries if injuries is not None else []

    def injured_on(self, day: date) -> Injury | None:
        """その日に休んでいる怪我（練習の怪我は月の初めに先の日の分まで決めるので、
        履歴の並びは日付の順とはかぎらない）。"""
        for injury in reversed(self.injuries):
            if injury.start <= day < injury.end:
                return injury
        return None

    def recovering(self, day: date) -> Injury | None:
        """その日までに治った怪我のうち、いちばん最近のもの（復帰直後の能力に使う）。"""
        ended = [injury for injury in self.injuries if injury.end <= day]
        return max(ended, key=lambda injury: injury.end) if ended else None


def _pack_states(first_year: int, states: dict[tuple[int, int], PlayerState]) -> bytes:
    out = bytearray()
    for (entry_year, roster_no), state in sorted(states.items()):
        out.extend((
            entry_year - first_year + 2, roster_no, state.growth_type,
            state.potential, state.velocity_potential, state.games,
            min(255, state.season_games), len(state.injuries), len(state.values),
        ))
        for injury in state.injuries:
            out.extend(_day(injury.start).to_bytes(2, "big"))
            out.extend(injury.days.to_bytes(2, "big"))
            out.append(injury.severity)
        out.extend(state.values)
    return bytes(out)


def _unpack_states(first_year: int, data: bytes) -> dict[tuple[int, int], PlayerState]:
    states = {}
    offset = 0
    while offset < len(data):
        (entry, roster_no, growth_type, potential, velocity_potential, games,
         season_games, count, size) = data[offset:offset + 9]
        offset += 9
        injuries = []
        for _ in range(count):
            injuries.append(Injury(
                _from_day(int.from_bytes(data[offset:offset + 2], "big")),
                int.from_bytes(data[offset + 2:offset + 4], "big"),
                data[offset + 4],
            ))
            offset += 5
        states[(entry + first_year - 2, roster_no)] = PlayerState(
            bytearray(data[offset:offset + size]), growth_type, potential, games,
            season_games, injuries, velocity_potential,
        )
        offset += size
    return states


class RosterBook:
    """年度ごとの名簿と、選手ごとの能力・成長の状態。

    ``team_for``（学校ID → Team）・名前の生成・能力の生成・成長の設定はセーブに
    入れず、読み込んだあとに ``bind`` でつなぎ直す。``school_ids`` を渡すと、毎月の
    成長の前にその全校の名簿をつくる（名簿をつくった時期で成長が変わらないように）。
    """

    def __init__(
        self,
        team_for: Callable[[str], Team],
        *,
        first_year: int,
        career_seed: int,
        school_ids: Iterable[str] = (),
        generator: PlayerRosterGenerator | None = None,
        ability_generator=None,
        growth: PlayerGrowth | None = None,
    ):
        self.reputation = None
        self.coaches = None
        self.grown_through: date | None = None
        self.ability_edits = {}
        self.team_edits = []
        self.first_year = first_year
        self.career_seed = career_seed
        self.school_ids = tuple(school_ids)
        # この年度までの名簿は手放した（閉じた年度。履歴に書き出してある）
        self.closed_through = first_year - 2
        # 成長した回数（能力が変わるたびに増える。試合・画面の能力の作り直しの目印）
        self.version = 0
        # (年度, 学校ID) → 詰めた名簿
        self._packed: dict[tuple[int, str], tuple] = {}
        # 学校ID → (入学年度, 番号) → 能力と成長の状態
        self._states: dict[str, dict[tuple[int, int], PlayerState]] = {}
        # 年度 → 学校ID → 年度末（3月の成長のあと）の能力と成長の状態（詰めた形）。
        # 閉じた年度の名簿と一緒に履歴に書き出すまで持つ
        self._year_end: dict[int, dict[str, bytes]] = {}
        # 怪我の頻度（セーブごとの設定。injuries_v1 の levels）と、今日（復帰直後の
        # 能力の下がり方を決める。CareerState が毎日進める）
        self.injury_level = injury_model().config["default_level"]
        self.today: date | None = None
        self.bind(
            team_for, generator=generator, ability_generator=ability_generator, growth=growth,
        )

    def bind(self, team_for, *, generator=None, ability_generator=None, growth=None) -> None:
        self.team_for = team_for
        self.generator = generator or PlayerRosterGenerator()
        self._ability_generator = ability_generator
        self._growth = growth
        self._rosters: dict[tuple[int, str], SchoolRoster] = {}
        self._abilities: dict[tuple[str, int], PlayerAbilitySnapshot] = {}
        self._fields: dict | None = None
        # 画面は別のスレッドで能力を読む（日付を進めるスレッドと同時）
        self._lock = threading.RLock()

    def __getstate__(self):
        return {
            "first_year": self.first_year,
            "reputation": self.reputation,
            "coaches": self.coaches,
            "grown_through": self.grown_through,
            "ability_edits": self.ability_edits,
            "team_edits": self.team_edits,
            "career_seed": self.career_seed,
            "school_ids": self.school_ids,
            "closed_through": self.closed_through,
            "version": self.version,
            "_packed": self._packed,
            "_year_end": self._year_end,
            "injury_level": self.injury_level,
            "today": self.today,
            "_states": {
                school_id: _pack_states(self.first_year, states)
                for school_id, states in self._states.items()
            },
        }

    def __setstate__(self, data):
        states = data.pop("_states")
        self.__dict__.update(data)
        self._states = {
            school_id: _unpack_states(self.first_year, packed)
            for school_id, packed in states.items()
        }
        self.bind(None)

    # ---- 能力の生成（入学・新規開始のときだけ） ----

    @property
    def ability_generator(self):
        if self._ability_generator is None:
            from .school_intake import SchoolAwarePlayerAbilityGenerator

            self._ability_generator = SchoolAwarePlayerAbilityGenerator()
        if self.reputation is not None:
            self._ability_generator.intake_model.reputation = self.reputation
        if self.coaches is not None:
            self._ability_generator.intake_model.coaches = self.coaches
        return self._ability_generator

    @property
    def growth(self) -> PlayerGrowth:
        if self._growth is None:
            self._growth = PlayerGrowth()
        return self._growth

    def _base(self):
        return self.ability_generator.base_generator

    def _config_fields(self) -> dict:
        base = self._base()
        out = {}
        for prefix, document in (
            ("catalog", base.catalog), ("scale", base.scale),
            ("generation", base.generation),
        ):
            out[f"{prefix}_config_id"] = document.config_id
            out[f"{prefix}_revision"] = document.revision
            out[f"{prefix}_sha256"] = document.canonical_sha256
        return out

    def pitch_types(self) -> list[str]:
        """能力の並びの球種の番号 → 球種。"""
        return self._pitch_types()

    def _pitch_types(self) -> list[str]:
        return list(self._base().params["pitch_repertoire"]["pitch_types"])

    def _new_state(self, player: Player, year: int, cohort: Iterable[int] = ()) -> PlayerState:
        """入学（新規開始の部員を含む）：能力と成長の型・潜在能力をつくる。

        ``cohort`` は同じ学校・入学年度の部員番号（有望な新入生の割り当て）。新規開始の
        2・3年生も1年の4月の能力でつくり、開始の前の月までの成長を進める。"""
        from .school_intake import IntakeAdjustedPlayerAbilitySnapshot, SchoolAwarePlayerAbilityGenerator

        generator = self.ability_generator
        if isinstance(generator, SchoolAwarePlayerAbilityGenerator):
            snapshot = generator.generate(
                player, year, self.career_seed, cohort=tuple(cohort) or None,
            )
        else:
            snapshot = generator.generate(player, year, self.career_seed)
        if (type(generator) is SchoolAwarePlayerAbilityGenerator and generator.source is None
                and type(snapshot) is IntakeAdjustedPlayerAbilitySnapshot):
            # 今まさに能力へ適用した学校成分を使う。別の選手・年度へは保持しない。
            program_z = snapshot.intake_program_quality_z
        else:
            program_z = generator.intake_model.profile(
                school_id=player.school_id, entry_year=player.entry_year,
                base_seed=self.career_seed,
            ).program_quality_z
        namespace = self.growth.config["rng_namespaces"]["player"].format(
            entry_year=player.entry_year, school_id=player.school_id,
            roster_no=player.roster_no,
        )
        growth_type, potential, velocity_potential = self.growth.draw(
            rng_for(self.career_seed, namespace), program_z,
        )
        values = bytearray(pack_abilities(snapshot, self._pitch_types()))
        if player.entry_year < self.first_year and (
                type(generator) is SchoolAwarePlayerAbilityGenerator and generator.source is None):
            self.growth.bootstrap(
                values, position=player.primary_position, entry_year=player.entry_year,
                first_year=self.first_year, type_index=growth_type, potential=potential,
                velocity_potential=velocity_potential,
                rng=rng_for(self.career_seed, self.growth.config["rng_namespaces"]["bootstrap"].format(
                    entry_year=player.entry_year, school_id=player.school_id,
                    roster_no=player.roster_no,
                )),
            )
        return PlayerState(
            values, growth_type, potential, velocity_potential=velocity_potential,
        )

    # ---- 名簿 ----

    def years(self) -> list[int]:
        return sorted({year for year, _ in self._packed})

    def schools(self, year: int) -> list[str]:
        """その年度の名簿をつくった学校。"""
        with self._lock:
            return sorted(school for y, school in self._packed if y == year)

    def roster(self, year: int, school_id: str) -> SchoolRoster:
        with self._lock:
            return self._roster(year, school_id)

    def _roster(self, year: int, school_id: str) -> SchoolRoster:
        key = (year, school_id)
        cached = self._rosters.get(key)
        if cached is not None:
            return cached
        if year < self.first_year - 1:
            raise ValueError(f"no roster before {self.first_year - 1}: {year}")
        if year <= self.closed_through:
            raise ValueError(f"roster {year} is closed (see the history)")
        if year == self.first_year - 1:
            return self._before_first_year(school_id)
        if key in self._packed:
            return self._unpack(year, school_id)
        team = self.team_for(school_id)
        states = self._states.setdefault(school_id, {})
        if year == self.first_year:
            roster = self.generator.generate_school(team, year, self.career_seed)
            newcomers = roster.players
        else:
            if (year - 1, school_id) not in self._packed and year - 1 != self.first_year:
                raise ValueError(f"{school_id}: roster {year - 1} is not kept")
            transition = advance_school_roster(
                self.roster(year - 1, school_id), team, next_year=year,
                career_seed=self.career_seed, generator=self.generator,
            )
            roster = transition.roster
            newcomers = transition.newcomers
        cohorts: dict[int, list[int]] = {}
        for player in newcomers:
            cohorts.setdefault(player.entry_year, []).append(player.roster_no)
        for player in newcomers:
            states[(player.entry_year, player.roster_no)] = self._new_state(
                player, year, cohorts[player.entry_year],
            )
        self._packed[key] = pack_school(roster, first_year=self.first_year)
        self._rosters[key] = roster
        return roster

    def _player_id(self, school_id: str, entry_year: int, roster_no: int) -> str:
        # 最初の年度の部員と新入生で作り方が違う（players.py・career_rosters.py）
        if entry_year <= self.first_year:
            return _player_id(self.career_seed, self.first_year, school_id, roster_no)
        return _newcomer_id(self.career_seed, entry_year, school_id, roster_no)

    def _unpack(self, year: int, school_id: str) -> SchoolRoster:
        school_name, program_id, cohort_policy = self._packed[(year, school_id)][:3]
        rows = unpack_school(self._packed[(year, school_id)], first_year=self.first_year)
        players = [
            Player(
                player_id=self._player_id(school_id, entry_year, roster_no),
                school_id=school_id,
                program_id=program_id,
                display_name=name,
                name_source=name_source,
                hometown_prefecture_code=hometown,
                academic_year=year - entry_year + 1,
                entry_year=entry_year,
                roster_no=roster_no,
                primary_position=position,
                position_group=_position_group(position),
                bats=bats,
                throws=throws,
                roster_status="active_core",
                generation_seed=self.career_seed,
            )
            for (entry_year, roster_no, name, name_source, hometown,
                 position, bats, throws) in rows
        ]
        roster = SchoolRoster(
            reference_year=year,
            school_id=school_id,
            program_id=program_id,
            school_name=school_name,
            rng_seed=self.career_seed,
            players=players,
            cohort_policy=cohort_policy,
        )
        self._rosters[(year, school_id)] = roster
        return roster

    def _before_first_year(self, school_id: str) -> SchoolRoster:
        """ゲーム開始の前の年度（3月に始まる大会用）。

        最初の年度の2・3年生を1学年戻したもの。卒業した3年生と、まだ
        入学していない新入生はいない。能力は最初の年度のもの。
        """
        first = self.roster(self.first_year, school_id)
        roster = replace(
            first,
            reference_year=self.first_year - 1,
            players=[
                replace(player, academic_year=player.academic_year - 1)
                for player in first.players
                if player.academic_year >= 2
            ],
        )
        self._rosters[(self.first_year - 1, school_id)] = roster
        return roster

    # ---- 能力 ----

    def state(self, player: Player) -> PlayerState:
        with self._lock:
            states = self._states.get(player.school_id, {})
            key = (player.entry_year, player.roster_no)
            if key not in states:
                self.roster(player.entry_year + player.academic_year - 1, player.school_id)
            return self._states[player.school_id][key]

    def base_ability(self, player: Player) -> PlayerAbilitySnapshot:
        """怪我・復帰の補正を掛ける前の能力。編集はこの値に対して行う。"""
        return unpack_abilities(bytes(self.state(player).values), player,
                                config_fields=self._config_fields(), pitch_types=self._pitch_types())

    def project_ability(self, player, snapshot):
        values = bytearray(pack_abilities(snapshot, self._pitch_types()))
        recent = self.state(player).recovering(self.today) if self.today else None
        step = injury_model().recovery_step(recent, self.today) if recent else 0
        if step:
            self._recovery_drop(values, recent, step)
        return unpack_abilities(bytes(values), player, config_fields=self._config_fields(),
                                pitch_types=self._pitch_types())

    def edit_abilities(self, players, snapshots, *, day, source):
        # 検証とパックを全員分済ませ、途中まで変更されるのを防ぐ。
        from .abilities import validate_ability_snapshot

        packed = []
        for player, snapshot in zip(players, snapshots, strict=True):
            if snapshot.player_id != player.player_id or snapshot.school_id != player.school_id:
                raise ValueError("編集対象の選手IDが一致しません")
            validate_ability_snapshot(snapshot)
            packed.append(bytearray(pack_abilities(snapshot, self._pitch_types())))
        with self._lock:
            for player, snapshot, values in zip(players, snapshots, packed):
                self.state(player).values = values
                self.ability_edits.setdefault(player.player_id, []).append({
                    "date": day, "school_id": player.school_id, "source": source,
                    "abilities": snapshot.to_dict(),
                })
            self.version += 1
            self._abilities.clear()

    def ability(self, player: Player) -> PlayerAbilitySnapshot:
        """その選手の今の能力（復帰直後は少し下がる）。"""
        with self._lock:
            state = self.state(player)
            recent = state.recovering(self.today) if self.today is not None else None
            step = injury_model().recovery_step(recent, self.today) if recent else 0
            key = (player.player_id, player.academic_year, step)
            cached = self._abilities.get(key)
            if cached is None:
                if self._fields is None:
                    self._fields = self._config_fields()
                values = bytearray(state.values)
                if step:
                    self._recovery_drop(values, recent, step)
                cached = unpack_abilities(
                    bytes(values), player,
                    config_fields=self._fields, pitch_types=self._pitch_types(),
                )
                self._abilities[key] = cached
            return cached

    def _recovery_drop(self, values: bytearray, injury: Injury, step: int) -> None:
        """復帰直後：1〜100の能力と変化球の質・制球を割合で、球速を km/h で下げる。"""
        share, kmh = injury_model().recovery_drop(injury, step)
        velocity = SCALARS.index("velocity_kmh")
        for index in range(len(SCALARS)):
            if not values[index]:
                continue
            if index == velocity:
                values[index] = max(100, values[index] - kmh)
            else:
                values[index] = max(1, values[index] - round(values[index] * share))
        pitches = len(SCALARS) + len(FIELD_POSITIONS)
        for offset in range(pitches, len(values), PITCH_FIELDS):
            for field in (1, 2):
                values[offset + field] = max(
                    1, values[offset + field] - round(values[offset + field] * share),
                )

    # ---- 怪我 ----

    def set_today(self, day: date) -> None:
        with self._lock:
            self.today = day

    def injury(self, player: Player, day: date | None = None) -> Injury | None:
        """その日（省くと今日）に怪我で休んでいれば、その怪我。"""
        day = day or self.today
        if day is None:
            return None
        return self.state(player).injured_on(day)

    def condition(self, player: Player, day: date) -> tuple[bool, int]:
        """(怪我で休んでいるか, 復帰直後の段階)。試合の出場メンバーと能力の作り直しに使う。"""
        state = self.state(player)
        if state.injured_on(day) is not None:
            return True, 0
        recent = state.recovering(day)
        return False, injury_model().recovery_step(recent, day) if recent else 0

    def after_game(
        self, appearances, *, day: date, rng,
    ) -> list[tuple[Player, Injury]]:
        """試合の怪我。``appearances`` は (選手, 投げた球数, 7日間の球数, 前の日から続けて
        投げた日数)。投げていなければ球数は0。怪我をした (選手, 怪我) を返す。"""
        model = injury_model()
        out = []
        with self._lock:
            for player, pitches, load7, consecutive in appearances:
                state = self.state(player)
                if state.injured_on(day) is not None:
                    continue
                chance, overuse = model.match_chance(
                    pitches=pitches, load7=load7, consecutive=consecutive,
                    level=self.injury_level,
                )
                if rng.random() < chance:
                    injury = model.draw(rng, day + timedelta(days=1), overuse=overuse)
                    state.injuries.append(injury)
                    out.append((player, injury))
        return out

    def _practice_injuries(self, first: date) -> None:
        """``first`` から始まる月の練習の怪我（その月のどこかの日から休む）。"""
        model = injury_model()
        if not model.rate(self.injury_level):
            return
        year = school_year_of(first)
        for school_id in self.school_ids:
            self.roster(year, school_id)
        days = ((first + timedelta(days=32)).replace(day=1) - first).days
        namespace = model.config["rng_namespaces"]["practice"]
        for school_id in self.schools(year):
            rng = rng_for(
                self.career_seed,
                namespace.format(month=first.strftime("%Y-%m"), school_id=school_id),
            )
            for player in self.roster(year, school_id).players:
                state = self.state(player)
                chance = model.practice_chance(
                    pitcher=player.primary_position == "P",
                    season_games=state.season_games, level=self.injury_level,
                )
                if rng.random() >= chance:
                    continue
                start = first + timedelta(days=rng.randrange(days))
                if state.injured_on(start) is not None:
                    continue
                state.injuries.append(model.draw(rng, start))

    # ---- 成長 ----

    def reset_appearance_counters(self) -> None:
        """新規開始前の出場経験を区切る。能力・怪我・成長済み月は変更しない。

        開始前の試合を処理し終えた直後だけ呼ぶ。通常の月次成長・年度更新や
        セーブの読込では呼ばない。
        """
        with self._lock:
            for states in self._states.values():
                for state in states.values():
                    state.games = 0
                    state.season_games = 0

    def record_games(self, school_id: str, players: Iterable[Player]) -> None:
        """公式戦に出た選手（毎月の成長で少し足す。怪我の起きやすさにも使う）。"""
        with self._lock:
            for player in players:
                state = self.state(player)
                state.games = min(255, state.games + 1)
                state.season_games = min(255, state.season_games + 1)

    def grow(self, month: date) -> None:
        """``month`` の月の分を伸ばす（その月が終わった次の日に呼ぶ）。"""
        with self._lock:
            first = month.replace(day=1)
            if self.grown_through is not None and first <= self.grown_through:
                return
            year = school_year_of(month)
            if year <= self.closed_through:
                return
            for school_id in self.school_ids:
                self.roster(year, school_id)
            namespace = self.growth.config["rng_namespaces"]["month"]
            for school_id in self.schools(year):
                practice_multiplier = (self.coaches.practice_for(school_id, first)[2]
                                       if self.coaches is not None else 1.0)
                rng = rng_for(
                    self.career_seed,
                    namespace.format(month=month.strftime("%Y-%m"), school_id=school_id),
                )
                days = ((first + timedelta(days=32)).replace(day=1) - first).days
                for player in self.roster(year, school_id).players:
                    state = self.state(player)
                    # 怪我で休んだ日の分は伸びない
                    healthy = days - sum(
                        1 for offset in range(days)
                        if state.injured_on(first + timedelta(days=offset)) is not None
                    ) if state.injuries else days
                    self.growth.grow(
                        state.values, position=player.primary_position,
                        grade=player.academic_year, type_index=state.growth_type,
                        potential=round(state.potential * healthy / days),
                        velocity_potential=round(state.velocity_potential * healthy / days),
                        games=state.games,
                        month=month.month, rng=rng,
                        practice_multiplier=practice_multiplier,
                    )
                    state.games = 0
                    if month.month == 3:
                        state.season_games = 0
            if month.month == 3:
                self._year_end[year] = {
                    school_id: self._pack_roster_states(year, school_id)
                    for school_id in self.schools(year)
                }
            # 次の月の練習の怪我
            self._practice_injuries((month.replace(day=1) + timedelta(days=32)).replace(day=1))
            self.version += 1
            self._abilities = {}
            self.grown_through = first

    def _pack_roster_states(self, year: int, school_id: str) -> bytes:
        states = self._states[school_id]
        return _pack_states(self.first_year, {
            key: states[key]
            for key in (
                (p.entry_year, p.roster_no) for p in self.roster(year, school_id).players
            )
        })

    def drop_year_end(self, year: int) -> None:
        """年度末の能力を履歴に書き出したら、セーブからは手放す。"""
        with self._lock:
            self._year_end.pop(year, None)

    def closed_record(self, year: int, school_id: str) -> bytes:
        """閉じた年度の名簿（名前・出身など）と年度末の能力・成長の状態を詰めて圧縮した
        もの（試合履歴の ``closed_rosters`` に入れる）。開始前の年度には能力がない。"""
        with self._lock:
            packed = (
                pack_school(self.roster(year, school_id), first_year=self.first_year)
                if year == self.first_year - 1 else self._packed[(year, school_id)]
            )
            school_name, program_id, cohort_policy, source, names, small = packed
            header = json.dumps({
                "year": year, "school_id": school_id, "first_year": self.first_year,
                "career_seed": self.career_seed, "school_name": school_name,
                "program_id": program_id, "cohort_policy": cohort_policy,
                "name_source": source, "names": names, "small": len(small),
            }, ensure_ascii=False).encode("utf-8")
            states = self._year_end.get(year, {}).get(school_id, b"")
            return zlib.compress(
                len(header).to_bytes(4, "big") + header + small + states, 9,
            )

    # ---- 閉じた年度 ----

    def forget(self, year: int) -> None:
        """閉じた年度の名簿を手放す（履歴に書き出したあと）。翌年度の名簿は先につくる。
        卒業した選手の能力も手放す。"""
        with self._lock:
            schools = self.schools(year)
            for school_id in schools:
                self.roster(year + 1, school_id)
            for school_id in schools:
                self._packed.pop((year, school_id), None)
                kept = {
                    (p.entry_year, p.roster_no)
                    for y in self.years() if y > year
                    for p in self.roster(y, school_id).players
                }
                self._states[school_id] = {
                    key: state for key, state in self._states[school_id].items()
                    if key in kept
                }
            self._rosters = {
                key: value for key, value in self._rosters.items() if key[0] > year
            }
            self._abilities = {}
            self._year_end.pop(year, None)
            self.closed_through = max(self.closed_through, year)


def decode_closed_record(blob: bytes) -> list[dict]:
    """``RosterBook.closed_record`` を選手ごとの dict（``Player.to_dict()`` に、年度末の
    能力 ``abilities``（1項目1バイトの並び）・成長の型 ``growth_type``・潜在能力
    ``potential`` を足したもの）に戻す。能力のない年度は ``abilities`` が None。"""
    from .player_growth import POTENTIAL_SCALE, TYPES

    data = zlib.decompress(blob)
    size = int.from_bytes(data[:4], "big")
    header = json.loads(data[4:4 + size].decode("utf-8"))
    small = data[4 + size:4 + size + header["small"]]
    states = _unpack_states(header["first_year"], data[4 + size + header["small"]:])
    packed = (
        header["school_name"], header["program_id"], header["cohort_policy"],
        header["name_source"], header["names"], small,
    )
    year, school_id = header["year"], header["school_id"]
    first_year, seed = header["first_year"], header["career_seed"]
    out = []
    for (entry_year, roster_no, name, source, hometown, position, bats, throws) in unpack_school(
        packed, first_year=first_year,
    ):
        player_id = (
            _player_id(seed, first_year, school_id, roster_no) if entry_year <= first_year
            else _newcomer_id(seed, entry_year, school_id, roster_no)
        )
        state = states.get((entry_year, roster_no))
        out.append({
            **Player(
                player_id=player_id, school_id=school_id, program_id=header["program_id"],
                display_name=name, name_source=source, hometown_prefecture_code=hometown,
                academic_year=year - entry_year + 1, entry_year=entry_year,
                roster_no=roster_no, primary_position=position,
                position_group=_position_group(position), bats=bats, throws=throws,
                roster_status="active_core", generation_seed=seed,
            ).to_dict(),
            "abilities": list(state.values) if state is not None else None,
            "injuries": [
                {"start": i.start.isoformat(), "days": i.days, "severity": i.severity}
                for i in state.injuries
            ] if state is not None else [],
            "growth_type": TYPES[state.growth_type] if state is not None else None,
            "potential": state.potential / POTENTIAL_SCALE if state is not None else None,
            "velocity_potential": (
                state.velocity_potential / POTENTIAL_SCALE if state is not None else None
            ),
        })
    return out
