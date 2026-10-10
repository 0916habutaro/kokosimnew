"""Stage 43G-14: player season/career and school record views from Option-A.

Read-only, school-indexed, game-backed. No event/at-bat reconstruction, no
pitcher wins or losses inferred from box scores. Missing GameStats are stated
as gaps, not zero-filled evidence. Career player IDs, not names, are keys.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import sqlite3
from pathlib import Path

from .career_longitudinal_read import (
    CareerHistoryViewConflict, _iter_school_games,
)
from .career_roster_archive import CareerRosterArchive
from .historical_match_archive import HistoricalMatchArchive

BATTER = (
    "plate_appearances", "at_bats", "runs", "hits", "doubles", "triples",
    "home_runs", "rbi", "walks", "strikeouts", "hit_by_pitch",
    "sacrifice_flies", "sacrifice_bunts", "stolen_bases", "caught_stealing",
)
PITCHER = (
    "outs_recorded", "batters_faced", "runs_allowed", "earned_runs",
    "hits_allowed", "home_runs_allowed", "walks", "strikeouts", "hit_batters",
)
RANKABLE = {
    "batting_hits": ("batting", "hits"),
    "batting_home_runs": ("batting", "home_runs"),
    "batting_rbi": ("batting", "rbi"),
    "batting_stolen_bases": ("batting", "stolen_bases"),
    "pitching_strikeouts": ("pitching", "strikeouts"),
    "pitching_outs": ("pitching", "outs_recorded"),
}


class CareerPlayerRecordView:
    def __init__(
        self,
        match_archive: HistoricalMatchArchive | str | Path,
        roster_archive: CareerRosterArchive | str | Path,
    ):
        self.matches = (
            match_archive if isinstance(match_archive, HistoricalMatchArchive)
            else HistoricalMatchArchive(match_archive)
        )
        self.rosters = (
            roster_archive if isinstance(roster_archive, CareerRosterArchive)
            else CareerRosterArchive(roster_archive)
        )

    @staticmethod
    def _years(start_year: int, end_year: int) -> None:
        if (not isinstance(start_year, int) or isinstance(start_year, bool)
                or not isinstance(end_year, int) or isinstance(end_year, bool)
                or start_year < 1 or end_year < start_year):
            raise ValueError("invalid year window")

    def _identities(self, school_id: str) -> dict[str, dict]:
        """Verify immutable identity payloads before accepting player stats."""
        if not self.rosters.db_path.is_file():
            return {}
        identities = {}
        with sqlite3.connect(self.rosters.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT player_id, school_id, entry_year, identity_json, "
                "identity_sha256 FROM career_player_identities "
                "WHERE school_id=?", (school_id,),
            )
            for row in cursor:
                raw = row["identity_json"]
                if hashlib.sha256(raw.encode("utf-8")).hexdigest() != row["identity_sha256"]:
                    raise CareerHistoryViewConflict("player identity digest differs")
                detail = json.loads(raw)
                if (detail.get("player_id") != row["player_id"]
                        or detail.get("school_id") != school_id
                        or detail.get("entry_year") != row["entry_year"]):
                    raise CareerHistoryViewConflict("player identity changed")
                identities[row["player_id"]] = detail
        return identities

    def _iterate(self, school_id: str, start_year: int, end_year: int):
        if not isinstance(school_id, str) or not school_id:
            raise ValueError("invalid school id")
        self._years(start_year, end_year)
        identities = self._identities(school_id)
        cache = {}
        if not self.matches.db_path.is_file():
            return
        for row in _iter_school_games(
            self.matches.db_path, school_id, start_year, end_year,
        ):
            raw = row["payload_json"]
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != row["record_sha256"]:
                raise CareerHistoryViewConflict("match SHA changed")
            match = json.loads(raw)
            if (match.get("year") != row["year"]
                    or match.get("competition_id") != row["competition_id"]
                    or match.get("match_id") != row["match_id"]
                    or match.get("team1_id") != row["team1_id"]
                    or match.get("team2_id") != row["team2_id"]
                    or match.get("team1_score") != row["team1_score"]
                    or match.get("team2_score") != row["team2_score"]
                    or match.get("winner_id") not in
                    (row["team1_id"], row["team2_id"])):
                raise CareerHistoryViewConflict("match identity changed")
            if school_id not in (match["team1_id"], match["team2_id"]):
                raise CareerHistoryViewConflict("match school membership changed")
            scores = (match["team1_score"], match["team2_score"])
            if (any(type(v) is not int or v < 0 for v in scores)
                    or scores[0] == scores[1]
                    or match["winner_id"] != match[
                        "team1_id" if scores[0] > scores[1] else "team2_id"
                    ]):
                raise CareerHistoryViewConflict("match score/winner differs")
            batters = match.get("batter_stats")
            pitchers = match.get("pitcher_stats")
            if batters is None and pitchers is None:
                yield match["year"], match["match_id"], None, None
                continue
            if not isinstance(batters, list) or not isinstance(pitchers, list):
                raise CareerHistoryViewConflict("partial/inconsistent Option-A box score")
            year = match["year"]
            if year not in cache:
                roster = self.rosters.roster(year, school_id)
                if roster is None:
                    raise CareerHistoryViewConflict("school-year roster absent for A stats")
                cache[year] = {p.player_id for p in roster.players}
            seen = set()
            school_rows = {"batting": [], "pitching": []}
            for kind, values, keys in (
                ("batting", batters, BATTER), ("pitching", pitchers, PITCHER),
            ):
                for item in values:
                    if not isinstance(item, dict):
                        raise CareerHistoryViewConflict("invalid player game row")
                    if item.get("school_id") != school_id:
                        continue
                    pid = item.get("player_id")
                    if (not isinstance(pid, str) or pid not in identities
                            or pid not in cache[year]
                            or (kind, pid) in seen):
                        raise CareerHistoryViewConflict("player game attribution differs")
                    seen.add((kind, pid))
                    for field in keys:
                        v = item.get(field)
                        if type(v) is not int or v < 0:
                            raise CareerHistoryViewConflict("invalid nonnegative player stat")
                    if kind == "batting":
                        if (item["hits"] > item["at_bats"]
                                or item["doubles"] + item["triples"] +
                                item["home_runs"] > item["hits"]):
                            raise CareerHistoryViewConflict("invalid batting hit breakdown")
                    school_rows[kind].append(item)
            yield year, match["match_id"], school_rows["batting"], school_rows["pitching"]

    @staticmethod
    def _blank() -> dict:
        return {
            "batting": {"games": 0, **dict.fromkeys(BATTER, 0)},
            "pitching": {"games": 0, **dict.fromkeys(PITCHER, 0)},
            "missing_box_score_games": 0,
        }

    @staticmethod
    def _add(target: dict, kind: str, row: dict) -> None:
        dest = target[kind]
        dest["games"] += 1
        keys = BATTER if kind == "batting" else PITCHER
        for k in keys:
            dest[k] += row[k]

    @staticmethod
    def _metrics(data: dict) -> dict:
        bat = dict(data["batting"])
        pit = dict(data["pitching"])
        ab = bat["at_bats"]
        obp_den = ab + bat["walks"] + bat["hit_by_pitch"] + bat["sacrifice_flies"]
        singles = bat["hits"] - bat["doubles"] - bat["triples"] - bat["home_runs"]
        bases = singles + bat["doubles"] * 2 + bat["triples"] * 3 + bat["home_runs"] * 4
        avg = round(bat["hits"] / ab, 3) if ab else None
        obp = round(
            (bat["hits"] + bat["walks"] + bat["hit_by_pitch"]) / obp_den, 3
        ) if obp_den else None
        slg = round(bases / ab, 3) if ab else None
        bat.update({
            "batting_average": avg,
            "on_base_percentage": obp,
            "slugging_percentage": slg,
            "on_base_plus_slugging": (
                round((bat["hits"] + bat["walks"] + bat["hit_by_pitch"]) / obp_den
                      + bases / ab, 3) if obp_den and ab else None
            ),
        })
        outs = pit["outs_recorded"]
        pit.update({
            "innings_pitched_outs": outs,
            "earned_run_average": round(27 * pit["earned_runs"] / outs, 2)
            if outs else None,
            "walks_hits_per_inning": round(
                3 * (pit["walks"] + pit["hits_allowed"]) / outs, 2
            ) if outs else None,
        })
        return {**data, "batting": bat, "pitching": pit}

    def _aggregate(self, school_id: str, start_year: int, end_year: int):
        entries = {}
        for year, _mid, batters, pitchers in self._iterate(
            school_id, start_year, end_year,
        ):
            if batters is None:
                # Retained Option A may coexist with older score-only games.
                # Do not fabricate plate appearances for those games.
                continue
            for kind, records in (("batting", batters), ("pitching", pitchers)):
                for row in records:
                    key = (row["player_id"], year)
                    target = entries.setdefault(key, self._blank())
                    self._add(target, kind, row)
        return entries

    def player_seasons(self, player_id: str, *,
                       start_year: int, end_year: int) -> dict:
        self._years(start_year, end_year)
        if not isinstance(player_id, str) or not player_id:
            raise ValueError("invalid player id")
        hist = self.rosters.player_history(player_id)
        if not hist:
            return {"player_id": player_id, "seasons": [],
                    "totals": self._metrics(self._blank()),
                    "games_without_box_scores": 0,
                    "verified_stats_only": True}
        school = hist[0]["school_id"]
        by_year = self._aggregate(school, start_year, end_year)
        rows = []
        total = self._blank()
        for year in range(start_year, end_year + 1):
            if (player_id, year) not in by_year:
                continue
            value = by_year[(player_id, year)]
            rows.append({"year": year, **self._metrics(value)})
            for kind, fields in (("batting", BATTER), ("pitching", PITCHER)):
                total[kind]["games"] += value[kind]["games"]
                for k in fields:
                    total[kind][k] += value[kind][k]
        return {
            "player_id": player_id,
            "school_id": school,
            "seasons": rows,
            "totals": self._metrics(total),
            "games_without_box_scores": self._missing(school, start_year, end_year),
            "verified_stats_only": True,
            "pitcher_wins_losses_inferred": False,
        }

    def _missing(self, school_id: str, start_year: int, end_year: int) -> int:
        return sum(
            batters is None
            for _year, _mid, batters, _pitchers
            in self._iterate(school_id, start_year, end_year)
        )

    def school_leaders(self, school_id: str, *, start_year: int, end_year: int,
                       category: str, limit: int = 20) -> dict:
        self._years(start_year, end_year)
        if category not in RANKABLE or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("unsupported metric or rank limit")
        totals = defaultdict(self._blank)
        for (pid, _year), record in self._aggregate(
            school_id, start_year, end_year,
        ).items():
            target = totals[pid]
            for kind, fields in (("batting", BATTER), ("pitching", PITCHER)):
                target[kind]["games"] += record[kind]["games"]
                for field in fields:
                    target[kind][field] += record[kind][field]
        kind, metric = RANKABLE[category]
        ranked = sorted(
            (
                {"player_id": pid, "stat_value": total[kind][metric]}
                for pid, total in totals.items() if total[kind]["games"]
            ),
            key=lambda item: (-item["stat_value"], item["player_id"]),
        )
        return {
            "school_id": school_id, "start_year": start_year, "end_year": end_year,
            "category": category, "rows": ranked[:limit],
            "candidate_count": len(ranked),
            "only_archived_option_a_stats": True,
            "missing_box_score_games": self._missing(
                school_id, start_year, end_year,
            ),
        }
