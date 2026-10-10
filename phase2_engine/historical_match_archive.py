"""Append-only, slot-scoped archive of completed live-season games.

Stores Option A historical facts without retaining per-plate-appearance events.
The live JSON save remains the source for replay and crash reconciliation.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable, Mapping


class HistoricalMatchConflictError(ValueError):
    """An existing archived match differs from a replayed or restored result."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS archive_identity (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS career_years (
    year INTEGER PRIMARY KEY CHECK (year > 0),
    metadata_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'sealed')),
    match_count INTEGER,
    ledger_sha256 TEXT
);
CREATE TABLE IF NOT EXISTS historical_matches (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    match_date TEXT NOT NULL,
    date_source TEXT NOT NULL,
    team1_id TEXT NOT NULL,
    team2_id TEXT NOT NULL,
    team1_score INTEGER,
    team2_score INTEGER,
    score_source TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (year, competition_id, match_id)
);
CREATE INDEX IF NOT EXISTS idx_history_date
    ON historical_matches(year, match_date, competition_id, match_id);
CREATE INDEX IF NOT EXISTS idx_history_team1
    ON historical_matches(year, team1_id, match_date, competition_id, match_id);
CREATE INDEX IF NOT EXISTS idx_history_team2
    ON historical_matches(year, team2_id, match_date, competition_id, match_id);
