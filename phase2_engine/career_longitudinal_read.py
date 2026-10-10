"""Stage43G-12: indexed, paginated school history and stable alumni-ID views.

SQL uses the existing by-year, by-school and player-identity indexes. The
result is read-only; no thousands-of-schools full-history JSON is materialized.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .career_roster_archive import CareerRosterArchive, CareerRosterConflictError
from .historical_match_archive import HistoricalMatchArchive


def _iter_school_games(path: Path, school_id: str,
                       start_year: int, end_year: int):
    """Single-index school history generator: rows stay in SQLite until read."""
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT year, competition_id, match_id, team1_id, team2_id,
                   team1_score, team2_score, record_sha256, payload_json
              FROM historical_matches
             WHERE team1_id=? AND year BETWEEN ? AND ?
            UNION ALL
            SELECT year, competition_id, match_id, team1_id, team2_id,
                   team1_score, team2_score, record_sha256, payload_json
              FROM historical_matches
             WHERE team2_id=? AND year BETWEEN ? AND ?
            ORDER BY year, competition_id, match_id
            """,
            (school_id, start_year, end_year,
             school_id, start_year, end_year),
        )
        yield from cursor


class CareerHistoryViewConflict(ValueError):
    """An archived A-record or immutable player identity changed."""


class CareerLongitudinalReadModel:
    def __init__(self, match_archive: HistoricalMatchArchive | str | Path,
                 roster_archive: CareerRosterArchive | str | Path):
        self.matches = (
            match_archive if isinstance(match_archive, HistoricalMatchArchive)
            else HistoricalMatchArchive(match_archive)
        )
        self.rosters = (
            roster_archive if isinstance(roster_archive, CareerRosterArchive)
            else CareerRosterArchive(roster_archive)
        )

    @staticmethod
    def _page(limit: int, offset: int) -> None:
        if (not isinstance(limit, int) or isinstance(limit, bool)
                or not 1 <= limit <= 200
                or not isinstance(offset, int) or isinstance(offset, bool)
                or offset < 0):
            raise ValueError("invalid indexed history page")

    def school_results(self, school_id: str, *, start_year: int,
                       end_year: int, limit: int = 100,
                       offset: int = 0) -> dict:
        """Aggregate scores by game year+competition, not individual at-bats.

        This is a game-result view, *not* an invented district ranking:
        tournament champion/runner-up are stored by the separate outcome model.
        """
        self._page(limit, offset)
        if (not isinstance(school_id, str) or not school_id
                or not isinstance(start_year, int) or isinstance(start_year, bool)
                or not isinstance(end_year, int) or isinstance(end_year, bool)
                or start_year < 1 or end_year < start_year):
            raise ValueError("invalid school/year window")
        if not self.matches.db_path.is_file():
            return {"school_id": school_id, "records": [],
                    "total_groups": 0, "limit": limit, "offset": offset}
        # Stream only this school's rows through the two team/year indexes.
        # Never materialize all 50/100-year match payloads or all year-groups
        # merely to return a requested page. Every visited game still passes
        # its original content-hash and score-consistency verification.
        rows = _iter_school_games(
            self.matches.db_path, school_id, start_year, end_year,
        )
        page: list[dict] = []
        total_groups = 0
        current_key = None
        group = None

        def flush() -> None:
            nonlocal total_groups
            if group is None:
                return
            if offset <= total_groups < offset + limit:
                page.append(group)
            total_groups += 1

        for record in rows:
            raw = record["payload_json"]
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != record["record_sha256"]:
                raise CareerHistoryViewConflict("archived match digest differs")
            data = json.loads(raw)
            if (data["year"] != record["year"]
                    or data["competition_id"] != record["competition_id"]
                    or data["match_id"] != record["match_id"]
                    or data["team1_id"] != record["team1_id"]
                    or data["team2_id"] != record["team2_id"]
                    or data["team1_score"] != record["team1_score"]
                    or data["team2_score"] != record["team2_score"]
                    or data["winner_id"] not in (
                        record["team1_id"], record["team2_id"]
                    )):
                raise CareerHistoryViewConflict("archived match identity differs")
            first = school_id == data["team1_id"]
            a = data["team1_score"] if first else data["team2_score"]
            b = data["team2_score"] if first else data["team1_score"]
            if a is None or b is None:
                raise CareerHistoryViewConflict("archived completed score missing")
            if ((a > b) != (data["winner_id"] == school_id)):
                raise CareerHistoryViewConflict("archived winner differs from score")
            key = (record["year"], record["competition_id"])
            if key != current_key:
                flush()
                current_key = key
                group = {
                    "year": record["year"],
                    "competition_id": record["competition_id"],
                    "games": 0, "wins": 0, "losses": 0,
                    "runs_for": 0, "runs_against": 0,
                    "historical_record_source": "archived_game_scores",
                }
            group["games"] += 1
            group["wins"] += int(a > b)
            group["losses"] += int(a < b)
            group["runs_for"] += a
            group["runs_against"] += b
        flush()
        return {
            "school_id": school_id,
            "start_year": start_year, "end_year": end_year,
            "records": page,
            "total_groups": total_groups, "limit": limit, "offset": offset,
            "rankings_inferred": False,
        }

    def school_player_index(self, school_id: str, *, limit: int = 100,
                            offset: int = 0) -> dict:
        """Page stable player identities, including former squad members.

        'not_on_latest_saved_roster' is not necessarily graduation: it merely
        means the player was not present in the latest saved school roster.
        """
        self._page(limit, offset)
        if not isinstance(school_id, str) or not school_id:
            raise ValueError("invalid school ID")
        if not self.rosters.db_path.is_file():
            return {"school_id": school_id, "players": [], "total": 0,
                    "limit": limit, "offset": offset}
        with sqlite3.connect(self.rosters.db_path) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                "SELECT COUNT(*) FROM career_player_identities WHERE school_id=?",
                (school_id,),
            ).fetchone()[0]
            identities = conn.execute(
                "SELECT player_id, school_id, entry_year, identity_sha256, identity_json "
                "FROM career_player_identities "
                "WHERE school_id=? ORDER BY entry_year, player_id LIMIT ? OFFSET ?",
                (school_id, limit, offset),
            ).fetchall()
            latest = conn.execute(
                "SELECT MAX(year) FROM career_school_rosters WHERE school_id=?",
                (school_id,),
            ).fetchone()[0]
            if latest is None and identities:
                raise CareerHistoryViewConflict("player identities lack roster snapshots")
            current = self.rosters._get(conn, latest, school_id) if latest is not None else None
            active_ids = {p.player_id for p in current.players} if current else set()
        players = []
        for item in identities:
            raw = item["identity_json"]
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != item["identity_sha256"]:
                raise CareerHistoryViewConflict("career player identity digest differs")
            identity = json.loads(raw)
            if (identity.get("player_id") != item["player_id"]
                    or identity.get("school_id") != school_id
                    or identity.get("entry_year") != item["entry_year"]):
                raise CareerHistoryViewConflict("career player identity metadata differs")
            players.append({
                "player_id": item["player_id"],
                "school_id": school_id,
                "entry_year": item["entry_year"],
                "display_name": identity["display_name"],
                "last_saved_roster_year": latest,
                "latest_roster_status": (
                    "on_latest_saved_roster"
                    if item["player_id"] in active_ids
                    else "not_on_latest_saved_roster"
                ),
            })
        return {
            "school_id": school_id,
            "players": players, "total": total,
            "limit": limit, "offset": offset,
            "status_is_graduation_proof": False,
        }

    def player_years(self, player_id: str) -> list[dict]:
        """Reuse the established immutable per-year roster decoder."""
        if not isinstance(player_id, str) or not player_id:
            raise ValueError("invalid player ID")
        return self.rosters.player_history(player_id)
