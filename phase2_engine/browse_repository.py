from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

from .browse_views import (
    SeasonBrowseViews,
    build_season_browse_views,
    load_season_calendar,
)
from .repository import DataRepository
from .season import SeasonExecution


SCHEMA_VERSION = 1


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS browse_seasons (
    year INTEGER PRIMARY KEY,
    rng_seed INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    match_count INTEGER NOT NULL,
    competition_count INTEGER NOT NULL,
    school_count INTEGER NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS matches_by_date (
    year INTEGER NOT NULL,
    match_date TEXT NOT NULL,
    date_source TEXT NOT NULL,
    competition_id TEXT NOT NULL,
    competition_name TEXT NOT NULL,
    season_segment TEXT NOT NULL,
    competition_type TEXT NOT NULL,
    competition_level TEXT NOT NULL,
    match_id TEXT NOT NULL,
    stage_code TEXT NOT NULL,
    phase_code TEXT NOT NULL,
    round_no INTEGER NOT NULL,
    round_name TEXT NOT NULL,
    group_id TEXT NOT NULL,
    group_name TEXT NOT NULL,
    team1_id TEXT NOT NULL,
    team1_name TEXT NOT NULL,
    team1_score INTEGER,
    team2_id TEXT NOT NULL,
    team2_name TEXT NOT NULL,
    team2_score INTEGER,
    winner_id TEXT NOT NULL,
    winner_name TEXT NOT NULL,
    loser_id TEXT NOT NULL,
    loser_name TEXT NOT NULL,
    is_bye INTEGER NOT NULL CHECK (is_bye IN (0, 1)),
    score_source TEXT NOT NULL,
    result_text TEXT NOT NULL,
    PRIMARY KEY (year, competition_id, match_id),
    FOREIGN KEY (year) REFERENCES browse_seasons(year) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS competition_results (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    competition_name TEXT NOT NULL,
    season_segment TEXT NOT NULL,
    competition_type TEXT NOT NULL,
    competition_level TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    calendar_status TEXT NOT NULL,
    scheduled_date_count INTEGER NOT NULL,
    first_match_date TEXT NOT NULL,
    last_match_date TEXT NOT NULL,
    date_sources TEXT NOT NULL,
    match_count INTEGER NOT NULL,
    played_match_count INTEGER NOT NULL,
    bye_count INTEGER NOT NULL,
    participant_count INTEGER NOT NULL,
    champion_id TEXT NOT NULL,
    champion_name TEXT NOT NULL,
    runner_up_id TEXT NOT NULL,
    runner_up_name TEXT NOT NULL,
    total_runs INTEGER NOT NULL,
    average_total_runs REAL NOT NULL,
    score_sources TEXT NOT NULL,
    PRIMARY KEY (year, competition_id),
    FOREIGN KEY (year) REFERENCES browse_seasons(year) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS school_records (
    year INTEGER NOT NULL,
    school_id TEXT NOT NULL,
    school_name TEXT NOT NULL,
    prefecture_code TEXT NOT NULL,
    competition_count INTEGER NOT NULL,
    competition_ids TEXT NOT NULL,
    games INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    win_pct REAL NOT NULL,
    runs_for INTEGER NOT NULL,
    runs_against INTEGER NOT NULL,
    run_differential INTEGER NOT NULL,
    titles INTEGER NOT NULL,
    runner_up_finishes INTEGER NOT NULL,
    last_game_date TEXT NOT NULL,
    PRIMARY KEY (year, school_id),
    FOREIGN KEY (year) REFERENCES browse_seasons(year) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_matches_year_date
    ON matches_by_date(year, match_date, competition_id, match_id);
CREATE INDEX IF NOT EXISTS idx_matches_year_competition
    ON matches_by_date(year, competition_id, match_date, round_no, match_id);
CREATE INDEX IF NOT EXISTS idx_matches_year_team1
    ON matches_by_date(year, team1_id, match_date, competition_id);
CREATE INDEX IF NOT EXISTS idx_matches_year_team2
    ON matches_by_date(year, team2_id, match_date, competition_id);
CREATE INDEX IF NOT EXISTS idx_competitions_year_start
    ON competition_results(year, start_date, competition_id);
CREATE INDEX IF NOT EXISTS idx_schools_year_name
    ON school_records(year, school_name, school_id);
CREATE INDEX IF NOT EXISTS idx_schools_year_prefecture
    ON school_records(year, prefecture_code, wins DESC, school_id);
"""


class BrowseRepository:
    """SQLite repository for GUI/read-only browsing of one or more seasons."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _initialize_schema_conn(conn: sqlite3.Connection) -> None:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def initialize_schema(self) -> None:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)

    @staticmethod
    def _validate_views(year: int, views: SeasonBrowseViews) -> None:
        if year <= 0:
            raise ValueError("year must be positive")

        match_keys = [
            (row.competition_id, row.match_id)
            for row in views.matches_by_date
        ]
        if len(match_keys) != len(set(match_keys)):
            raise ValueError("duplicate (competition_id, match_id) in matches_by_date")

        competition_ids = [
            row.competition_id
            for row in views.competition_results
        ]
        if len(competition_ids) != len(set(competition_ids)):
            raise ValueError("duplicate competition_id in competition_results")
        competition_set = set(competition_ids)

        match_competitions = {
            row.competition_id
            for row in views.matches_by_date
        }
        missing_competitions = match_competitions - competition_set
        if missing_competitions:
            raise ValueError(
                "matches reference missing competition_results: "
                f"{sorted(missing_competitions)}"
            )

        school_ids = [row.school_id for row in views.school_records]
        if len(school_ids) != len(set(school_ids)):
            raise ValueError("duplicate school_id in school_records")
        school_set = set(school_ids)

        referenced_school_ids = {
            school_id
            for row in views.matches_by_date
            for school_id in (
                row.team1_id,
                row.team2_id,
                row.winner_id,
                row.loser_id,
            )
            if school_id
        }
        missing_schools = referenced_school_ids - school_set
        if missing_schools:
            raise ValueError(
                "matches reference missing school_records: "
                f"{sorted(missing_schools)}"
            )

    @staticmethod
    def _insert_dataclass_rows(
        conn: sqlite3.Connection,
        table: str,
        year: int,
        rows: Iterable[object],
    ) -> None:
        items = list(rows)
        if not items:
            return
        first = asdict(items[0])
        columns = ["year", *first.keys()]
        placeholders = ", ".join("?" for _ in columns)
        sql = (
            f"INSERT INTO {table} "
            f"({', '.join(columns)}) VALUES ({placeholders})"
        )

        payload = []
        for item in items:
            row = asdict(item)
            if "is_bye" in row:
                row["is_bye"] = 1 if row["is_bye"] else 0
            payload.append([year, *[row[column] for column in first]])
        conn.executemany(sql, payload)

    def replace_season_views(
        self,
        year: int,
        rng_seed: int,
        views: SeasonBrowseViews,
    ) -> dict:
        self._validate_views(year, views)
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            with conn:
                conn.execute(
                    "DELETE FROM browse_seasons WHERE year = ?",
                    (year,),
                )
                conn.execute(
                    """
                    INSERT INTO browse_seasons (
                        year, rng_seed, schema_version,
                        match_count, competition_count, school_count
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        year,
                        rng_seed,
                        SCHEMA_VERSION,
                        len(views.matches_by_date),
                        len(views.competition_results),
                        len(views.school_records),
                    ),
                )
                self._insert_dataclass_rows(
                    conn,
                    "matches_by_date",
                    year,
                    views.matches_by_date,
                )
                self._insert_dataclass_rows(
                    conn,
                    "competition_results",
                    year,
                    views.competition_results,
                )
                self._insert_dataclass_rows(
                    conn,
                    "school_records",
                    year,
                    views.school_records,
                )
        return {
            "year": year,
            "rng_seed": rng_seed,
            "schema_version": SCHEMA_VERSION,
            "match_count": len(views.matches_by_date),
            "competition_count": len(views.competition_results),
            "school_count": len(views.school_records),
            "sqlite_db": str(self.db_path),
        }

    @staticmethod
    def _rows(cursor: sqlite3.Cursor) -> list[dict]:
        return [dict(row) for row in cursor.fetchall()]

    def season_meta(self, year: int) -> dict | None:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            row = conn.execute(
                "SELECT * FROM browse_seasons WHERE year = ?",
                (year,),
            ).fetchone()
            return dict(row) if row is not None else None

    def matches_on_date(self, year: int, match_date: str) -> list[dict]:
        date.fromisoformat(match_date)
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                """
                SELECT * FROM matches_by_date
                WHERE year = ? AND match_date = ?
                ORDER BY competition_name, round_no, match_id
                """,
                (year, match_date),
            ))

    def undated_matches(self, year: int) -> list[dict]:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                """
                SELECT * FROM matches_by_date
                WHERE year = ? AND match_date = ''
                ORDER BY competition_name, round_no, match_id
                """,
                (year,),
            ))

    def competition_result(
        self,
        year: int,
        competition_id: str,
    ) -> dict | None:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            row = conn.execute(
                """
                SELECT * FROM competition_results
                WHERE year = ? AND competition_id = ?
                """,
                (year, competition_id),
            ).fetchone()
            return dict(row) if row is not None else None

    def competition_matches(
        self,
        year: int,
        competition_id: str,
    ) -> list[dict]:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                """
                SELECT * FROM matches_by_date
                WHERE year = ? AND competition_id = ?
                ORDER BY
                    CASE WHEN match_date = '' THEN 1 ELSE 0 END,
                    match_date,
                    round_no,
                    match_id
                """,
                (year, competition_id),
            ))

    def list_competitions(self, year: int) -> list[dict]:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                """
                SELECT * FROM competition_results
                WHERE year = ?
                ORDER BY start_date, competition_id
                """,
                (year,),
            ))

    def school_record(
        self,
        year: int,
        school_id: str,
    ) -> dict | None:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            row = conn.execute(
                """
                SELECT * FROM school_records
                WHERE year = ? AND school_id = ?
                """,
                (year, school_id),
            ).fetchone()
            return dict(row) if row is not None else None

    def school_matches(
        self,
        year: int,
        school_id: str,
    ) -> list[dict]:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                """
                SELECT
                    m.*,
                    CASE
                        WHEN m.team1_id = ? THEN m.team2_id
                        ELSE m.team1_id
                    END AS opponent_id,
                    CASE
                        WHEN m.team1_id = ? THEN m.team2_name
                        ELSE m.team1_name
                    END AS opponent_name,
                    CASE
                        WHEN m.is_bye = 1 THEN 'BYE'
                        WHEN m.winner_id = ? THEN 'W'
                        WHEN m.loser_id = ? THEN 'L'
                        ELSE ''
                    END AS school_result
                FROM matches_by_date AS m
                WHERE m.year = ?
                  AND (m.team1_id = ? OR m.team2_id = ?)
                ORDER BY
                    CASE WHEN m.match_date = '' THEN 1 ELSE 0 END,
                    m.match_date,
                    m.competition_id,
                    m.round_no,
                    m.match_id
                """,
                (
                    school_id,
                    school_id,
                    school_id,
                    school_id,
                    year,
                    school_id,
                    school_id,
                ),
            ))

    def search_school_records(
        self,
        year: int,
        *,
        text: str = "",
        prefecture_code: str = "",
        limit: int = 100,
    ) -> list[dict]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        clauses = ["year = ?"]
        params: list[object] = [year]
        if text:
            clauses.append("(school_name LIKE ? OR school_id LIKE ?)")
            token = f"%{text}%"
            params.extend([token, token])
        if prefecture_code:
            clauses.append("prefecture_code = ?")
            params.append(prefecture_code)
        params.append(limit)

        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                f"""
                SELECT * FROM school_records
                WHERE {' AND '.join(clauses)}
                ORDER BY wins DESC, titles DESC, school_name, school_id
                LIMIT ?
                """,
                params,
            ))


def save_season_browse_repository(
    season: SeasonExecution,
    repo: DataRepository,
    data_dir: str | Path,
    db_path: str | Path,
    *,
    score_overrides_by_competition: Mapping[str, Mapping[str, object]] | None = None,
    match_date_overrides_by_competition: Mapping[str, Mapping[str, str]] | None = None,
) -> dict:
    views = build_season_browse_views(
        season,
        repo,
        load_season_calendar(data_dir),
        score_overrides_by_competition=score_overrides_by_competition,
        match_date_overrides_by_competition=match_date_overrides_by_competition,
    )
    repository = BrowseRepository(db_path)
    return repository.replace_season_views(
        season.year,
        season.rng_seed,
        views,
    )
