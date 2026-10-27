"""選手の画面：能力の表示（S〜G）と、試合の記録からの年度ごとの成績。"""
from __future__ import annotations

from game_core.abilities import FIELD_POSITIONS
from game_core.player_growth import SCALARS


# 能力の名前（画面に出す順）
BATTER_LABELS = (
    ("contact", "ミート"), ("power", "長打"), ("plate_discipline", "選球"),
    ("strikeout_resistance", "三振しにくさ"), ("bunt", "バント"), ("speed", "走力"),
    ("baserunning", "走塁"), ("stealing", "盗塁"), ("arm_strength", "肩"),
    ("fielding", "守備"), ("throwing", "送球"),
)
CATCHER_LABELS = (("catching", "捕球"), ("game_calling", "リード"))
PITCHER_LABELS = (
    ("velocity_kmh", "球速"), ("control", "制球"), ("stamina", "スタミナ"),
    ("stuff", "球威"), ("strikeout", "奪三振"), ("groundball", "ゴロ"),
    ("composure", "度胸"),
)
# 学年ごとの推移に出す能力（多すぎないように主なものだけ）
TREND_BATTER = ("contact", "power", "plate_discipline", "speed", "arm_strength", "fielding")
TREND_PITCHER = ("velocity_kmh", "control", "stamina", "stuff", "strikeout")
PITCH_LABELS = {
    "four_seam": "ストレート", "two_seam": "ツーシーム", "slider": "スライダー",
    "curve": "カーブ", "fork": "フォーク", "changeup": "チェンジアップ",
    "sinker": "シンカー", "cutter": "カットボール",
}
GROWTH_LABELS = {"early": "早熟", "normal": "普通", "late": "晩成"}
BATTING_KEYS = (
    "plate_appearances", "at_bats", "hits", "doubles", "triples", "home_runs",
    "rbi", "runs", "walks", "strikeouts", "stolen_bases",
)
PITCHING_KEYS = (
    "outs_recorded", "batters_faced", "hits_allowed", "runs_allowed",
    "earned_runs", "walks", "strikeouts", "home_runs_allowed", "pitches",
)


def ability_values(values, pitch_types) -> dict:
    """1項目1バイトの能力（roster_book.pack_abilities の並び）→ 名前 → 値。"""
    out = {name: (values[i] or None) for i, name in enumerate(SCALARS)}
    offset = len(SCALARS)
    out["position_aptitude"] = {
        position: values[offset + i] for i, position in enumerate(FIELD_POSITIONS)
    }
    offset += len(FIELD_POSITIONS)
    out["pitches"] = [
        {
            "pitch_type": pitch_types[values[i]],
            "label": PITCH_LABELS.get(pitch_types[values[i]], pitch_types[values[i]]),
            "quality": values[i + 1], "command": values[i + 2], "usage": values[i + 3],
        }
        for i in range(offset, len(values), 4)
    ]
    return out


def snapshot_values(snapshot) -> dict:
    """能力（PlayerAbilitySnapshot）→ 名前 → 値。"""
    out = {name: getattr(snapshot, name) for name in SCALARS}
    out["position_aptitude"] = dict(snapshot.position_aptitude)
    out["pitches"] = [
        {
            "pitch_type": pitch.pitch_type,
            "label": PITCH_LABELS.get(pitch.pitch_type, pitch.pitch_type),
            "quality": pitch.quality, "command": pitch.command, "usage": pitch.usage,
        }
        for pitch in snapshot.pitch_repertoire
    ]
    return out


def rank(value, bands) -> str:
    if value is None:
        return ""
    for band in bands:
        if band["min"] <= value:
            return band["grade"]
    return bands[-1]["grade"]


def ability_rows(values: dict, position: str, bands) -> list[dict]:
    """能力の一覧（名前・値・ランク）。球速はランクの代わりに km/h。"""
    labels = list(BATTER_LABELS)
    if position == "C":
        labels += CATCHER_LABELS
    if position == "P":
        labels = list(PITCHER_LABELS) + labels
    rows = []
    for key, label in labels:
        value = values.get(key)
        if value is None:
            continue
        rows.append({
            "key": key, "label": label, "value": value,
            "rank": "" if key == "velocity_kmh" else rank(value, bands),
            "group": "pitcher" if key in dict(PITCHER_LABELS) else "batter",
        })
    return rows


def trend_keys(position: str) -> list[tuple[str, str]]:
    labels = dict(BATTER_LABELS) | dict(PITCHER_LABELS)
    keys = (TREND_PITCHER + TREND_BATTER[:2]) if position == "P" else TREND_BATTER
    return [(key, labels[key]) for key in keys]


def _innings(outs: int) -> str:
    whole, part = divmod(outs, 3)
    return f"{whole}" + (f" {part}/3" if part else "")


def season_stats(details, player_id: str) -> dict:
    """試合の記録（個人成績つき）の並びから、その選手の打撃・投手の合計。"""
    batting = {key: 0 for key in BATTING_KEYS}
    pitching = {key: 0 for key in PITCHING_KEYS}
    games = pitched = 0
    for detail in details:
        batter = next(
            (s for s in detail.get("batter_stats") or () if s.get("player_id") == player_id), None,
        )
        if batter is not None:
            games += 1
            for key in BATTING_KEYS:
                batting[key] += int(batter.get(key, 0) or 0)
        pitcher = next(
            (s for s in detail.get("pitcher_stats") or () if s.get("player_id") == player_id), None,
        )
        if pitcher is not None:
            pitched += 1
            for key in PITCHING_KEYS:
                pitching[key] += int(pitcher.get(key, 0) or 0)
    at_bats, outs = batting["at_bats"], pitching["outs_recorded"]
    return {
        "batting": {
            **batting, "games": games,
            "average": f"{batting['hits'] / at_bats:.3f}".lstrip("0") if at_bats else "−",
        } if games else None,
        "pitching": {
            **pitching, "games": pitched, "innings": _innings(outs),
            # 高校野球は9回
            "era": f"{pitching['earned_runs'] * 27 / outs:.2f}" if outs else "−",
        } if pitched else None,
    }
