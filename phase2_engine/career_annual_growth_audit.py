"""Stage43G-23: immutable, read-only per-year growth and SQLite query-plan audit.

Logical payload bytes are exact stored UTF-8 values; they are NOT SQLite
file-page deltas. Physical growth is measured separately during synthetic
append-only generation. No user slot is opened for writing by this module.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from hashlib import sha256
from pathlib import Path

from .career_option_a_storage_profile import _read_only

_COMPONENTS = (
    "match_payload", "school_roster_payload",
    "new_player_identity_payload", "derived_player_year_payload",
)


def _size_and_check(raw: str, expected_sha: str, label: str) -> int:
    payload = raw.encode("utf-8")
    if sha256(payload).hexdigest() != expected_sha:
        raise ValueError(f"historical yearly growth {label} checksum differs")
    return len(payload)


def profile_annual_growth(matches: str | Path, rosters: str | Path,
                          cache: str | Path) -> dict:
    """Measure exact retained JSON values per year and coverage of sealed cache.

    Every recorded JSON digest is checked, as is sealed-year cache ledger
    provenance. This does *not* prove source match ledger recomputation or
    school-year cache fact digest; those remain separate audits.
    """
    paths = {
        "matches": Path(matches), "rosters": Path(rosters),
        "derived_cache": Path(cache),
    }
    by_year = defaultdict(lambda: {
        "logical_bytes": {part: 0 for part in _COMPONENTS},
        "record_counts": {
            "matches": 0, "school_rosters": 0, "new_player_identities": 0,
            "derived_player_years": 0, "cache_school_year_facts": 0,
        },
    })
    with closing(_read_only(paths["matches"])) as con:
        years = {}
        for year, status, count, ledger in con.execute(
            "SELECT year,status,match_count,ledger_sha256 "
            "FROM career_years ORDER BY year"
        ):
            if year in years:
                raise ValueError("duplicate year in sealed ledger")
            years[year] = (status, count, ledger)
            by_year[year]
        for year, raw, digest in con.execute(
            "SELECT year,payload_json,record_sha256 "
            "FROM historical_matches ORDER BY year,competition_id,match_id"
        ):
            by_year[year]["logical_bytes"]["match_payload"] += (
                _size_and_check(raw, digest, "match")
            )
            by_year[year]["record_counts"]["matches"] += 1
    with closing(_read_only(paths["rosters"])) as con:
        for year, raw, digest in con.execute(
            "SELECT year,payload_json,content_sha256 "
            "FROM career_school_rosters ORDER BY year,school_id"
        ):
            by_year[year]["logical_bytes"]["school_roster_payload"] += (
                _size_and_check(raw, digest, "roster")
            )
            by_year[year]["record_counts"]["school_rosters"] += 1
        for year, raw, digest in con.execute(
            "SELECT entry_year,identity_json,identity_sha256 "
            "FROM career_player_identities ORDER BY entry_year,player_id"
        ):
            by_year[year]["logical_bytes"]["new_player_identity_payload"] += (
                _size_and_check(raw, digest, "player identity")
            )
            by_year[year]["record_counts"]["new_player_identities"] += 1
    with closing(_read_only(paths["derived_cache"])) as con:
        for year, raw, digest in con.execute(
            "SELECT year,payload_json,payload_sha256 "
            "FROM player_year_stat_cache ORDER BY year,school_id,player_id"
        ):
            by_year[year]["logical_bytes"]["derived_player_year_payload"] += (
                _size_and_check(raw, digest, "derived stats")
            )
            by_year[year]["record_counts"]["derived_player_years"] += 1
        for school_id, year, source_digest, count in con.execute(
            "SELECT school_id,year,source_ledger_sha256,source_match_count "
            "FROM school_year_stat_cache ORDER BY year,school_id"
        ):
            stored = years.get(year)
            if (stored is None or stored[0] != "sealed"
                    or source_digest != stored[2]
                    or count != stored[1]):
                raise ValueError(
                    f"school-year cache source ledger mismatch: {school_id}/{year}"
                )
            by_year[year]["record_counts"]["cache_school_year_facts"] += 1

    ordered = sorted(by_year)
    running = {component: 0 for component in _COMPONENTS}
    rows = []
    previous = None
    for year in ordered:
        if previous is not None and year != previous + 1:
            # Missing registered years are an integrity warning, not proof of
            # correct multi-year progression. A game may predate modern save.
            raise ValueError("annual growth audit found a missing career year")
        if year not in years:
            raise ValueError("a stored record has no registered career year")
        status, expected, _digest = years[year]
        if status != "sealed":
            raise ValueError("growth benchmark requires sealed source years")
        row = by_year[year]
        if expected != row["record_counts"]["matches"]:
            raise ValueError("sealed annual match count changed")
        annual_bytes = sum(row["logical_bytes"].values())
        for key in _COMPONENTS:
            running[key] += row["logical_bytes"][key]
        rows.append({
            "year": year,
            "source_year_status": status,
            "logical_payload_bytes": dict(row["logical_bytes"]),
            "annual_logical_payload_total_bytes": annual_bytes,
            "cumulative_logical_payload_bytes": dict(running),
            "cumulative_logical_payload_total_bytes": sum(running.values()),
            "record_counts": dict(row["record_counts"]),
        })
        previous = year

    totals = {key: running[key] for key in _COMPONENTS}
    return {
        "source_kind": "archived_a_plus_rosters_plus_disposable_cache",
        "first_year": ordered[0] if ordered else None,
        "last_year": ordered[-1] if ordered else None,
        "sealed_year_count": len(rows),
        "rows": rows,
        "final_logical_payload_bytes": totals,
        "final_logical_payload_total_bytes": sum(totals.values()),
        "logical_bytes_are_not_sqlite_physical_file_deltas": True,
        "record_sha256_checked": True,
        "school_year_cache_ledger_metadata_checked": True,
        "source_match_ledger_fully_recomputed": False,
        "school_year_cache_fact_sha_fully_recomputed": False,
        "all_databases_opened_read_only": True,
    }


def physical_year_snapshot(year: int, files: dict[str, Path],
                           previous: dict | None = None) -> dict:
    """Capture files' exact allocated bytes *after* each annual transaction.

    SQLite page reuse may make deltas zero/negative; snapshots are evidence,
    not a guarantee that historical data grows linearly or monotonically.
    """
    if type(year) is not int or year < 1:
        raise ValueError("invalid snapshot year")
    names = ("matches", "rosters", "derived_cache")
    if set(files) != set(names):
        raise ValueError("incorrect SQLite snapshot components")
    current = {}
    for name in names:
        path = Path(files[name])
        if not path.is_file():
            raise FileNotFoundError(f"missing benchmark file: {path}")
        current[name] = path.stat().st_size
    if previous is not None:
        if year != previous["year"] + 1:
            raise ValueError("physical snapshots require adjacent years")
        before = previous["allocated_file_bytes"]
    else:
        before = {name: 0 for name in names}
    changes = {name: current[name] - before[name] for name in names}
    return {
        "year": year,
        "allocated_file_bytes": current,
        "allocated_delta_bytes_since_previous_snapshot": changes,
        "allocated_total_file_bytes": sum(current.values()),
        "allocated_total_delta_bytes": sum(changes.values()),
        "file_size_is_not_a_per_year_record_size": True,
    }


def school_query_plan_audit(matches: str | Path, rosters: str | Path,
                            cache: str | Path, school_id: str,
                            player_id: str, start_year: int,
                            end_year: int) -> dict:
    """Read production's school-first match/identity/cached-player plan shape.

    A query planner's *chosen* index matters more than mere CREATE INDEX
    presence. Test fixture conditions can differ from 3000-school deployments.
    """
    if (not isinstance(school_id, str) or not school_id
            or not isinstance(player_id, str) or not player_id
            or type(start_year) is not int or type(end_year) is not int
            or start_year < 1 or end_year < start_year):
        raise ValueError("invalid index plan target")
    targets = (
        (
            "home_matches", Path(matches),
            "SELECT match_id FROM historical_matches "
            "WHERE team1_id=? AND year BETWEEN ? AND ?",
            (school_id, start_year, end_year), "idx_history_school1_year",
        ),
        (
            "away_matches", Path(matches),
            "SELECT match_id FROM historical_matches "
            "WHERE team2_id=? AND year BETWEEN ? AND ?",
            (school_id, start_year, end_year), "idx_history_school2_year",
        ),
        (
            "school_alumni", Path(rosters),
            "SELECT player_id FROM career_player_identities "
            "WHERE school_id=? ORDER BY entry_year,player_id LIMIT ? OFFSET ?",
            (school_id, 20, 0), "idx_career_players_school_entry",
        ),
        (
            "cached_player", Path(cache),
            "SELECT payload_json FROM player_year_stat_cache "
            "WHERE player_id=? AND year BETWEEN ? AND ? ORDER BY year",
            (player_id, start_year, end_year), "idx_cached_player_year",
        ),
    )
    plans = {}
    for label, path, query, args, expected in targets:
        with closing(_read_only(path)) as con:
            steps = [str(rec[3]) for rec in con.execute(
                "EXPLAIN QUERY PLAN " + query, args
            )]
        plans[label] = {
            "plan_steps": steps,
            "expected_index": expected,
            "index_selected": any(expected in step for step in steps),
        }
    return {
        "plans": plans,
        "all_expected_indexes_selected": all(
            plan["index_selected"] for plan in plans.values()
        ),
        "planner_inspected_read_only": True,
        "representative_fixture_not_nationwide_plan_guarantee": True,
    }
