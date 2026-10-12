"""Stage43G-86: read-only timing audit for bounded, explicit century shard sets.

This measures an existing sealed fictional-v2 source; it does not generate
players, years, games, indexes, or any other data in this function. A fixture
with 32 saved years spaced 100 years apart is *not* 3200 played years.
"""
from __future__ import annotations

from pathlib import Path
from time import perf_counter

from .career_history_scale_benchmark import file_sha256
from .career_v2_school_century_shards import (
    CENTURY_SPAN, MAX_SHARDS_PER_REQUEST, read_v2_school_century_page,
)

SCENARIOS = (4, 16, 32)


def measure_v2_century_shard_scale(
    v2_path: str | Path, calendar_path: str | Path,
    index_paths: list[str | Path] | tuple[str | Path, ...],
    school_id: str, *, first_year: int = 10000,
    scenarios: tuple[int, ...] = SCENARIOS,
) -> dict:
    """Time page/strict read across N 100-year shards, checking all input SHA.

    Scenarios are prefixes of the explicitly supplied shard list; benchmark
    does not discover, create, approve, or repair shards. Values reflect this
    *particular saved synthetic dataset and execution environment* only.
    """
    if (type(first_year) is not int or first_year < 10000
            or not isinstance(index_paths, (list, tuple))
            or not 1 <= len(index_paths) <= MAX_SHARDS_PER_REQUEST
            or type(school_id) is not str or not school_id
            or not isinstance(scenarios, tuple) or not scenarios
            or any(type(n) is not int or not 1 <= n <= len(index_paths)
                   for n in scenarios)
            or tuple(sorted(set(scenarios))) != scenarios):
        raise ValueError("invalid bounded v2 century shard scale audit")
    source, calendar = Path(v2_path), Path(calendar_path)
    paths = tuple(Path(p) for p in index_paths)
    snapshots = {
        str(p.resolve()): file_sha256(p)
        for p in (source, calendar, *paths)
    }
    if len(snapshots) != len(paths) + 2:
        raise ValueError("source, calendar and indexes must be distinct")
    observations = []
    for count in scenarios:
        target_end = first_year + (count - 1) * CENTURY_SPAN
        example = None
        timings = {}
        for scope in ("page", "selected_years"):
            started = perf_counter()
            data = read_v2_school_century_page(
                source, calendar, paths[:count], school_id,
                start_year=first_year, end_year=target_end,
                limit=30, offset=0, verify_scope=scope,
            )
            elapsed = (perf_counter() - started) * 1000
            timings[scope] = round(elapsed, 3)
            if (data.get("cross_century_school_index_shards") is not True
                    or data.get("shard_count") != count
                    or data.get("source_records_not_modified") is not True
                    or data.get("legacy_records_combined") is not False
                    or data.get("all_selected_year_payloads_verified")
                    is not (scope == "selected_years")):
                raise ValueError("invalid cross-century audit source proof")
            if example is not None:
                if (example["total"] != data["total"]
                        or example["records"] != data["records"]):
                    raise ValueError("page and strict verified source differ")
            example = data
        observations.append({
            "shards": count,
            "start_year": first_year,
            "end_year": target_end,
            "saved_school_matches": example["total"],
            "visible_school_matches": len(example["records"]),
            "page_ms": timings["page"],
            "strict_selected_years_ms": timings["selected_years"],
            "source_full_a_sha_verified": True,
            "all_shard_memberships_strictly_verified": True,
        })
    unchanged = all(
        file_sha256(Path(p)) == sha for p, sha in snapshots.items()
    )
    if not unchanged:
        raise RuntimeError("cross-century scale audit altered a SQLite input")
    return {
        "cases": observations,
        "source_sqlite_and_indexes_unchanged": True,
        "derived_index_not_authoritative": True,
        "fictional_full_option_a_only": True,
        "observed_environment_only_not_performance_guarantee": True,
        "sparse_years_not_continuous_3200_year_simulation": True,
        "max_index_shards_per_read": MAX_SHARDS_PER_REQUEST,
        "long_term_save_year_limit_imposed": False,
        "automatic_index_activation": False,
    }
