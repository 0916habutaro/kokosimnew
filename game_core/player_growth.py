"""選手の成長（game_definition.md §3.1）。

毎月の初めに前の月の分を伸ばす。1か月の伸びは

    3年間の伸び × 潜在能力 × 月の重み × 成長の型の学年の重み ÷ 型ごとの3年間の重みの合計
    × 上限に近いほど小さくなる係数

で、公式戦に出た試合の数だけ少し足す。端数は乱数で切り上げ・切り捨てる。

強豪だけが伸びすぎないように、入部時の能力（入部品質）と成長量を分け、成長量の
学校差（潜在能力の評判による差）は小さくする。上限に近いほど伸びにくく、試合に
出ない控えは試合の分が伸びない。値は ``config/players/player_growth_v1.json``。
"""
from __future__ import annotations

import json
from pathlib import Path
import random

from .abilities import BATTER_ABILITIES, CATCHER_ABILITIES, FIELD_POSITIONS, PITCHER_ABILITIES


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path("config") / "players" / "player_growth_v1.json"
TYPES = ("early", "normal", "late")
# 能力の並び（roster_book.pack_abilities と同じ）
SCALARS = BATTER_ABILITIES + CATCHER_ABILITIES + PITCHER_ABILITIES
APTITUDE_OFFSET = len(SCALARS)
PITCH_OFFSET = APTITUDE_OFFSET + len(FIELD_POSITIONS)
POTENTIAL_SCALE = 80  # 潜在能力は ×80 して1バイトで持つ


