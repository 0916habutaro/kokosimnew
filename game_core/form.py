"""選手の調子（画面に出さない。game_definition.md §3.4 の段階F4）。

- 値は ``config/players/form_v1.json`` の ``unit`` 刻みの整数で持ち（セーブも同じ）、
  続けて遊んでもロードしても同じ値になる
- 試合の日ごとに、出場した選手の調子を前の値に引き寄せ、選手ごとの乱数と試合の結果で動かす
- 試合のない日は少しずつ0に戻る
- 試合の能力は、調子に応じて打撃・投球の主な能力を少し上下させる
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from functools import lru_cache
import json
import math
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path("config") / "players" / "form_v1.json"


class FormModel:
    def __init__(self, root: str | Path = ROOT):
        self.config = json.loads((Path(root) / CONFIG_PATH).read_text(encoding="utf-8"))
        c = self.config
        numbers = ("unit", "limit", "daily_decay", "match_pull", "match_noise_sd", "points_per_form")
        if any(not math.isfinite(c[k]) or c[k] < 0 for k in numbers) or not (
                0 < c["unit"] and 0 < c["daily_decay"] <= 1 and 0 <= c["match_pull"] <= 1
                and c["limit"] / c["unit"] <= 127):
            raise ValueError("invalid player form configuration")
        self.limit_units = round(c["limit"] / c["unit"])
        self.max_age_days = int(c["max_age_days"])
        if not 0 <= self.max_age_days <= 127:
            raise ValueError("player form max_age_days must be within 0..127")

    def value(self, units: int, since: date | None, day: date) -> float:
        """``since`` に ``units`` だった調子の、``day`` の値（試合のない日は0に戻る）。"""
        if not units or since is None:
            return 0.0
        days = max(0, (day - since).days)
        if days > self.max_age_days:
            return 0.0
        return units * self.config["unit"] * self.config["daily_decay"] ** days

    def points(self, form: float) -> int:
        """試合の能力に足す点（打撃・投球の主な能力）。"""
        value = form * self.config["points_per_form"]
        # 四捨五入（0.5は0から遠い側）。偶数への丸めで +2 と −2 の効きが変わらないように
        return int(math.copysign(math.floor(abs(value) + 0.5), value))

    def after_game(self, form: float, seed: int, *, on_base: int = 0, outs_made: int = 0,
                   outs_recorded: int = 0, earned_runs: int = 0) -> int:
        """試合のあとの調子（整数の刻み）。``seed`` は選手・日ごとの乱数の種。"""
        c = self.config
        moved = (form * c["match_pull"] + random.Random(seed).gauss(0.0, c["match_noise_sd"])
                 + on_base * c["batter"]["per_on_base"] + outs_made * c["batter"]["per_out"]
                 + outs_recorded * c["pitcher"]["per_out"]
                 + earned_runs * c["pitcher"]["per_earned_run"])
        units = round(moved / c["unit"])
        return max(-self.limit_units, min(self.limit_units, units))

    def apply(self, snapshot, points: int):
        """試合の能力に調子を入れる（1〜100に収める。投手の能力のない選手は打撃だけ）。"""
        if not points:
            return snapshot
        changes = {}
        for field in (*self.config["batting_abilities"], *self.config["pitching_abilities"]):
            value = getattr(snapshot, field)
            if value is not None:
                changes[field] = max(1, min(100, value + points))
        return replace(snapshot, **changes)


@lru_cache(maxsize=1)
def form_model() -> FormModel:
    return FormModel()
