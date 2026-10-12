"""Stage43G-79: opt-in independent SQLite school index for sealed v2 A.

Building writes ONLY a new sidecar and never alters match or calendar SQLite.
The index is derived, never authoritative. Source seal/ledger/calendar checks
and visible full-A payload SHA checks remain mandatory for every page.
A deeper explicit mode verifies ALL original rows and all indexed memberships.
No background refresh, no migration, no false unlimited-years guarantee.
"""
from __future__ import annotations

from contextlib import ExitStack, closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from . import career_calendar_v2 as calendar_v2
from .career_calendar_v2 import CareerCalendarV2Archive
from .career_option_a_storage_profile import _read_only
from .career_v2_option_a_archive import (
    CareerV2MatchConflict, _calendar_info, _ledger, _verify_match,
)
from .career_v2_school_game_page import (
    CareerV2SchoolPageConflict, _presentation, MAX_WINDOW_YEARS, PAGE_SIZE,
)
from .historical_match_archive import _canonical, _digest

SCHEMA = "derived_v2_school_lookup_1"
_FILENAME = "fictional_v2_school_read_index.sqlite3"
_SQL = """
CREATE TABLE meta (
  schema_version TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  calendar_path TEXT NOT NULL,
  start_year INTEGER NOT NULL,
  end_year INTEGER NOT NULL
);
CREATE TABLE indexed_year (
  year INTEGER PRIMARY KEY,
  calendar_sha256 TEXT NOT NULL,
  ledger_sha256 TEXT NOT NULL,
  match_count INTEGER NOT NULL,
  membership_count INTEGER NOT NULL,
  memberships_sha256 TEXT NOT NULL
);
CREATE TABLE school_game (
  school_id TEXT NOT NULL,
  year INTEGER NOT NULL,
  competition_id TEXT NOT NULL,
  match_id TEXT NOT NULL,
  game_day_token TEXT NOT NULL,
  record_sha256 TEXT NOT NULL,
  PRIMARY KEY (school_id,year,competition_id,match_id)
);
CREATE INDEX idx_v2_school_game_date ON school_game (
  school_id,year,game_day_token,competition_id,match_id
);
CREATE INDEX idx_v2_school_game_year ON school_game(year);
"""


class CareerV2ReadIndexConflict(CareerV2SchoolPageConflict):
    """Source provenance, sealed ledger or derived school index differs."""


def _paths(v2: str | Path, calendar: str | Path,
           index: str | Path) -> tuple[Path, Path, Path]:
    paths = tuple(Path(p).resolve() for p in (v2, calendar, index))
    if len(set(paths)) != 3:
        raise ValueError("v2 original, fictional calendar and index must differ")
    return paths


def _validate(start_year: int, end_year: int) -> None:
    if (type(start_year) is not int or type(end_year) is not int
            or start_year < 10000 or end_year < start_year
            or end_year - start_year >= MAX_WINDOW_YEARS):
        raise ValueError("derived index covers at most 100 fictional v2 years")


def _member(row: sqlite3.Row, school_id: str) -> tuple:
    return (
        school_id, row["year"], row["competition_id"], row["match_id"],
        row["game_day_token"], row["record_sha256"],
    )


def _source_checked_header(conn: sqlite3.Connection, calendar: CareerCalendarV2Archive,
                           header: sqlite3.Row) -> tuple[dict, str]:
    year = header["year"]
    if header["status"] != "sealed":
        raise CareerV2ReadIndexConflict("unsealed fictional v2 year")
    plan, plan_sha = _calendar_info(calendar, year)
    if plan_sha != header["calendar_sha256"]:
        raise CareerV2ReadIndexConflict("v2 calendar SHA differs")
    count, ledger = _ledger(conn, year)
    if (count, ledger) != (header["match_count"], header["ledger_sha256"]):
        raise CareerV2ReadIndexConflict("sealed v2 ledger differs")
    return plan, plan_sha


