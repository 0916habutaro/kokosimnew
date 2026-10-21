"""秋季地区大会の結果から選抜の出場校を選ぶ（game_definition.md §8）。

- 地区ごとの枠（``selection_rules.csv`` の ``base_quota``）を、その地区の
  秋季地区大会の順位の上位から選ぶ（東京は東京都秋季大会）
- 関東・東京の比較枠は、関東の次の順位の学校と東京の次の順位の学校から
  1校をくじで選ぶ
- 21世紀枠は、各地区（実際と同じ9地区。関東・東京は1地区）が秋の県大会で
  ベスト8以上に入った公立校から1校をくじで推薦し、推薦校の中から枠の数（2校）を
  くじで選ぶ。一般の選考で選ばれた学校は候補から外す
- 神宮枠（``bonus_quota`` の合計）は、その年の神宮大会で優勝した学校の地区に付ける。
  地区ごとの枠は ``base_quota``
"""
from __future__ import annotations

from typing import Mapping, Sequence

from .randomness import shuffled


KANTO_TOKYO_SCOPE = "関東・東京"
KANTO_REGION = "REG03"
TOKYO_REGION = "REG04"
CENTURY_METHOD = "21st_century_selection"
# 公立校（data/master/schools.csv の ownership_type）
PUBLIC_OWNERSHIP_TYPES = frozenset({"prefectural", "municipal"})
# 21世紀枠の候補になる秋の県大会の順位（ベスト8以上）
CENTURY_TOP_N = 8


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
    rng_seed: int,
) -> list[str]:
    """``rankings`` は地区 → 秋季地区大会の順位（優勝校が先頭）。
    ``jingu_region`` は神宮大会で優勝した学校の地区。
    ``prefectural_rankings`` は地区 → その地区の秋の県大会の順位の一覧
    （21世紀枠に使う）。"""
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
            chosen,
            int(rule.get("base_quota") or 0),
            rng_seed,
        )
        selected.extend(picks)
        chosen.update(picks)
    return selected


def _century_picks(
    rules: Sequence[Mapping[str, str]],
    prefectural_rankings: Mapping[str, Sequence[Sequence[str]]],
    public_school_ids,
    chosen: set[str],
    quota: int,
    rng_seed: int,
) -> list[str]:
    """各地区の推薦校（くじで1校）から、枠の数をくじで選ぶ。"""
    # 推薦は実際と同じ9地区。東京は関東と1つの地区にする
    areas: dict[str, list[str]] = {}
    for region in selection_region_ids(rules):
        area = KANTO_REGION if region == TOKYO_REGION else region
        areas.setdefault(area, []).append(region)
    recommended = []
    for area, regions in areas.items():
        candidates = list(dict.fromkeys(
            school_id
            for region in regions
            for ranking in prefectural_rankings.get(region, ())
            for school_id in ranking[:CENTURY_TOP_N]
            if school_id in public_school_ids and school_id not in chosen
        ))
        if candidates:
            recommended.append(shuffled(
                candidates, rng_seed, f"senbatsu:21st_century:{area}"
            )[0])
    return shuffled(
        recommended, rng_seed, "senbatsu:21st_century:draw"
    )[:quota]
