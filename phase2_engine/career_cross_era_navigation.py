"""Stage43G-32: deterministic read-only navigation for cross-era school/player views.

This is a headless navigation contract, not the official GUI. Every
transition revalidates exact stable school/player IDs and explicit saved
year selection. Neither archives nor caches are created by browsing.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .career_cross_era_browse_model import CareerCrossEraBrowseModel
from .career_option_a_storage_profile import _read_only
from .career_roster_archive import CareerRosterArchive

MAX_SELECTED_YEARS = 24
MAX_PAGE = 100


class CareerCrossEraNavigationConflict(ValueError):
    """Malformed navigation, unsaved player membership or source conflict."""


class CareerCrossEraNavigator:
    """Explicit year and stable ID links for a future read-only GUI adapter."""

    def __init__(self, slot_root: str | Path):
        self.browse = CareerCrossEraBrowseModel(slot_root)

    @staticmethod
    def _selection(years: list[int], selected_year: int) -> list[int]:
        if (type(years) is not list or not 1 <= len(years) <= MAX_SELECTED_YEARS
                or any(type(year) is not int or year < 1 for year in years)
                or years != sorted(set(years))
                or type(selected_year) is not int
                or selected_year not in years):
            raise CareerCrossEraNavigationConflict(
                "select an existing year from bounded distinct ascending years"
            )
        return list(years)

    @staticmethod
    def _school_target(years: list[int], year: int, school_id: str) -> dict:
        return {
            "view": "school", "years": list(years),
            "selected_year": year, "school_id": school_id,
        }

    @staticmethod
    def _player_target(
        years: list[int], year: int, school_id: str, player_id: str,
    ) -> dict:
        return {
            **CareerCrossEraNavigator._school_target(years, year, school_id),
            "view": "player", "player_id": player_id,
        }

    def _roster_links(self, years: list[int], year: int, school_id: str) -> dict:
        path = self.browse.rosters.db_path
        if not path.is_file():
            return {"state": "missing_annual_roster", "links": []}
        with closing(_read_only(path)) as conn:
            conn.row_factory = sqlite3.Row
            snapshot = CareerRosterArchive._get(conn, year, school_id)
            if snapshot is None:
                return {"state": "missing_annual_roster", "links": []}
            # Fail closed on tampered permanent identity. Do not silently
            # create navigation links from display names or jersey numbers.
            members = self.browse.attribution._members(conn, year, school_id)
            if len(snapshot.players) != len(members):
                raise CareerCrossEraNavigationConflict(
                    "annual roster ID coverage changed"
                )
            return {
                "state": "saved_roster_and_permanent_ids_verified",
                "links": [
                    {
                        "player_id": player_id,
                        "target": self._player_target(
                            years, year, school_id, player_id,
                        ),
                    }
                    for player_id in sorted(members)
                ],
            }

    def school_page(
        self, years: list[int], school_id: str, *,
        selected_year: int, limit: int = 30, offset: int = 0,
        verify_source: bool = True,
    ) -> dict:
        selection = self._selection(years, selected_year)
        if type(school_id) is not str or not school_id:
            raise ValueError("school ID required")
        if (type(limit) is not int or not 1 <= limit <= MAX_PAGE
                or type(offset) is not int or offset < 0
                or type(verify_source) is not bool):
            raise ValueError("invalid match page or verification mode")
        original = self.browse.school_years(
            selection, school_id, verify_source=verify_source,
        )
        selected = next(
            row for row in original["sections"]
            if row["year"] == selected_year
        )
        matches = selected["matches"]
        visible = matches[offset:offset + limit]
        roster = self._roster_links(selection, selected_year, school_id)
        return {
            "screen": "cross_era_school",
            "years": selection,
            "school_id": school_id,
            "selected_year": selected_year,
            "source": selected["source"],
            "date_kind": selected["date_kind"],
            "match_total": len(matches),
            "match_page": visible,
            "match_page_limit": limit,
            "match_page_offset": offset,
            "match_wins_from_saved_games": selected["wins_from_saved_games"],
            "match_losses_from_saved_games": selected["losses_from_saved_games"],
            "year_targets": [
                self._school_target(selection, year, school_id)
                for year in selection
            ],
            "opponent_school_targets": [
                {
                    "competition_id": match["competition_id"],
                    "match_id": match["match_id"],
                    "target": self._school_target(
                        selection, selected_year,
                        match["team2_id"] if match["team1_id"] == school_id
                        else match["team1_id"],
                    ),
                }
                for match in visible
            ],
            "annual_roster_state": roster["state"],
            "player_targets": roster["links"],
            "unverified_intervening_year_intervals":
                original["unverified_intervening_year_intervals"],
            "source_payloads_rechecked": original["source_payloads_rechecked"],
            "combined_career_stats_authorized": False,
            "navigation_wrote_to_save": False,
            "official_gui_connected": False,
        }

    def player_page(
        self, years: list[int], school_id: str, player_id: str, *,
        selected_year: int, verify_source: bool = True,
    ) -> dict:
        selection = self._selection(years, selected_year)
        if (type(school_id) is not str or not school_id
                or type(player_id) is not str or not player_id
                or type(verify_source) is not bool):
            raise ValueError("school, permanent player ID and bool audit required")
        original = self.browse.player_years(
            selection, school_id, player_id, verify_source=verify_source,
        )
        selected = next(
            row for row in original["sections"]
            if row["year"] == selected_year
        )
        return {
            "screen": "cross_era_player",
            "years": selection,
            "school_id": school_id,
            "player_id": player_id,
            "selected_year": selected_year,
            "selected_status": selected["status"],
            "selected_source": selected["source"],
            "selected_statistics": selected["statistics"],
            "source_separated_year_sections": original["sections"],
            "year_targets": [
                self._player_target(selection, year, school_id, player_id)
                for year in selection
            ],
            "back_to_school_target": self._school_target(
                selection, selected_year, school_id,
            ),
            "unverified_intervening_year_intervals":
                original["unverified_intervening_year_intervals"],
            "combined_career_totals": None,
            "identity_continuity_proven": False,
            "source_payloads_rechecked": original["source_payloads_rechecked"],
            "navigation_wrote_to_save": False,
            "official_gui_connected": False,
        }

    def follow(self, target: dict, *, verify_source: bool = True) -> dict:
        """Resolve only routes created by this navigation contract.

        A route is not trusted just because it came from the previous page:
        every source archive, roster and selected year is checked anew.
        """
        if type(target) is not dict or type(verify_source) is not bool:
            raise ValueError("invalid navigation target")
        view = target.get("view")
        expected = (
            {"view", "years", "selected_year", "school_id"}
            if view == "school" else
            {"view", "years", "selected_year", "school_id", "player_id"}
            if view == "player" else None
        )
        if expected is None or set(target) != expected:
            raise CareerCrossEraNavigationConflict("unknown or malformed route")
        if view == "school":
            return self.school_page(
                target["years"], target["school_id"],
                selected_year=target["selected_year"],
                verify_source=verify_source,
            )
        return self.player_page(
            target["years"], target["school_id"], target["player_id"],
            selected_year=target["selected_year"],
            verify_source=verify_source,
        )
