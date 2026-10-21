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
