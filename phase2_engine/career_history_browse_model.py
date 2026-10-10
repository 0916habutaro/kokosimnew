"""Stage43G-16: read-only, ID-addressed future-career history screen model.

This is a PILOT screen contract, separate from Stage13D3's 2026 browse DB.
Do not blend game sandbox scores with historical/official research previews.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Literal

from .career_longitudinal_read import CareerLongitudinalReadModel
from .career_player_records import CareerPlayerRecordView, RANKABLE
from .career_stats_readonly_adapter import CareerStatsReadOnlyAdapter
from .historical_match_archive import HistoricalMatchArchive
from .career_roster_archive import CareerRosterArchive
from .repository import DataRepository

SCREENS = ("years", "school", "player", "competition", "match", "leaders")
SOURCE = "game_career_sandbox_not_official"
Page = dict


@dataclass(frozen=True)
class HistoryRoute:
    screen: Literal["years", "school", "player", "competition", "match", "leaders"]
    year: int
    school_id: str = ""
    player_id: str = ""
    competition_id: str = ""
    match_id: str = ""
    start_year: int = 0
    offset: int = 0
    metric: str = "batting_hits"


class CareerHistoryBrowseModel:
    """Headless GUI adapter: all public pages are read-only structured data."""

    def __init__(self, data_root: str | Path, slot_root: str | Path):
        self.repo = DataRepository(Path(data_root))
        slot = Path(slot_root)
        self.history = HistoricalMatchArchive(slot / "historical_matches.sqlite3")
        self.rosters = CareerRosterArchive(slot / "career_rosters.sqlite3")
        self.school = CareerLongitudinalReadModel(self.history, self.rosters)
        self.stats = CareerPlayerRecordView(self.history, self.rosters)
        self.stats_cache = CareerStatsReadOnlyAdapter(
            self.stats, slot / "derived_player_stats.sqlite3"
        )
        # Stage43G-17 adapter never materializes; missing caches use raw A.
        self.slot_root = slot

    def _stats_reader(self, school_id: str, start_year: int, end_year: int):
        """Return a read path and its precise verification level."""
        if self.stats_cache.ready(
            school_id, start_year=start_year, end_year=end_year
        ):
            return self.stats_cache, "sealed_cache_ledger_checked"
        return self.stats, "raw_archived_A_verified"

    def years(self) -> list[dict]:
        # HistoricalMatchArchive.list_years() replays schema DDL for normal
        # game runtime. A history GUI must use a true SQLite READ-ONLY
        # connection and must not create the database or any index.
        if not self.history.db_path.is_file():
            return []
        with sqlite3.connect(
            self.history.db_path.resolve().as_uri() + "?mode=ro", uri=True
        ) as conn:
            rows = conn.execute(
                "SELECT year,status,match_count FROM career_years "
                "ORDER BY year"
            ).fetchall()
        return [
            {"year": year, "state": status,
             "archived_match_count": match_count, "source_kind": SOURCE}
            for year, status, match_count in rows
        ]

    def _school(self, sid: str) -> dict:
        try:
            return self.repo.schools[sid]
        except KeyError as exc:
            raise ValueError("unknown school ID") from exc

    def _competition(self, competition_id: str) -> dict:
        try:
            return self.repo.competition(competition_id)
        except KeyError as exc:
            raise ValueError("unknown competition ID") from exc

    def _year(self, year: int) -> None:
        if type(year) is not int or year not in {
            row["year"] for row in self.years()
        }:
            raise ValueError("year not in career archive")

    @staticmethod
    def _page(limit: int, offset: int) -> None:
        if (type(limit) is not int or not 1 <= limit <= 100
                or type(offset) is not int or offset < 0):
            raise ValueError("invalid browse page")

    def find_schools(self, text: str, *, limit: int = 30) -> list[dict]:
        if type(text) is not str or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid school search")
        keyword = text.strip().casefold()
        if not keyword:
            return []
        found = []
        for sid, s in sorted(self.repo.schools.items()):
            if (keyword in str(s.get("school_name", "")).casefold()
                    or keyword == sid.casefold()):
                found.append({
                    "school_id": sid, "school_name": s.get("school_name", ""),
                    "prefecture_code": s.get("prefecture_code", ""),
                })
                if len(found) >= limit:
                    break
        return found

    def _school_players_at_year(self, year: int, school_id: str, *,
                                limit: int, offset: int) -> dict:
        # Selection-year membership: never display an entrant from a later
        # career year while the user views an older school season.
        path = self.rosters.db_path
        if not path.is_file():
            return {
                "school_id": school_id, "players": [], "total": 0,
                "limit": limit, "offset": offset,
                "status_is_graduation_proof": False,
            }
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                "SELECT COUNT(*) FROM career_player_identities "
                "WHERE school_id=? AND entry_year<=?",
                (school_id, year),
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT player_id,entry_year,identity_json,identity_sha256 "
                "FROM career_player_identities WHERE school_id=? "
                "AND entry_year<=? ORDER BY entry_year,player_id "
                "LIMIT ? OFFSET ?",
                (school_id, year, limit, offset),
            ).fetchall()
        roster = self.rosters.roster(year, school_id)
        roster_ids = {p.player_id for p in roster.players} if roster else set()
        results = []
        for row in rows:
            raw = row["identity_json"]
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != row["identity_sha256"]:
                raise ValueError("archived career player identity checksum differs")
            info = json.loads(raw)
            if (info.get("player_id") != row["player_id"]
                    or info.get("school_id") != school_id
                    or info.get("entry_year") != row["entry_year"]):
                raise ValueError("archived career player identity mismatched")
            results.append({
                "player_id": row["player_id"], "school_id": school_id,
                "entry_year": row["entry_year"],
                "display_name": info["display_name"],
                "selected_roster_year": year,
                "latest_roster_status": (
                    "on_selected_year_roster" if row["player_id"] in roster_ids
                    else "not_on_selected_year_roster"
                ) if roster else "selected_year_roster_unavailable",
            })
        return {
            "school_id": school_id, "players": results, "total": total,
            "limit": limit, "offset": offset,
            "status_is_graduation_proof": False,
        }

    def school_page(self, year: int, school_id: str, *,
                    start_year: int | None = None, offset: int = 0,
                    limit: int = 30) -> Page:
        self._year(year)
        self._page(limit, offset)
        s = self._school(school_id)
        start = start_year if start_year is not None else min(
            row["year"] for row in self.years()
        )
        years = self.school.school_results(
            school_id, start_year=start, end_year=year, limit=limit, offset=offset
        )
        members = self._school_players_at_year(
            year, school_id, limit=limit, offset=offset
        )
        return {
            "screen": "school", "year": year, "school_id": school_id,
            "school_name": s.get("school_name", school_id),
            "prefecture_code": s.get("prefecture_code", ""),
            "year_results": years, "historical_players": members,
            "source_kind": SOURCE,
            "links": {
                "school_id": school_id, "year": year,
                "player_ids": [r["player_id"] for r in members["players"]],
                "competition_ids": [r["competition_id"] for r in years["records"]],
            },
        }

    def player_page(self, year: int, player_id: str, *,
                    start_year: int | None = None) -> Page:
        self._year(year)
        membership = self.rosters.player_history(player_id)
        if not membership:
            raise ValueError("unknown career player ID")
        selected = [r for r in membership if r["year"] <= year]
        if not selected:
            raise ValueError("player has no record on or before selected year")
        start = (min(r["year"] for r in selected)
                 if start_year is None else start_year)
        if start > year:
            raise ValueError("start year after screen year")
        # The full raw read path validates every matched A box score.
        reader, validation = self._stats_reader(
            selected[0]["school_id"], start, year
        )
        stat = reader.player_seasons(
            player_id, start_year=start, end_year=year,
        )
        return {
            "screen": "player", "year": year, "player_id": player_id,
            "school_id": selected[0]["school_id"],
            "display_name": selected[0]["display_name"],
            "membership": selected,
            "season_stats": stat["seasons"],
            "career_stats": stat["totals"],
            "missing_box_score_games": stat["games_without_box_scores"],
            "source_kind": SOURCE,
            "source_validation": validation,
            "source_payloads_rechecked_on_read": (
                validation == "raw_archived_A_verified"
            ),
            "pitcher_wins_losses_inferred": False,
        }

    def _matches(self, year: int, *, competition_id: str = "",
                 limit: int = 50, offset: int = 0) -> dict:
        self._year(year)
        self._page(limit, offset)
        if competition_id:
            self._competition(competition_id)
        if not self.history.db_path.is_file():
            return {"rows": [], "total": 0}
        with sqlite3.connect(
            self.history.db_path.resolve().as_uri() + "?mode=ro", uri=True
        ) as conn:
            conn.row_factory = sqlite3.Row
            where = "year=?"
            args: list = [year]
            if competition_id:
                where += " AND competition_id=?"
                args.append(competition_id)
            total = conn.execute(
                "SELECT COUNT(*) FROM historical_matches WHERE " + where,
                args,
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT year,competition_id,match_id,record_sha256,payload_json "
                "FROM historical_matches WHERE " + where
                + " ORDER BY match_date,competition_id,match_id LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        matches = []
        for row in rows:
            raw = row["payload_json"]
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != row["record_sha256"]:
                raise ValueError("archived game checksum differs")
            game = json.loads(raw)
            if ((game["year"], game["competition_id"], game["match_id"])
                    != (row["year"], row["competition_id"], row["match_id"])):
                raise ValueError("archived game identity differs")
            matches.append({
                "year": year, "competition_id": row["competition_id"],
                "match_id": row["match_id"],
                "match_date": game["match_date"],
                "team1_id": game["team1_id"], "team2_id": game["team2_id"],
                "team1_score": game["team1_score"],
                "team2_score": game["team2_score"],
                "score_source": game["score_source"],
            })
        return {"rows": matches, "total": total, "limit": limit, "offset": offset}

    def competition_page(self, year: int, competition_id: str,
                         *, offset: int = 0, limit: int = 50) -> Page:
        games = self._matches(
            year, competition_id=competition_id, offset=offset, limit=limit
        )
        master = self._competition(competition_id)
        return {
            "screen": "competition", "year": year,
            "competition_id": competition_id,
            "competition_name": master.get("competition_name", competition_id),
            "matches": games, "source_kind": SOURCE,
            # Results in this archive do not certify a completed bracket.
            "bracket_champion_verified": False,
            "advancement_rights_inferred": False,
        }

    def match_page(self, year: int, competition_id: str, match_id: str) -> Page:
        self._year(year)
        self._competition(competition_id)
        if not match_id:
            raise ValueError("match ID required")
        if not self.history.db_path.is_file():
            raise ValueError("match archive missing")
        with sqlite3.connect(
            self.history.db_path.resolve().as_uri() + "?mode=ro", uri=True
        ) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT payload_json,record_sha256 FROM historical_matches "
                "WHERE year=? AND competition_id=? AND match_id=?",
                (year, competition_id, match_id),
            ).fetchone()
        if row is None:
            raise ValueError("no such saved career game")
        raw = row["payload_json"]
        if hashlib.sha256(raw.encode("utf-8")).hexdigest() != row["record_sha256"]:
            raise ValueError("archived game checksum differs")
        game = json.loads(raw)
        if (game["year"], game["competition_id"], game["match_id"]) != (
            year, competition_id, match_id
        ):
            raise ValueError("archived game identity differs")
        return {
            "screen": "match", "year": year,
            "competition_id": competition_id, "match_id": match_id,
            "game": {
                "match_date": game["match_date"],
                "date_source": game["date_source"],
                "score_source": game["score_source"],
                "team1_id": game["team1_id"],
                "team2_id": game["team2_id"],
                "team1_score": game["team1_score"],
                "team2_score": game["team2_score"],
                "winner_id": game["winner_id"],
                "inning_scores": game.get("inning_scores"),
                "team_stats": game.get("team_stats"),
                "batter_stats": game.get("batter_stats"),
                "pitcher_stats": game.get("pitcher_stats"),
            },
            "inning_score_status": (
                "recorded" if game.get("inning_scores") is not None else "not_recorded"
            ),
            "box_score_status": (
                "recorded" if game.get("batter_stats") is not None
                and game.get("pitcher_stats") is not None else "not_recorded"
            ),
            "plate_appearance_events_archived": False,
            "source_kind": SOURCE,
        }

    def leaders_page(self, year: int, school_id: str, *,
                     start_year: int | None = None,
                     category: str = "batting_hits",
                     limit: int = 20) -> Page:
        self._year(year)
        self._school(school_id)
        if category not in RANKABLE:
            raise ValueError("unknown leaderboard metric")
        start = (min(row["year"] for row in self.years())
                 if start_year is None else start_year)
        reader, validation = self._stats_reader(school_id, start, year)
        records = reader.school_leaders(
            school_id, start_year=start, end_year=year,
            category=category, limit=limit,
        )
        return {
            "screen": "leaders", "year": year, "school_id": school_id,
            "category": category, "records": records,
            "source_kind": SOURCE,
            "ranking_qualification_inferred": False,
            "source_validation": validation,
            "source_payloads_rechecked_on_read": (
                validation == "raw_archived_A_verified"
            ),
        }


class CareerHistoryNavigator:
    """Pure navigation state; never indexes the UI by a displayed school name."""

    def __init__(self, model: CareerHistoryBrowseModel, *, year: int):
        model._year(year)
        self.model = model
        self.current = HistoryRoute("years", year)
        self._back: list[HistoryRoute] = []

    def open(self, route: HistoryRoute) -> Page:
        if route.screen not in SCREENS:
            raise ValueError("unsupported history view")
        # Only commit navigation after data validation succeeds.
        data = self.render(route)
        if route != self.current:
            self._back.append(self.current)
            self.current = route
        return data

    def back(self) -> Page:
        if not self._back:
            return self.render(self.current)
        route = self._back[-1]
        data = self.render(route)
        self._back.pop()
        self.current = route
        return data

    def render(self, route: HistoryRoute | None = None) -> Page:
        r = route or self.current
        self.model._year(r.year)
        if r.screen == "years":
            return {"screen": "years", "year": r.year,
                    "years": self.model.years(), "source_kind": SOURCE}
        if r.screen == "school":
            return self.model.school_page(
                r.year, r.school_id, start_year=r.start_year or None,
                offset=r.offset,
            )
        if r.screen == "player":
            return self.model.player_page(
                r.year, r.player_id, start_year=r.start_year or None,
            )
        if r.screen == "competition":
            return self.model.competition_page(
                r.year, r.competition_id, offset=r.offset,
            )
        if r.screen == "match":
            return self.model.match_page(
                r.year, r.competition_id, r.match_id,
            )
        if r.screen == "leaders":
            return self.model.leaders_page(
                r.year, r.school_id, start_year=r.start_year or None,
                category=r.metric,
            )
        raise ValueError("unsupported history view")
