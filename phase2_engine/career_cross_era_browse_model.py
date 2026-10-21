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
from .career_v2_option_a_archive import (
    CareerV2OptionAArchive, _calendar_info, _verify_match,
)
from .career_v2_roster_attribution import CareerV2RosterAttribution
from .career_v2_player_stat_cache import CareerV2PlayerStatCache
from .historical_match_archive import expand_payload


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
                game = expand_payload(json.loads(raw))
                if (game.get("competition_id"), game.get("match_id")) != (
                    row["competition_id"], row["match_id"]
                ):
                    raise CareerCrossEraBrowseConflict("legacy match primary key changed")
                records.append(self._checked_game(game, year, school, source))
        return records

    def _future_games(self, year: int, school: str, source: str) -> list[dict]:
        # Preserve the same full verified-source semantics, but scan the
        # annual archive once instead of re-verifying it for every 100 rows.
        plan, plan_sha = _calendar_info(self.v2.calendar, year)
        status, rows = self.v2._verified_year(year, plan, plan_sha)
        if status != "sealed":
            raise CareerCrossEraBrowseConflict("v2 year must be sealed")
        return [
            self._checked_game(game, year, school, source)
            for game in rows if school in (game["team1_id"], game["team2_id"])
        ]

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

    def match_detail(self, years: list[int], school_id: str, *,
                     selected_year: int, competition_id: str, match_id: str,
                     verify_source: bool = True) -> dict:
        """Read one immutable match from exactly one verified saved year.

        Do not manufacture inning scores or player box scores for older games
        that only saved a final score. The selected source is never migrated.
        """
        if (type(school_id) is not str or not school_id
                or type(competition_id) is not str or not competition_id
                or type(match_id) is not str or not match_id
                or type(selected_year) is not int
                or type(verify_source) is not bool):
            raise ValueError("saved year, school and match IDs are required")
        manifest = self.gate.inspect(years, verify_source=verify_source)
        route = next(
            (item for item in manifest["routes"]
             if item["year"] == selected_year), None,
        )
        if route is None:
            raise CareerCrossEraBrowseConflict("match year not in selection")
        source = route["source"]
        if source == "historical_matches_legacy_iso":
            with closing(_read_only(self.gate.legacy_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT year,competition_id,match_id,record_sha256,payload_json "
                    "FROM historical_matches WHERE year=? AND competition_id=? "
                    "AND match_id=?",
                    (selected_year, competition_id, match_id),
                ).fetchone()
                if row is None:
                    raise CareerCrossEraBrowseConflict("saved match not found")
                raw = row["payload_json"]
                if sha256(raw.encode("utf-8")).hexdigest() != row["record_sha256"]:
                    raise CareerCrossEraBrowseConflict("legacy match SHA changed")
                game = expand_payload(json.loads(raw))
                if (game.get("year"), game.get("competition_id"),
                        game.get("match_id")) != (
                        row["year"], row["competition_id"], row["match_id"]):
                    raise CareerCrossEraBrowseConflict("legacy match key changed")
        else:
            # The gate already verifies the sealed year ledger and, with
            # verify_source=True, every payload. Fetch only the requested
            # composite primary key rather than rescanning the annual archive
            # once per pagination offset. Reverify this row even in shallow
            # mode; a tampered or wrong-calendar match must never be shown.
            plan, plan_sha = _calendar_info(self.v2.calendar, selected_year)
            if route["calendar_sha256"] != plan_sha:
                raise CareerCrossEraBrowseConflict("v2 calendar changed")
            with closing(_read_only(self.gate.v2_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM v2_option_a_matches "
                    "WHERE year=? AND competition_id=? AND match_id=?",
                    (selected_year, competition_id, match_id),
                ).fetchone()
                if row is None:
                    raise CareerCrossEraBrowseConflict("saved v2 match not found")
                game = _verify_match(row, plan, plan_sha)
        summary = self._checked_game(game, selected_year, school_id, source)
        fields = ("inning_scores", "team_stats", "batter_stats", "pitcher_stats")
        details = {}
        for field in fields:
            value = game.get(field)
            if value is not None and not isinstance(value, list):
                raise CareerCrossEraBrowseConflict("invalid saved match detail type")
            details[field] = value
        innings = details["inning_scores"]
        if innings is not None:
            totals = {"top": 0, "bottom": 0}
            seen = []
            for item in innings:
                if (type(item) is not dict
                        or type(item.get("inning")) is not int
                        or item["inning"] <= 0
                        or item.get("half") not in ("top", "bottom")
                        or type(item.get("was_played")) is not bool):
                    raise CareerCrossEraBrowseConflict("invalid inning line")
                half = item["half"]
                expected_team = (
                    game["team1_id"] if half == "top" else game["team2_id"]
                )
                if item.get("batting_team_id") != expected_team:
                    raise CareerCrossEraBrowseConflict("inning team changed")
                runs = item.get("runs")
                if item["was_played"]:
                    if type(runs) is not int or runs < 0:
                        raise CareerCrossEraBrowseConflict("invalid inning runs")
                    totals[half] += runs
                elif runs is not None:
                    raise CareerCrossEraBrowseConflict("unplayed inning has runs")
                seen.append((item["inning"], half))
            if seen != [
                (inning, half)
                for inning in range(1, len(seen) // 2 + 1)
                for half in ("top", "bottom")
            ] or (totals["top"], totals["bottom"]) != (
                summary["team1_score"], summary["team2_score"]
            ):
                raise CareerCrossEraBrowseConflict("line score disagrees with final")
        teams = details["team_stats"]
        if teams is not None and (
                len(teams) != 2
                or {item.get("school_id") for item in teams}
                != {game["team1_id"], game["team2_id"]}
                or any(item.get("runs") != game[
                    "team1_score" if item["school_id"] == game["team1_id"]
                    else "team2_score"
                ] for item in teams)):
            raise CareerCrossEraBrowseConflict("team stats disagree with final")
        return {
            "screen": "cross_era_match",
            "school_id": school_id,
            "selected_year": selected_year,
            "years": list(years),
            "source": source,
            "match": summary,
            "details": details,
            "detail_status": (
                "full_option_a_saved"
                if all(isinstance(details[field], list) for field in fields)
                else "partial_or_score_only_legacy"
            ),
            "missing_detail_fields": [
                field for field in fields if details[field] is None
            ],
            "source_payloads_rechecked": verify_source,
            "source_records_not_modified": True,
            "combined_career_stats_authorized": False,
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
