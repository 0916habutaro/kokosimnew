from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .browse_repository import BrowseRepository


UNDATED_LABEL = "日付未定"
ALL_COMPETITIONS_LABEL = "すべての大会"
ALL_PREFECTURES_LABEL = "すべての都道府県"


@dataclass(frozen=True)
class CompetitionOption:
    competition_id: str
    label: str


@dataclass(frozen=True)
class SchoolOption:
    school_id: str
    label: str


@dataclass(frozen=True)
class BracketRound:
    round_no: int
    round_name: str
    matches: tuple[dict, ...]


class BrowseGuiModel:
    """Pure read-model adapter used by Tkinter and headless tests."""

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

    def competition_options(self, year: int) -> list[CompetitionOption]:
        rows = self.repository.list_competitions(year)
        return [
            CompetitionOption(
                competition_id=row["competition_id"],
                label=f"{row['competition_name']} [{row['competition_id']}]",
            )
            for row in rows
        ]

    def prefecture_choices(self, year: int) -> list[str]:
        return self.repository.list_prefecture_codes(year)

    def matches_for_date_choice(
        self,
        year: int,
        date_choice: str,
        *,
        competition_id: str = "",
        prefecture_code: str = "",
    ) -> list[dict]:
        date_value = "" if date_choice == UNDATED_LABEL else date_choice
        return self.repository.matches_for_date_filtered(
            year,
            date_value,
            competition_id=competition_id,
            prefecture_code=prefecture_code,
        )

    def competition_detail(
        self,
        year: int,
        competition_id: str,
    ) -> tuple[dict | None, list[dict]]:
        return (
            self.repository.competition_result(year, competition_id),
            self.repository.competition_matches(year, competition_id),
        )

    @staticmethod
    def bracket_rounds(
        matches: Iterable[dict],
    ) -> list[BracketRound]:
        rows = list(matches)
        main = [
            row
            for row in rows
            if (row.get("stage_code") or "") == "MAIN"
            and int(row.get("round_no") or 0) > 0
        ]
        candidates = main or [
            row
            for row in rows
            if int(row.get("round_no") or 0) > 0
        ]

        grouped: dict[int, list[dict]] = {}
        for row in candidates:
            grouped.setdefault(
                int(row["round_no"]),
                [],
            ).append(row)

        out: list[BracketRound] = []
        for round_no in sorted(grouped):
            cards = sorted(
                grouped[round_no],
                key=lambda row: (
                    row.get("group_id") or "",
                    row.get("match_id") or "",
                ),
            )
            round_name = next(
                (
                    str(row.get("round_name") or "")
                    for row in cards
                    if row.get("round_name")
                ),
                "",
            )
            if not round_name:
                round_name = next(
                    (
                        str(row.get("phase_code") or "")
                        for row in cards
                        if row.get("phase_code")
                    ),
                    f"Round {round_no}",
                )
            out.append(
                BracketRound(
                    round_no=round_no,
                    round_name=round_name,
                    matches=tuple(cards),
                )
            )
        return out

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
