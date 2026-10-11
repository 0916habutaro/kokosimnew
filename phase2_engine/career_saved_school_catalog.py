"""Stage43G-65: exact-year school choices for a future save/history GUI.

Only schools with a saved school-year roster snapshot are indexed here.
This does not claim to enumerate all Japanese schools or schools whose only
historical evidence is a match without a stored roster.

A sealed year is source-verified BEFORE any candidate is displayed; each
school label comes from that exact year's digest-checked roster snapshot.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .career_cross_era_read_gate import CareerCrossEraReadGate
from .career_option_a_storage_profile import _read_only
from .career_roster_archive import CareerRosterArchive

MAX_SCHOOL_CHOICES = 30


class CareerSavedSchoolCatalogConflict(ValueError):
    """Unverified source or malformed school page may not be displayed."""


class CareerSavedSchoolCatalog:
    """Bounded, read-only (year, school_id) composite primary-key scan."""

    def __init__(self, slot_root: str | Path):
        slot = Path(slot_root)
        self.rosters = CareerRosterArchive(slot / "career_rosters.sqlite3")
        self.gate = CareerCrossEraReadGate(
            slot / "historical_matches.sqlite3",
            slot / "fictional_option_a_v2.sqlite3",
            slot / "sandbox_calendar_v2.sqlite3",
        )

    def page(self, year: int, *, after_school_id: str | None = None,
             limit: int = MAX_SCHOOL_CHOICES) -> dict:
        if (type(year) is not int or year < 1
                or type(limit) is not int or not 1 <= limit <= MAX_SCHOOL_CHOICES
                or (after_school_id is not None and (
                    type(after_school_id) is not str or not after_school_id
                ))):
            raise CareerSavedSchoolCatalogConflict(
                "a saved year and bounded school cursor are required"
            )
        # Revalidate the sealed year and every match payload. The year
        # header catalog alone is deliberately not a verified game record.
        checked = self.gate.inspect([year], verify_source=True)
        route = checked["routes"][0]
        found = []
        if self.rosters.db_path.is_file():
            with closing(_read_only(self.rosters.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                if after_school_id is None:
                    rows = conn.execute(
                        "SELECT school_id FROM career_school_rosters "
                        "WHERE year=? ORDER BY school_id LIMIT ?",
                        (year, limit + 1),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT school_id FROM career_school_rosters "
                        "WHERE year=? AND school_id>? "
                        "ORDER BY school_id LIMIT ?",
                        (year, after_school_id, limit + 1),
                    ).fetchall()
                for row in rows:
                    school_id = row["school_id"]
                    roster = CareerRosterArchive._get(conn, year, school_id)
                    if roster is None or not roster.school_name:
                        raise CareerSavedSchoolCatalogConflict(
                            "saved year school name is missing"
                        )
                    found.append({
                        "year": year, "school_id": school_id,
                        "school_name": roster.school_name,
                        "label": f"{roster.school_name}（{school_id}）",
                        "source": "exact_saved_school_year_roster",
                        "school_name_digest_verified": True,
                    })
        candidates = found[:limit]
        older = len(found) > limit
        return {
            "screen": "history_school_catalog",
            "year": year,
            "source": route["source"],
            "date_kind": route["date_kind"],
            "schools": candidates,
            "has_older": older,
            "after_school_id": after_school_id,
            "next_after_school_id": (
                candidates[-1]["school_id"] if older else None
            ),
            "limit": limit,
            "only_saved_year_rosters_indexed": True,
            "full_nation_school_coverage_proven": False,
            "source_payloads_rechecked": True,
            "read_only": True,
            "allow_advance_year": False,
        }
