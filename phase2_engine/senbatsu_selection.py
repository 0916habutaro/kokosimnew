"""秋季地区大会の結果から選抜の出場校を選ぶ（game_definition.md §8）。

- 地区ごとの枠（``selection_rules.csv`` の ``base_quota``）を、その地区の
  秋季地区大会の順位の上位から選ぶ（東京は東京都秋季大会）
- 関東・東京の比較枠は、関東の次の順位の学校と東京の次の順位の学校から
  1校をくじで選ぶ
- 21世紀枠は実際の流れに合わせる。都道府県推薦（秋の県大会ベスト16以上から
  くじで1校。公立は重く、チームの強さが低いほど重い）→ 地区推薦（9地区。
  関東・東京は1地区。秋の成績が良いほど重い）→ 最終（9校からくじで2校）。
  一般の選考で選ばれた学校は候補から外す。重みは ``config/selection``
- 神宮枠（``bonus_quota`` の合計）は、その年の神宮大会で優勝した学校の地区に付ける。
  地区ごとの枠は ``base_quota``
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .randomness import rng_for, shuffled


KANTO_TOKYO_SCOPE = "関東・東京"
KANTO_REGION = "REG03"
TOKYO_REGION = "REG04"
CENTURY_METHOD = "21st_century_selection"
# 21世紀枠の重み（config/ からの相対パス）
CONFIG_PATH = Path("selection") / "senbatsu_selection_v1.json"


def selection_region_ids(rules: Sequence[Mapping[str, str]]) -> list[str]:
    """選考に結果を使う地区（地区ごとの枠と比較枠の地区）。"""
    regions = [rule["region_id"] for rule in rules if rule.get("region_id")]
    if any(rule.get("selection_scope") == KANTO_TOKYO_SCOPE for rule in rules):
        regions.extend((KANTO_REGION, TOKYO_REGION))
    return list(dict.fromkeys(regions))


def select_invitational(
    rules: Sequence[Mapping[str, str]],
    rankings: Mapping[str, Sequence[str]],
    *,
    jingu_region: str,
    prefectural_rankings: Mapping[str, Sequence[Sequence[str]]] | None = None,
    public_school_ids: frozenset[str] | set[str] = frozenset(),
    strength_of: Callable[[str], float | None] | None = None,
    century_config: Mapping | None = None,
    rng_seed: int,
) -> list[str]:
    """``rankings`` は地区 → 秋季地区大会の順位（優勝校が先頭）。
    ``jingu_region`` は神宮大会で優勝した学校の地区。
    ``prefectural_rankings`` は地区 → その地区の秋の県大会の順位の一覧、
    ``strength_of`` は学校 → チームの強さ（分からなければ None）、
    ``century_config`` は ``config/selection`` の ``century``（どれも21世紀枠に使う）。"""
    jingu_quota = sum(int(rule.get("bonus_quota") or 0) for rule in rules)
    selected: list[str] = []
    chosen: set[str] = set()

    def next_ranked(region: str) -> list[str]:
        return [sid for sid in rankings.get(region, ()) if sid not in chosen]

    for rule in rules:
        region = rule.get("region_id", "")
        if not region:
            continue
        quota = int(rule.get("base_quota") or 0)
        if region == jingu_region:
            quota += jingu_quota
        picks = next_ranked(region)[:quota]
        if len(picks) != quota:
            raise ValueError(
                f"senbatsu selection {region}: "
                f"ranked={len(picks)} quota={quota}"
            )
        selected.extend(picks)
        chosen.update(picks)

    for rule in rules:
        if rule.get("selection_scope") != KANTO_TOKYO_SCOPE:
            continue
        candidates = [
            ranked[0]
            for ranked in (
                next_ranked(KANTO_REGION), next_ranked(TOKYO_REGION)
            )
            if ranked
        ]
        quota = int(rule.get("base_quota") or 0)
        picks = shuffled(
            candidates, rng_seed, "senbatsu:kanto_tokyo_compare"
        )[:quota]
        selected.extend(picks)
        chosen.update(picks)

    for rule in rules:
        if rule.get("selection_method") != CENTURY_METHOD:
            continue
        picks = _century_picks(
            rules,
            prefectural_rankings or {},
            public_school_ids,
            strength_of,
            century_config,
            chosen,
            int(rule.get("base_quota") or 0),
            rng_seed,
        )
        selected.extend(picks)
        chosen.update(picks)
    return selected


# 秋の大会の順位（0始まり）→ 成績の区分
_PERFORMANCE_TIERS = (
    (1, "champion"), (2, "runner_up"), (4, "best4"), (8, "best8"),
)


def _performance_tier(index: int) -> str:
    for limit, tier in _PERFORMANCE_TIERS:
        if index < limit:
            return tier
    return "best16"


def _weighted_pick(items, weights, rng_seed: int, namespace: str):
    return rng_for(rng_seed, namespace).choices(items, weights=weights)[0]


def _century_picks(
    rules: Sequence[Mapping[str, str]],
    prefectural_rankings: Mapping[str, Sequence[Sequence[str]]],
    public_school_ids,
    strength_of: Callable[[str], float | None] | None,
    config: Mapping,
    chosen: set[str],
    quota: int,
    rng_seed: int,
) -> list[str]:
    """都道府県推薦 → 地区推薦（9地区）→ 最終（2校）。どれもくじ。"""
    top_n = int(config["prefecture_candidate_top_n"])
    public_weight = float(config["public_weight_multiplier"])
    exponent = float(config["strength_exponent"])
    performance = config["region_performance_weights"]

    def prefecture_pick(ranking: Sequence[str], key: str):
        candidates = [
            (index, school_id)
            for index, school_id in enumerate(ranking[:top_n])
            if school_id not in chosen
        ]
        if not candidates:
            return None
        strengths = [
            strength_of(school_id) if strength_of else None
            for _, school_id in candidates
        ]
        weakest = (
            min(strengths) if None not in strengths else None
        )
        weights = [
            (public_weight if school_id in public_school_ids else 1.0)
            * (
                (weakest / strength) ** exponent
                if weakest is not None else 1.0
            )
            for (_, school_id), strength in zip(candidates, strengths)
        ]
        return _weighted_pick(
            candidates, weights, rng_seed,
            f"senbatsu:21st_century:prefecture:{key}",
        )

    # 地区推薦は実際と同じ9地区。東京は関東と1つの地区にする
    areas: dict[str, list[str]] = {}
    for region in selection_region_ids(rules):
        area = KANTO_REGION if region == TOKYO_REGION else region
        areas.setdefault(area, []).append(region)
    recommended = []
    for area, regions in areas.items():
        prefecture_picks = [
            pick
            for region in regions
            for number, ranking in enumerate(
                prefectural_rankings.get(region, ())
            )
            if (pick := prefecture_pick(ranking, f"{region}:{number}"))
            is not None
        ]
        if prefecture_picks:
            _, school_id = _weighted_pick(
                prefecture_picks,
                [
                    float(performance[_performance_tier(index)])
                    for index, _ in prefecture_picks
                ],
                rng_seed,
                f"senbatsu:21st_century:area:{area}",
            )
            recommended.append(school_id)
    # 最終は推薦校から同じ重みで（東日本・西日本の区別はしない）
    return shuffled(
        recommended, rng_seed, "senbatsu:21st_century:draw"
    )[:quota]


def load_selection_config(config_root: str | Path) -> dict:
    """``config/selection/senbatsu_selection_v1.json``。"""
    path = Path(config_root) / CONFIG_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("config_id") != "senbatsu_selection_v1":
        raise ValueError("senbatsu selection config_id mismatch")
    return data
