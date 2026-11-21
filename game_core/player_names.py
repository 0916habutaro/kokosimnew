"""選手の名前（苗字＋名前）と出身の都道府県（game_definition.md §3.5）。

- 出身：基本は学校の所在県。私立は評判のランクが高いほど県外の割合を上げる。
  県外の出身県は、近隣県・同一地方・その他の地方の重みで選ぶ。各区分の県は苗字の\n  件数の合計（人口の目安）で重み付けする。県外に出る割合そのものは変えない
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
        # 地域区分と近接県はゲーム用の大まかな分類。都道府県の入試制度ではない。
        geography = self.config.get("origin_geography") or {}
        self._region_for: dict[str, str] = {}
        for region, codes in geography.get("regions", {}).items():
            for code in codes:
                if code in self._region_for:
                    raise ValueError(f"duplicate prefecture in origin regions: {code}")
                self._region_for[code] = region
        self._nearby: dict[str, set[str]] = {}
        for pair in geography.get("nearby_pairs", []):
            if len(pair) != 2 or pair[0] == pair[1]:
                raise ValueError(f"invalid nearby prefectures: {pair}")
            left, right = pair
            self._nearby.setdefault(left, set()).add(right)
            self._nearby.setdefault(right, set()).add(left)
        # (進学先県, 公私・評判区分) → 県外の出身県候補。生成順に依存しない。
        self._away: dict[tuple[str, str], _Weighted] = {}

    def out_of_prefecture_rate(self, school_id: str, base_seed: int) -> float:
        rates = self.config["out_of_prefecture_rate"]
        if self.ownership.get(school_id) != "private":
            return float(rates["public"])
        if self.rank_of is None:
            self.rank_of = reputation_for(str(self.root)).rank
        rank = self.rank_of(school_id, base_seed)
        return float(rates["private"].get(rank, rates["private"]["E"]))

    def _away_policy(self, school_id: str, base_seed: int) -> tuple[str, dict | None]:
        mixes = self.config.get("away_origin_mix")
        if not mixes:
            return "legacy", None
        if self.ownership.get(school_id) != "private":
            return "public", mixes["public"]
        if self.rank_of is None:
            self.rank_of = reputation_for(str(self.root)).rank
        rank = self.rank_of(school_id, base_seed)
        return f"private:{rank}", mixes["private"].get(rank, mixes["private"]["E"])

    def _away_chooser(self, home: str, school_id: str, base_seed: int) -> _Weighted:
        mode, mix = self._away_policy(school_id, base_seed)
        key = (home, mode)
        away = self._away.get(key)
        if away is not None:
            return away
        codes = sorted(code for code in self.prefecture_weights if code != home)
        weights = [self.prefecture_weights[code] for code in codes]
        if mix is not None and home in self._region_for:
            # 近隣は地域境界を越えても優先。全国の残りは遠方区分。
            groups = [
                ("nearby" if code in self._nearby.get(home, ())
                 else "regional" if self._region_for.get(code) == self._region_for[home]
                 else "distant")
                for code in codes
            ]
            totals = {
                group: sum(weight for weight, category in zip(weights, groups)
                           if category == group)
                for group in ("nearby", "regional", "distant")
            }
            # 空の区分は抽選から外し、残りの重みを自動で正規化する。
            adjusted = [
                weight * float(mix[group]) / totals[group] if totals[group] else 0.0
                for weight, group in zip(weights, groups)
            ]
            if sum(adjusted) > 0:
                weights = adjusted
        away = self._away[key] = _Weighted(codes, weights)
        return away

    def hometown(self, team: Team, base_seed: int, rng: random.Random) -> str:
        home = team.prefecture_code
        if home not in self.surnames:
            raise ValueError(f"{team.school_id}: no surname data for prefecture {home!r}")
        if rng.random() >= self.out_of_prefecture_rate(team.school_id, base_seed):
            return home
        return self._away_chooser(home, team.school_id, base_seed).choose(rng)

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
