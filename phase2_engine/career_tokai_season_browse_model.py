"""Stage43G-54: strict read-only Tokai 2027 career-season browse projection.

The A-history SQLite archive is the only source for game scores/individual
box scores. A list of archived games is NOT proof of bracket completion or
official 2027 entrants. Navigation uses saved IDs, never displayed labels.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path

from .career_history_browse_model import (
    CareerHistoryBrowseModel, SOURCE,
)
from .career_option_a_storage_profile import _read_only

SENBATSU = "CMP000001"
GIFU = "CMP000109"
SHIZUOKA = "CMP000111"
AICHI = "CMP000113"
MIE = "CMP000115"
TOKAI = "CMP000008"
TOKAI_SEASON_IDS = (SENBATSU, GIFU, SHIZUOKA, AICHI, MIE, TOKAI)
TOKAI_LABELS = {
    SENBATSU: "全国選抜（同年度の免除資格の根拠）",
    GIFU: "岐阜県春季",
    SHIZUOKA: "静岡県春季",
    AICHI: "愛知県春季",
    MIE: "三重県春季",
    TOKAI: "春季東海地区",
}


class TokaiSeasonBrowseConflict(ValueError):
    """Invalid identity, tampered stored game or unavailable view."""


class CareerTokaiSeasonBrowseModel:
    """Opt-in season/competition/school/match/player read-only navigation."""

    def __init__(self, data_root: str | Path, slot_root: str | Path):
        self.source = CareerHistoryBrowseModel(data_root, slot_root)
        self.path = self.source.history.db_path

    def _year(self, year: int) -> None:
        if type(year) is not int or year <= 2026:
            raise TokaiSeasonBrowseConflict("future Tokai career year required")
        if year not in {x["year"] for x in self.source.years()}:
            raise TokaiSeasonBrowseConflict("career season is not archived")

    @staticmethod
    def _page(offset: int, limit: int) -> None:
        if (type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= 100):
            raise TokaiSeasonBrowseConflict("invalid match browse pagination")

    @staticmethod
    def _competition(cid: str) -> None:
        if cid not in TOKAI_SEASON_IDS:
            raise TokaiSeasonBrowseConflict("not part of the Tokai season view")

    def _games(self, year: int) -> list[dict]:
        self._year(year)
        placeholders = ",".join("?" for _ in TOKAI_SEASON_IDS)
        # SQLite URI query_only=ON prevents sidecar creation or DB writes.
        try:
            with closing(_read_only(self.path)) as conn:
                conn.row_factory = __import__("sqlite3").Row
                rows = conn.execute(
                    "SELECT year,competition_id,match_id,match_date,"
                    "record_sha256,payload_json FROM historical_matches "
                    f"WHERE year=? AND competition_id IN ({placeholders}) "
                    "ORDER BY match_date,competition_id,match_id",
                    (year, *TOKAI_SEASON_IDS),
                ).fetchall()
        except (OSError, __import__("sqlite3").DatabaseError) as exc:
            raise TokaiSeasonBrowseConflict("Tokai A-history archive unreadable") from exc
        result = []
        seen = set()
        for row in rows:
            raw = row["payload_json"]
            if (type(raw) is not str
                    or sha256(raw.encode("utf-8")).hexdigest()
                    != row["record_sha256"]):
                raise TokaiSeasonBrowseConflict("archived Tokai game SHA changed")
            try:
                game = json.loads(raw)
            except (ValueError, TypeError) as exc:
                raise TokaiSeasonBrowseConflict("archived Tokai game invalid") from exc
            key = (row["competition_id"], row["match_id"])
            teams = [game.get("team1_id"), game.get("team2_id")]
            if (key in seen
                    or game.get("year") != year
                    or game.get("competition_id") != key[0]
                    or game.get("match_id") != key[1]
                    or game.get("match_date") != row["match_date"]
                    or len(set(teams)) != 2
                    or any(type(s) is not str or s not in self.source.repo.schools
                           for s in teams)
                    or game.get("winner_id") not in teams
                    or game.get("loser_id") not in teams
                    or game["winner_id"] == game["loser_id"]):
                raise TokaiSeasonBrowseConflict("archived Tokai game identity differs")
            seen.add(key)
            result.append({
                "year": year, "competition_id": key[0], "match_id": key[1],
                "match_date": row["match_date"],
                "team1_id": teams[0], "team2_id": teams[1],
                "team1_score": game.get("team1_score"),
                "team2_score": game.get("team2_score"),
                "winner_id": game["winner_id"],
                "score_source": game.get("score_source"),
                "has_inning_scores": game.get("inning_scores") is not None,
                "has_individual_stats": (
                    game.get("batter_stats") is not None
                    and game.get("pitcher_stats") is not None
                ),
                "match_target": {
                    "screen": "match", "year": year,
                    "competition_id": key[0], "match_id": key[1],
                },
            })
        return result

    def overview(self, year: int) -> dict:
        games = self._games(year)
        events = []
        for cid in TOKAI_SEASON_IDS:
            selected = [x for x in games if x["competition_id"] == cid]
            schools = {
                s for x in selected for s in (x["team1_id"], x["team2_id"])
            }
            events.append({
                "competition_id": cid, "label": TOKAI_LABELS[cid],
                "archived_match_count": len(selected),
                "schools_seen_in_saved_games": len(schools),
                "latest_saved_game_date": (
                    max(x["match_date"] for x in selected) if selected else None
                ),
                "competition_target": {
                    "screen": "competition", "year": year,
                    "competition_id": cid,
                },
                "bracket_completed_or_advancement_proven": False,
            })
        return {
            "screen": "tokai_season", "year": year,
            "events": events, "archived_match_count": len(games),
            "source_kind": SOURCE, "read_only": True,
            "official_future_results": False,
            "regional_qualifiers_inferred_from_scores": False,
            "first_saved_game_date": games[0]["match_date"] if games else None,
        }

    def competition(self, year: int, cid: str, *,
                    offset: int = 0, limit: int = 50) -> dict:
        self._competition(cid)
        self._page(offset, limit)
        rows = [x for x in self._games(year) if x["competition_id"] == cid]
        page = rows[offset: offset + limit]
        return {
            "screen": "tokai_competition", "year": year,
            "competition_id": cid, "label": TOKAI_LABELS[cid],
            "matches": {"rows": page, "total": len(rows),
                        "offset": offset, "limit": limit},
            "school_targets": [
                {"screen": "school", "year": year, "school_id": sid}
                for sid in sorted({
                    team for g in page for team in (g["team1_id"], g["team2_id"])
                })
            ],
            "read_only": True, "source_kind": SOURCE,
            "bracket_champion_or_feeder_proven": False,
        }

    def school(self, year: int, school_id: str, *,
               offset: int = 0, limit: int = 50) -> dict:
        self._page(offset, limit)
        if school_id not in self.source.repo.school_to_program:
            raise TokaiSeasonBrowseConflict("unknown hardball school ID")
        games = [
            x for x in self._games(year)
            if school_id in (x["team1_id"], x["team2_id"])
        ]
        window = games[offset: offset + limit]
        roster = self.source.rosters.roster(year, school_id)
        return {
            "screen": "tokai_school", "year": year,
            "school_id": school_id,
            "school_name": self.source.repo.schools[school_id].get(
                "school_name", school_id,
            ),
            "matches": {"rows": window, "total": len(games),
                        "offset": offset, "limit": limit},
            "archived_wins": sum(x["winner_id"] == school_id for x in games),
            "archived_losses": sum(x["winner_id"] != school_id for x in games),
            "roster_known": roster is not None,
            "player_targets": (
                [{"screen": "player", "year": year, "player_id": p.player_id}
                 for p in roster.players]
                if roster is not None else []
            ),
            "source_kind": SOURCE, "read_only": True,
            "all_real_world_season_games_known": False,
        }

    def match(self, year: int, cid: str, match_id: str) -> dict:
        self._competition(cid)
        if type(match_id) is not str or not match_id:
            raise TokaiSeasonBrowseConflict("saved match ID required")
        if not any(
            x["competition_id"] == cid and x["match_id"] == match_id
            for x in self._games(year)
        ):
            raise TokaiSeasonBrowseConflict("Tokai match ID not in archived year")
        page = self.source.match_page(year, cid, match_id)
        game = page["game"]
        ids = set()
        for section in ("batter_stats", "pitcher_stats"):
            for row in game.get(section) or []:
                if (isinstance(row, dict)
                        and isinstance(row.get("player_id"), str)
                        and row.get("school_id") in {
                            game["team1_id"], game["team2_id"],
                        }):
                    ids.add(row["player_id"])
        return {
            **page,
            "screen": "tokai_match",
            "school_targets": [
                {"screen": "school", "year": year, "school_id": sid}
                for sid in (game["team1_id"], game["team2_id"])
            ],
            "player_targets": [
                {"screen": "player", "year": year, "player_id": pid}
                for pid in sorted(ids)
            ],
            "source_kind": SOURCE, "read_only": True,
            "official_future_results": False,
        }

    def player(self, year: int, player_id: str) -> dict:
        if type(player_id) is not str or not player_id:
            raise TokaiSeasonBrowseConflict("career player ID required")
        # The existing history model validates stored roster identity and
        # reconstructs career totals only from saved Option-A box scores.
        self._year(year)
        page = self.source.player_page(year, player_id)
        if not any(
            page["school_id"] in (x["team1_id"], x["team2_id"])
            for x in self._games(year)
        ):
            raise TokaiSeasonBrowseConflict("player school has no Tokai games")
        return {
            **page, "screen": "tokai_player",
            "school_target": {
                "screen": "school", "year": year,
                "school_id": page["school_id"],
            },
            "source_kind": SOURCE, "read_only": True,
            "official_future_results": False,
        }

    def open(self, target: dict) -> dict:
        """GUI-ready stable-ID navigation; never resolve display-name links."""
        if not isinstance(target, dict) or type(target.get("year")) is not int:
            raise TokaiSeasonBrowseConflict("invalid Tokai navigation target")
        year = target["year"]
        screen = target.get("screen")
        if screen == "tokai_season" and set(target) == {"screen", "year"}:
            return self.overview(year)
        if screen == "competition" and set(target) == {
            "screen", "year", "competition_id",
        }:
            return self.competition(year, target["competition_id"])
        if screen == "school" and set(target) == {
            "screen", "year", "school_id",
        }:
            return self.school(year, target["school_id"])
        if screen == "match" and set(target) == {
            "screen", "year", "competition_id", "match_id",
        }:
            return self.match(year, target["competition_id"], target["match_id"])
        if screen == "player" and set(target) == {
            "screen", "year", "player_id",
        }:
            return self.player(year, target["player_id"])
        raise TokaiSeasonBrowseConflict("unsupported Tokai navigation target")
