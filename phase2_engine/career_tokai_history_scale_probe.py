"""Stage43G-56: bounded, read-only performance probe of saved Tokai views.

This only observes existing fictional game archives. It never generates a
national 100-year season, infers unplayed results, or repairs history caches.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
from time import perf_counter
import tracemalloc

from .career_tokai_season_browse_model import (
    CareerTokaiSeasonBrowseModel, TokaiSeasonBrowseConflict, TOKAI,
    TOKAI_SEASON_IDS,
)


def _file_sha(path: Path) -> str:
    checksum = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _files_snapshot(slot: Path) -> dict[str, str]:
    """Include SQLite sidecars and derived caches; the probe cannot write any."""
    return {
        f.name: _file_sha(f)
        for f in sorted(slot.glob("*.sqlite3*"))
        if f.is_file()
    }


def run_tokai_history_scale_probe(
    model: CareerTokaiSeasonBrowseModel, *,
    years: list[int] | tuple[int, ...], school_id: str,
    competition_id: str = TOKAI, limit: int = 30,
    repeats: int = 2,
) -> dict:
    """Measure existing saved-year overview, first/next match and school pages.

    The bounded diagnostic does not impose timing budgets, extrapolate sampled
    runs or assert that 3,000 schools / unlimited simulated years were tested.
    """
    if (not isinstance(years, (tuple, list)) or not 1 <= len(years) <= 100
            or any(type(y) is not int or y < 2027 for y in years)
            or len(set(years)) != len(years)):
        raise ValueError("choose 1..100 unique archived years >= 2027")
    if (type(repeats) is not int or not 1 <= repeats <= 5
            or type(limit) is not int or not 1 <= limit <= 100):
        raise ValueError("invalid probe bounds")
    if competition_id not in TOKAI_SEASON_IDS:
        raise ValueError("competition not in the Tokai season view")
    if school_id not in model.source.repo.school_to_program:
        raise TokaiSeasonBrowseConflict("unknown hardball school ID")
    archived = {row["year"] for row in model.source.years()}
    if any(year not in archived for year in years):
        raise TokaiSeasonBrowseConflict("requested year has no archived games")

    slot = model.source.slot_root
    before = _files_snapshot(slot)
    if model.path.name not in before:
        raise TokaiSeasonBrowseConflict("A-history source file is missing")
    metrics: dict[str, list[dict]] = {
        name: [] for name in (
            "overview", "competition_first", "competition_next",
            "school_first", "school_next",
        )
    }
    coverage = []
    for year in sorted(years):
        # Measure each screen path exactly as the GUI does: no synthetic rows,
        # no cached output substituted for the read model.
        tasks = (
            ("overview", lambda y=year: model.overview(y)),
            ("competition_first", lambda y=year: model.competition(
                y, competition_id, offset=0, limit=limit,
            )),
            ("competition_next", lambda y=year: model.competition(
                y, competition_id, offset=limit, limit=limit,
            )),
            ("school_first", lambda y=year: model.school(
                y, school_id, offset=0, limit=limit,
            )),
            ("school_next", lambda y=year: model.school(
                y, school_id, offset=limit, limit=limit,
            )),
        )
        counts = {}
        for name, read in tasks:
            for _ in range(repeats):
                tracemalloc.start()
                started = perf_counter()
                try:
                    page = read()
                finally:
                    elapsed_ms = round((perf_counter() - started) * 1000, 3)
                    peak_bytes = tracemalloc.get_traced_memory()[1]
                    tracemalloc.stop()
                if name == "overview":
                    counts["archived_match_count"] = page["archived_match_count"]
                    rows = len(page["events"])
                else:
                    rows = len(page["matches"]["rows"])
                    if rows > limit:
                        raise AssertionError("browse exceeded requested page limit")
                    counts[name + "_total"] = page["matches"]["total"]
                metrics[name].append({
                    "year": year, "milliseconds": elapsed_ms,
                    "traced_python_peak_bytes": peak_bytes,
                    "rows": rows,
                })
        coverage.append({"year": year, **counts})
    after = _files_snapshot(slot)
    if after != before:
        raise AssertionError("read-only Tokai probe changed SQLite or sidecars")
    return {
        "stage": "43G-56",
        "source_kind": "fictional_saved_option_a_games_only",
        "measured_not_extrapolated": True,
        "sampled_years": sorted(years),
        "sampled_year_count": len(years),
        "sampled_school_id": school_id,
        "sampled_competition_id": competition_id,
        "page_limit": limit,
        "repeats": repeats,
        "coverage": coverage,
        "measurements": {
            name: {
                "sample_count": len(values),
                "median_ms": round(median(x["milliseconds"] for x in values), 3),
                "max_traced_python_peak_bytes": max(
                    x["traced_python_peak_bytes"] for x in values
                ),
                "max_returned_rows": max(x["rows"] for x in values),
            }
            for name, values in metrics.items()
        },
        "source_sqlite_and_sidecars_unchanged": True,
        "game_simulation_performed": False,
        "nationwide_3000_schools_tested": False,
        "unlimited_year_progression_proven": False,
        "official_match_results_included": False,
        "cache_repair_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure existing fictional Tokai archive GUI read paths",
    )
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--slot", required=True)
    parser.add_argument("--school-id", required=True)
    parser.add_argument("--years", type=int, nargs="+", required=True)
    parser.add_argument("--competition-id", default=TOKAI)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    model = CareerTokaiSeasonBrowseModel(
        Path(args.data_root), Path(args.slot),
    )
    result = run_tokai_history_scale_probe(
        model, years=args.years, school_id=args.school_id,
        competition_id=args.competition_id, limit=args.limit,
        repeats=args.repeats,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
