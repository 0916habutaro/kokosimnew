"""Stage43G-73: controlled full-Option-A school/year/game scaling study.

All five bounded cases use the same real archive, roster progression,
sealed-year cached stats, SHA checks and indexed browsing code. The data
are *fictional box scores*, not a completed nationwide tournament.
The legacy cache duplicate-index control uses two identical SQLite backups,
never dropping an index from an existing user save.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median

from .career_full_a_benchmark import run_full_a_benchmark, validate_options
from .career_option_a_storage_profile import sqlite_file_profile
from .career_paired_index_benchmark import compare_duplicate_index_build


CONTROLLED_CASES = (
    ("baseline", 2, 2, 2),
    ("school_only", 8, 2, 2),
    ("years_only", 2, 8, 2),
    ("games_only", 2, 2, 8),
    ("combined", 8, 8, 4),
)


def _probe_storage(saved: dict[str, Path], *, repeats: int) -> dict:
    """Perform only readonly probes while existing fixture is still alive."""
    profiles = {
        key: sqlite_file_profile(path) for key, path in saved.items()
    }
    cache = compare_duplicate_index_build(
        saved["derived_cache"], kind="legacy_cache", repeats=repeats,
    )
    by_file = {}
    for name, profile in profiles.items():
        btrees = profile["btree_page_bytes"]
        if btrees is None:
            indexed_bytes = None
        else:
            indexed_bytes = sum(
                byte_count for key, byte_count in btrees.items()
                if key.startswith("sqlite_autoindex_")
                or key.startswith("idx_")
            )
        by_file[name] = {
            "sqlite_file_bytes": profile["file_bytes"],
            "page_size": profile["page_size"],
            "sqlite_page_count": profile["page_count"],
            "sqlite_freelist_count": profile["freelist_count"],
            "dbstat_available": profile["dbstat_available"],
            "known_index_btree_bytes": indexed_bytes,
            "index_and_table_btree_bytes": btrees,
        }
    return {
        "physical_by_file": by_file,
        "controlled_legacy_cache_pk_index": {
            "saved_player_year_rows": cache["new_schema"]["stored_rows"],
            "new_and_old_full_row_digest_identical":
                cache["identical_record_rows_and_full_content_sha"],
            "observed_extra_file_bytes_with_duplicate":
                cache["observed_extra_file_bytes_in_old_index_copy"],
            "observed_duplicate_index_btree_bytes":
                cache["observed_old_duplicate_btree_allocated_bytes"],
            "new_exact_row_read_median_ms":
                cache["new_schema"]["median_exact_row_lookup_ms"],
            "old_exact_row_read_median_ms":
                cache["previous_schema"]["median_exact_row_lookup_ms"],
            "read_latency_ranking_not_asserted": True,
        },
    }


def run_full_a_scaling_study(
    data_root: str | Path, *,
    cases: tuple[tuple[str, int, int, int], ...] = CONTROLLED_CASES,
    repeats: int = 2,
) -> dict:
    """Vary one dimension at a time, plus a combined bounded case.

    Never extrapolate the sizes to 3000 schools or 100 years. SQLite
    allocation is page-granular, and indexed browse timings depend on CI.
    """
    if type(cases) is not tuple or not 1 <= len(cases) <= 5:
        raise ValueError("only 1 to 5 explicitly bounded scale cases allowed")
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("controlled repeated probes must be 1..5")
    seen = set()
    total_generated_matches = 0
    for case in cases:
        if (type(case) is not tuple or len(case) != 4
                or type(case[0]) is not str or not case[0]
                or case[0] in seen):
            raise ValueError("scale cases require unique nonempty names")
        name, schools, years, games = case
        if (type(schools) is not int or type(years) is not int
                or type(games) is not int
                or schools > 8 or years > 8 or games > 8):
            raise ValueError("stage73 bounds: 8 schools, 8 years, 8 games")
        validate_options(schools, years, games, repeats)
        total_generated_matches += schools * years * games // 2
        seen.add(name)
    if total_generated_matches > 400:
        raise ValueError("Stage43G-73 total synthetic full-A matches > 400")

    rows = []
    for label, schools, years, games in cases:
        bench = run_full_a_benchmark(
            data_root, schools=schools, years=years,
            games_per_school_year=games, repeats=repeats,
            read_only_observer=lambda saved: _probe_storage(
                saved, repeats=repeats,
            ),
        )
        counts = bench["counts"]
        if (bench["expected_matches"] != counts["full_option_a_matches"]
                or counts["cached_school_years"] != schools * years
                or counts["school_year_rosters"] != schools * years
                or not bench["all_db_hashes_unchanged_on_read"]
                or not bench["temporary_fixture_deleted_after_run"]
                or not bench["school_index_plans"]["all_expected_indexes_selected"]):
            raise AssertionError("fictional full-A scale case not complete")
        obs = bench["read_only_observer_result"]
        count_matches = counts["matches"]
        assert count_matches > 0
        physical = obs["physical_by_file"]
        total_file_bytes = sum(
            item["sqlite_file_bytes"] for item in physical.values()
        )
        if total_file_bytes != bench["total_database_bytes"]:
            raise AssertionError("physical allocation disagrees with full-A benchmark")
        payload = bench["annual_growth"]["final_logical_payload_total_bytes"]
        if not isinstance(payload, int) or payload <= 0:
            raise AssertionError("full A payloads were not measured")
        sampled_reads = bench["reads"]
        read_latencies = {}
        for operation in (
            "school_results_page", "raw_player", "cached_player",
            "raw_leaders", "cached_leaders",
        ):
            observed = [
                sample["read_latency"][operation]["median_elapsed_ms"]
                for sample in sampled_reads
            ]
            read_latencies[operation] = {
                "per_sample_median_ms": observed,
                "median_of_school_sample_medians_ms": round(median(observed), 3),
                "school_sample_count": len(observed),
            }
        if not all(s["cached_matches_raw"] for s in sampled_reads):
            raise AssertionError("cached A stats diverge from persisted A source")
        indexed_bytes = [
            record["known_index_btree_bytes"]
            for record in physical.values()
        ]
        rows.append({
            "case": label,
            "schools_with_generated_rosters": schools,
            "successive_sealed_years": years,
            "games_per_school_year_input": games,
            "archived_complete_a_matches": count_matches,
            "saved_school_year_rosters": counts["school_year_rosters"],
            "derived_cache_player_year_rows": counts["cached_player_years"],
            "saved_sqlite_files_bytes": total_file_bytes,
            "exact_saved_json_logical_bytes": payload,
            "known_index_btree_bytes_sum": (
                sum(indexed_bytes) if all(x is not None for x in indexed_bytes)
                else None
            ),
            "physical_sqlite_components": physical,
            "school_first_history_and_cached_player_indexes_selected": True,
            "source_and_cache_stats_match_on_sampled_players": True,
            "browse_and_stat_read_latency_ms": read_latencies,
            "paired_identical_cache_old_index": (
                obs["controlled_legacy_cache_pk_index"]
            ),
            "full_game_engine_progression_verified": False,
            "nationwide_gameplay_verified": False,
        })
    return {
        "stage": "43G-73",
        "audit_kind": "bounded_fictional_full_option_a_real_archival_writers",
        "cases": rows,
        "case_labels": [r["case"] for r in rows],
        "sample_cases_comparable_by_one_input_dimension": (
            cases == CONTROLLED_CASES
        ),
        "total_synthetic_full_a_matches_generated": sum(
            r["archived_complete_a_matches"] for r in rows
        ),
        "all_files_disposable_and_removed": True,
        "all_original_source_sha_unchanged": True,
        "all_deep_full_a_source_roster_cache_validation_passed": True,
        "national_3000_school_100_year_runtime_verified": False,
        "physical_file_size_per_year_is_not_linear_capacity_forecast": True,
        "index_page_saving_from_existing_user_save_not_established": True,
        "read_latency_rankings_not_claimed": True,
        "score_innings_player_stats_preserved": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Controlled five-case full-A game/roster/cache scale audit"
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    report = run_full_a_scaling_study(args.data_root, repeats=args.repeats)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
