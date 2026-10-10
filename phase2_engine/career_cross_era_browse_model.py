"""Stage43G-31: source-separated cross-era school/player browse read model.

No implicit continuous save history, no cross-era career-stat summation,
no guessing a player identity by name/jersey and no game-year rollover.
The source archives, caches and snapshots are opened without writes.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from .career_cross_era_read_gate import CareerCrossEraReadGate
from .career_option_a_storage_profile import _read_only
from .career_player_records import CareerPlayerRecordView
from .career_roster_archive import CareerRosterArchive
from .career_v2_option_a_archive import CareerV2OptionAArchive
from .career_v2_roster_attribution import CareerV2RosterAttribution
from .career_v2_player_stat_cache import CareerV2PlayerStatCache


class CareerCrossEraBrowseConflict(ValueError):
    """A requested archived match or player cannot be verified."""


class CareerCrossEraBrowseModel:
    """Opt-in headless, read-only history views using Stage43G-30 routing."""

    def __init__(self, slot_root: str | Path):
        slot = Path(slot_root)
        self.gate = CareerCrossEraReadGate(
            slot / "historical_matches.sqlite3",
            slot / "fictional_option_a_v2.sqlite3",
            slot / "sandbox_calendar_v2.sqlite3",
        )
        self.rosters = CareerRosterArchive(slot / "career_rosters.sqlite3")
        self.legacy_players = CareerPlayerRecordView(
            self.gate.legacy_path, self.rosters,
        )
        self.v2 = self.gate.v2_archive
        self.attribution = CareerV2RosterAttribution(self.v2, self.rosters)
        self.v2_stats = CareerV2PlayerStatCache(
            self.attribution, slot / "fictional_v2_player_stat_cache.sqlite3",
        )

    @staticmethod
    def _checked_game(game: dict, year: int, school_id: str,
                      route: str) -> dict:
        if (game.get("year") != year
                or school_id not in (game.get("team1_id"), game.get("team2_id"))
                or not all(type(game.get(key)) is str and game[key]
                           for key in ("competition_id", "match_id"))):
            raise CareerCrossEraBrowseConflict("match identity or school differs")
        a, b = game.get("team1_score"), game.get("team2_score")
        if (type(a) is not int or type(b) is not int or a < 0 or b < 0
                or a == b
                or game.get("winner_id") !=
                (game["team1_id"] if a > b else game["team2_id"])):
            raise CareerCrossEraBrowseConflict("saved game score differs")
        date_kind = ("YYYY-MM-DD" if route == "historical_matches_legacy_iso"
                     else "G{year}:MM-DD")
        if route == "historical_matches_legacy_iso":
            token = game.get("match_date")
            from .career_calendar_v2 import GameDaySlot
            try:
                slot = GameDaySlot.from_iso(token)
            except ValueError as exc:
                raise CareerCrossEraBrowseConflict("legacy date invalid") from exc
            if slot.year != year:
                raise CareerCrossEraBrowseConflict("legacy match year differs")
        else:
            token = game.get("game_day_token")
            from .career_calendar_v2 import GameDaySlot
            try:
                slot = GameDaySlot.from_token(token)
            except ValueError as exc:
                raise CareerCrossEraBrowseConflict("v2 logical date invalid") from exc
            if (slot.year != year or token != game.get("match_date")):
                raise CareerCrossEraBrowseConflict("v2 logical match day differs")
        return {
            "year": year, "competition_id": game["competition_id"],
            "match_id": game["match_id"], "date": token,
            "date_kind": date_kind,
            "team1_id": game["team1_id"], "team2_id": game["team2_id"],
            "team1_score": a, "team2_score": b,
            "winner_id": game["winner_id"],
            "result_for_school": "win" if game["winner_id"] == school_id else "loss",
            "source": route, "full_option_a_source_retained": (
                route == "fictional_option_a_v2" or
                all(isinstance(game.get(key), list) for key in
                    ("inning_scores", "team_stats", "batter_stats", "pitcher_stats"))
            ),
        }

    def _legacy_games(self, year: int, school: str, source: str) -> list[dict]:
        records = []
        with closing(_read_only(self.gate.legacy_path)) as con:
            con.row_factory = sqlite3.Row
            for row in con.execute(
                "SELECT competition_id,match_id,record_sha256,payload_json "
                "FROM historical_matches WHERE year=? "
                "AND (team1_id=? OR team2_id=?) "
                "ORDER BY match_date,competition_id,match_id",
                (year, school, school),
            ):
                raw = row["payload_json"]
                if sha256(raw.encode("utf-8")).hexdigest() != row["record_sha256"]:
                    raise CareerCrossEraBrowseConflict("legacy match SHA changed")
                game = json.loads(raw)
                if (game.get("competition_id"), game.get("match_id")) != (
                    row["competition_id"], row["match_id"]
                ):
                    raise CareerCrossEraBrowseConflict("legacy match primary key changed")
                records.append(self._checked_game(game, year, school, source))
        return records

    def _future_games(self, year: int, school: str, source: str) -> list[dict]:
        first = self.v2.year_matches(year, limit=100)
        if first["year_status"] != "sealed":
            raise CareerCrossEraBrowseConflict("v2 year must be sealed")
        found = []
        for offset in range(0, first["total"], 100):
            page = (first if offset == 0 else
                    self.v2.year_matches(year, limit=100, offset=offset))
            if (page["year_status"] != "sealed"
                    or page["calendar_sha256"] != first["calendar_sha256"]
                    or page["total"] != first["total"]):
                raise CareerCrossEraBrowseConflict("v2 source changed while reading")
            for game in page["rows"]:
                if school in (game["team1_id"], game["team2_id"]):
                    found.append(self._checked_game(game, year, school, source))
        return found

    def school_years(self, years: list[int], school_id: str, *,
                     verify_source: bool = True) -> dict:
        """Per-year school score pages. No inferred bracket or career totals."""
        if type(school_id) is not str or not school_id:
            raise ValueError("school ID required")
        manifest = self.gate.inspect(years, verify_source=verify_source)
        sections = []
        for route in manifest["routes"]:
            year, source = route["year"], route["source"]
            rows = (
                self._legacy_games(year, school_id, source)
                if source == "historical_matches_legacy_iso"
                else self._future_games(year, school_id, source)
            )
            sections.append({
                "year": year, "source": source, "date_kind": route["date_kind"],
                "school_id": school_id, "matches": rows,
                "match_count": len(rows),
                "wins_from_saved_games": sum(
                    r["result_for_school"] == "win" for r in rows
                ),
                "losses_from_saved_games": sum(
                    r["result_for_school"] == "loss" for r in rows
                ),
                "tournament_champion_inferred": False,
            })
        return {
            "screen": "cross_era_school_years",
            "school_id": school_id, "sections": sections,
            "unverified_intervening_year_intervals":
                manifest["unverified_intervening_year_intervals"],
            "combined_career_stats_authorized": False,
            "source_payloads_rechecked": verify_source,
            "source_records_not_modified": True,
        }

    def player_years(self, years: list[int], school_id: str,
                     player_id: str, *, verify_source: bool = True) -> dict:
        """Source-separated player-year A records; never combine identity eras."""
        if (type(school_id) is not str or not school_id
                or type(player_id) is not str or not player_id):
            raise ValueError("school and permanent player IDs required")
        manifest = self.gate.inspect(years, verify_source=verify_source)
        sections = []
        any_member = False
        with closing(_read_only(self.rosters.db_path)) as roster_conn:
            roster_conn.row_factory = sqlite3.Row
            for route in manifest["routes"]:
                year, source = route["year"], route["source"]
                members = self.attribution._members(
                    roster_conn, year, school_id,
                )
                on_roster = player_id in members
                any_member |= on_roster
                if not on_roster:
                    sections.append({
                        "year": year, "source": source,
                        "status": "not_on_saved_school_year_roster",
                        "statistics": None, "year_roster_membership_verified": True,
                    })
                    continue
                if source == "historical_matches_legacy_iso":
                    raw = self.legacy_players.player_seasons(
                        player_id, start_year=year, end_year=year,
                    )
                    seasons = raw["seasons"]
                    missing = raw["games_without_box_scores"]
                else:
                    stat = self.v2_stats.read_year(
                        year, school_id, verify_source=verify_source,
                    )
                    seasons = [
                        item for item in stat["rows"]
                        if item["player_id"] == player_id
                    ]
                    missing = 0
                if len(seasons) > 1:
                    raise CareerCrossEraBrowseConflict(
                        "multiple annual records for permanent player"
                    )
                sections.append({
                    "year": year, "source": source,
                    "status": (
                        "verified_box_score" if seasons
                        else "on_roster_no_recorded_box_score"
                    ),
                    "statistics": seasons[0] if seasons else None,
                    "games_missing_box_scores": missing,
                    "year_roster_membership_verified": True,
                })
        if not any_member:
            raise CareerCrossEraBrowseConflict(
                "player ID was not on any explicitly selected year roster"
            )
        return {
            "screen": "cross_era_player_years",
            "school_id": school_id, "player_id": player_id,
            "sections": sections,
            "unverified_intervening_year_intervals":
                manifest["unverified_intervening_year_intervals"],
            "cross_year_player_identity_continuity_proven": False,
            "combined_career_totals": None,
            "source_payloads_rechecked": verify_source,
            "source_records_not_modified": True,
        }
