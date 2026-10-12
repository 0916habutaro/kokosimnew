"""Stage43G-79: side-by-side bounded synthetic indexed vs JSON1 v2 reads.

This is NOT a real 3000-school career simulation. Measurements are specific
to CI hardware, exact fixture shape and year span; no speedup is promised.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
from statistics import median
import tempfile
from time import perf_counter
import sqlite3

from .career_calendar_v2 import CareerCalendarV2Archive, explicit_sandbox_plan
from .career_history_scale_audit import synthetic_ability_record
from .career_history_scale_benchmark import file_sha256
from .career_option_a_storage_profile import _read_only
from .career_v2_option_a_archive import CareerV2OptionAArchive
from .career_v2_school_read_index import (
    build_v2_school_read_index, read_indexed_v2_school_page,
)

SCHOOL = "SCH000001"
COMP = "CMPV2AUDIT"


def audit_indexed_v2_search(*, years: int = 4,
                            games_per_year: int = 40,
                            repetitions: int = 2,
                            allow_large: bool = False) -> dict:
    if (type(years) is not int or not 1 <= years <= 100
            or type(games_per_year) is not int or
            not 2 <= games_per_year <= 1000
            or type(repetitions) is not int or
            not 1 <= repetitions <= 20
            or type(allow_large) is not bool):
        raise ValueError("invalid bounded synthetic index benchmark")
    count = years * games_per_year
    if count > 1000 and not allow_large:
        raise ValueError("large fixture requires --allow-large")
    if count > 100000:
        raise ValueError("index benchmark limit exceeded")
    with tempfile.TemporaryDirectory(prefix="kokosim-v2-index-audit-") as wd:
        root = Path(wd)
        source = root / "fictional_option_a_v2.sqlite3"
        calendar_path = root / "sandbox_calendar_v2.sqlite3"
        index = root / "fictional_v2_school_read_index.sqlite3"
        calendar = CareerCalendarV2Archive(calendar_path)
        archive = CareerV2OptionAArchive(source, calendar_path)
        for year in range(10000, 10000 + years):
            calendar.record(explicit_sandbox_plan(
                year, {COMP: ["04-01", "04-02"]},
                approved_for_fictional_game=True,
            ))
            for ordinal in range(games_per_year):
                pair = ordinal % 20
                first, second = (
                    f"SCH{2*pair+1:06d}", f"SCH{2*pair+2:06d}",
                )
                data = synthetic_ability_record(
                    year, COMP, f"IDX-{year}-{ordinal:05d}",
                    first, second, 1,
                )
                data.pop("match_date")
                data["game_day_token"] = (
                    f"G{year}:04-{1+ordinal%2:02d}"
                )
                data["date_source"] = "fictional_v2_day_slot"
                data["completed_on"] = ""
                archive.append(year, data)
            archive.seal_year(year, expected_match_count=games_per_year)
        originals = {
            source.name: file_sha256(source),
            calendar_path.name: file_sha256(calendar_path),
        }
        started = perf_counter()
        built = build_v2_school_read_index(
            source, calendar_path, index,
            start_year=10000, end_year=10000 + years - 1,
        )
        build_index_ms = round((perf_counter() - started) * 1000, 3)
        selected = years * sum(
            ordinal % 20 == 0 for ordinal in range(games_per_year)
        )
        data: dict[str, list[float]] = {
            "json1_page": [], "indexed_page": [],
            "json1_strict": [], "indexed_strict": [],
        }
        for _ in range(repetitions):
            for name in data:
                start = perf_counter()
                if name.startswith("json1"):
                    page = archive.school_game_page(
                        SCHOOL, start_year=10000,
                        end_year=10000 + years - 1, limit=30,
                        verify_scope=(
                            "selected_years" if name.endswith("strict")
                            else "page"
                        ),
                    )
                else:
                    page = read_indexed_v2_school_page(
                        source, calendar_path, index, SCHOOL,
                        start_year=10000, end_year=10000 + years - 1,
                        limit=30, verify_scope=(
                            "selected_years" if name.endswith("strict")
                            else "page"
                        ),
                    )
                data[name].append((perf_counter() - start) * 1000)
                if page["total"] != selected:
                    raise RuntimeError("index and source school counts differ")
        original_page = archive.school_game_page(
            SCHOOL, start_year=10000, end_year=10000 + years - 1,
        )
        index_page = read_indexed_v2_school_page(
            source, calendar_path, index, SCHOOL,
            start_year=10000, end_year=10000 + years - 1,
        )
        if original_page["records"] != index_page["records"]:
            raise RuntimeError("index school display differs from original")
        after = {
            source.name: file_sha256(source),
            calendar_path.name: file_sha256(calendar_path),
        }
        if originals != after:
            raise RuntimeError("authoritative sealed v2 files changed")
        with closing(_read_only(index)) as conn:
            school_plan = [
                str(row[3]) for row in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT COUNT(*) "
                    "FROM school_game WHERE school_id=? "
                    "AND year BETWEEN ? AND ?",
                    (SCHOOL, 10000, 10000 + years - 1),
                )
            ]
        return {
            "audit_contract": "stage43g79_bounded_synthetic_index_comparison",
            "years": years, "fictional_full_a_matches": count,
            "target_school_matches": selected,
            "source_json1_vs_index_records_identical": True,
            "index_build_ms": build_index_ms,
            "index_bytes": index.stat().st_size,
            "index_build_proof": built["derived_index_is_not_authoritative"],
            "source_sha256_before": originals,
            "source_sha256_after": after,
            "original_sqlite_unchanged": True,
            "school_lookup_sql_plan": school_plan,
            "measurement": {
                name: {
                    "median_ms": round(median(values), 3),
                    "samples_ms": [round(value, 3) for value in values],
                } for name, values in data.items()
            },
            "real_full_scale_3000_school_history_proven": False,
            "absolute_latency_or_speedup_guaranteed": False,
            "source_and_calendar_remain_authoritative": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=4)
    parser.add_argument("--games-per-year", type=int, default=40)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--allow-large", action="store_true")
    args = parser.parse_args()
    result = audit_indexed_v2_search(
        years=args.years, games_per_year=args.games_per_year,
        repetitions=args.repetitions, allow_large=args.allow_large,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
