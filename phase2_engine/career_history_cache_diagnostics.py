"""Stage43G-19: read-only per-school/year A-history cache diagnostics.

This is diagnostics, not cache repair or an archive-integrity certification.
Sealed-ledger metadata and derived SHA checks do NOT verify every source game.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from statistics import median
from time import perf_counter
import tracemalloc

from .career_history_browse_model import CareerHistoryBrowseModel, SOURCE
from .career_stats_readonly_adapter import _read_only
from .career_player_stat_cache import CareerStatsCacheConflict


class CareerHistoryCacheDiagnostics:
    """Inspect a bounded school/year window without creating any databases."""

    def __init__(self, model: CareerHistoryBrowseModel):
        self.model = model

    def report(self, school_id: str, *, start_year: int, end_year: int,
               check_cached_rows: bool = True) -> dict:
        if (type(start_year) is not int or type(end_year) is not int
                or start_year < 1 or end_year < start_year
                or end_year - start_year >= 500
                or type(check_cached_rows) is not bool):
            raise ValueError("invalid cache diagnostic range")
        self.model._school(school_id)
        archive = self.model.history.db_path
        cache_path = self.model.stats_cache.path

        # An absent archive is a missing source, not a cue to initialize it.
        sources = {}
        if archive.is_file():
            try:
                with closing(_read_only(archive)) as conn:
                    sources = {
                        row["year"]: dict(row) for row in conn.execute(
                            "SELECT year,status,ledger_sha256,match_count "
                            "FROM career_years WHERE year BETWEEN ? AND ?",
                            (start_year, end_year),
                        )
                    }
            except sqlite3.DatabaseError as exc:
                raise ValueError("source year ledger unreadable") from exc

        cache_state = "missing"
        cached = {}
        orphan_counts = {}
        if cache_path.is_file():
            try:
                with closing(_read_only(cache_path)) as conn:
                    cached = {
                        row["year"]: dict(row) for row in conn.execute(
                            "SELECT year,source_ledger_sha256,source_match_count,"
                            "player_count,school_missing_box_score_games "
                            "FROM school_year_stat_cache WHERE school_id=? "
                            "AND year BETWEEN ? AND ?",
                            (school_id, start_year, end_year),
                        )
                    }
                    orphan_counts = {
                        row["year"]: row["n"] for row in conn.execute(
                            "SELECT year,COUNT(*) AS n FROM "
                            "player_year_stat_cache WHERE school_id=? "
                            "AND year BETWEEN ? AND ? GROUP BY year",
                            (school_id, start_year, end_year),
                        )
                    }
                cache_state = "readable"
            except sqlite3.DatabaseError:
                cache_state = "unreadable"

        rows = []
        for year in range(start_year, end_year + 1):
            source, record = sources.get(year), cached.get(year)
            info = {
                "year": year,
                "source_status": source["status"] if source else "missing",
                "cache_status": "",
                "cached_player_count": record["player_count"] if record else None,
                "missing_box_score_games": (
                    record["school_missing_box_score_games"] if record else None
                ),
            }
            if cache_state == "unreadable":
                state = "cache_unreadable"
            elif record is None and orphan_counts.get(year, 0):
                state = "orphan_cache_rows"
            elif record is not None and source is None:
                state = "cache_without_source"
            elif source is None:
                state = "source_missing"
            elif record is not None and source["status"] != "sealed":
                state = "cache_on_unsealed_source"
            elif source["status"] != "sealed":
                state = "source_active"
            elif record is None:
                state = "cache_missing"
            elif (record["source_ledger_sha256"] != source["ledger_sha256"]
                  or record["source_match_count"] != source["match_count"]):
                state = "cache_source_mismatch"
            elif check_cached_rows:
                try:
                    self.model.stats_cache.verified_school_rows(
                        school_id, start_year=year, end_year=year,
                    )
                except (CareerStatsCacheConflict, sqlite3.DatabaseError,
                        KeyError, ValueError):
                    state = "cache_corrupt"
                else:
                    state = "cache_ready"
            else:
                state = "cache_metadata_matches"
            info["cache_status"] = state
            rows.append(info)

        counts = dict(sorted(Counter(
            row["cache_status"] for row in rows
        ).items()))
        return {
            "screen": "cache_diagnostics",
            "school_id": school_id,
            "start_year": start_year,
            "end_year": end_year,
            "cache_file_state": cache_state,
            "check_cached_rows": check_cached_rows,
            "source_kind": SOURCE,
            "source_payloads_rechecked_on_read": False,
            "cache_materialized_during_read": False,
            "rows": rows,
            "counts": counts,
            "total_years": len(rows),
        }

    def benchmark(self, school_id: str, *, start_year: int, end_year: int,
                  repeats: int = 3, check_cached_rows: bool = True) -> dict:
        """Measure *this* local slot only; no fabricated nationwide timings."""
        if type(repeats) is not int or not 1 <= repeats <= 10:
            raise ValueError("invalid performance repeat count")
        elapsed = []
        peaks = []
        summary = None
        for _ in range(repeats):
            tracemalloc.start()
            start = perf_counter()
            try:
                result = self.report(
                    school_id, start_year=start_year, end_year=end_year,
                    check_cached_rows=check_cached_rows,
                )
            finally:
                elapsed.append(round((perf_counter() - start) * 1000, 3))
                peaks.append(tracemalloc.get_traced_memory()[1])
                tracemalloc.stop()
            summary = result["counts"]
        return {
            "school_id": school_id, "start_year": start_year,
            "end_year": end_year, "repeats": repeats,
            "elapsed_ms": elapsed, "median_elapsed_ms": median(elapsed),
            "peak_traced_python_bytes": peaks,
            "max_peak_traced_python_bytes": max(peaks),
            "counts": summary,
            "measurement_scope": "one_local_slot_one_school",
            "nationwide_3000_schools_100_years_verified": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only career cache diagnostics")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--slot", required=True)
    parser.add_argument("--school-id", required=True)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--repeats", type=int, default=0,
                        help="0=diagnostics only; 1..10=measure repeat reads")
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    model = CareerHistoryBrowseModel(Path(args.data_root), Path(args.slot))
    reader = CareerHistoryCacheDiagnostics(model)
    kwargs = {
        "start_year": args.start_year, "end_year": args.end_year,
        "check_cached_rows": not args.metadata_only,
    }
    result = (
        reader.benchmark(args.school_id, repeats=args.repeats, **kwargs)
        if args.repeats else reader.report(args.school_id, **kwargs)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
