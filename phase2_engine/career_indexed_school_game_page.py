"""Stage43G-74: bounded, school-first indexed historical match pages.

This is ONLY for legacy A match archives (ISO years <= 9999). It does NOT
read the unrelated fictional-v2 sidecar. Page mode validates all *visible*
payloads; window mode validates ALL matching payloads, including records
outside the requested page. Do not claim page mode proves an entire season.
The existing grouped school_results method keeps its strict all-record scan.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from .career_option_a_storage_profile import _read_only
from .historical_match_archive import expand_payload


class IndexedSchoolGamePageConflict(ValueError):
    """A saved match payload, score, or identity disagrees with its index."""


_COLUMNS = (
    "year,competition_id,match_id,match_date,team1_id,team2_id,"
    "team1_score,team2_score,record_sha256,payload_json"
)


def _branch(team: str, competition_id: str | None, *,
            count_only: bool = False) -> str:
    if team not in ("team1_id", "team2_id"):
        raise ValueError("unrecognized indexed team column")
    cols = "COUNT(*)" if count_only else _COLUMNS
    suffix = " AND competition_id=?" if competition_id is not None else ""
    return (
        f"SELECT {cols} FROM historical_matches "
        f"WHERE {team}=? AND year BETWEEN ? AND ?{suffix}"
    )


def _args(school_id: str, start_year: int, end_year: int,
          competition_id: str | None) -> tuple:
    original = (school_id, start_year, end_year)
    return original + ((competition_id,) if competition_id is not None else ())


def _verified(row: sqlite3.Row, school_id: str) -> dict:
    raw = row["payload_json"]
    if (type(raw) is not str or type(row["record_sha256"]) is not str
            or sha256(raw.encode("utf-8")).hexdigest() != row["record_sha256"]):
        raise IndexedSchoolGamePageConflict("saved match record digest differs")
    try:
        value = expand_payload(json.loads(raw))
    except (TypeError, ValueError) as exc:
        raise IndexedSchoolGamePageConflict("saved match payload invalid") from exc
    if (type(value) is not dict
            or any(value.get(k) != row[k] for k in (
                "year", "competition_id", "match_id", "match_date",
                "team1_id", "team2_id", "team1_score", "team2_score",
            ))
            or school_id not in (row["team1_id"], row["team2_id"])
            or row["team1_id"] == row["team2_id"]
            or type(row["team1_score"]) is not int
            or type(row["team2_score"]) is not int
            or row["team1_score"] < 0 or row["team2_score"] < 0
            or row["team1_score"] == row["team2_score"]):
        raise IndexedSchoolGamePageConflict("saved match indexed fields disagree")
    expected_winner = (
        row["team1_id"] if row["team1_score"] > row["team2_score"]
        else row["team2_id"]
    )
    loser = (
        row["team2_id"] if expected_winner == row["team1_id"]
        else row["team1_id"]
    )
    if (value.get("winner_id") != expected_winner
            or value.get("loser_id") != loser):
        raise IndexedSchoolGamePageConflict("saved match winner disagrees")
    home = row["team1_id"] == school_id
    school_score = row["team1_score"] if home else row["team2_score"]
    opponent_score = row["team2_score"] if home else row["team1_score"]
    return {
        "year": row["year"],
        "competition_id": row["competition_id"],
        "match_id": row["match_id"],
        "match_date": row["match_date"],
        "school_id": school_id,
        "opponent_school_id": row["team2_id"] if home else row["team1_id"],
        "runs_for": school_score,
        "runs_against": opponent_score,
        "result_for_school": "win" if school_score > opponent_score else "loss",
        "stored_source": "legacy_a_archived_match",
        "full_option_a_fields_not_inferred": True,
    }


def read_indexed_school_game_page(
    matches: str | Path, school_id: str, *, start_year: int,
    end_year: int, competition_id: str | None = None,
    limit: int = 30, offset: int = 0,
    verify_scope: str = "page",
) -> dict:
    """Page original saved matches using BOTH existing school-first indexes.

    SELECT of payload_json is limited to requested matches unless
    verify_scope="filtered_window" is explicitly requested, in which case
    SHA and identity checks cover all matching source rows, including offpage.
    COUNT queries select only index columns and never decode whole-A JSON.
    """
    if (type(school_id) is not str or not school_id
            or type(start_year) is not int or type(end_year) is not int
            or not 1 <= start_year <= end_year <= 9999
            or competition_id is not None
            and (type(competition_id) is not str or not competition_id)
            or type(limit) is not int or not 1 <= limit <= 200
            or type(offset) is not int or offset < 0
            or verify_scope not in ("page", "filtered_window")
            or type(verify_scope) is not str):
        raise ValueError("invalid legacy year, school, tournament, or page")
    path = Path(matches)
    if not path.is_file():
        return {
            "school_id": school_id, "start_year": start_year,
            "end_year": end_year, "competition_id": competition_id,
            "records": [], "total": 0, "limit": limit, "offset": offset,
            "verification_scope": verify_scope,
            "visible_match_checksums_verified": True,
            "all_filtered_window_checksums_verified":
                verify_scope == "filtered_window",
            "source_records_not_modified": True,
        }

    args = _args(school_id, start_year, end_year, competition_id)
    select = (
        _branch("team1_id", competition_id) + " UNION ALL " +
        _branch("team2_id", competition_id)
    )
    # Index-backed separate COUNTs are cheaper than fetching/decoding
    # potentially decades of A box scores only to count page entries.
    count1 = _branch("team1_id", competition_id, count_only=True)
    count2 = _branch("team2_id", competition_id, count_only=True)
    page_sql = (
        "SELECT * FROM (" + select + ") "
        "ORDER BY year,competition_id,match_id LIMIT ? OFFSET ?"
    )
    with closing(_read_only(path)) as conn:
        conn.row_factory = sqlite3.Row
        total = sum(
            conn.execute(query, args).fetchone()[0]
            for query in (count1, count2)
        )
        records = [
            _verified(row, school_id) for row in conn.execute(
                page_sql, args + args + (limit, offset),
            )
        ]
        if verify_scope == "filtered_window":
            checked = 0
            for row in conn.execute(
                "SELECT * FROM (" + select + ") "
                "ORDER BY year,competition_id,match_id",
                args + args,
            ):
                _verified(row, school_id)
                checked += 1
            if checked != total:
                raise IndexedSchoolGamePageConflict(
                    "school games changed during strict window verification"
                )
    return {
        "school_id": school_id,
        "start_year": start_year, "end_year": end_year,
        "competition_id": competition_id,
        "records": records, "total": total,
        "limit": limit, "offset": offset,
        "verification_scope": verify_scope,
        "visible_match_checksums_verified": True,
        "all_filtered_window_checksums_verified":
            verify_scope == "filtered_window",
        "unselected_competitions_not_verified": competition_id is not None,
        "unselected_years_not_verified": True,
        "source_records_not_modified": True,
        "no_unbounded_payload_materialization_for_page_mode": True,
    }
