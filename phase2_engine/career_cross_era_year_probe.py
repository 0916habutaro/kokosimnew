"""Stage43G-61: bounded, read-only keyset catalog measurement.

Measures only actual sealed year HEADERS in an existing save. It never
simulates unplayed years, tests full nation-wide game runtime, or extrapolates
latency/storage to an arbitrary 100-year career.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
from time import perf_counter
import tracemalloc

from .career_cross_era_year_catalog import CareerCrossEraYearCatalog


def _file_digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _snapshot(slot: Path) -> dict[str, str]:
    return {
        file.name: _file_digest(file)
        for file in sorted(slot.glob("*.sqlite3*"))
        if file.is_file()
    }


def probe_cross_era_year_catalog(
    slot_root: str | Path, *, limit: int = 24, max_pages: int = 50,
) -> dict:
    """Read at most max_pages keyset pages and verify no SQLite was changed."""
    if (type(limit) is not int or not 1 <= limit <= 24
            or type(max_pages) is not int or not 1 <= max_pages <= 100):
        raise ValueError("invalid bounded catalog probe limits")
    slot = Path(slot_root)
    before = _snapshot(slot)
    catalog = CareerCrossEraYearCatalog(slot)
    cursor = None
    prior_year = None
    sample = []
    observed_years = set()
    complete = False
    try:
        for _ in range(max_pages):
            tracemalloc.start()
            started = perf_counter()
            try:
                page = catalog.page_after(before_year=cursor, limit=limit)
            finally:
                elapsed_ms = round((perf_counter() - started) * 1000, 3)
                peak_bytes = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
            years = [row["year"] for row in page["years"]]
            if (len(years) > limit
                    or len(years) != len(set(years))
                    or years != sorted(years, reverse=True)
                    or any(y in observed_years for y in years)
                    or (years and prior_year is not None
                        and years[0] >= prior_year)):
                raise AssertionError("catalog cursor ordering or bounds differ")
            observed_years.update(years)
            if years:
                prior_year = years[-1]
            sample.append({
                "start_cursor_exclusive": cursor,
                "year_count": len(years),
                "elapsed_ms": elapsed_ms,
                "traced_python_peak_bytes": peak_bytes,
            })
            if not page["has_older"]:
                complete = True
                break
            next_cursor = page["next_cursor_before_year"]
            if (not years or next_cursor != years[-1]
                    or next_cursor == cursor):
                raise AssertionError("catalog cursor failed to advance")
            cursor = next_cursor
    finally:
        after = _snapshot(slot)
        if before != after:
            raise AssertionError("catalog probe modified saved SQLite files")
    return {
        "stage": "43G-61",
        "source": "saved_sealed_year_headers_not_gameplay_simulation",
        "slot_files_checked": sorted(before),
        "limit": limit,
        "max_pages": max_pages,
        "sampled_pages": len(sample),
        "sampled_unique_year_headers": len(observed_years),
        "older_catalog_exhausted": complete,
        "median_page_ms": round(
            median(row["elapsed_ms"] for row in sample), 3,
        ),
        "max_traced_python_peak_bytes": max(
            row["traced_python_peak_bytes"] for row in sample
        ),
        "measurements": sample,
        "verified_gameplay_years": False,
        "verified_source_payloads": False,
        "read_only_sha256_unchanged": True,
        "combined_career_stats_authorized": False,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Bounded read-only legacy/v2 sealed-year catalog probe",
    )
    p.add_argument("--slot", type=Path, required=True)
    p.add_argument("--limit", type=int, default=24)
    p.add_argument("--max-pages", type=int, default=50)
    args = p.parse_args()
    result = probe_cross_era_year_catalog(
        args.slot, limit=args.limit, max_pages=args.max_pages,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
