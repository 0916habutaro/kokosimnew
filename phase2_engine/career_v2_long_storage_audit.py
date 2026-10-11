"""Stage43G-68: independent fictional-v2 complete-A long-term storage audit.

This is an EXPLICIT, BOUNDED, READ-ONLY full-source inspection, not a
regular GUI page or a season simulation. It does not migrate legacy years,
merge player careers, or infer actual tournament winners.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import argparse
import json
from pathlib import Path
import sqlite3
from statistics import median
from time import perf_counter
import tracemalloc

from .career_calendar_v2 import CareerCalendarV2Archive
from .career_history_scale_benchmark import file_sha256
from .career_option_a_storage_profile import _read_only, sqlite_file_profile
from .career_roster_archive import CareerRosterArchive
from .career_v2_option_a_archive import (
    CareerV2OptionAArchive, _calendar_info, _ledger,
)
from .career_v2_player_stat_cache import CareerV2PlayerStatCache
from .career_v2_roster_attribution import CareerV2RosterAttribution

PARTS = ("match_payload", "roster_payload", "cached_player_year_payload")
MAX_AUDIT_YEARS = 12


def _verified_stored_bytes(conn: sqlite3.Connection, query: str,
                           params: tuple, sha_field: str,
                           name: str) -> tuple[int, int]:
    """Count exact stored UTF-8 bytes and reject every altered row."""
    bytes_total = count = 0
    for raw, digest in conn.execute(query, params):
        if (type(raw) is not str or type(digest) is not str
                or sha256(raw.encode("utf-8")).hexdigest() != digest):
            raise ValueError(f"fictional v2 {name} digest differs")
        bytes_total += len(raw.encode("utf-8"))
        count += 1
    return bytes_total, count


def _timed(call) -> tuple[object, dict]:
    tracemalloc.start()
    start = perf_counter()
    try:
        result = call()
    finally:
        elapsed = round((perf_counter() - start) * 1000, 3)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    return result, {
        "elapsed_ms": elapsed, "peak_traced_python_bytes": peak,
    }


def audit_saved_v2_storage(slot_root: str | Path, years: list[int]) -> dict:
    """Verify at most 12 selected sealed v2 years and four isolated files.

    Match/calendar records, annual school rosters and derived player-stat
    cache are independently immutable. Deep cache verification reconciles
    stored player rows with source A matches and year-specific roster IDs.
    """
    if (type(years) is not list or not 1 <= len(years) <= MAX_AUDIT_YEARS
            or any(type(y) is not int or y <= 9999 for y in years)
            or years != sorted(set(years))):
        raise ValueError("explicit distinct sorted v2 years (up to 12) required")
    root = Path(slot_root)
    files = {
        "v2_matches": root / "fictional_option_a_v2.sqlite3",
        "v2_calendar": root / "sandbox_calendar_v2.sqlite3",
        "school_rosters": root / "career_rosters.sqlite3",
        "v2_player_cache": root / "fictional_v2_player_stat_cache.sqlite3",
    }
    legacy = root / "historical_matches.sqlite3"
    if len({p.resolve() for p in files.values()}) != len(files):
        raise ValueError("v2 source and cache paths must differ")
    if any(not path.is_file() for path in files.values()):
        raise FileNotFoundError("all four saved fictional v2 SQLite files required")
    if legacy.exists() and legacy.resolve() in {p.resolve() for p in files.values()}:
        raise ValueError("legacy archive must remain physically separate")

    measured = {**files}
    if legacy.is_file():
        measured["legacy_matches_unchanged"] = legacy
    before = {k: file_sha256(p) for k, p in measured.items()}
    archive = CareerV2OptionAArchive(
        files["v2_matches"], files["v2_calendar"],
        legacy_archive_path=legacy,
    )
    rosters = CareerRosterArchive(files["school_rosters"])
    attribution = CareerV2RosterAttribution(archive, rosters)
    cache = CareerV2PlayerStatCache(
        attribution, files["v2_player_cache"],
    )
    calendar = CareerCalendarV2Archive(files["v2_calendar"])
    result_rows = []
    for year in years:
        plan, plan_sha = _calendar_info(calendar, year)
        (status, matches), source_time = _timed(
            lambda: archive._verified_year(year, plan, plan_sha),
        )
        if status != "sealed":
            raise ValueError("v2 archive year must be sealed to audit")
        with closing(_read_only(files["v2_matches"])) as conn:
            conn.row_factory = sqlite3.Row
            header = conn.execute(
                "SELECT calendar_sha256,status,match_count,ledger_sha256 "
                "FROM v2_game_years WHERE year=?", (year,),
            ).fetchone()
            count, ledger = _ledger(conn, year)
            match_bytes, match_rows = _verified_stored_bytes(
                conn, "SELECT payload_json,record_sha256 "
                "FROM v2_option_a_matches WHERE year=? "
                "ORDER BY competition_id,match_id",
                (year,), "record_sha256", "source match",
            )
        if (header is None or header["status"] != "sealed"
                or header["calendar_sha256"] != plan_sha
                or (count, ledger) != (
                    header["match_count"], header["ledger_sha256"]
                ) or match_rows != count or len(matches) != count):
            raise ValueError("v2 sealed match count/ledger/calendar differs")

        participants = {
            team for game in matches
            for team in (game["team1_id"], game["team2_id"])
        }
        with closing(_read_only(files["school_rosters"])) as conn:
            conn.row_factory = sqlite3.Row
            annual_rosters = conn.execute(
                "SELECT school_id,payload_json,content_sha256 "
                "FROM career_school_rosters WHERE year=? ORDER BY school_id",
                (year,),
            ).fetchall()
            roster_bytes = 0
            for row in annual_rosters:
                if sha256(row["payload_json"].encode("utf-8")).hexdigest() != (
                    row["content_sha256"]
                ):
                    raise ValueError("v2 annual roster digest differs")
                verified = CareerRosterArchive._get(
                    conn, year, row["school_id"],
                )
                if verified is None or verified.school_id != row["school_id"]:
                    raise ValueError("v2 annual roster identity changed")
                roster_bytes += len(row["payload_json"].encode("utf-8"))
        saved_school_ids = {r["school_id"] for r in annual_rosters}
        if not participants <= saved_school_ids:
            raise ValueError("v2 source match school roster not saved")

        with closing(_read_only(files["v2_player_cache"])) as conn:
            conn.row_factory = sqlite3.Row
            cached_schools = {
                row[0] for row in conn.execute(
                    "SELECT school_id FROM v2_school_year_stat_cache "
                    "WHERE year=?", (year,),
                )
            }
            cache_bytes, cached_row_count = _verified_stored_bytes(
                conn, "SELECT payload_json,payload_sha256 "
                "FROM v2_player_year_stat_cache WHERE year=? "
                "ORDER BY school_id,player_id",
                (year,), "payload_sha256", "player cache",
            )
        # An actual recorded match needs both teams' individual totals in
        # the independently stored v2 cache; fail closed on missing extras.
        if cached_schools != participants:
            raise ValueError("v2 cache school coverage differs from matches")
        deep_year_reads = {}
        for school_id in sorted(cached_schools):
            data, elapsed = _timed(
                lambda sid=school_id: cache.read_year(
                    year, sid, verify_source=True,
                ),
            )
            if (not data["source_payloads_rechecked_on_read"]
                    or data["team_match_count"] != sum(
                        school_id in (x["team1_id"], x["team2_id"])
                        for x in matches
                    )):
                raise ValueError("v2 school full-A/cache read differs")
            deep_year_reads[school_id] = {
                "verified_players": data["player_count"],
                **elapsed,
            }
        parts = {
            "match_payload": match_bytes,
            "roster_payload": roster_bytes,
            "cached_player_year_payload": cache_bytes,
        }
        result_rows.append({
            "year": year, "logical_day_kind": "G{year}:MM-DD",
            "source_sealed_and_calendar_sha_verified": True,
            "match_count": count,
            "school_roster_count": len(annual_rosters),
            "v2_cached_school_count": len(cached_schools),
            "v2_cached_player_year_rows": cached_row_count,
            "exact_json_payload_bytes": parts,
            "annual_logical_json_bytes": sum(parts.values()),
            "source_match_full_scan": source_time,
            "cached_school_deep_read": deep_year_reads,
        })
    after = {k: file_sha256(p) for k, p in measured.items()}
    if before != after:
        raise AssertionError("read-only v2 audit modified a saved SQLite file")
    sizes = {
        k: sqlite_file_profile(path)
        for k, path in files.items()
    }
    values = [row["annual_logical_json_bytes"] for row in result_rows]
    return {
        "stage": "43G-68",
        "audit_kind": "selected_sealed_fictional_v2_complete_A_deep_read_only",
        "selected_years": years,
        "selected_year_count": len(years),
        "year_rows": result_rows,
        "yearly_json_bytes_median": median(values),
        "selected_json_bytes_total": sum(values),
        "sqlite_files": {
            name: {
                "file_bytes": entry["file_bytes"],
                "page_count": entry["page_count"],
            } for name, entry in sizes.items()
        },
        "total_v2_roster_cache_calendar_sqlite_file_bytes": sum(
            row["file_bytes"] for row in sizes.values()
        ),
        "physical_file_size_not_attributable_to_selected_years": True,
        "shared_player_identity_rows_not_attributed_to_a_specific_year": True,
        "all_selected_years_original_match_and_cache_deep_verified": True,
        "all_saved_files_sha256_unchanged": True,
        "legacy_archive_unchanged_if_present": True,
        "original_legacy_stats_never_combined": True,
        "complete_career_progression_to_10000_verified": False,
        "full_nation_or_official_tournament_results_verified": False,
        "all_other_saved_years_outside_selection_verified": False,
        "read_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only bounded deep storage audit of fictional v2 A saves",
    )
    parser.add_argument("--slot", required=True, type=Path)
    parser.add_argument(
        "--years", required=True, help="comma-separated exact v2 game years",
    )
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    try:
        selected = [int(v) for v in args.years.split(",")]
    except ValueError:
        parser.error("--years expects comma-separated integers")
    result = audit_saved_v2_storage(args.slot, selected)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
