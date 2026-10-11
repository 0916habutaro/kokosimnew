"""Stage43G-60: bounded, source-separated saved year discovery.

This is a header-only index for the legacy ISO archive and the independent
fictional v2 logical calendar. Listing a year does NOT verify its records:
opening that year explicitly goes through the full cross-era read gate.

Never migrate original A games or unify ISO and G{year}:MM-DD day tokens.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .career_cross_era_navigation import CareerCrossEraNavigator, MAX_SELECTED_YEARS
from .career_option_a_storage_profile import _read_only
from .career_era_calendar_contract import MAX_GREGORIAN_YEAR

LEGACY = "historical_matches_legacy_iso"
FUTURE = "fictional_option_a_v2"
SOURCES = (
    ("historical_matches.sqlite3", "career_years", LEGACY, "YYYY-MM-DD"),
    ("fictional_option_a_v2.sqlite3", "v2_game_years", FUTURE, "G{year}:MM-DD"),
)


class CareerCrossEraYearCatalogConflict(ValueError):
    """Invalid year selection or incompatible source metadata."""


class CareerCrossEraYearCatalog:
    """Read-only catalog over TWO independent sources, never an A migration."""

    def __init__(self, slot_root: str | Path):
        self.slot_root = Path(slot_root)
        self.navigator = CareerCrossEraNavigator(self.slot_root)

    def _source_years(self, name: str, table: str, source: str,
                      date_kind: str, bound: int, *,
                      before_year: int | None = None) -> list[dict]:
        path = self.slot_root / name
        if not path.is_file():
            return []
        try:
            with closing(_read_only(path)) as conn:
                # Both career_years.year and v2_game_years.year are
                # INTEGER PRIMARY KEY; a seek cursor does not pay an OFFSET
                # cost proportional to saved career years.
                if before_year is None:
                    rows = conn.execute(
                        f"SELECT year FROM {table} WHERE status='sealed' "
                        "ORDER BY year DESC LIMIT ?", (bound,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"SELECT year FROM {table} WHERE status='sealed' "
                        "AND year<? ORDER BY year DESC LIMIT ?",
                        (before_year, bound),
                    ).fetchall()
        except (OSError, sqlite3.DatabaseError) as exc:
            raise CareerCrossEraYearCatalogConflict(
                "saved year catalog archive unreadable"
            ) from exc
        records = []
        for (year,) in rows:
            if (type(year) is not int or year < 1
                    or (source == LEGACY and year > MAX_GREGORIAN_YEAR)
                    or (source == FUTURE and year <= MAX_GREGORIAN_YEAR)):
                raise CareerCrossEraYearCatalogConflict(
                    "saved calendar era and year metadata differ"
                )
            records.append({
                "year": year, "source": source, "date_kind": date_kind,
                # A sealed header may itself be corrupted; only select() below
                # verifies the match ledger and per-record checksums.
                "header_state": "sealed_header_unverified",
                "source_verified": False,
            })
        return records

    def page(self, *, limit: int = 24, offset: int = 0) -> dict:
        if (type(limit) is not int or not 1 <= limit <= MAX_SELECTED_YEARS
                or type(offset) is not int or offset < 0):
            raise CareerCrossEraYearCatalogConflict(
                "invalid bounded saved-year catalog page"
            )
        # At most offset + limit + 1 years from EACH separate SQLite source.
        # Do not read every match or copy DBs; no source uses ATTACH.
        bound = offset + limit + 1
        rows = []
        for name, table, source, date_kind in SOURCES:
            rows.extend(self._source_years(
                name, table, source, date_kind, bound,
            ))
        rows.sort(key=lambda x: x["year"], reverse=True)
        years = [x["year"] for x in rows]
        if len(years) != len(set(years)):
            raise CareerCrossEraYearCatalogConflict(
                "two archives have overlapping saved years"
            )
        window = rows[offset:offset + limit]
        return {
            "screen": "cross_era_year_catalog",
            "years": window,
            "offset": offset, "limit": limit,
            "has_older": len(rows) > offset + limit,
            "year_count_is_exhaustive": False,
            "source_headers_only_not_record_verification": True,
            "combined_date_index_authorized": False,
            "combined_career_stats_authorized": False,
            "official_future_results": False,
            "read_only": True,
        }

    def page_after(self, *, before_year: int | None = None,
                   limit: int = 24) -> dict:
        """Seek the next older bounded set without scanning earlier pages.

        A cursor is an exclusive saved-year boundary (not a trusted ledger).
        Each page lists UNVERIFIED sealed headers only. select_school()
        remains the mandatory deep-verification step before showing records.
        """
        if (type(limit) is not int or not 1 <= limit <= MAX_SELECTED_YEARS
                or (before_year is not None and (
                    type(before_year) is not int or before_year < 1
                ))):
            raise CareerCrossEraYearCatalogConflict(
                "invalid keyset saved-year catalog request"
            )
        rows = []
        for name, table, source, date_kind in SOURCES:
            rows.extend(self._source_years(
                name, table, source, date_kind,
                limit + 1, before_year=before_year,
            ))
        rows.sort(key=lambda row: row["year"], reverse=True)
        years = [row["year"] for row in rows]
        if len(years) != len(set(years)):
            raise CareerCrossEraYearCatalogConflict(
                "two archives have overlapping saved years"
            )
        window = rows[:limit]
        older = len(rows) > limit
        return {
            "screen": "cross_era_year_catalog",
            "years": window,
            "limit": limit,
            "cursor_before_year": before_year,
            "next_cursor_before_year": (
                window[-1]["year"] if older else None
            ),
            "has_older": older,
            "index_kind": "sqlite_year_primary_key_seek",
            "year_count_is_exhaustive": False,
            "source_headers_only_not_record_verification": True,
            "combined_date_index_authorized": False,
            "combined_career_stats_authorized": False,
            "official_future_results": False,
            "read_only": True,
        }

    def select_school(self, year: int, school_id: str, *,
                      limit: int = 30, offset: int = 0) -> dict:
        """One selected sealed year routes into existing verified navigator.

        A cross-era selection never implies intervening years were played.
        """
        if (type(year) is not int or year < 1
                or type(school_id) is not str or not school_id):
            raise CareerCrossEraYearCatalogConflict(
                "saved year and permanent school ID required"
            )
        # Source gate verifies year uniqueness/era, sealed ledger, A payloads
        # and calendar source before any match page is made visible.
        page = self.navigator.school_page(
            [year], school_id, selected_year=year,
            limit=limit, offset=offset, verify_source=True,
        )
        return {
            **page,
            "selected_from_bounded_year_catalog": True,
            "combined_date_index_authorized": False,
            "combined_career_stats_authorized": False,
            "official_future_results": False,
        }
