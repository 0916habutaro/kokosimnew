"""Stage43G-29: immutable separate cache for sealed fictional-v2 player stats.

The v2 match, fictional calendar, annual rosters, and legacy match/stat
archives remain authoritative. Fast reads verify source seal/ledger metadata,
roster identities, every cached row hash and complete cache coverage.
verify_source=True also checks every original box score via Stage43G-28.
This is neither a migration nor real year-10000 tournament progression.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from .career_option_a_storage_profile import _read_only
from .career_roster_archive import CareerRosterArchive, _digest, _identity
from .career_v2_roster_attribution import CareerV2RosterAttribution

SOURCE = "sealed_fictional_v2_player_stats_cache_v1"
FILENAME = "fictional_v2_player_stat_cache.sqlite3"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_school_year_stat_cache (
  school_id TEXT NOT NULL,
  year INTEGER NOT NULL CHECK(year > 0),
  source_ledger_sha256 TEXT NOT NULL,
  source_calendar_sha256 TEXT NOT NULL,
  source_match_count INTEGER NOT NULL,
  roster_school_ids_json TEXT NOT NULL,
  roster_proof_sha256 TEXT NOT NULL,
  team_match_count INTEGER NOT NULL,
  player_count INTEGER NOT NULL,
  fact_sha256 TEXT NOT NULL,
  PRIMARY KEY (school_id,year)
);
CREATE TABLE IF NOT EXISTS v2_player_year_stat_cache (
  school_id TEXT NOT NULL,
  year INTEGER NOT NULL,
  player_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  PRIMARY KEY (school_id,year,player_id)
);
CREATE INDEX IF NOT EXISTS idx_v2_stat_player_year
  ON v2_player_year_stat_cache(player_id,year);
"""


class CareerV2StatsCacheConflict(ValueError):
    """v2 source proof, immutable cache contents or roster attribution differs."""


def _json(data: object) -> str:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _sha(raw: str) -> str:
    return sha256(raw.encode("utf-8")).hexdigest()


