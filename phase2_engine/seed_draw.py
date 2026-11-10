"""県大会・地方大会の成績シードと、本大会の抽選の決まり
（game_definition.md §8「夏の地方大会のシード」「秋季・春季の県大会のシード」）。

データ
- ``competition_seed_rules.csv`` の ``source_result_selector`` が ``finish_rank``・
  ``points_rank``・``stage_rank`` の行：大会ごとのシードの階級。1行が1つの階級で、
  元の大会の順位の ``source_rank_from``〜``source_rank_to`` 位をその階級にする。
  順位の付け方は ``source_result_selector``：

  - ``finish_rank``：``source_competition_type`` の最初の大会（``source_year_offset`` の
    年度のずれ。-1＝前の年度）の到達点の順（優勝・準優勝・ベスト4・8・16…。同じ到達点の
    中は大会の抽選の順）。シードを付ける大会に出る学校だけで数える（東京の東西など）。
    夏：当年の春季県大会。秋：当年の夏の地方大会。春：前の年度の秋季県大会
  - ``points_rank``：前年の秋季県大会と当年の春季県大会の到達点に点を付けて足した順。
    点は ``config/selection/summer_seed_points_v1.json``（ゲームの仮の配点）
  - ``stage_rank``：同じ大会の支部・地区予選（``prelim_stage``）の成績の順。予選を免除された
    本大会の出場校が先、次に予選で負けの少ない順。同じなら ``source_competition_type`` の
    2つ目の大会（秋は夏の地方大会、春は前年の秋季県大会）の順位、それもなければ抽選。
    予選が終わって本大会を組むときに選ぶ（``main_seeds_after_prelim``）

  ``seed_assignment_method=main_size_fallback`` の行は、調査でシード校の数が分からなかった
  大会のゲームの仮の決まり。本大会の出場校の数でシード校の数を決め
  （``config/selection/prefectural_seed_fallback_v1.json``）、それを超える階級は使わない。
  1つの大会の行は選ぶ元が違ってもよい（岐阜の春：前年秋の上位4校＋地区予選の上位4校）。
  別の元で選んだ学校は数えずに、次の順位を繰り上げる。

- ``bracket_generation_policies.csv`` の ``MAIN`` の行：
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
STAGE_RANK = "stage_rank"
SELECTORS = (FINISH_RANK, POINTS_RANK, STAGE_RANK)
# 同じ大会の支部・地区予選（stage_rank の元）
PRELIM_STAGE = "prelim_stage"
PRELIM_STAGE_CODES = ("BRANCH_QUALIFIER", "PRELIMINARY_QUALIFIER")
MAIN_SIZE_FALLBACK = "main_size_fallback"
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "selection"
POINTS_CONFIG = CONFIG_DIR / "summer_seed_points_v1.json"
FALLBACK_CONFIG = CONFIG_DIR / "prefectural_seed_fallback_v1.json"


def _load(path: Path, config_id: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("config_id") != config_id:
        raise ValueError(f"{path.name}: config_id mismatch")
    return data


@lru_cache(maxsize=1)
def points_config() -> dict:
    return _load(POINTS_CONFIG, "summer_seed_points_v1")


@lru_cache(maxsize=1)
def fallback_config() -> dict:
    return _load(FALLBACK_CONFIG, "prefectural_seed_fallback_v1")


def game_seed_rules(repo, competition_id: str) -> list[dict]:
    """その大会の成績シードの行（階級の上から）。シード0校の行は除く。"""
    rows = [
        row for row in repo.seed_rules(competition_id)
        if row.get("source_result_selector") in SELECTORS
        and int(row.get("seed_count") or 0) > 0
    ]
    return sorted(rows, key=lambda row: (int(row["source_rank_from"]), row["seed_rule_id"]))


def summer_seed_rules(repo, competition_id: str) -> list[dict]:
    """その大会の夏のシードの行（階級の上から）。"""
    return [r for r in game_seed_rules(repo, competition_id) if r.get("season_segment") == SUMMER]


def chooses_after_prelim(repo, competition_id: str, rules: Sequence[Mapping] | None = None) -> bool:
    """支部・地区予選のある大会：本大会を組むとき（予選が終わったとき）にシードを選ぶ。"""
    rules = game_seed_rules(repo, competition_id) if rules is None else rules
    return bool(rules) and any(
        stage.get("stage_code") in PRELIM_STAGE_CODES for stage in repo.stages(competition_id)
    )


def _kinds(row: Mapping) -> list[str]:
    return [k for k in row.get("source_competition_type", "").split(";") if k]


def seed_sources(rules: Sequence[Mapping]) -> list[tuple[str, int]]:
    """シードを選ぶ元の大会（大会の種類, 年度のずれ）。前の年度は -1。
    同じ大会の予選（``prelim_stage``）は含めない（本大会を組むときに数える）。"""
    out: list[tuple[str, int]] = []
    for row in rules:
        kinds = _kinds(row)
        offsets = [int(v) for v in str(row.get("source_year_offset") or "0").split(";") if v]
        offsets += [offsets[-1] if offsets else 0] * (len(kinds) - len(offsets))
        for pair in zip(kinds, offsets):
            if pair[0] != PRELIM_STAGE and pair not in out:
                out.append(pair)
    return out


def merge_rankings(rankings: Sequence[Sequence[str]]) -> list[str]:
    """同じ種類の大会が2つあるとき（北・南北海道、東・西東京の夏）の順位を1つに。
    到達点の順に交互に並べる。"""
    keyed = []
    for index, ranking in enumerate(rankings):
        for position, school_id in enumerate(ranking):
            keyed.append((best_of(position), index, position, school_id))
    return list(dict.fromkeys(school_id for *_, school_id in sorted(keyed)))


def best_of(position: int) -> int:
    """順位の並びの位置（0から）→ 到達点（1＝優勝、2＝準優勝、4＝ベスト4…）。"""
    return 1 if position == 0 else next_power_of_two(position + 1)


def prelim_order(
    main_entrants: Sequence[str],
    prelim_matches: Iterable,
    tiebreak: Sequence[str] = (),
    *,
    base_seed: int,
    namespace: str,
) -> list[str]:
    """支部・地区予選の成績の順（``stage_rank``）。予選に出なかった（免除された）本大会の
    出場校が先、次に予選で負けの少ない順。同じなら ``tiebreak`` の順位、なければ抽選。"""
    played: set[str] = set()
    losses: dict[str, int] = {}
    for match in prelim_matches:
        if getattr(match, "is_bye", False):
            continue
        for team in (match.team1, match.team2):
            if team:
                played.add(team)
        if match.loser:
            losses[match.loser] = losses.get(match.loser, 0) + 1
    position = {school_id: index for index, school_id in enumerate(tiebreak)}
    rng = rng_for(base_seed, f"{namespace}:stage_seed:tie")
    entrants = list(dict.fromkeys(main_entrants))
    tie = {school_id: rng.random() for school_id in sorted(entrants)}
    return sorted(entrants, key=lambda s: (
        s in played, losses.get(s, 0), position.get(s, len(position)), tie[s],
    ))


def candidate_order(
    rules: Sequence[Mapping],
    rankings: Mapping[str, Sequence[str]],
    eligible: Iterable[str],
    *,
    base_seed: int,
    namespace: str,
    config: Mapping | None = None,
) -> list[str]:
    """シードの候補を良い順に（``rules`` は同じ選び方の行）。
    ``rankings`` は大会の種類 → 順位の並び（到達点の順）。予選の順は ``prelim_stage``。"""
    eligible = set(eligible)
    selector = rules[0].get("source_result_selector", FINISH_RANK) if rules else FINISH_RANK
    kinds = _kinds(rules[0]) if rules else []
    if selector in (FINISH_RANK, STAGE_RANK):
        kind = PRELIM_STAGE if selector == STAGE_RANK else (kinds[0] if kinds else "spring_prefectural")
        return [s for s in rankings.get(kind, ()) if s in eligible]
    if selector != POINTS_RANK:
        raise ValueError(f"unknown seed selector: {selector}")
    spring = [s for s in rankings.get("spring_prefectural", ()) if s in eligible]
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


def seed_total(rules: Sequence[Mapping], main_entrant_count: int, config: Mapping | None = None) -> int | None:
    """仮の決まり（``main_size_fallback``）の大会のシード校の数。それ以外は None（行のとおり）。"""
    if not any(row.get("seed_assignment_method") == MAIN_SIZE_FALLBACK for row in rules):
        return None
    config = config or fallback_config()
    if main_entrant_count >= int(config["large_min_main_entrants"]):
        return int(config["large_seed_count"])
    return int(config["small_seed_count"])


def _source_key(row: Mapping) -> tuple[str, str, str]:
    return (row.get("source_result_selector", FINISH_RANK),
            row.get("source_competition_type", ""), str(row.get("source_year_offset") or "0"))


def choose_seeds(
    rules: Sequence[Mapping],
    rankings: Mapping[str, Sequence[str]],
    eligible: Iterable[str],
    *,
    base_seed: int,
    namespace: str,
    config: Mapping | None = None,
    fallback: Mapping | None = None,
) -> list[str]:
    """シード校をシード番号の順に。階級の順に並べ、同じ階級の中は抽選。
    候補がシードの数より少なければ、いる学校だけ。"""
    eligible = list(dict.fromkeys(eligible))
    total = seed_total(rules, len(eligible), fallback)
    orders: dict[tuple, list[str]] = {}
    chosen_by: dict[tuple, set[str]] = {}
    out: list[str] = []
    for row in rules:
        low, high = int(row["source_rank_from"]), int(row["source_rank_to"])
        if total is not None:
            if low > total:
                continue
            high = min(high, total)
        key = _source_key(row)
        if key not in orders:
            orders[key] = candidate_order(
                [row], rankings, eligible, base_seed=base_seed, namespace=namespace, config=config,
            )
        others = set(out) - chosen_by.get(key, set())
        order = [s for s in orders[key] if s not in others]
        tier = [s for s in order[low - 1:high] if s not in out]
        chosen_by.setdefault(key, set()).update(tier)
        out += shuffled(tier, base_seed, f"{namespace}:summer_seed:{row['seed_rule_id']}")
    return out


def main_seeds_after_prelim(
    repo,
    annual,
    main_entrants: Sequence[str],
    prelim_matches: Iterable,
) -> list[str]:
    """支部・地区予選のある大会の本大会のシード校（予選が終わって本大会を組むとき）。
    ほかの大会の順位は ``annual.main_seed_rankings``（大会を始めるときに入れる）。"""
    rules = game_seed_rules(repo, annual.competition_id)
    if not rules:
        return []
    rankings = {kind: list(ids) for kind, ids in (annual.main_seed_rankings or {}).items()}
    stage_rows = [r for r in rules if r.get("source_result_selector") == STAGE_RANK]
    if stage_rows:
        kinds = [k for k in _kinds(stage_rows[0]) if k != PRELIM_STAGE]
        tiebreak = rankings.get(kinds[0], ()) if kinds else ()
        rankings[PRELIM_STAGE] = prelim_order(
            main_entrants, prelim_matches, tiebreak,
            base_seed=annual.rng_seed, namespace=annual.competition_id,
        )
    return choose_seeds(
        rules, rankings, main_entrants,
        base_seed=annual.rng_seed, namespace=annual.competition_id,
    )


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
