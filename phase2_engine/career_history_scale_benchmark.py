"""Stage43G-20: bounded, deterministic synthetic century-history benchmark.

This measures the real SQLite A-archive *score-only* storage shape and the
Stage43G-13 indexed school-results reader. It is NOT an all-3000-schools game
simulation, a full Option-A box-score test, or an unlimited-years proof.

Synthetic datasets are generated in a temporary directory, never a user slot.
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
import tracemalloc

from .career_longitudinal_read import CareerLongitudinalReadModel
from .career_roster_archive import CareerRosterArchive
from .historical_match_archive import (
    HistoricalMatchArchive, _SCHEMA as MATCH_SCHEMA,
    _canonical, _digest, _history_payload,
)

START_YEAR = 2026
SAFE_MAX_ROWS = 250_000
HARD_MAX_ROWS = 5_000_000
SOURCE = "synthetic_score_only_not_actual_game"


def validate_scale(schools: int, years: int, games_per_school_year: int,
                   repeats: int, *, allow_large: bool = False) -> int:
    if (type(schools) is not int or not 1 <= schools <= 3_000
            or type(years) is not int or not 1 <= years <= 100
            or type(games_per_school_year) is not int
            or not 1 <= games_per_school_year <= 50
            or type(repeats) is not int or not 1 <= repeats <= 10
            or type(allow_large) is not bool):
        raise ValueError("invalid synthetic benchmark dimensions")
    total = schools * years * games_per_school_year
    if total > HARD_MAX_ROWS:
        raise ValueError("synthetic benchmark exceeds absolute row limit")
    if total > SAFE_MAX_ROWS and not allow_large:
        raise ValueError(
            "large synthetic test requires explicit --allow-large"
        )
    return total


def school_id(n: int) -> str:
    return f"BENCH-SCH-{n:04d}"


def build_synthetic_archive(
    path: Path, *, schools: int, years: int,
    games_per_school_year: int,
) -> dict:
    """Build only into a newly created scratch DB, with real schema/indexes.

    All rows pass the actual archive normalization and SHA calculation,
    not a reduced fake JSON shape. They intentionally lack individual
    inning/box-score stats; capacity here is a SCORE-ONLY lower-bound.
    """
    if path.exists():
        raise FileExistsError("synthetic archive target already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    start = perf_counter()
    rows_written = 0
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(MATCH_SCHEMA)
        for year in range(START_YEAR, START_YEAR + years):
            entries = []
            for school_no in range(1, schools + 1):
                first = school_id(school_no)
                second = f"BENCH-OPP-{school_no:04d}"
                for game_no in range(games_per_school_year):
                    game = {
                        "competition_id": (
                            "BENCH-CMP-A" if game_no % 2 == 0
                            else "BENCH-CMP-B"
                        ),
                        "match_id": (
                            f"BENCH-{year}-{school_no:04d}-{game_no:02d}"
                        ),
                        "match_date": f"{year:04d}-04-01",
                        "date_source": "synthetic_fixture_v1",
                        "status": "completed",
                        "team1_id": first,
                        "team2_id": second,
                        "team1_score": 2 + game_no % 4,
                        "team2_score": 1,
                        "winner_id": first,
                        "loser_id": second,
                        "score_source": "synthetic_score_only",
                    }
                    payload = _history_payload(year, game)
                    raw = _canonical(payload)
                    entries.append((
                        year, payload["competition_id"], payload["match_id"],
                        payload["match_date"], payload["date_source"],
                        payload["team1_id"], payload["team2_id"],
                        payload["team1_score"], payload["team2_score"],
                        payload["score_source"], _digest(raw), raw,
                    ))
            with conn:
                conn.execute(
                    "INSERT INTO career_years (year,metadata_json,status) "
                    "VALUES (?,?,'active')",
                    (year, _canonical({
                        "year": year, "source": SOURCE
                    })),
                )
                conn.executemany(
                    "INSERT INTO historical_matches "
                    "(year,competition_id,match_id,match_date,date_source,"
                    "team1_id,team2_id,team1_score,team2_score,score_source,"
                    "record_sha256,payload_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    entries,
                )
                count, ledger = HistoricalMatchArchive._ledger(conn, year)
                if count != len(entries):
                    raise ValueError("synthetic yearly match count mismatched")
                conn.execute(
                    "UPDATE career_years SET status='sealed',match_count=?,"
                    "ledger_sha256=? WHERE year=?",
                    (count, ledger, year),
                )
            rows_written += len(entries)
    return {
        "match_rows": rows_written,
        "db_bytes": path.stat().st_size,
        "build_elapsed_ms": round((perf_counter() - start) * 1000, 3),
    }


def measure_indexed_history(
    path: Path, *, schools: int, years: int,
    games_per_school_year: int, repeats: int,
) -> dict:
    """Use the production school-history read model on the generated DB."""
    model = CareerLongitudinalReadModel(
        HistoricalMatchArchive(path),
        CareerRosterArchive(path.parent / "not_created_rosters.sqlite3"),
    )
    sample_numbers = sorted({1, (schools + 1) // 2, schools})
    samples = []
    db_hash_before = sha256(path.read_bytes()).hexdigest()
    for number in sample_numbers:
        sid = school_id(number)
        measurements = []
        peaks = []
        expected_games = years * games_per_school_year
        for _ in range(repeats):
            tracemalloc.start()
            start = perf_counter()
            try:
                page = model.school_results(
                    sid, start_year=START_YEAR,
                    end_year=START_YEAR + years - 1,
                    limit=30, offset=0,
                )
            finally:
                measurements.append(
                    round((perf_counter() - start) * 1000, 3)
                )
                peaks.append(tracemalloc.get_traced_memory()[1])
                tracemalloc.stop()
            if sum(
                row["games"] for row in page["records"]
            ) > expected_games:
                raise AssertionError("paginated result has excess games")
            if page["total_groups"] != years * min(
                games_per_school_year, 2
            ):
                raise AssertionError("unexpected synthetic groups")
            if len(page["records"]) > 30:
                raise AssertionError("history result bypassed page limit")
        samples.append({
            "school_id": sid,
            "total_groups": page["total_groups"],
            "first_page_rows": len(page["records"]),
            "median_first_page_ms": median(measurements),
            "repeat_elapsed_ms": measurements,
            "max_traced_python_bytes": max(peaks),
        })
    if sha256(path.read_bytes()).hexdigest() != db_hash_before:
        raise AssertionError("read benchmark modified SQLite source bytes")

    with closing(sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True
    )) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM historical_matches"
        ).fetchone()[0]
        indexes = sorted(
            row[1] for row in conn.execute(
                "PRAGMA index_list('historical_matches')"
            )
        )
    if count != schools * years * games_per_school_year:
        raise AssertionError("synthetic archive was incompletely stored")
    for required in ("idx_history_school1_year", "idx_history_school2_year"):
        if required not in indexes:
            raise AssertionError("school-first search index missing")
    return {
        "measurement": "indexed_school_history_first_page",
        "samples": samples,
        "db_unmodified_by_reads": True,
        "required_school_first_indexes_present": True,
        "query_page_limit": 30,
        "full_box_score_perf_measured": False,
    }


def run_benchmark(*, schools: int = 24, years: int = 50,
                  games_per_school_year: int = 4,
                  repeats: int = 3, allow_large: bool = False) -> dict:
    total = validate_scale(
        schools, years, games_per_school_year, repeats,
        allow_large=allow_large,
    )
    with tempfile.TemporaryDirectory(prefix="kokosim-scale-") as d:
        path = Path(d) / "synthetic_historical_matches.sqlite3"
        generated = build_synthetic_archive(
            path, schools=schools, years=years,
            games_per_school_year=games_per_school_year,
        )
        reads = measure_indexed_history(
            path, schools=schools, years=years,
            games_per_school_year=games_per_school_year,
            repeats=repeats,
        )
    return {
        "stage": "43G-20",
        "source_kind": SOURCE,
        "start_year": START_YEAR, "years": years,
        "schools": schools,
        "games_per_school_year": games_per_school_year,
        "expected_match_rows": total,
        "actual_match_rows": generated["match_rows"],
        "database_bytes": generated["db_bytes"],
        "build_elapsed_ms": generated["build_elapsed_ms"],
        "read_measurements": reads,
        "temporary_data_deleted_after_run": True,
        "population_3000_schools_100_years_verified": (
            schools == 3000 and years == 100
        ),
        "production_gameplay_or_full_option_A_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthetic multi-decade SQLite history benchmark"
    )
    parser.add_argument("--schools", type=int, default=24)
    parser.add_argument("--years", type=int, default=50)
    parser.add_argument("--games-per-school-year", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--allow-large", action="store_true")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    result = run_benchmark(
        schools=args.schools, years=args.years,
        games_per_school_year=args.games_per_school_year,
        repeats=args.repeats, allow_large=args.allow_large,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
