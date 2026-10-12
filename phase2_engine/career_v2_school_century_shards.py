"""Stage43G-83: explicitly selected 100-year v2 school-index shards.

This composes *existing* sealed-source-verified Stage43G-79 readers, without
changing the v2 Option-A source or its calendar. There is no automatic
discovery or repair: callers specify exactly which shards to trust.

A single request is bounded for practical/UI performance, but the saved
career does NOT stop at year 10099; further 100-year segments may be
created, queried and paged through independently.
"""
from __future__ import annotations

from contextlib import closing, nullcontext
from pathlib import Path
import re
import sqlite3

from .career_option_a_storage_profile import _read_only
from .career_v2_school_read_index import (
    SCHEMA, CareerV2ReadIndexConflict, build_v2_school_read_index,
    _school_read_request,
)
from .career_v2_school_game_page import PAGE_SIZE

CENTURY_SPAN = 100
MAX_SHARDS_PER_REQUEST = 32
MAX_SHARDS_PER_BUILD = 32
_SUFFIX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,15}\Z")


def _window(year: int) -> tuple[int, int]:
    if type(year) is not int or year < 10000:
        raise ValueError("fictional v2 game years begin at 10000")
    start = 10000 + ((year - 10000) // CENTURY_SPAN) * CENTURY_SPAN
    return start, start + CENTURY_SPAN - 1


def _filename(first: int, last: int, suffix: str | None) -> str:
    if suffix is not None and (
        type(suffix) is not str or _SUFFIX.fullmatch(suffix) is None
    ):
        raise ValueError("invalid derived index version tag")
    tag = f"_G{first}_G{last}"
    if suffix is not None:
        tag += "_" + suffix
    return "fictional_v2_school_read_index" + tag + ".sqlite3"


def _source_years(source: Path, first: int, last: int) -> list[tuple[int, str]]:
    with closing(_read_only(source)) as conn:
        return [
            (year, status) for year, status in conn.execute(
                "SELECT year,status FROM v2_game_years "
                "WHERE year BETWEEN ? AND ? ORDER BY year",
                (first, last),
            )
        ]


def build_v2_school_century_shards(
    v2_path: str | Path, calendar_path: str | Path, *,
    start_year: int, end_year: int,
    version: str | None = None,
) -> dict:
    """Explicitly build new, independent century shards for saved years only.

    Preflights *all* target names, avoiding partially creating shards on
    an obvious name collision. A runtime source-integrity failure could
    still leave earlier new shards intact; they are never auto-activated.
    """
    if (type(start_year) is not int or type(end_year) is not int
            or start_year < 10000 or end_year < start_year):
        raise ValueError("invalid fictional v2 index build window")
    v2 = Path(v2_path).resolve()
    calendar = Path(calendar_path).resolve()
    if not v2.is_file() or not calendar.is_file():
        raise FileNotFoundError("authoritative v2 source and calendar required")
    if v2.parent != calendar.parent:
        raise ValueError("v2 source and calendar must share one save slot")
    first_bucket, _ = _window(start_year)
    last_bucket, _ = _window(end_year)
    number = (last_bucket - first_bucket) // CENTURY_SPAN + 1
    if number > MAX_SHARDS_PER_BUILD:
        raise ValueError("batch exceeds 32 century shards; choose a narrower window")
    # Query all saved years in requested buckets so no year is silently
    # skipped by partially selected century boundaries.
    saved = _source_years(v2, first_bucket, last_bucket + 99)
    if any(status != "sealed" for _, status in saved):
        raise CareerV2ReadIndexConflict("unsealed source years block shard build")
    buckets = sorted({_window(year) for year, _ in saved})
    if not buckets:
        raise ValueError("no saved sealed years in requested build buckets")
    targets = [
        (first, last, v2.parent / _filename(first, last, version))
        for first, last in buckets
    ]
    if any(path.exists() or path.is_symlink() for _, _, path in targets):
        raise FileExistsError("century index target already exists; use new version")
    made = []
    for first, last, target in targets:
        result = build_v2_school_read_index(
            v2, calendar, target, start_year=first, end_year=last,
        )
        made.append({
            "start_year": first, "end_year": last,
            "index_path": str(target),
            "indexed_source_matches": result["indexed_source_matches"],
        })
    return {
        "shards": made,
        "saved_years": [year for year, _ in saved],
        "fictional_v2_only": True,
        "source_and_calendar_modified": False,
        "old_indexes_overwritten": False,
        "automatic_gui_activation": False,
        "century_span": CENTURY_SPAN,
    }


def _shard_details(source: Path, calendar: Path,
                   index_path: str | Path, *, connection=None) -> tuple[int, int, Path]:
    """Reject foreign/alias/overlong/non-century source index candidates."""
    p = Path(index_path)
    if p.is_symlink() or p.resolve().parent != source.parent:
        raise ValueError("index shard must be local to the save slot")
    resolved = p.resolve()
    if resolved in (source, calendar):
        raise ValueError("derived index must not alias a source file")
    with (closing(_read_only(resolved)) if connection is None
          else nullcontext(connection)) as conn:
        conn.row_factory = sqlite3.Row
        meta = conn.execute("SELECT * FROM meta").fetchall()
        if len(meta) != 1:
            raise CareerV2ReadIndexConflict("missing shard index metadata")
        row = meta[0]
        first, last = row["start_year"], row["end_year"]
        if (row["schema_version"] != SCHEMA
                or row["source_path"] != str(source)
                or row["calendar_path"] != str(calendar)
                or type(first) is not int or type(last) is not int
                or first < 10000 or _window(first) != (first, last)):
            raise CareerV2ReadIndexConflict(
                "wrong-source or non-century index shard"
            )
    return first, last, resolved


def read_v2_school_century_page(
    v2_path: str | Path, calendar_path: str | Path,
    index_paths: list[str | Path] | tuple[str | Path, ...],
    school_id: str, *, start_year: int, end_year: int,
    competition_id: str | None = None,
    limit: int = PAGE_SIZE, offset: int = 0,
    verify_scope: str = "page",
) -> dict:
    """Globally page one school across explicit, sealed 100-year shards.

    Each contributing source shard is verified even when the school has
    zero games there. Missing shard coverage of *any saved source year*
    is fatal, rather than silently reporting fewer results.

    Proof, count and display share per-file read snapshots for this call.
    Independent PRAGMA data_version watchers reject observed commits to
    source, calendar or indexes. Separate files are not one atomic snapshot.
    """
    if (type(school_id) is not str or not school_id
            or type(start_year) is not int or type(end_year) is not int
            or start_year < 10000 or end_year < start_year
            or type(limit) is not int or not 1 <= limit <= 200
            or type(offset) is not int or offset < 0
            or (competition_id is not None and
                (type(competition_id) is not str or not competition_id))
            or type(verify_scope) is not str
            or verify_scope not in ("page", "selected_years")
            or not isinstance(index_paths, (list, tuple))
            or not 1 <= len(index_paths) <= MAX_SHARDS_PER_REQUEST):
        raise ValueError("invalid bounded cross-century school lookup")
    source = Path(v2_path).resolve()
    calendar = Path(calendar_path).resolve()
    if not source.is_file() or not calendar.is_file():
        raise FileNotFoundError("source v2 matches and calendar required")
    if source.parent != calendar.parent:
        raise ValueError("source and calendar must share a save slot")
    with _school_read_request(source, calendar) as request:
        # Validate candidate paths before opening; then inspect exactly the
        # same pinned index snapshot used for proof, count and display.
        details = []
        for path in index_paths:
            p = Path(path)
            if p.is_symlink() or p.resolve().parent != source.parent:
                raise ValueError("index shard must be local to the save slot")
            resolved = p.resolve()
            if resolved in (source, calendar):
                raise ValueError("derived index must not alias a source file")
            details.append(_shard_details(
                source, calendar, path, connection=request.connection(resolved),
            ))
        details.sort()
        for i, (first, last, _) in enumerate(details):
            if i and details[i - 1][1] >= first:
                raise CareerV2ReadIndexConflict("overlapping century index shards")
            if last < start_year or first > end_year:
                raise ValueError("index shard outside selected year window")
        original = request.source
        years = original.execute(
            "SELECT year,status FROM v2_game_years "
            "WHERE year BETWEEN ? AND ? ORDER BY year",
            (start_year, end_year),
        ).fetchall()
        if any(status != "sealed" for _, status in years):
            raise CareerV2ReadIndexConflict("unsealed saved year in school lookup")
        for year, _ in years:
            if sum(first <= year <= last for first, last, _ in details) != 1:
                raise CareerV2ReadIndexConflict(
                    "not all saved fictional v2 years have index coverage"
                )
        slices = []
        all_total = 0
        for first, last, path in details:
            lo, hi = max(start_year, first), min(end_year, last)
            verified = request.prepare(path, lo, hi, verify_scope)
            data = verified.page(school_id, competition_id, 1, 0)
            count = data["total"]
            if type(count) is not int or count < 0:
                raise CareerV2ReadIndexConflict("invalid shard total")
            slices.append((lo, hi, path, count, verified))
            all_total += count
        remaining, skipped = limit, offset
        records = []
        for lo, hi, path, count, verified in slices:
            if skipped >= count:
                skipped -= count
                continue
            if remaining == 0:
                break
            take = min(remaining, count - skipped)
            if take > 0:
                data = verified.page(school_id, competition_id, take, skipped)
                if (data["total"] != count or
                        len(data["records"]) != take):
                    raise CareerV2ReadIndexConflict(
                        "shard changed during composed pagination"
                    )
                records.extend(data["records"])
                remaining -= take
            skipped = 0
    return {
        "school_id": school_id, "start_year": start_year,
        "end_year": end_year, "competition_id": competition_id,
        "total": all_total, "records": records,
        "limit": limit, "offset": offset,
        "verification_scope": verify_scope,
        "all_selected_year_payloads_verified": verify_scope == "selected_years",
        "offpage_derived_memberships_verified": verify_scope == "selected_years",
        "source_records_not_modified": True,
        "visible_match_checksums_verified": True,
        "legacy_records_combined": False,
        "uses_separate_verified_school_index": True,
        "cross_century_school_index_shards": True,
        "shard_count": len(slices),
        "index_paths": [str(path) for _, _, path, _, _ in slices],
        "source_records_fictional": True,
        "index_shards_generated_by_read": False,
        "original_source_data_version_unchanged": True,
        "full_nation_unlimited_years_verified": False,
    }
