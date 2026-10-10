"""Append-only school-year roster snapshots and stable career player IDs.

A school-year snapshot is immutable. The career identity table detects
accidental reidentification across years, even if names happen to match.
No match-by-name heuristics are used.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from game_core.career_rosters import advance_school_roster
from .players import Player, SchoolRoster, validate_school_roster


class CareerRosterConflictError(ValueError):
    pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS career_school_rosters (
    year INTEGER NOT NULL CHECK(year > 0),
    school_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (year, school_id)
);
CREATE INDEX IF NOT EXISTS idx_career_rosters_school_year
    ON career_school_rosters(school_id, year);
CREATE TABLE IF NOT EXISTS career_player_identities (
    player_id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL,
    entry_year INTEGER NOT NULL,
    identity_sha256 TEXT NOT NULL,
    identity_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_career_players_school_entry
    ON career_player_identities(school_id, entry_year, player_id);
"""


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(player: Player) -> str:
    values = asdict(player)
    # Grade changes year by year, while personal identity is stable.
    values.pop("academic_year")
    return _json(values)


def _decode(raw: str) -> SchoolRoster:
    data = json.loads(raw)
    roster = SchoolRoster(
        reference_year=data["reference_year"],
        school_id=data["school_id"],
        program_id=data["program_id"],
        school_name=data["school_name"],
        rng_seed=data["rng_seed"],
        players=[Player(**row) for row in data["players"]],
        cohort_policy=data.get("cohort_policy", "initial_v1"),
    )
    validate_school_roster(roster)
    return roster


class CareerRosterArchive:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _get(conn: sqlite3.Connection, year: int, school_id: str):
        row = conn.execute(
            "SELECT payload_json, content_sha256 FROM career_school_rosters "
            "WHERE year=? AND school_id=?",
            (year, school_id),
        ).fetchone()
        if row is None:
            return None
        if _digest(row["payload_json"]) != row["content_sha256"]:
            raise CareerRosterConflictError("archived roster digest mismatch")
        roster = _decode(row["payload_json"])
        if roster.reference_year != year or roster.school_id != school_id:
            raise CareerRosterConflictError("archived roster identity mismatch")
        return roster

    @staticmethod
    def _insert(conn: sqlite3.Connection, roster: SchoolRoster) -> bool:
        validate_school_roster(roster)
        payload = _json(roster.to_dict())
        fingerprint = _digest(payload)
        known = conn.execute(
            "SELECT content_sha256, payload_json "
            "FROM career_school_rosters WHERE year=? AND school_id=?",
            (roster.reference_year, roster.school_id),
        ).fetchone()
        if known:
            if (known["content_sha256"] != fingerprint or
                    known["payload_json"] != payload):
                raise CareerRosterConflictError(
                    "archived school roster differs from new snapshot"
                )
            return False
        for player in roster.players:
            identity = _identity(player)
            sha = _digest(identity)
            old = conn.execute(
                "SELECT identity_sha256, identity_json FROM career_player_identities "
                "WHERE player_id=?", (player.player_id,),
            ).fetchone()
            if old is None:
                conn.execute(
                    "INSERT INTO career_player_identities "
                    "(player_id, school_id, entry_year, identity_sha256, identity_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (player.player_id, player.school_id, player.entry_year, sha, identity),
                )
            elif old["identity_sha256"] != sha or old["identity_json"] != identity:
                raise CareerRosterConflictError(
                    f"career player identity changed: {player.player_id}"
                )
        conn.execute(
            "INSERT INTO career_school_rosters "
            "(year, school_id, content_sha256, payload_json) VALUES (?, ?, ?, ?)",
            (roster.reference_year, roster.school_id, fingerprint, payload),
        )
        return True

    def save_initial_roster(self, roster: SchoolRoster) -> dict:
        if roster.cohort_policy != "initial_v1":
            raise ValueError("first saved roster must be the initial cohort")
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                present = conn.execute(
                    "SELECT 1 FROM career_school_rosters WHERE school_id=? LIMIT 1",
                    (roster.school_id,),
                ).fetchone()
                # An existing initial snapshot may be re-saved idempotently.
                if present:
                    oldest = conn.execute(
                        "SELECT MIN(year) FROM career_school_rosters WHERE school_id=?",
                        (roster.school_id,),
                    ).fetchone()[0]
                    if oldest != roster.reference_year:
                        raise CareerRosterConflictError(
                            "initial school roster year differs"
                        )
                inserted = self._insert(conn, roster)
        return {
            "year": roster.reference_year,
            "school_id": roster.school_id,
            "inserted": inserted,
        }

    def advance_and_save(self, team, *, next_year: int, career_seed: int,
                         generator=None) -> dict:
        """Advance only from an archived prior-year school snapshot.

        The entire operation is transactional; no partial new roster or
        partial identity set survives a collision or validation error.
        """
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                previous = self._get(conn, next_year - 1, team.school_id)
                if previous is None:
                    raise CareerRosterConflictError(
                        f"missing previous school roster for year {next_year-1}"
                    )
                transition = advance_school_roster(
                    previous, team, next_year=next_year,
                    career_seed=career_seed, generator=generator,
                )
                inserted = self._insert(conn, transition.roster)
        return {**transition.summary(), "inserted": inserted}

    def roster(self, year: int, school_id: str) -> SchoolRoster | None:
        if not self.db_path.is_file():
            return None
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return self._get(conn, year, school_id)

    def player_history(self, player_id: str) -> list[dict]:
        """Read the annual membership snapshots for one permanent player ID."""
        if not self.db_path.is_file():
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            identity = conn.execute(
                "SELECT school_id FROM career_player_identities WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if identity is None:
                return []
            years = conn.execute(
                "SELECT year FROM career_school_rosters WHERE school_id=? "
                "ORDER BY year", (identity["school_id"],),
            ).fetchall()
            found = []
            for row in years:
                roster = self._get(conn, row["year"], identity["school_id"])
                for player in roster.players:
                    if player.player_id == player_id:
                        found.append({
                            "year": roster.reference_year,
                            "school_id": roster.school_id,
                            "player_id": player_id,
                            "academic_year": player.academic_year,
                            "roster_no": player.roster_no,
                            "display_name": player.display_name,
                        })
            return found

    def school_years(self, school_id: str) -> list[int]:
        if not self.db_path.is_file():
            return []
        with sqlite3.connect(self.db_path) as conn:
            return [
                row[0] for row in conn.execute(
                    "SELECT year FROM career_school_rosters "
                    "WHERE school_id=? ORDER BY year", (school_id,),
                )
            ]
