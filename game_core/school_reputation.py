"""学校の評判の初期値（ゲーム開始時点。game_definition.md §10「初期の勢力図」）。

実際の甲子園の出場（``historical_data/koshien_entrants.csv``、1915年〜）・通算
（``koshien_records.csv``）と、直前の結果（2026年選抜・2025年夏・2025年秋）から
学校ごとに点を出す。最近の出場ほど重く（``recency_half_life_years`` 年で半分）、
甲子園に出たことのない学校は小さな乱数だけ。重みは
``config/abilities/school_reputation_v1.json``。

評判の順位を、入部品質の学校成分（``school_intake_v1`` の ``program_component``）と
同じ平均・広がりの z に変える（``SchoolIntakeModel`` が使う）。学校の強さは選手から
計算する（ADR-001・006）。実際の記録は読むだけで、評判はゲームのデータ。
"""
from __future__ import annotations

import csv
from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
from statistics import NormalDist

from phase2_engine.randomness import rng_for


CONFIG_NAME = "school_reputation_v1.json"
PRIOR_RESULTS = Path("initial_state") / "2026" / "prior_results.csv"


def _rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class SchoolReputation:
    """学校ID → 評判の点・入部品質の z・ランク。"""

    def __init__(self, root: str | Path):
        root = Path(root)
        self.config = json.loads(
            (root / "config" / "abilities" / CONFIG_NAME).read_text(encoding="utf-8")
        )
        intake = json.loads(
            (root / "config" / "abilities" / "school_intake_v1.json").read_text(encoding="utf-8")
        )
        program = intake["quality_model"]["program_component"]
        self._mean = float(program["mean"])
        self._stddev = float(program["stddev"])
        self.school_ids = sorted(
            row["school_id"] for row in _rows(root / "data" / "master" / "schools.csv")
        )
        self.base = self._base_points(root / "historical_data", root / "data")
        self._by_seed: dict[int, tuple[dict[str, float], dict[str, float]]] = {}

    def _decay(self, year: int) -> float:
        age = int(self.config["reference_year"]) - int(year)
        return 0.5 ** (max(0, age) / float(self.config["recency_half_life_years"]))

    def _base_points(self, history: Path, data: Path) -> dict[str, float]:
        config = self.config
        kind_points = config["appearance_points"]
        recent = config["recent_points"]
        career = config["career"]
        points: dict[str, float] = defaultdict(float)
        counted: dict[tuple[str, str], int] = defaultdict(int)
        for row in _rows(history / "koshien_entrants.csv"):
            school_id = row["school_id"]
            if not school_id or row["status"] == "withdrawn":
                continue
            year = int(row["year"])
            points[school_id] += float(kind_points[row["kind"]]) * self._decay(year)
            counted[(school_id, row["kind"])] += 1
            if (row["kind"], year) == ("spring", 2026):
                points[school_id] += float(recent["senbatsu_2026"])
            elif (row["kind"], year) == ("summer", 2025):
                points[school_id] += float(recent["summer_2025"])
        for row in _rows(history / "koshien_records.csv"):
            school_id, kind = row["school_id"], row["kind"]
            last = int(row["last_appearance_year"] or config["reference_year"])
            # 年ごとの出場にない分（1959年以前・照合できなかった出場）
            uncounted = int(row["appearances"] or 0) - counted[(school_id, kind)]
            if uncounted > 0:
                year = last if counted[(school_id, kind)] == 0 else 1959
                points[school_id] += (
                    uncounted * float(career["uncounted_appearance_points"])
                    * float(kind_points[kind]) * self._decay(year)
                )
            points[school_id] += (
                int(row["wins"] or 0) * float(career["win_points"])
                + int(row["championships"] or 0) * float(career["championship_points"])
            ) * self._decay(last)
        for row in _rows(history / "autumn_regional_entrants_2025.csv"):
            if row["school_id"]:
                points[row["school_id"]] += float(recent["autumn_regional_2025"])
        for row in _rows(data / PRIOR_RESULTS):
            if row["kind"] == "autumn_prefectural" and row["achievement"] in ("best4", "best8"):
                points[row["school_id"]] += float(
                    recent[f"autumn_prefectural_{row['achievement']}"]
                )
        return dict(points)

    def _for_seed(self, base_seed: int) -> tuple[dict[str, float], dict[str, float]]:
        if base_seed not in self._by_seed:
            noise = self.config["noise"]
            scores = {
                school_id: self.base.get(school_id, 0.0) + rng_for(
                    base_seed, self.config["rng_namespace"].format(school_id=school_id),
                ).uniform(0.0, float(noise["max"]))
                for school_id in self.school_ids
            }
            order = sorted(scores, key=lambda school_id: (scores[school_id], school_id))
            count = len(order)
            # 順位（下から）の割合 → 正規分布の z
            share = {school_id: (index + 0.5) / count for index, school_id in enumerate(order)}
            self._by_seed[base_seed] = (scores, share)
        return self._by_seed[base_seed]

    def score(self, school_id: str, base_seed: int) -> float | None:
        return self._for_seed(base_seed)[0].get(school_id)

    def program_z(self, school_id: str, base_seed: int) -> float | None:
        """入部品質の学校成分。学校マスターにない学校は None（いつもの乱数を使う）。"""
        share = self._for_seed(base_seed)[1].get(school_id)
        if share is None:
            return None
        return self._mean + self._stddev * NormalDist().inv_cdf(share)

    def rank(self, school_id: str, base_seed: int) -> str:
        """画面に出す評判のランク（S〜E）。"""
        share = self._for_seed(base_seed)[1].get(school_id)
        if share is None:
            return ""
        return next(
            label for label, minimum in self.config["rank_labels"] if share >= float(minimum)
        )


@lru_cache(maxsize=4)
def reputation_for(root: str) -> SchoolReputation:
    return SchoolReputation(root)
