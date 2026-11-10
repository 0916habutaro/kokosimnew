"""夏の地方大会の成績シードと、本大会の抽選の決まり（game_definition.md §8「夏の地方大会のシード」）。

データ
- ``competition_seed_rules.csv`` の ``season_segment=summer`` の行：大会ごとのシードの階級。
  1行が1つの階級で、元の大会の順位の ``source_rank_from``〜``source_rank_to`` 位を
  その階級にする。順位の付け方は ``source_result_selector``：

  - ``finish_rank``：当年の春季県大会の到達点の順（優勝・準優勝・ベスト4・8・16…。
    同じ到達点の中は大会の抽選の順）。夏の大会に出る学校だけで数える（東京の東西）
  - ``points_rank``：前年の秋季県大会と当年の春季県大会の到達点に点を付けて足した順。
    点は ``config/selection/summer_seed_points_v1.json``（ゲームの仮の配点）

- ``bracket_generation_policies.csv`` の夏の地方大会の ``MAIN`` の行：
  ``seed_bye_count``（不戦勝を先に付けるシードの数。空＝全シード）と
  ``redraw_rounds``（途中で抽選し直す回戦。``QF:1`` は準々決勝を5回戦のあとに
  抽選する。数は前の回戦の勝者を上から何組に分けて組ごとに抽選するか。
  夏の甲子園と同じ ``tournament_runtime.redraw_rounds`` の仕組み）

シード校の位置は ``main_tournament.generate_main_slots`` の標準のシード位置。
階級の順にシード番号を付け、同じ階級の中は抽選（乱数）で並べるので、
シード校は別々のブロックに入る（8校なら準々決勝まで当たらない）。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .main_tournament import next_power_of_two
from .national_day_plan import round_number
from .randomness import rng_for, shuffled


SUMMER = "summer"
FINISH_RANK = "finish_rank"
POINTS_RANK = "points_rank"
POINTS_CONFIG = Path(__file__).resolve().parents[1] / "config" / "selection" / "summer_seed_points_v1.json"


@lru_cache(maxsize=1)
def points_config() -> dict:
    data = json.loads(POINTS_CONFIG.read_text(encoding="utf-8"))
    if data.get("config_id") != "summer_seed_points_v1":
        raise ValueError("summer seed points config_id mismatch")
    return data


def summer_seed_rules(repo, competition_id: str) -> list[dict]:
    """その大会の夏のシードの行（階級の上から）。"""
    rows = [
        row for row in repo.seed_rules(competition_id)
        if row.get("season_segment") == SUMMER and row.get("seed_count")
    ]
    return sorted(rows, key=lambda row: (int(row["source_rank_from"]), row["seed_rule_id"]))


def seed_sources(rules: Sequence[Mapping]) -> list[tuple[str, int]]:
    """シードを選ぶ元の大会（大会の種類, 年度のずれ）。秋は前の年度（-1）。"""
    out: list[tuple[str, int]] = []
    for row in rules:
        kinds = [k for k in row.get("source_competition_type", "").split(";") if k]
        offsets = [int(v) for v in str(row.get("source_year_offset") or "0").split(";") if v]
        offsets += [offsets[-1] if offsets else 0] * (len(kinds) - len(offsets))
        for pair in zip(kinds, offsets):
            if pair not in out:
                out.append(pair)
    return out


def best_of(position: int) -> int:
    """順位の並びの位置（0から）→ 到達点（1＝優勝、2＝準優勝、4＝ベスト4…）。"""
    return 1 if position == 0 else next_power_of_two(position + 1)


def candidate_order(
    rules: Sequence[Mapping],
    rankings: Mapping[str, Sequence[str]],
    eligible: Iterable[str],
    *,
    base_seed: int,
    namespace: str,
    config: Mapping | None = None,
) -> list[str]:
    """シードの候補を良い順に。``rankings`` は大会の種類 → 順位の並び（到達点の順）。"""
    eligible = set(eligible)
    selector = rules[0].get("source_result_selector", FINISH_RANK) if rules else FINISH_RANK
    spring = [s for s in rankings.get("spring_prefectural", ()) if s in eligible]
    if selector == FINISH_RANK:
        return spring
    if selector != POINTS_RANK:
        raise ValueError(f"unknown summer seed selector: {selector}")
    config = config or points_config()
    table = {int(k): float(v) for k, v in config["points_by_best"].items()}
    weights = config.get("source_weights", {})
    points: dict[str, float] = {}
    for kind, ranking in rankings.items():
        weight = float(weights.get(kind, 1.0))
        for position, school_id in enumerate(ranking):
            if school_id in eligible:
                points[school_id] = points.get(school_id, 0.0) + weight * table.get(best_of(position), 0.0)
    spring_position = {school_id: index for index, school_id in enumerate(spring)}
    rng = rng_for(base_seed, f"{namespace}:summer_seed:points_tie")
    tie = {school_id: rng.random() for school_id in sorted(points)}
    return sorted(
        (s for s, value in points.items() if value > 0),
        key=lambda s: (-points[s], spring_position.get(s, len(spring)), tie[s]),
    )


def choose_seeds(
    rules: Sequence[Mapping],
    rankings: Mapping[str, Sequence[str]],
    eligible: Iterable[str],
    *,
    base_seed: int,
    namespace: str,
    config: Mapping | None = None,
) -> list[str]:
    """シード校をシード番号の順に。階級の順に並べ、同じ階級の中は抽選。
    候補がシードの数より少なければ、いる学校だけ。"""
    order = candidate_order(
        rules, rankings, eligible, base_seed=base_seed, namespace=namespace, config=config,
    )
    out: list[str] = []
    for row in rules:
        low, high = int(row["source_rank_from"]), int(row["source_rank_to"])
        tier = [s for s in order[low - 1:high] if s not in out]
        out += shuffled(tier, base_seed, f"{namespace}:summer_seed:{row['seed_rule_id']}")
    return out


def bracket_policy(repo, competition_id: str, stage_code: str = "MAIN") -> dict:
    policies = getattr(repo, "bracket_policies", {}) or {}
    return dict(policies.get((competition_id, stage_code), {}))


def policy_seed_bye_count(repo, competition_id: str) -> int | None:
    value = bracket_policy(repo, competition_id).get("seed_bye_count", "")
    return int(value) if str(value).strip() else None


def policy_redraw_rounds(repo, competition_id: str, total_rounds: int) -> dict[int, int]:
    """途中で抽選し直す回戦 → 前の回戦の勝者を何組に分けて抽選するか。"""
    text = bracket_policy(repo, competition_id).get("redraw_rounds", "")
    out: dict[int, int] = {}
    for item in [x for x in text.split(";") if x.strip()]:
        key, _, groups = item.partition(":")
        round_no = round_number(key.strip(), total_rounds)
        if 1 < round_no <= total_rounds:
            out[round_no] = int(groups or 1)
    return out
