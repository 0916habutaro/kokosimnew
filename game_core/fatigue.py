"""投手の疲れ（game_definition.md §3.6.2 の E）。値は ``config/match/match_simulation_v1.json`` の ``fatigue``。

疲れは能力の点（大きいほど疲れている）で表す。

- 試合の中：その試合の球数が、スタミナで決まる目安（``in_game.base_pitches`` ＋
  (スタミナ − 50) × ``per_stamina``）を超えた1球ごとに ``per_pitch`` 点
- 試合をまたぐ（連投）：直近の日の球数のうち ``free_pitches`` を超えた分 × ``per_pitch`` を、
  何日前かで減らして足す（1日ごとに exp(−回復の速さ)。回復の速さはスタミナで変わる）。
  球数制限のために記録している日ごとの球数（7日分）から求めるので、新しい状態は持たない

疲れは ``stage_points`` ごとの段階に切り捨ててから能力に効かせる（段階が同じなら能力も
同じなので、打席の結果の計算を段階ごとに使い回せる）。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Mapping

from .abilities import PitchAbility, PlayerAbilitySnapshot


def carry_fatigue(history: Mapping[int, int], stamina: float | None, rule: Mapping) -> float:
    """``history`` は (何日前 → その日の球数)。今日（0日前）は含めない。"""
    carry = rule["carry"]
    rate = (float(carry["recovery_per_day"])
            + ((stamina or 50) - 50.0) * float(carry["recovery_per_stamina"]))
    rate = max(float(carry["min_recovery_per_day"]), rate)
    total = 0.0
    for days_ago, pitches in history.items():
        if days_ago < 1:
            continue
        load = max(0, int(pitches) - int(carry["free_pitches"])) * float(carry["per_pitch"])
        total += load * math.exp(-rate * days_ago)
    return total


def in_game_fatigue(pitches: int, stamina: float | None, rule: Mapping) -> float:
    game = rule["in_game"]
    threshold = float(game["base_pitches"]) + ((stamina or 50) - 50.0) * float(game["per_stamina"])
    return max(0.0, pitches - threshold) * float(game["per_pitch"])


def stage_of(points: float, rule: Mapping) -> int:
    """疲れの段階（0から。``max_stage`` まで）。"""
    return min(int(rule["max_stage"]), int(max(0.0, points) // float(rule["stage_points"])))


def label_of(stage: int, rule: Mapping) -> str:
    """画面に出す疲れの言葉（段階の小さいほうから ``labels`` の境目で決める。なければ空）。"""
    text = ""
    for row in rule["labels"]:
        if stage >= int(row["min_stage"]):
            text = row["label_ja"]
    return text


def tired(pitcher: PlayerAbilitySnapshot, stage: int, rule: Mapping) -> PlayerAbilitySnapshot:
    """疲れの段階の分だけ能力を下げた写し（打席の結果の計算だけに使う）。"""
    if stage <= 0:
        return pitcher
    points = stage * float(rule["stage_points"])
    drop = rule["drop"]

    def lower(value, weight):
        return None if value is None else max(1.0, value - points * float(weight))

    return replace(
        pitcher,
        velocity_kmh=(None if pitcher.velocity_kmh is None
                      else max(100.0, pitcher.velocity_kmh - points * float(drop["velocity_kmh"]))),
        stuff=lower(pitcher.stuff, drop["stuff"]),
        control=lower(pitcher.control, drop["control"]),
        pitch_repertoire=tuple(
            PitchAbility(p.pitch_type, lower(p.quality, drop["pitch_quality"]),
                         lower(p.command, drop["pitch_command"]), p.usage)
            for p in pitcher.pitch_repertoire
        ),
    )


def history_from_log(days: Mapping[str, int], today: date) -> dict[int, int]:
    """球数制限の記録（日付 → 球数）を (何日前 → 球数) に直す。今日と先の日は含めない。"""
    out = {}
    for on, pitches in days.items():
        ago = (today - date.fromisoformat(on)).days
        if ago >= 1:
            out[ago] = out.get(ago, 0) + int(pitches)
    return out


@lru_cache(maxsize=1)
def default_rule() -> dict:
    """本番の設定（``config/match/match_simulation_v1.json`` の ``fatigue``）。画面で使う。"""
    path = Path(__file__).resolve().parents[1] / "config" / "match" / "match_simulation_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))["fatigue"]
