"""Stage43G-34: source-attributed Japanese names for read-only history UI.

The CSV supplies *display labels*, not identity or match provenance. Player
names are taken only from their exact saved school/year roster snapshot.
Never associate students between years by name, position or uniform number.
"""
from __future__ import annotations

import csv
from contextlib import closing
from pathlib import Path
import sqlite3

from .career_option_a_storage_profile import _read_only
from .career_roster_archive import CareerRosterArchive
from .paths import resolve_data_file


class CareerDisplayLabelConflict(ValueError):
    """Duplicate or corrupted school labels, or unverified player identities."""


class CareerCrossEraDisplayLabels:
    """Readable names always accompanied by immutable archive IDs."""

    def __init__(self, data_root: str | Path | None,
                 roster_archive: CareerRosterArchive, attribution):
        self.rosters = roster_archive
        self.attribution = attribution
        self.school_names: dict[str, str] = {}
        if data_root is not None:
            path = resolve_data_file(data_root, "schools.csv")
            if not path.is_file():
                raise FileNotFoundError("school master schools.csv is absent")
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                for item in csv.DictReader(stream):
                    school_id = (item.get("school_id") or "").strip()
                    label = (
                        item.get("display_name") or
                        item.get("federation_name") or ""
                    ).strip()
                    if not school_id:
                        raise CareerDisplayLabelConflict(
                            "school master row has no school ID"
                        )
                    if school_id in self.school_names:
                        raise CareerDisplayLabelConflict(
                            "duplicate canonical school ID"
                        )
                    self.school_names[school_id] = label

    def school(self, school_id: str) -> str:
        if type(school_id) is not str or not school_id:
            raise ValueError("school ID is required")
        label = self.school_names.get(school_id)
        return f"{label}（{school_id}）" if label else (
            f"{school_id}（学校名未登録）"
        )

    def player_labels(self, year: int, school_id: str) -> dict[str, str]:
        """Read one exact year roster with checksum and identity validation."""
        if (type(year) is not int or year <= 0
                or type(school_id) is not str or not school_id):
            raise ValueError("year and school ID required")
        if not self.rosters.db_path.is_file():
            return {}
        with closing(_read_only(self.rosters.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            snapshot = CareerRosterArchive._get(conn, year, school_id)
            if snapshot is None:
                return {}
            members = self.attribution._members(conn, year, school_id)
            if len(members) != len(snapshot.players):
                raise CareerDisplayLabelConflict(
                    "verified player identity count differs"
                )
            return {
                p.player_id: p.display_name
                for p in snapshot.players
            }

    @staticmethod
    def player(player_id: str, names: dict[str, str]) -> str:
        if type(player_id) is not str or not player_id:
            raise ValueError("permanent player ID required")
        name = names.get(player_id)
        return f"{name}（{player_id}）" if name else (
            f"{player_id}（この年度に氏名の確認なし）"
        )
