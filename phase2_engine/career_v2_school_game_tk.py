"""Stage43G-77: atomic school game pages for independently sealed fictional v2.

The legacy A archive is not an input. Pages come solely from the dedicated
v2 Option-A read API; neither records nor logical dates are converted.
"""
from __future__ import annotations

from pathlib import Path

PAGE_SIZE = 30
V2_SOURCE = "fictional_option_a_v2"


class CareerV2SchoolGamePager:
    """Bounded school/year/competition selection with fail-closed transitions."""

    source_kind = V2_SOURCE
    valid_verify_scopes = ("page", "selected_years")
    min_year = 10000
    max_year = None

    def __init__(self, v2_path: str | Path, calendar_path: str | Path,
                 school_id: str, selected_year: int):
        if (type(school_id) is not str or not school_id
                or type(selected_year) is not int or selected_year < 10000):
            raise ValueError("valid v2 school and game year are required")
        self.v2_path = Path(v2_path)
        self.calendar_path = Path(calendar_path)
        self.school_id = school_id
        self.start_year = selected_year
        self.end_year = selected_year
        self.competition_id: str | None = None
        self.verify_scope = "page"
        self.offset = 0
        self.page = self._fetch(
            selected_year, selected_year, None, 0, "page",
        )

    def _fetch(self, start: int, end: int, competition_id: str | None,
               offset: int, verify_scope: str) -> dict:
        from .career_v2_school_game_page import read_v2_school_game_page
        data = read_v2_school_game_page(
            self.v2_path, self.calendar_path, self.school_id,
            start_year=start, end_year=end, competition_id=competition_id,
            limit=PAGE_SIZE, offset=offset, verify_scope=verify_scope,
        )
        if (data.get("school_id") != self.school_id
                or data.get("start_year") != start
                or data.get("end_year") != end
                or data.get("competition_id") != competition_id
                or data.get("limit") != PAGE_SIZE
                or data.get("offset") != offset
                or data.get("verification_scope") != verify_scope
                or data.get("legacy_records_combined") is not False
                or data.get("source_records_not_modified") is not True
                or data.get("visible_match_checksums_verified") is not True
                or data.get("all_selected_year_payloads_verified")
                is not (verify_scope == "selected_years")):
            raise ValueError("fictional v2 search did not verify its saved source")
        for row in data["records"]:
            if (row.get("stored_source") !=
                    "explicit_fictional_v2_option_a_not_official"
                    or row.get("school_id") != self.school_id
                    or type(row.get("game_day_token")) is not str):
                raise ValueError("fictional v2 game row has wrong provenance")
        return data

    def apply_filters(self, start: int, end: int,
                      competition_id: str | None = None,
                      verify_scope: str = "page") -> dict:
        data = self._fetch(start, end, competition_id, 0, verify_scope)
        self.start_year, self.end_year = start, end
        self.competition_id, self.verify_scope = competition_id, verify_scope
        self.offset, self.page = 0, data
        return data

    def move(self, direction: int) -> dict:
        if type(direction) is not int or direction not in (-1, 1):
            raise ValueError("invalid game page direction")
        target = self.offset + direction * PAGE_SIZE
        if target < 0 or target >= self.page["total"]:
            return self.page
        data = self._fetch(
            self.start_year, self.end_year, self.competition_id,
            target, self.verify_scope,
        )
        if not data["records"]:
            raise ValueError("fictional v2 page changed while browsing")
        self.offset, self.page = target, data
        return data

    @property
    def can_previous(self) -> bool:
        return self.offset > 0

    @property
    def can_next(self) -> bool:
        return self.offset + PAGE_SIZE < self.page["total"]
