"""甲子園の「ゲーム開始前の実際の記録」と「ゲーム内の記録」を並べる（game_definition.md §9）。

実際の記録は ``historical_data/koshien_records.csv``（1行＝1校×夏／春の通算。
夏は2025年、春は2026年の選抜まで）。ゲーム内の記録とは混ぜずに持ち、画面では
合計と内訳を並べる。行がない学校はゲーム内の記録だけにする。
"""
from __future__ import annotations

import csv
from pathlib import Path


RECORDS_PATH = Path("historical_data") / "koshien_records.csv"
KINDS = ("summer", "spring")
# 最高成績の比べ方（実際の記録の「3回戦」は3回戦で負けたこと）
_RANKS = {
    "優勝": 8, "準優勝": 7, "決勝進出": 7, "ベスト4": 6, "ベスト8": 5,
    "ベスト16": 4, "3回戦": 3, "2回戦": 2, "1回戦": 1, "初戦敗退": 1,
}


def result_rank(label: str) -> int:
    if label in _RANKS:
        return _RANKS[label]
    # ゲーム内の「2回戦敗退」「3回戦進出」
    digits = "".join(ch for ch in label if ch.isdigit())
    return int(digits) if digits else 0


def _int(value: str) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


def load_actual(path: str | Path) -> dict[str, dict[str, dict]]:
    """学校ID → {"summer"/"spring": 実際の通算}。ファイルがなければ空。"""
    path = Path(path)
    if not path.is_file():
        return {}
    out: dict[str, dict[str, dict]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            years = [int(y) for y in (row.get("appearance_years") or "").split(";") if y]
            out.setdefault(row["school_id"], {})[row["kind"]] = {
                "appearances": int(row["appearances"]),
                "wins": int(row["wins"]),
                "losses": int(row["losses"]),
                "draws": _int(row.get("draws", "")) or 0,
                "championships": _int(row.get("championships", "")) or 0,
                "best": row.get("best_result", ""),
                "last_year": _int(row.get("last_appearance_year", "")),
                "years": years,
            }
    return out


def combined(actual: dict | None, game: dict) -> dict:
    """合計（実際＋ゲーム内）と内訳。実際の記録がなければ合計はゲーム内と同じ。"""
    parts = [part for part in (actual, game) if part]
    best = max(
        (part["best"] for part in parts if part.get("best")),
        key=result_rank, default="",
    )
    last = max(
        [part["last_year"] for part in parts if part.get("last_year")]
        + list(game.get("years", [])),
        default=None,
    )
    return {
        "total": {
            "appearances": sum(part["appearances"] for part in parts),
            "wins": sum(part["wins"] for part in parts),
            "losses": sum(part["losses"] for part in parts),
            "draws": sum(part.get("draws", 0) for part in parts),
            "championships": sum(part.get("championships", 0) for part in parts),
            "best": best,
            "last_year": last,
        },
        "actual": actual,
        "game": game,
    }


def count_label(actual: int, game: int) -> dict:
    """記録の画面の「〇回目」と内訳。"""
    return {"total": actual + game, "actual": actual, "game": game}
