"""試合中の出場状態。DHの有無・役割を検証し、先発選考や交代判断は行わない。"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from typing import Literal

from .team_strength import STARTING_POSITIONS, LineupEntry, StartingLineup, DefensiveAssignment, validate_starting_lineup


_ChangeKind = Literal["position_change", "substitution", "pitcher_change", "dh_transition", "dh_plate_appearance", "dh_opponent_pitcher"]


@dataclass(frozen=True, slots=True)
class BattingOrderSlot:
    batting_order: int
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
    order: int = 0

    def __post_init__(self):
        if (type(self.inning) is not int or self.inning < 1
                or self.half not in ("top", "bottom")
                or type(self.next_plate_appearance_no) is not int
                or self.next_plate_appearance_no < 1
                or type(self.order) is not int or self.order < 0):
            raise ValueError("invalid change moment")


@dataclass(frozen=True, slots=True)
class CompletedPlateAppearanceMoment:
    """結果確定後の規則通知。次打席の存在を必要としない。"""
    inning: int
    half: str
    completed_plate_appearance_no: int

    def __post_init__(self):
        ChangeMoment(self.inning, self.half, self.completed_plate_appearance_no)


def _moment_key(moment):
    if isinstance(moment, CompletedPlateAppearanceMoment):
        return (moment.completed_plate_appearance_no, 1, 0)
    return (moment.next_plate_appearance_no, 0, moment.order)


def _read_moment(value):
    if value is None:
        return None
    cls = CompletedPlateAppearanceMoment if 'completed_plate_appearance_no' in value else ChangeMoment
    return cls(**value)


@dataclass(frozen=True, slots=True)
class DHAction:
    batting_changes: tuple[BattingOrderSlot, ...] = ()
    player_id: str | None = None
    medical_exception: str | None = None
    umpire_approved: bool = False

    @classmethod
    def from_dict(cls, value):
        return cls(tuple(BattingOrderSlot(**s) for s in value['batting_changes']),
                   value['player_id'], value['medical_exception'], value['umpire_approved'])


@dataclass(frozen=True, slots=True)
class LineupChange:
    sequence: int
    school_id: str
    kind: _ChangeKind
    batting_order: int | None
    outgoing_player_id: str | None
    incoming_player_id: str | None
    defensive_changes: tuple[DefensiveChange, ...]
    moment: ChangeMoment | CompletedPlateAppearanceMoment | None = None
    dh_action: DHAction | None = None

    def to_dict(self) -> dict:
        # あとで作り直す守備変更・DH入力までasdictで先に複製しない。
        out = {name: getattr(self, name) for name in (
            'sequence', 'school_id', 'kind', 'batting_order',
            'outgoing_player_id', 'incoming_player_id')}
        out['defensive_changes'] = [asdict(change) for change in self.defensive_changes]
        out['moment'] = asdict(self.moment) if self.moment is not None else None
        if self.dh_action is not None:
            out['dh_action'] = {
                'batting_changes': [
                    {'batting_order': s.batting_order, 'player_id': s.player_id}
                    for s in self.dh_action.batting_changes],
                'player_id': self.dh_action.player_id,
                'medical_exception': self.dh_action.medical_exception,
                'umpire_approved': self.dh_action.umpire_approved,
            }
        if isinstance(self.moment, ChangeMoment) and self.moment.order == 0:
            out['moment'].pop('order')
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
    starting_designated_hitter_id: str | None = None
    starting_defense: tuple[DefensiveAssignment, ...] = ()

    def to_dict(self) -> dict:
        out = {
            "school_id": self.school_id,
            "starting_lineup": [asdict(slot) for slot in self.starting_lineup],
            "starting_pitcher_id": self.starting_pitcher_id,
            "changes": [change.to_dict() for change in self.changes],
            "fielding_player_ids": list(self.fielding_player_ids),
        }
        if self.starting_designated_hitter_id is not None:
            out['starting_designated_hitter_id'] = self.starting_designated_hitter_id
            out['starting_defense'] = [asdict(a) for a in self.starting_defense]
        return out

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
                    moment=_read_moment(item['moment']),
                    dh_action=DHAction.from_dict(item['dh_action']) if item.get('dh_action') is not None else None,
                ) for item in value["changes"]),
                tuple(value["fielding_player_ids"]),
                value.get('starting_designated_hitter_id'),
                tuple(DefensiveAssignment(**a) for a in value.get('starting_defense', ())),
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
    dh_id: str | None = None
    dh_pending: bool = False
    pitcher_role_retired: bool = False
    batter_role_retired: bool = False


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
        if isinstance(available_player_ids, str):
            raise ValueError('available players must be a collection of IDs')
        self._available = registered if available_player_ids is None else frozenset(available_player_ids)
        if not self._available <= registered:
            raise ValueError("available players must be registered")
        self._initial_lineup = starting_lineup
        positions = {entry.defensive_position: entry.player_id for entry in starting_lineup.defense or starting_lineup.entries}
        data = _TeamStateData(
            batting_order=tuple(
                BattingOrderSlot(entry.batting_order, entry.player_id)
                for entry in sorted(starting_lineup.entries, key=lambda e: e.batting_order)
            ),
            defense=self._alignment(positions), dh_id=starting_lineup.designated_hitter_id,
            dh_pending=starting_lineup.designated_hitter_id is not None,
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
        return frozenset(slot.player_id for slot in self.batting_order) | frozenset(a.player_id for a in self.defensive_alignment)

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
        defenders = frozenset(a.player_id for a in self.defensive_alignment)
        if not defenders <= self.fielding_player_ids:
            self._data = replace(self._data, fielding=self.fielding_player_ids | defenders)

    def participation(self) -> TeamMatchParticipation:
        return TeamMatchParticipation(
            self.school_id,
            tuple(MatchLineupSlot(e.batting_order, e.player_id, e.defensive_position)
                  for e in sorted(self.initial_lineup.entries, key=lambda e: e.batting_order)),
            self.initial_lineup.player_for_position("P"), self.history,
            tuple(sorted(self.fielding_player_ids)),
            self.initial_lineup.designated_hitter_id,
            tuple(DefensiveAssignment(a.defensive_position, a.player_id)
                  for a in self.initial_lineup.defense),
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
        if data.dh_id is None:
            if batters != fielders or data.dh_pending:
                raise ValueError("batting and defensive players differ without DH")
        else:
            if self.initial_lineup.designated_hitter_id is None:
                raise ValueError('DH cannot be introduced during the game')
            pitcher = data.defense[0].player_id
            if data.dh_id not in batters or batters - {data.dh_id} != fielders - {pitcher}:
                raise ValueError('DH batting and defensive roles differ')
            if data.dh_id in fielders and data.dh_id != self._initial_two_way_id():
                raise ValueError('only the declared starting pitcher may be pitcher/DH')
        two_way = self._initial_two_way_id()
        if two_way is not None:
            if data.pitcher_role_retired and data.defense[0].player_id == two_way:
                raise ValueError('a retired pitcher role cannot be regained')
            if data.batter_role_retired and two_way in batters:
                raise ValueError('a retired batting role cannot be regained')
        active = batters | fielders
        if not active <= self._registered or not data.exited <= self._registered:
            raise ValueError("unregistered player")
        if not active <= self._available:
            raise ValueError("unavailable player")
        if active & data.exited:
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
                moment: ChangeMoment | CompletedPlateAppearanceMoment | None = None,
                dh_action: DHAction | None = None) -> LineupChange | None:
        expected_moment = CompletedPlateAppearanceMoment if kind == 'dh_plate_appearance' else ChangeMoment
        if moment is not None and not isinstance(moment, expected_moment):
            raise ValueError('lineup change has an invalid phase')
        self._validate(candidate, actual_pitcher_id)
        if candidate == self._data:
            return None
        changes = tuple(
            DefensiveChange(before.defensive_position, before.player_id, after.player_id)
            for before, after in zip(self.defensive_alignment, candidate.defense, strict=True)
            if before.player_id != after.player_id
        )
        change = LineupChange(len(self.history) + 1, self.school_id, kind, slot, outgoing,
                              incoming, changes, moment, dh_action)
        candidate = replace(candidate, history=(*self.history, change))
        self._data = candidate
        return change

    @property
    def designated_hitter_id(self) -> str | None:
        return self._data.dh_id

    @property
    def dh_batting_required(self) -> bool:
        return self._data.dh_pending

    @property
    def retired_two_way_roles(self) -> frozenset[str]:
        return frozenset(role for role, retired in (
            ('pitcher', self._data.pitcher_role_retired),
            ('batter', self._data.batter_role_retired),
        ) if retired)

    def transition(self, *, batting_changes: Mapping[int, str] | None = None,
                   defensive_changes: Mapping[str, str] | None = None,
                   medical_exception: str | None = None, umpire_approved: bool = False,
                   moment: ChangeMoment | None = None) -> LineupChange | None:
        """同時交代を一括適用する。DH消滅時の新投手等の打順は呼出側が明示する。

        医療例外は球審が負傷・病気による出場不可を認めた場合のみ申告する。
        DH宣言を途中から作成・復活させる引数は持たない。
        """
        changes = dict(batting_changes or {})
        if any(type(n) is not int or not 1 <= n <= 9 for n in changes):
            raise ValueError('batting order must be 1..9')
        if (medical_exception not in (None, 'injury', 'illness')
                or type(umpire_approved) is not bool
                or (medical_exception is None) != (not umpire_approved)):
            raise ValueError('medical exception requires injury/illness and umpire approval')
        bats = tuple(BattingOrderSlot(s.batting_order, changes.get(s.batting_order, s.player_id))
                     for s in self.batting_order)
        new_batters = {s.player_id for s in bats}
        for slot in self.batting_order:
            if slot.player_id in new_batters and bats[slot.batting_order-1].player_id != slot.player_id:
                raise ValueError('an active batter cannot change batting slots')
        positions = self._positions(defensive_changes or {})
        old_defense = {a.defensive_position: a.player_id for a in self.defensive_alignment}
        old_pitcher = self.current_pitcher_id
        dh = self.designated_hitter_id
        # 先発P+DHがPに残ること自体はDH消滅の理由ではない。
        fielded_dh = dh is not None and any(
            pid == dh and (pos != 'P' or old_pitcher != dh)
            for pos, pid in positions.items())
        pitcher_moves = any(pos != 'P' and pid == old_pitcher for pos, pid in positions.items())
        fielder_pitches = positions['P'] in {pid for pos, pid in old_defense.items() if pos != 'P'}
        structural_end = fielded_dh or pitcher_moves or fielder_pitches
        pitcher_bats = dh is not None and old_pitcher != dh and old_pitcher in new_batters
        dh_slot = next((s.batting_order for s in self.batting_order if s.player_id == dh), None)
        candidate_dh = None if dh_slot is None else bats[dh_slot-1].player_id
        # DH枠の後継者が同時に守備へ入る場合も消滅する（新投手の打順入りを含む）。
        # 後継者の守備入りでは、交代前の先発DHの初回打撃義務を免除しない。
        replacement_fields = dh_slot is not None and candidate_dh != dh and candidate_dh in positions.values()
        if pitcher_bats and not (structural_end or replacement_fields) and candidate_dh != old_pitcher:
            raise ValueError('the active pitcher may pinch hit/run only for DH')
        ends = structural_end or pitcher_bats or replacement_fields
        if (self.dh_batting_required and dh not in new_batters
                and not structural_end and medical_exception is None):
            raise ValueError('starting DH must complete the first plate appearance')
        new_dh = None if dh is None or ends else candidate_dh
        active = new_batters | set(positions.values())
        two_way = self._initial_two_way_id()
        candidate = replace(
            self._data, batting_order=bats, defense=self._alignment(positions), dh_id=new_dh,
            dh_pending=self.dh_batting_required and new_dh == dh,
            exited=self.exited_player_ids | (self.active_player_ids - active),
            pitcher_role_retired=self._data.pitcher_role_retired or
                (two_way is not None and positions['P'] != two_way),
            batter_role_retired=self._data.batter_role_retired or
                (two_way is not None and two_way not in new_batters),
        )
        action = DHAction(tuple(BattingOrderSlot(n, pid) for n, pid in sorted(changes.items())),
                          medical_exception=medical_exception, umpire_approved=umpire_approved)
        return self._commit(candidate, 'dh_transition', moment=moment, dh_action=action)

    def _initial_two_way_id(self) -> str | None:
        dh = self.initial_lineup.designated_hitter_id
        return dh if dh is not None and dh == self.initial_lineup.player_for_position('P') else None

    def record_completed_plate_appearance(self, player_id: str, *,
                                         moment: CompletedPlateAppearanceMoment | None = None) -> LineupChange | None:
        """打撃完了の規則入力。実際の打席処理への接続は次工程で行う。"""
        if player_id not in {s.player_id for s in self.batting_order}:
            raise ValueError('completed batter is not in the batting order')
        if not self.dh_batting_required or player_id != self.designated_hitter_id:
            return None
        return self._commit(replace(self._data, dh_pending=False), 'dh_plate_appearance',
                            moment=moment, dh_action=DHAction(player_id=player_id))

    def record_opposing_starter_replaced(self, *,
                                        moment: ChangeMoment | None = None) -> LineupChange | None:
        """5.11(a)(2)の例外。自チーム先発の交代には使用しない。"""
        if not self.dh_batting_required:
            return None
        return self._commit(replace(self._data, dh_pending=False), 'dh_opponent_pitcher',
                            moment=moment, dh_action=DHAction())

    def to_dict(self) -> dict:
        """状態モデル用の記録。A方式への書込みはこの段階では接続しない。"""
        return {'reference_year': self.initial_lineup.reference_year,
                'registered': sorted(self.registered_player_ids),
                'available': sorted(self.available_player_ids),
                'participation': self.participation().to_dict()}

    @classmethod
    def from_dict(cls, value: dict) -> TeamMatchState:
        record = TeamMatchParticipation.from_dict(value['participation'])
        state = _participation_start(record, value['reference_year'], value['registered'],
                                     available=value['available'])
        for change in record.changes:
            apply_lineup_change(state, change, require_moment=False)
        fielding = frozenset(record.fielding_player_ids)
        participants = {a.player_id for a in state.initial_lineup.defense or state.initial_lineup.entries}
        for change in record.changes:
            participants.update(c.after_player_id for c in change.defensive_changes)
        if len(fielding) != len(record.fielding_player_ids) or not fielding <= participants:
            raise ValueError('invalid fielding appearances')
        state._data = replace(state._data, fielding=fielding)
        return state

    def change_positions(self, assignments: Mapping[str, str], *,
                         batting_changes: Mapping[int, str] | None = None,
                         moment: ChangeMoment | None = None) -> LineupChange | None:
        """位置→選手IDの交換・循環をまとめて適用し、打順は維持する。"""
        if self.initial_lineup.designated_hitter_id is not None or batting_changes is not None:
            return self.transition(defensive_changes=assignments, batting_changes=batting_changes, moment=moment)
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
                   medical_exception: str | None = None, umpire_approved: bool = False,
                   moment: ChangeMoment | None = None) -> LineupChange:
        """控えが退場者の打順枠を継承。付随する位置変更も1操作で検証する。"""
        if self.initial_lineup.designated_hitter_id is not None:
            if outgoing_player_id not in self.active_player_ids:
                raise ValueError('outgoing player is not active')
            if outgoing_player_id == incoming_player_id:
                raise ValueError('a player cannot substitute for themselves')
            if incoming_player_id in self.active_player_ids and not (
                    incoming_player_id == self.current_pitcher_id
                    and outgoing_player_id == self.designated_hitter_id):
                raise ValueError('incoming player is already active')
            bats = {s.batting_order: incoming_player_id for s in self.batting_order
                    if s.player_id == outgoing_player_id}
            defense = {a.defensive_position: incoming_player_id for a in self.defensive_alignment
                       if a.player_id == outgoing_player_id and outgoing_player_id != self.designated_hitter_id}
            return self.transition(batting_changes=bats, defensive_changes={**defense, **(defensive_changes or {})},
                                   medical_exception=medical_exception, umpire_approved=umpire_approved,
                                   moment=moment)
        if medical_exception is not None or umpire_approved:
            raise ValueError('DH medical exception requires a declared DH')
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

    def relieve_pitcher(self, incoming_player_id: str, *,
                        moment: ChangeMoment | None = None) -> LineupChange | None:
        """本番の自動継投。野手登板で空く位置にはDHが入り、旧投手は退く。"""
        extra_defense = {}
        if self.designated_hitter_id is not None and self.current_pitcher_id != self.designated_hitter_id:
            vacated = next((a.defensive_position for a in self.defensive_alignment
                            if a.player_id == incoming_player_id and a.defensive_position != 'P'), None)
            if vacated is not None:
                extra_defense[vacated] = self.designated_hitter_id
        return self.change_pitcher(incoming_player_id, defensive_changes=extra_defense, moment=moment)

    def change_pitcher(self, incoming_player_id: str, *, outgoing_player_id: str | None = None,
                       defensive_changes: Mapping[str, str] | None = None,
                       batting_changes: Mapping[int, str] | None = None,
                       moment: ChangeMoment | None = None) -> LineupChange | None:
        """配置操作のみ。登板可否・球数・再登板の規則は呼出側で判断する。

        出場中の野手なら現投手と位置交換。控えなら原則現投手を交代させる。
        別の出場選手を交代対象に指定すると、その打順枠へ控え投手が入り、現投手はその守備へ残る。
        """
        current = self.current_pitcher_id
        if self.initial_lineup.designated_hitter_id is not None:
            if (defensive_changes or {}).get('P', incoming_player_id) != incoming_player_id:
                raise ValueError('P assignment differs from incoming pitcher')
            if outgoing_player_id is not None:
                raise ValueError('use atomic transition for simultaneous DH substitutions')
            changes = {'P': incoming_player_id}
            position = next((a.defensive_position for a in self.defensive_alignment
                             if a.player_id == incoming_player_id and a.defensive_position != 'P'), None)
            if position is not None:
                changes[position] = current
            if self.designated_hitter_id is None and position is None and batting_changes is None:
                batting_changes = {s.batting_order: incoming_player_id for s in self.batting_order
                                   if s.player_id == current}
            return self.transition(defensive_changes={**changes, **(defensive_changes or {})},
                                   batting_changes=batting_changes, moment=moment)
        if batting_changes is not None:
            raise ValueError('explicit batting changes require transition')
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
                         registered: Iterable[str] | None = None, *,
                         available: Iterable[str] | None = None) -> TeamMatchState:
    if not isinstance(record.starting_pitcher_id, str) or not record.starting_pitcher_id:
        raise ValueError("starting pitcher is required")
    if registered is None:
        registered = {s.player_id for s in record.starting_lineup} | {
            c.after_player_id for change in record.changes for c in change.defensive_changes
        } | {a.player_id for a in record.starting_defense} | {
            slot.player_id for change in record.changes if change.dh_action is not None
            for slot in change.dh_action.batting_changes
        }
    lineup = StartingLineup(record.school_id, reference_year, tuple(
        LineupEntry(s.batting_order, s.defensive_position, s.player_id, 0.0)
        for s in record.starting_lineup
    ), tuple(DefensiveAssignment(a.defensive_position, a.player_id) for a in record.starting_defense),
        record.starting_designated_hitter_id)
    return TeamMatchState(lineup, registered, actual_pitcher_id=record.starting_pitcher_id,
                          available_player_ids=available)


def apply_lineup_change(state: TeamMatchState, change: LineupChange, *, require_moment: bool = True) -> None:
    """保存した差分を既存の状態操作で検証して適用する。失敗時は状態を保つ。"""
    moment_type = CompletedPlateAppearanceMoment if change.kind == 'dh_plate_appearance' else ChangeMoment
    if (type(change.sequence) is not int or change.sequence != len(state.history) + 1
            or change.school_id != state.school_id
            or (not isinstance(change.moment, moment_type) and (require_moment or change.moment is not None))
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
        if change.dh_action is not None:
            action = change.dh_action
            if change.kind == 'dh_transition':
                if len({s.batting_order for s in action.batting_changes}) != len(action.batting_changes):
                    raise ValueError('duplicate batting changes')
                applied = state.transition(batting_changes={s.batting_order: s.player_id for s in action.batting_changes},
                    defensive_changes=positions, medical_exception=action.medical_exception,
                    umpire_approved=action.umpire_approved, moment=change.moment)
            elif change.kind == 'dh_plate_appearance':
                applied = state.record_completed_plate_appearance(action.player_id, moment=change.moment)
            elif change.kind == 'dh_opponent_pitcher':
                applied = state.record_opposing_starter_replaced(moment=change.moment)
            else:
                raise ValueError('invalid DH action')
        elif state.initial_lineup.designated_hitter_id is not None:
            raise ValueError('DH changes require rule inputs')
        elif change.kind == "position_change":
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
    participants = {a.player_id for a in state.defensive_alignment}
    previous = None
    for change in record.changes:
        moment = change.moment
        if moment is None:
            raise ValueError("lineup change requires a moment")
        key = (moment.inning * 2 + (moment.half == "bottom"), _moment_key(moment))
        if previous is not None and (
            key[0] < previous[0] or key[1] < previous[1]
            or (key[0] != previous[0] and key[1] == previous[1])
        ):
            raise ValueError("lineup change moments are out of order")
        apply_lineup_change(state, change)
        participants.update(a.player_id for a in state.defensive_alignment)
        previous = key
    fielding = frozenset(record.fielding_player_ids)
    if len(fielding) != len(record.fielding_player_ids) or not fielding <= participants:
        raise ValueError("invalid fielding appearances")
    state._data = replace(state._data, fielding=fielding)
    return state


def _check_final_participation(records, states, final_states):
    fields = ('batting_order', 'defensive_alignment', 'exited_player_ids', 'fielding_player_ids',
              'designated_hitter_id', 'dh_batting_required', 'retired_two_way_roles')
    for record in records:
        actual = states[record.school_id]
        if actual.participation() != record:
            raise ValueError('participation differs from actual game appearances')
        if final_states is not None and any(
                getattr(actual, field) != getattr(final_states[record.school_id], field) for field in fields):
            raise ValueError('replayed final lineup differs from runtime state')


def _validate_dh_event_history(records, team_ids, reference_year, known_ids, events,
                               final_states, ranges, total_plate_appearances, *, recorded=False):
    """同じ状態操作を打席前・結果確定後の順に再生し、規則通知の根拠も照合する。"""
    if events is None and not recorded:
        raise ValueError('DH participation validation requires plate appearance events')
    states = {r.school_id: _participation_start(r, reference_year,
              None if known_ids is None else known_ids[r.school_id]) for r in records}
    by_pa = {}
    for record in records:
        previous = None
        for change in record.changes:
            moment = change.moment
            expected_type = CompletedPlateAppearanceMoment if change.kind == 'dh_plate_appearance' else ChangeMoment
            if not isinstance(moment, expected_type):
                raise ValueError('rule notification has an invalid phase')
            key = _moment_key(moment)
            if previous is not None and key < previous:
                raise ValueError('lineup change moments are out of order')
            previous = key
            if not 1 <= key[0] <= total_plate_appearances:
                raise ValueError('lineup change occurs outside the played game')
            if ranges:
                first, last = ranges.get((moment.inning, moment.half), (1, 0))
                if not first <= key[0] <= last:
                    raise ValueError('lineup change belongs to another half inning')
            by_pa.setdefault(key[0], []).append(change)
    batting_slots = dict.fromkeys(team_ids, 1)
    previous_half = None
    previous_bases = None
    from collections import Counter
    pa_counts, bf_counts = Counter(), Counter()
    if recorded:
        # 全イベントのない履歴では、配置が変わらない区間を9人の打順周期で数える。
        # 半イニングの先頭・すべての規則入力は従来どおり1打席ずつ再生する。
        boundaries = sorted(by_pa)

        def recorded_timeline():
            for (inning, half), (first, last) in ranges.items():
                if first > last:
                    continue
                points = [first] + [pa for pa in boundaries if first < pa <= last]
                for index, pa in enumerate(points):
                    following = points[index+1] if index+1 < len(points) else last+1
                    yield pa, inning, half, None, following-pa-1

        timeline = recorded_timeline()
    else:
        timeline = ((e.plate_appearance_no, e.inning, e.half, e, 0) for e in events)
    seen = 0
    for pa_no, inning, half_name, event, unchanged in timeline:
        offense, defense = team_ids if half_name == 'top' else tuple(reversed(team_ids))
        seen += 1
        if pa_no != seen:
            raise ValueError('plate appearances must be contiguous')
        boundary = by_pa.pop(seen, [])
        half = (inning, half_name)
        expected_bases = list(previous_bases) if previous_bases is not None and half == previous_half else None
        before = sorted((c for c in boundary if isinstance(c.moment, ChangeMoment)), key=lambda c: c.moment.order)
        if [c.moment.order for c in before] != list(range(1, len(before)+1)):
            raise ValueError('DH boundary changes require a unique execution order')
        expected_notices = set()
        for change in before:
            if (change.moment.inning, change.moment.half) != (inning, half_name):
                raise ValueError('lineup change moment differs from actual event')
            state = states[change.school_id]
            opponent_id = next(sid for sid in team_ids if sid != change.school_id)
            if change.kind == 'dh_opponent_pitcher':
                if change.school_id not in expected_notices or not state.dh_batting_required:
                    raise ValueError('opponent starter notification lacks an actual replacement')
                expected_notices.remove(change.school_id)
            old_pitcher = state.current_pitcher_id
            if (expected_bases is not None and change.school_id == offense
                    and change.kind == 'dh_transition' and change.dh_action is not None):
                for slot in change.dh_action.batting_changes:
                    outgoing = state.player_at_order(slot.batting_order)
                    expected_bases = [slot.player_id if pid == outgoing else pid for pid in expected_bases]
            apply_lineup_change(state, change)
            if old_pitcher != state.current_pitcher_id:
                if (old_pitcher == state.initial_lineup.player_for_position('P')
                        and states[opponent_id].dh_batting_required):
                    expected_notices.add(opponent_id)
        if expected_notices:
            raise ValueError('missing opponent starter replacement notification')
        batter_id = states[offense].player_at_order(batting_slots[offense])
        pitcher_id = states[defense].current_pitcher_id
        if event is not None and (
                (event.offense_school_id, event.defense_school_id) != (offense, defense)
                or batter_id != event.batter_id or pitcher_id != event.pitcher_id):
            raise ValueError('event batter or pitcher differs from lineup history')
        pa_counts[offense, batter_id] += 1
        bf_counts[defense, pitcher_id] += 1
        batting_slots[offense] = batting_slots[offense] % 9 + 1
        if event is not None:
            metadata = dict(event.metadata)
            try:
                before_bases = metadata['bases_before'].split('|')
                after_bases = metadata['bases_after'].split('|')
            except (KeyError, AttributeError) as exc:
                raise ValueError('DH events require actual base runners') from exc
            batters = {s.player_id for s in states[offense].batting_order}
            for runners in (before_bases, after_bases):
                occupied = [pid for pid in runners if pid]
                if len(runners) != 3 or len(occupied) != len(set(occupied)) or not set(occupied) <= batters:
                    raise ValueError('base runners differ from actual batting roles')
            if expected_bases is not None and expected_bases != before_bases:
                raise ValueError('base runners do not continue the preceding play/substitution')
            previous_bases = after_bases
        # 守備交代はP以外の変更も含む。規則通知だけでは出場を増やさない。
        defense_changed = any(c.school_id == defense and c.defensive_changes for c in before)
        if half != previous_half or defense_changed:
            states[defense].record_fielding_appearance()
        previous_half = half
        after = [c for c in boundary if isinstance(c.moment, CompletedPlateAppearanceMoment)]
        required = states[offense].dh_batting_required and states[offense].designated_hitter_id == batter_id
        if len(after) != int(required):
            raise ValueError('missing or unexpected completed DH plate appearance notification')
        for change in after:
            if (change.school_id != offense or change.dh_action is None
                    or change.dh_action.player_id != batter_id
                    or (change.moment.inning, change.moment.half) != half):
                raise ValueError('completed DH notification differs from actual event')
            apply_lineup_change(states[offense], change)
        if unchanged:
            state = states[offense]
            start = batting_slots[offense]-1
            batters = state.batting_order
            # 区間内に先発DHの初打席があれば、そのPAの完了通知が必要。
            if state.dh_batting_required:
                dh_index = next(i for i, slot in enumerate(batters)
                                if slot.player_id == state.designated_hitter_id)
                if (dh_index-start) % 9 < unchanged:
                    raise ValueError('missing or unexpected completed DH plate appearance notification')
            turns, extra = divmod(unchanged, 9)
            if turns:
                for slot in batters:
                    pa_counts[offense, slot.player_id] += turns
            for offset in range(extra):
                pa_counts[offense, batters[(start+offset) % 9].player_id] += 1
            bf_counts[defense, states[defense].current_pitcher_id] += unchanged
            batting_slots[offense] = (start+unchanged) % 9+1
            seen += unchanged
    if seen != total_plate_appearances or by_pa:
        raise ValueError('unapplied lineup changes or missing events')
    _check_final_participation(records, states, final_states)

    return pa_counts, bf_counts


def validate_recorded_match_participation(records, *, team_ids, reference_year,
        half_plate_appearances, known_ids, batter_appearances, pitcher_appearances):
    """保存された打席数と履歴の整合。実打球・走者・責任投手の再証明はしない。"""
    if tuple(r.school_id for r in records) != team_ids:
        raise ValueError('participation must contain both teams in match order')
    ranges = {}
    next_pa = 1
    for half, count in half_plate_appearances.items():
        if type(count) is not int or count < 0:
            raise ValueError('invalid half inning plate appearance count')
        ranges[half] = (next_pa, next_pa+count-1)
        next_pa += count
    expected_pa, expected_bf = _validate_dh_event_history(
        records, team_ids, reference_year, known_ids, None, None, ranges, next_pa-1, recorded=True)
    for actual, expected in ((batter_appearances, expected_pa), (pitcher_appearances, expected_bf)):
        if any(type(n) is not int or n < 0 for n in actual.values()):
            raise ValueError('invalid recorded appearance count')
        if any(actual.get(key) != n for key, n in expected.items()) or any(
                expected.get(key, 0) != n for key, n in actual.items()):
            raise ValueError('individual PA/BF differ from recorded lineup timeline')
    for record in records:
        batters = {s.player_id for s in record.starting_lineup}
        pitchers = {record.starting_pitcher_id}
        for change in record.changes:
            if change.dh_action is not None:
                batters.update(s.player_id for s in change.dh_action.batting_changes)
            elif change.incoming_player_id is not None:
                batters.add(change.incoming_player_id)
            pitchers.update(c.after_player_id for c in change.defensive_changes if c.defensive_position == 'P')
        if {pid for sid, pid in batter_appearances if sid == record.school_id} != batters:
            raise ValueError('recorded batting roles differ from batter rows')
        if {pid for sid, pid in pitcher_appearances if sid == record.school_id} != pitchers:
            raise ValueError('recorded pitchers differ from pitcher rows')


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
    if any(r.starting_designated_hitter_id is not None for r in records):
        events = None if events is None else tuple(events)
        if events and (events[-1].inning, events[-1].half) != (last_inning, ending_half):
            raise ValueError('last plate appearance differs from game ending')
        _validate_dh_event_history(records, team_ids, reference_year, known_ids, events,
                                   final_states, ranges, total_plate_appearances)
        return
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
        _check_final_participation(records, states, final_states)

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
