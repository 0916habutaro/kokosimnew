"""秋季地区大会の結果から選抜の出場校を選ぶ（game_definition.md §8）。

- 地区ごとの枠（``selection_rules.csv`` の ``total_quota``）を、その地区の
  秋季地区大会の順位の上位から選ぶ（東京は東京都秋季大会）
- 関東・東京の比較枠は、関東の次の順位の学校と東京の次の順位の学校から
  1校をくじで選ぶ
- 21世紀枠はまだ選ばない（§8「21世紀枠は後で追加」）。その分、出場校は少ない
- 神宮枠（``bonus_quota``）は、神宮大会を試合で行うまではデータのとおりの地区
"""
from __future__ import annotations

from typing import Mapping, Sequence

from .randomness import shuffled


KANTO_TOKYO_SCOPE = "関東・東京"
KANTO_REGION = "REG03"
TOKYO_REGION = "REG04"
CENTURY_METHOD = "21st_century_selection"


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
    rng_seed: int,
) -> list[str]:
    """``rankings`` は地区 → 秋季地区大会の順位（優勝校が先頭）。"""
    selected: list[str] = []
    chosen: set[str] = set()

    def next_ranked(region: str) -> list[str]:
        return [sid for sid in rankings.get(region, ()) if sid not in chosen]

    for rule in rules:
        region = rule.get("region_id", "")
        if not region:
            continue
        quota = int(rule.get("total_quota") or 0)
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
        quota = int(rule.get("total_quota") or 0)
        picks = shuffled(
            candidates, rng_seed, "senbatsu:kanto_tokyo_compare"
        )[:quota]
        selected.extend(picks)
        chosen.update(picks)
    return selected
