"""能力ランキングの画面：学校のチーム力を並べる（game_definition.md §9）。

学校の能力は ``SchoolAbilities``（school_views.py）が今日の部員から出した値をそのまま使い、
ここでは並べ替え・順位・評判との差・都道府県の強さだけを計算する。保存はしない。
調整値（件数・上位◯校・差のしきい値）は ``config/screen/ability_rankings_v1.json``。
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path("screen") / "ability_rankings_v1.json"
TEAM_SORT_KEYS = ("overall", "batting", "pitching", "defense", "running")


def load_config(config_root: str | Path) -> dict:
    data = json.loads((Path(config_root) / CONFIG_PATH).read_text(encoding="utf-8"))
    if data.get("config_id") != "ability_rankings_v1":
        raise ValueError("ability_rankings config_id mismatch")
    return data


def places(values: dict[str, float]) -> dict[str, int]:
    """キー → 順位（1から。値の高い順、同じ値はキーの順）。"""
    order = sorted(values, key=lambda key: (-values[key], key))
    return {key: index for index, key in enumerate(order, start=1)}


def team_rows(abilities: dict[str, dict | None], *, sort_key: str = "overall") -> list[dict]:
    """学校ID → 能力 から、``sort_key`` の高い順の行（同じ値は学校ID順）。

    能力のない学校（部員が9人に満たない）は出さない。"""
    if sort_key not in TEAM_SORT_KEYS:
        sort_key = "overall"
    shown = {sid: values for sid, values in abilities.items() if values}
    order = places({sid: values[sort_key] for sid, values in shown.items()})
    return [{"school_id": sid, "place": order[sid], "abilities": shown[sid]}
            for sid in sorted(order, key=order.get)]


def reputation_gap(reputation: dict[str, float], overall: dict[str, float],
                   *, min_places: int) -> dict[str, list[dict]]:
    """評判の順位と総合の順位の差。両方の値がある学校の中で順位を数える。

    ダークホース（``dark_horse``）は総合の順位が評判の順位より ``min_places`` 以上高い学校、
    名前負け（``underperformer``）は ``min_places`` 以上低い学校。どちらも差の大きい順
    （同じ差は学校ID順）。``gap`` は順位の数の差（正の数）。"""
    both = [sid for sid in overall if sid in reputation]
    rep_place = places({sid: reputation[sid] for sid in both})
    overall_place = places({sid: overall[sid] for sid in both})
    out = {"dark_horse": [], "underperformer": []}
    for sid in both:
        gap = rep_place[sid] - overall_place[sid]
        if abs(gap) < min_places:
            continue
        out["dark_horse" if gap > 0 else "underperformer"].append({
            "school_id": sid, "reputation_place": rep_place[sid],
            "overall_place": overall_place[sid], "gap": abs(gap),
        })
    for rows in out.values():
        rows.sort(key=lambda row: (-row["gap"], row["school_id"]))
    return out


def prefecture_strength(overall: dict[str, float], prefecture_of, *, top_n: int) -> list[dict]:
    """都道府県ごとの総合の上位 ``top_n`` 校の平均（高い順。同じ値は都道府県コード順）。

    学校が ``top_n`` 校に満たない県はある学校だけの平均。``top_school_id`` は県で1位の学校。"""
    by_prefecture: dict[str, list[tuple[float, str]]] = {}
    for sid, value in overall.items():
        code = prefecture_of(sid)
        if code:
            by_prefecture.setdefault(code, []).append((value, sid))
    rows = []
    for code, entries in by_prefecture.items():
        entries.sort(key=lambda entry: (-entry[0], entry[1]))
        top = entries[:top_n]
        rows.append({
            "prefecture_code": code,
            "average": round(sum(value for value, _ in top) / len(top), 1),
            "count": len(top),
            "top_school_id": top[0][1],
            "top_overall": top[0][0],
        })
    rows.sort(key=lambda row: (-row["average"], row["prefecture_code"]))
    for place, row in enumerate(rows, start=1):
        row["place"] = place
    return rows