"""


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _score(value: object, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label}: expected non-negative integer or null")
    return value


def _history_payload(year: int, record: Mapping[str, object]) -> dict:
    """Normalize a completed runtime record; events are deliberately excluded."""
    if not isinstance(year, int) or isinstance(year, bool) or year < 1:
        raise ValueError("history year must be positive integer")
    if record.get("status") != "completed":
        raise ValueError("only completed match records can be archived")
    required = ("competition_id", "match_id", "team1_id", "team2_id")
    for field in required:
        if not isinstance(record.get(field), str) or not record[field]:
            raise ValueError(f"archived match missing {field}")
    if record["team1_id"] == record["team2_id"]:
        raise ValueError("archived match has identical opponents")

    first = _score(record.get("team1_score"), "team1_score")
    second = _score(record.get("team2_score"), "team2_score")
    if (first is None) != (second is None):
        raise ValueError("both match scores must be present or absent")
    if first is not None and first == second:
        raise ValueError("completed match scores cannot be tied")
    winner = str(record.get("winner_id") or "")
    loser = str(record.get("loser_id") or "")
    if (winner, loser) not in (
        (record["team1_id"], record["team2_id"]),
        (record["team2_id"], record["team1_id"]),
    ):
        raise ValueError("winner/loser do not match participants")
    if first is not None:
        expected = (record["team1_id"], record["team2_id"])
        if first < second:
            expected = expected[::-1]
        if (winner, loser) != expected:
            raise ValueError("winner/loser inconsistent with score")

    detail = record.get("ability_detail")
    if detail is not None and not isinstance(detail, dict):
        raise ValueError("invalid ability_detail")
    detail = detail or {}
    # Non-ability resolvers may emit metadata but not real GameStats.
    has_a_detail = (
        record.get("score_source") == "ability_model_v1"
        and detail.get("score_source") == "ability_model_v1"
    )
    if has_a_detail:
        for field, expected in (
            ("reference_year", year),
            ("competition_id", record["competition_id"]),
            ("match_id", record["match_id"]),
            ("team1_school_id", record["team1_id"]),
            ("team2_school_id", record["team2_id"]),
            ("team1_score", first),
            ("team2_score", second),
        ):
            if detail.get(field) != expected:
                raise ValueError(f"ability detail mismatched {field}")

    innings = None
    teams = None
    batters = None
    pitchers = None
    if has_a_detail:
        innings = detail.get("inning_scores")
        teams = detail.get("team_stats")
        batters = detail.get("batter_stats")
        pitchers = detail.get("pitcher_stats")
        for field, values in (
            ("inning_scores", innings),
            ("team_stats", teams),
            ("batter_stats", batters),
            ("pitcher_stats", pitchers),
        ):
            if values is not None and not isinstance(values, list):
                raise ValueError(f"{field}: expected list or null")

        if innings is not None:
            if first is None or not innings:
                raise ValueError("line score requires complete final score")
            halves = ("top", "bottom")
            expected_half = [
                (i, h)
                for i in range(1, int(detail["last_inning"]) + 1)
                for h in halves
            ]
            if [(r["inning"], r["half"]) for r in innings] != expected_half:
                raise ValueError("invalid archived inning score ordering")
            totals = {"top": 0, "bottom": 0}
            skipped = []
            for row in innings:
                half = row["half"]
                batting = (
                    record["team1_id"] if half == "top" else record["team2_id"]
                )
                if row.get("batting_team_id") != batting:
                    raise ValueError("invalid archived inning batting team")
                if not isinstance(row.get("was_played"), bool):
                    raise ValueError("invalid archived inning played flag")
                if row["was_played"]:
                    value = _score(row.get("runs"), "inning_runs")
                    if value is None:
                        raise ValueError("played inning cannot have null runs")
                    totals[half] += value
                else:
                    if row.get("runs") is not None:
                        raise ValueError("unplayed inning cannot have runs")
                    skipped.append((row["inning"], half))
            if (totals["top"], totals["bottom"]) != (first, second):
                raise ValueError("archived inning totals mismatch")
            last = int(detail["last_inning"])
            if skipped and (
                skipped != [(last, "bottom")]
                or detail.get("ending_half") != "top"
            ):
                raise ValueError("invalid archived unplayed inning")
            if detail.get("ending_half") == "top" and not skipped:
                raise ValueError("top ending missing skipped bottom")

        if teams is not None:
            if len(teams) != 2 or {
                row.get("school_id") for row in teams
            } != {record["team1_id"], record["team2_id"]}:
                raise ValueError("archived team stats mismatch")
            for row in teams:
                target = first if row["school_id"] == record["team1_id"] else second
                if row.get("runs") != target:
                    raise ValueError("archived team runs mismatch")

    # Keep enough metadata to identify the original game, but omit the
    # frequently voluminous list of every MatchEvent.
    return {
        "year": year,
        "competition_id": record["competition_id"],
        "competition_name": str(record.get("competition_name") or ""),
        "match_id": record["match_id"],
        "match_date": str(record.get("match_date") or ""),
        "date_source": str(record.get("date_source") or ""),
        "completed_on": str(record.get("completed_on") or ""),
        "stage_code": str(record.get("stage_code") or ""),
        "phase_code": str(record.get("phase_code") or ""),
        "round_no": int(record.get("round_no") or 0),
        "round_name": str(record.get("round_name") or ""),
        "group_id": str(record.get("group_id") or ""),
        "group_name": str(record.get("group_name") or ""),
        "team1_id": record["team1_id"],
        "team1_name": str(record.get("team1_name") or ""),
        "team2_id": record["team2_id"],
        "team2_name": str(record.get("team2_name") or ""),
        "team1_score": first,
        "team2_score": second,
        "winner_id": winner,
        "loser_id": loser,
        "score_source": str(record.get("score_source") or ""),
        "inning_scores": innings,
        "team_stats": teams,
        "batter_stats": batters,
        "pitcher_stats": pitchers,
    }


class HistoricalMatchArchive:
    """Persistent A-history tied to a save slot, not a replaceable season view."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _identity(
        year: int, rng_seed: int, resolver_contract: str, plan_fingerprint: str
    ) -> str:
        if not resolver_contract or not plan_fingerprint:
            raise ValueError("missing live save identity")
        return _canonical({
            "initial_year": year,
            "rng_seed": rng_seed,
            "resolver_contract": resolver_contract,
            "plan_fingerprint": plan_fingerprint,
        })

    @staticmethod
    def _year_metadata(
        year: int, rng_seed: int, resolver_contract: str, plan_fingerprint: str,
    ) -> str:
        if not isinstance(year, int) or isinstance(year, bool) or year < 1:
            raise ValueError("invalid career year")
        if not isinstance(rng_seed, int) or isinstance(rng_seed, bool):
            raise ValueError("invalid career rng_seed")
        if not resolver_contract or not plan_fingerprint:
            raise ValueError("missing annual game identity")
        return _canonical({
            "year": year, "rng_seed": rng_seed,
            "resolver_contract": resolver_contract,
            "plan_fingerprint": plan_fingerprint,
        })

    @staticmethod
    def _ledger(conn: sqlite3.Connection, year: int) -> tuple[int, str]:
        """Digest ordered immutable records, including their full A snapshots."""
        rows = conn.execute(
            """SELECT competition_id, match_id, record_sha256
               FROM historical_matches WHERE year = ?
               ORDER BY competition_id, match_id""",
            (year,),
        ).fetchall()
        content = _canonical([
            (row[0], row[1], row[2]) for row in rows
        ])
        return len(rows), _digest(content)

    def seal_year(self, year: int, *, expected_match_count: int) -> dict:
        """Seal a completed year; callers must verify runtime readiness first.

        A sealed year accepts an idempotent re-sync of existing records only.
        """
        if (not isinstance(expected_match_count, int)
                or isinstance(expected_match_count, bool)
                or expected_match_count < 0):
            raise ValueError("expected_match_count must be non-negative")
        if not self.db_path.is_file():
            raise ValueError("archive does not exist")
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                entry = conn.execute(
                    "SELECT status, match_count, ledger_sha256 "
                    "FROM career_years WHERE year = ?", (year,),
                ).fetchone()
                if entry is None:
                    raise HistoricalMatchConflictError("career year not registered")
                count, ledger = self._ledger(conn, year)
                if count != expected_match_count:
                    raise HistoricalMatchConflictError(
                        f"year {year} has {count} archived matches, "
                        f"expected {expected_match_count}"
                    )
                if entry["status"] == "sealed":
                    if (entry["match_count"], entry["ledger_sha256"]) != (
                        count, ledger
                    ):
                        raise HistoricalMatchConflictError(
                            "sealed year ledger was modified"
                        )
                    return {"year": year, "match_count": count,
                            "ledger_sha256": ledger, "already_sealed": True}
                conn.execute(
                    """UPDATE career_years SET
                       status='sealed', match_count=?, ledger_sha256=?
                       WHERE year=? AND status='active'""",
                    (count, ledger, year),
                )
                return {"year": year, "match_count": count,
                        "ledger_sha256": ledger, "already_sealed": False}

    def register_next_year(
        self, *, year: int, rng_seed: int,
        resolver_contract: str, plan_fingerprint: str,
    ) -> dict:
        """Register only an adjacent year after the preceding one is sealed.

        This is an archive-contract operation, not a 2027 competition or
        roster generator and not a full gameplay year rollover.
        """
        metadata = self._year_metadata(
            year, rng_seed, resolver_contract, plan_fingerprint
        )
        if not self.db_path.is_file():
            raise HistoricalMatchConflictError("archive does not exist")
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                known = conn.execute(
                    "SELECT metadata_json, status FROM career_years WHERE year=?",
                    (year,),
                ).fetchone()
                if known is not None:
                    if known["metadata_json"] != metadata:
                        raise HistoricalMatchConflictError(
                            "existing career year identity differs"
                        )
                    return {"year": year, "registered": False}
                prev = conn.execute(
                    "SELECT year, status FROM career_years "
                    "ORDER BY year DESC LIMIT 1"
                ).fetchone()
                if (prev is None or prev["year"] != year - 1
                        or prev["status"] != "sealed"):
                    raise HistoricalMatchConflictError(
                        "adjacent previous year must be sealed"
                    )
                conn.execute(
                    "INSERT INTO career_years(year, metadata_json, status) "
                    "VALUES (?, ?, 'active')",
                    (year, metadata),
                )
                return {"year": year, "registered": True}

    def list_years(self) -> list[dict]:
        """Return registered career years, including sealed state."""
        if not self.db_path.is_file():
            return []
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            return [
                {"year": int(row["year"]), "status": row["status"],
                 "match_count": row["match_count"]}
                for row in conn.execute(
                    "SELECT year, status, match_count "
                    "FROM career_years ORDER BY year"
                )
            ]

    def sync(
        self,
        *,
        year: int,
        rng_seed: int,
        resolver_contract: str,
        plan_fingerprint: str,
        completed: Iterable[Mapping[str, object]],
    ) -> dict:
        identity = self._identity(
            year, rng_seed, resolver_contract, plan_fingerprint
        )
        year_metadata = self._year_metadata(
            year, rng_seed, resolver_contract, plan_fingerprint
        )
        # Validate all rows *before* writing, including duplicate keys
        # inside a supplied snapshot.
        normalized = []
        seen = set()
        for source in completed:
            payload = _history_payload(year, source)
            key = (
                payload["year"], payload["competition_id"], payload["match_id"]
            )
            if key in seen:
                raise ValueError(f"duplicate completed match: {key}")
            seen.add(key)
            raw = _canonical(payload)
            normalized.append((key, payload, raw, _digest(raw)))

        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                existing_identity = conn.execute(
                    "SELECT metadata_json FROM archive_identity WHERE id = 1"
                ).fetchone()
                if existing_identity is None:
                    conn.execute(
                        "INSERT INTO archive_identity(id, metadata_json) VALUES (1, ?)",
                        (identity,),
                    )
                is_initial_year = existing_identity is None or (
                    existing_identity[0] == identity
                )
                if existing_identity is not None and not is_initial_year:
                    # A new year's identity is allowed only after an explicit
                    # adjacent rollover registration in the same career.
                    known = conn.execute(
                        "SELECT metadata_json FROM career_years WHERE year=?",
                        (year,),
                    ).fetchone()
                    if known is None or known[0] != year_metadata:
                        raise HistoricalMatchConflictError(
                            "archive identity differs from the saved game"
                        )
                known_year = conn.execute(
                    "SELECT metadata_json, status FROM career_years "
                    "WHERE year=?", (year,),
                ).fetchone()
                if known_year is None:
                    if not is_initial_year:
                        raise HistoricalMatchConflictError(
                            "new career year requires explicit registration"
                        )
                    # Backfill Stage43C archives on first sync; never rewrite
                    # the original archive_identity metadata.
                    conn.execute(
                        "INSERT INTO career_years(year, metadata_json, status) "
                        "VALUES (?, ?, 'active')",
                        (year, year_metadata),
                    )
                    year_status = "active"
                else:
                    if known_year["metadata_json"] != year_metadata:
                        raise HistoricalMatchConflictError(
                            "career year plan/seed differs"
                        )
                    year_status = known_year["status"]
                added = 0
                same = 0
                for key, payload, raw, fingerprint in normalized:
                    old = conn.execute(
                        """SELECT record_sha256 FROM historical_matches
                           WHERE year=? AND competition_id=? AND match_id=?""",
                        key,
                    ).fetchone()
                    if old is not None:
                        if old[0] != fingerprint:
                            raise HistoricalMatchConflictError(
                                f"archived match changed: {key}"
                            )
                        same += 1
                        continue
                    if year_status == "sealed":
                        raise HistoricalMatchConflictError(
                            f"sealed year {year} cannot accept new matches"
                        )
                    conn.execute(
                        """INSERT INTO historical_matches (
                            year, competition_id, match_id, match_date,
                            date_source, team1_id, team2_id, team1_score,
                            team2_score, score_source, record_sha256, payload_json
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            *key, payload["match_date"], payload["date_source"],
                            payload["team1_id"], payload["team2_id"],
                            payload["team1_score"], payload["team2_score"],
                            payload["score_source"], fingerprint, raw,
                        ),
                    )
                    added += 1
        return {"inserted": added, "already_archived": same}

    def get_match(self, year: int, competition_id: str, match_id: str) -> dict | None:
        if not self.db_path.is_file():
            return None
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT payload_json FROM historical_matches
                   WHERE year=? AND competition_id=? AND match_id=?""",
                (year, competition_id, match_id),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def list_matches(
        self, year: int, *, school_id: str = "",
        limit: int = 200, offset: int = 0,
    ) -> list[dict]:
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("invalid pagination")
        if not self.db_path.is_file():
            return []
        filters = "year = ?"
        args: list[object] = [year]
        if school_id:
            filters += " AND (team1_id=? OR team2_id=?)"
            args.extend((school_id, school_id))
        args.extend((limit, offset))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"""SELECT payload_json FROM historical_matches
                    WHERE {filters}
                    ORDER BY match_date, competition_id, match_id
                    LIMIT ? OFFSET ?""",
                args,
            ).fetchall()
            return [json.loads(row[0]) for row in rows]
