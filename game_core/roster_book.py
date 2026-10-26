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
from datetime import date
import threading
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


class PlayerState:
    """選手ごとの能力（1項目1バイト）と成長の状態。"""

    __slots__ = ("values", "growth_type", "potential", "games")

    def __init__(self, values: bytearray, growth_type: int, potential: int, games: int = 0):
        self.values = values
        self.growth_type = growth_type
        self.potential = potential
        self.games = games


def _pack_states(first_year: int, states: dict[tuple[int, int], PlayerState]) -> bytes:
    out = bytearray()
    for (entry_year, roster_no), state in sorted(states.items()):
        out.extend((
            entry_year - first_year + 2, roster_no, state.growth_type,
            state.potential, state.games, len(state.values),
        ))
        out.extend(state.values)
    return bytes(out)


def _unpack_states(first_year: int, data: bytes) -> dict[tuple[int, int], PlayerState]:
    states = {}
    offset = 0
    while offset < len(data):
        entry, roster_no, growth_type, potential, games, size = data[offset:offset + 6]
        offset += 6
        states[(entry + first_year - 2, roster_no)] = PlayerState(
            bytearray(data[offset:offset + size]), growth_type, potential, games,
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
            "career_seed": self.career_seed,
            "school_ids": self.school_ids,
            "closed_through": self.closed_through,
            "version": self.version,
            "_packed": self._packed,
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

    def _pitch_types(self) -> list[str]:
        return list(self._base().params["pitch_repertoire"]["pitch_types"])

    def _new_state(self, player: Player, year: int) -> PlayerState:
        """入学（新規開始の部員を含む）：能力と成長の型・潜在能力をつくる。"""
        snapshot = self.ability_generator.generate(player, year, self.career_seed)
        program_z = self.ability_generator.intake_model.profile(
            school_id=player.school_id, entry_year=player.entry_year,
            base_seed=self.career_seed,
        ).program_quality_z
        namespace = self.growth.config["rng_namespaces"]["player"].format(
            entry_year=player.entry_year, school_id=player.school_id,
            roster_no=player.roster_no,
        )
        growth_type, potential = self.growth.draw(rng_for(self.career_seed, namespace), program_z)
        return PlayerState(
            bytearray(pack_abilities(snapshot, self._pitch_types())), growth_type, potential,
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
        for player in newcomers:
            states[(player.entry_year, player.roster_no)] = self._new_state(player, year)
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

    def ability(self, player: Player) -> PlayerAbilitySnapshot:
        """その選手の今の能力。学校の編集の補正は入っていない。"""
        with self._lock:
            key = (player.player_id, player.academic_year)
            cached = self._abilities.get(key)
            if cached is None:
                if self._fields is None:
                    self._fields = self._config_fields()
                cached = unpack_abilities(
                    bytes(self.state(player).values), player,
                    config_fields=self._fields, pitch_types=self._pitch_types(),
                )
                self._abilities[key] = cached
            return cached

    # ---- 成長 ----

    def record_games(self, school_id: str, players: Iterable[Player]) -> None:
        """公式戦に出た選手（毎月の成長で少し足す）。"""
        with self._lock:
            for player in players:
                state = self.state(player)
                state.games = min(255, state.games + 1)

    def grow(self, month: date) -> None:
        """``month`` の月の分を伸ばす（その月が終わった次の日に呼ぶ）。"""
        with self._lock:
            year = school_year_of(month)
            if year <= self.closed_through:
                return
            for school_id in self.school_ids:
                self.roster(year, school_id)
            namespace = self.growth.config["rng_namespaces"]["month"]
            for school_id in self.schools(year):
                rng = rng_for(
                    self.career_seed,
                    namespace.format(month=month.strftime("%Y-%m"), school_id=school_id),
                )
                for player in self.roster(year, school_id).players:
                    state = self.state(player)
                    self.growth.grow(
                        state.values, position=player.primary_position,
                        grade=player.academic_year, type_index=state.growth_type,
                        potential=state.potential, games=state.games,
                        month=month.month, rng=rng,
                    )
                    state.games = 0
            self.version += 1
            self._abilities = {}

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
            self.closed_through = max(self.closed_through, year)