class CareerV2PlayerStatCache:
    """An opt-in v2-only append/verify cache, never the legacy cache file."""

    def __init__(self, attribution: CareerV2RosterAttribution,
                 cache_path: str | Path):
        self.view = attribution
        self.path = Path(cache_path)
        if self.path.name != FILENAME:
            raise ValueError("v2 stats must use the dedicated cache filename")
        source_paths = [
            attribution.matches.path, attribution.matches.calendar.path,
            attribution.rosters.db_path,
        ]
        if attribution.matches.legacy_path is not None:
            source_paths.append(attribution.matches.legacy_path)
        if self.path.resolve() in {p.resolve() for p in source_paths}:
            raise ValueError("v2 cache cannot replace a source archive")

    def _source(self, year: int) -> dict:
        if type(year) is not int or year < 1:
            raise ValueError("invalid game year")
        with closing(_read_only(self.view.matches.path)) as con:
            con.row_factory = sqlite3.Row
            rec = con.execute(
                "SELECT calendar_sha256,status,match_count,ledger_sha256 "
                "FROM v2_game_years WHERE year=?", (year,),
            ).fetchone()
        if (rec is None or rec["status"] != "sealed"
                or type(rec["match_count"]) is not int
                or rec["match_count"] < 0
                or type(rec["ledger_sha256"]) is not str
                or type(rec["calendar_sha256"]) is not str):
            raise CareerV2StatsCacheConflict(
                "only sealed fictional v2 source years can be cached"
            )
        return {
            "source_ledger_sha256": rec["ledger_sha256"],
            "source_calendar_sha256": rec["calendar_sha256"],
            "source_match_count": rec["match_count"],
        }

    def _roster_proof(self, year: int, schools: list[str]) -> str:
        if (type(schools) is not list or not schools
                or schools != sorted(set(schools))
                or any(type(s) is not str or not s for s in schools)):
            raise CareerV2StatsCacheConflict("invalid roster proof school list")
        proofs = []
        with closing(_read_only(self.view.rosters.db_path)) as con:
            con.row_factory = sqlite3.Row
            for school in schools:
                # _members verifies both the annual snapshot and every
                # permanent-player identity against its original JSON hash.
                self.view._members(con, year, school)
                snapshot = CareerRosterArchive._get(con, year, school)
                payload = [
                    (p.player_id, _digest(_identity(p)))
                    for p in sorted(snapshot.players, key=lambda x: x.player_id)
                ]
                proofs.append((school, _digest(_json(snapshot.to_dict())), payload))
        return _sha(_json(proofs))

    @staticmethod
    def _rows(rows: list[dict], year: int, school: str) -> list[tuple]:
        if type(rows) is not list:
            raise CareerV2StatsCacheConflict("invalid aggregated player rows")
        output = []
        for item in rows:
            if (not isinstance(item, dict)
                    or item.get("year") != year
                    or item.get("school_id") != school
                    or type(item.get("player_id")) is not str
                    or not item["player_id"]):
                raise CareerV2StatsCacheConflict("cached player identity differs")
            raw = _json(item)
            output.append((item["player_id"], raw, _sha(raw)))
        if [x[0] for x in output] != sorted(set(x[0] for x in output)):
            raise CareerV2StatsCacheConflict("unsorted or repeated player IDs")
        return output

    @staticmethod
    def _fingerprint(
        school: str, year: int, source: dict, schools_raw: str,
        roster_proof: str, team_games: int, rows: list[tuple],
    ) -> str:
        return _sha(_json({
            "source_kind": SOURCE, "school_id": school, "year": year,
            **source,
            "roster_school_ids_json": schools_raw,
            "roster_proof_sha256": roster_proof,
            "team_match_count": team_games,
            "player_count": len(rows),
            "rows": [(pid, checksum) for pid, _raw, checksum in rows],
        }))

    def _fact(self, year: int, school: str) -> tuple[tuple, list[tuple]]:
        # Revalidate entire sealed v2 source and actual on-year roster IDs.
        source_before = self._source(year)
        audited = self.view.school_year(year, school)
        source_after = self._source(year)
        if (source_before != source_after
                or audited["source_match_count"] != source_before["source_match_count"]
                or audited["source_calendar_sha256"] != source_before["source_calendar_sha256"]
                or audited["year_status"] != "sealed"):
            raise CareerV2StatsCacheConflict("source changed during v2 materialization")
        schools = audited["verified_school_ids"]
        if school not in schools:
            raise CareerV2StatsCacheConflict("requested school is not proven")
        schools_raw = _json(schools)
        roster_proof = self._roster_proof(year, schools)
        rows = self._rows(audited["rows"], year, school)
        games = audited["team_match_count"]
        digest = self._fingerprint(
            school, year, source_before, schools_raw, roster_proof, games, rows,
        )
        return ((
            school, year, source_before["source_ledger_sha256"],
            source_before["source_calendar_sha256"],
            source_before["source_match_count"], schools_raw,
            roster_proof, games, len(rows), digest,
        ), rows)

    def materialize(self, year: int, school_id: str) -> dict:
        if type(school_id) is not str or not school_id:
            raise ValueError("invalid school ID")
        header, rows = self._fact(year, school_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            with conn:
                previous = conn.execute(
                    "SELECT * FROM v2_school_year_stat_cache "
                    "WHERE school_id=? AND year=?", (school_id, year),
                ).fetchone()
                existing = conn.execute(
                    "SELECT player_id,payload_json,payload_sha256 "
                    "FROM v2_player_year_stat_cache "
                    "WHERE school_id=? AND year=? ORDER BY player_id",
                    (school_id, year),
                ).fetchall()
                if previous is not None:
                    if tuple(previous) != header or [tuple(r) for r in existing] != rows:
                        raise CareerV2StatsCacheConflict(
                            "immutable v2 player-stat cache differs from verified source"
                        )
                    inserted = False
                else:
                    if existing:
                        raise CareerV2StatsCacheConflict(
                            "orphan v2 player-year cache entries"
                        )
                    conn.execute(
                        "INSERT INTO v2_school_year_stat_cache VALUES(?,?,?,?,?,?,?,?,?,?)",
                        header,
                    )
                    conn.executemany(
                        "INSERT INTO v2_player_year_stat_cache VALUES(?,?,?,?,?)",
                        [(school_id, year, *r) for r in rows],
                    )
                    inserted = True
        return {
            "year": year, "school_id": school_id, "inserted": inserted,
            "player_count": len(rows), "team_match_count": header[7],
            "source_year_sealed": True, "fact_sha256": header[9],
            "separate_v2_cache": True, "legacy_cache_modified": False,
        }

    def read_year(self, year: int, school_id: str, *,
                  verify_source: bool = False) -> dict:
        """Fast immutable metadata+roster read; optional full-source audit."""
        if type(year) is not int or year < 1:
            raise ValueError("invalid game year")
        if type(school_id) is not str or not school_id:
            raise ValueError("invalid school ID")
        if type(verify_source) is not bool:
            raise ValueError("verify_source must be a bool")
        source = self._source(year)
        with closing(_read_only(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            header = conn.execute(
                "SELECT * FROM v2_school_year_stat_cache "
                "WHERE school_id=? AND year=?", (school_id, year),
            ).fetchone()
            if header is None:
                raise CareerV2StatsCacheConflict("no materialized v2 school-year")
            parts = {k: header[k] for k in source}
            if parts != source:
                raise CareerV2StatsCacheConflict("sealed v2 source metadata changed")
            try:
                schools = json.loads(header["roster_school_ids_json"])
            except (ValueError, TypeError) as exc:
                raise CareerV2StatsCacheConflict("cached roster list unreadable") from exc
            if school_id not in schools or _json(schools) != header["roster_school_ids_json"]:
                raise CareerV2StatsCacheConflict("cached roster school IDs changed")
            if self._roster_proof(year, schools) != header["roster_proof_sha256"]:
                raise CareerV2StatsCacheConflict("saved roster provenance changed")
            saved = conn.execute(
                "SELECT player_id,payload_json,payload_sha256 "
                "FROM v2_player_year_stat_cache "
                "WHERE school_id=? AND year=? ORDER BY player_id",
                (school_id, year),
            ).fetchall()
            rows = []
            for r in saved:
                if _sha(r["payload_json"]) != r["payload_sha256"]:
                    raise CareerV2StatsCacheConflict("v2 cached player row digest differs")
                try:
                    value = json.loads(r["payload_json"])
                except (ValueError, TypeError) as exc:
                    raise CareerV2StatsCacheConflict("cached stats unreadable") from exc
                if (not isinstance(value, dict)
                        or value.get("player_id") != r["player_id"]
                        or value.get("school_id") != school_id
                        or value.get("year") != year):
                    raise CareerV2StatsCacheConflict("v2 cached row identity changed")
                rows.append(value)
            checked = self._rows(rows, year, school_id)
            fact = self._fingerprint(
                school_id, year, source, header["roster_school_ids_json"],
                header["roster_proof_sha256"], header["team_match_count"], checked,
            )
            if len(rows) != header["player_count"] or fact != header["fact_sha256"]:
                raise CareerV2StatsCacheConflict("v2 cached coverage or fact changed")
        if verify_source:
            updated_header, actual = self._fact(year, school_id)
            if updated_header != tuple(header) or checked != actual:
                raise CareerV2StatsCacheConflict("v2 cache and original A rows differ")
        return {
            "source_kind": SOURCE, "year": year, "school_id": school_id,
            "rows": rows, "player_count": len(rows),
            "team_match_count": header["team_match_count"],
            "fact_sha256": fact,
            "source_ledger_sha256": source["source_ledger_sha256"],
            "roster_id_attribution_verified_at_build": True,
            "source_payloads_rechecked_on_read": verify_source,
            "legacy_stats_cache_modified": False,
            "merged_into_legacy_player_career": False,
            "real_tournament_runtime_connected": False,
        }
