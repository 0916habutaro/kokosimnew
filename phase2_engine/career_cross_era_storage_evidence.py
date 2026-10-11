"""Stage43G-69: comparable *evidence categories*, not merged save histories.

Consumes independent Stage43G-67 and Stage43G-68 completed audit JSON
reports. Every number is an observation from the provided report; reports
are NOT a proof that the original SQLite files still exist or are unchanged
since the reports were generated. Source archive validation belongs to
the underlying stages, run before exporting reports.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median


class CareerStorageEvidenceConflict(ValueError):
    """Inconsistent provenance, dimensions, or arithmetic in audit reports."""


def _natural(value: object, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise CareerStorageEvidenceConflict(f"{label} must be an integer >= 0")
    return value


def _size(parts: dict, key: str) -> int:
    if not isinstance(parts, dict):
        raise CareerStorageEvidenceConflict("missing per-year byte components")
    return _natural(parts.get(key), f"component {key}")


def _years(rows: list[dict], name: str, maximum: int | None) -> list[int]:
    if not isinstance(rows, list) or not rows:
        raise CareerStorageEvidenceConflict(f"{name}: no years measured")
    years = [r.get("year") for r in rows]
    if (any(type(y) is not int or y <= 0 for y in years)
            or years != sorted(set(years))
            or (maximum is not None and max(years) > maximum)
            or (maximum is None and min(years) <= 9999)):
        raise CareerStorageEvidenceConflict(
            f"{name}: duplicate, nonascending, or wrong-era years"
        )
    return years


def _legacy(report: dict) -> dict:
    if type(report) is not dict or report.get("stage") != "43G-67":
        raise CareerStorageEvidenceConflict("requires Stage43G-67 legacy A report")
    generated = report.get("audit_kind") == (
        "synthetic_complete_a_archive_not_tournament_simulation"
    )
    existing = report.get("audit_kind") == (
        "existing_retained_a_archive_explicit_full_scan"
    )
    if not (generated or existing):
        raise CareerStorageEvidenceConflict("unknown legacy audit provenance")
    if (report.get("official_game_results") is not False
            or report.get("full_3000_school_100_year_gameplay_verified") is not False
            or report.get("v2_year_10000_included") is not False):
        raise CareerStorageEvidenceConflict("legacy source claims unauthorized results")
    annual = (report["per_year_logical_growth"] if generated
              else report["annual"])
    storage = report["full_a_storage"] if generated else report["storage"]
    if not (report.get("read_only_pass_preserved_file_hashes") is True
            if generated else
            report.get("all_three_source_file_hashes_unchanged") is True):
        raise CareerStorageEvidenceConflict("legacy archive read-only proof absent")
    if (annual.get("exact_original_record_sha256_checked") is not True
            or annual.get("school_year_cache_ledger_metadata_checked") is not True
            or storage.get("saved_data_not_modified") is not True):
        raise CareerStorageEvidenceConflict("legacy A row integrity proof absent")
    rows = annual["annual_rows"]
    years = _years(rows, "legacy", 9999)
    if (annual.get("years_profiled") != len(rows)
            or annual.get("sealed_year_count") != len(rows)
            or annual.get("active_year_count") != 0
            or storage.get("match_record_shapes") != {
                "full_a": storage.get("archived_match_count")
            }):
        raise CareerStorageEvidenceConflict(
            "legacy comparison needs complete sealed Option-A records"
        )
    sums = {
        "match": 0, "roster": 0, "cached_player": 0,
        "new_player_identity": 0,
    }
    total_matches = total_rosters = player_rows = 0
    for entry in rows:
        parts = entry["logical_payload_bytes"]
        counts = entry["record_counts"]
        components = {
            "match": _size(parts, "match_payload"),
            "roster": _size(parts, "school_roster_payload"),
            "cached_player": _size(parts, "derived_player_year_payload"),
            "new_player_identity": _size(parts, "new_player_identity_payload"),
        }
        if sum(components.values()) != entry["annual_logical_payload_total_bytes"]:
            raise CareerStorageEvidenceConflict("legacy annual byte sums differ")
        for key, value in components.items():
            sums[key] += value
        total_matches += _natural(counts.get("matches"), "legacy matches")
        total_rosters += _natural(counts.get("school_rosters"), "legacy rosters")
        player_rows += _natural(
            counts.get("derived_player_years"), "legacy player-year rows"
        )
        if entry.get("status") != "sealed":
            raise CareerStorageEvidenceConflict("legacy year not sealed")
    if (sum(sums.values()) != annual["cumulative_logical_payload_total_bytes"]
            or storage["archived_match_count"] != total_matches
            or sum(_natural(x["file_bytes"], "legacy sqlite file bytes")
                   for x in storage["sqlite_files"].values())
            != storage["sqlite_total_bytes"]):
        raise CareerStorageEvidenceConflict("legacy observed totals differ")
    if generated:
        if (report.get("complete_a_matches_verified") != total_matches
                or report.get("cached_player_years") != player_rows
                or report.get("cached_stats_match_raw_stats_for_sampled_players")
                is not True):
            raise CareerStorageEvidenceConflict("legacy generated coverage differs")
    return {
        "kind": report["audit_kind"], "years": years,
        "matches": total_matches, "rosters": total_rosters,
        "cached_player_years": player_rows,
        "bytes": sums, "logical_total": sum(sums.values()),
        "sqlite_total": storage["sqlite_total_bytes"],
        "physical_files": len(storage["sqlite_files"]),
        "read_provenance": (
            "legacy raw and derived cache samples"
            if generated else "legacy full-scan original source and cache rows"
        ),
    }


def _v2(report: dict) -> dict:
    if (type(report) is not dict or report.get("stage") != "43G-68"
            or report.get("audit_kind") !=
            "selected_sealed_fictional_v2_complete_A_deep_read_only"
            or report.get("all_selected_years_original_match_and_cache_deep_verified")
            is not True
            or report.get("all_saved_files_sha256_unchanged") is not True
            or report.get("original_legacy_stats_never_combined") is not True
            or report.get("read_only") is not True
            or report.get("complete_career_progression_to_10000_verified") is not False
            or report.get("full_nation_or_official_tournament_results_verified")
            is not False):
        raise CareerStorageEvidenceConflict("v2 complete source proof absent")
    rows = report["year_rows"]
    years = _years(rows, "v2", None)
    if (report["selected_years"] != years
            or report["selected_year_count"] != len(years)
            or len(years) > 12):
        raise CareerStorageEvidenceConflict("v2 requested year list differs")
    sums = {"match": 0, "roster": 0, "cached_player": 0}
    total_matches = total_rosters = player_rows = 0
    for row in rows:
        parts = row["exact_json_payload_bytes"]
        components = {
            "match": _size(parts, "match_payload"),
            "roster": _size(parts, "roster_payload"),
            "cached_player": _size(parts, "cached_player_year_payload"),
        }
        if (row.get("source_sealed_and_calendar_sha_verified") is not True
                or row.get("logical_day_kind") != "G{year}:MM-DD"
                or sum(components.values()) != row["annual_logical_json_bytes"]):
            raise CareerStorageEvidenceConflict("v2 source annual totals differ")
        for key, value in components.items():
            sums[key] += value
        total_matches += _natural(row.get("match_count"), "v2 matches")
        total_rosters += _natural(row.get("school_roster_count"), "v2 rosters")
        player_rows += _natural(
            row.get("v2_cached_player_year_rows"), "v2 player-year rows"
        )
        schools = row.get("cached_school_deep_read")
        if (type(schools) is not dict
                or len(schools) != row.get("v2_cached_school_count")):
            raise CareerStorageEvidenceConflict("v2 deep cache coverage missing")
        for school in schools.values():
            if (_natural(school.get("verified_players"), "verified players") < 0
                    or not isinstance(school.get("elapsed_ms"), (int, float))
                    or school["elapsed_ms"] < 0
                    or _natural(school.get("peak_traced_python_bytes"),
                                "v2 peak memory") < 0):
                raise CareerStorageEvidenceConflict("v2 measured deep read invalid")
        if (type(row.get("source_match_full_scan")) is not dict
                or not isinstance(
                    row["source_match_full_scan"].get("elapsed_ms"), (int, float)
                ) or row["source_match_full_scan"]["elapsed_ms"] < 0):
            raise CareerStorageEvidenceConflict("v2 source scan metric absent")
    if (sum(sums.values()) != report["selected_json_bytes_total"]
            or sum(_natural(v.get("file_bytes"), "v2 sqlite file bytes")
                   for v in report["sqlite_files"].values())
            != report["total_v2_roster_cache_calendar_sqlite_file_bytes"]):
        raise CareerStorageEvidenceConflict("v2 selected totals differ")
    return {
        "kind": report["audit_kind"], "years": years,
        "matches": total_matches, "rosters": total_rosters,
        "cached_player_years": player_rows,
        "bytes": sums, "logical_total": sum(sums.values()),
        "sqlite_total":
            report["total_v2_roster_cache_calendar_sqlite_file_bytes"],
        "physical_files": len(report["sqlite_files"]),
        "read_provenance": "v2 deep source and per-school cache revalidation",
    }


def _per_unit(count: int, bytes_total: int) -> float | None:
    return round(bytes_total / count, 2) if count else None


def compare_independent_a_audits(legacy: dict, v2: dict) -> dict:
    """Compare byte accounting of validated reports; do not combine seasons."""
    old = _legacy(legacy)
    future = _v2(v2)
    if set(old["years"]) & set(future["years"]):
        raise CareerStorageEvidenceConflict("legacy and v2 years collide")
    output = {}
    for key, observed in (("legacy", old), ("v2", future)):
        values = observed["bytes"]
        output[key] = {
            "audit_provenance": observed["kind"],
            "year_range": {
                "first": observed["years"][0],
                "last": observed["years"][-1],
            },
            "sampled_years": len(observed["years"]),
            "exact_saved_match_count": observed["matches"],
            "saved_school_year_roster_count": observed["rosters"],
            "saved_cached_player_year_count": observed["cached_player_years"],
            "measured_json_bytes": values,
            "measured_json_bytes_total": observed["logical_total"],
            "observed_match_json_bytes_per_saved_match":
                _per_unit(observed["matches"], values["match"]),
            "observed_roster_json_bytes_per_saved_school_year":
                _per_unit(observed["rosters"], values["roster"]),
            "observed_derived_cache_json_bytes_per_player_year":
                _per_unit(observed["cached_player_years"],
                          values["cached_player"]),
            "whole_sqlite_files_bytes": observed["sqlite_total"],
            "whole_sqlite_files_count": observed["physical_files"],
            "read_validation_kind": observed["read_provenance"],
        }
    return {
        "stage": "43G-69",
        "contract": "two_independent_retained_option_a_evidence_reports_v1",
        "legacy": output["legacy"],
        "fictional_v2": output["v2"],
        "safe_to_compare": [
            "within-each-source-match-payload-bytes-per-record",
            "within-each-source-roster-json-bytes-per-saved-school-year",
            "within-each-source-derived-stat-json-bytes-per-player-year",
        ],
        "do_not_compare_or_infer": [
            "overall-physical-sqlite-bytes-as-format-savings",
            "physical-bytes-per-year-as-full-save-forecast",
            "unlike-depth-performance-times-as-speed-ranking",
            "year-2026-and-year-10000-as-contiguous-gameplay",
            "combined-game-seasons-player-careers-or-tournament-outcomes",
            "nationwide-3000-school-50-or-100-year-runtime-proven",
        ],
        "source_formats_have_different_schema_and_file_counts": True,
        "source_match_counts_may_differ": (
            old["matches"] != future["matches"]
        ),
        "derived_cache_and_match_read_depths_differ": True,
        "aggregated_career_statistics_authorized": False,
        "physical_file_storage_savings_claimed": False,
        "historical_tournament_progression_proven": False,
        "evidence_is_stored_report_not_reinspection_of_live_sqlite": True,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Compare independent Stage43G-67/68 JSON audit evidence "
                    "without merging source years or inferring storage savings",
    )
    p.add_argument("--legacy-report", required=True, type=Path)
    p.add_argument("--v2-report", required=True, type=Path)
    p.add_argument("--output-json", type=Path)
    a = p.parse_args()
    if (a.legacy_report.resolve() == a.v2_report.resolve()
            or a.output_json is not None
            and a.output_json.resolve() in {
                a.legacy_report.resolve(), a.v2_report.resolve()
            }):
        p.error("comparison cannot overwrite or reuse input report paths")
    legacy = json.loads(a.legacy_report.read_text(encoding="utf-8"))
    v2 = json.loads(a.v2_report.read_text(encoding="utf-8"))
    result = compare_independent_a_audits(legacy, v2)
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if a.output_json is not None:
        a.output_json.parent.mkdir(parents=True, exist_ok=True)
        a.output_json.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
