"""Stage43G-78: reproducible, bounded FULL-A fictional-v2 search audit.

Every record is a synthetic, schema-valid full Option-A fixture; not a real
high-school tournament or an actual 3,000-school x 100-year saved career.
Only fresh temporary SQLite files are written. Source data is never migrated.
Runtime latencies are measurements, NOT cross-hardware performance promises.
"""
from __future__ import annotations

import argparse
from contextlib import closing, nullcontext
import json
from pathlib import Path
from statistics import median
import tempfile
from time import perf_counter

from .career_calendar_v2 import (
    CareerCalendarV2Archive, explicit_sandbox_plan,
)
from .career_history_scale_audit import synthetic_ability_record
from .career_history_scale_benchmark import file_sha256
from .career_option_a_storage_profile import _read_only
from .career_v2_option_a_archive import CareerV2OptionAArchive
from .career_v2_school_game_page import _SCHOOL_SQL

SOURCE = "bounded_synthetic_full_a_fictional_v2_school_search_audit"
COMPETITION = "CMPV2AUDIT"
TARGET_SCHOOL = "SCH000001"
PAIR_COUNT = 20


def _validated(years: int, games_per_year: int, repetitions: int,
               allow_large: bool) -> None:
    if (type(years) is not int or not 1 <= years <= 100
            or type(games_per_year) is not int
            or not 2 <= games_per_year <= 1000
            or type(repetitions) is not int or not 1 <= repetitions <= 20
            or type(allow_large) is not bool):
        raise ValueError("invalid bounded v2 audit dimensions")
    total = years * games_per_year
    if total > 1000 and not allow_large:
        raise ValueError("large fixture requires explicit --allow-large")
    if total > 100000:
        raise ValueError("v2 audit hard cap is 100000 fictional matches")


def _synthetic_full_a(year: int, ordinal: int) -> dict:
    pair = ordinal % PAIR_COUNT
    first = f"SCH{2 * pair + 1:06d}"
    second = f"SCH{2 * pair + 2:06d}"
    source = synthetic_ability_record(
        year, COMPETITION, f"V2-AUDIT-{year}-{ordinal:05d}",
        first, second, 1,
    )
    source.pop("match_date")
    source["game_day_token"] = f"G{year}:04-{1 + ordinal % 2:02d}"
    source["date_source"] = "fictional_v2_day_slot"
    source["completed_on"] = ""
    return source


def _summary(values: list[float]) -> dict:
    seq = sorted(values)
    return {
        "samples": len(seq),
        "median_ms": round(median(seq), 3),
        "max_ms": round(seq[-1], 3),
        "samples_ms": [round(x, 3) for x in values],
    }


def _plans(path: Path, first: int, last: int) -> dict:
    school = _SCHOOL_SQL
    args = (first, last, TARGET_SCHOOL, TARGET_SCHOOL)
    cases = {
        "count_school_matches": (
            "SELECT COUNT(*) FROM v2_option_a_matches WHERE " + school,
            args,
        ),
        "first_30_school_matches": (
            "SELECT * FROM v2_option_a_matches WHERE " + school
            + " ORDER BY year,game_day_token,competition_id,match_id "
            "LIMIT ? OFFSET ?",
            args + (30, 0),
        ),
        "sealed_ledger_rows": (
            "SELECT competition_id,match_id,record_sha256 "
            "FROM v2_option_a_matches WHERE year=? "
            "ORDER BY competition_id,match_id",
            (first,),
        ),
    }
    with closing(_read_only(path)) as conn:
        return {
            label: [
                row[3] for row in conn.execute(
                    "EXPLAIN QUERY PLAN " + sql, params,
                )
            ]
            for label, (sql, params) in cases.items()
        }


