"""Append-only, slot-scoped archive of completed live-season games.

Stores Option A historical facts without retaining per-plate-appearance events.
The live JSON save remains the source for replay and crash reconciliation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import zlib
from contextlib import closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
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
-- Multi-decade school history filters by school equality *before* the
-- 50/100-year range. Existing year-first indexes remain for yearly views.
CREATE INDEX IF NOT EXISTS idx_history_school1_year
    ON historical_matches(team1_id, year, competition_id, match_id);
CREATE INDEX IF NOT EXISTS idx_history_school2_year
    ON historical_matches(team2_id, year, competition_id, match_id);
-- 閉じた年度の大会の進行（見るだけ。トーナメント表・出場校一覧を出すため）
CREATE TABLE IF NOT EXISTS closed_seasons (
    year INTEGER PRIMARY KEY,
    snapshot BLOB NOT NULL,
    names_json TEXT NOT NULL
);
-- 大会別・複数年度閲覧の最小索引。正本はclosed_seasonsの確定ランタイム。
CREATE TABLE IF NOT EXISTS competition_best8 (
    competition_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (competition_id, year)
);
CREATE TABLE IF NOT EXISTS competition_entrants (
    competition_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (competition_id, year)
);
-- 大会の確定結果への学校別索引。人物・監督IDや大会全体のコピーは保存しない。
CREATE TABLE IF NOT EXISTS school_competition_records (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (year, competition_id, school_id)
);
CREATE INDEX IF NOT EXISTS idx_competition_records_school
    ON school_competition_records(school_id, year, competition_id);
-- 閉じた年度の名簿（選手の名前・出身・学年と年度末の能力・成長の状態。
-- game_core/roster_book.py の closed_record で詰めて圧縮したもの）
CREATE TABLE IF NOT EXISTS closed_rosters (
    year INTEGER NOT NULL,
    school_id TEXT NOT NULL,
    record BLOB NOT NULL,
    PRIMARY KEY (year, school_id)
);
-- 終わった大会の試合の記録をまとめて圧縮したもの（match_id → payload_json の
-- JSON を zlib）。まとめた試合の historical_matches.payload_json は空にする
CREATE TABLE IF NOT EXISTS packed_competitions (
    year INTEGER NOT NULL,
    competition_id TEXT NOT NULL,
    payloads BLOB NOT NULL,
    PRIMARY KEY (year, competition_id)
);
"""


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


# 個人成績などの表は、列名を1回だけ書き行を配列で持つ（容量を小さくする）。
# 読むときは expand_payload で元の「行ごとの dict」に戻す。中身は同じ。
_TABLE_FIELDS = ("inning_scores", "team_stats", "batter_stats", "pitcher_stats", "team_participation")


def _compact_table(rows):
    if not isinstance(rows, list) or not rows:
        return rows
    columns = list(rows[0])
    if any(not isinstance(row, dict) or list(row) != columns for row in rows):
        return rows
    return {
        "columns": columns,
        "rows": [[row[name] for name in columns] for row in rows],
    }


def _expand_table(value):
    if isinstance(value, dict) and set(value) == {"columns", "rows"}:
        if (not isinstance(value['columns'], list)
                or any(not isinstance(name, str) for name in value['columns'])
                or len(set(value['columns'])) != len(value['columns'])
                or not isinstance(value['rows'], list)
                or any(not isinstance(row, list) or len(row) != len(value['columns']) for row in value['rows'])):
            raise ValueError('invalid compact table')
        return [dict(zip(value["columns"], row)) for row in value["rows"]]
    return value


