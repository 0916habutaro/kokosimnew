"""Stage43G-67: actual A-format match+roster+cache growth/read audit.

Two separate modes:
  1. BOUNDED fictional complete Option-A game/roster/cache generation using
     existing real archival writers and synthetic (never official) results.
  2. Read-only FULL-SCAN inspection of three ALREADY SAVED SQLite files.
Do not confuse these with actual nationwide or unlimited-year gameplay.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
from statistics import median

from .career_annual_growth_audit import profile_annual_growth
from .career_full_a_benchmark import run_full_a_benchmark, validate_options
from .career_history_scale_benchmark import file_sha256
from .career_option_a_storage_profile import profile_option_a_storage


def _annual_summary(annual: dict) -> dict:
    rows = annual["rows"]
    if not rows:
        return {
            "years_profiled": 0, "annual_rows": [], "annual_median_bytes": None,
            "annual_min_bytes": None, "annual_max_bytes": None,
        }
    compact = [{
        "year": row["year"],
        "status": row["source_year_status"],
        "record_counts": row["record_counts"],
        "logical_payload_bytes": row["logical_payload_bytes"],
        "annual_logical_payload_total_bytes":
            row["annual_logical_payload_total_bytes"],
    } for row in rows]
    values = [
        row["annual_logical_payload_total_bytes"]
        for row in rows
    ]
    return {
        "years_profiled": len(rows),
        "sealed_year_count": annual["sealed_year_count"],
        "active_year_count": annual["active_year_count"],
        "annual_rows": compact,
        "annual_median_bytes": median(values),
        "annual_min_bytes": min(values),
        "annual_max_bytes": max(values),
        "cumulative_logical_payload_total_bytes":
            annual["final_logical_payload_total_bytes"],
        "exact_original_record_sha256_checked":
            annual["record_sha256_checked"],
        "school_year_cache_ledger_metadata_checked":
            annual["school_year_cache_ledger_metadata_checked"],
        "source_match_ledger_fully_recomputed":
            annual["source_match_ledger_fully_recomputed"],
        "school_year_cache_fact_sha_fully_recomputed":
            annual["school_year_cache_fact_sha_fully_recomputed"],
    }


def _storage_summary(storage: dict) -> dict:
    return {
        "archived_match_count": storage["archived_match_count"],
        "match_record_shapes": storage["match_record_shapes"],
        "payload_min_bytes": storage["payload_min_bytes"],
        "payload_median_bytes": storage["payload_median_bytes"],
        "payload_max_bytes": storage["payload_max_bytes"],
        "payload_bytes": storage["payload_bytes"],
        "sqlite_files": {
            key: {
                "file_bytes": row["file_bytes"],
                "page_count": row["page_count"],
                "freelist_count": row["freelist_count"],
            }
            for key, row in storage["sqlite_files"].items()
        },
        "sqlite_total_bytes": storage["sqlite_total_bytes"],
        "gzip_sample_hypothetical_only":
            storage["gzip_sample"]["hypothetical_only_not_applied_to_save"],
        "saved_data_not_modified": storage["source_payloads_not_modified"],
    }


def run_long_full_a_audit(data_root: str | Path, *,
                          schools: int = 2, years: int = 12,
                          games_per_school_year: int = 2,
                          repeats: int = 1,
                          allow_large: bool = False) -> dict:
    """Generate, seal, audit, read and REMOVE a temporary complete A save."""
    validate_options(
        schools, years, games_per_school_year, repeats, allow_large,
    )
    full = run_full_a_benchmark(
        data_root, schools=schools, years=years,
        games_per_school_year=games_per_school_year, repeats=repeats,
        allow_large=allow_large,
    )
    actual = full["counts"]
    if (actual["matches"] != full["expected_matches"]
            or actual["full_option_a_matches"] != actual["matches"]
            or actual["school_year_rosters"] != schools * years
            or actual["cached_school_years"] != schools * years
            or full["annual_growth"]["sealed_year_count"] != years
            or len(full["annual_physical_snapshots"]) != years
            or not full["all_db_hashes_unchanged_on_read"]
            or not full["temporary_fixture_deleted_after_run"]
            or not full["school_index_plans"]["all_expected_indexes_selected"]):
        raise AssertionError("retained full-A long-term audit coverage differs")
    physical = full["annual_physical_snapshots"]
    snapshots = [{
        "year": r["year"],
        "physical_total_sqlite_file_bytes": r["allocated_total_file_bytes"],
        "physical_total_delta_since_prior_year_bytes":
            r["allocated_total_delta_bytes"],
    } for r in physical]
    if physical[-1]["allocated_total_file_bytes"] != (
            full["total_database_bytes"]):
        raise AssertionError("final physical SQLite allocation differs")
    if full["storage_profile"]["match_record_shapes"] != {
        "full_a": actual["matches"]
    }:
        raise AssertionError("non-Option-A match in generated fixture")
    return {
        "stage": "43G-67",
        "audit_kind": "synthetic_complete_a_archive_not_tournament_simulation",
        "schools_with_real_generated_rosters": schools,
        "years_with_adjacent_generated_rosters": years,
        "fictional_matches_archived": actual["matches"],
        "complete_a_matches_verified": actual["full_option_a_matches"],
        "cached_school_years": actual["cached_school_years"],
        "cached_player_years": actual["cached_player_years"],
        "per_year_logical_growth": _annual_summary(full["annual_growth"]),
        "physical_save_growth_measured_each_year": snapshots,
        "full_a_storage": _storage_summary(full["storage_profile"]),
        "total_actual_sqlite_bytes": full["total_database_bytes"],
        "permanent_school_index_plans_verified": True,
        "sampled_raw_and_cached_statistics": full["reads"],
        "cached_stats_match_raw_stats_for_sampled_players": all(
            r["cached_matches_raw"] for r in full["reads"]
        ),
        "snapshot_byte_sizes_not_linear_capacity_projections": True,
        "raw_match_ledger_and_cache_fact_not_fully_reverified_by_growth_report": True,
        "temporary_files_deleted_after_audit": True,
        "read_only_pass_preserved_file_hashes": True,
        "full_3000_school_100_year_gameplay_verified": False,
        "official_game_results": False,
        "v2_year_10000_included": False,
    }


def inspect_existing_full_a_files(matches: str | Path,
                                  rosters: str | Path,
                                  derived_cache: str | Path) -> dict:
    """Expensive explicit full scan of existing source+derived SQLite data.

    No materialization, index creation or writing is done. Every stored A
    record and other stored JSON passes its own digest; source ledger is
    checked as metadata, not reconstructed. This is an audit, not the
    paginated path used when a GUI opens a single saved match.
    """
    paths = {
        "matches": Path(matches),
        "rosters": Path(rosters),
        "derived_cache": Path(derived_cache),
    }
    if len({p.resolve() for p in paths.values()}) != 3:
        raise ValueError("source matches, rosters and derived cache must differ")
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(f"saved A audit file is absent: {path}")
    before = {name: file_sha256(p) for name, p in paths.items()}
    growth = profile_annual_growth(*paths.values())
    storage = profile_option_a_storage(
        *paths.values(), gzip_sample_limit=0,
    )
    after = {name: file_sha256(p) for name, p in paths.items()}
    if before != after:
        raise AssertionError("archived A audit altered saved files")
    return {
        "stage": "43G-67",
        "audit_kind": "existing_retained_a_archive_explicit_full_scan",
        "annual": _annual_summary(growth),
        "storage": _storage_summary(storage),
        "all_three_source_file_hashes_unchanged": True,
        "created_materialized_statistics": False,
        "source_match_ledger_fully_recomputed": False,
        "school_year_cache_fact_sha_fully_recomputed": False,
        "full_3000_school_100_year_gameplay_verified": False,
        "official_game_results": False,
        "v2_year_10000_included": False,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Read-only existing A storage audit or disposable "
                    "synthetic long-year full Option-A fixture"
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--synthetic-data-root", type=Path)
    mode.add_argument("--inspect-matches", type=Path)
    p.add_argument("--rosters", type=Path)
    p.add_argument("--derived-cache", type=Path)
    p.add_argument("--schools", type=int, default=2)
    p.add_argument("--years", type=int, default=12)
    p.add_argument("--games-per-school-year", type=int, default=2)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--allow-large", action="store_true")
    args = p.parse_args()
    if args.inspect_matches is not None:
        if args.rosters is None or args.derived_cache is None:
            p.error("--inspect-matches requires --rosters and --derived-cache")
        data = inspect_existing_full_a_files(
            args.inspect_matches, args.rosters, args.derived_cache,
        )
    else:
        if args.rosters is not None or args.derived_cache is not None:
            p.error("saved file paths require --inspect-matches")
        data = run_long_full_a_audit(
            args.synthetic_data_root, schools=args.schools,
            years=args.years, games_per_school_year=args.games_per_school_year,
            repeats=args.repeats, allow_large=args.allow_large,
        )
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