class PlayerGrowth:
    def __init__(self, root: str | Path = ROOT):
        self.config = json.loads((Path(root) / CONFIG_PATH).read_text(encoding="utf-8"))
        totals = self.config["abilities"]
        default = float(totals["default"])
        self.totals = [float(totals.get(name, default)) for name in SCALARS]
        self.default_total = default
        self.pitch_totals = (float(totals["pitch_quality"]), float(totals["pitch_command"]))
        months = {int(k): float(v) for k, v in self.config["months"].items() if k.isdigit()}
        year_weight = sum(months.values())
        # (型, 学年, 月) → 3年間の伸びのうちその月の割合
        self.share: dict[tuple[int, int, int], float] = {}
        for index, name in enumerate(TYPES):
            grades = self.config["types"][name]["grades"]
            total = year_weight * sum(grades)
            for grade, weight in enumerate(grades, start=1):
                for month, month_weight in months.items():
                    self.share[(index, grade, month)] = month_weight * weight / total
        self.type_shares = [float(self.config["types"][name]["share"]) for name in TYPES]
        head = self.config["headroom"]
        self._head = (float(head["cap"]), float(head["pivot"]))
        self._velocity_head = (float(head["velocity_cap"]), float(head["velocity_pivot"]))
        self._head_range = (float(head["min"]), float(head["max"]))
        self.velocity_index = SCALARS.index("velocity_kmh")
        self.batter_indexes = range(len(BATTER_ABILITIES))
        self.catcher_indexes = range(len(BATTER_ABILITIES), len(BATTER_ABILITIES) + len(CATCHER_ABILITIES))
        self.pitcher_indexes = range(len(BATTER_ABILITIES) + len(CATCHER_ABILITIES), len(SCALARS))

    # ---- 入学のとき ----

    def draw(self, rng: random.Random, program_z: float) -> tuple[int, int, int]:
        """(成長の型の番号, 潜在能力×80, 球速の伸びしろ×80)。

        伸び悩み（stagnation）の選手は、学校によらず一定の割合で、どちらも小さくなる。"""
        roll = rng.random()
        type_index = len(TYPES) - 1
        for index, share in enumerate(self.type_shares):
            if roll < share:
                type_index = index
                break
            roll -= share
        p = self.config["potential"]
        value = rng.gauss(
            float(p["mean"]) + float(p["school_per_z"]) * program_z, float(p["stddev"]),
        )
        if rng.random() < float(p["bloom_chance"]):
            value += float(p["bloom_add"])
        v = self.config["velocity_potential"]
        velocity = rng.gauss(float(v["mean"]), float(v["stddev"]))
        stagnation = self.config["stagnation"]
        if rng.random() < float(stagnation["chance"]):
            value *= float(stagnation["factor"])
            velocity *= float(stagnation["factor"])
        value = min(float(p["max"]), max(float(p["min"]), value))
        velocity = min(float(v["max"]), max(float(v["min"]), velocity))
        return (
            type_index, int(round(value * POTENTIAL_SCALE)),
            int(round(velocity * POTENTIAL_SCALE)),
        )

    # ---- 毎月 ----

    def _headroom(self, value: float, cap: float, pivot: float) -> float:
        low, high = self._head_range
        return min(high, max(low, (cap - value) / (cap - pivot)))

    @staticmethod
    def _add(values: bytearray, index: int, gain: float, rng: random.Random, high: int) -> None:
        whole = int(gain)
        if rng.random() < gain - whole:
            whole += 1
        if whole:
            values[index] = max(values[index], min(high, values[index] + whole))

    def grow(
        self,
        values: bytearray,
        *,
        position: str,
        grade: int,
        type_index: int,
        potential: int,
        games: int,
        month: int,
        rng: random.Random,
        practice_multiplier: float = 1.0,
        velocity_potential: int | None = None,
    ) -> None:
        """1か月分伸ばす。練習分だけ倍率を掛け、試合経験と端数抽選は従来どおり。
        球速は潜在能力の代わりに球速の伸びしろ（``velocity_potential``）を使う。"""
        base_share = self.share.get((type_index, grade, month), 0.0)
        share = base_share * potential / POTENTIAL_SCALE
        velocity_share = base_share * (
            potential if velocity_potential is None else velocity_potential
        ) / POTENTIAL_SCALE
        per_game = self.config["games"]
        batter_games = games * float(per_game["batter"])
        pitcher_games = games * float(per_game["pitcher"]) if position == "P" else 0.0
        cap, pivot = self._head
        indexes = list(self.batter_indexes)
        if position == "C":
            indexes.extend(self.catcher_indexes)
        if position == "P":
            indexes.extend(self.pitcher_indexes)
        for index in indexes:
            value = values[index]
            if not value:
                continue
            if index == self.velocity_index:
                head = self._headroom(value, *self._velocity_head)
                high = int(self._velocity_head[0])
            else:
                head = self._headroom(value, cap, pivot)
                high = int(cap)
            games_gain = pitcher_games if index in self.pitcher_indexes else batter_games
            # 試合の分も能力ごとの伸びの大きさに合わせる（球速は3年間の伸びが小さい）
            games_gain *= self.totals[index] / self.default_total
            if index == self.velocity_index and velocity_potential is not None:
                # 球速は試合の分も球速の伸びしろに比例する（伸びしろのない投手は伸びない）
                games_gain *= velocity_potential / POTENTIAL_SCALE
            index_share = velocity_share if index == self.velocity_index else share
            practice_gain = self.totals[index] * index_share * practice_multiplier
            self._add(values, index, (practice_gain + games_gain) * head, rng, high)
        if position == "P":
            for offset in range(PITCH_OFFSET, len(values), 4):
                for field, total in ((1, self.pitch_totals[0]), (2, self.pitch_totals[1])):
                    head = self._headroom(values[offset + field], cap, pivot)
                    practice_gain = total * share * practice_multiplier
                    self._add(values, offset + field, (practice_gain + pitcher_games) * head, rng, int(cap))

    def bootstrap(
        self, values: bytearray, *, position: str, entry_year: int, first_year: int,
        type_index: int, potential: int, velocity_potential: int, rng: random.Random,
    ) -> None:
        """新規開始時の上級生：入学（1年の4月）から開始の前の月（3月）までの成長を
        進める。公式戦の出場は1か月あたり ``bootstrap.games_per_month`` とみる。"""
        games = self.config["bootstrap"]["games_per_month"]
        for year in range(entry_year, first_year):
            grade = year - entry_year + 1
            for month in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3):
                self.grow(
                    values, position=position, grade=grade, type_index=type_index,
                    potential=potential, velocity_potential=velocity_potential,
                    games=int(games[str(month)]), month=month, rng=rng,
                )
