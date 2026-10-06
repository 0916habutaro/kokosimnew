from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .browse_repository import BrowseRepository


UNDATED_LABEL = "日付未定"


@dataclass(frozen=True)
class CompetitionOption:
    competition_id: str
    label: str


@dataclass(frozen=True)
class SchoolOption:
    school_id: str
    label: str


class BrowseGuiModel:
    """Pure read-model adapter used by the Tkinter GUI and headless tests."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.repository = BrowseRepository(self.db_path)

    def ensure_database_exists(self) -> None:
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"SQLite DB not found: {self.db_path}. "
                "Run season_cli with --sqlite-db first."
            )

    def available_years(self) -> list[int]:
        self.ensure_database_exists()
        return self.repository.list_years()

    def date_choices(self, year: int) -> list[str]:
        dates = self.repository.list_match_dates(
            year,
            include_undated=True,
        )
        dated = [value for value in dates if value]
        if "" in dates:
            dated.append(UNDATED_LABEL)
        return dated

    def matches_for_date_choice(
        self,
        year: int,
        date_choice: str,
    ) -> list[dict]:
        if date_choice == UNDATED_LABEL:
            return self.repository.undated_matches(year)
        return self.repository.matches_on_date(year, date_choice)

    def competition_options(self, year: int) -> list[CompetitionOption]:
        rows = self.repository.list_competitions(year)
        return [
            CompetitionOption(
                competition_id=row["competition_id"],
                label=f"{row['competition_name']} [{row['competition_id']}]",
            )
            for row in rows
        ]

    def competition_detail(
        self,
        year: int,
        competition_id: str,
    ) -> tuple[dict | None, list[dict]]:
        return (
            self.repository.competition_result(year, competition_id),
            self.repository.competition_matches(year, competition_id),
        )

    def search_schools(
        self,
        year: int,
        *,
        text: str = "",
        prefecture_code: str = "",
        limit: int = 200,
    ) -> list[dict]:
        return self.repository.search_school_records(
            year,
            text=text.strip(),
            prefecture_code=prefecture_code.strip(),
            limit=limit,
        )

    def school_detail(
        self,
        year: int,
        school_id: str,
    ) -> tuple[dict | None, list[dict]]:
        return (
            self.repository.school_record(year, school_id),
            self.repository.school_matches(year, school_id),
        )

    @staticmethod
    def score_text(row: dict) -> str:
        if int(row.get("is_bye") or 0):
            return "不戦勝"
        left = row.get("team1_score")
        right = row.get("team2_score")
        if left is None or right is None:
            return "-"
        return f"{left}-{right}"

    @staticmethod
    def result_symbol(value: str) -> str:
        return {
            "W": "○",
            "L": "●",
            "BYE": "不戦勝",
        }.get(value, value or "")