def build_v2_school_read_index(v2_path: str | Path,
                               calendar_path: str | Path,
                               index_path: str | Path, *,
                               start_year: int, end_year: int) -> dict:
    """Build a new, immutable-by-policy sidecar only on explicit request.

    Creation is atomic and fails if the target already exists. The source
    remains mode=ro throughout. No automatic rebuilding from a GUI read.
    """
    _validate(start_year, end_year)
    source, calendar_file, target = _paths(v2_path, calendar_path, index_path)
    if target.exists():
        raise FileExistsError("derived v2 school index already exists")
    if not source.is_file() or not calendar_file.is_file():
        raise FileNotFoundError("both fictional v2 source and calendar required")
    calendar = CareerCalendarV2Archive(calendar_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".v2-school-index-", suffix=".sqlite3",
            dir=target.parent, delete=False,
        ) as temp:
            temp_path = Path(temp.name)
        with closing(_read_only(source)) as src, closing(
            sqlite3.connect(temp_path)
        ) as dest:
            src.row_factory = sqlite3.Row
            dest.executescript(_SQL)
            dest.execute(
                "INSERT INTO meta VALUES (?,?,?,?,?)",
                (SCHEMA, str(source), str(calendar_file), start_year, end_year),
            )
            src.execute("BEGIN")
            headers = src.execute(
                "SELECT * FROM v2_game_years "
                "WHERE year BETWEEN ? AND ? ORDER BY year",
                (start_year, end_year),
            ).fetchall()
            plans = {
                header["year"]: _source_checked_header(src, calendar, header)
                for header in headers
            }
            for header in headers:
                year = header["year"]
                plan, plan_sha = plans[year]
                membership_rows: list[tuple] = []
                for row in src.execute(
                    "SELECT * FROM v2_option_a_matches WHERE year=? "
                    "ORDER BY competition_id,match_id",
                    (year,),
                ):
                    game = _verify_match(row, plan, plan_sha)
                    a, b = game.get("team1_id"), game.get("team2_id")
                    if (type(a) is not str or not a or type(b) is not str
                            or not b or a == b):
                        raise CareerV2ReadIndexConflict(
                            "invalid source school membership"
                        )
                    for school_id in (a, b):
                        membership = _member(row, school_id)
                        dest.execute(
                            "INSERT INTO school_game VALUES (?,?,?,?,?,?)",
                            membership,
                        )
                        membership_rows.append(membership)
                membership_rows.sort()
                count = len(membership_rows)
                if count != 2 * header["match_count"]:
                    raise CareerV2ReadIndexConflict(
                        "school membership count differs from sealed source"
                    )
                dest.execute(
                    "INSERT INTO indexed_year VALUES (?,?,?,?,?,?)",
                    (year, plan_sha, header["ledger_sha256"],
                     header["match_count"], count,
                     _digest(_canonical(membership_rows))),
                )
            dest.commit()
            # Reject source ledger drift before publishing the derived index.
            for header in headers:
                count, ledger = _ledger(src, header["year"])
                if (count, ledger) != (
                    header["match_count"], header["ledger_sha256"]
                ):
                    raise CareerV2ReadIndexConflict(
                        "source changed while indexing"
                    )
        # An atomic hard-link refuses an already present target, unlike
        # os.replace which could silently destroy a previously saved index.
        os.link(temp_path, target)
        return {
            "index_path": str(target), "source_path": str(source),
            "calendar_path": str(calendar_file),
            "indexed_saved_years": [row["year"] for row in headers],
            "indexed_source_matches": sum(row["match_count"] for row in headers),
            "source_sqlite_modified": False,
            "calendar_sqlite_modified": False,
            "derived_index_is_not_authoritative": True,
            "source_records_are_fictional": True,
        }
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _check_index_meta(cache: sqlite3.Connection, source: Path,
                      calendar: Path, start: int, end: int) -> tuple[int, int]:
    meta = cache.execute("SELECT * FROM meta").fetchall()
    if len(meta) != 1:
        raise CareerV2ReadIndexConflict("derived school index metadata missing")
    info = meta[0]
    if (info["schema_version"] != SCHEMA
            or info["source_path"] != str(source)
            or info["calendar_path"] != str(calendar)
            or not info["start_year"] <= start <= end <= info["end_year"]):
        raise CareerV2ReadIndexConflict(
            "derived school index belongs to a different saved source or year"
        )
    return info["start_year"], info["end_year"]


