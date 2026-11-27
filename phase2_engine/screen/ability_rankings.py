"""能力ランキングの画面：学校のチーム力と選手の能力を並べる（game_definition.md §9）。

学校の能力は ``SchoolAbilities``（school_views.py）が今日の部員から出した値をそのまま使い、
ここでは並べ替え・順位・評判との差・都道府県の強さだけを計算する。選手は、選手の詳細と
同じ今日の能力から、重み付きの総合・守備位置ごとの総合・プロ注目を出す。保存はしない。
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


# ---- 選手 ----

POSITIONS = ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
PLAYER_VIEWS = ("overall", "position", "featured")


def player_overall(values: dict, weights: dict[str, float]) -> float | None:
    """Σ（能力×重み）÷Σ重み（小数1桁）。値のない能力は重みごと除く。どれもなければ None。"""
    total = weight_sum = 0.0
    for key, weight in weights.items():
        value = values.get(key)
        if value is None:
            continue
        total += float(value) * float(weight)
        weight_sum += float(weight)
    return round(total / weight_sum, 1) if weight_sum else None


def kind_of(position: str) -> str:
    """主な守備位置が P なら投手（``pitcher``）、ほかは野手（``batter``）。"""
    return "pitcher" if position == "P" else "batter"


def position_weights(overall_config: dict, position: str) -> dict[str, float]:
    """守備位置ごとの重み。``"pitcher"`` のように種類の名前なら、その種類の重み。"""
    weights = overall_config["by_position"][position]
    return overall_config[weights] if isinstance(weights, str) else weights


def featured_reasons(values: dict, is_prospect: bool | None, keys, grade_of, grade: str) -> list[str]:
    """プロ注目の理由：有望な新入生なら ``"prospect"``、続けて文字が ``grade`` の能力の名前。

    ``grade_of(値)`` は選手の文字。どれにも当たらなければ空。"""
    reasons = ["prospect"] if is_prospect else []
    reasons += [key for key in keys if values.get(key) is not None and grade_of(values[key]) == grade]
    return reasons


def player_rows(players: list[dict], *, kind: str | None = None, position: str | None = None,
                grade: int | None = None, weights: dict | None = None,
                featured: bool = False) -> list[dict]:
    """選手の行を並べる（値の高い順、同じ値は選手ID順）。

    ``players`` は {player_id, grade, position, overall, values, reasons, ...}。``kind`` で野手・投手、
    ``position`` で主な守備位置、``grade`` で学年、``featured`` でプロ注目（``reasons`` のある選手）に絞る。
    ``weights`` を渡すとその重みの総合（守備位置ごと）で並べ、``score`` に入れる。渡さなければ総合。"""
    out = []
    for player in players:
        if kind and kind_of(player["position"]) != kind:
            continue
        if position and player["position"] != position:
            continue
        if grade and player["grade"] != grade:
            continue
        if featured and not player["reasons"]:
            continue
        score = player_overall(player["values"], weights) if weights else player["overall"]
        if score is None:
            continue
        out.append({**player, "score": score})
    out.sort(key=lambda row: (-row["score"], row["player_id"]))
    for place, row in enumerate(out, start=1):
        row["place"] = place
    return out
