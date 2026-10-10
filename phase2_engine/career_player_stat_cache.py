"""Stage43G-15: materialized, append-only sealed-year player stats read model.

Correctness contract:
 * A-history and career_rosters remain the sole authoritative data.
 * Only genuinely sealed source years can be cached.
 * Rows are immutable and repeat builds are idempotent.
 * Fast reads verify sealed ledger METADATA, cached row digests and coverage,
   not every original payload. Call verify_source=True to re-check every raw
   box-score SHA and roster before reading (slower, audit-grade).
 * Active-year player stats continue to use Stage43G-14's live read model.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3

from .career_player_records import (
    BATTER, PITCHER, RANKABLE, CareerPlayerRecordView,
)
from .historical_match_archive import HistoricalMatchArchive

_SCHEMA = """
CREATE TABLE IF NOT EXISTS school_year_stat_cache (
    school_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    source_ledger_sha256 TEXT NOT NULL,
    source_match_count INTEGER NOT NULL,
    school_missing_box_score_games INTEGER NOT NULL,
    player_count INTEGER NOT NULL,
    fact_sha256 TEXT NOT NULL,
    PRIMARY KEY (school_id, year)
);
CREATE TABLE IF NOT EXISTS player_year_stat_cache (
    school_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    PRIMARY KEY (school_id, year, player_id)
);
CREATE INDEX IF NOT EXISTS idx_cached_player_year
    ON player_year_stat_cache(player_id, year);
CREATE INDEX IF NOT EXISTS idx_cached_school_year
    ON player_year_stat_cache(school_id, year, player_id);