def _compact_participation(record):
    out = {**record, 'starting_lineup': _compact_table(record['starting_lineup'])}
    dh = record.get('starting_designated_hitter_id') is not None
    if dh:
        out['starting_defense'] = _compact_table(record['starting_defense'])
    changes = []
    for raw in record['changes']:
        change = {**raw, 'defensive_changes': _compact_table(raw['defensive_changes'])}
        # DH試合の相手側もorder付きの場合がある。DHなしの従来形は維持する。
        if dh or raw.get('moment', {}).get('order', 0):
            moment = raw['moment']
            change['moment'] = (['A', moment['inning'], moment['half'], moment['completed_plate_appearance_no']]
                if 'completed_plate_appearance_no' in moment else
                ['B', moment['inning'], moment['half'], moment['next_plate_appearance_no'], moment.get('order', 0)])
        if (dh or raw.get('moment', {}).get('order', 0)) and raw.get('dh_action') is not None:
            action = raw['dh_action']
            change['dh_action'] = [[[s['batting_order'], s['player_id']] for s in action['batting_changes']],
                                   action['player_id'], action['medical_exception'], action['umpire_approved']]
        changes.append(change)
    out['changes'] = _compact_table(changes)
    return out


def _expand_participation(record):
    out = {**record, 'starting_lineup': _expand_table(record['starting_lineup'])}
    if 'starting_defense' in record:
        out['starting_defense'] = _expand_table(record['starting_defense'])
    changes = []
    for raw in _expand_table(record['changes']):
        change = {**raw, 'defensive_changes': _expand_table(raw['defensive_changes'])}
        moment = raw['moment']
        if isinstance(moment, list):
            if len(moment) == 4 and moment[0] == 'A':
                change['moment'] = dict(inning=moment[1], half=moment[2], completed_plate_appearance_no=moment[3])
            elif len(moment) == 5 and moment[0] == 'B':
                change['moment'] = dict(inning=moment[1], half=moment[2], next_plate_appearance_no=moment[3])
                if moment[4]:
                    change['moment']['order'] = moment[4]
            else:
                raise ValueError('invalid compact change moment')
        action = raw.get('dh_action')
        if isinstance(action, list):
            if len(action) != 4 or any(len(s) != 2 for s in action[0]):
                raise ValueError('invalid compact DH action')
            change['dh_action'] = dict(batting_changes=[dict(batting_order=s[0], player_id=s[1]) for s in action[0]],
                                      player_id=action[1], medical_exception=action[2], umpire_approved=action[3])
        changes.append(change)
    out['changes'] = changes
    return out


def compact_payload(payload: Mapping[str, object]) -> dict:
    out = dict(payload)
    if out.get("team_participation"):
        from game_core.highlights import compact_pitching_highlights

        out["highlights"] = compact_pitching_highlights(out.get("highlights"), out["team_participation"], out.get('inning_scores'))
        # 9人の開始配置と変更差分も、既存の表形式で列名を一度だけ保存する。
        out['team_participation'] = [_compact_participation(r) for r in out['team_participation']]
    for name in _TABLE_FIELDS:
        if name in out:
            out[name] = _compact_table(out[name])
    return out


def expand_payload(payload: Mapping[str, object]) -> dict:
    """履歴に保存した試合の記録を、行ごとの dict の表に戻す。"""
    out = dict(payload)
    for name in _TABLE_FIELDS:
        if name in out:
            out[name] = _expand_table(out[name])
    if "team_participation" in out:
        from game_core.highlights import expand_pitching_highlights

        out['team_participation'] = [_expand_participation(r) for r in out['team_participation']]
        out["highlights"] = expand_pitching_highlights(out.get("highlights"), out["team_participation"], out.get('inning_scores'))
        _validate_participation_payload(out)
    return out


