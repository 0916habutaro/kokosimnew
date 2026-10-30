"""試合経過の要点（game_definition.md §8）。

1打席ごとの記録は残さず、次だけを残す（履歴に保存する。セーブには入れない）。

- 得点が入った打席：``["S", 回, 表裏, 打者ID, 打撃結果, 得点]``
  （本塁打は打撃結果が ``home_run``）
- 投手交代：``["P", 回, 表裏, 守備側の学校ID, 代わった投手ID]``

表裏は ``"t"``（表）・``"b"``（裏）。容量を抑えるため短い配列で持つ。
"""
from __future__ import annotations

from typing import Iterable

SCORE = "S"
PITCHING_CHANGE = "P"
_HALF = {"top": "t", "bottom": "b"}


def game_highlights(events: Iterable) -> list[list]:
    out: list[list] = []
    pitchers: dict[str, str] = {}
    for event in events:
        half = _HALF[event.half]
        previous = pitchers.get(event.defense_school_id)
        if previous is not None and previous != event.pitcher_id:
            out.append([
                PITCHING_CHANGE, event.inning, half,
                event.defense_school_id, event.pitcher_id,
            ])
        pitchers[event.defense_school_id] = event.pitcher_id
        if event.runs_scored:
            out.append([
                SCORE, event.inning, half,
                event.batter_id, event.event_type, event.runs_scored,
            ])
    return out


def validate_highlights(value) -> None:
    if not isinstance(value, list):
        raise ValueError("highlights must be a list")
    for item in value:
        if not isinstance(item, list) or not item:
            raise ValueError("invalid highlight entry")
        kind = item[0]
        if kind == SCORE:
            if len(item) != 6 or not isinstance(item[5], int) or item[5] < 1:
                raise ValueError("invalid scoring highlight")
        elif kind == PITCHING_CHANGE:
            if len(item) != 5:
                raise ValueError("invalid pitching change highlight")
        else:
            raise ValueError(f"unknown highlight kind: {kind}")
        if not isinstance(item[1], int) or item[1] < 1 or item[2] not in ("t", "b"):
            raise ValueError("invalid highlight inning")


def _pitching_highlight_moment(record, change, inning_scores=None):
    moment = change['moment']
    if 'next_plate_appearance_no' not in moment:
        raise ValueError('pitching changes require a before-PA moment')
    if inning_scores is None:
        return moment['inning'], _HALF[moment['half']]
    # 攻撃中の申告も可能。要点は実際に次の守備で登板した回・表裏を指す。
    anchor = moment['next_plate_appearance_no']
    next_pa = 1
    for row in inning_scores:
        count = row['plate_appearances']
        last = next_pa+count-1
        if row['batting_team_id'] != record['school_id'] and max(next_pa, anchor) <= last:
            first_defense = max(next_pa, anchor)
            if any(c['sequence'] > change['sequence']
                   and c['moment'].get('next_plate_appearance_no', first_defense+1) <= first_defense
                   and any(d['defensive_position'] == 'P' for d in c['defensive_changes'])
                   for c in record['changes']):
                return None
            return row['inning'], _HALF[row['half']]
        next_pa += count
    return None


def compact_pitching_highlights(highlights, participation, inning_scores=None):
    """投手交代の事実は配置履歴を正本とし、要点の並びには参照だけを保存する。"""
    if highlights is None:
        return None
    references = {}
    for team_index, record in enumerate(participation):
        for change in record["changes"]:
            pitcher = next((c["after_player_id"] for c in change["defensive_changes"]
                            if c["defensive_position"] == "P"), None)
            if pitcher is not None:
                when = _pitching_highlight_moment(record, change, inning_scores)
                if when is None:
                    continue
                key = (*when, record["school_id"], pitcher)
                references.setdefault(key, []).append([PITCHING_CHANGE, team_index, change["sequence"]])
    out = []
    for item in highlights:
        if item[0] == PITCHING_CHANGE:
            matches = references.get(tuple(item[1:]))
            if not matches:
                raise ValueError("pitching highlight differs from lineup history")
            out.append(matches.pop(0))
        else:
            out.append(item)
    return out


def expand_pitching_highlights(highlights, participation, inning_scores=None):
    """参照から従来と同じ投手交代の要点を返す。表示側の形式は変えない。"""
    if highlights is None:
        return None
    out = []
    for item in highlights:
        if item[0] == PITCHING_CHANGE and len(item) == 3:
            _, team_index, sequence = item
            if (type(team_index) is not int or not 0 <= team_index < len(participation)
                    or type(sequence) is not int or sequence < 1):
                raise ValueError("invalid pitching highlight reference")
            record = participation[team_index]
            if sequence > len(record["changes"]):
                raise ValueError("missing pitching highlight change")
            change = record["changes"][sequence - 1]
            pitcher = next((c["after_player_id"] for c in change["defensive_changes"]
                            if c["defensive_position"] == "P"), None)
            if pitcher is None:
                raise ValueError("highlight refers to a change without a pitcher")
            when = _pitching_highlight_moment(record, change, inning_scores)
            if when is None:
                raise ValueError('pitching highlight has no played defensive half')
            out.append([PITCHING_CHANGE, *when, record["school_id"], pitcher])
        else:
            out.append(item)
    return out
