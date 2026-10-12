"""Stage43G-76: read-only school match pages for sealed fictional v2 years.

The v2 archive has no indexed school-id columns. JSON1 school filtering must
scan in-range match payloads at SQL level. This is deliberately NOT advertised
as an indexed/O(30) equivalent of Stage43G-74. Legacy ISO records remain in
their separate SQLite archive. Existing sealed v2 databases are never altered.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .career_calendar_v2 import CareerCalendarV2Archive
from .career_option_a_storage_profile import _read_only
from .career_v2_option_a_archive import (
    CareerV2MatchConflict, SOURCE, _calendar_info, _ledger, _verify_match,
)

MAX_WINDOW_YEARS = 100
PAGE_SIZE = 30

# Year bounds and a JSON school-membership predicate. Unlike legacy A, v2's
# authoritative school IDs exist only inside the immutable JSON record. This
# predicate is not index-backed and even SQL COUNT must inspect JSON.
_SCHOOL_SQL = (
    "year BETWEEN ? AND ? AND "
    "(json_extract(payload_json, '$.team1_id')=? OR "
    "json_extract(payload_json, '$.team2_id')=?)"
)


class CareerV2SchoolPageConflict(CareerV2MatchConflict):
    """A selected fictional-v2 school page has inconsistent saved sources."""


def _presentation(row: sqlite3.Row, school_id: str, plan: dict,
                  plan_sha: str) -> dict:
    game = _verify_match(row, plan, plan_sha)
    a, b = game.get("team1_id"), game.get("team2_id")
    if (type(a) is not str or not a or type(b) is not str or not b
            or a == b or school_id not in (a, b)):
        raise CareerV2SchoolPageConflict("v2 school membership differs")
    first = a == school_id
    own = game["team1_score"] if first else game["team2_score"]
    opp = game["team2_score"] if first else game["team1_score"]
    if (type(own) is not int or type(opp) is not int
            or own < 0 or opp < 0 or own == opp
            or game.get("loser_id") != (b if own > opp and first
                                        else a if own > opp
                                        else a if first else b)):
        # Explicitly cross-check loser metadata in addition to _verify_match's
        # winner and score contract.
        raise CareerV2SchoolPageConflict("v2 score or loser identity differs")
    return {
        "year": row["year"],
        "competition_id": row["competition_id"],
        "match_id": row["match_id"],
        "game_day_token": row["game_day_token"],
        "school_id": school_id,
        "opponent_school_id": b if first else a,
        "runs_for": own,
        "runs_against": opp,
        "result_for_school": "win" if own > opp else "loss",
        "stored_source": SOURCE,
        "full_option_a_original_retained": True,
        "logical_game_date_not_iso": True,
    }


def read_v2_school_game_page(
    v2_path: str | Path, calendar_path: str | Path, school_id: str, *,
    start_year: int, end_year: int, competition_id: str | None = None,
    limit: int = PAGE_SIZE, offset: int = 0, verify_scope: str = "page",
) -> dict:
    """Page fictional saved school games; preserve independent source facts.

    'page' verifies every visible payload plus every in-range *saved* sealed
    year header, calendar plan and checksum ledger (not offpage JSON).
    'selected_years' additionally verifies ALL source match JSON in every
    present year inside the date window, including other schools. This
    stronger scope detects school-membership tampering otherwise invisible
    to SQLite JSON1 filtering. Neither mode proves unsaved years had games.
    """
    if (type(school_id) is not str or not school_id
            or type(start_year) is not int or type(end_year) is not int
            or start_year < 10000 or end_year < start_year
            or end_year - start_year >= MAX_WINDOW_YEARS
            or competition_id is not None and (
                type(competition_id) is not str or not competition_id
            )
            or type(limit) is not int or not 1 <= limit <= 200
            or type(offset) is not int or offset < 0
            or type(verify_scope) is not str
            or verify_scope not in ("page", "selected_years")):
        raise ValueError("invalid fictional-v2 school, year, filter or page")
    path = Path(v2_path)
    if not path.is_file():
        return {
            "school_id": school_id, "start_year": start_year,
            "end_year": end_year, "competition_id": competition_id,
            "records": [], "total": 0, "limit": limit, "offset": offset,
            "verification_scope": verify_scope, "verified_saved_years": [],
            "visible_match_checksums_verified": True,
            "all_selected_year_payloads_verified":
                verify_scope == "selected_years",
            "school_membership_integrity_for_years_verified":
                verify_scope == "selected_years",
            "source_records_not_modified": True,
            "legacy_records_combined": False,
            "school_filter_uses_unindexed_json_scan": True,
            "unsaved_years_not_inferred": True,
        }

    calendar = CareerCalendarV2Archive(calendar_path)
    where = _SCHOOL_SQL
    params: tuple = (start_year, end_year, school_id, school_id)
    if competition_id is not None:
        where += " AND competition_id=?"
        params += (competition_id,)
    with closing(_read_only(path)) as conn:
        conn.row_factory = sqlite3.Row
        # Same-file read snapshot for header, SHA ledger and page.
        conn.execute("BEGIN")
        try:
            headers = conn.execute(
                "SELECT year,status,calendar_sha256,match_count,ledger_sha256 "
                "FROM v2_game_years WHERE year BETWEEN ? AND ? ORDER BY year",
                (start_year, end_year),
            ).fetchall()
            plans: dict[int, tuple[dict, str]] = {}
            for header in headers:
                year = header["year"]
                if header["status"] != "sealed":
                    raise CareerV2SchoolPageConflict("v2 year is not sealed")
                plan, sha = _calendar_info(calendar, year)
                if sha != header["calendar_sha256"]:
                    raise CareerV2SchoolPageConflict("v2 calendar SHA differs")
                count, ledger = _ledger(conn, year)
                if (count != header["match_count"]
                        or ledger != header["ledger_sha256"]):
                    raise CareerV2SchoolPageConflict("v2 sealed ledger differs")
                plans[year] = (plan, sha)

            # Strict mode intentionally verifies ALL payloads in selected
            # saved years, because school IDs are not in indexed SQL columns.
            # Thus even a changed school ID that drops out of the JSON1
            # membership filter is rejected. Page mode does not promise this.
            if verify_scope == "selected_years":
                for row in conn.execute(
                    "SELECT * FROM v2_option_a_matches "
                    "WHERE year BETWEEN ? AND ?",
                    (start_year, end_year),
                ):
                    plan, sha = plans[row["year"]]
                    _verify_match(row, plan, sha)
            total = conn.execute(
                "SELECT COUNT(*) FROM v2_option_a_matches WHERE " + where,
                params,
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM v2_option_a_matches WHERE " + where +
                " ORDER BY year,game_day_token,competition_id,match_id "
                "LIMIT ? OFFSET ?",
                params + (limit, offset),
            ).fetchall()
            records = [
                _presentation(row, school_id, *plans[row["year"]])
                for row in rows
            ]
        except (sqlite3.DatabaseError, KeyError, TypeError) as exc:
            raise CareerV2SchoolPageConflict(
                "unreadable fictional-v2 saved school page"
            ) from exc
    return {
        "school_id": school_id, "start_year": start_year,
        "end_year": end_year, "competition_id": competition_id,
        "records": records, "total": total, "limit": limit, "offset": offset,
        "verification_scope": verify_scope,
        "verified_saved_years": list(plans),
        "saved_year_metadata_and_ledger_verified": True,
        "visible_match_checksums_verified": True,
        "all_selected_year_payloads_verified":
            verify_scope == "selected_years",
        "school_membership_integrity_for_years_verified":
            verify_scope == "selected_years",
        "source_records_not_modified": True,
        "legacy_records_combined": False,
        "school_filter_uses_unindexed_json_scan": True,
        "unsaved_years_not_inferred": True,
        "real_tournament_runtime_connected": False,
    }
