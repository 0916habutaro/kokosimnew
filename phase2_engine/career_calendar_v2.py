"""Stage43G-25: explicit fictional calendar v2 and immutable year/day-slot plans.

Do not mistake game day slots for official schedules.  The official 2026
competition master is not automatically repeated; callers must supply an
explicit synthetic game policy and its dates for EACH target career year.
Never migrate, overwrite or re-date legacy match records here.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from .career_era_calendar_contract import (
    CAREER_START_YEAR, MAX_GREGORIAN_YEAR, _year,
)
from .career_option_a_storage_profile import _read_only

SCHEMA_VERSION = "career_calendar_v2_sandbox_1"
SOURCE = "explicit_fictional_game_calendar_not_official"
POLICY = "opt_in_synthetic_calendar_v1"
_DAY = re.compile(r"([0-9]{2})-([0-9]{2})\Z")
_TOKEN = re.compile(r"G([1-9][0-9]*):([0-9]{2})-([0-9]{2})\Z")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sandbox_year_plans (
    game_year INTEGER PRIMARY KEY CHECK (game_year > 0),
    schema_version TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    plan_json TEXT NOT NULL
);
"""


class SandboxCalendarConflict(ValueError):
    """Calendar contract, persisted digest or schedule attribution differs."""


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


@dataclass(frozen=True, order=True)
class GameDaySlot:
    """Sortable logical game date; no datetime.date needed after year 9999."""

    year: int
    month: int
    day: int

    def __post_init__(self) -> None:
        _year(self.year)
        if type(self.month) is not int or type(self.day) is not int:
            raise ValueError("game slot month/day must be integers")
        month_days = (
            31, 29 if _leap(self.year) else 28, 31, 30, 31, 30,
            31, 31, 30, 31, 30, 31,
        )
        if (not 1 <= self.month <= 12
                or not 1 <= self.day <= month_days[self.month - 1]):
            raise ValueError("invalid game calendar day")

    @property
    def day_of_year(self) -> int:
        lengths = (
            31, 29 if _leap(self.year) else 28, 31, 30, 31, 30,
            31, 31, 30, 31, 30, 31,
        )
        return sum(lengths[:self.month - 1]) + self.day

    @property
    def token(self) -> str:
        return f"G{self.year}:{self.month:02d}-{self.day:02d}"

    @property
    def iso_date(self) -> str | None:
        return (
            date(self.year, self.month, self.day).isoformat()
            if self.year <= MAX_GREGORIAN_YEAR else None
        )

    @classmethod
    def from_token(cls, token: str) -> GameDaySlot:
        if not isinstance(token, str):
            raise ValueError("invalid logical game date token")
        m = _TOKEN.fullmatch(token)
        if m is None:
            raise ValueError("invalid logical game date token")
        return cls(int(m[1]), int(m[2]), int(m[3]))

    @classmethod
    def from_iso(cls, value: str) -> GameDaySlot:
        if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value,
        ):
            raise ValueError("unsupported legacy ISO date")
        y, m, d = map(int, value.split("-"))
        if y > MAX_GREGORIAN_YEAR:
            raise ValueError("ISO date beyond supported Gregorian calendar")
        return cls(y, m, d)


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def explicit_sandbox_plan(game_year: int, competition_days: dict,
                          *, policy_id: str = POLICY,
                          approved_for_fictional_game: bool = False,
                          allowed_competitions: set[str] | None = None) -> dict:
    """Bind *supplied* competition dates; never infer official next-year data.

    A caller explicitly opts in to fictional dates for a test game year.
    Avoid generating a real tournament schedule from the 2026 official source.
    """
    _year(game_year)
    if game_year < CAREER_START_YEAR:
        raise ValueError("game calendar precedes career beginning")
    if (type(approved_for_fictional_game) is not bool
            or not approved_for_fictional_game
            or type(policy_id) is not str or not policy_id.strip()
            or policy_id != POLICY):
        raise SandboxCalendarConflict("explicit fictional-game policy required")
    if (type(competition_days) is not dict or not competition_days
            or len(competition_days) > 200
            or (allowed_competitions is not None
                and not isinstance(allowed_competitions, set))):
        raise ValueError("invalid competition day list")
    days = {}
    for comp, raw_days in sorted(competition_days.items()):
        if (type(comp) is not str or not comp or len(comp) > 128
                or (allowed_competitions is not None
                    and comp not in allowed_competitions)
                or not isinstance(raw_days, list)
                or not 1 <= len(raw_days) <= 366):
            raise ValueError("invalid competition calendar entry")
        slots = []
        for raw in raw_days:
            if not isinstance(raw, str) or _DAY.fullmatch(raw) is None:
                raise ValueError("invalid MM-DD game calendar entry")
            mm, dd = map(int, raw.split("-"))
            slots.append(GameDaySlot(game_year, mm, dd))
        tokens = [slot.token for slot in sorted(slots)]
        if len(set(tokens)) != len(tokens):
            raise SandboxCalendarConflict("repeated fixture day in competition")
        days[comp] = tokens
    return {
        "schema_version": SCHEMA_VERSION,
        "source_kind": SOURCE,
        "policy_id": policy_id,
        "game_year": game_year,
        "approved_for_fictional_game": True,
        "official_dates_proven": False,
        "competition_days": days,
    }