"""


class CareerStatsCacheConflict(ValueError):
    """Sealed-year provenance, rows or unverified cache coverage differs."""


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CareerPlayerStatCache:
    def __init__(self, view: CareerPlayerRecordView,
                 cache_path: str | Path):
        self.view = view
        self.path = Path(cache_path)
        if self.path.resolve() in (
            self.view.matches.db_path.resolve(),
            self.view.rosters.db_path.resolve(),
        ):
            raise ValueError("cache database cannot replace authoritative archives")

    def _source(self, year: int) -> dict:
        if not self.view.matches.db_path.is_file():
            raise CareerStatsCacheConflict("historical archive missing")
        with sqlite3.connect(self.view.matches.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rec = conn.execute(
                "SELECT year, status, match_count, ledger_sha256 "
                "FROM career_years WHERE year=?", (year,),
            ).fetchone()
        if (rec is None or rec["status"] != "sealed"
                or not isinstance(rec["match_count"], int)
                or not isinstance(rec["ledger_sha256"], str)):
            raise CareerStatsCacheConflict(
                "only confirmed sealed source years may be materialized"
            )
        return {
            "year": year, "ledger": rec["ledger_sha256"],
            "match_count": rec["match_count"],
        }

    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    @staticmethod
    def _annual_rows(view: CareerPlayerRecordView,
                     school_id: str, year: int) -> tuple[list[tuple], int]:
        records = view._aggregate(school_id, year, year)
        missing = view._missing(school_id, year, year)
        annual = []
        for (pid, y), metrics in sorted(records.items()):
            if y != year:
                raise CareerStatsCacheConflict("player year mismatched")
            raw = _json(metrics)
            annual.append((pid, raw, _sha(raw)))
        return annual, missing

    @staticmethod
    def _fingerprint(source: dict, school: str,
                     annual: list[tuple], missing: int) -> str:
        return _sha(_json({
            "source_ledger_sha256": source["ledger"],
            "source_match_count": source["match_count"],
            "school_id": school, "year": source["year"],
            "missing_box_score_games": missing,
            "rows": [(pid, sha) for pid, _raw, sha in annual],
        }))

    def materialize(self, school_id: str, *, year: int) -> dict:
        if not isinstance(school_id, str) or not school_id:
            raise ValueError("invalid school ID")
        if type(year) is not int or year < 1:
            raise ValueError("invalid game year")
        source = self._source(year)
        annual, missing = self._annual_rows(self.view, school_id, year)
        # First read fully verifies the school game payloads; the sealed
        # annual ledger must *also* still match all source match digests.
        with sqlite3.connect(self.view.matches.db_path) as src:
            total, ledger = HistoricalMatchArchive._ledger(src, year)
        if (total != source["match_count"] or ledger != source["ledger"]):
            raise CareerStatsCacheConflict("sealed year source ledger changed")
        proof = self._fingerprint(source, school_id, annual, missing)
        with self._connection() as conn:
            with conn:
                prior = conn.execute(
                    "SELECT * FROM school_year_stat_cache "
                    "WHERE school_id=? AND year=?",
                    (school_id, year),
                ).fetchone()
                target = (
                    school_id, year, source["ledger"], source["match_count"],
                    missing, len(annual), proof,
                )
                if prior is not None:
                    stored = tuple(prior)
                    existing = conn.execute(
                        "SELECT player_id, payload_json, payload_sha256 "
                        "FROM player_year_stat_cache "
                        "WHERE school_id=? AND year=? ORDER BY player_id",
                        (school_id, year),
                    ).fetchall()
                    if stored != target or [tuple(r) for r in existing] != annual:
                        raise CareerStatsCacheConflict(
                            "immutable player-year cache differs from source"
                        )
                    inserted = False
                else:
                    conn.execute(
                        "INSERT INTO school_year_stat_cache VALUES(?,?,?,?,?,?,?)",
                        target,
                    )
                    conn.executemany(
                        "INSERT INTO player_year_stat_cache VALUES(?,?,?,?,?)",
                        [(school_id, year, *row) for row in annual],
                    )
                    inserted = True
        return {
            "school_id": school_id, "year": year, "inserted": inserted,
            "player_count": len(annual),
            "missing_box_score_games": missing,
            "source_year_sealed": True,
            "source_year_ledger_sha256": source["ledger"],
            "fact_sha256": proof,
        }

    def _coverage(self, conn: sqlite3.Connection, school: str,
                  start: int, end: int, *, verify_source: bool) -> list[dict]:
        self.view._years(start, end)
        if not isinstance(school, str) or not school:
            raise ValueError("invalid school ID")
        cache_rows = {
            r["year"]: r for r in conn.execute(
                "SELECT * FROM school_year_stat_cache "
                "WHERE school_id=? AND year BETWEEN ? AND ? ORDER BY year",
                (school, start, end),
            )
        }
        with sqlite3.connect(self.view.matches.db_path) as src:
            src.row_factory = sqlite3.Row
            source_rows = {
                r["year"]: r for r in src.execute(
                    "SELECT year,status,match_count,ledger_sha256 "
                    "FROM career_years WHERE year BETWEEN ? AND ?",
                    (start, end),
                )
            }
        years = list(range(start, end + 1))
        for year in years:
            cache, source = cache_rows.get(year), source_rows.get(year)
            if (cache is None or source is None or source["status"] != "sealed"
                    or cache["source_ledger_sha256"] != source["ledger_sha256"]
                    or cache["source_match_count"] != source["match_count"]):
                raise CareerStatsCacheConflict(
                    f"sealed school-year cache unavailable or stale: {year}"
                )
            if verify_source:
                self.materialize(school, year=year)
        return [dict(cache_rows[y]) for y in years]

    @staticmethod
    def _verified_record(row: sqlite3.Row) -> tuple[str, int, dict]:
        raw = row["payload_json"]
        if _sha(raw) != row["payload_sha256"]:
            raise CareerStatsCacheConflict("player-year cache row digest differs")
        try:
            detail = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise CareerStatsCacheConflict("cached player-year unreadable") from exc
        if (not isinstance(detail, dict)
                or not isinstance(detail.get("batting"), dict)
                or not isinstance(detail.get("pitching"), dict)
                or type(detail["batting"].get("games")) is not int
                or type(detail["pitching"].get("games")) is not int):
            raise CareerStatsCacheConflict("invalid cached player-year data")
        for kind, fields in (("batting", BATTER), ("pitching", PITCHER)):
            for key in fields:
                if type(detail[kind].get(key)) is not int or detail[kind][key] < 0:
                    raise CareerStatsCacheConflict("invalid cached player stat")
        return row["player_id"], row["year"], detail

    @staticmethod
    def _rollup(rows: list[dict]) -> dict:
        total = CareerPlayerRecordView._blank()
        for item in rows:
            for kind, fields in (("batting", BATTER), ("pitching", PITCHER)):
                total[kind]["games"] += item[kind]["games"]
                for field in fields:
                    total[kind][field] += item[kind][field]
        return CareerPlayerRecordView._metrics(total)

    def player_seasons(self, player_id: str, *, start_year: int,
                       end_year: int, verify_source: bool = False) -> dict:
        if not isinstance(player_id, str) or not player_id:
            raise ValueError("invalid player ID")
        self.view._years(start_year, end_year)
        career = self.view.rosters.player_history(player_id)
        if not career:
            return {
                "player_id": player_id, "seasons": [],
                "totals": self._rollup([]),
                "source_payloads_rechecked_on_read": False,
            }
        school = career[0]["school_id"]
        with self._connection() as conn:
            facts = self._coverage(
                conn, school, start_year, end_year,
                verify_source=verify_source,
            )
            rows = conn.execute(
                "SELECT player_id,year,payload_json,payload_sha256 "
                "FROM player_year_stat_cache "
                "WHERE player_id=? AND school_id=? AND year BETWEEN ? AND ? "
                "ORDER BY year",
                (player_id, school, start_year, end_year),
            ).fetchall()
            parsed = []
            for row in rows:
                pid, year, record = self._verified_record(row)
                if pid != player_id:
                    raise CareerStatsCacheConflict("cached player ID mismatch")
                parsed.append({"year": year, **CareerPlayerRecordView._metrics(record)})
        return {
            "player_id": player_id, "school_id": school,
            "seasons": parsed,
            "totals": self._rollup(parsed),
            "games_without_box_scores": sum(
                r["school_missing_box_score_games"] for r in facts
            ),
            "source_years_sealed": True,
            "source_payloads_rechecked_on_read": verify_source,
            "cache_is_disposable": True,
        }

    def school_leaders(self, school_id: str, *, start_year: int,
                       end_year: int, category: str,
                       limit: int = 20, verify_source: bool = False) -> dict:
        if (category not in RANKABLE or type(limit) is not int
                or not 1 <= limit <= 100):
            raise ValueError("invalid school record metric or limit")
        kind, metric = RANKABLE[category]
        with self._connection() as conn:
            facts = self._coverage(
                conn, school_id, start_year, end_year,
                verify_source=verify_source,
            )
            rows = conn.execute(
                "SELECT player_id,year,payload_json,payload_sha256 "
                "FROM player_year_stat_cache "
                "WHERE school_id=? AND year BETWEEN ? AND ? "
                "ORDER BY year,player_id",
                (school_id, start_year, end_year),
            )
            totals = defaultdict(lambda: {"games": 0, "value": 0})
            for row in rows:
                pid, _year, record = self._verified_record(row)
                target = totals[pid]
                target["games"] += record[kind]["games"]
                target["value"] += record[kind][metric]
        ranked = sorted(
            ({"player_id": pid, "stat_value": value["value"]}
             for pid, value in totals.items() if value["games"]),
            key=lambda r: (-r["stat_value"], r["player_id"]),
        )
        return {
            "school_id": school_id, "start_year": start_year,
            "end_year": end_year, "category": category,
            "rows": ranked[:limit], "candidate_count": len(ranked),
            "only_archived_option_a_stats": True,
            "missing_box_score_games": sum(
                r["school_missing_box_score_games"] for r in facts
            ),
            "source_years_sealed": True,
            "source_payloads_rechecked_on_read": verify_source,
            "cache_is_disposable": True,
        }
