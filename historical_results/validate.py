"""実戦績CSV v1の読み取り専用検証。ゲーム用SQLiteには一切アクセスしない。"""
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = {
    "sources": ("source_id", "publisher", "document_title", "url", "retrieved_at", "verification_status"),
    "tournaments": ("tournament_id", "season_year", "season", "competition_name", "level", "prefecture_code", "competition_id", "completion_status", "source_id"),
    "teams": ("team_id", "tournament_id", "display_name", "team_type"),
    "team_members": ("team_id", "school_id", "observed_name", "mapping_status", "source_id"),
    "matches": ("match_id", "tournament_id", "game_date", "round_label", "home_team_id", "away_team_id", "home_score", "away_score", "result_status", "source_id"),
}
# data/master/prefectures.csv と同じ2桁ゼロ埋め（01〜47）
PREFECTURE_CODES = frozenset(f"{i:02d}" for i in range(1, 48))
IDS = {"sources": "source_id", "tournaments": "tournament_id", "teams": "team_id", "matches": "match_id"}


@dataclass(frozen=True)
class Issue:
    table: str
    line: int
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.table}:{self.line} {self.code}: {self.detail}"


@dataclass(frozen=True)
class Report:
    counts: dict[str, int]
    issues: tuple[Issue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def _read(path: Path, name: str, required: tuple[str, ...], issues: list[Issue]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != list(required):
                issues.append(Issue(name, 1, "SCHEMA", f"列定義が不一致: {reader.fieldnames!r}"))
                return []
            result = []
            for line, raw in enumerate(reader, 2):
                if None in raw:
                    issues.append(Issue(name, line, "EXTRA_COLUMN", "列数がヘッダーより多い"))
                    continue
                result.append({key: (raw.get(key) or "").strip() for key in required})
            return result
    except (OSError, UnicodeError, csv.Error) as exc:
        issues.append(Issue(name, 0, "READ_ERROR", f"{type(exc).__name__}: {exc}"))
        return []


def _master_ids(path: Path, id_column: str, name: str, issues: list[Issue]) -> set[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or id_column not in reader.fieldnames:
                issues.append(Issue(name, 1, "MASTER_SCHEMA", f"{id_column} 列がない"))
                return set()
            return {row[id_column].strip() for row in reader if row.get(id_column)}
    except (OSError, UnicodeError, csv.Error) as exc:
        issues.append(Issue(name, 0, "MASTER_READ_ERROR", f"{type(exc).__name__}: {exc}"))
        return set()


def _valid_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _valid_score(value: str) -> bool:
    return bool(re.fullmatch(r"(0|[1-9][0-9]*)", value))


def validate(
    data_dir: Path,
    school_master: Path = ROOT / "data/master/schools.csv",
    competition_master: Path = ROOT / "data/competitions/competitions.csv",
) -> Report:
    """完全にread-only。空のヘッダーのみもスキーマ準備済みとして許可する。"""
    issues: list[Issue] = []

    def error(table: str, line: int, code: str, detail: str) -> None:
        issues.append(Issue(table, line, code, detail))

    tables = {name: _read(data_dir / f"{name}.csv", name, cols, issues)
              for name, cols in COLUMNS.items()}
    schools = _master_ids(school_master, "school_id", "school_master", issues)
    competitions = _master_ids(competition_master, "competition_id", "competition_master", issues)
    indices: dict[str, dict[str, dict[str, str]]] = {}
    for name, key in IDS.items():
        lookup: dict[str, dict[str, str]] = {}
        for line, row in enumerate(tables[name], 2):
            value = row[key]
            if not value:
                error(name, line, "EMPTY_ID", key)
            elif value in lookup:
                error(name, line, "DUPLICATE_ID", value)
            else:
                lookup[value] = row
        indices[name] = lookup
    sources = indices["sources"]
    tournaments = indices["tournaments"]
    teams = indices["teams"]

    def check_source(name: str, line: int, row: dict[str, str]) -> None:
        if row["source_id"] not in sources:
            error(name, line, "UNKNOWN_SOURCE", row["source_id"])

    for line, row in enumerate(tables["sources"], 2):
        if not row["publisher"] or not row["document_title"]:
            error("sources", line, "SOURCE_METADATA", "発行主体・資料名は必須")
        try:
            parts = urlsplit(row["url"])
            valid_url = parts.scheme == "https" and bool(parts.netloc)
        except ValueError:
            valid_url = False
        if not valid_url:
            error("sources", line, "SOURCE_URL", "https URLが必須")
        if not _valid_date(row["retrieved_at"]):
            error("sources", line, "SOURCE_DATE", row["retrieved_at"])
        if row["verification_status"] not in {"official", "secondary", "unverified"}:
            error("sources", line, "SOURCE_STATUS", row["verification_status"])

    for line, row in enumerate(tables["tournaments"], 2):
        check_source("tournaments", line, row)
        if row["season_year"] not in {"2024", "2025", "2026"}:
            error("tournaments", line, "YEAR_SCOPE", row["season_year"])
        if row["season"] not in {"spring", "summer", "autumn"}:
            error("tournaments", line, "SEASON", row["season"])
        if row["level"] not in {"prefectural", "regional", "national"}:
            error("tournaments", line, "LEVEL", row["level"])
        if not row["competition_name"]:
            error("tournaments", line, "EMPTY_NAME", "大会名")
        if row["level"] == "prefectural" and row["prefecture_code"] not in PREFECTURE_CODES:
            error("tournaments", line, "PREFECTURE", row["prefecture_code"])
        if row["competition_id"] and row["competition_id"] not in competitions:
            error("tournaments", line, "UNKNOWN_COMPETITION", row["competition_id"])
        if row["completion_status"] not in {"completed", "in_progress", "unknown"}:
            error("tournaments", line, "COMPLETION_STATUS", row["completion_status"])

    for line, row in enumerate(tables["teams"], 2):
        if row["tournament_id"] not in tournaments:
            error("teams", line, "UNKNOWN_TOURNAMENT", row["tournament_id"])
        if not row["display_name"]:
            error("teams", line, "EMPTY_NAME", "出場チーム名")
        if row["team_type"] not in {"single", "joint"}:
            error("teams", line, "TEAM_TYPE", row["team_type"])

    members: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_names: set[tuple[str, str]] = set()
    seen_ids: set[tuple[str, str]] = set()
    for line, row in enumerate(tables["team_members"], 2):
        team_id, school_id = row["team_id"], row["school_id"]
        check_source("team_members", line, row)
        if team_id not in teams:
            error("team_members", line, "UNKNOWN_TEAM", team_id)
        if not row["observed_name"]:
            error("team_members", line, "EMPTY_NAME", "資料表記")
        if row["mapping_status"] == "verified":
            if not school_id or school_id not in schools:
                error("team_members", line, "UNKNOWN_SCHOOL", school_id)
        elif row["mapping_status"] == "unresolved":
            if school_id:
                error("team_members", line, "UNRESOLVED_WITH_ID", school_id)
        else:
            error("team_members", line, "MAPPING_STATUS", row["mapping_status"])
        if (team_id, row["observed_name"]) in seen_names:
            error("team_members", line, "DUPLICATE_MEMBER_NAME", row["observed_name"])
        seen_names.add((team_id, row["observed_name"]))
        if school_id and (team_id, school_id) in seen_ids:
            error("team_members", line, "DUPLICATE_MEMBER_ID", school_id)
        if school_id:
            seen_ids.add((team_id, school_id))
        members[team_id].append(row)

    for team_id, team in teams.items():
        count = len(members[team_id])
        if (team["team_type"] == "single" and count != 1) or (team["team_type"] == "joint" and count < 2):
            error("teams", 0, "MEMBER_COUNT", f"{team_id}: {count}校")

    for line, row in enumerate(tables["matches"], 2):
        check_source("matches", line, row)
        tournament = tournaments.get(row["tournament_id"])
        if not tournament:
            error("matches", line, "UNKNOWN_TOURNAMENT", row["tournament_id"])
        a, b = row["home_team_id"], row["away_team_id"]
        if not a or not b or a == b:
            error("matches", line, "SAME_OR_EMPTY_TEAM", f"{a}/{b}")
        for team_id in (a, b):
            if team_id not in teams:
                error("matches", line, "UNKNOWN_TEAM", team_id)
            elif teams[team_id]["tournament_id"] != row["tournament_id"]:
                error("matches", line, "CROSS_TOURNAMENT_TEAM", team_id)
        if not row["round_label"]:
            error("matches", line, "EMPTY_ROUND", row["match_id"])
        game_date = row["game_date"]
        if game_date and not _valid_date(game_date):
            error("matches", line, "GAME_DATE", game_date)
        elif game_date and tournament and game_date[:4] != tournament["season_year"]:
            error("matches", line, "DATE_YEAR_MISMATCH", game_date)
        if row["result_status"] == "final":
            if not game_date or not _valid_date(game_date):
                error("matches", line, "FINAL_NEEDS_DATE", row["match_id"])
            if not _valid_score(row["home_score"]) or not _valid_score(row["away_score"]):
                error("matches", line, "FINAL_SCORE", row["match_id"])
        elif row["result_status"] in {"unplayed", "abandoned"}:
            if row["home_score"] or row["away_score"]:
                error("matches", line, "NONFINAL_SCORE", row["match_id"])
        else:
            error("matches", line, "RESULT_STATUS", row["result_status"])

    return Report(
        counts={name: len(tables[name]) for name in COLUMNS},
        issues=tuple(issues),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="実在試合結果CSVのread-only検証")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "historical_data")
    parser.add_argument("--school-master", type=Path, default=ROOT / "data/master/schools.csv")
    parser.add_argument("--competition-master", type=Path, default=ROOT / "data/competitions/competitions.csv")
    args = parser.parse_args()
    report = validate(args.data_dir, args.school_master, args.competition_master)
    print("CSV行数: " + ", ".join(f"{k}={v}" for k, v in report.counts.items()))
    for issue in report.issues:
        print(issue)
    print("OK" if report.ok else f"INVALID: {len(report.issues)} issue(s)")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
