"""試合中の出場状態。DHなしの9人配置を扱い、先発選考や交代判断は行わない。"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from typing import Literal

from .team_strength import STARTING_POSITIONS, LineupEntry, StartingLineup, validate_starting_lineup


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
class ChangeMoment:
    """打席開始前に確定する変更の時点。打席番号は試合全体で1から数える。"""
    inning: int
    half: str
    next_plate_appearance_no: int

    def __post_init__(self):
        if (type(self.inning) is not int or self.inning < 1
                or self.half not in ("top", "bottom")
                or type(self.next_plate_appearance_no) is not int
                or self.next_plate_appearance_no < 1):
            raise ValueError("invalid change moment")


@dataclass(frozen=True, slots=True)
class LineupChange:
    sequence: int
    school_id: str
    kind: _ChangeKind
    batting_order: int | None
    outgoing_player_id: str | None
    incoming_player_id: str | None
    defensive_changes: tuple[DefensiveChange, ...]
    moment: ChangeMoment | None = None

    def to_dict(self) -> dict:
        out = asdict(self)
        out["defensive_changes"] = [asdict(change) for change in self.defensive_changes]
        return out


@dataclass(frozen=True, slots=True)
class MatchLineupSlot:
    batting_order: int
    player_id: str
    defensive_position: str


@dataclass(frozen=True, slots=True)
class TeamMatchParticipation:
    school_id: str
    starting_lineup: tuple[MatchLineupSlot, ...]
    starting_pitcher_id: str
    changes: tuple[LineupChange, ...]
    fielding_player_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "school_id": self.school_id,
            "starting_lineup": [asdict(slot) for slot in self.starting_lineup],
            "starting_pitcher_id": self.starting_pitcher_id,
            "changes": [change.to_dict() for change in self.changes],
            "fielding_player_ids": list(self.fielding_player_ids),
        }

    @classmethod
    def from_dict(cls, value: dict) -> TeamMatchParticipation:
        try:
            return cls(
                value["school_id"],
                tuple(MatchLineupSlot(**slot) for slot in value["starting_lineup"]),
                value["starting_pitcher_id"],
                tuple(LineupChange(
                    **{key: item[key] for key in ("sequence", "school_id", "kind", "batting_order",
                                                   "outgoing_player_id", "incoming_player_id")},
                    defensive_changes=tuple(DefensiveChange(**c) for c in item["defensive_changes"]),
                    moment=ChangeMoment(**item["moment"]),
                ) for item in value["changes"]),
                tuple(value["fielding_player_ids"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("invalid team participation record") from exc


@dataclass(frozen=True, slots=True)
class _TeamStateData:
    batting_order: tuple[BattingOrderSlot, ...]
    defense: tuple[DefensiveAssignment, ...]
    exited: frozenset[str] = frozenset()
    history: tuple[LineupChange, ...] = ()
    fielding: frozenset[str] = frozenset()


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

    @property
    def fielding_player_ids(self) -> frozenset[str]:
        return self._data.fielding

    def record_fielding_appearance(self) -> None:
        """実際の守備開始時と交代時だけ呼ぶ。成長・怪我の計算は変更しない。"""
        if any(slot.player_id not in self.fielding_player_ids for slot in self.batting_order):
            self._data = replace(self._data, fielding=self.fielding_player_ids | self.active_player_ids)

    def participation(self) -> TeamMatchParticipation:
        return TeamMatchParticipation(
            self.school_id,
            tuple(MatchLineupSlot(e.batting_order, e.player_id, e.defensive_position)
                  for e in sorted(self.initial_lineup.entries, key=lambda e: e.batting_order)),
            self.initial_lineup.player_for_position("P"), self.history,
            tuple(sorted(self.fielding_player_ids)),
        )

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
                actual_pitcher_id: str | None = None,
                moment: ChangeMoment | None = None) -> LineupChange | None:
        self._validate(candidate, actual_pitcher_id)
        if candidate == self._data:
            return None
        changes = tuple(
            DefensiveChange(before.defensive_position, before.player_id, after.player_id)
            for before, after in zip(self.defensive_alignment, candidate.defense, strict=True)
            if before.player_id != after.player_id
        )
        change = LineupChange(len(self.history) + 1, self.school_id, kind, slot, outgoing,
                              incoming, changes, moment)
        candidate = replace(candidate, history=(*self.history, change))
        self._data = candidate
        return change

    def change_positions(self, assignments: Mapping[str, str], *,
                         moment: ChangeMoment | None = None) -> LineupChange | None:
        """位置→選手IDの交換・循環をまとめて適用し、打順は維持する。"""
        return self._change_positions(assignments, "position_change", moment=moment)

    def _change_positions(self, assignments: Mapping[str, str], kind: _ChangeKind, *,
                          actual_pitcher_id: str | None = None,
                          moment: ChangeMoment | None = None) -> LineupChange | None:
        positions = self._positions(assignments)
        candidate = replace(self._data, defense=self._alignment(positions))
        return self._commit(candidate, kind, actual_pitcher_id=actual_pitcher_id, moment=moment)

    def swap_positions(self, first: str, second: str, *,
                       moment: ChangeMoment | None = None) -> LineupChange | None:
        return self.change_positions({first: self.player_for_position(second),
                                      second: self.player_for_position(first)}, moment=moment)

    def substitute(self, outgoing_player_id: str, incoming_player_id: str, *,
                   defensive_changes: Mapping[str, str] | None = None,
                   moment: ChangeMoment | None = None) -> LineupChange:
        """控えが退場者の打順枠を継承。付随する位置変更も1操作で検証する。"""
        return self._substitute(outgoing_player_id, incoming_player_id,
                                defensive_changes or {}, "substitution", moment=moment)

    def _substitute(self, outgoing: str, incoming: str, defensive_changes: Mapping[str, str],
                    kind: _ChangeKind, *, actual_pitcher_id: str | None = None,
                    moment: ChangeMoment | None = None) -> LineupChange:
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
                              incoming=incoming, actual_pitcher_id=actual_pitcher_id, moment=moment)
        # A bench player always changes the batting slot; this cannot be a no-op.
        assert change is not None
        return change

    def change_pitcher(self, incoming_player_id: str, *, outgoing_player_id: str | None = None,
                       defensive_changes: Mapping[str, str] | None = None,
                       moment: ChangeMoment | None = None) -> LineupChange | None:
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
            return self._change_positions(changes, "pitcher_change", actual_pitcher_id=incoming_player_id,
                                          moment=moment)
        outgoing = outgoing_player_id if outgoing_player_id is not None else current
        if outgoing not in self.active_player_ids:
            raise ValueError("outgoing player is not active")
        position = next(a.defensive_position for a in self.defensive_alignment if a.player_id == outgoing)
        changes = {position: current, "P": incoming_player_id, **(defensive_changes or {})}
        return self._substitute(outgoing, incoming_player_id, changes, "pitcher_change",
                                actual_pitcher_id=incoming_player_id, moment=moment)


def _participation_start(record: TeamMatchParticipation, reference_year: int,
                         registered: Iterable[str] | None = None) -> TeamMatchState:
    if not isinstance(record.starting_pitcher_id, str) or not record.starting_pitcher_id:
        raise ValueError("starting pitcher is required")
    if registered is None:
        registered = {s.player_id for s in record.starting_lineup} | {
            c.after_player_id for change in record.changes for c in change.defensive_changes
        }
    lineup = StartingLineup(record.school_id, reference_year, tuple(
        LineupEntry(s.batting_order, s.defensive_position, s.player_id, 0.0)
        for s in record.starting_lineup
    ))
    return TeamMatchState(lineup, registered, actual_pitcher_id=record.starting_pitcher_id)


def apply_lineup_change(state: TeamMatchState, change: LineupChange) -> None:
    """保存した差分を既存の状態操作で検証して適用する。失敗時は状態を保つ。"""
    if (type(change.sequence) is not int or change.sequence != len(state.history) + 1
            or change.school_id != state.school_id or not isinstance(change.moment, ChangeMoment)
            or (change.batting_order is not None
                and (type(change.batting_order) is not int or not 1 <= change.batting_order <= 9))):
        raise ValueError("invalid lineup change sequence, school, slot or moment")
    positions = {}
    for assignment in change.defensive_changes:
        pos = assignment.defensive_position
        if (pos in positions or state.player_for_position(pos) != assignment.before_player_id
                or assignment.before_player_id == assignment.after_player_id):
            raise ValueError("lineup change does not continue previous alignment")
        positions[pos] = assignment.after_player_id
    before = state._data
    try:
        if change.kind == "position_change":
            applied = state.change_positions(positions, moment=change.moment)
        elif change.kind == "substitution":
            applied = state.substitute(change.outgoing_player_id, change.incoming_player_id,
                                       defensive_changes=positions, moment=change.moment)
        elif change.kind == "pitcher_change" and "P" in positions:
            applied = state.change_pitcher(positions["P"], outgoing_player_id=change.outgoing_player_id,
                                           defensive_changes=positions, moment=change.moment)
        else:
            raise ValueError("invalid lineup change kind")
        if applied != change:
            raise ValueError("lineup change differs from the applied operation")
    except (ValueError, KeyError, TypeError):
        state._data = before
        raise


def replay_team_participation(record: TeamMatchParticipation, reference_year: int,
                              registered: Iterable[str] | None = None) -> TeamMatchState:
    """能力・現在名簿を使わず開始配置と差分だけから最終配置・退場者を復元する。"""
    state = _participation_start(record, reference_year, registered)
    participants = set(state.active_player_ids)
    previous = None
    for change in record.changes:
        moment = change.moment
        if moment is None:
            raise ValueError("lineup change requires a moment")
        key = (moment.inning * 2 + (moment.half == "bottom"), moment.next_plate_appearance_no)
        if previous is not None and (
            key[0] < previous[0] or key[1] < previous[1]
            or (key[0] != previous[0] and key[1] == previous[1])
        ):
            raise ValueError("lineup change moments are out of order")
        apply_lineup_change(state, change)
        participants.update(state.active_player_ids)
        previous = key
    fielding = frozenset(record.fielding_player_ids)
    if len(fielding) != len(record.fielding_player_ids) or not fielding <= participants:
        raise ValueError("invalid fielding appearances")
    state._data = replace(state._data, fielding=fielding)
    return state


def validate_match_participation(
    records: tuple[TeamMatchParticipation, ...], *, team_ids: tuple[str, str],
    reference_year: int, last_inning: int, ending_half: str, total_plate_appearances: int,
    known_ids: Mapping[str, Iterable[str]] | None = None, events: Iterable | None = None,
    final_states: Mapping[str, TeamMatchState] | None = None,
    half_plate_appearances: Mapping[tuple[int, str], int] | None = None,
) -> None:
    if tuple(record.school_id for record in records) != team_ids:
        raise ValueError("participation must contain both teams in match order")
    ranges = {}
    if half_plate_appearances is not None:
        next_pa = 1
        for half, count in half_plate_appearances.items():
            if type(count) is not int or count < 0:
                raise ValueError("invalid half inning plate appearance count")
            ranges[half] = (next_pa, next_pa + count - 1)
            next_pa += count
        if next_pa - 1 != total_plate_appearances:
            raise ValueError("inning plate appearances differ from batter totals")
    for record in records:
        previous = None
        for change in record.changes:
            moment = change.moment
            if not isinstance(moment, ChangeMoment):
                raise ValueError("lineup change requires a moment")
            key = (moment.inning * 2 + (moment.half == "bottom"), moment.next_plate_appearance_no)
            if previous is not None and (key[0] < previous[0] or key[1] < previous[1]
                                         or (key[0] != previous[0] and key[1] == previous[1])):
                raise ValueError("lineup change moments are out of order")
            previous = key
            if (moment.inning > last_inning or moment.next_plate_appearance_no > total_plate_appearances
                    or (moment.inning == last_inning and ending_half == "top" and moment.half == "bottom")):
                raise ValueError("lineup change occurs outside the played game")
            if half_plate_appearances is not None:
                first, last = ranges.get((moment.inning, moment.half), (1, 0))
                if not first <= moment.next_plate_appearance_no <= last:
                    raise ValueError("lineup change plate appearance does not belong to its half inning")
    def check_final(states):
        for record in records:
            actual = states[record.school_id]
            if actual.participation() != record:
                raise ValueError("participation differs from actual game appearances")
            if final_states is not None:
                expected = final_states[record.school_id]
                if (actual.batting_order != expected.batting_order
                        or actual.defensive_alignment != expected.defensive_alignment
                        or actual.exited_player_ids != expected.exited_player_ids
                        or actual.fielding_player_ids != expected.fielding_player_ids):
                    raise ValueError("replayed final lineup differs from runtime state")

    if events is None and half_plate_appearances is None:
        check_final({r.school_id: replay_team_participation(
            r, reference_year, None if known_ids is None else known_ids[r.school_id]) for r in records})
        return
    # 全打席がある本番結果で時点・打者・P・守備出場を厳密照合する。
    # 保存するのは開始配置・成功した差分・出場IDだけで、打席ごとの状態は残さない。
    states = {r.school_id: _participation_start(r, reference_year,
               None if known_ids is None else known_ids[r.school_id]) for r in records}
    pending = sorted((c for r in records for c in r.changes),
                     key=lambda c: (c.moment.next_plate_appearance_no, team_ids.index(c.school_id), c.sequence))
    cursor = 0
    if events is None:
        # 表裏の開始と変更時点だけを再生すれば、全打席を残さず守備出場を照合できる。
        spans = [(first, last, half) for half, (first, last) in ranges.items() if first <= last]
        checkpoints = sorted({first for first, _, _ in spans}
                             | {c.moment.next_plate_appearance_no for c in pending})
        span_index = 0
        for pa in checkpoints:
            while cursor < len(pending) and pending[cursor].moment.next_plate_appearance_no <= pa:
                change = pending[cursor]
                apply_lineup_change(states[change.school_id], change)
                cursor += 1
            while pa > spans[span_index][1]:
                span_index += 1
            _, half = spans[span_index][2]
            defense = team_ids[1] if half == "top" else team_ids[0]
            states[defense].record_fielding_appearance()
        check_final(states)
        return
    batting_slots = dict.fromkeys(team_ids, 1)
    previous_half = None
    for event in events:
        changed = set()
        while cursor < len(pending) and pending[cursor].moment.next_plate_appearance_no <= event.plate_appearance_no:
            change = pending[cursor]
            if (change.moment.next_plate_appearance_no != event.plate_appearance_no
                    or (change.moment.inning, change.moment.half) != (event.inning, event.half)):
                raise ValueError("lineup change moment differs from the next plate appearance")
            apply_lineup_change(states[change.school_id], change)
            changed.add(change.school_id)
            cursor += 1
        offense, defense = event.offense_school_id, event.defense_school_id
        if (states[offense].player_at_order(batting_slots[offense]) != event.batter_id
                or states[defense].current_pitcher_id != event.pitcher_id):
            raise ValueError("event batter or pitcher differs from lineup history")
        batting_slots[offense] = batting_slots[offense] % 9 + 1
        half = (event.inning, event.half)
        if half != previous_half or defense in changed:
            states[defense].record_fielding_appearance()
        previous_half = half
    if cursor != len(pending):
        raise ValueError("unapplied lineup changes")
    check_final(states)
