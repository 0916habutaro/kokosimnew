"""セーブの管理画面に出す一覧（game_definition.md §9）。

セーブの読み書きは ``LiveGameService`` に任せ、ここは画面に出す形に直すだけ。
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path


SOURCE_LABELS = {"manual": "手動セーブ", "autosave": "自動セーブ"}
SLOT_PREFIX = "slot"


def source_label(source: str) -> str:
    kind, _, generation = source.partition("_backup_")
    label = SOURCE_LABELS.get(kind, source)
    return f"{label}（{generation}つ前）" if generation else label


def saved_at_label(path: str) -> str:
    try:
        moment = datetime.fromtimestamp(Path(path).stat().st_mtime)
    except OSError:
        return ""
    return f"{moment.year}/{moment.month}/{moment.day} {moment:%H:%M}"


def game_date_label(value: str) -> str:
    if not value:
        return ""
    day = date.fromisoformat(value)
    return f"{day.year}年{day.month}月{day.day}日"


def _file_row(source: str, file: dict) -> dict:
    metadata = file.get("metadata") or {}
    return {
        "source": source,
        "label": source_label(source),
        "valid": file.get("status") == "valid",
        "error": file.get("error", ""),
        "date_label": game_date_label(metadata.get("current_date", "")),
        "saved_at": saved_at_label(file.get("path", "")),
    }


def slot_rows(summaries: list[dict], current_slot: str) -> list[dict]:
    """``LiveGameService.list_games`` の結果を、画面の一覧の行にする。"""
    rows = []
    for summary in summaries:
        user = summary.get("user_metadata") or {}
        latest = summary.get("latest_source", "")
        files = [
            _file_row(kind, summary[kind])
            for kind in SOURCE_LABELS if summary[kind].get("exists")
        ]
        newest = next((row for row in files if row["source"] == latest), None)
        rows.append({
            "slot_id": summary["slot_id"],
            "title": user.get("title") or summary["slot_id"],
            "current": summary["slot_id"] == current_slot,
            "date_label": newest["date_label"] if newest else "",
            "saved_at": newest["saved_at"] if newest else "",
            "loadable": bool(newest and newest["valid"]),
            "files": files,
        })
    return rows


def recovery_rows(sources: list[dict]) -> list[dict]:
    return [_file_row(row["source"], row) for row in sources]


def next_slot_id(existing) -> str:
    """まだ使っていない ``slot01`` の形の名前を返す。"""
    used = set(existing)
    number = 1
    while f"{SLOT_PREFIX}{number:02d}" in used:
        number += 1
    return f"{SLOT_PREFIX}{number:02d}"
