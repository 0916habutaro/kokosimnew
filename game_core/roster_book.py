"""全国の名簿：年度ごとの部員と、選手ごとの名前・出身・能力。セーブに入る。

乱数の種から作るのは最初の年度の名簿と新入生だけ（新規開始と入学のとき）。
進級した選手は前の年度の名簿から名前・出身・能力を引き継ぐ。能力は年度ごとに
持つ（3月に始まる大会は前の年度の名簿と能力で戦う）。成長（game_definition.md
§3.1）ができるまでは、進級のときに学年の差（``player_generation_v1`` の
``grade_adjustment``）を能力に足す。

セーブを小さくするため、書き出すときは学校・年度ごとに詰めた形にする
（選手IDは乱数の種・学校・入学年度・番号から作り直す。能力は1項目1バイト）。
読み込んだあとは、使う学校の分だけ元の形に戻す。
"""
from __future__ import annotations

from dataclasses import replace
import threading
from typing import Callable

from phase2_engine.models import Team

from .abilities import (
    BATTER_ABILITIES,
    CATCHER_ABILITIES,
    FIELD_POSITIONS,
    PITCHER_ABILITIES,
    PitchAbility,
    PlayerAbilitySnapshot,
    validate_ability_snapshot,
)
from .career_rosters import _newcomer_id, advance_school_roster
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


def pack_school(roster: SchoolRoster, abilities: list[bytes], *, first_year: int) -> tuple:
    """学校・年度の名簿を詰める：名前は改行でつなぎ、小さい項目は1バイトずつ、
    能力は長さを前に付けてつなぐ（同じ種類の値をまとめると圧縮が効く）。"""
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
        b"".join(bytes([len(data)]) + data for data in abilities),
    )


def unpack_school(packed: tuple, *, first_year: int) -> list[tuple]:
    """(入学年度, 番号, 名前, 名前の出典, 出身, 守備位置, 打, 投, 能力) の並び。"""
    _, _, _, source, names, small, abilities = packed
    rows = []
    offset = 0
    for index, name in enumerate(names.split("\n")):
        entry, roster_no, hometown, position, bats, throws = small[index * 6:index * 6 + 6]
        size = abilities[offset]
        rows.append((
            entry + first_year - 2, roster_no, name, source, f"{hometown:02d}",
            POSITIONS[position], BATS[bats], THROWS[throws],
            abilities[offset + 1:offset + 1 + size],
        ))
        offset += 1 + size
    return rows


