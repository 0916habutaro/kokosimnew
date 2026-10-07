from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from .browse_repository import BrowseRepository
from .player_stats_read_model import PlayerStatsReadModel


UNDATED_LABEL = "日付未定"
ALL_COMPETITIONS_LABEL = "すべての大会"
ALL_PREFECTURES_LABEL = "すべての都道府県"
ALL_SEASONS_LABEL = "すべての季節"
ALL_TYPES_LABEL = "すべての大会種別"

SEASON_SEGMENT_LABELS = {
    "spring": "春",
    "summer": "夏",
    "autumn": "秋",
}

COMPETITION_TYPE_LABELS = {
    "spring_prefectural": "春季県大会",
    "spring_regional": "春季地区大会",
    "summer_local_qualifier": "夏地方大会",
    "national_invitational": "選抜大会",
    "national_championship": "全国選手権",
    "autumn_prefectural": "秋季県大会",
    "autumn_regional": "秋季地区大会",
    "national_autumn_championship": "秋季全国大会",
}


@dataclass(frozen=True)
class FilterOption:
    value: str
    label: str


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

    def __init__(
        self,
        db_path: str | Path,
        data_dir: str | Path = "data",
    ):
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)
        self.repository = BrowseRepository(self.db_path)
        stats_config = (
            self.data_dir.parent
            / "config"
            / "stats"
            / "player_rankings_v1.json"
        )
        if not stats_config.exists():
            stats_config = Path("config/stats/player_rankings_v1.json")
        self.player_stats = PlayerStatsReadModel(
            self.repository,
            config_path=stats_config,
        )
        self._prefecture_names = self._load_prefecture_names()

    def _load_prefecture_names(self) -> dict[str, str]:
        path = self.data_dir / "master" / "prefectures.csv"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = csv.DictReader(f)
            return {
                str(row["prefecture_code"]).zfill(2): row["prefecture_name"]
                for row in rows
                if row.get("prefecture_code") and row.get("prefecture_name")
            }

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

    def season_segment_options(self, year: int) -> list[FilterOption]:
        return [
            FilterOption(
                value=value,
                label=SEASON_SEGMENT_LABELS.get(value, value),
            )
            for value in self.repository.list_season_segments(year)
        ]

    def competition_type_options(
        self,
        year: int,
        *,
        season_segment: str = "",
    ) -> list[FilterOption]:
        return [
            FilterOption(
                value=value,
                label=COMPETITION_TYPE_LABELS.get(value, value),
            )
            for value in self.repository.list_competition_types(
                year,
                season_segment=season_segment,
            )
        ]

    def competition_options(
        self,
        year: int,
        *,
        season_segment: str = "",
        competition_type: str = "",
    ) -> list[CompetitionOption]:
        rows = self.repository.list_competitions_filtered(
            year,
            season_segment=season_segment,
            competition_type=competition_type,
        )
        return [
            CompetitionOption(
                competition_id=row["competition_id"],
                label=f"{row['competition_name']} [{row['competition_id']}]",
            )
            for row in rows
        ]

    def prefecture_choices(self, year: int) -> list[str]:
        return self.repository.list_prefecture_codes(year)

    def prefecture_options(self, year: int) -> list[FilterOption]:
        return [
            FilterOption(
                value=code,
                label=self.prefecture_label(code),
            )
            for code in self.prefecture_choices(year)
        ]

    def prefecture_label(self, code: str) -> str:
        normalized = str(code or "").zfill(2) if code else ""
        name = self._prefecture_names.get(normalized)
        if name:
            return name
        return normalized or "-"

    def matches_for_date_choice(
        self,
        year: int,
        date_choice: str,
        *,
        competition_id: str = "",
        prefecture_code: str = "",
        season_segment: str = "",
        competition_type: str = "",
    ) -> list[dict]:
        date_value = "" if date_choice == UNDATED_LABEL else date_choice
        return self.repository.matches_for_date_filtered(
            year,
            date_value,
            competition_id=competition_id,
            prefecture_code=prefecture_code,
            season_segment=season_segment,
            competition_type=competition_type,
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

    def search_players(
        self,
        year: int,
        *,
        text: str = "",
        school_id: str = "",
        position: str = "",
        limit: int = 200,
    ) -> list[dict]:
        return self.repository.search_players(
            year,
            text=text.strip(),
            school_id=school_id.strip(),
            position=position.strip(),
            limit=limit,
        )

    def school_roster_stats(
        self,
        year: int,
        school_id: str,
        *,
        competition_id: str = "",
    ) -> list[dict]:
        return self.player_stats.school_roster_summary(
            year,
            school_id,
            competition_id=competition_id,
        )

    def player_detail(
        self,
        year: int,
        player_id: str,
        *,
        competition_id: str = "",
    ) -> dict:
        return self.player_stats.player_summary(
            year,
            player_id,
            competition_id=competition_id,
        )

    def competition_leaderboards(
        self,
        year: int,
        competition_id: str,
        *,
        batting_metric: str = "ops",
        pitching_metric: str = "earned_run_average",
        limit: int = 20,
    ) -> dict:
        competition = self.repository.competition_result(
            year,
            competition_id,
        )
        return {
            "year": year,
            "competition_id": competition_id,
            "competition": competition,
            "batting_metric": batting_metric,
            "pitching_metric": pitching_metric,
            "batting": self.batting_leaderboard(
                year,
                batting_metric,
                competition_id=competition_id,
                limit=limit,
            ),
            "pitching": self.pitching_leaderboard(
                year,
                pitching_metric,
                competition_id=competition_id,
                limit=limit,
            ),
        }

    def player_stats_summary(
        self,
        year: int,
        player_id: str,
        *,
        competition_id: str = "",
    ) -> dict:
        return self.player_stats.player_summary(
            year,
            player_id,
            competition_id=competition_id,
        )

    def batting_leaderboard(
        self,
        year: int,
        metric: str,
        *,
        competition_id: str = "",
        school_id: str = "",
        limit: int = 50,
    ) -> list[dict]:
        return [
            row.to_dict()
            for row in self.player_stats.batter_rankings(
                year,
                metric,
                competition_id=competition_id,
                school_id=school_id,
                limit=limit,
            )
        ]

    def pitching_leaderboard(
        self,
        year: int,
        metric: str,
        *,
        competition_id: str = "",
        school_id: str = "",
        limit: int = 50,
    ) -> list[dict]:
        return [
            row.to_dict()
            for row in self.player_stats.pitcher_rankings(
                year,
                metric,
                competition_id=competition_id,
                school_id=school_id,
                limit=limit,
            )
        ]

    def home_summary(
        self,
        year: int,
        *,
        today: str | None = None,
    ) -> dict:
        meta = self.repository.season_meta(year) or {}
        competitions = self.repository.list_competitions(year)
        dates = self.repository.list_match_dates(year)

        today_value = today or date.today().isoformat()
        dated = [value for value in dates if value]
        previous_date = max(
            (value for value in dated if value <= today_value),
            default="",
        )
        next_date = min(
            (value for value in dated if value >= today_value),
            default="",
        )
        today_match_count = (
            len(self.repository.matches_on_date(year, today_value))
            if today_value in dated
            else 0
        )

        segment_counts: dict[str, int] = {}
        for row in competitions:
            segment = row.get("season_segment") or ""
            segment_counts[segment] = segment_counts.get(segment, 0) + 1

        return {
            "year": year,
            "today": today_value,
            "match_count": int(meta.get("match_count") or 0),
            "competition_count": int(meta.get("competition_count") or 0),
            "school_count": int(meta.get("school_count") or 0),
            "today_match_count": today_match_count,
            "previous_match_date": previous_date,
            "next_match_date": next_date,
            "segment_counts": segment_counts,
        }

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
