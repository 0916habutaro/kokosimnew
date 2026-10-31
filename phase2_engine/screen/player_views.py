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


def injury_row(start: str, days: int, severity: int) -> dict:
    """怪我（重さ・休み始めた日・休む日数・復帰の見込みの日）。"""
    from datetime import date, timedelta

    from game_core.injuries import injury_model

    first = date.fromisoformat(start)
    back = first + timedelta(days=days)
    return {
        "severity": severity, "label": injury_model().label(severity),
        "start": first.isoformat(), "days": days, "return_date": back.isoformat(),
    }


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


# 学校の部員の一覧に出す能力（投手と野手で別の表）
MEMBER_PITCHER = (("velocity_kmh", "球速"), ("control", "制球"), ("stamina", "スタミナ"))
MEMBER_BATTER = (("contact", "ミート"), ("power", "長打"), ("speed", "走力"), ("fielding", "守備"))


def member_abilities(values: dict | None, position: str, bands) -> dict:
    """部員の一覧の能力（投手は球速・制球・スタミナ、野手はミート・長打・走力・守備）。"""
    keys = MEMBER_PITCHER if position == "P" else MEMBER_BATTER
    return {
        key: {
            "value": (values or {}).get(key),
            "rank": "" if key == "velocity_kmh" else rank((values or {}).get(key), bands),
        }
        for key, _ in keys
    }


def member_stats(stats: dict) -> dict:
    """``season_stats`` の結果 → 部員の一覧の成績（並べ替えできるよう数で持つ）。"""
    batting, pitching = stats["batting"], stats["pitching"]
    return {
        "average": batting["hits"] / batting["at_bats"]
        if batting and batting["at_bats"] else None,
        "home_runs": batting["home_runs"] if batting else None,
        "era": pitching["earned_runs"] * 27 / pitching["outs_recorded"]
        if pitching and pitching["outs_recorded"] else None,
        "outs": pitching["outs_recorded"] if pitching else None,
    }


def aptitude_rows(aptitudes: dict, labels: dict, bands) -> list[dict]:
    """守備位置の適性（守備位置の順に、名前・値・ランク）。"""
    return [
        {"key": key, "label": labels.get(key, key), "value": aptitudes[key],
         "rank": rank(aptitudes[key], bands)}
        for key in FIELD_POSITIONS if aptitudes.get(key) is not None
    ]


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
