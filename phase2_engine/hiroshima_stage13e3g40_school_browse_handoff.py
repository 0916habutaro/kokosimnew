"""Stage 13E-3G-40: read-only, identity-checked GUI school handoff.

A Stage39 checked school identity is NOT proof that a scored SQLite
season exists. Only an exact 2026 school_records.school_id and prefecture=34
allow navigation to the existing scored browse GUI. No fallbacks by name,
no 2025/2027 records, no writes, and no blending historical qualifier games
with fictitious season scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .hiroshima_stage13e3g37_school_master import SchoolMasterPreviewLink

TARGET_YEAR = 2026
TARGET_PREFECTURE = "34"
SOURCE_NOTE = (
    "既存SQLiteの学校戦績はゲーム内のシミュレーション結果です。"
    "2026広島西部の二次資料による史実25試合と合算されません。"
)


@dataclass(frozen=True)
class SchoolBrowseHandoff:
    allowed: bool
    reason: str
    year: int
    school_id: str
    observed_name: str
    official_name: str
    source_note: str = SOURCE_NOTE
    read_only: bool = True
    added_qualifier_history_to_sqlite: bool = False
    official_2026_qualification_graph_verified: bool = False


def _blocked(reason: str, link: SchoolMasterPreviewLink | None = None) -> SchoolBrowseHandoff:
    return SchoolBrowseHandoff(
        allowed=False, reason=reason, year=TARGET_YEAR,
        school_id=link.school_id if link and link.authorized_for_read_only_detail else "",
        observed_name=link.observed_name if link else "",
        official_name=link.official_name if link and link.authorized_for_read_only_detail else "",
    )


def preflight_2026_west_school_browse_handoff(
    db_path: str | Path,
    link: SchoolMasterPreviewLink,
    *,
    selected_browse_year: int | None,
) -> SchoolBrowseHandoff:
    """Check an already Stage39-verified visible school and an existing DB.

    This deliberately does not call BrowseRepository: that class creates a
    SQLite file/schema as part of connecting; the preflight MUST never do so.
    """
    if not isinstance(link, SchoolMasterPreviewLink):
        raise TypeError("Stage39 SchoolMasterPreviewLink required")
    if (
        not link.authorized_for_read_only_detail
        or link.prefecture_code != TARGET_PREFECTURE
        or not link.school_id.startswith("SCH")
        or not link.program_id.startswith("PRG")
        or not link.official_name
        or link.official_2026_draw_verified
        or link.live_fmt025_runtime_enabled
    ):
        return _blocked("学校マスターの2026年照合が未確認です。", link)
    if type(selected_browse_year) is not int or selected_browse_year != TARGET_YEAR:
        return _blocked("既存GUIで2026年を選択してください。別年度へ自動切替しません。", link)
    target = Path(db_path)
    if not target.is_file():
        return _blocked("閲覧用SQLiteが存在しません。元の学校情報のみ参照できます。", link)

    try:
        # mode=ro prevents DB creation/DDL/DML even on an otherwise writable
        # filesystem. URI is made from the resolved file path, not user text.
        uri = target.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.execute("PRAGMA query_only = ON")
            found = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='school_records'"
            ).fetchone()
            if found is None:
                return _blocked("SQLiteに学校戦績テーブルがありません。", link)
            rows = conn.execute(
                "SELECT school_id, prefecture_code FROM school_records "
                "WHERE year = ? AND school_id = ? LIMIT 2",
                (TARGET_YEAR, link.school_id),
            ).fetchall()
    except (sqlite3.Error, OSError) as exc:
        return _blocked(f"SQLiteの学校戦績を読み取れません: {type(exc).__name__}", link)

    if len(rows) != 1:
        return _blocked("2026年SQLiteに対象学校IDの戦績が一意に存在しません。", link)
    if str(rows[0][0]) != link.school_id or str(rows[0][1]).zfill(2) != TARGET_PREFECTURE:
        return _blocked("SQLite学校IDと広島県コードの対応が一致しません。", link)
    return SchoolBrowseHandoff(
        allowed=True, reason="2026年SQLiteの同一学校IDへ移動できます。",
        year=TARGET_YEAR, school_id=link.school_id,
        observed_name=link.observed_name, official_name=link.official_name,
    )
