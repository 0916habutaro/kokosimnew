"""試合中の出場状態。DHなしの9人配置を扱い、先発選考や交代判断は行わない。"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Literal

from .team_strength import STARTING_POSITIONS, StartingLineup, validate_starting_lineup


_ChangeKind = Literal["position_change", "substitution", "pitcher_change"]


@dataclass(frozen=True, slots=True)
class BattingOrderSlot:
    batting_order: int
    player_id: str


@dataclass(frozen=True, slots=True)
class DefensiveAssignment:
    defensive_position: str
    player_id: str


@dataclass(frozen=True, slots=True)
class DefensiveChange:
    defensive_position: str
    before_player_id: str
    after_player_id: str


@dataclass(frozen=True, slots=True)
class LineupChange:
    sequence: int
    kind: _ChangeKind
    batting_order: int | None
    outgoing_player_id: str | None
    incoming_player_id: str | None
    defensive_changes: tuple[DefensiveChange, ...]


@dataclass(frozen=True, slots=True)
class _TeamStateData:
    batting_order: tuple[BattingOrderSlot, ...]
    defense: tuple[DefensiveAssignment, ...]
    exited: frozenset[str] = frozenset()
    history: tuple[LineupChange, ...] = ()


class TeamMatchState:
    """登録者と、打順枠・実配置・退場者をまとめて検証する実行時の状態。

    公開するコレクションは不変。操作は候補全体の検証後に一度だけ状態を置換する。
    actual_pitcher_idを省略した初期化・validateは先発選考との内部整合だけを保証し、
    球数制限後の実際の投手との一致は保証しない。本番では先発確定後に初期化する。
    """

    __slots__ = ("_school_id", "_registered", "_available", "_initial_lineup", "_data")

    def __init__(self, starting_lineup: StartingLineup,
                 registered_player_ids: Iterable[str], *, actual_pitcher_id: str | None = None,
                 available_player_ids: Iterable[str] | None = None):
        validate_starting_lineup(starting_lineup)
        if not isinstance(starting_lineup.school_id, str) or not starting_lineup.school_id:
            raise ValueError("school_id is required")
        if isinstance(registered_player_ids, str):
            raise ValueError("registered players must be a collection of IDs")
        registered = frozenset(registered_player_ids)
        if any(not isinstance(pid, str) or not pid.strip() for pid in registered):
            raise ValueError("registered player IDs must be nonempty strings")
        self._school_id = starting_lineup.school_id
        self._registered = registered
        self._available = registered if available_player_ids is None else frozenset(available_player_ids)
        if not self._available <= registered:
            raise ValueError("available players must be registered")
        self._initial_lineup = starting_lineup
        positions = {entry.defensive_position: entry.player_id for entry in starting_lineup.entries}
        data = _TeamStateData(
            batting_order=tuple(
                BattingOrderSlot(entry.batting_order, entry.player_id)
                for entry in sorted(starting_lineup.entries, key=lambda e: e.batting_order)
            ),
            defense=self._alignment(positions),
        )
        self._validate(data, actual_pitcher_id)
        self._data = data

    @property
    def school_id(self) -> str:
        return self._school_id

    @property
    def registered_player_ids(self) -> frozenset[str]:
        return self._registered

    @property
    def available_player_ids(self) -> frozenset[str]:
        return self._available

    @property
    def initial_lineup(self) -> StartingLineup:
        """球数制限などを反映した開始配置。実行中の履歴とともに保持する。"""
        return self._initial_lineup

    @property
    def batting_order(self) -> tuple[BattingOrderSlot, ...]:
        return self._data.batting_order

    @property
    def defensive_alignment(self) -> tuple[DefensiveAssignment, ...]:
        return self._data.defense

    @property
    def active_player_ids(self) -> frozenset[str]:
        return frozenset(slot.player_id for slot in self.batting_order)

    @property
    def current_pitcher_id(self) -> str:
        # STARTING_POSITIONSの先頭はP。独立した投手IDを持たず、ずれを防ぐ。
        return self._data.defense[0].player_id

    @property
    def bench_player_ids(self) -> frozenset[str]:
        return self._available - self.active_player_ids - self.exited_player_ids

    @property
    def exited_player_ids(self) -> frozenset[str]:
        return self._data.exited

    @property
    def history(self) -> tuple[LineupChange, ...]:
        return self._data.history

    def player_at_order(self, batting_order: int) -> str:
        if type(batting_order) is not int or not 1 <= batting_order <= 9:
            raise ValueError("batting order must be 1..9")
        return self.batting_order[batting_order - 1].player_id

    def player_for_position(self, position: str) -> str:
        if position not in STARTING_POSITIONS:
            raise ValueError(f"unknown defensive position: {position}")
        return self.defensive_alignment[STARTING_POSITIONS.index(position)].player_id

    def validate(self, *, actual_pitcher_id: str | None = None) -> None:
        """外部の登板投手IDを渡した場合、その投手とP配置の一致も検証する。"""
        self._validate(self._data, actual_pitcher_id)

    def _validate(self, data: _TeamStateData, actual_pitcher_id: str | None = None) -> None:
        slots = data.batting_order
        if (len(slots) != 9 or any(type(s.batting_order) is not int for s in slots)
                or tuple(s.batting_order for s in slots) != tuple(range(1, 10))):
            raise ValueError("batting slots must be 1..9")
        if tuple(a.defensive_position for a in data.defense) != STARTING_POSITIONS:
            raise ValueError("defensive positions must contain the nine positions")
        batters = frozenset(s.player_id for s in slots)
        fielders = frozenset(a.player_id for a in data.defense)
        if len(batters) != 9 or len(fielders) != 9:
            raise ValueError("duplicate player in batting order or defense")
        if batters != fielders:
            raise ValueError("batting and defensive players differ without DH")
        if not batters <= self._registered or not data.exited <= self._registered:
            raise ValueError("unregistered player")
        if not batters <= self._available:
            raise ValueError("unavailable player")
        if batters & data.exited:
            raise ValueError("an exited player cannot reenter")
        if actual_pitcher_id is not None and data.defense[0].player_id != actual_pitcher_id:
            raise ValueError(
                f"P assignment {data.defense[0].player_id} differs from actual pitcher {actual_pitcher_id}"
            )

    @staticmethod
    def _alignment(positions: Mapping[str, str]) -> tuple[DefensiveAssignment, ...]:
        return tuple(DefensiveAssignment(pos, positions[pos]) for pos in STARTING_POSITIONS)

    def _positions(self, changes: Mapping[str, str]) -> dict[str, str]:
        if set(changes) - set(STARTING_POSITIONS):
            raise ValueError("unknown defensive position")
        return {**{a.defensive_position: a.player_id for a in self.defensive_alignment}, **changes}

    def _commit(self, candidate: _TeamStateData, kind: _ChangeKind, *, slot: int | None = None,
                outgoing: str | None = None, incoming: str | None = None,
                actual_pitcher_id: str | None = None) -> LineupChange | None:
        self._validate(candidate, actual_pitcher_id)
        if candidate == self._data:
            return None
        changes = tuple(
            DefensiveChange(before.defensive_position, before.player_id, after.player_id)
            for before, after in zip(self.defensive_alignment, candidate.defense, strict=True)
            if before.player_id != after.player_id
        )
        change = LineupChange(len(self.history) + 1, kind, slot, outgoing, incoming, changes)
        candidate = replace(candidate, history=(*self.history, change))
        self._data = candidate
        return change

    def change_positions(self, assignments: Mapping[str, str]) -> LineupChange | None:
        """位置→選手IDの交換・循環をまとめて適用し、打順は維持する。"""
        return self._change_positions(assignments, "position_change")

    def _change_positions(self, assignments: Mapping[str, str], kind: _ChangeKind, *,
                          actual_pitcher_id: str | None = None) -> LineupChange | None:
        positions = self._positions(assignments)
        candidate = replace(self._data, defense=self._alignment(positions))
        return self._commit(candidate, kind, actual_pitcher_id=actual_pitcher_id)

    def swap_positions(self, first: str, second: str) -> LineupChange | None:
        return self.change_positions({first: self.player_for_position(second),
                                      second: self.player_for_position(first)})

    def substitute(self, outgoing_player_id: str, incoming_player_id: str, *,
                   defensive_changes: Mapping[str, str] | None = None) -> LineupChange:
        """控えが退場者の打順枠を継承。付随する位置変更も1操作で検証する。"""
        return self._substitute(outgoing_player_id, incoming_player_id,
                                defensive_changes or {}, "substitution")

    def _substitute(self, outgoing: str, incoming: str, defensive_changes: Mapping[str, str],
                    kind: _ChangeKind, *, actual_pitcher_id: str | None = None) -> LineupChange:
        active = self.active_player_ids
        if outgoing not in active:
            raise ValueError("outgoing player is not active")
        if incoming not in self._registered:
            raise ValueError("incoming player is not registered")
        if incoming in self.exited_player_ids:
            raise ValueError("an exited player cannot reenter")
        if incoming in active:
            raise ValueError("incoming player is already active")
        slot = next(s.batting_order for s in self.batting_order if s.player_id == outgoing)
        position = next(a.defensive_position for a in self.defensive_alignment if a.player_id == outgoing)
        positions = self._positions({position: incoming, **defensive_changes})
        candidate = replace(
            self._data,
            batting_order=tuple(BattingOrderSlot(s.batting_order, incoming) if s.player_id == outgoing
                                else s for s in self.batting_order),
            defense=self._alignment(positions), exited=self.exited_player_ids | {outgoing},
        )
        change = self._commit(candidate, kind, slot=slot, outgoing=outgoing,
                              incoming=incoming, actual_pitcher_id=actual_pitcher_id)
        # A bench player always changes the batting slot; this cannot be a no-op.
        assert change is not None
        return change

    def change_pitcher(self, incoming_player_id: str, *, outgoing_player_id: str | None = None,
                       defensive_changes: Mapping[str, str] | None = None) -> LineupChange | None:
        """配置操作のみ。登板可否・球数・再登板の規則は呼出側で判断する。

        出場中の野手なら現投手と位置交換。控えなら原則現投手を交代させる。
        別の出場選手を交代対象に指定すると、その打順枠へ控え投手が入り、現投手はその守備へ残る。
        """
        current = self.current_pitcher_id
        if incoming_player_id == current:
            if outgoing_player_id is not None or defensive_changes:
                raise ValueError("current pitcher requires no replacement")
            return None
        if incoming_player_id in self.active_player_ids:
            if outgoing_player_id is not None:
                raise ValueError("position exchange does not retire a player")
            position = next(a.defensive_position for a in self.defensive_alignment
                            if a.player_id == incoming_player_id)
            changes = {position: current, "P": incoming_player_id, **(defensive_changes or {})}
            return self._change_positions(changes, "pitcher_change", actual_pitcher_id=incoming_player_id)
        outgoing = outgoing_player_id if outgoing_player_id is not None else current
        if outgoing not in self.active_player_ids:
            raise ValueError("outgoing player is not active")
        position = next(a.defensive_position for a in self.defensive_alignment if a.player_id == outgoing)
        changes = {position: current, "P": incoming_player_id, **(defensive_changes or {})}
        return self._substitute(outgoing, incoming_player_id, changes, "pitcher_change",
                                actual_pitcher_id=incoming_player_id)
