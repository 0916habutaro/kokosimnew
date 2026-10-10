"""Stage43G-27: append-only Option-A match sidecar with typed v2 day slots.

The original historical_matches.sqlite3 is NEVER migrated or written here.
This opt-in fictional sandbox stores full Option-A facts in a separate DB and
supports year 10000+. It is not connected to real tournament simulation, the
legacy player-stat cache, or GUI. Never present this as real game progression.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Mapping

from .career_calendar_v2 import (
    CareerCalendarV2Archive, GameDaySlot, SandboxCalendarConflict,
)
from .career_option_a_storage_profile import _read_only
from .career_era_calendar_contract import _year
from .historical_match_archive import (
    _canonical, _digest, _history_payload,
)

SOURCE = "explicit_fictional_v2_option_a_not_official"
SCHEMA_VERSION = "career_v2_option_a_sandbox_1"
_DETAIL = ("inning_scores", "team_stats", "batter_stats", "pitcher_stats")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_game_years (
    year INTEGER PRIMARY KEY CHECK(year>0),
    calendar_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','sealed')),
    match_count INTEGER,
    ledger_sha256 TEXT
);
CREATE TABLE IF NOT EXISTS v2_option_a_matches (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    game_day_token TEXT NOT NULL,
    calendar_sha256 TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (year,competition_id,match_id),
    FOREIGN KEY (year) REFERENCES v2_game_years(year)
);
CREATE INDEX IF NOT EXISTS idx_v2_games_day
    ON v2_option_a_matches(year,game_day_token,competition_id,match_id);
CREATE INDEX IF NOT EXISTS idx_v2_games_school_a
    ON v2_option_a_matches(year,competition_id,match_id);
"""


class CareerV2MatchConflict(ValueError):
    """Saved calendar, immutable game record or annual source ledger differs."""


def _calendar_info(calendar: CareerCalendarV2Archive, year: int) -> tuple[dict, str]:
    plan = calendar.read(year)
    if plan is None:
        raise CareerV2MatchConflict("no explicit fictional calendar for game year")
    return plan, _digest(_canonical(plan))


def _normalized(year: int, source: Mapping[str, object], plan: dict) -> dict:
    if not isinstance(source, Mapping):
        raise ValueError("invalid full-A match input")
    raw_date = source.get("game_day_token")
    if not isinstance(raw_date, str):
        raise ValueError("v2 match requires a logical game day token")
    slot = GameDaySlot.from_token(raw_date)
    comp = source.get("competition_id")
    if (slot.year != year
            or not isinstance(comp, str)
            or slot.token not in plan["competition_days"].get(comp, [])):
        raise CareerV2MatchConflict("game day not in approved fictional calendar")
    if source.get("match_date") not in (None, "", slot.token):
        raise ValueError("legacy ISO date may not be written into v2 match")
    if source.get("date_source") != "fictional_v2_day_slot":
        raise ValueError("v2 match requires explicit fictional date provenance")
    data = dict(source)
    data["match_date"] = slot.token
    data["completed_on"] = ""
    normalized = _history_payload(year, data)
    if (normalized["score_source"] != "ability_model_v1"
            or normalized["team1_score"] is None
            or any(not isinstance(normalized.get(k), list)
                   or not normalized[k] for k in _DETAIL)):
        raise ValueError("v2 Option-A requires full inning/team/batter/pitcher stats")
    # This stage reuses the verified A field contract; it does not infer
    # roster attribution. Real permanent-player IDs are a later integration.
    if (normalized["date_source"] != "fictional_v2_day_slot"
            or normalized["match_date"] != slot.token):
        raise CareerV2MatchConflict("v2 date provenance differs")
    normalized["schema_version"] = SCHEMA_VERSION
    normalized["source_kind"] = SOURCE
    normalized["game_day_token"] = slot.token
    return normalized


def _verify_match(row: sqlite3.Row, plan: dict, plan_sha: str) -> dict:
    raw = row["payload_json"]
    if _digest(raw) != row["record_sha256"]:
        raise CareerV2MatchConflict("v2 Option-A match checksum differs")
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise CareerV2MatchConflict("v2 Option-A payload unreadable") from exc
    if (not isinstance(value, dict)
            or row["calendar_sha256"] != plan_sha
            or value.get("schema_version") != SCHEMA_VERSION
            or value.get("source_kind") != SOURCE
            or (value.get("year"), value.get("competition_id"),
                value.get("match_id"), value.get("game_day_token"))
            != (row["year"], row["competition_id"],
                row["match_id"], row["game_day_token"])
            or value.get("match_date") != row["game_day_token"]
            or value.get("date_source") != "fictional_v2_day_slot"
            or value.get("score_source") != "ability_model_v1"
            or value.get("winner_id") not in (
                value.get("team1_id"), value.get("team2_id"))
            or any(not isinstance(value.get(k), list) or not value[k]
                   for k in _DETAIL)):
        raise CareerV2MatchConflict("v2 A row and payload identity differ")
    try:
        slot = GameDaySlot.from_token(row["game_day_token"])
    except ValueError as exc:
        raise CareerV2MatchConflict("stored v2 day token invalid") from exc
    if (slot.year != row["year"] or slot.token not in
            plan["competition_days"].get(row["competition_id"], [])):
        raise CareerV2MatchConflict("stored v2 game not approved by calendar")
    a, b = value.get("team1_score"), value.get("team2_score")
    if (type(a) is not int or type(b) is not int or a == b
            or (value["winner_id"] !=
                (value["team1_id"] if a > b else value["team2_id"]))):
        raise CareerV2MatchConflict("v2 match score/winner differs")
    return value


