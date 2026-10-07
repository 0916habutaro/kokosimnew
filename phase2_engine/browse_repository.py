from __future__ import annotations

import json
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


SCHEMA_VERSION = 2


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


CREATE TABLE IF NOT EXISTS ability_matches (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    generation_seed INTEGER NOT NULL,
    team1_school_id TEXT NOT NULL,
    team2_school_id TEXT NOT NULL,
    team1_score INTEGER NOT NULL,
    team2_score INTEGER NOT NULL,
    winner_id TEXT NOT NULL,
    loser_id TEXT NOT NULL,
    last_inning INTEGER NOT NULL,
    ending_half TEXT NOT NULL,
    score_source TEXT NOT NULL,
    match_config_id TEXT NOT NULL,
    match_config_revision INTEGER NOT NULL,
    match_config_sha256 TEXT NOT NULL,
    event_catalog_id TEXT NOT NULL,
    event_catalog_revision INTEGER NOT NULL,
    event_catalog_sha256 TEXT NOT NULL,
    stats_config_id TEXT NOT NULL,
    stats_config_revision INTEGER NOT NULL,
    stats_config_sha256 TEXT NOT NULL,
    PRIMARY KEY (year, competition_id, match_id),
    FOREIGN KEY (year) REFERENCES browse_seasons(year) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS batter_game_stats (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    plate_appearances INTEGER NOT NULL,
    at_bats INTEGER NOT NULL,
    runs INTEGER NOT NULL,
    hits INTEGER NOT NULL,
    doubles INTEGER NOT NULL,
    triples INTEGER NOT NULL,
    home_runs INTEGER NOT NULL,
    rbi INTEGER NOT NULL,
    walks INTEGER NOT NULL,
    strikeouts INTEGER NOT NULL,
    hit_by_pitch INTEGER NOT NULL,
    sacrifice_flies INTEGER NOT NULL,
    sacrifice_bunts INTEGER NOT NULL,
    stolen_bases INTEGER NOT NULL,
    caught_stealing INTEGER NOT NULL,
    singles INTEGER NOT NULL,
    PRIMARY KEY (year, competition_id, match_id, player_id),
    FOREIGN KEY (year, competition_id, match_id)
      REFERENCES ability_matches(year, competition_id, match_id)
      ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pitcher_game_stats (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    outs_recorded INTEGER NOT NULL,
    batters_faced INTEGER NOT NULL,
    runs_allowed INTEGER NOT NULL,
    earned_runs INTEGER NOT NULL,
    hits_allowed INTEGER NOT NULL,
    home_runs_allowed INTEGER NOT NULL,
    walks INTEGER NOT NULL,
    strikeouts INTEGER NOT NULL,
    hit_batters INTEGER NOT NULL,
    PRIMARY KEY (year, competition_id, match_id, player_id),
    FOREIGN KEY (year, competition_id, match_id)
      REFERENCES ability_matches(year, competition_id, match_id)
      ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS team_game_stats (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    runs INTEGER NOT NULL,
    hits INTEGER NOT NULL,
    errors INTEGER NOT NULL,
    PRIMARY KEY (year, competition_id, match_id, school_id),
    FOREIGN KEY (year, competition_id, match_id)
      REFERENCES ability_matches(year, competition_id, match_id)
      ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS match_events (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    event_no INTEGER NOT NULL,
    plate_appearance_no INTEGER NOT NULL,
    inning INTEGER NOT NULL,
    half TEXT NOT NULL,
    offense_school_id TEXT NOT NULL,
    defense_school_id TEXT NOT NULL,
    batter_id TEXT NOT NULL,
    pitcher_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    runs_scored INTEGER NOT NULL,
    outs_on_play INTEGER NOT NULL,
    rbi INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (year, competition_id, match_id, event_no),
    FOREIGN KEY (year, competition_id, match_id)
      REFERENCES ability_matches(year, competition_id, match_id)
      ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ability_matches_year_comp
    ON ability_matches(year, competition_id, match_id);
CREATE INDEX IF NOT EXISTS idx_batter_stats_year_player
    ON batter_game_stats(year, player_id, competition_id, match_id);
CREATE INDEX IF NOT EXISTS idx_batter_stats_year_school
    ON batter_game_stats(year, school_id, competition_id, match_id);
CREATE INDEX IF NOT EXISTS idx_pitcher_stats_year_player
    ON pitcher_game_stats(year, player_id, competition_id, match_id);
CREATE INDEX IF NOT EXISTS idx_pitcher_stats_year_school
    ON pitcher_game_stats(year, school_id, competition_id, match_id);
CREATE INDEX IF NOT EXISTS idx_events_year_batter
    ON match_events(year, batter_id, competition_id, match_id, event_no);
CREATE INDEX IF NOT EXISTS idx_events_year_pitcher
    ON match_events(year, pitcher_id, competition_id, match_id, event_no);
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
    def _validate_match_result_detail(
        year: int,
        competition_id: str,
        match_id: str,
        detail: Mapping[str, object],
    ) -> None:
        if detail.get("match_id") != match_id:
            raise ValueError(
                f"{competition_id}/{match_id}: match_id mismatch"
            )
        if detail.get("competition_id") != competition_id:
            raise ValueError(
                f"{competition_id}/{match_id}: competition_id mismatch"
            )
        if int(detail.get("reference_year") or 0) != year:
            raise ValueError(
                f"{competition_id}/{match_id}: reference_year mismatch"
            )
        if detail.get("score_source") != "ability_model_v1":
            raise ValueError(
                f"{competition_id}/{match_id}: score_source must be ability_model_v1"
            )
        team1_score = detail.get("team1_score")
        team2_score = detail.get("team2_score")
        if (
            not isinstance(team1_score, int)
            or isinstance(team1_score, bool)
            or not isinstance(team2_score, int)
            or isinstance(team2_score, bool)
            or team1_score < 0
            or team2_score < 0
            or team1_score == team2_score
        ):
            raise ValueError(
                f"{competition_id}/{match_id}: invalid score"
            )

    def _replace_match_results_conn(
        self,
        conn: sqlite3.Connection,
        season: SeasonExecution,
    ) -> dict:
        year = season.year
        match_count = 0
        batter_count = 0
        pitcher_count = 0
        team_count = 0
        event_count = 0

        for competition_id, run in sorted(season.competition_runs.items()):
            for match_id, detail in sorted(
                (run.match_simulation_results or {}).items()
            ):
                self._validate_match_result_detail(
                    year,
                    competition_id,
                    match_id,
                    detail,
                )
                conn.execute(
                    """
                    INSERT INTO ability_matches (
                        year, competition_id, match_id, generation_seed,
                        team1_school_id, team2_school_id,
                        team1_score, team2_score, winner_id, loser_id,
                        last_inning, ending_half, score_source,
                        match_config_id, match_config_revision, match_config_sha256,
                        event_catalog_id, event_catalog_revision, event_catalog_sha256,
                        stats_config_id, stats_config_revision, stats_config_sha256
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        year,
                        competition_id,
                        match_id,
                        int(detail["generation_seed"]),
                        str(detail["team1_school_id"]),
                        str(detail["team2_school_id"]),
                        int(detail["team1_score"]),
                        int(detail["team2_score"]),
                        str(detail["winner_id"]),
                        str(detail["loser_id"]),
                        int(detail["last_inning"]),
                        str(detail["ending_half"]),
                        str(detail["score_source"]),
                        str(detail["match_config_id"]),
                        int(detail["match_config_revision"]),
                        str(detail["match_config_sha256"]),
                        str(detail["event_catalog_id"]),
                        int(detail["event_catalog_revision"]),
                        str(detail["event_catalog_sha256"]),
                        str(detail["stats_config_id"]),
                        int(detail["stats_config_revision"]),
                        str(detail["stats_config_sha256"]),
                    ),
                )
                match_count += 1

                for row in detail.get("batter_stats", []):
                    conn.execute(
                        """
                        INSERT INTO batter_game_stats (
                            year, competition_id, match_id, player_id, school_id,
                            plate_appearances, at_bats, runs, hits, doubles, triples,
                            home_runs, rbi, walks, strikeouts, hit_by_pitch,
                            sacrifice_flies, sacrifice_bunts, stolen_bases,
                            caught_stealing, singles
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            year,
                            competition_id,
                            match_id,
                            row["player_id"],
                            row["school_id"],
                            int(row["plate_appearances"]),
                            int(row["at_bats"]),
                            int(row["runs"]),
                            int(row["hits"]),
                            int(row["doubles"]),
                            int(row["triples"]),
                            int(row["home_runs"]),
                            int(row["rbi"]),
                            int(row["walks"]),
                            int(row["strikeouts"]),
                            int(row["hit_by_pitch"]),
                            int(row["sacrifice_flies"]),
                            int(row["sacrifice_bunts"]),
                            int(row["stolen_bases"]),
                            int(row["caught_stealing"]),
                            int(row["singles"]),
                        ),
                    )
                    batter_count += 1

                for row in detail.get("pitcher_stats", []):
                    conn.execute(
                        """
                        INSERT INTO pitcher_game_stats (
                            year, competition_id, match_id, player_id, school_id,
                            outs_recorded, batters_faced, runs_allowed, earned_runs,
                            hits_allowed, home_runs_allowed, walks, strikeouts, hit_batters
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            year,
                            competition_id,
                            match_id,
                            row["player_id"],
                            row["school_id"],
                            int(row["outs_recorded"]),
                            int(row["batters_faced"]),
                            int(row["runs_allowed"]),
                            int(row["earned_runs"]),
                            int(row["hits_allowed"]),
                            int(row["home_runs_allowed"]),
                            int(row["walks"]),
                            int(row["strikeouts"]),
                            int(row["hit_batters"]),
                        ),
                    )
                    pitcher_count += 1

                for row in detail.get("team_stats", []):
                    conn.execute(
                        """
                        INSERT INTO team_game_stats (
                            year, competition_id, match_id, school_id,
                            runs, hits, errors
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            year,
                            competition_id,
                            match_id,
                            row["school_id"],
                            int(row["runs"]),
                            int(row["hits"]),
                            int(row["errors"]),
                        ),
                    )
                    team_count += 1

                for row in detail.get("events", []):
                    conn.execute(
                        """
                        INSERT INTO match_events (
                            year, competition_id, match_id, event_no,
                            plate_appearance_no, inning, half,
                            offense_school_id, defense_school_id,
                            batter_id, pitcher_id, event_type,
                            runs_scored, outs_on_play, rbi, metadata_json
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            year,
                            competition_id,
                            match_id,
                            int(row["event_no"]),
                            int(row["plate_appearance_no"]),
                            int(row["inning"]),
                            str(row["half"]),
                            str(row["offense_school_id"]),
                            str(row["defense_school_id"]),
                            str(row["batter_id"]),
                            str(row["pitcher_id"]),
                            str(row["event_type"]),
                            int(row["runs_scored"]),
                            int(row["outs_on_play"]),
                            int(row["rbi"]),
                            json.dumps(
                                row.get("metadata", {}),
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        ),
                    )
                    event_count += 1

        return {
            "ability_match_count": match_count,
            "batter_game_stat_count": batter_count,
            "pitcher_game_stat_count": pitcher_count,
            "team_game_stat_count": team_count,
            "match_event_count": event_count,
        }

    def replace_season_match_results(
        self,
        season: SeasonExecution,
    ) -> dict:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            with conn:
                if conn.execute(
                    "SELECT 1 FROM browse_seasons WHERE year = ?",
                    (season.year,),
                ).fetchone() is None:
                    raise ValueError(
                        "browse season must be stored before match results"
                    )
                for table in (
                    "match_events",
                    "team_game_stats",
                    "pitcher_game_stats",
                    "batter_game_stats",
                    "ability_matches",
                ):
                    conn.execute(
                        f"DELETE FROM {table} WHERE year = ?",
                        (season.year,),
                    )
                return self._replace_match_results_conn(conn, season)

    def ability_match(
        self,
        year: int,
        competition_id: str,
        match_id: str,
    ) -> dict | None:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            row = conn.execute(
                """
                SELECT * FROM ability_matches
                WHERE year = ? AND competition_id = ? AND match_id = ?
                """,
                (year, competition_id, match_id),
            ).fetchone()
            return dict(row) if row is not None else None

    def player_batter_game_stats(
        self,
        year: int,
        player_id: str,
    ) -> list[dict]:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                """
                SELECT * FROM batter_game_stats
                WHERE year = ? AND player_id = ?
                ORDER BY competition_id, match_id
                """,
                (year, player_id),
            ))

    def player_pitcher_game_stats(
        self,
        year: int,
        player_id: str,
    ) -> list[dict]:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                """
                SELECT * FROM pitcher_game_stats
                WHERE year = ? AND player_id = ?
                ORDER BY competition_id, match_id
                """,
                (year, player_id),
            ))

    def events_for_match(
        self,
        year: int,
        competition_id: str,
        match_id: str,
    ) -> list[dict]:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                """
                SELECT * FROM match_events
                WHERE year = ? AND competition_id = ? AND match_id = ?
                ORDER BY event_no
                """,
                (year, competition_id, match_id),
            ))

    def aggregate_batter_counts(
        self,
        year: int,
        *,
        competition_id: str = "",
        school_id: str = "",
        player_id: str = "",
    ) -> list[dict]:
        clauses = ["b.year = ?"]
        params: list[object] = [year]
        if competition_id:
            clauses.append("b.competition_id = ?")
            params.append(competition_id)
        if school_id:
            clauses.append("b.school_id = ?")
            params.append(school_id)
        if player_id:
            clauses.append("b.player_id = ?")
            params.append(player_id)

        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                f"""
                SELECT
                    b.player_id,
                    b.school_id,
                    COALESCE(s.school_name, '') AS school_name,
                    COUNT(*) AS games,
                    SUM(b.plate_appearances) AS plate_appearances,
                    SUM(b.at_bats) AS at_bats,
                    SUM(b.runs) AS runs,
                    SUM(b.hits) AS hits,
                    SUM(b.singles) AS singles,
                    SUM(b.doubles) AS doubles,
                    SUM(b.triples) AS triples,
                    SUM(b.home_runs) AS home_runs,
                    SUM(b.rbi) AS rbi,
                    SUM(b.walks) AS walks,
                    SUM(b.strikeouts) AS strikeouts,
                    SUM(b.hit_by_pitch) AS hit_by_pitch,
                    SUM(b.sacrifice_flies) AS sacrifice_flies,
                    SUM(b.sacrifice_bunts) AS sacrifice_bunts,
                    SUM(b.stolen_bases) AS stolen_bases,
                    SUM(b.caught_stealing) AS caught_stealing
                FROM batter_game_stats AS b
                LEFT JOIN school_records AS s
                  ON s.year = b.year
                 AND s.school_id = b.school_id
                WHERE {' AND '.join(clauses)}
                GROUP BY b.player_id, b.school_id, s.school_name
                ORDER BY b.school_id, b.player_id
                """,
                params,
            ))

    def aggregate_pitcher_counts(
        self,
        year: int,
        *,
        competition_id: str = "",
        school_id: str = "",
        player_id: str = "",
    ) -> list[dict]:
        clauses = ["p.year = ?"]
        params: list[object] = [year]
        if competition_id:
            clauses.append("p.competition_id = ?")
            params.append(competition_id)
        if school_id:
            clauses.append("p.school_id = ?")
            params.append(school_id)
        if player_id:
            clauses.append("p.player_id = ?")
            params.append(player_id)

        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                f"""
                SELECT
                    p.player_id,
                    p.school_id,
                    COALESCE(s.school_name, '') AS school_name,
                    COUNT(*) AS games,
                    SUM(p.outs_recorded) AS outs_recorded,
                    SUM(p.batters_faced) AS batters_faced,
                    SUM(p.runs_allowed) AS runs_allowed,
                    SUM(p.earned_runs) AS earned_runs,
                    SUM(p.hits_allowed) AS hits_allowed,
                    SUM(p.home_runs_allowed) AS home_runs_allowed,
                    SUM(p.walks) AS walks,
                    SUM(p.strikeouts) AS strikeouts,
                    SUM(p.hit_batters) AS hit_batters
                FROM pitcher_game_stats AS p
                LEFT JOIN school_records AS s
                  ON s.year = p.year
                 AND s.school_id = p.school_id
                WHERE {' AND '.join(clauses)}
                GROUP BY p.player_id, p.school_id, s.school_name
                ORDER BY p.school_id, p.player_id
                """,
                params,
            ))

    def team_game_counts(
        self,
        year: int,
        *,
        competition_id: str = "",
        school_id: str = "",
    ) -> dict[str, int]:
        clauses = ["year = ?"]
        params: list[object] = [year]
        if competition_id:
            clauses.append("competition_id = ?")
            params.append(competition_id)
        if school_id:
            clauses.append("school_id = ?")
            params.append(school_id)

        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            rows = conn.execute(
                f"""
                SELECT school_id, COUNT(*) AS team_games
                FROM team_game_stats
                WHERE {' AND '.join(clauses)}
                GROUP BY school_id
                """,
                params,
            ).fetchall()
            return {
                str(row["school_id"]): int(row["team_games"])
                for row in rows
            }

    @staticmethod
    def _rows(cursor: sqlite3.Cursor) -> list[dict]:
        return [dict(row) for row in cursor.fetchall()]

    def list_years(self) -> list[int]:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            rows = conn.execute(
                "SELECT year FROM browse_seasons ORDER BY year DESC"
            ).fetchall()
            return [int(row["year"]) for row in rows]

    def list_match_dates(
        self,
        year: int,
        *,
        include_undated: bool = False,
    ) -> list[str]:
        clauses = ["year = ?"]
        params: list[object] = [year]
        if not include_undated:
            clauses.append("match_date <> ''")
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            rows = conn.execute(
                f"""
                SELECT match_date
                FROM matches_by_date
                WHERE {' AND '.join(clauses)}
                GROUP BY match_date
                ORDER BY
                    CASE WHEN match_date = '' THEN 1 ELSE 0 END,
                    match_date
                """,
                params,
            ).fetchall()
            return [str(row["match_date"]) for row in rows]

    def list_prefecture_codes(self, year: int) -> list[str]:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            rows = conn.execute(
                """
                SELECT DISTINCT prefecture_code
                FROM school_records
                WHERE year = ? AND prefecture_code <> ''
                ORDER BY prefecture_code
                """,
                (year,),
            ).fetchall()
            return [str(row["prefecture_code"]) for row in rows]

    def list_season_segments(self, year: int) -> list[str]:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            rows = conn.execute(
                """
                SELECT DISTINCT season_segment
                FROM competition_results
                WHERE year = ? AND season_segment <> ''
                ORDER BY season_segment
                """,
                (year,),
            ).fetchall()
            return [str(row["season_segment"]) for row in rows]

    def list_competition_types(
        self,
        year: int,
        *,
        season_segment: str = "",
    ) -> list[str]:
        clauses = ["year = ?", "competition_type <> ''"]
        params: list[object] = [year]
        if season_segment:
            clauses.append("season_segment = ?")
            params.append(season_segment)

        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            rows = conn.execute(
                f"""
                SELECT DISTINCT competition_type
                FROM competition_results
                WHERE {' AND '.join(clauses)}
                ORDER BY competition_type
                """,
                params,
            ).fetchall()
            return [str(row["competition_type"]) for row in rows]

    def season_meta(self, year: int) -> dict | None:
        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            row = conn.execute(
                "SELECT * FROM browse_seasons WHERE year = ?",
                (year,),
            ).fetchone()
            return dict(row) if row is not None else None

    def matches_for_date_filtered(
        self,
        year: int,
        match_date: str,
        *,
        competition_id: str = "",
        prefecture_code: str = "",
        season_segment: str = "",
        competition_type: str = "",
    ) -> list[dict]:
        if match_date:
            date.fromisoformat(match_date)

        clauses = [
            "m.year = ?",
            "m.match_date = ?",
        ]
        params: list[object] = [year, match_date]

        if competition_id:
            clauses.append("m.competition_id = ?")
            params.append(competition_id)

        if prefecture_code:
            clauses.append(
                "(s1.prefecture_code = ? OR s2.prefecture_code = ?)"
            )
            params.extend([prefecture_code, prefecture_code])
        if season_segment:
            clauses.append("m.season_segment = ?")
            params.append(season_segment)
        if competition_type:
            clauses.append("m.competition_type = ?")
            params.append(competition_type)

        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                f"""
                SELECT
                    m.*,
                    s1.prefecture_code AS team1_prefecture_code,
                    s2.prefecture_code AS team2_prefecture_code
                FROM matches_by_date AS m
                LEFT JOIN school_records AS s1
                  ON s1.year = m.year
                 AND s1.school_id = m.team1_id
                LEFT JOIN school_records AS s2
                  ON s2.year = m.year
                 AND s2.school_id = m.team2_id
                WHERE {' AND '.join(clauses)}
                ORDER BY
                    m.competition_name,
                    m.round_no,
                    m.match_id
                """,
                params,
            ))

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

    def list_competitions(
        self,
        year: int,
    ) -> list[dict]:
        return self.list_competitions_filtered(year)

    def list_competitions_filtered(
        self,
        year: int,
        *,
        season_segment: str = "",
        competition_type: str = "",
    ) -> list[dict]:
        clauses = ["year = ?"]
        params: list[object] = [year]
        if season_segment:
            clauses.append("season_segment = ?")
            params.append(season_segment)
        if competition_type:
            clauses.append("competition_type = ?")
            params.append(competition_type)

        with self._connect() as conn:
            self._initialize_schema_conn(conn)
            return self._rows(conn.execute(
                f"""
                SELECT * FROM competition_results
                WHERE {' AND '.join(clauses)}
                ORDER BY start_date, competition_id
                """,
                params,
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
    summary = repository.replace_season_views(
        season.year,
        season.rng_seed,
        views,
    )
    summary.update(repository.replace_season_match_results(season))
    return summary
