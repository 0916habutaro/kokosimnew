"""Stage43G-70: read-only measured B-tree/storage attribution for A archives.

Does not rebuild indexes, VACUUM, drop objects, rewrite saved box scores,
or create caches. Index DDL for NEW v2 files is separately defined in
career_v2_option_a_archive.py. Existing v2 files retain their old indexes.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .career_history_scale_benchmark import file_sha256
from .career_option_a_storage_profile import (
    _read_only, sqlite_file_profile,
)

V2_PK_COLUMNS = ["year", "competition_id", "match_id"]
V2_DAY_COLUMNS = ["year", "game_day_token", "competition_id", "match_id"]
KNOWN_FILES = (
    ("legacy_matches", "historical_matches.sqlite3", "legacy_source"),
    ("v2_matches", "fictional_option_a_v2.sqlite3", "v2_source"),
    ("v2_calendar", "sandbox_calendar_v2.sqlite3", "v2_calendar"),
    ("shared_rosters", "career_rosters.sqlite3", "rosters_shared"),
    ("legacy_derived_cache", "derived_player_stats.sqlite3", "legacy_cache"),
    ("v2_derived_cache", "fictional_v2_player_stat_cache.sqlite3", "v2_cache"),
)


class CareerStorageBtreeConflict(ValueError):
    """Missing or malformed saved B-tree/index/query contract."""


def _index_columns(conn: sqlite3.Connection, name: str) -> list[str]:
    # The name comes exclusively from SQLite PRAGMA index_list output, never
    # user text. Validate before interpolating into the PRAGMA statement.
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in name):
        raise CareerStorageBtreeConflict("unrecognized SQLite index identifier")
    return [row[2] for row in conn.execute(f"PRAGMA index_info('{name}')")]


def _plan(conn: sqlite3.Connection, query: str, params: tuple) -> list[str]:
    return [str(row[3]) for row in conn.execute(
        "EXPLAIN QUERY PLAN " + query, params,
    )]


def _v2_indexes(conn: sqlite3.Connection) -> dict:
    listed = conn.execute(
        "PRAGMA index_list('v2_option_a_matches')"
    ).fetchall()
    idx = [{
        "name": row[1],
        "unique": bool(row[2]),
        "origin": row[3],
        "columns": _index_columns(conn, row[1]),
    } for row in listed]
    natural_pk = [
        row for row in idx
        if row["origin"] == "pk"
        and row["unique"] and row["columns"] == V2_PK_COLUMNS
    ]
    dated = [
        row for row in idx
        if row["name"] == "idx_v2_games_day"
        and row["columns"] == V2_DAY_COLUMNS
    ]
    if len(natural_pk) != 1 or len(dated) != 1:
        raise CareerStorageBtreeConflict(
            "v2 permanent primary-key and calendar indexes required"
        )
    duplicates = [
        row["name"] for row in idx
        if row["origin"] != "pk" and row["columns"] == V2_PK_COLUMNS
    ]
    exact = _plan(
        conn, "SELECT match_id FROM v2_option_a_matches "
        "WHERE year=? AND competition_id=? AND match_id=?",
        (10000, "TEST-COMP", "TEST-MATCH"),
    )
    dated_plan = _plan(
        conn, "SELECT match_id FROM v2_option_a_matches "
        "WHERE year=? AND game_day_token=? "
        "ORDER BY competition_id,match_id LIMIT 24",
        (10000, "G10000:04-01"),
    )
    if not any("SEARCH v2_option_a_matches" in item for item in exact):
        raise CareerStorageBtreeConflict(
            "v2 exact match ID query unexpectedly scans full table"
        )
    if not any(
        "SEARCH v2_option_a_matches" in item
        and "idx_v2_games_day" in item
        for item in dated_plan
    ):
        raise CareerStorageBtreeConflict(
            "v2 calendar day seek index not selected"
        )
    return {
        "indices": idx,
        "primary_key_columns": V2_PK_COLUMNS,
        "v2_pk_autoindex_verified": True,
        "required_day_lookup_index_verified": True,
        "redundant_exact_pk_index_names": sorted(duplicates),
        "legacy_explicit_duplicate_index_present": bool(duplicates),
        "exact_match_id_seek_plan": exact,
        "game_day_seek_plan": dated_plan,
    }


def audit_save_storage_btrees(slot_root: str | Path) -> dict:
    """Profile *existing* saved files and confirm source remains unchanged.

    Requires a v2 match archive, while additional files are optional.
    Does not assert that a saved source ledger is valid; run Stage43G-68
    separately for full match/roster/cache SHA and attribution verification.
    """
    root = Path(slot_root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("existing save slot directory required")
    files = {}
    for key, name, kind in KNOWN_FILES:
        path = root / name
        if path.is_symlink():
            raise CareerStorageBtreeConflict("symlinked save file disallowed")
        if path.is_file():
            files[key] = (path, kind)
    if "v2_matches" not in files:
        raise FileNotFoundError("fictional v2 match archive required")
    if len({p.resolve() for p, kind in files.values()}) != len(files):
        raise CareerStorageBtreeConflict("saved SQLite files cannot alias")
    before = {key: file_sha256(path)
              for key, (path, kind) in files.items()}
    records = {}
    index_contract = None
    for key, (path, kind) in files.items():
        profile = sqlite_file_profile(path)
        with closing(_read_only(path)) as conn:
            if key == "v2_matches":
                index_contract = _v2_indexes(conn)
            # Source of truth for ownership: SQLite index_list. This
            # includes automatic primary-key B-trees absent from sqlite_master.
            auto_and_explicit = {}
            for (table,) in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ):
                for entry in conn.execute(
                    f'PRAGMA index_list("{table}")'
                ):
                    auto_and_explicit[entry[1]] = {
                        "table": table, "origin": entry[3],
                        "columns": _index_columns(conn, entry[1]),
                    }
        by_tree = profile["btree_page_bytes"]
        rows = {
            "file_role": kind,
            "file_bytes": profile["file_bytes"],
            "page_count": profile["page_count"],
            "page_size": profile["page_size"],
            "free_page_count": profile["freelist_count"],
            "dbstat_available": profile["dbstat_available"],
            "btree_index_bytes": (
                sum(by_tree.get(name, 0) for name in auto_and_explicit)
                if by_tree is not None else None
            ),
            "btree_table_bytes": (
                sum(size for name, size in by_tree.items()
                    if name not in auto_and_explicit)
                if by_tree is not None else None
            ),
            "indexes": auto_and_explicit,
            "index_btree_sizes": (
                {name: by_tree.get(name, 0)
                 for name in sorted(auto_and_explicit)}
                if by_tree is not None else None
            ),
            "file_bytes_are_not_only_record_json_bytes": True,
        }
        if (rows["btree_index_bytes"] is not None
                and rows["btree_index_bytes"]
                + rows["btree_table_bytes"]
                > profile["allocated_page_bytes"]):
            raise CareerStorageBtreeConflict(
                "SQLite dbstat B-tree bytes exceed allocated page capacity"
            )
        records[key] = rows
    after = {key: file_sha256(path)
             for key, (path, kind) in files.items()}
    if before != after:
        raise AssertionError("B-tree investigation modified saved SQLite")
    duplicates = index_contract["redundant_exact_pk_index_names"]
    measured_legacy_duplicate_bytes = records[
        "v2_matches"
    ]["index_btree_sizes"]
    return {
        "stage": "43G-70",
        "audit_kind": "read_only_saved_btree_allocations_and_query_plans",
        "files": records,
        "file_bytes_total": sum(r["file_bytes"] for r in records.values()),
        "v2_match_lookup": index_contract,
        "v2_obsolete_duplicate_exact_pk_index_bytes": (
            sum(measured_legacy_duplicate_bytes.get(name, 0)
                for name in duplicates)
            if measured_legacy_duplicate_bytes is not None else None
        ),
        "redundant_pk_index_allocation_avoided_for_new_v2_archives": True,
        "existing_sealed_v2_archives_migrated_or_modified": False,
        "removing_existing_index_savings_measured": False,
        "file_size_reduction_guaranteed": False,
        "btree_index_page_allocation_is_not_entire_index_overhead": True,
        "not_verified_by_this_function": [
            "source_payload_sha", "sealed_match_ledger",
            "roster_identity_attribution", "derived_player_cache_facts",
            "yearly_full_save_growth", "nationwide_gameplay_progress",
        ],
        "all_existing_files_sha256_unchanged": True,
        "read_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage43G-70 read-only index B-tree and storage hotspot audit"
    )
    parser.add_argument("--slot", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    report = audit_save_storage_btrees(args.slot)
    raw = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output_json is not None:
        if args.output_json.resolve() in {
            p.resolve() for p, _, _ in (
                (args.slot / name, key, kind)
                for key, name, kind in KNOWN_FILES
            )
        }:
            parser.error("output path cannot overwrite saved SQLite files")
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(raw, encoding="utf-8")
    print(raw, end="")


if __name__ == "__main__":
    main()
