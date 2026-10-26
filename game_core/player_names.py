"""選手の名前（苗字＋名前）と出身の都道府県（game_definition.md §3.5）。

- 出身：基本は学校の所在県。私立は評判のランクが高いほど県外の割合を上げる。
  県外の出身地は、苗字データの件数の合計（人口の目安）で重み付けして選ぶ
- 苗字：出身の都道府県の苗字データ（``data/generation/player_names/surnames.csv``）
  から件数で重み付けして選ぶ
- 名前：``given_names.json`` の先頭の人気の名前を重く、残りは同じ重み
- 同じ学校の中で同姓同名にならないように選び直す（同じ苗字は許す）

重みは ``config/players/player_names_v1.json``。材料は架空の選手名をつくるための
生成用データで、実在の記録ではない。
"""
from __future__ import annotations

import csv
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from itertools import accumulate
import json
from pathlib import Path
import random
from typing import Callable, Collection

from phase2_engine.models import Team

from .school_reputation import reputation_for


NAME_SOURCE = "player_names_v1"
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path("data") / "generation" / "player_names"
CONFIG_PATH = Path("config") / "players" / "player_names_v1.json"


@dataclass(frozen=True)
class PlayerIdentity:
    display_name: str
    name_source: str
    hometown_prefecture_code: str


class _Weighted:
    """重み付きの抽選（累積の重み + 二分探索）。"""

    def __init__(self, items: list[str], weights: list[float]):
        if not items or len(items) != len(weights):
            raise ValueError("weighted choice needs items")
        self.items = items
        self.cumulative = list(accumulate(weights))
        self.total = self.cumulative[-1]

    def choose(self, rng: random.Random) -> str:
        return self.items[bisect_right(self.cumulative, rng.random() * self.total)]


class PlayerNameGenerator:
    """``PlayerRosterGenerator`` の name provider（選手1人の名前と出身）。"""

    def __init__(
        self,
        root: str | Path = ROOT,
        *,
        rank_of: Callable[[str, int], str] | None = None,
    ):
        self.root = Path(root)
        # 学校の評判のランク（学校ID, 乱数の種 → S〜E）。私立の学校で初めて要るときに読む
        self.rank_of = rank_of
        self.config = json.loads(
            (self.root / CONFIG_PATH).read_text(encoding="utf-8")
        )
        surnames: dict[str, tuple[list[str], list[float]]] = {}
        with (self.root / DATA_DIR / "surnames.csv").open(
            encoding="utf-8", newline="",
        ) as handle:
            for row in csv.DictReader(handle):
                items, weights = surnames.setdefault(row["prefecture_code"], ([], []))
                items.append(row["surname"])
                weights.append(float(row["count"]))
        self.surnames = {
            code: _Weighted(items, weights)
            for code, (items, weights) in surnames.items()
        }
        # 県外の出身地の重み（その都道府県の苗字の件数の合計）
        self.prefecture_weights = {
            code: chooser.total for code, chooser in self.surnames.items()
        }
        names = json.loads(
            (self.root / DATA_DIR / "given_names.json").read_text(encoding="utf-8")
        )
        given = self.config["given_names"]
        popular = int(given["popular_count"])
        self.given_names = _Weighted(
            names,
            [
                float(given["popular_weight"] if index < popular else given["other_weight"])
                for index in range(len(names))
            ],
        )
        self.ownership: dict[str, str] = {}
        with (self.root / "data" / "master" / "schools.csv").open(
            encoding="utf-8-sig", newline="",
        ) as handle:
            for row in csv.DictReader(handle):
                self.ownership[row["school_id"]] = row["ownership_type"]
        self._away: dict[str, _Weighted] = {}

    def out_of_prefecture_rate(self, school_id: str, base_seed: int) -> float:
        rates = self.config["out_of_prefecture_rate"]
        if self.ownership.get(school_id) != "private":
            return float(rates["public"])
        if self.rank_of is None:
            self.rank_of = reputation_for(str(self.root)).rank
        rank = self.rank_of(school_id, base_seed)
        return float(rates["private"].get(rank, rates["private"]["E"]))

    def hometown(self, team: Team, base_seed: int, rng: random.Random) -> str:
        home = team.prefecture_code
        if home not in self.surnames:
            raise ValueError(f"{team.school_id}: no surname data for prefecture {home!r}")
        if rng.random() >= self.out_of_prefecture_rate(team.school_id, base_seed):
            return home
        away = self._away.get(home)
        if away is None:
            codes = sorted(code for code in self.prefecture_weights if code != home)
            away = self._away[home] = _Weighted(
                codes, [self.prefecture_weights[code] for code in codes],
            )
        return away.choose(rng)

    def __call__(
        self,
        team: Team,
        base_seed: int,
        rng: random.Random,
        taken: Collection[str],
    ) -> PlayerIdentity:
        """``taken``（同じ学校の部員の名前）と重ならない名前を選ぶ。"""
        hometown = self.hometown(team, base_seed, rng)
        surnames = self.surnames[hometown]
        separator = self.config["display_separator"]
        for _ in range(int(self.config["max_name_attempts"])):
            name = (
                f"{surnames.choose(rng)}{separator}{self.given_names.choose(rng)}"
            )
            if name not in taken:
                return PlayerIdentity(name, NAME_SOURCE, hometown)
        raise ValueError(f"{team.school_id}: could not draw a unique player name")


@lru_cache(maxsize=2)
def name_generator(root: str = str(ROOT)) -> PlayerNameGenerator:
    return PlayerNameGenerator(root)
