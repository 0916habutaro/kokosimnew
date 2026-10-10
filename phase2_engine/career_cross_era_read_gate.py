"""Stage43G-30: read-only preflight for viewing legacy and v2 years together.

This gate returns a source manifest, NOT a migrated save, career-stat union,
combined chronological date index, or permission to run a synthetic season.
Dates and match records remain in their independent authoritative archives.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from .career_calendar_v2 import CareerCalendarV2Archive, GameDaySlot
from .career_era_calendar_contract import MAX_GREGORIAN_YEAR, _year
from .career_option_a_storage_profile import _read_only
from .career_v2_option_a_archive import (
    CareerV2OptionAArchive, _calendar_info, _ledger as _v2_ledger,
)
from .historical_match_archive import HistoricalMatchArchive

CONTRACT = "career_legacy_v2_read_preflight_v1"


class CareerCrossEraConflict(ValueError):
    """Overlapping, unsealed, absent or altered source prevents safe routing."""


class CareerCrossEraReadGate:
    """Verify a finite explicit year selection without writing SQLite."""

    def __init__(self, legacy_path: str | Path,
                 v2_path: str | Path, calendar_path: str | Path):
        self.legacy_path = Path(legacy_path)
        self.v2_path = Path(v2_path)
        self.calendar_path = Path(calendar_path)
        physical = [p.resolve() for p in (
            self.legacy_path, self.v2_path, self.calendar_path,
        )]
        if len(set(physical)) != 3:
            raise ValueError("legacy, v2 and calendar must be separate files")
        self.v2_archive = CareerV2OptionAArchive(
            self.v2_path, self.calendar_path,
            legacy_archive_path=self.legacy_path,
        )

    @staticmethod
    def _header(path: Path, query: str) -> dict[int, dict]:
        if not path.is_file():
            return {}
        with closing(_read_only(path)) as conn:
            conn.row_factory = sqlite3.Row
            return {
                row["year"]: dict(row)
                for row in conn.execute(query)
            }

    def _all_headers(self) -> tuple[dict, dict]:
        try:
            legacy = self._header(
                self.legacy_path,
                "SELECT year,status,match_count,ledger_sha256 "
                "FROM career_years ORDER BY year",
            )
            v2 = self._header(
                self.v2_path,
                "SELECT year,status,match_count,ledger_sha256,calendar_sha256 "
                "FROM v2_game_years ORDER BY year",
            )
        except sqlite3.DatabaseError as exc:
            raise CareerCrossEraConflict("source archive metadata unreadable") from exc
        for src in (legacy, v2):
            for year, record in src.items():
                try:
                    _year(year)
                except ValueError as exc:
                    raise CareerCrossEraConflict("saved game year invalid") from exc
                if (record["status"] not in ("active", "sealed")
                        or (record["status"] == "sealed" and
                            (type(record["match_count"]) is not int
                             or record["match_count"] < 0
                             or type(record["ledger_sha256"]) is not str))):
                    raise CareerCrossEraConflict("saved game year metadata invalid")
        if set(legacy).intersection(v2):
            raise CareerCrossEraConflict(
                "legacy and v2 archives contain overlapping years"
            )
        if any(y > MAX_GREGORIAN_YEAR for y in legacy):
            raise CareerCrossEraConflict("legacy ISO archive has year beyond 9999")
        if any(y <= MAX_GREGORIAN_YEAR for y in v2):
            raise CareerCrossEraConflict(
                "v2 year overlaps the Gregorian legacy calendar era"
            )
        return legacy, v2

    def _legacy_year(self, year: int, header: dict,
                     deep: bool) -> dict:
        if header["status"] != "sealed":
            raise CareerCrossEraConflict("legacy year not sealed")
        try:
            with closing(_read_only(self.legacy_path)) as conn:
                conn.row_factory = sqlite3.Row
                count, ledger = HistoricalMatchArchive._ledger(conn, year)
                if (count != header["match_count"]
                        or ledger != header["ledger_sha256"]):
                    raise CareerCrossEraConflict("legacy sealed ledger differs")
                if deep:
                    rows = conn.execute(
                        "SELECT year,competition_id,match_id,match_date,"
                        "payload_json,record_sha256 "
                        "FROM historical_matches WHERE year=?",
                        (year,),
                    )
                    for row in rows:
                        raw = row["payload_json"]
                        if sha256(raw.encode("utf-8")).hexdigest() != row["record_sha256"]:
                            raise CareerCrossEraConflict(
                                "legacy Option-A match payload SHA differs"
                            )
                        value = json.loads(raw)
                        if (value.get("year"), value.get("competition_id"),
                            value.get("match_id"), value.get("match_date")) != (
                            year, row["competition_id"], row["match_id"],
                            row["match_date"],
                        ):
                            raise CareerCrossEraConflict("legacy match identity differs")
                        token = GameDaySlot.from_iso(row["match_date"])
                        if token.year != year:
                            raise CareerCrossEraConflict("legacy match date year differs")
        except (sqlite3.DatabaseError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, CareerCrossEraConflict):
                raise
            raise CareerCrossEraConflict("legacy source validation failed") from exc
        return {
            "year": year, "source": "historical_matches_legacy_iso",
            "date_kind": "YYYY-MM-DD", "match_count": count,
            "ledger_sha256": ledger, "year_sealed": True,
            "payloads_rechecked": deep,
        }

    def _v2_year(self, year: int, header: dict, deep: bool) -> dict:
        if header["status"] != "sealed":
            raise CareerCrossEraConflict("fictional v2 year not sealed")
        try:
            plan, plan_sha = _calendar_info(
                CareerCalendarV2Archive(self.calendar_path), year,
            )
            if plan_sha != header["calendar_sha256"]:
                raise CareerCrossEraConflict("v2 calendar SHA differs")
            with closing(_read_only(self.v2_path)) as conn:
                count, ledger = _v2_ledger(conn, year)
            if (count != header["match_count"]
                    or ledger != header["ledger_sha256"]):
                raise CareerCrossEraConflict("v2 sealed ledger differs")
            if deep:
                first = self.v2_archive.year_matches(year, limit=100)
                if (first["total"] != count or first["year_status"] != "sealed"
                        or first["calendar_sha256"] != plan_sha):
                    raise CareerCrossEraConflict("v2 deep source metadata differs")
                for offset in range(100, count, 100):
                    page = self.v2_archive.year_matches(
                        year, limit=100, offset=offset,
                    )
                    if (page["total"] != count or page["year_status"] != "sealed"
                            or page["calendar_sha256"] != plan_sha):
                        raise CareerCrossEraConflict("v2 paging source changed")
        except (sqlite3.DatabaseError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, CareerCrossEraConflict):
                raise
            raise CareerCrossEraConflict("v2 source validation failed") from exc
        return {
            "year": year, "source": "fictional_option_a_v2",
            "date_kind": "G{year}:MM-DD", "match_count": count,
            "ledger_sha256": ledger, "calendar_sha256": plan_sha,
            "year_sealed": True, "payloads_rechecked": deep,
            "fictional_calendar_not_official": True,
        }

    def inspect(self, years: list[int], *, verify_source: bool = False) -> dict:
        """Report source routing and missing periods; never merge game facts.

        Gaps *between selected years* are disclosed as intervals. They are
        not assumed to contain missing games or seasons, and must not be
        presented as validated continuous career history.
        """
        if (type(years) is not list or not years
                or any(type(y) is not int for y in years)
                or years != sorted(set(years))
                or type(verify_source) is not bool):
            raise ValueError("explicit unique ascending years are required")
        for year in years:
            _year(year)
        legacy, v2 = self._all_headers()
        routes = []
        for year in years:
            if year in legacy:
                routes.append(self._legacy_year(year, legacy[year], verify_source))
            elif year in v2:
                routes.append(self._v2_year(year, v2[year], verify_source))
            else:
                raise CareerCrossEraConflict(f"requested year not saved: {year}")
        holes = [
            {"from_year": a + 1, "through_year": b - 1}
            for a, b in zip(years, years[1:]) if b > a + 1
        ]
        return {
            "contract_id": CONTRACT,
            "requested_years": years,
            "routes": routes,
            "unverified_intervening_year_intervals": holes,
            "selected_years_are_contiguous": not bool(holes),
            "each_selected_year_sealed": True,
            "source_payloads_rechecked": verify_source,
            "dual_source_year_collision_absent": True,
            "read_only_preflight": True,
            "legacy_records_migrated": False,
            "combined_career_stats_authorized": False,
            "combined_date_index_authorized": False,
            "future_tournament_runtime_authorized": False,
        }
