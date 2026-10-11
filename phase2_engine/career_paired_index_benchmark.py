"""Stage43G-72: paired, same-data duplicate-index allocation and read probe.

Create disposable copies from an already-saved NEW-schema A/v2 database.
The only experimental difference is an index with columns identical to
the SQLite primary key. Source SQLite stays read-only and byte unchanged.
No claim is made about savings from deleting old indexes in place.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from statistics import median
import tempfile
from time import perf_counter

from .career_history_scale_benchmark import file_sha256
from .career_option_a_storage_profile import _read_only, sqlite_file_profile

_CASES = {
    "v2_matches": {
        "table": "v2_option_a_matches",
        "duplicate": "idx_v2_games_school_a",
        "columns": "year,competition_id,match_id",
        "pk_columns": ["year", "competition_id", "match_id"],
        "source_query": (
            "SELECT year,competition_id,match_id,game_day_token,"
            "calendar_sha256,record_sha256,payload_json "
            "FROM v2_option_a_matches "
            "ORDER BY year,competition_id,match_id"
        ),
        "sample_query": (
            "SELECT year,competition_id,match_id,game_day_token "
            "FROM v2_option_a_matches ORDER BY year,competition_id,match_id LIMIT 1"
        ),
        "read_query": (
            "SELECT payload_json FROM v2_option_a_matches "
            "WHERE year=? AND competition_id=? AND match_id=?"
        ),
        "seek_columns": (0, 1, 2),
        "retained": "idx_v2_games_day",
        "required_columns": ["year", "game_day_token", "competition_id", "match_id"],
    },
    "legacy_cache": {
        "table": "player_year_stat_cache",
        "duplicate": "idx_cached_school_year",
        "columns": "school_id,year,player_id",
        "pk_columns": ["school_id", "year", "player_id"],
        "source_query": (
            "SELECT school_id,year,player_id,payload_json,payload_sha256 "
            "FROM player_year_stat_cache "
            "ORDER BY school_id,year,player_id"
        ),
        "sample_query": (
            "SELECT school_id,year,player_id FROM player_year_stat_cache "
            "ORDER BY school_id,year,player_id LIMIT 1"
        ),
        "read_query": (
            "SELECT payload_json FROM player_year_stat_cache "
            "WHERE school_id=? AND year=? AND player_id=?"
        ),
        "seek_columns": (0, 1, 2),
        "retained": "idx_cached_player_year",
        "required_columns": ["player_id", "year"],
    },
}


class CareerControlledIndexConflict(ValueError):
    """Source database is not the new immutable cache/match index contract."""


def _index_list(conn, table: str) -> list[dict]:
    items = []
    for row in conn.execute(f'PRAGMA index_list("{table}")'):
        name = row[1]
        if not isinstance(name, str) or '"' in name:
            raise CareerControlledIndexConflict("invalid SQLite index identifier")
        cols = [r[2] for r in conn.execute(f'PRAGMA index_info("{name}")')]
        items.append({
            "name": name, "origin": row[3], "unique": bool(row[2]),
            "columns": cols,
        })
    return items


def _check_indexes(conn, kind: str, *, old: bool) -> list[dict]:
    spec = _CASES[kind]
    indexed = _index_list(conn, spec["table"])
    pk = [
        idx for idx in indexed if idx["origin"] == "pk"
        and idx["unique"] and idx["columns"] == spec["pk_columns"]
    ]
    distinct = [
        idx for idx in indexed if idx["name"] == spec["retained"]
        and idx["columns"] == spec["required_columns"]
    ]
    duplicates = [
        idx for idx in indexed if idx["origin"] != "pk"
        and idx["columns"] == spec["pk_columns"]
    ]
    if (len(pk) != 1 or len(distinct) != 1
            or [x["name"] for x in duplicates] != (
                [spec["duplicate"]] if old else []
            )):
        raise CareerControlledIndexConflict(
            f"{kind}: new/old schema query-index comparison failed"
        )
    return indexed


def _row_fingerprint(conn, kind: str) -> tuple[int, str]:
    digest = sha256()
    rows = 0
    for row in conn.execute(_CASES[kind]["source_query"]):
        encoded = json.dumps(
            row, ensure_ascii=False, sort_keys=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        rows += 1
    return rows, digest.hexdigest()


def _probe(path: Path, kind: str, *, old: bool, repeats: int) -> dict:
    spec = _CASES[kind]
    with closing(_read_only(path)) as conn:
        index_list = _check_indexes(conn, kind, old=old)
        count, digest = _row_fingerprint(conn, kind)
        if count == 0:
            raise CareerControlledIndexConflict(
                "controlled index test needs at least one immutable saved row"
            )
        sample = conn.execute(spec["sample_query"]).fetchone()
        keys = tuple(sample[i] for i in spec["seek_columns"])
        plan = [
            str(row[3]) for row in conn.execute(
                "EXPLAIN QUERY PLAN " + spec["read_query"], keys,
            )
        ]
        if not any(
            "SEARCH " + spec["table"] in line
            and "USING INDEX" in line or
            "SEARCH " + spec["table"] in line
            and "USING COVERING INDEX" in line
            for line in plan
        ):
            raise CareerControlledIndexConflict(
                "primary-key lookup unexpectedly did not use an index"
            )
        latencies = []
        for _ in range(repeats):
            start = perf_counter()
            result = conn.execute(spec["read_query"], keys).fetchone()
            latencies.append(round((perf_counter() - start) * 1000, 4))
            if result is None or not isinstance(result[0], str):
                raise CareerControlledIndexConflict("saved player/match payload absent")
    physical = sqlite_file_profile(path)
    per_tree = physical["btree_page_bytes"]
    return {
        "stored_rows": count,
        "ordered_full_row_sha256": digest,
        "file_bytes": physical["file_bytes"],
        "page_count": physical["page_count"],
        "page_size": physical["page_size"],
        "dbstat_available": physical["dbstat_available"],
        "all_indexes": index_list,
        "explicit_pk_duplicate_present": old,
        "duplicate_index_allocated_bytes": (
            per_tree.get(spec["duplicate"], 0)
            if per_tree is not None else None
        ),
        "indexed_exact_row_query_plan": plan,
        "repeated_exact_row_lookup_ms": latencies,
        "median_exact_row_lookup_ms": median(latencies),
    }


def compare_duplicate_index_build(
    saved_db: str | Path, *, kind: str, repeats: int = 5,
) -> dict:
    """Read original only; generate 2 temporary SQLite backups for comparison."""
    if kind not in _CASES:
        raise ValueError("kind must be v2_matches or legacy_cache")
    if type(repeats) is not int or not 1 <= repeats <= 25:
        raise ValueError("repeats must be between 1 and 25")
    path = Path(saved_db)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("existing, non-symlinked new-schema source required")
    source_before = file_sha256(path)
    # Read from a real saved source; never create a DB at the source path.
    with closing(_read_only(path)) as input_conn:
        _check_indexes(input_conn, kind, old=False)
        if input_conn.execute(
            "SELECT COUNT(*) FROM " + _CASES[kind]["table"]
        ).fetchone()[0] < 1:
            raise CareerControlledIndexConflict("new schema has no sample rows")
        with tempfile.TemporaryDirectory(prefix="kokosim-index-paired-") as d:
            folder = Path(d)
            new_path = folder / "new.sqlite3"
            old_path = folder / "old.sqlite3"
            for target in (new_path, old_path):
                with closing(sqlite3.connect(target)) as copy:
                    input_conn.backup(copy)
            spec = _CASES[kind]
            with closing(sqlite3.connect(old_path)) as old_conn:
                old_conn.execute(
                    f"CREATE INDEX {spec['duplicate']} "
                    f"ON {spec['table']}({spec['columns']})"
                )
                old_conn.commit()
            newer = _probe(new_path, kind, old=False, repeats=repeats)
            older = _probe(old_path, kind, old=True, repeats=repeats)
            if (newer["stored_rows"] != older["stored_rows"]
                    or newer["ordered_full_row_sha256"] !=
                    older["ordered_full_row_sha256"]):
                raise CareerControlledIndexConflict(
                    "paired SQLite databases no longer contain identical records"
                )
            if newer["file_bytes"] > older["file_bytes"]:
                raise CareerControlledIndexConflict(
                    "adding the old redundant index reduced DB file size"
                )
            report = {
                "stage": "43G-72",
                "kind": kind,
                "experiment": "same_saved_row_payload_paired_temporary_sqlite_backup",
                "new_schema": newer, "previous_schema": older,
                "observed_extra_file_bytes_in_old_index_copy":
                    older["file_bytes"] - newer["file_bytes"],
                "observed_old_duplicate_btree_allocated_bytes":
                    older["duplicate_index_allocated_bytes"],
                "identical_record_rows_and_full_content_sha": True,
                "exact_row_indexed_lookup_preserved": True,
                "median_read_latency_comparison_is_observational_only": True,
                "repeat_count": repeats,
                "source_sqlite_sha_unchanged": True,
                "temporary_sqlite_files_removed": True,
                "in_place_existing_save_savings_not_established": True,
                "nationwide_50_100_year_runtime_not_simulated": True,
                "original_option_a_payload_format_unchanged": True,
            }
    if source_before != file_sha256(path):
        raise AssertionError("index comparison mutated original saved SQLite")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Paired same-record SQLite B-tree index control test"
    )
    parser.add_argument("--kind", choices=sorted(_CASES), required=True)
    parser.add_argument("--saved-db", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    if (args.output_json is not None
            and args.output_json.resolve() == args.saved_db.resolve()):
        parser.error("output must not overwrite original SQLite source")
    report = compare_duplicate_index_build(
        args.saved_db, kind=args.kind, repeats=args.repeats,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
