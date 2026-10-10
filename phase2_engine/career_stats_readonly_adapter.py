"""Stage43G-17: optional, strictly read-only GUI access to sealed stats cache.

The builder in career_player_stat_cache is intentionally NOT exposed here.
Incomplete/missing derived data may fall back to the A-history source.
A present but inconsistent cache must never be accepted as valid history.
"""
from __future__ import annotations

from contextlib import closing
import sqlite3

from .career_player_stat_cache import (
    CareerPlayerStatCache, CareerStatsCacheConflict,
)


def _read_only(path):
    """Open an existing SQLite file without permission to create or update it."""
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


class CareerStatsReadOnlyAdapter(CareerPlayerStatCache):
    """Reuse Stage43G-15 integrity/rollup checks but never initialize a DB."""

    def _connection(self):
        if not self.path.is_file():
            raise CareerStatsCacheConflict("derived cache not available")
        return closing(_read_only(self.path))

    def materialize(self, *args, **kwargs):
        raise PermissionError("history GUI cannot materialize derived stats")

    def _coverage(self, conn, school, start, end, *, verify_source):
        if verify_source:
            raise PermissionError("read-only cache cannot rebuild source verification")
        return super()._coverage(
            conn, school, start, end, verify_source=False
        )

    def ready(self, school_id: str, *, start_year: int, end_year: int) -> bool:
        """Choose cache only for complete sealed years with matching ledger.

        Return False when the cache is absent, incomplete, or any requested
        year is active. If a cached sealed year's ledger is inconsistent,
        reject rather than silently falling back to raw and hiding corruption.
        The full row/checksum coverage is verified again by the read method.
        """
        self.view._years(start_year, end_year)
        if not isinstance(school_id, str) or not school_id:
            raise ValueError("invalid school ID")
        if not self.path.is_file() or not self.view.matches.db_path.is_file():
            return False
        try:
            with closing(_read_only(self.path)) as cached, closing(_read_only(
                self.view.matches.db_path
            )) as source:
                source_rows = {
                    row["year"]: row
                    for row in source.execute(
                        "SELECT year,status,ledger_sha256,match_count "
                        "FROM career_years WHERE year BETWEEN ? AND ?",
                        (start_year, end_year),
                    )
                }
                cache_rows = {
                    row["year"]: row
                    for row in cached.execute(
                        "SELECT year,source_ledger_sha256,source_match_count "
                        "FROM school_year_stat_cache WHERE school_id=? "
                        "AND year BETWEEN ? AND ?",
                        (school_id, start_year, end_year),
                    )
                }
        except sqlite3.DatabaseError as exc:
            raise CareerStatsCacheConflict(
                "derived cache or source metadata unreadable"
            ) from exc

        complete = True
        for year in range(start_year, end_year + 1):
            source = source_rows.get(year)
            cache = cache_rows.get(year)
            if source is None or source["status"] != "sealed":
                complete = False
                continue
            if cache is None:
                complete = False
                continue
            if (cache["source_ledger_sha256"] != source["ledger_sha256"]
                    or cache["source_match_count"] != source["match_count"]):
                raise CareerStatsCacheConflict(
                    f"sealed school-year cache source changed: {year}"
                )
        return complete

    def player_seasons(self, player_id: str, *, start_year: int,
                       end_year: int, verify_source: bool = False) -> dict:
        if verify_source:
            raise PermissionError("GUI cannot request cache materialization")
        return super().player_seasons(
            player_id, start_year=start_year, end_year=end_year,
            verify_source=False,
        )

    def school_leaders(self, school_id: str, *, start_year: int,
                       end_year: int, category: str, limit: int = 20,
                       verify_source: bool = False) -> dict:
        if verify_source:
            raise PermissionError("GUI cannot request cache materialization")
        return super().school_leaders(
            school_id, start_year=start_year, end_year=end_year,
            category=category, limit=limit, verify_source=False,
        )
