"""Stage43G-62: GUI-independent, read-only historical screen handoff.

This adapter exposes validated screen routes to a FUTURE official GUI, not a
new official GUI or simulated-year advancement implementation. The two match
archives and roster DB remain independent; no cache/SQLite write is allowed.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .career_cross_era_year_catalog import CareerCrossEraYearCatalog
from .career_saved_school_catalog import (
    CareerSavedSchoolCatalog, MAX_SCHOOL_CHOICES,
)

CATALOG_LIMIT = 24
MAX_BACK_STACK = 100
_SCREEN_NAMES = {
    "cross_era_school": "history_school",
    "cross_era_match": "history_match",
    "cross_era_player": "history_player",
}


class CareerHistoryGuiBridgeConflict(ValueError):
    """Invalid save history link or unsupported gameplay-side operation."""


class CareerHistoryGuiBridge:
    """Atomic, stable-ID routes that an eventual GUI can render on demand."""

    def __init__(self, slot_root: str | Path, *, year_page_size: int = CATALOG_LIMIT):
        if type(year_page_size) is not int or not 1 <= year_page_size <= 24:
            raise CareerHistoryGuiBridgeConflict("invalid history catalog page size")
        self.catalog = CareerCrossEraYearCatalog(slot_root)
        self.school_catalog = CareerSavedSchoolCatalog(slot_root)
        self.year_page_size = year_page_size
        self.route = {"kind": "catalog", "before_year": None}
        self.history: list[dict] = []
        self.page = self._read(self.route)

    def _read(self, route: dict) -> dict:
        if route["kind"] == "catalog":
            data = self.catalog.page_after(
                before_year=route["before_year"], limit=self.year_page_size,
            )
            screen = "history_year_catalog"
            checked = False
            actions = ["open_saved_school"]
            if data["has_older"]:
                actions.append("older_years")
        elif route["kind"] == "schools":
            data = self.school_catalog.page(
                route["year"], after_school_id=route["after_school_id"],
                limit=MAX_SCHOOL_CHOICES,
            )
            screen = "history_school_catalog"
            checked = data["source_payloads_rechecked"]
            actions = ["open_saved_school"]
            if data["has_older"]:
                actions.append("older_schools")
        elif route["kind"] == "detail":
            target = route["target"]
            if target["view"] == "school":
                data = self.catalog.select_school(
                    target["selected_year"], target["school_id"],
                )
            else:
                data = self.catalog.navigator.follow(
                    target, verify_source=True,
                )
            if (data["screen"] == "cross_era_school"
                    and data["match_total"] == 0
                    and data["annual_roster_state"] == "missing_annual_roster"):
                raise CareerHistoryGuiBridgeConflict(
                    "no saved school-year roster or game for school ID"
                )
            screen = _SCREEN_NAMES[data["screen"]]
            checked = data["source_payloads_rechecked"]
            actions = ["open_saved_link"]
        else:
            raise CareerHistoryGuiBridgeConflict("unknown history screen route")
        return {
            "screen": screen, "data": data,
            "source_verified": checked,
            "history_read_only": True,
            "simulation_actions_available": False,
            "allow_advance_year": False,
            "allow_modify_records": False,
            "all_real_world_results_proven": False,
            "combined_career_stats_authorized": False,
            "actions": actions + (["back"] if self.history else []),
        }

    def _navigate(self, next_route: dict) -> dict:
        # Validate the new source before mutating any navigation state.
        page = self._read(next_route)
        self.history.append(deepcopy(self.route))
        if len(self.history) > MAX_BACK_STACK:
            self.history.pop(0)
        if "back" not in page["actions"]:
            page["actions"].append("back")
        self.route = deepcopy(next_route)
        self.page = page
        return page

    def open_year(self, year: int) -> dict:
        """Open a verified roster-school chooser from a displayed year."""
        if (self.route["kind"] != "catalog" or type(year) is not int
                or year not in {
                    row["year"] for row in self.page["data"]["years"]
                }):
            raise CareerHistoryGuiBridgeConflict(
                "select a saved year from the current catalog page"
            )
        return self._navigate({
            "kind": "schools", "year": year, "after_school_id": None,
        })

    def open_school(self, year: int, school_id: str) -> dict:
        if type(year) is not int or (
            type(school_id) is not str or not school_id
        ):
            raise CareerHistoryGuiBridgeConflict(
                "saved year and stable school ID are required"
            )
        if self.route["kind"] == "catalog":
            allowed = {
                row["year"] for row in self.page["data"]["years"]
            }
            if year not in allowed:
                raise CareerHistoryGuiBridgeConflict(
                    "select a saved year displayed in the current catalog page"
                )
        elif self.route["kind"] == "schools":
            if year != self.route["year"] or school_id not in {
                row["school_id"] for row in self.page["data"]["schools"]
            }:
                raise CareerHistoryGuiBridgeConflict(
                    "select a school from the current saved-year roster page"
                )
        else:
            raise CareerHistoryGuiBridgeConflict(
                "return to the saved-year school chooser before opening"
            )
        target = self.catalog.navigator._school_target(
            [year], year, school_id,
        )
        return self._navigate({"kind": "detail", "target": target})

    def older_schools(self) -> dict:
        if self.route["kind"] != "schools":
            raise CareerHistoryGuiBridgeConflict(
                "school paging requires the saved-year school chooser"
            )
        data = self.page["data"]
        if not data["has_older"]:
            return self.page
        cursor = data["next_after_school_id"]
        if type(cursor) is not str or not cursor:
            raise CareerHistoryGuiBridgeConflict("missing school page cursor")
        return self._navigate({
            "kind": "schools", "year": self.route["year"],
            "after_school_id": cursor,
        })

    def older_years(self) -> dict:
        if self.route["kind"] != "catalog":
            raise CareerHistoryGuiBridgeConflict(
                "return to the year catalog before moving to older years"
            )
        data = self.page["data"]
        if not data["has_older"]:
            return self.page
        cursor = data["next_cursor_before_year"]
        if type(cursor) is not int:
            raise CareerHistoryGuiBridgeConflict("missing year page cursor")
        return self._navigate({
            "kind": "catalog", "before_year": cursor,
        })

    @staticmethod
    def _visible_targets(source: dict) -> list[dict]:
        """Only expose exact stable-ID links produced by the verified page."""
        targets: list[dict] = []
        for key in (
            "match_detail_targets", "opponent_school_targets", "player_targets",
            "year_targets",
        ):
            for entry in source.get(key, []):
                target = entry.get("target", entry)
                if type(target) is dict:
                    targets.append(target)
        for key in ("back_to_school_target", "opponent_school_target"):
            target = source.get(key)
            if type(target) is dict:
                targets.append(target)
        return targets

    def open_link(self, target: dict) -> dict:
        if (self.route["kind"] != "detail" or type(target) is not dict
                or target not in self._visible_targets(self.page["data"])):
            raise CareerHistoryGuiBridgeConflict(
                "history link was not supplied by the current verified page"
            )
        current = self.route["target"]
        if (target["years"] != current["years"]
                or target["selected_year"] != current["selected_year"]):
            # Cross-year switches must go through explicit year selection.
            raise CareerHistoryGuiBridgeConflict(
                "history link belongs to another selected year"
            )
        return self._navigate({
            "kind": "detail", "target": deepcopy(target),
        })

    def back(self) -> dict:
        if not self.history:
            return self.page
        candidate = self.history[-1]
        page = self._read(candidate)
        self.history.pop()
        self.route = deepcopy(candidate)
        self.page = page
        return page

    def refresh(self) -> dict:
        page = self._read(self.route)
        self.page = page
        return page

    def advance_year(self, *args, **kwargs) -> None:
        raise CareerHistoryGuiBridgeConflict(
            "history is read-only; year progression must use a separately "
            "approved gameplay runtime, which is not connected here"
        )