def _validate_participation_payload(payload: Mapping[str, object]) -> None:
    from game_core.match_state import TeamMatchParticipation, validate_match_participation

    if not isinstance(payload["team_participation"], list):
        raise ValueError("team_participation: expected list")
    records = tuple(TeamMatchParticipation.from_dict(row) for row in payload["team_participation"])
    dh = any(r.starting_designated_hitter_id is not None for r in records)
    innings = payload.get("inning_scores") or ()
    played = [row for row in innings if row["was_played"]]
    if not played:
        raise ValueError("lineup history requires played inning scores")
    for row in innings:
        count = row.get("plate_appearances")
        if (type(count) is not int or count < 0 or type(row["was_played"]) is not bool
                or row["was_played"] != (count > 0)):
            raise ValueError("invalid archived half inning plate appearances")
    team_ids = (payload["team1_id"], payload["team2_id"])
    batters = payload.get("batter_stats") or ()
    known = {sid: {row["player_id"] for row in batters if row["school_id"] == sid} for sid in team_ids}
    if dh:
        try:
            if any(_canonical(raw) != _canonical(record.to_dict()) for raw, record in zip(payload['team_participation'], records)):
                raise ValueError('noncanonical DH participation fields')
            _validate_dh_payload(payload, records, known)
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise ValueError('invalid DH history payload') from exc
        return
    validate_match_participation(
        records, team_ids=team_ids, reference_year=payload["year"],
        last_inning=played[-1]["inning"], ending_half=played[-1]["half"],
        total_plate_appearances=sum(row["plate_appearances"] for row in batters), known_ids=known,
        half_plate_appearances={(row["inning"], row["half"]): row["plate_appearances"] for row in innings},
    )


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compress_competition(payload: bytes) -> bytes:
    # 保存済み大会と同じ圧縮率・バイト列を維持する。
    return zlib.compress(payload, 9)


def _validate_dh_payload(payload, records, known):
    from game_core.match_contract import (
        BatterGameStats, PitcherGameStats, dh_history_fingerprint,
        TeamGameStats, validate_team_game_stats, validate_batter_game_stats, validate_pitcher_game_stats,
    )
    from game_core.match_state import validate_recorded_match_participation
    receipt = payload.get('dh_verification')
    if (not isinstance(receipt, dict) or set(receipt) != {'version', 'facts_sha256'}
            or type(receipt['version']) is not int or receipt['version'] != 1):
        raise ValueError('DH history requires pre-save event verification')
    if receipt['facts_sha256'] != dh_history_fingerprint(payload):
        raise ValueError('DH verified facts changed before or after saving')
    team_ids = (payload['team1_id'], payload['team2_id'])
    if len(set(team_ids)) != 2 or any(not isinstance(sid, str) or not sid for sid in team_ids):
        raise ValueError('invalid recorded team identities')
    innings = payload['inning_scores']
    if [(r['inning'], r['half']) for r in innings] != [
            (i, h) for i in range(1, innings[-1]['inning']+1) for h in ('top', 'bottom')]:
        raise ValueError('invalid recorded inning coverage')
    for row in innings:
        team = team_ids[0] if row['half'] == 'top' else team_ids[1]
        if row['batting_team_id'] != team or (not row['was_played'] and row['runs'] is not None):
            raise ValueError('invalid recorded inning team/score')
        if row['was_played'] and _score(row['runs'], 'recorded inning runs') is None:
            raise ValueError('played inning requires runs')
    unplayed = [i for i, r in enumerate(innings) if not r['was_played']]
    if unplayed and unplayed != [len(innings)-1]:
        raise ValueError('unplayed half must be the final bottom')
    batters, pitchers = payload['batter_stats'], payload['pitcher_stats']
    pa, bf = {}, {}
    for rows, counts, field, cls, validate in (
            (batters, pa, 'plate_appearances', BatterGameStats, validate_batter_game_stats),
            (pitchers, bf, 'batters_faced', PitcherGameStats, validate_pitcher_game_stats)):
        for raw in rows:
            key = (raw['school_id'], raw['player_id'])
            if key[0] not in team_ids or key in counts:
                raise ValueError('invalid/duplicate recorded player stats')
            stat = cls(**{k: v for k, v in raw.items() if k != 'singles'})
            validate(stat)
            if 'singles' in raw and raw['singles'] != stat.singles:
                raise ValueError('recorded singles differ from hit breakdown')
            counts[key] = raw[field]
            known[key[0]].add(key[1])
    # 開始配置・実守備・交代の参照も取り込み、役割別成績との一致は再生後に照合する。
    for record in records:
        ids = known[record.school_id]
        ids.update(s.player_id for s in record.starting_lineup)
        ids.update(a.player_id for a in record.starting_defense)
        ids.update(record.fielding_player_ids)
        for change in record.changes:
            ids.update(c.after_player_id for c in change.defensive_changes)
            if change.dh_action:
                ids.update(s.player_id for s in change.dh_action.batting_changes)
    validate_recorded_match_participation(
        records, team_ids=team_ids, reference_year=payload['year'], known_ids=known,
        half_plate_appearances={(r['inning'], r['half']): r['plate_appearances'] for r in innings},
        batter_appearances=pa, pitcher_appearances=bf)
    scores = (payload['team1_score'], payload['team2_score'])
    if (any(type(n) is not int or n < 0 for n in scores) or scores[0] == scores[1]
            or payload['winner_id'] != team_ids[scores[1] > scores[0]]
            or payload['loser_id'] != team_ids[scores[0] > scores[1]]):
        raise ValueError('recorded winner/score mismatch')
    teams = payload['team_stats']
    if len(teams) != 2 or {t['school_id'] for t in teams} != set(team_ids):
        raise ValueError('invalid recorded team stats')
    for team in teams:
        validate_team_game_stats(TeamGameStats(**team))
    for sid, opponent, score in ((team_ids[0], team_ids[1], scores[0]), (team_ids[1], team_ids[0], scores[1])):
        batting = [b for b in batters if b['school_id'] == sid]
        pitching = [p for p in pitchers if p['school_id'] == opponent]
        team = next(t for t in teams if t['school_id'] == sid)
        if (sum(r['runs'] for r in innings if r['batting_team_id'] == sid and r['was_played']) != score
                or team['runs'] != score or sum(b['runs'] for b in batting) != score
                or sum(p['runs_allowed'] for p in pitching) != score
                or sum(b['hits'] for b in batting) != team['hits']
                or sum(p['hits_allowed'] for p in pitching) != team['hits']):
            raise ValueError('recorded team/individual totals mismatch')


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
    highlights = None
    if has_a_detail:
        highlights = detail.get("highlights")
        if highlights is not None:
            from game_core.highlights import validate_highlights

            validate_highlights(highlights)
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
    payload = {
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
        # 試合経過の要点（得点が入った打席・投手交代。game_core/highlights.py）
        "highlights": highlights,
    }
    participation = detail.get("team_participation") if has_a_detail else None
    if participation is not None:
        if not isinstance(participation, list):
            raise ValueError("team_participation: expected list")
        payload["team_participation"] = participation
        if detail.get('dh_verification') is not None:
            payload['dh_verification'] = detail['dh_verification']
        _validate_participation_payload(payload)
    return payload


