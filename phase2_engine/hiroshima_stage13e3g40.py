"""Stage13E-3G-40: integration audit of exact year+school SQLite handoff."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile

from .hiroshima_stage13e3g39_school_master import (
    audit_2026_hiroshima_stage13e3g39,
    load_2026_hiroshima_west_school_links_stage39,
)
from .hiroshima_stage13e3g40_school_browse_handoff import (
    preflight_2026_west_school_browse_handoff,
    TARGET_YEAR, TARGET_PREFECTURE,
)


def audit_2026_hiroshima_stage13e3g40(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    predecessor = audit_2026_hiroshima_stage13e3g39(root)
    errors = []
    if not predecessor["ok"]:
        errors.append("Stage39 18-school master ID proof was not valid")
    mapping = load_2026_hiroshima_west_school_links_stage39(root).links
    verified = [link for link in mapping.values() if link.authorized_for_read_only_detail]
    if len(mapping) != 18 or len(verified) != 18:
        errors.append("not all 18 Stage39 school identities are proven")
    outcomes = {}
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / "scored_browse.sqlite3"
        # Minimal materialized scored browse schools solely for verifying the
        # bridge. This is a synthetic fixture, not the user's actual DB.
        with sqlite3.connect(db) as conn:
            conn.execute(
                "CREATE TABLE school_records("
                "year INTEGER NOT NULL, school_id TEXT NOT NULL,"
                "prefecture_code TEXT NOT NULL)"
            )
            conn.executemany(
                "INSERT INTO school_records(year,school_id,prefecture_code) VALUES(?,?,?)",
                [(2026, item.school_id, "34") for item in verified],
            )
        for link in verified:
            result = preflight_2026_west_school_browse_handoff(
                db, link, selected_browse_year=TARGET_YEAR,
            )
            if not result.allowed or result.school_id != link.school_id:
                errors.append(f"verified identity could not be navigated: {link.observed_name}")
        sample = verified[0]
        wrong_year = preflight_2026_west_school_browse_handoff(
            db,sample,selected_browse_year=2025,
        )
        if wrong_year.allowed:
            errors.append("different browse year must not auto-switch")
        with sqlite3.connect(db) as conn:
            conn.execute("DELETE FROM school_records WHERE school_id=?", (sample.school_id,))
        missing_row = preflight_2026_west_school_browse_handoff(
            db,sample,selected_browse_year=2026,
        )
        if missing_row.allowed:
            errors.append("absent SQLite scored season school must not navigate")
        absent_db=Path(temp)/"missing.sqlite3"
        no_db = preflight_2026_west_school_browse_handoff(
            absent_db,sample,selected_browse_year=2026,
        )
        if no_db.allowed or absent_db.exists():
            errors.append("handoff attempted to create a missing SQLite database")
        outcomes = {
            "verified_preview_schools":len(verified),
            "exact_2026_school_id_passing_synthetic_sqlite_probe":len(verified),
            "wrong_year_refused":not wrong_year.allowed,
            "missing_school_record_refused":not missing_row.allowed,
            "missing_db_not_created":not absent_db.exists(),
        }
    return {
        "ok":not errors,"errors":errors,
        "handoff":outcomes,
        "2026_historical_qualifier_results_inserted":False,
        "existing_browse_sqlite_modified":False,
        "native_tk_window_visual_checked":False,
        "original_master_changed":False,
        "2026_official_numbered_match_arrows_verified":0,
        "2026_official_8_group_routes_unresolved":48,
        "production_fmt025_runtime_enabled":False,
        "optional_ranking_enabled":False,
    }
