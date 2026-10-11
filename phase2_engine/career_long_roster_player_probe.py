"""Stage43G-66: measure indexed permanent-player career lookup read-only.

The query always uses a stable player ID and, per the game's high-school
grade 1–3 contract, at most three actual annual roster snapshots. Results
do NOT imply 3000 schools × 100 years were simulated or verified.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from statistics import median
from time import perf_counter
import tracemalloc

from .career_option_a_storage_profile import _read_only
from .career_roster_archive import CareerRosterArchive
from .career_history_scale_benchmark import file_sha256


def probe_roster_player_history(roster_db: str | Path, player_id: str, *,
                                repeats: int = 3) -> dict:
    if type(player_id) is not str or not player_id:
        raise ValueError("permanent player ID required")
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("repeats must be 1..10")
    path = Path(roster_db)
    if not path.is_file():
        raise FileNotFoundError("saved roster SQLite missing")
    before = file_sha256(path)
    with closing(_read_only(path)) as conn:
        total_schools, total_year_rows = conn.execute(
            "SELECT COUNT(DISTINCT school_id), COUNT(*) "
            "FROM career_school_rosters"
        ).fetchone()
        query_plan = [
            row[3] for row in conn.execute(
                "EXPLAIN QUERY PLAN SELECT year FROM career_school_rosters "
                "WHERE school_id=? AND year BETWEEN ? AND ? ORDER BY year",
                ("BENCH_SCHOOL_ID", 2026, 2028),
            )
        ]
        if not any(
            "SEARCH career_school_rosters" in item
            and "idx_career_rosters_school_year" in item
            for item in query_plan
        ):
            raise ValueError("school-year lookup did not use the saved index")
    archive = CareerRosterArchive(path)
    elapsed = []
    memory = []
    expected = None
    for _ in range(repeats):
        tracemalloc.start()
        started = perf_counter()
        try:
            result = archive.player_history(player_id)
        finally:
            elapsed.append(round((perf_counter() - started) * 1000, 3))
            memory.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.stop()
        if expected is not None and result != expected:
            raise ValueError("read-only player history changed between runs")
        expected = result
    if before != file_sha256(path):
        raise AssertionError("player history query changed saved SQLite")
    return {
        "stage": "43G-66",
        "source": "saved_school_roster_snapshots_not_gameplay_simulation",
        "total_saved_school_year_rows": total_year_rows,
        "distinct_saved_school_ids": total_schools,
        "selected_player_id": player_id,
        "player_membership_years": [
            row["year"] for row in expected
        ],
        "verified_membership_snapshots": len(expected),
        "bounded_grade_window_years": 3,
        "query_plan": query_plan,
        "lookup_ms": elapsed,
        "median_lookup_ms": round(median(elapsed), 3),
        "peak_traced_python_bytes": max(memory),
        "source_sha256_unchanged": True,
        "verified_all_schools_or_years": False,
        "verified_full_option_a_game_archive": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only bounded permanent player history probe"
    )
    parser.add_argument("--rosters", type=Path, required=True)
    parser.add_argument("--player-id", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    options = parser.parse_args()
    report = probe_roster_player_history(
        options.rosters, options.player_id, repeats=options.repeats,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
