"""Stage43G-24: non-mutating long-career year and calendar boundary contract.

Game years are durable positive INTEGER keys; Gregorian YYYY-MM-DD remains a
separate date type. This module provides *preflight diagnostics only*.
It does not rebind the actual competition schedule, change existing save
schemas, or authorize playing beyond the calendar implemented in the runtime.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3

from .career_option_a_storage_profile import _read_only
from .historical_match_archive import HistoricalMatchArchive

CAREER_START_YEAR = 2026
MAX_GREGORIAN_YEAR = 9999
MAX_SQLITE_YEAR = (1 << 63) - 1
CALENDAR_TEMPLATE_YEAR = 2026
CONTRACT_ID = "career_era_calendar_preflight_v1"


class CareerEraBoundaryConflict(ValueError):
    """The existing archive state, template or date is not safe to advance."""


def _year(year: int) -> None:
    if type(year) is not int or not 1 <= year <= MAX_SQLITE_YEAR:
        raise ValueError("game year must be a positive SQLite 64-bit integer")


def career_coordinate(game_year: int, *,
                      initial_year: int = CAREER_START_YEAR) -> dict:
    """A non-ambiguous durable coordinate, independent of datetime support."""
    _year(game_year)
    _year(initial_year)
    if game_year < initial_year:
        raise ValueError("game year is before start of this career")
    return {
        "contract_id": CONTRACT_ID,
        "initial_game_year": initial_year,
        "game_year": game_year,
        "career_year_index": game_year - initial_year,
        "game_year_display": str(game_year),
        "gregorian_iso_year_supported": game_year <= MAX_GREGORIAN_YEAR,
        "calendar_binding": (
            "gregorian_date_possible_but_not_schedule_certified"
            if game_year <= MAX_GREGORIAN_YEAR
            else "requires_new_calendar_date_representation"
        ),
        "official_schedule_inferred": False,
    }


def calendar_day_preflight(
    game_year: int, month: int, day: int,
    *, template_year: int = CALENDAR_TEMPLATE_YEAR,
) -> dict:
    """Inspect a future month/day without claiming that it is scheduled.

    Dates through 9999 are Gregorian candidates, not approved game fixtures.
    Beyond year 9999 a stable non-date token is returned for *planning only*.
    Leap-day templates cannot repeat without an explicit leap-year policy.
    """
    _year(game_year)
    if (type(month) is not int or type(day) is not int
            or type(template_year) is not int
            or not 1 <= template_year <= MAX_GREGORIAN_YEAR):
        raise ValueError("invalid calendar template or month/day")
    try:
        date(template_year, month, day)
    except ValueError as exc:
        raise CareerEraBoundaryConflict(
            "invalid month/day in calendar template"
        ) from exc
    if game_year <= MAX_GREGORIAN_YEAR:
        try:
            projected = date(game_year, month, day).isoformat()
        except ValueError as exc:
            raise CareerEraBoundaryConflict(
                "target year requires an explicit leap-day schedule policy"
            ) from exc
    else:
        if (month, day) == (2, 29):
            raise CareerEraBoundaryConflict(
                "leap-day calendar mapping beyond 9999 is unspecified"
            )
        projected = None
    return {
        "contract_id": CONTRACT_ID,
        "game_year": game_year,
        "template_year": template_year,
        "template_day": f"{month:02d}-{day:02d}",
        "gregorian_candidate_date": projected,
        "logical_day_token": f"G{game_year}:{month:02d}-{day:02d}",
        "is_game_schedule_approved": False,
        "competition_dates_generated": False,
        "master_season_calendar_recurrence_approved": False,
        "day_token_is_not_iso_date": True,
    }


def next_year_preflight(
    archive_path: str | Path, *, requested_year: int,
) -> dict:
    """Read-only check for adjacent sealed-year rollover.

    A passing archive preflight is *not* permission to generate actual future
    tournaments or reuse 2026's school branches/competition dates. The game
    runtime must separately supply a verified next-year calendar+teams plan.
    """
    _year(requested_year)
    path = Path(archive_path)
    if not path.is_file():
        raise FileNotFoundError("career archive must already exist")
    try:
        with closing(_read_only(path)) as conn:
            rows = conn.execute(
                "SELECT year,status,match_count,ledger_sha256 "
                "FROM career_years ORDER BY year"
            ).fetchall()
            if not rows:
                raise CareerEraBoundaryConflict("no registered career year")
            previous = None
            for year, status, _, _ in rows:
                if (previous is not None and year != previous + 1):
                    raise CareerEraBoundaryConflict(
                        "nonadjacent saved career years"
                    )
                if status not in ("sealed", "active"):
                    raise CareerEraBoundaryConflict("invalid saved year state")
                previous = year
            latest_year, status, match_count, ledger = rows[-1]
            # For a sealed most-recent year, also check that its *record digest
            # ledger* still agrees with its stored source metadata. Original
            # match payload bytes remain a separate deeper integrity audit.
            ledger_verified = False
            if status == "sealed":
                count_now, digest_now = HistoricalMatchArchive._ledger(
                    conn, latest_year
                )
                if (count_now != match_count or digest_now != ledger):
                    raise CareerEraBoundaryConflict(
                        "sealed previous year ledger changed"
                    )
                ledger_verified = True
    except sqlite3.DatabaseError as exc:
        raise CareerEraBoundaryConflict(
            "saved career ledger unavailable"
        ) from exc

    already_saved = requested_year <= latest_year
    archive_ready = (
        requested_year == latest_year + 1
        and status == "sealed"
    )
    return {
        "contract_id": CONTRACT_ID,
        "requested_year": requested_year,
        "current_latest_saved_year": latest_year,
        "current_latest_status": status,
        "existing_year_count": len(rows),
        "already_registered_or_historical": already_saved,
        "next_year_is_adjacent": requested_year == latest_year + 1,
        "previous_year_source_ledger_checked": ledger_verified,
        "archive_year_registration_preflight_ok": archive_ready,
        "calendar_yyyy_supported": requested_year <= MAX_GREGORIAN_YEAR,
        "future_calendar_rule_verified": False,
        "runtime_season_start_authorized": False,
        "recorded_save_modified": False,
        "decision": (
            "already_registered_or_past_year" if already_saved
            else "blocked_nonadjacent_year"
            if requested_year != latest_year + 1
            else "blocked_unsealed_previous_year"
            if status != "sealed"
            else "archive_only_calendar_boundary_unresolved"
            if requested_year > MAX_GREGORIAN_YEAR
            else "archive_only_requires_validated_new_season_plan"
        ),
    }


def main() -> None:
    """Read an existing archive boundary without changing the save."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Dry-run career rollover and calendar year preflight"
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--requested-year", type=int, required=True)
    parser.add_argument(
        "--initial-year", type=int, default=CAREER_START_YEAR
    )
    parser.add_argument("--month", type=int)
    parser.add_argument("--day", type=int)
    parser.add_argument(
        "--template-year", type=int, default=CALENDAR_TEMPLATE_YEAR
    )
    args = parser.parse_args()
    if (args.month is None) != (args.day is None):
        parser.error("--month and --day must be used together")
    result = {
        "career_coordinate": career_coordinate(
            args.requested_year, initial_year=args.initial_year
        ),
        "rollover": next_year_preflight(
            args.archive, requested_year=args.requested_year,
        ),
    }
    if args.month is not None:
        result["day_mapping"] = calendar_day_preflight(
            args.requested_year, args.month, args.day,
            template_year=args.template_year,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
