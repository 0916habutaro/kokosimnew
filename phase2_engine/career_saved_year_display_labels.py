"""Stage43G-64: exact saved-year Japanese names for history screens.

Display labels cannot prove identity. Saved roster SHA and permanent player
IDs are verified before labels are returned; current master names are fallback
only and explicitly NOT proof of the name used in a past season.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .career_cross_era_display_labels import CareerCrossEraDisplayLabels
from .career_option_a_storage_profile import _read_only
from .career_roster_archive import CareerRosterArchive


class CareerSavedYearDisplayLabels:
    def __init__(self, bridge, data_root: str | Path | None = None):
        browse = bridge.catalog.navigator.browse
        self.archive = browse.rosters
        self.base = CareerCrossEraDisplayLabels(
            data_root, self.archive, browse.attribution,
        )

    def school(self, year: int, school_id: str) -> dict:
        if (type(year) is not int or year <= 0
                or type(school_id) is not str or not school_id):
            raise ValueError("exact archived year and school ID required")
        roster = None
        if self.archive.db_path.is_file():
            with closing(_read_only(self.archive.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                roster = CareerRosterArchive._get(conn, year, school_id)
        if roster is not None:
            return {
                "label": f"{roster.school_name}（{school_id}）",
                "name": roster.school_name,
                "source": "exact_saved_school_year_roster",
                "historical_name_proven": True,
                "school_id": school_id,
                "year": year,
            }
        return {
            "label": self.base.school(school_id),
            "name": self.base.school_names.get(school_id),
            "source": "current_master_or_school_id_fallback",
            "historical_name_proven": False,
            "school_id": school_id,
            "year": year,
        }

    def player(self, year: int, school_id: str, player_id: str) -> dict:
        if type(player_id) is not str or not player_id:
            raise ValueError("permanent player ID required")
        names = self.base.player_labels(year, school_id)
        present = player_id in names
        return {
            "label": self.base.player(player_id, names),
            "player_id": player_id,
            "year": year,
            "school_id": school_id,
            "exact_year_roster_membership_verified": present,
            "source": (
                "exact_saved_school_year_roster"
                if present else "not_in_exact_year_roster"
            ),
        }
