"""Stage 43F-4: verified, immutable competition outcomes from archived games.

A competition result can drive future-year qualification ONLY after the
source year's match archive is sealed and every played MAIN match agrees
with the actual saved match result. This does not award committee selections,
invent unplayed matches, or change the game runtime.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .historical_match_archive import HistoricalMatchArchive
from .models import CompetitionRun


class CareerOutcomeConflictError(ValueError):
    """Source games, ranking, or previously saved outcome disagree."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_competition_outcomes (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    PRIMARY KEY (year, competition_id)
);
CREATE INDEX IF NOT EXISTS idx_outcomes_year
    ON historical_competition_outcomes(year, competition_id);
"""


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_school_list(values: object, label: str) -> list[str]:
    if (not isinstance(values, list)
            or not values
            or any(not isinstance(v, str) or not v for v in values)
            or len(values) != len(set(values))):
        raise CareerOutcomeConflictError(f"{label}: invalid school IDs")
    return values


def _main_result(run: CompetitionRun) -> tuple[dict, list]:
    if (not isinstance(run.year, int) or isinstance(run.year, bool)
            or run.year < 2026):
        raise CareerOutcomeConflictError("invalid competition result year")
    if not isinstance(run.competition_id, str) or not run.competition_id:
        raise CareerOutcomeConflictError("missing competition ID")
    if run.outcome is None:
        raise CareerOutcomeConflictError("competition is not completed")
    main = [s for s in run.stage_executions if s.stage_code == "MAIN"]
    if len(main) != 1:
        raise CareerOutcomeConflictError("exactly one completed MAIN is required")
    stage = main[0]
    entrants = _require_school_list(
        list(run.main_entrant_school_ids), "MAIN entrants",
    )
    if len(entrants) < 2 or set(entrants) != set(stage.entrant_school_ids):
        raise CareerOutcomeConflictError("MAIN entrant list mismatch")
    if not set(entrants).issubset(set(run.entrant_school_ids)):
        raise CareerOutcomeConflictError("MAIN school outside competition entrants")
    outcome = run.outcome
    ranking = _require_school_list(
        list(outcome.final_ranking_school_ids), "final ranking",
    )
    if len(ranking) != len(entrants) or set(ranking) != set(entrants):
        raise CareerOutcomeConflictError("ranking does not cover MAIN entrants")
    if (ranking[0] != outcome.champion_school_id
            or ranking[1] != outcome.runner_up_school_id):
        raise CareerOutcomeConflictError("champion/runner-up disagree with ranking")
    if (set(outcome.semifinalist_school_ids) -
            set(entrants)) or (set(outcome.quarterfinalist_school_ids) -
                               set(entrants)):
        raise CareerOutcomeConflictError("invalid semifinal or quarterfinal school")

    matches = [m for m in stage.matches if not m.is_bye]
    if (len(matches) != len(entrants) - 1
            or len(matches) != outcome.match_count):
        raise CareerOutcomeConflictError("MAIN match count inconsistent")
    keys = [m.match_id for m in matches]
    if len(keys) != len(set(keys)):
        raise CareerOutcomeConflictError("duplicate MAIN match IDs")
    for m in matches:
        if (m.competition_id != run.competition_id
                or m.stage_id != stage.stage_id
                or m.stage_code != "MAIN"
                or not m.team1 or not m.team2 or m.team1 == m.team2
                or set((m.team1, m.team2)) - set(entrants)
                or (m.winner, m.loser) not in (
                    (m.team1, m.team2), (m.team2, m.team1)
                )):
            raise CareerOutcomeConflictError(
                f"invalid completed MAIN match: {m.match_id}"
            )
    finals = [m for m in matches if m.round_no == max(
        x.round_no for x in matches
    )]
    if len(finals) != 1 or finals[0].winner != outcome.champion_school_id:
        raise CareerOutcomeConflictError("MAIN final does not select champion")
    return {
        "year": run.year,
        "competition_id": run.competition_id,
        "source": "game_result",
        "status": "completed",
        "ranked_school_ids": list(ranking),
        "champion_school_id": outcome.champion_school_id,
        "runner_up_school_id": outcome.runner_up_school_id,
        "main_entrant_school_ids": list(entrants),
        "main_match_count": len(matches),
    }, matches


class CareerCompetitionOutcomes:
    """Stores completed competition ranking in the same sealed A-history DB."""

    def __init__(self, match_archive: HistoricalMatchArchive | str | Path):
        self.archive = (
            match_archive if isinstance(match_archive, HistoricalMatchArchive)
            else HistoricalMatchArchive(match_archive)
        )

    @staticmethod
    def _check_seal(conn: sqlite3.Connection, year: int) -> str:
        row = conn.execute(
            "SELECT status, match_count, ledger_sha256 "
            "FROM career_years WHERE year=?", (year,),
        ).fetchone()
        if row is None or row["status"] != "sealed":
            raise CareerOutcomeConflictError(
                "year must be sealed before exporting competition qualification"
            )
        actual_count, actual_sha = HistoricalMatchArchive._ledger(conn, year)
        if (row["match_count"], row["ledger_sha256"]) != (
            actual_count, actual_sha
        ):
            raise CareerOutcomeConflictError("sealed year ledger mismatch")
        return actual_sha

    @staticmethod
    def _check_source_matches(conn, year: int, comp_id: str, matches) -> list:
        indexed = []
        for match in sorted(matches, key=lambda m: m.match_id):
            row = conn.execute(
                "SELECT payload_json, record_sha256 "
                "FROM historical_matches "
                "WHERE year=? AND competition_id=? AND match_id=?",
                (year, comp_id, match.match_id),
            ).fetchone()
            if row is None or _sha(row["payload_json"]) != row["record_sha256"]:
                raise CareerOutcomeConflictError(
                    f"missing or modified archived MAIN match: {match.match_id}"
                )
            payload = json.loads(row["payload_json"])
            if (payload.get("year") != year
                    or payload.get("competition_id") != comp_id
                    or payload.get("match_id") != match.match_id
                    or payload.get("stage_code") != "MAIN"
                    or {payload.get("team1_id"), payload.get("team2_id")}
                    != {match.team1, match.team2}
                    or payload.get("winner_id") != match.winner
                    or payload.get("loser_id") != match.loser):
                raise CareerOutcomeConflictError(
                    f"archived result disagrees with MAIN match: {match.match_id}"
                )
            indexed.append([match.match_id, row["record_sha256"]])
        return indexed

    def record_completed(self, run: CompetitionRun) -> dict:
        """Idempotently record a competition only when sealed game rows prove it."""
        result, matches = _main_result(run)
        if not self.archive.db_path.is_file():
            raise CareerOutcomeConflictError("sealed match archive does not exist")
        with self.archive._connect() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                year = result["year"]
                digest = self._check_seal(conn, year)
                indexed = self._check_source_matches(
                    conn, year, result["competition_id"], matches,
                )
                # A bound match manifest cannot be swapped for another game.
                result["source_match_sha256"] = _sha(_canonical(indexed))
                result["source_year_ledger_sha256"] = digest
                raw = _canonical(result)
                fingerprint = _sha(raw)
                existing = conn.execute(
                    "SELECT record_sha256, payload_json "
                    "FROM historical_competition_outcomes "
                    "WHERE year=? AND competition_id=?",
                    (year, result["competition_id"]),
                ).fetchone()
                if existing is not None:
                    if (existing["record_sha256"] != fingerprint
                            or existing["payload_json"] != raw):
                        raise CareerOutcomeConflictError(
                            "previously recorded competition outcome changed"
                        )
                    return {"year": year, "competition_id": result["competition_id"],
                            "inserted": False}
                conn.execute(
                    "INSERT INTO historical_competition_outcomes "
                    "(year, competition_id, payload_json, record_sha256) "
                    "VALUES (?, ?, ?, ?)",
                    (year, result["competition_id"], raw, fingerprint),
                )
                return {"year": year, "competition_id": result["competition_id"],
                        "inserted": True}

    def previous_results(self, year: int) -> dict[str, dict]:
        """Read *sealed* and digest-verified results for future-year rules.

        Never infer rankings from only match scores; the completed tournament
        outcome is the ranking authority, bound to every archived MAIN match.
        """
        if not self.archive.db_path.is_file():
            return {}
        with self.archive._connect() as conn:
            conn.executescript(_SCHEMA)
            digest = self._check_seal(conn, year)
            output: dict[str, dict] = {}
            for row in conn.execute(
                "SELECT competition_id, payload_json, record_sha256 "
                "FROM historical_competition_outcomes "
                "WHERE year=? ORDER BY competition_id", (year,),
            ):
                if _sha(row["payload_json"]) != row["record_sha256"]:
                    raise CareerOutcomeConflictError(
                        "outcome fingerprint mismatch"
                    )
                data = json.loads(row["payload_json"])
                if (data.get("year") != year
                        or data.get("competition_id") != row["competition_id"]
                        or data.get("status") != "completed"
                        or data.get("source") != "game_result"
                        or data.get("source_year_ledger_sha256") != digest):
                    raise CareerOutcomeConflictError(
                        "outcome no longer belongs to sealed game year"
                    )
                output[row["competition_id"]] = {
                    "year": year,
                    "status": "completed",
                    "source": "game_result",
                    "ranked_school_ids": list(data["ranked_school_ids"]),
                }
            return output


def build_future_blueprint_from_archive(
    data_root: str | Path, *,
    year: int, base_seed: int,
    match_archive: HistoricalMatchArchive | str | Path,
) -> dict:
    """Resolve the known previous-autumn rules using sealed career history."""
    from .future_season_blueprint import build_future_season_blueprint

    results = CareerCompetitionOutcomes(match_archive).previous_results(year - 1)
    future = build_future_season_blueprint(
        data_root, year=year, base_seed=base_seed,
        previous_results=results,
    )
    future["previous_results_source"] = "sealed_career_game_archive"
    future["previous_results_year"] = year - 1
    future["previous_results_count"] = len(results)
    # Even resolved access rules cannot start a live full season by themselves.
    future["live_runtime_ready"] = False
    return future