def _verify_index_years(source: sqlite3.Connection, cache: sqlite3.Connection,
                        calendar: CareerCalendarV2Archive, start: int,
                        end: int, *, verify_scope: str) -> dict:
    saved = source.execute(
        "SELECT * FROM v2_game_years WHERE year BETWEEN ? AND ? ORDER BY year",
        (start, end),
    ).fetchall()
    index_years = cache.execute(
        "SELECT * FROM indexed_year WHERE year BETWEEN ? AND ? ORDER BY year",
        (start, end),
    ).fetchall()
    if [h["year"] for h in saved] != [h["year"] for h in index_years]:
        raise CareerV2ReadIndexConflict(
            "derived index does not cover exact saved v2 years"
        )
    plans = {}
    for header, indexed in zip(saved, index_years):
        plan, sha = _source_checked_header(source, calendar, header)
        if (indexed["calendar_sha256"] != sha
                or indexed["ledger_sha256"] != header["ledger_sha256"]
                or indexed["match_count"] != header["match_count"]
                or indexed["membership_count"] != 2 * header["match_count"]):
            raise CareerV2ReadIndexConflict("derived year proof differs")
        plans[header["year"]] = (plan, sha)
        if verify_scope == "selected_years":
            expected = []
            for row in source.execute(
                "SELECT * FROM v2_option_a_matches WHERE year=? "
                "ORDER BY competition_id,match_id",
                (header["year"],),
            ):
                game = _verify_match(row, plan, sha)
                a, b = game.get("team1_id"), game.get("team2_id")
                if (type(a) is not str or not a or type(b) is not str
                        or not b or a == b):
                    raise CareerV2ReadIndexConflict("invalid school provenance")
                expected.extend((_member(row, a), _member(row, b)))
            expected.sort()
            actual = [
                tuple(row) for row in cache.execute(
                    "SELECT school_id,year,competition_id,match_id,"
                    "game_day_token,record_sha256 FROM school_game "
                    "WHERE year=? ORDER BY school_id,year,competition_id,match_id",
                    (header["year"],),
                )
            ]
            if (expected != actual
                    or _digest(_canonical(actual)) !=
                    indexed["memberships_sha256"]):
                raise CareerV2ReadIndexConflict(
                    "derived school memberships differ from full v2 source"
                )
    return plans


class _SnapshotCalendar:
    """Use the calendar's existing verifier on this request's pinned read."""

    def __init__(self, connection):
        self.connection = connection

    def read(self, year):
        row = self.connection.execute(
            "SELECT schema_version,source_kind,policy_id,content_sha256,plan_json "
            "FROM sandbox_year_plans WHERE game_year=?", (year,),
        ).fetchone()
        if row is None:
            return None
        if tuple(row[:3]) != (calendar_v2.SCHEMA_VERSION,
                             calendar_v2.SOURCE, calendar_v2.POLICY):
            raise calendar_v2.SandboxCalendarConflict("stored calendar metadata changed")
        return calendar_v2._verified(row[4], row[3], year)


class _SchoolReadRequest:
    """Private, single-call scope. Never persists or accepts external proofs.

    Each file has a pinned SQLite read transaction and an independent commit
    watcher (data_version inside a WAL snapshot alone cannot observe drift).
    Snapshots across separate files are not one atomic SQLite transaction.
    """

    def __init__(self, stack, source_path, calendar_path):
        self.stack = stack
        self.source_path, self.calendar_path = source_path, calendar_path
        self.connections = {}
        self.watchers = []
        self.source = self.connection(source_path)
        self.calendar = _SnapshotCalendar(self.connection(calendar_path))

    def connection(self, path):
        if path not in self.connections:
            identity = path.stat()
            watcher = self.stack.enter_context(closing(_read_only(path)))
            version = watcher.execute("PRAGMA data_version").fetchone()[0]
            conn = self.stack.enter_context(closing(_read_only(path)))
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            # Acquire the snapshot now, including files with no selected rows.
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
            self.connections[path] = conn
            self.watchers.append((path, watcher, version, identity.st_dev, identity.st_ino))
        return self.connections[path]

    def prepare(self, index_path, start, end, verify_scope):
        cache = self.connection(index_path)
        _check_index_meta(cache, self.source_path, self.calendar_path, start, end)
        plans = _verify_index_years(self.source, cache, self.calendar, start, end,
                                    verify_scope=verify_scope)
        return _VerifiedSchoolSlice(self.source, cache, plans, start, end, verify_scope)

    def check_unchanged(self):
        for path, watcher, version, device, inode in self.watchers:
            try:
                identity = path.stat()
            except FileNotFoundError as exc:
                raise CareerV2ReadIndexConflict("saved file removed during school read") from exc
            if ((identity.st_dev, identity.st_ino) != (device, inode)
                    or watcher.execute("PRAGMA data_version").fetchone()[0] != version):
                raise CareerV2ReadIndexConflict("saved source or index changed during school read")