def run_v2_school_search_audit(*, years: int = 4,
                               games_per_year: int = 40,
                               repetitions: int = 3,
                               output_root: str | Path | None = None,
                               allow_large: bool = False) -> dict:
    """Actually build, seal and query *only* a bounded synthetic A archive."""
    _validated(years, games_per_year, repetitions, allow_large)
    workspace = (
        tempfile.TemporaryDirectory(prefix="kokosim-v2-school-search-")
        if output_root is None else nullcontext(str(output_root))
    )
    with workspace as directory:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        v2_file = root / "fictional_option_a_v2.sqlite3"
        calendar_file = root / "sandbox_calendar_v2.sqlite3"
        # Never overwrite or append to an existing database or user slot.
        if v2_file.exists() or calendar_file.exists():
            raise ValueError("v2 audit refuses to reuse any existing SQLite source")
        calendar = CareerCalendarV2Archive(calendar_file)
        archive = CareerV2OptionAArchive(v2_file, calendar_file)
        t0 = perf_counter()
        for year in range(10000, 10000 + years):
            calendar.record(explicit_sandbox_plan(
                year, {COMPETITION: ["04-01", "04-02"]},
                approved_for_fictional_game=True,
            ))
            for ordinal in range(games_per_year):
                result = archive.append(
                    year, _synthetic_full_a(year, ordinal),
                )
                if result["inserted"] is not True:
                    raise RuntimeError("benchmark fixture was not freshly inserted")
            archive.seal_year(year, expected_match_count=games_per_year)
        build_seconds = round(perf_counter() - t0, 3)
        hashes_before = {
            "fictional_option_a_v2.sqlite3": file_sha256(v2_file),
            "sandbox_calendar_v2.sqlite3": file_sha256(calendar_file),
        }
        first, last = 10000, 10000 + years - 1
        explain = _plans(v2_file, first, last)
        timings = {"page": [], "selected_years": [], "competition_page": []}
        pages = {}
        for i in range(repetitions):
            for label, opts in (
                ("page", {}),
                ("selected_years", {"verify_scope": "selected_years"}),
                ("competition_page", {"competition_id": COMPETITION}),
            ):
                begin = perf_counter()
                page = archive.school_game_page(
                    TARGET_SCHOOL, start_year=first, end_year=last,
                    limit=30, offset=0, **opts,
                )
                timings[label].append((perf_counter() - begin) * 1000)
                if page["source_records_not_modified"] is not True:
                    raise RuntimeError("read-only v2 page contract changed")
                if page["saved_year_metadata_and_ledger_verified"] is not True:
                    raise RuntimeError("sealed v2 ledger was not verified")
                pages[label] = page
        expected_selected = years * sum(
            ordinal % PAIR_COUNT == 0
            for ordinal in range(games_per_year)
        )
        if not all(x["total"] == expected_selected for x in pages.values()):
            raise RuntimeError("synthetic school count mismatched the saved fixture")
        if not pages["selected_years"]["all_selected_year_payloads_verified"]:
            raise RuntimeError("deep original SHA verification was skipped")
        hashes_after = {
            "fictional_option_a_v2.sqlite3": file_sha256(v2_file),
            "sandbox_calendar_v2.sqlite3": file_sha256(calendar_file),
        }
        if hashes_before != hashes_after:
            raise RuntimeError("benchmark must never change saved SQLite")
        return {
            "audit_contract": SOURCE,
            "synthetic_full_option_a_only": True,
            "official_competition_or_real_multiyear_progression": False,
            "fixture_written_to_isolated_temporary_files_only":
                output_root is None,
            "first_game_year": first, "last_game_year": last,
            "years": years, "games_per_year": games_per_year,
            "full_a_saved_matches": years * games_per_year,
            "target_school": TARGET_SCHOOL,
            "target_school_saved_matches": expected_selected,
            "repetitions": repetitions,
            "fixture_build_seconds": build_seconds,
            "v2_file_bytes": v2_file.stat().st_size,
            "calendar_file_bytes": calendar_file.stat().st_size,
            "query_plans": explain,
            "measured_queries": {
                k: _summary(v) for k, v in timings.items()
            },
            "page_size": 30,
            "page_scope_checks_visible_payload_only": True,
            "strict_scope_verifies_all_saved_year_payloads": True,
            "school_filter_uses_unindexed_json1_scan": True,
            "cross_machine_latency_guarantee": False,
            "actual_3000_school_100_year_gameplay_proven": False,
            "source_sha256_before": hashes_before,
            "source_sha256_after": hashes_after,
            "source_bytes_unchanged": True,
            "v2_sandbox_not_migrated": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bounded synthetic full-A v2 school-search read benchmark",
    )
    parser.add_argument("--years", type=int, default=4)
    parser.add_argument("--games-per-year", type=int, default=40)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--allow-large", action="store_true")
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    report = run_v2_school_search_audit(
        years=args.years, games_per_year=args.games_per_year,
        repetitions=args.repetitions, output_root=args.output_root,
        allow_large=args.allow_large,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