def _verified(raw: str, digest: str, year: int) -> dict:
    if _digest(raw) != digest:
        raise SandboxCalendarConflict("stored game calendar digest differs")
    try:
        plan = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise SandboxCalendarConflict("unreadable saved calendar plan") from exc
    if (not isinstance(plan, dict)
            or plan.get("game_year") != year
            or plan.get("source_kind") != SOURCE
            or plan.get("schema_version") != SCHEMA_VERSION
            or plan.get("policy_id") != POLICY
            or plan.get("approved_for_fictional_game") is not True
            or plan.get("official_dates_proven") is not False
            or not isinstance(plan.get("competition_days"), dict)):
        raise SandboxCalendarConflict("persisted game calendar contract changed")
    days = plan["competition_days"]
    rebuild = {}
    for comp, tokens in days.items():
        if not isinstance(tokens, list):
            raise SandboxCalendarConflict("persisted date list invalid")
        raw_days = []
        for token in tokens:
            try:
                slot = GameDaySlot.from_token(token)
            except ValueError as exc:
                raise SandboxCalendarConflict("persisted day token invalid") from exc
            if slot.year != year:
                raise SandboxCalendarConflict("persisted game year mismatch")
            raw_days.append(f"{slot.month:02d}-{slot.day:02d}")
        rebuild[comp] = raw_days
    try:
        expected = explicit_sandbox_plan(
            year, rebuild, policy_id=POLICY,
            approved_for_fictional_game=True,
        )
    except (ValueError, SandboxCalendarConflict) as exc:
        raise SandboxCalendarConflict("persisted dates invalid") from exc
    if expected != plan:
        raise SandboxCalendarConflict("persisted game calendar changed")
    return plan


class CareerCalendarV2Archive:
    """A separate immutable SQLite sandbox schedule (never the source match DB)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record(self, plan: dict) -> dict:
        if not isinstance(plan, dict):
            raise ValueError("invalid game calendar plan")
        year = plan.get("game_year")
        if type(year) is not int:
            raise ValueError("invalid calendar year")
        raw = _json(plan)
        digest = _digest(raw)
        _verified(raw, digest, year)  # reject forged approval/contracts
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as con:
            con.executescript(_SCHEMA)
            old = con.execute(
                "SELECT schema_version,source_kind,policy_id,"
                "content_sha256,plan_json FROM sandbox_year_plans "
                "WHERE game_year=?", (year,),
            ).fetchone()
            if old is not None:
                if old != (SCHEMA_VERSION, SOURCE, POLICY, digest, raw):
                    raise SandboxCalendarConflict(
                        "immutable year calendar conflicts with saved plan"
                    )
                return {"game_year": year, "inserted": False,
                        "plan_sha256": digest}
            with con:
                con.execute(
                    "INSERT INTO sandbox_year_plans VALUES (?,?,?,?,?,?)",
                    (year, SCHEMA_VERSION, SOURCE, POLICY, digest, raw),
                )
        return {"game_year": year, "inserted": True,
                "plan_sha256": digest}

    def read(self, year: int) -> dict | None:
        _year(year)
        if not self.path.is_file():
            return None
        with closing(_read_only(self.path)) as con:
            row = con.execute(
                "SELECT schema_version,source_kind,policy_id,"
                "content_sha256,plan_json FROM sandbox_year_plans "
                "WHERE game_year=?", (year,),
            ).fetchone()
        if row is None:
            return None
        if row[:3] != (SCHEMA_VERSION, SOURCE, POLICY):
            raise SandboxCalendarConflict("stored calendar metadata changed")
        return _verified(row[4], row[3], year)

    def list_years(self) -> list[int]:
        if not self.path.is_file():
            return []
        with closing(_read_only(self.path)) as con:
            return [r[0] for r in con.execute(
                "SELECT game_year FROM sandbox_year_plans ORDER BY game_year"
            )]


def verify_sandbox_match_dates(calendar_path: str | Path,
                               matches_path: str | Path) -> dict:
    """Cross-check legacy ISO game dates against explicit fictional plans.

    This is a read-only synthetic provenance audit, not an endorsement of
    real annual tournaments. A match with year>=10000 is rejected because
    the legacy match-date storage contract is not v2-aware.
    """
    calendar = CareerCalendarV2Archive(calendar_path)
    years = calendar.list_years()
    if not years:
        raise SandboxCalendarConflict("no approved sandbox game calendar")
    match_path = Path(matches_path)
    if not match_path.is_file():
        raise FileNotFoundError("historical matches archive missing")
    found = {}
    for year in years:
        found[year] = calendar.read(year)["competition_days"]
    total = 0
    with closing(_read_only(match_path)) as con:
        for year, competition, match_date in con.execute(
            "SELECT year,competition_id,match_date "
            "FROM historical_matches ORDER BY year,competition_id,match_id"
        ):
            if year not in found:
                raise SandboxCalendarConflict("match year lacks sandbox plan")
            try:
                slot = GameDaySlot.from_iso(match_date)
            except ValueError as exc:
                raise SandboxCalendarConflict(
                    "match has date outside supported legacy ISO format"
                ) from exc
            if (slot.year != year
                    or slot.token not in found[year].get(competition, [])):
                raise SandboxCalendarConflict(
                    "match date has no approved fictional calendar slot"
                )
            total += 1
    return {
        "source_kind": SOURCE,
        "game_years": years,
        "checked_archived_matches": total,
        "all_match_dates_within_approved_sandbox_plans": True,
        "calendar_plan_is_not_official_schedule": True,
        "historical_match_sqlite_modified": False,
    }