@contextmanager
def _school_read_request(source_path, calendar_path):
    with ExitStack() as stack:
        request = _SchoolReadRequest(stack, source_path, calendar_path)
        yield request
        request.check_unchanged()


class _VerifiedSchoolSlice:
    """Count and display share verified plans and the same source/index reads."""

    def __init__(self, source, cache, plans, start, end, verify_scope):
        self.source, self.cache, self.plans = source, cache, plans
        self.start, self.end, self.verify_scope = start, end, verify_scope

    def page(self, school_id, competition_id, limit, offset):
        source, cache, plans = self.source, self.cache, self.plans
        start_year, end_year, verify_scope = self.start, self.end, self.verify_scope
        where = "school_id=? AND year BETWEEN ? AND ?"
        params: tuple = (school_id, start_year, end_year)
        if competition_id is not None:
            where += " AND competition_id=?"
            params += (competition_id,)
        total = cache.execute(
            "SELECT COUNT(*) FROM school_game WHERE " + where, params,
        ).fetchone()[0]
        members = cache.execute(
            "SELECT * FROM school_game WHERE " + where +
            " ORDER BY year,game_day_token,competition_id,match_id "
            "LIMIT ? OFFSET ?",
            params + (limit, offset),
        ).fetchall()
        records = []
        for member in members:
            original = source.execute(
                "SELECT * FROM v2_option_a_matches WHERE "
                "year=? AND competition_id=? AND match_id=?",
                (member["year"], member["competition_id"], member["match_id"]),
            ).fetchone()
            if original is None:
                raise CareerV2ReadIndexConflict(
                    "derived school lookup points to a missing source match"
                )
            if (member["record_sha256"] != original["record_sha256"]
                    or member["game_day_token"] != original["game_day_token"]):
                raise CareerV2ReadIndexConflict(
                    "derived school lookup points to altered original identity"
                )
            game = _presentation(
                original, school_id, *plans[member["year"]],
            )
            if (game["year"], game["competition_id"],
                    game["match_id"], game["game_day_token"]) != (
                member["year"], member["competition_id"],
                member["match_id"], member["game_day_token"]
            ):
                raise CareerV2ReadIndexConflict(
                    "derived lookup does not match verified original game"
                )
            records.append(game)
        return {
            "school_id": school_id, "start_year": start_year,
            "end_year": end_year, "competition_id": competition_id,
            "records": records, "total": total, "limit": limit, "offset": offset,
            "verification_scope": verify_scope,
            "verified_saved_years": list(plans),
            "saved_year_metadata_and_ledger_verified": True,
            "visible_match_checksums_verified": True,
            "all_selected_year_payloads_verified":
                verify_scope == "selected_years",
            "school_membership_integrity_for_years_verified":
                verify_scope == "selected_years",
            "source_records_not_modified": True,
            "legacy_records_combined": False,
            "school_filter_uses_unindexed_json_scan": False,
            "uses_separate_verified_school_index": True,
            "derived_index_does_not_replace_source": True,
            "offpage_derived_memberships_verified":
                verify_scope == "selected_years",
            "real_tournament_runtime_connected": False,
        }


def read_indexed_v2_school_page(
    v2_path: str | Path, calendar_path: str | Path,
    index_path: str | Path, school_id: str, *,
    start_year: int, end_year: int, competition_id: str | None = None,
    limit: int = PAGE_SIZE, offset: int = 0,
    verify_scope: str = "page",
) -> dict:
    """Read a separately indexed page, checking original v2 facts on display."""
    _validate(start_year, end_year)
    if (type(school_id) is not str or not school_id
            or type(limit) is not int or not 1 <= limit <= 200
            or type(offset) is not int or offset < 0
            or (competition_id is not None and
                (type(competition_id) is not str or not competition_id))
            or verify_scope not in ("page", "selected_years")):
        raise ValueError("invalid indexed fictional v2 school page")
    source_path, calendar_path, index_path = _paths(
        v2_path, calendar_path, index_path,
    )
    with _school_read_request(source_path, calendar_path) as request:
        verified = request.prepare(index_path, start_year, end_year, verify_scope)
        result = verified.page(school_id, competition_id, limit, offset)
    return result
