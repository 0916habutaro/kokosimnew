"""ゲーム開始前の実際の結果（``data/initial_state/<年度>/prior_results.csv``）。

最初の年度の春季大会は、ゲーム開始前に終わっている前の年度の結果
（3月の選抜の出場校、前年秋の県大会・地区大会の上位校）を使う。
ゲーム内では試合をせず、ここにある実際の結果をそのまま入力にする。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


SENBATSU_ENTRANT = "senbatsu_entrant"


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
    for row in rows:
        if row["kind"] == SENBATSU_ENTRANT:
            senbatsu.append((row["school_id"], row["prefecture_code"]))
        elif row.get("rule_id"):
            by_rule.setdefault(row["rule_id"], []).append(row["school_id"])
    return PriorResults(
        year=year,
        senbatsu_entrants=tuple(senbatsu),
        school_ids_by_rule={
            rule_id: tuple(dict.fromkeys(ids))
            for rule_id, ids in by_rule.items()
        },
    )