class RosterBook:
    """年度ごとの名簿と選手の能力。

    ``team_for``（学校ID → Team）・名前の生成・能力の生成はセーブに入れず、
    読み込んだあとに ``bind`` でつなぎ直す。
    """

    def __init__(
        self,
        team_for: Callable[[str], Team],
        *,
        first_year: int,
        career_seed: int,
        generator: PlayerRosterGenerator | None = None,
        ability_generator=None,
    ):
        self.first_year = first_year
        self.career_seed = career_seed
        # この年度までの名簿は手放した（閉じた年度。履歴に書き出してある）
        self.closed_through = first_year - 2
        # (年度, 学校ID) → 詰めた名簿（セーブに入る）
        self._packed: dict[tuple[int, str], tuple] = {}
        self.bind(team_for, generator=generator, ability_generator=ability_generator)

    def bind(self, team_for, *, generator=None, ability_generator=None) -> None:
        self.team_for = team_for
        self.generator = generator or PlayerRosterGenerator()
        self._ability_generator = ability_generator
        self._rosters: dict[tuple[int, str], SchoolRoster] = {}
        self._abilities: dict[tuple[int, str], PlayerAbilitySnapshot] = {}
        self._fields: dict | None = None
        # 画面は別のスレッドで能力を読む（日付を進めるスレッドと同時）
        self._lock = threading.RLock()

    def __getstate__(self):
        return {
            "first_year": self.first_year,
            "career_seed": self.career_seed,
            "closed_through": self.closed_through,
            "_packed": self._packed,
        }

    def __setstate__(self, data):
        self.__dict__.update(data)
        self.bind(None)

    # ---- 能力の生成（入学・新規開始のときだけ） ----

    @property
    def ability_generator(self):
        if self._ability_generator is None:
            from .school_intake import SchoolAwarePlayerAbilityGenerator

            self._ability_generator = SchoolAwarePlayerAbilityGenerator()
        return self._ability_generator

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

    def _shifted(self, snapshot: PlayerAbilitySnapshot, player: Player) -> PlayerAbilitySnapshot:
        """学年が変わった能力：学年の差（grade_adjustment）を足す・戻す。

        成長（game_definition.md §3.1）ができるまでの仮の伸び。
        """
        params = self._base().params
        before, after = str(snapshot.academic_year), str(player.academic_year)
        changes = {}
        for name in SCALARS:
            value = getattr(snapshot, name)
            if value is None:
                continue
            grades = params["grade_adjustment"]
            low, high = 1, 100
            if name in PITCHER_ABILITIES:
                pitcher = params["pitcher_abilities"][name]
                grades = pitcher.get("grade_adjustment", grades)
                low, high = int(pitcher.get("min", 1)), int(pitcher.get("max", 100))
            delta = float(grades[after]) - float(grades[before])
            changes[name] = min(high, max(low, int(round(value + delta))))
        shifted = replace(
            snapshot, **changes,
            reference_year=player.entry_year + player.academic_year - 1,
            academic_year=player.academic_year,
        )
        validate_ability_snapshot(shifted)
        return shifted

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
        if year == self.first_year:
            roster = self.generator.generate_school(team, year, self.career_seed)
            abilities = {
                p.player_id: self.ability_generator.generate(p, year, self.career_seed)
                for p in roster.players
            }
        else:
            if (year - 1, school_id) not in self._packed and year - 1 != self.first_year:
                raise ValueError(f"{school_id}: roster {year - 1} is not kept")
            previous = self.roster(year - 1, school_id)
            transition = advance_school_roster(
                previous, team, next_year=year,
                career_seed=self.career_seed, generator=self.generator,
            )
            roster = transition.roster
            new_ids = {p.player_id for p in transition.newcomers}
            abilities = {
                p.player_id: (
                    self.ability_generator.generate(p, year, self.career_seed)
                    if p.player_id in new_ids
                    else self._shifted(
                        self.ability(replace(p, academic_year=p.academic_year - 1)), p,
                    )
                )
                for p in roster.players
            }
        self._store(roster, abilities)
        return roster

    def _store(self, roster: SchoolRoster, abilities: dict) -> None:
        pitch_types = self._pitch_types()
        key = (roster.reference_year, roster.school_id)
        self._packed[key] = pack_school(
            roster,
            [pack_abilities(abilities[p.player_id], pitch_types) for p in roster.players],
            first_year=self.first_year,
        )
        self._rosters[key] = roster
        for p, row in zip(roster.players, self._rows(key)):
            self._abilities[(roster.reference_year, p.player_id)] = self._unpack_ability(row[-1], p)

    def _rows(self, key: tuple[int, str]) -> list[tuple]:
        return unpack_school(self._packed[key], first_year=self.first_year)

    def _unpack_ability(self, data: bytes, player: Player) -> PlayerAbilitySnapshot:
        if self._fields is None:
            self._fields = self._config_fields()
        return unpack_abilities(
            data, player, config_fields=self._fields, pitch_types=self._pitch_types(),
        )

    def _player_id(self, school_id: str, entry_year: int, roster_no: int) -> str:
        # 最初の年度の部員と新入生で作り方が違う（players.py・career_rosters.py）
        if entry_year <= self.first_year:
            return _player_id(self.career_seed, self.first_year, school_id, roster_no)
        return _newcomer_id(self.career_seed, entry_year, school_id, roster_no)

    def _unpack(self, year: int, school_id: str) -> SchoolRoster:
        school_name, program_id, cohort_policy = self._packed[(year, school_id)][:3]
        rows = self._rows((year, school_id))
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
                 position, bats, throws, _) in rows
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
        入学していない新入生はいない。
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

    def ability(self, player: Player) -> PlayerAbilitySnapshot:
        """その選手のその年度（名簿の年度）の能力。学校の編集の補正は入っていない。"""
        with self._lock:
            return self._ability(player)

    def _ability(self, player: Player) -> PlayerAbilitySnapshot:
        year = player.entry_year + player.academic_year - 1
        key = (year, player.player_id)
        cached = self._abilities.get(key)
        if cached is not None:
            return cached
        if year == self.first_year - 1:
            # 開始前の年度は、最初の年度の能力から学年の差を戻す
            current = self.ability(replace(player, academic_year=player.academic_year + 1))
            snapshot = self._shifted(current, player)
        else:
            self.roster(year, player.school_id)
            snapshot = self._abilities.get(key)
            if snapshot is None:
                data = next(
                    row[-1] for row in self._rows((year, player.school_id))
                    if (row[0], row[1]) == (player.entry_year, player.roster_no)
                )
                snapshot = self._unpack_ability(data, player)
        self._abilities[key] = snapshot
        return snapshot

    # ---- 閉じた年度 ----

    def forget(self, year: int) -> None:
        """閉じた年度の名簿を手放す（履歴に書き出したあと）。翌年度の名簿は先につくる。"""
        with self._lock:
            self._forget(year)

    def _forget(self, year: int) -> None:
        schools = self.schools(year)
        for school_id in schools:
            self.roster(year + 1, school_id)
        for school_id in schools:
            self._packed.pop((year, school_id), None)
            self._rosters.pop((year, school_id), None)
        self._rosters = {
            key: value for key, value in self._rosters.items() if key[0] > year
        }
        self._abilities = {
            key: value for key, value in self._abilities.items() if key[0] > year
        }
        self.closed_through = max(self.closed_through, year)
