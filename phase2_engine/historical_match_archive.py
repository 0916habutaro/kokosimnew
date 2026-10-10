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
                elif existing_identity[0] != identity:
                    raise HistoricalMatchConflictError(
                        "archive identity differs from the saved game"
                    )
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