def _ledger(conn: sqlite3.Connection, year: int) -> tuple[int, str]:
    items = conn.execute(
        "SELECT competition_id,match_id,record_sha256 "
        "FROM v2_option_a_matches WHERE year=? "
        "ORDER BY competition_id,match_id", (year,),
    ).fetchall()
    return len(items), _digest(_canonical([
        (a, b, sha) for a, b, sha in items
    ]))


class CareerV2OptionAArchive:
    """Companion immutable synthetic A-records, never legacy archive migration."""

    def __init__(self, db_path: str | Path, calendar_path: str | Path,
                 *, legacy_archive_path: str | Path | None = None):
        self.path = Path(db_path)
        self.calendar = CareerCalendarV2Archive(calendar_path)
        self.legacy_path = (
            Path(legacy_archive_path)
            if legacy_archive_path is not None else None
        )

    def _check_legacy_collision(self, year: int, comp: str, match: str) -> None:
        if self.legacy_path is None or not self.legacy_path.exists():
            return
        with closing(_read_only(self.legacy_path)) as con:
            found = con.execute(
                "SELECT 1 FROM historical_matches WHERE "
                "year=? AND competition_id=? AND match_id=?",
                (year, comp, match),
            ).fetchone()
        if found is not None:
            raise CareerV2MatchConflict(
                "existing legacy Option-A match cannot be duplicated in sidecar"
            )

    def append(self, year: int, source: Mapping[str, object]) -> dict:
        _year(year)
        plan, plan_sha = _calendar_info(self.calendar, year)
        data = _normalized(year, source, plan)
        raw = _canonical(data)
        digest = _digest(raw)
        comp, match = data["competition_id"], data["match_id"]
        self._check_legacy_collision(year, comp, match)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(_SCHEMA)
            with con:
                entry = con.execute(
                    "SELECT calendar_sha256,status FROM v2_game_years "
                    "WHERE year=?", (year,),
                ).fetchone()
                if entry is None:
                    con.execute(
                        "INSERT INTO v2_game_years VALUES (?,?,'active',NULL,NULL)",
                        (year, plan_sha),
                    )
                    status = "active"
                elif entry["calendar_sha256"] != plan_sha:
                    raise CareerV2MatchConflict(
                        "saved annual calendar provenance differs"
                    )
                else:
                    status = entry["status"]
                old = con.execute(
                    "SELECT * FROM v2_option_a_matches "
                    "WHERE year=? AND competition_id=? AND match_id=?",
                    (year, comp, match),
                ).fetchone()
                if old is not None:
                    if (old["record_sha256"] != digest
                            or old["calendar_sha256"] != plan_sha):
                        raise CareerV2MatchConflict(
                            "immutable v2 Option-A match changed"
                        )
                    _verify_match(old, plan, plan_sha)
                    return {"inserted": False, "record_sha256": digest,
                            "game_day_token": data["game_day_token"]}
                if status == "sealed":
                    raise CareerV2MatchConflict(
                        "sealed v2 game year cannot accept new matches"
                    )
                con.execute(
                    "INSERT INTO v2_option_a_matches "
                    "(year,competition_id,match_id,game_day_token,"
                    "calendar_sha256,record_sha256,payload_json) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (year, comp, match, data["game_day_token"],
                     plan_sha, digest, raw),
                )
        return {"inserted": True, "record_sha256": digest,
                "game_day_token": data["game_day_token"]}

    def seal_year(self, year: int, *, expected_match_count: int) -> dict:
        _year(year)
        if (type(expected_match_count) is not int
                or expected_match_count < 0):
            raise ValueError("invalid expected v2 year match count")
        if not self.path.is_file():
            raise FileNotFoundError("v2 Option-A archive missing")
        plan, plan_sha = _calendar_info(self.calendar, year)
        with closing(sqlite3.connect(self.path)) as con:
            con.row_factory = sqlite3.Row
            with con:
                status = con.execute(
                    "SELECT * FROM v2_game_years WHERE year=?", (year,),
                ).fetchone()
                if status is None or status["calendar_sha256"] != plan_sha:
                    raise CareerV2MatchConflict("v2 annual calendar changed")
                for game in con.execute(
                    "SELECT * FROM v2_option_a_matches WHERE year=?", (year,)
                ):
                    _verify_match(game, plan, plan_sha)
                count, digest = _ledger(con, year)
                if count != expected_match_count:
                    raise CareerV2MatchConflict("v2 year match count differs")
                if status["status"] == "sealed":
                    if (status["match_count"], status["ledger_sha256"]) != (
                        count, digest
                    ):
                        raise CareerV2MatchConflict("sealed v2 ledger changed")
                    return {"already_sealed": True,
                            "match_count": count, "ledger_sha256": digest}
                con.execute(
                    "UPDATE v2_game_years SET status='sealed', "
                    "match_count=?, ledger_sha256=? WHERE year=?",
                    (count, digest, year),
                )
        return {"already_sealed": False,
                "match_count": count, "ledger_sha256": digest}

    def _verified_year(self, year: int, plan: dict,
                       plan_sha: str) -> tuple[str, list[dict]]:
        if not self.path.is_file():
            raise FileNotFoundError("v2 Option-A archive missing")
        with closing(_read_only(self.path)) as con:
            con.row_factory = sqlite3.Row
            status = con.execute(
                "SELECT * FROM v2_game_years WHERE year=?", (year,),
            ).fetchone()
            if status is None or status["calendar_sha256"] != plan_sha:
                raise CareerV2MatchConflict("v2 calendar/annual state differs")
            rows = con.execute(
                "SELECT * FROM v2_option_a_matches WHERE year=? "
                "ORDER BY game_day_token,competition_id,match_id", (year,),
            )
            data = [_verify_match(row, plan, plan_sha) for row in rows]
            if status["status"] == "sealed":
                count, digest = _ledger(con, year)
                if (count, digest) != (
                    status["match_count"], status["ledger_sha256"]
                ):
                    raise CareerV2MatchConflict("sealed v2 ledger changed")
        return status["status"], data

    def year_matches(self, year: int, *, limit: int = 50,
                     offset: int = 0) -> dict:
        _year(year)
        if (type(limit) is not int or not 1 <= limit <= 100
                or type(offset) is not int or offset < 0):
            raise ValueError("invalid v2 match page")
        plan, plan_sha = _calendar_info(self.calendar, year)
        # Integrity-first read checks every source match before paging.
        status, all_data = self._verified_year(year, plan, plan_sha)
        return {
            "source_kind": SOURCE,
            "game_year": year,
            "calendar_sha256": plan_sha,
            "year_status": status,
            "rows": all_data[offset:offset + limit],
            "total": len(all_data),
            "limit": limit,
            "offset": offset,
            "full_option_a_field_set": True,
            "legacy_archive_modified": False,
            "legacy_stats_cache_supports_v2": False,
            "real_tournament_runtime_connected": False,
        }

    def day_matches(self, token: str, *, competition_id: str | None = None,
                    limit: int = 50, offset: int = 0) -> dict:
        slot = GameDaySlot.from_token(token)
        plan, _ = _calendar_info(self.calendar, slot.year)
        scheduled = [
            comp for comp, days in plan["competition_days"].items()
            if token in days
        ]
        if not scheduled or (
            competition_id is not None and competition_id not in scheduled
        ):
            raise CareerV2MatchConflict("v2 day not approved for competition")
        if (type(limit) is not int or not 1 <= limit <= 100
                or type(offset) is not int or offset < 0
                or (competition_id is not None
                    and (type(competition_id) is not str or not competition_id))):
            raise ValueError("invalid v2 day page")
        _, plan_sha = _calendar_info(self.calendar, slot.year)
        status, verified = self._verified_year(slot.year, plan, plan_sha)
        selected = [
            row for row in verified if row["game_day_token"] == token
            and (competition_id is None
                 or row["competition_id"] == competition_id)
        ]
        return {
            "source_kind": SOURCE, "game_year": slot.year,
            "game_day_token": token, "competition_id": competition_id,
            "year_status": status,
            "rows": selected[offset:offset + limit],
            "total": len(selected), "limit": limit, "offset": offset,
            "full_option_a_field_set": True,
            "legacy_archive_modified": False,
            "legacy_stats_cache_supports_v2": False,
            "real_tournament_runtime_connected": False,
        }


def main() -> None:
    """Inspect pre-existing v2 sidecar without ever writing source DBs."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Read fictional Option-A sidecar results incl. year 10000+"
    )
    parser.add_argument("--slot-root", type=Path, required=True)
    parser.add_argument("--year", type=int)
    parser.add_argument("--day-token")
    parser.add_argument("--competition-id")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    if (args.year is None) == (args.day_token is None):
        parser.error("provide exactly one of --year or --day-token")
    if args.year is not None and args.competition_id is not None:
        parser.error("--competition-id requires --day-token")
    archive = CareerV2OptionAArchive(
        args.slot_root / "fictional_option_a_v2.sqlite3",
        args.slot_root / "sandbox_calendar_v2.sqlite3",
        legacy_archive_path=args.slot_root / "historical_matches.sqlite3",
    )
    result = (
        archive.year_matches(
            args.year, limit=args.limit, offset=args.offset,
        ) if args.year is not None else archive.day_matches(
            args.day_token, competition_id=args.competition_id,
            limit=args.limit, offset=args.offset,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
