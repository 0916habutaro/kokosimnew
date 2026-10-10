"""Stage43G-28: read-only attribution of sealed fictional v2 A records to rosters.

This is a separate verification/read model, NOT a migration of legacy match
archives, NOT a persistent player-stat cache and NOT real year-10000 gameplay.
Unattributed synthetic SCALE-* players from G-27 deliberately fail closed.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .career_option_a_storage_profile import _read_only
from .career_player_records import BATTER, PITCHER, CareerPlayerRecordView
from .career_roster_archive import (
    CareerRosterArchive, CareerRosterConflictError, _digest, _identity,
)
from .career_v2_option_a_archive import CareerV2OptionAArchive


class CareerV2AttributionConflict(ValueError):
    """A v2 match is unsealed, or a player cannot be proven on its year roster."""


class CareerV2RosterAttribution:
    """Reconcile only sealed synthetic A records with immutable school rosters.

    Every source archive is opened in SQLite read-only mode. Results are
    calculated in memory; the regular historical stats cache is not touched.
    """

    def __init__(self, match_archive: CareerV2OptionAArchive,
                 roster_archive: CareerRosterArchive | str | Path):
        self.matches = match_archive
        self.rosters = (
            roster_archive if isinstance(roster_archive, CareerRosterArchive)
            else CareerRosterArchive(roster_archive)
        )
        if self.matches.path.resolve() == self.rosters.db_path.resolve():
            raise ValueError("roster and v2 match archives must be separate")

    def _members(self, conn: sqlite3.Connection, year: int,
                 school: str) -> set[str]:
        try:
            snapshot = CareerRosterArchive._get(conn, year, school)
        except (CareerRosterConflictError, KeyError, TypeError) as exc:
            raise CareerV2AttributionConflict("invalid school-year roster") from exc
        if snapshot is None:
            raise CareerV2AttributionConflict(
                f"school-year roster not saved: {school}/{year}"
            )
        ids = set()
        for player in snapshot.players:
            if player.player_id in ids:
                raise CareerV2AttributionConflict("duplicate roster player ID")
            ids.add(player.player_id)
            row = conn.execute(
                "SELECT school_id,entry_year,identity_json,identity_sha256 "
                "FROM career_player_identities WHERE player_id=?",
                (player.player_id,),
            ).fetchone()
            expected = _identity(player)
            if (row is None or row["school_id"] != school
                    or row["entry_year"] != player.entry_year
                    or row["identity_json"] != expected
                    or row["identity_sha256"] != _digest(expected)):
                raise CareerV2AttributionConflict(
                    f"permanent player identity differs: {player.player_id}"
                )
        return ids

    @staticmethod
    def _validated_rows(game: dict, members: dict[str, set[str]]) -> dict:
        teams = (game["team1_id"], game["team2_id"])
        if (not all(isinstance(t, str) and t for t in teams)
                or teams[0] == teams[1]):
            raise CareerV2AttributionConflict("invalid competing schools")
        checked = {"batting": [], "pitching": []}
        for kind, name, keys in (
            ("batting", "batter_stats", BATTER),
            ("pitching", "pitcher_stats", PITCHER),
        ):
            seen = set()
            represented = set()
            for rec in game[name]:
                if not isinstance(rec, dict):
                    raise CareerV2AttributionConflict("invalid player game stat row")
                school = rec.get("school_id")
                player = rec.get("player_id")
                if (school not in teams or type(player) is not str
                        or player not in members[school]
                        or (school, player) in seen):
                    raise CareerV2AttributionConflict(
                        "v2 permanent player / school-year attribution differs"
                    )
                seen.add((school, player))
                represented.add(school)
                if any(type(rec.get(k)) is not int or rec[k] < 0 for k in keys):
                    raise CareerV2AttributionConflict("invalid nonnegative player stat")
                if kind == "batting" and (
                    rec["hits"] > rec["at_bats"]
                    or rec["doubles"] + rec["triples"]
                    + rec["home_runs"] > rec["hits"]
                ):
                    raise CareerV2AttributionConflict("invalid batting hit breakdown")
                if kind == "pitching" and (
                    rec["earned_runs"] > rec["runs_allowed"]
                ):
                    raise CareerV2AttributionConflict("invalid pitching runs")
                checked[kind].append(rec)
            if represented != set(teams):
                raise CareerV2AttributionConflict(
                    "both schools need attributable " + kind + " stats"
                )
        return checked

    def school_year(self, year: int, school_id: str) -> dict:
        """Verify all source games, seal and both opposing teams, then aggregate.

        The returned statistics do not enter legacy career totals. Each
        player_id is verified against its exact annual roster and identity
        table, never guessed from the display name or jersey number.
        """
        if type(year) is not int or year < 1:
            raise ValueError("invalid year")
        if type(school_id) is not str or not school_id:
            raise ValueError("invalid school ID")
        if not self.rosters.db_path.is_file():
            raise FileNotFoundError("saved career roster archive missing")
        first = self.matches.year_matches(year, limit=100)
        if first["year_status"] != "sealed":
            raise CareerV2AttributionConflict(
                "only sealed fictional v2 years can be attributed"
            )
        total_games = first["total"]
        aggregate: dict[str, dict] = {}
        team_game_count = 0
        with closing(_read_only(self.rosters.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            membership: dict[str, set[str]] = {}
            # Enforce presence of the selected school's exact year snapshot,
            # including if there are no recorded games for that school.
            membership[school_id] = self._members(conn, year, school_id)
            for offset in range(0, total_games, 100):
                page = (first if offset == 0 else
                        self.matches.year_matches(year, limit=100, offset=offset))
                if (page["year_status"] != "sealed"
                        or page["total"] != total_games
                        or page["calendar_sha256"] != first["calendar_sha256"]):
                    raise CareerV2AttributionConflict("v2 annual source changed")
                for game in page["rows"]:
                    teams = (game["team1_id"], game["team2_id"])
                    if school_id not in teams:
                        continue
                    for team in teams:
                        if team not in membership:
                            membership[team] = self._members(conn, year, team)
                    checked = self._validated_rows(game, membership)
                    team_game_count += 1
                    for kind in ("batting", "pitching"):
                        for rec in checked[kind]:
                            if rec["school_id"] != school_id:
                                continue
                            pid = rec["player_id"]
                            bucket = aggregate.setdefault(
                                pid, CareerPlayerRecordView._blank()
                            )
                            CareerPlayerRecordView._add(bucket, kind, rec)
        rows = [
            {"player_id": player_id, "school_id": school_id,
             "year": year, **CareerPlayerRecordView._metrics(stats)}
            for player_id, stats in sorted(aggregate.items())
        ]
        return {
            "source_kind": "sealed_fictional_v2_option_a_roster_verified",
            "game_year": year,
            "school_id": school_id,
            "team_match_count": team_game_count,
            "player_count": len(rows),
            "rows": rows,
            "source_match_count": total_games,
            "source_calendar_sha256": first["calendar_sha256"],
            "year_status": "sealed",
            "roster_id_attribution_verified": True,
            "recorded_box_scores_only": True,
            "legacy_stats_cache_modified": False,
            "merged_into_legacy_player_career": False,
            "real_tournament_runtime_connected": False,
            "pitcher_wins_losses_inferred": False,
        }
