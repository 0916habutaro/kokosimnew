"""Stage43G-22: read-only byte attribution for retained Option-A career data.

Analyze REAL persisted canonical JSON bytes and SQLite pages; never modify
the archived JSON schema or claim hypothetical gzip samples are stored savings.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from statistics import median

FIELDS = ("inning_scores", "team_stats", "batter_stats", "pitcher_stats")
SOURCE = "read_only_persisted_full_option_a_storage_breakdown"


def _canonical_bytes(value: object) -> int:
    return len(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8"))


def _read_only(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"SQLite archive absent: {path}")
    connection = sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True
    )
    connection.execute("PRAGMA query_only=ON")
    return connection


def sqlite_file_profile(path: Path) -> dict:
    """Physical file bytes, page utilization and optional btree breakdown.

    The dbstat virtual table may be omitted from the deployed SQLite build;
    its absence is recorded explicitly instead of failing measurements.
    """
    path = Path(path)
    with closing(_read_only(path)) as conn:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        freelist_count = conn.execute("PRAGMA freelist_count").fetchone()[0]
        try:
            btrees = {
                name: int(used) for name, used in conn.execute(
                    "SELECT name,SUM(pgsize) FROM dbstat GROUP BY name "
                    "ORDER BY name"
                )
            }
            dbstat_available = True
        except sqlite3.OperationalError as exc:
            if "dbstat" not in str(exc).lower():
                raise
            btrees = None
            dbstat_available = False
    return {
        "file_bytes": path.stat().st_size,
        "page_size": int(page_size),
        "page_count": int(page_count),
        "freelist_count": int(freelist_count),
        "allocated_page_bytes": int(page_count * page_size),
        "dbstat_available": dbstat_available,
        "btree_page_bytes": btrees,
        "btree_page_bytes_include_indexes": dbstat_available,
    }


def profile_option_a_storage(
    matches: str | Path, rosters: str | Path, cache: str | Path,
    *, gzip_sample_limit: int = 100,
) -> dict:
    """Attribute each persisted match JSON byte; profile 3 actual DB files.

    `metadata_and_json_syntax` is exact remainder after the four top-level
    Option-A list *values* (their property names and commas remain there).
    This is not the entire SQLite row/index footprint. Gzip is on a bounded
    deterministic per-record SAMPLE and never applied to saved records.
    """
    if (type(gzip_sample_limit) is not int
            or not 0 <= gzip_sample_limit <= 1000):
        raise ValueError("invalid bounded gzip sample size")
    paths = {
        "matches": Path(matches),
        "rosters": Path(rosters),
        "derived_cache": Path(cache),
    }
    # Missing files must never be implicitly created by a profiling query.
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(f"archive file missing: {path}")

    parts = Counter()
    sizes = []
    source_counts = Counter()
    sample_plain_bytes = 0
    sample_gzip_bytes = 0
    sampled_records = 0
    records = 0

    with closing(_read_only(paths["matches"])) as conn:
        for raw, recorded_sha in conn.execute(
            "SELECT payload_json, record_sha256 FROM historical_matches "
            "ORDER BY year,competition_id,match_id"
        ):
            raw_bytes = raw.encode("utf-8")
            if hashlib.sha256(raw_bytes).hexdigest() != recorded_sha:
                raise ValueError("stored full-A match digest mismatch")
            value = json.loads(raw)
            total = len(raw_bytes)
            sizes.append(total)
            records += 1
            parts["persisted_payload_bytes"] += total
            list_bytes = 0
            for field in FIELDS:
                section = value.get(field)
                if section is not None and not isinstance(section, list):
                    raise ValueError("invalid persisted A-detail field")
                length = _canonical_bytes(section)
                parts[field + "_value_bytes"] += length
                list_bytes += length
            if list_bytes > total:
                raise AssertionError("option A byte attribution exceeds payload")
            parts["metadata_and_json_syntax_bytes"] += total - list_bytes
            source_counts[
                "full_a" if all(
                    isinstance(value.get(k), list) and value[k]
                    for k in FIELDS
                ) else "partial_or_score_only"
            ] += 1
            if sampled_records < gzip_sample_limit:
                sample_plain_bytes += total
                sample_gzip_bytes += len(gzip.compress(raw_bytes, mtime=0))
                sampled_records += 1

    if parts["persisted_payload_bytes"] != (
        parts["metadata_and_json_syntax_bytes"]
        + sum(parts[field + "_value_bytes"] for field in FIELDS)
    ):
        raise AssertionError("Option-A payload byte attribution lost bytes")
    files = {
        key: sqlite_file_profile(path)
        for key, path in paths.items()
    }
    return {
        "source_kind": SOURCE,
        "source_verified_record_sha256": True,
        "archived_match_count": records,
        "match_record_shapes": dict(sorted(source_counts.items())),
        "payload_bytes": dict(sorted(parts.items())),
        "payload_min_bytes": min(sizes) if sizes else None,
        "payload_median_bytes": median(sizes) if sizes else None,
        "payload_max_bytes": max(sizes) if sizes else None,
        "gzip_sample": {
            "records_sampled": sampled_records,
            "sample_limit": gzip_sample_limit,
            "sample_uncompressed_payload_bytes": sample_plain_bytes,
            "sample_gzip_encoded_bytes": sample_gzip_bytes,
            "sample_ratio": (
                round(sample_gzip_bytes / sample_plain_bytes, 4)
                if sample_plain_bytes else None
            ),
            "hypothetical_only_not_applied_to_save": True,
            "not_a_projection_of_sqlite_index_savings": True,
        },
        "sqlite_files": files,
        "sqlite_total_bytes": sum(
            info["file_bytes"] for info in files.values()
        ),
        "source_payloads_not_modified": True,
        "all_record_scores_from_synthetic_fixture": True,
        "full_option_a_real_tournament_execution_verified": False,
    }
