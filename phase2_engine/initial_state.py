"""ゲーム開始前の実際の結果（``data/initial_state/<年度>/prior_results.csv``）。

最初の年度の春季大会は、ゲーム開始前に終わっている前の年度の結果
（3月の選抜の出場校、前年秋の県大会・地区大会の上位校）を使う。
ゲーム内では試合をせず、ここにある実際の結果をそのまま入力にする。
前年秋の県大会の上位（優勝〜ベスト16）は、最初の年度の春季県大会のシードを
選ぶ順位にも使う（``initial_autumn_ranking``）。ゲームの記録（試合・戦績）には入れない。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .randomness import shuffled


SENBATSU_ENTRANT = "senbatsu_entrant"
AUTUMN_PREFECTURAL = "autumn_prefectural"
# 到達点 → その到達点の学校の数（順位の並びでの枠）。上から順に並べる
AUTUMN_FINISH_SLOTS = (
    ("champion", 1), ("runner_up", 1), ("best4", 2), ("best8", 4), ("best16", 8),
)


@dataclass(frozen=True)
class PriorResults:
    year: int
    senbatsu_entrants: tuple[tuple[str, str], ...] = ()
    school_ids_by_rule: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    # 2年目からのゲーム内の結果（``prior_season.py``）。実際の結果は
    # ルールごと（school_ids_by_rule）、ゲーム内の結果は大会の順位で持つ。
    autumn_prefectural_rankings: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    autumn_regional_entrants: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    # 実際の前年秋の県大会の到達点（都道府県 → (学校ID, 到達点)）。最初の年度だけ
    autumn_prefectural_finishes: dict[str, tuple[tuple[str, str], ...]] = field(
        default_factory=dict
    )

    @property
    def from_game(self) -> bool:
        """ゲーム内の結果（実際の結果ではない）。"""
        return bool(
            self.autumn_prefectural_rankings or self.autumn_regional_entrants
        )

    def to_dict(self) -> dict:
        return {
            "year": self.year,
            "senbatsu_entrants": [list(row) for row in self.senbatsu_entrants],
            "school_ids_by_rule": _lists(self.school_ids_by_rule),
            "autumn_prefectural_rankings": _lists(
                self.autumn_prefectural_rankings
            ),
            "autumn_regional_entrants": _lists(self.autumn_regional_entrants),
            "autumn_prefectural_finishes": {
                key: [list(row) for row in rows]
                for key, rows in sorted(self.autumn_prefectural_finishes.items())
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PriorResults":
        return cls(
            year=int(data["year"]),
            senbatsu_entrants=tuple(
                (row[0], row[1]) for row in data["senbatsu_entrants"]
            ),
            school_ids_by_rule=_tuples(data["school_ids_by_rule"]),
            autumn_prefectural_rankings=_tuples(
                data["autumn_prefectural_rankings"]
            ),
            autumn_regional_entrants=_tuples(data["autumn_regional_entrants"]),
            autumn_prefectural_finishes={
                key: tuple((row[0], row[1]) for row in rows)
                for key, rows in data["autumn_prefectural_finishes"].items()
            },
        )

    def senbatsu_entrants_from(self, prefecture_code: str) -> list[str]:
        return [
            school_id
            for school_id, pcode in self.senbatsu_entrants
            if pcode == prefecture_code
        ]


def _lists(mapping) -> dict[str, list[str]]:
    return {key: list(ids) for key, ids in sorted(mapping.items())}


def _tuples(mapping) -> dict[str, tuple[str, ...]]:
    return {key: tuple(ids) for key, ids in mapping.items()}


def prior_results_path(data_dir: str | Path, year: int) -> Path:
    return Path(data_dir) / "initial_state" / str(year) / "prior_results.csv"


def load_prior_results(
    data_dir: str | Path,
    year: int,
) -> PriorResults | None:
    """``year`` 年度の開始前の実際の結果。データがない年度は ``None``。"""
    path = prior_results_path(data_dir, year)
    if not path.exists():
        return None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    senbatsu = []
    by_rule: dict[str, list[str]] = {}
    finishes: dict[str, dict[str, str]] = {}
    tiers = [name for name, _ in AUTUMN_FINISH_SLOTS]
    for row in rows:
        if row["kind"] == SENBATSU_ENTRANT:
            senbatsu.append((row["school_id"], row["prefecture_code"]))
        elif row.get("rule_id"):
            by_rule.setdefault(row["rule_id"], []).append(row["school_id"])
        if (row["kind"] == AUTUMN_PREFECTURAL and row["school_id"]
                and row["achievement"] in tiers):
            known = finishes.setdefault(row["prefecture_code"], {})
            old = known.get(row["school_id"])
            if old is None or tiers.index(row["achievement"]) < tiers.index(old):
                known[row["school_id"]] = row["achievement"]
    return PriorResults(
        year=year,
        senbatsu_entrants=tuple(senbatsu),
        school_ids_by_rule={
            rule_id: tuple(dict.fromkeys(ids))
            for rule_id, ids in by_rule.items()
        },
        autumn_prefectural_finishes={
            pcode: tuple(sorted(known.items(), key=lambda item: tiers.index(item[1])))
            for pcode, known in finishes.items()
        },
    )


def initial_autumn_ranking(
    finishes: Sequence[tuple[str, str]],
    *,
    base_seed: int,
    namespace: str,
) -> list[str]:
    """実際の前年秋の到達点から、シードを選ぶ順位の並び（ゲーム内の秋季県大会の
    ``final_ranking_school_ids`` と同じ形。上から優勝・準優勝・ベスト4・8・16）。

    同じ到達点の中は抽選。分かっている到達点までを使い、学校の数が足りない到達点
    （の分かっている学校）までで止める。残りは ``fill_by_lot`` で埋める。"""
    by_tier: dict[str, list[str]] = {}
    for school_id, achievement in finishes:
        by_tier.setdefault(achievement, []).append(school_id)
    out: list[str] = []
    for achievement, slots in AUTUMN_FINISH_SLOTS:
        tier = sorted(by_tier.get(achievement, ()))
        out += shuffled(tier, base_seed, f"{namespace}:{achievement}")
        if len(tier) < slots:
            break
    return out


def fill_by_lot(
    ranking: Sequence[str],
    school_ids: Iterable[str],
    *,
    base_seed: int,
    namespace: str,
) -> list[str]:
    """分かっている順位のあとに、その都道府県のほかの学校を抽選で並べる
    （前年秋の結果がないときの仮の決まり）。"""
    rest = sorted(set(school_ids) - set(ranking))
    return list(ranking) + shuffled(rest, base_seed, f"{namespace}:rest")
