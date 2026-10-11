"""Stage43G-71: read-only SQLite B-tree index allocation for A stats caches.

The two independently persisted cache formats have different schemas:
 legacy: player_year_stat_cache
 v2:     v2_player_year_stat_cache
Only the legacy explicit school-year index exactly duplicates its primary
key. This module NEVER modifies existing caches and NEVER asserts that
the measured index page size equals disk space saved by deleting it.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .career_history_scale_benchmark import file_sha256
from .career_option_a_storage_profile import _read_only, sqlite_file_profile

_CONTRACTS = {
    "legacy": {
        "table": "player_year_stat_cache",
        "pk": ["school_id", "year", "player_id"],
        "player": "idx_cached_player_year",
        "legacy_duplicate": "idx_cached_school_year",
    },
    "v2": {
        "table": "v2_player_year_stat_cache",
        "pk": ["school_id", "year", "player_id"],
        "player": "idx_v2_stat_player_year",
        "legacy_duplicate": None,
    },
}


class CareerStatsCacheBtreeConflict(ValueError):
    """Expected immutable cache index/seek structure was not found."""


def _indices(conn: sqlite3.Connection, table: str) -> list[dict]:
    # Table identifier comes from the constant _CONTRACTS, index names come
    # only from SQLite metadata. Index-info PRAGMA uses safely quoted names.
    results = []
    for row in conn.execute(f'PRAGMA index_list("{table}")'):
        name = row[1]
        if not isinstance(name, str) or '"' in name:
            raise CareerStatsCacheBtreeConflict("malformed SQLite index name")
        cols = [r[2] for r in conn.execute(
            f'PRAGMA index_info("{name}")'
        )]
        results.append({
            "name": name, "columns": cols,
            "unique": bool(row[2]), "origin": row[3],
        })
    return results


def _query_plan(conn: sqlite3.Connection, kind: str) -> dict:
    table = _CONTRACTS[kind]["table"]
    queries = {
        "school_year": (
            f"SELECT player_id FROM {table} WHERE school_id=? "
            "AND year BETWEEN ? AND ? ORDER BY year,player_id LIMIT 20",
            ("BENCH-SCHOOL", 2026, 2126),
        ),
        "player_year": (
            f"SELECT payload_json FROM {table} WHERE player_id=? "
            "AND year BETWEEN ? AND ? ORDER BY year LIMIT 20",
            ("BENCH-PLAYER", 2026, 2126),
        ),
    }
    return {
        name: [
            str(row[3]) for row in conn.execute(
                "EXPLAIN QUERY PLAN " + sql, params,
            )
        ]
        for name, (sql, params) in queries.items()
    }


def audit_saved_stats_cache_indexes(
    *, legacy_cache: str | Path | None = None,
    v2_cache: str | Path | None = None,
) -> dict:
    """Measure one or both ALREADY EXISTING cache DBs, read-only.

    No source match/roster provenance is proved here. For full record
    correctness, run Stage43G-67/68 source+cache validation separately.
    """
    chosen = {}
    for kind, requested in (("legacy", legacy_cache), ("v2", v2_cache)):
        if requested is None:
            continue
        path = Path(requested)
        if path.is_symlink():
            raise CareerStatsCacheBtreeConflict(
                "symlinked cache file not allowed"
            )
        if not path.is_file():
            raise FileNotFoundError(f"{kind} saved cache file missing: {path}")
        chosen[kind] = path
    if not chosen:
        raise ValueError("specify at least one existing stats cache")
    if len({p.resolve() for p in chosen.values()}) != len(chosen):
        raise CareerStatsCacheBtreeConflict(
            "legacy and v2 cache files may not alias"
        )
    before = {k: file_sha256(p) for k, p in chosen.items()}
    results = {}
    for kind, path in chosen.items():
        profile = sqlite_file_profile(path)
        spec = _CONTRACTS[kind]
        with closing(_read_only(path)) as conn:
            indexes = _indices(conn, spec["table"])
            expected = [
                row for row in indexes if (
                    row["origin"] == "pk" and row["unique"] and
                    row["columns"] == spec["pk"]
                )
            ]
            player = [
                row for row in indexes if (
                    row["name"] == spec["player"] and
                    row["columns"] == ["player_id", "year"]
                )
            ]
            if len(expected) != 1 or len(player) != 1:
                raise CareerStatsCacheBtreeConflict(
                    f"{kind} PK or player-first index missing"
                )
            exact_duplicates = sorted(
                row["name"] for row in indexes
                if row["origin"] != "pk" and row["columns"] == spec["pk"]
            )
            plans = _query_plan(conn, kind)
            school_steps = plans["school_year"]
            player_steps = plans["player_year"]
            if (not any(
                "SEARCH " + spec["table"] in step and (
                    expected[0]["name"] in step
                    or any(name in step for name in exact_duplicates)
                ) for step in school_steps
            ) or not any(
                "SEARCH " + spec["table"] in step and
                spec["player"] in step for step in player_steps
            )):
                raise CareerStatsCacheBtreeConflict(
                    f"{kind} indexed school/player seek query not selected"
                )
            count = conn.execute(
                f"SELECT COUNT(*) FROM {spec['table']}"
            ).fetchone()[0]
        by_tree = profile["btree_page_bytes"]
        duplicate_bytes = (
            sum(by_tree.get(name, 0) for name in exact_duplicates)
            if by_tree is not None else None
        )
        indexes_by_name = {r["name"]: r for r in indexes}
        results[kind] = {
            "file_bytes": profile["file_bytes"],
            "page_count": profile["page_count"],
            "page_size": profile["page_size"],
            "freelist_count": profile["freelist_count"],
            "saved_player_year_rows": count,
            "all_indexes": indexes,
            "primary_key_autoindex": expected[0]["name"],
            "distinct_player_first_index": spec["player"],
            "exact_primary_key_duplicate_indexes": exact_duplicates,
            "old_duplicate_index_present": bool(exact_duplicates),
            "dbstat_available": profile["dbstat_available"],
            "index_btree_bytes": (
                {name: by_tree.get(name, 0)
                 for name in sorted(indexes_by_name)}
                if by_tree is not None else None
            ),
            "old_duplicate_index_allocated_bytes": duplicate_bytes,
            "school_year_seek_plan": school_steps,
            "player_year_seek_plan": player_steps,
            "both_query_plans_use_indexes": True,
            "source_match_and_roster_contents_verified_here": False,
        }
    after = {k: file_sha256(p) for k, p in chosen.items()}
    if before != after:
        raise AssertionError("index inspection altered saved stats cache")
    return {
        "stage": "43G-71",
        "audit_kind": "existing_legacy_and_v2_stats_cache_indexes_only",
        "files": results,
        "observed_cache_file_bytes": sum(
            row["file_bytes"] for row in results.values()
        ),
        "legacy_pk_duplicate_omitted_for_new_cache": True,
        "v2_player_first_index_remains_distinct_and_necessary": True,
        "existing_saved_cache_indexes_dropped": False,
        "cache_json_payload_or_player_stats_modified": False,
        "existing_cache_shas_unchanged": True,
        "full_cache_source_integrity_audited_here": False,
        "old_index_page_size_is_not_guaranteed_disk_saving": True,
        "national_3000_school_100_year_gameplay_verified": False,
        "read_only": True,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Inspect existing A/v2 stats cache PK and distinct player "
                    "seek indexes read-only; never drop indexes"
    )
    p.add_argument("--legacy-cache", type=Path)
    p.add_argument("--v2-cache", type=Path)
    p.add_argument("--output-json", type=Path)
    args = p.parse_args()
    if args.output_json is not None and args.output_json.resolve() in {
        x.resolve() for x in (args.legacy_cache, args.v2_cache)
        if x is not None
    }:
        p.error("output cannot overwrite an existing saved stats cache")
    result = audit_saved_stats_cache_indexes(
        legacy_cache=args.legacy_cache, v2_cache=args.v2_cache,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