LOGGER = logging.getLogger(__name__)
# ほかの接続（年度を閉じるときの VACUUM など）がファイルを使っている間は、
# エラーにせずこの秒数まで待つ
BUSY_TIMEOUT_SECONDS = 60

# 最近開いた大会のまとめた試合の記録（(ファイル, 年度, 大会ID) → match_id → payload_json）
_PACKED_CACHE: dict[tuple[str, int, str], dict[str, str]] = {}
_PACKED_CACHE_SIZE = 8
_PACKED_LOCK = threading.Lock()


class HistoricalMatchArchive:
    """Persistent A-history tied to a save slot, not a replaceable season view."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        """Own the handle as well as the SQLite commit/rollback context."""
        conn = None
        try:
            with self._connect() as conn:
                yield conn
        finally:
            if conn is not None:
                conn.close()

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
        with self._connection() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                # executescript commits implicitly: reserve the writer AFTER
                # schema setup, BEFORE any state/ledger decision.
                conn.execute("BEGIN IMMEDIATE")
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
        """Register only the year after the latest registered year.

        年度の重なりで、前の年度を封印する前（3月）に翌年度の試合が始まる
        ので、前の年度は封印前でもよい。
        """
        metadata = self._year_metadata(
            year, rng_seed, resolver_contract, plan_fingerprint
        )
        if not self.db_path.is_file():
            raise HistoricalMatchConflictError("archive does not exist")
        with self._connection() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                conn.execute("BEGIN IMMEDIATE")
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
                if prev is None or prev["year"] != year - 1:
                    raise HistoricalMatchConflictError(
                        "adjacent previous year must be registered"
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
        with self._connection() as conn:
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
            raw = _canonical(compact_payload(payload))
            normalized.append((key, payload, raw, _digest(raw)))

        with self._connection() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                conn.execute("BEGIN IMMEDIATE")
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
                # 同じ書込トランザクション内で索引を一度だけ読む。各入力の正規化・
                # チェックサム照合・封印条件は省かず、新規行だけをまとめて登録する。
                existing = {
                    (row[0], row[1]): row[2] for row in conn.execute(
                        "SELECT competition_id, match_id, record_sha256 "
                        "FROM historical_matches WHERE year=?", (year,),
                    )
                } if normalized else {}
                pending = []
                same = 0
                for key, payload, raw, fingerprint in normalized:
                    match_key = key[1:]
                    if match_key in existing:
                        if existing[match_key] != fingerprint:
                            raise HistoricalMatchConflictError(
                                f"archived match changed: {key}"
                            )
                        same += 1
                        continue
                    if year_status == "sealed":
                        raise HistoricalMatchConflictError(
                            f"sealed year {year} cannot accept new matches"
                        )
                    pending.append((
                        *key, payload["match_date"], payload["date_source"],
                        payload["team1_id"], payload["team2_id"],
                        payload["team1_score"], payload["team2_score"],
                        payload["score_source"], fingerprint, raw,
                    ))
                conn.executemany(
                    """INSERT INTO historical_matches (
                        year, competition_id, match_id, match_date,
                        date_source, team1_id, team2_id, team1_score,
                        team2_score, score_source, record_sha256, payload_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    pending,
                )
        return {"inserted": len(pending), "already_archived": same}

    def get_match(self, year: int, competition_id: str, match_id: str) -> dict | None:
        if not self.db_path.is_file():
            return None
        with closing(sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            row = conn.execute(
                """SELECT payload_json, record_sha256 FROM historical_matches
                   WHERE year=? AND competition_id=? AND match_id=?""",
                (year, competition_id, match_id),
            ).fetchone()
            if row is None:
                return None
            return self._read_match_payload(conn, year, competition_id, match_id, row[0], row[1])

    def match_scores(self, year: int, keys) -> dict[tuple, dict]:
        """(大会ID, 試合ID) → 点と半イニングの記録だけ（試合の一覧に「7回コールド」を付ける）。

        一覧の行ごとに試合の記録を全部戻して検証すると遅いので、読み取りだけで
        点と ``inning_scores`` を取り出す。保存の形は変えない。ない試合は入れない。"""
        keys = list(keys)
        if not keys or not self.db_path.is_file():
            return {}
        out = {}
        with closing(sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            for competition_id, match_id in keys:
                row = conn.execute(
                    """SELECT payload_json, record_sha256 FROM historical_matches
                       WHERE year=? AND competition_id=? AND match_id=?""",
                    (year, competition_id, match_id),
                ).fetchone()
                if row is None:
                    continue
                raw = row[0] or self._packed(conn, year, competition_id).get(match_id)
                if not isinstance(raw, str) or _digest(raw) != row[1]:
                    continue
                payload = json.loads(raw)
                out[competition_id, match_id] = {
                    "team1_score": payload.get("team1_score"),
                    "team2_score": payload.get("team2_score"),
                    "inning_scores": _expand_table(payload.get("inning_scores")) or [],
                }
        return out

    def _read_match_payload(self, conn, year, competition_id, match_id, raw, digest):
        if not raw:
            raw = self._packed(conn, year, competition_id).get(match_id)
            if raw is None:
                # COMMIT直後、圧縮側が旧キャッシュを破棄する前の読込にも対応する。
                raw = self._packed(conn, year, competition_id, refresh=True).get(match_id)
        if not isinstance(raw, str) or _digest(raw) != digest:
            raise HistoricalMatchConflictError(f'archived match missing or changed: {competition_id}/{match_id}')
        payload = json.loads(raw)
        if (payload.get('year'), payload.get('competition_id'), payload.get('match_id')) != (year, competition_id, match_id):
            raise HistoricalMatchConflictError('archived match identity differs from index')
        return expand_payload(payload)

    def _packed(self, conn, year: int, competition_id: str, *, refresh: bool = False) -> dict[str, str]:
        """まとめて圧縮した大会の試合の記録（最近開いた大会はとっておく）。"""
        key = (str(self.db_path), year, competition_id)
        with _PACKED_LOCK:
            cached = None if refresh else _PACKED_CACHE.get(key)
        if cached is None:
            row = conn.execute(
                "SELECT payloads FROM packed_competitions WHERE year=? AND competition_id=?",
                (year, competition_id),
            ).fetchone()
            cached = json.loads(zlib.decompress(row[0])) if row else {}
            with _PACKED_LOCK:
                _PACKED_CACHE[key] = cached
                while len(_PACKED_CACHE) > _PACKED_CACHE_SIZE:
                    _PACKED_CACHE.pop(next(iter(_PACKED_CACHE)))
        return cached

    def vacuum(self) -> bool:
        """まとめて圧縮したあとの空きを詰めてファイルを小さくする（年度を閉じるとき）。

        VACUUM はファイルと同じくらいの空き容量を一時的に使う。空き容量が足りない・
        ほかの接続が長く使っているなどで失敗しても、ゲームは止めずにログに残す
        （空きは次の年度を閉じるときにまた詰める）。詰められたら True。
        """
        if not self.db_path.is_file():
            return False
        try:
            with closing(sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
                conn.execute("VACUUM")
        except sqlite3.Error as exc:
            LOGGER.warning(
                "試合履歴の空きを詰められませんでした（次の年度の切り替えでもう一度行います）: %s: %s",
                self.db_path, exc,
            )
            return False
        return True

    def packed_competitions(self, year: int) -> set[str]:
        if not self.db_path.is_file():
            return set()
        with closing(sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            conn.executescript(_SCHEMA)
            return {
                row[0] for row in conn.execute(
                    "SELECT competition_id FROM packed_competitions WHERE year=?", (year,),
                )
            }

    def pack_competition(self, year: int, competition_id: str) -> int:
        """終わった大会の試合の記録をまとめて圧縮する。まとめた試合の数を返す。"""
        return self.pack_competitions(year, (competition_id,))

    def pack_competitions(self, year: int, competition_ids: Iterable[str]) -> int:
        """同じA形式・圧縮設定で大会をまとめる。SQL操作は呼出スレッドだけで行う。"""
        competition_ids = tuple(dict.fromkeys(competition_ids))
        if not competition_ids:
            return 0
        packed_keys = []
        count = 0
        with self._connection() as conn:
            conn.executescript(_SCHEMA)
            with conn, ThreadPoolExecutor(max_workers=2) as pool:
                conn.execute("BEGIN IMMEDIATE")
                # 一度に保持する未圧縮データは2大会まで。順序・zlib level 9は維持する。
                for offset in range(0, len(competition_ids), 2):
                    prepared = []
                    for cid in competition_ids[offset:offset+2]:
                        rows = conn.execute(
                            """SELECT match_id, payload_json, record_sha256 FROM historical_matches
                               WHERE year=? AND competition_id=? AND payload_json != ''""",
                            (year, cid),
                        ).fetchall()
                        if not rows:
                            continue
                        payloads = dict(self._packed(conn, year, cid))
                        for match_id, raw, digest in rows:
                            if _digest(raw) != digest:
                                raise HistoricalMatchConflictError(f"archived match changed: {cid}/{match_id}")
                            payloads[match_id] = raw
                        prepared.append((cid, len(rows), _canonical(payloads).encode('utf-8')))
                    raw_payloads = [raw for _, _, raw in prepared]
                    encoded = (pool.map(_compress_competition, raw_payloads) if len(prepared) > 1
                               else map(_compress_competition, raw_payloads))
                    for (cid, size, _), blob in zip(prepared, encoded, strict=True):
                        conn.execute("INSERT OR REPLACE INTO packed_competitions VALUES (?, ?, ?)", (year, cid, blob))
                        conn.execute("UPDATE historical_matches SET payload_json='' WHERE year=? AND competition_id=?", (year, cid))
                        packed_keys.append((str(self.db_path), year, cid))
                        count += size
            with _PACKED_LOCK:
                for key in packed_keys:
                    _PACKED_CACHE.pop(key, None)
        return count

    def store_closed_season(self, year: int, snapshot: bytes, names: Mapping[str, str],
                            *, school_records: Iterable[Mapping] = (),
                            best8_records: Iterable[Mapping] = (),
                            entrant_records: Iterable[Mapping] = ()) -> None:
        """閉じた年度の大会の進行（``runtime_snapshot.dump_runtime_state``）と大会名。"""
        records = []
        for record in school_records:
            if (record.get('year') != year or not record.get('competition_id')
                    or not record.get('school_id')):
                raise ValueError('invalid school competition record identity')
            records.append((year, record['competition_id'], record['school_id'],
                            _canonical(dict(record))))
        best8 = []
        for record in best8_records:
            if record.get('school_year') != year or not record.get('competition_id'):
                raise ValueError('invalid best8 record identity')
            best8.append((record['competition_id'], year, _canonical(dict(record))))
        entrants = []
        for record in entrant_records:
            if record.get('school_year') != year or not record.get('competition_id'):
                raise ValueError('invalid entrant record identity')
            entrants.append((record['competition_id'], year, _canonical(dict(record))))
        with self._connection() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO closed_seasons VALUES (?, ?, ?)",
                    (year, snapshot, _canonical(dict(names))),
                )
                conn.execute('DELETE FROM competition_entrants WHERE year=?', (year,))
                conn.executemany('INSERT INTO competition_entrants VALUES (?, ?, ?)', entrants)
                conn.execute('DELETE FROM competition_best8 WHERE year=?', (year,))
                conn.executemany('INSERT INTO competition_best8 VALUES (?, ?, ?)', best8)
                conn.execute('DELETE FROM school_competition_records WHERE year=?', (year,))
                conn.executemany('INSERT INTO school_competition_records VALUES (?, ?, ?, ?)', records)

    def best8_bounds(self) -> tuple[int, int] | None:
        """閉じた年度の範囲だけを読み取り専用で取得する。DBを作成しない。"""
        if not self.db_path.is_file():
            return None
        with closing(sqlite3.connect(self.db_path.resolve().as_uri() + '?mode=ro',
                                    uri=True, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='closed_seasons'").fetchone():
                return None
            first = conn.execute('SELECT year FROM closed_seasons ORDER BY year LIMIT 1').fetchone()
            last = conn.execute('SELECT year FROM closed_seasons ORDER BY year DESC LIMIT 1').fetchone()
        return (first[0], last[0]) if first else None

    def competition_entrants(self, cid: str, first: int, last: int) -> list[dict]:
        return self._competition_history('competition_entrants', cid, first, last)

    def competition_best8(self, cid: str, first: int, last: int) -> list[dict]:
        return self._competition_history('competition_best8', cid, first, last)

    def _competition_history(self, table: str, cid: str, first: int, last: int) -> list[dict]:
        """大会ID・年度の索引で限定取得する。試合・名簿・年度スナップショットは読まない。"""
        if not self.db_path.is_file():
            return []
        with closing(sqlite3.connect(self.db_path.resolve().as_uri() + '?mode=ro',
                                    uri=True, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                return []
            rows = conn.execute(f'SELECT record_json FROM {table} '
                                'WHERE competition_id=? AND year BETWEEN ? AND ? ORDER BY year DESC',
                                (cid, first, last)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def school_competition_records(self, school_id: str) -> list[dict]:
        """年度スナップショットを展開せず、学校に関係する大会結果だけを読む。"""
        if not self.db_path.is_file():
            return []
        with closing(sqlite3.connect(self.db_path.resolve().as_uri() + '?mode=ro',
                                    uri=True, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='school_competition_records'").fetchone() is None:
                return []
            rows = conn.execute('SELECT record_json FROM school_competition_records '
                                'WHERE school_id=? ORDER BY year, competition_id',
                                (school_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def closed_season(self, year: int) -> tuple[bytes, dict[str, str]] | None:
        if not self.db_path.is_file():
            return None
        with closing(sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            conn.executescript(_SCHEMA)
            row = conn.execute(
                "SELECT snapshot, names_json FROM closed_seasons WHERE year = ?",
                (year,),
            ).fetchone()
        return (bytes(row[0]), json.loads(row[1])) if row else None

    def store_closed_rosters(self, year: int, rosters: Mapping[str, bytes]) -> None:
        """閉じた年度の名簿（学校ID → ``RosterBook.closed_record``）。"""
        with self._connection() as conn:
            conn.executescript(_SCHEMA)
            with conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO closed_rosters VALUES (?, ?, ?)",
                    [
                        (year, school_id, record)
                        for school_id, record in sorted(rosters.items())
                    ],
                )

    def closed_roster(self, year: int, school_id: str) -> bytes | None:
        if not self.db_path.is_file():
            return None
        with closing(sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            conn.executescript(_SCHEMA)
            row = conn.execute(
                "SELECT record FROM closed_rosters WHERE year = ? AND school_id = ?",
                (year, school_id),
            ).fetchone()
        return bytes(row[0]) if row else None

    def school_match_facts(self, school_id: str, first: str, last: str) -> list[dict]:
        """学校索引から日付と実試合判定に必要な事実だけを読む。履歴DBは変更しない。"""
        if not self.db_path.is_file():
            return []
        with closing(sqlite3.connect(self.db_path.resolve().as_uri() + '?mode=ro',
                                    uri=True, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            rows = conn.execute(
                """SELECT year, competition_id, match_id, match_date, date_source,
                          team1_id, team2_id, team1_score, team2_score, score_source
                   FROM historical_matches
                   WHERE (team1_id = ? OR team2_id = ?) AND match_date >= ? AND match_date <= ?
                   ORDER BY match_date, year, competition_id, match_id""",
                (school_id, school_id, first, last),
            ).fetchall()
        keys = ('year', 'competition_id', 'match_id', 'match_date', 'date_source',
                'team1_id', 'team2_id', 'team1_score', 'team2_score', 'score_source')
        return [dict(zip(keys, row)) for row in rows]

    def match_index(self, year: int) -> list[dict]:
        """その年度の全試合の要約（成績表用。個人成績などは読まない）。"""
        if not self.db_path.is_file():
            return []
        with closing(sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            rows = conn.execute(
                """SELECT competition_id, match_id, match_date, team1_id,
                          team2_id, team1_score, team2_score
                   FROM historical_matches WHERE year = ?
                   ORDER BY match_date, competition_id, match_id""",
                (year,),
            ).fetchall()
        return [
            {
                "competition_id": cid, "match_id": mid, "match_date": day,
                "team1_id": team1, "team2_id": team2,
                "team1_score": score1, "team2_score": score2,
            }
            for cid, mid, day, team1, team2, score1, score2 in rows
        ]

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
        with closing(sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
            rows = conn.execute(
                f"""SELECT payload_json, competition_id, match_id, record_sha256 FROM historical_matches
                    WHERE {filters}
                    ORDER BY match_date, competition_id, match_id
                    LIMIT ? OFFSET ?""",
                args,
            ).fetchall()
            return [
                self._read_match_payload(conn, year, cid, mid, raw, digest)
                for raw, cid, mid, digest in rows
            ]
