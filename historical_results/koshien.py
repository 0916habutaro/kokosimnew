"""甲子園（夏の選手権・春の選抜）のゲーム開始前の実際の記録。

- ``historical_data/koshien_appearances.csv``：1行＝1校の1回の出場（年・試合の勝敗・成績・出典）
- ``historical_data/koshien_records.csv``：1行＝1校×1種別の通算（画面が読む）

通算は出場の記録から数えたものと一致しなければならない。ゲームの記録とは混ぜない。
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "historical_data"

KINDS = ("summer", "spring")
# どの大会までの記録か（ゲームは2026年4月開始。2026年の選抜は実際の大会）
AS_OF_EDITION = {"summer": 107, "spring": 98}
AS_OF_YEAR = {"summer": 2025, "spring": 2026}
RESULTS = ("優勝", "準優勝", "ベスト4", "ベスト8", "3回戦", "2回戦", "1回戦")
# 通算だけ分かっている学校（出場ごとの記録がない）で使える最高成績。何回戦か分からない初戦敗退
RECORD_ONLY_RESULTS = RESULTS + ("初戦敗退",)

APPEARANCE_COLUMNS = (
    "kind", "year", "school_id", "team_name", "results", "result", "source_id",
)
RECORD_COLUMNS = (
    "school_id", "kind", "as_of_edition", "appearances", "wins", "losses",
    "draws", "championships", "runner_ups", "best_result",
    "last_appearance_year", "appearance_years", "source_id", "verified_at",
    "notes",
)


# 主催者の裁定記録は実際の試合結果W/L/Dとは区別する。
# 未判明の算入基準は unknown とし、勝敗ゼロへ暗黙変換しない。
SPECIAL_RESULT_COLUMNS = (
    "event_id", "kind", "year", "edition", "round_label",
    "winner_school_id", "winner_team_name", "loser_school_id", "loser_team_name",
    "result_type", "played", "win_counted", "loss_counted", "source_id",
)
SPECIAL_RESULT_TYPES = frozenset({"walkover"})
SPECIAL_COUNT_VALUES = frozenset({"0", "1", "unknown"})

# 当時の学校・野球部系列を大会ごとの実出場と分けて識別する。
# 現役校の school_id をそのまま歴史校IDとして使わない。
HISTORICAL_SCHOOL_COLUMNS = (
    "historical_school_id",
    "historical_name",
    "source_id",
    "notes",
)
HISTORICAL_TEAM_COLUMNS = (
    "appearance_id",
    "historical_school_id",
    "kind",
    "year",
    "edition",
    "team_name",
    "representative_region",
    "source_id",
)
HISTORICAL_ATTRIBUTION_COLUMNS = (
    "appearance_id",
    "school_id",
    "counts_in_school_total",
    "source_id",
)
ATTRIBUTION_COUNT_VALUES = frozenset({"0", "1", "unknown"})


@dataclass(frozen=True)
class Issue:
    table: str
    line: int
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.table}:{self.line} {self.code}: {self.detail}"


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def aggregate(appearances: list[dict[str, str]]) -> dict[tuple[str, str], dict]:
    """出場の記録から、学校×種別の通算を数える。"""
    totals: dict[tuple[str, str], dict] = {}
    for row in sorted(appearances, key=lambda r: int(r["year"])):
        key = (row["school_id"], row["kind"])
        total = totals.setdefault(key, {
            "years": [], "wins": 0, "losses": 0, "draws": 0,
            "championships": 0, "runner_ups": 0, "best_result": "",
        })
        total["years"].append(int(row["year"]))
        total["wins"] += row["results"].count("W")
        total["losses"] += row["results"].count("L")
        total["draws"] += row["results"].count("D")
        result = row["result"]
        if result == "優勝":
            total["championships"] += 1
        elif result == "準優勝":
            total["runner_ups"] += 1
        if result and (
            not total["best_result"]
            or RESULTS.index(result) < RESULTS.index(total["best_result"])
        ):
            total["best_result"] = result
    return totals



def summarize_adjudications(
    special_results: list[dict[str, str]],
) -> dict[tuple[str, str], dict[str, int]]:
    """認定勝敗と算入未確定件数を、実施試合の W/L/D と独立して数える。

    source に裏付けられた counted=1 だけを加算する。unknown を0扱いしない。
    現行の aggregate()・通算CSVは、この値で自動更新しない（移行は別PR）。
    """
    totals: dict[tuple[str, str], dict[str, int]] = {}
    for row in special_results:
        for side, counted, confirmed, pending in (
            ("winner", "win_counted", "awarded_wins", "pending_wins"),
            ("loser", "loss_counted", "awarded_losses", "pending_losses"),
        ):
            school_id = row[f"{side}_school_id"]
            if not school_id:
                continue  # 歴史校の帰属未確定。学校IDを推測しない。
            key = (school_id, row["kind"])
            total = totals.setdefault(key, {
                "awarded_wins": 0, "awarded_losses": 0,
                "pending_wins": 0, "pending_losses": 0,
            })
            status = row[counted]
            if status == "1":
                total[confirmed] += 1
            elif status == "unknown":
                total[pending] += 1
    return totals



def summarize_historical_attributions(
    team_rows: list[dict[str, str]],
    attribution_rows: list[dict[str, str]],
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], dict[str, int]]]:
    """実出場チーム数と、学校ごとの継承通算を独立集計する。

    一つの実出場を複数校が継承表示しても全国出場数は増えない。
    unknownは数値0に自動確定せずpendingに集計する。
    入力の検証は validate() が担当し、本関数は検証済み行を受け取る。
    """
    team_index = {row["appearance_id"]: row for row in team_rows}
    actual: dict[tuple[str, str], int] = {}
    school: dict[tuple[str, str], dict[str, int]] = {}
    for row in team_rows:
        key = (row["kind"], row["year"])
        actual[key] = actual.get(key, 0) + 1
    for row in attribution_rows:
        team = team_index[row["appearance_id"]]
        key = (row["school_id"], team["kind"])
        tally = school.setdefault(key, {"counted": 0, "excluded": 0, "pending": 0})
        decision = row["counts_in_school_total"]
        tally[{"1": "counted", "0": "excluded", "unknown": "pending"}[decision]] += 1
    return actual, school


def validate(
    data_dir: Path = DATA_DIR,
    school_master: Path = ROOT / "data/master/schools.csv",
) -> list[Issue]:
    issues: list[Issue] = []

    def error(table: str, line: int, code: str, detail: str) -> None:
        issues.append(Issue(table, line, code, detail))

    _, schools = read_rows(school_master)
    school_ids = {row["school_id"] for row in schools}
    _, sources = read_rows(data_dir / "sources.csv")
    source_ids = {row["source_id"] for row in sources}


    # 全国共通の裁定。元の年度別W/L/Dと別管理し、既存通算の数字を変えない。
    try:
        special_columns, special_rows = read_rows(data_dir / "koshien_special_results.csv")
    except (OSError, UnicodeError, csv.Error) as exc:
        error("special", 0, "READ_ERROR", f"{type(exc).__name__}: {exc}")
        special_columns, special_rows = [], []
    if tuple(special_columns) != SPECIAL_RESULT_COLUMNS:
        error("special", 1, "SCHEMA", repr(special_columns))
    else:
        seen_events: set[str] = set()
        for line, row in enumerate(special_rows, 2):
            if None in row or any(v is None for v in row.values()):
                error("special", line, "ROW_COLUMNS", "列数不足または余剰")
                continue
            event_id = row["event_id"]
            if not event_id or event_id in seen_events:
                error("special", line, "DUPLICATE_OR_EMPTY_ID", event_id)
            seen_events.add(event_id)
            kind = row["kind"]
            if kind not in KINDS:
                error("special", line, "KIND", kind)
            year = row["year"]
            if not re.fullmatch(r"\d{4}", year) or (
                kind in KINDS and not 1915 <= int(year) <= AS_OF_YEAR[kind]
            ):
                error("special", line, "YEAR", year)
            edition = row["edition"]
            if not re.fullmatch(r"\d+", edition) or (
                kind in KINDS and not 1 <= int(edition) <= AS_OF_EDITION[kind]
            ):
                error("special", line, "EDITION", edition)
            if not row["round_label"]:
                error("special", line, "ROUND", event_id)
            for side in ("winner", "loser"):
                school_id = row[f"{side}_school_id"]
                if school_id and school_id not in school_ids:
                    error("special", line, "UNKNOWN_SCHOOL", school_id)
                if not row[f"{side}_team_name"]:
                    error("special", line, "EMPTY_TEAM_NAME", side)
            if row["winner_team_name"] == row["loser_team_name"]:
                error("special", line, "SAME_TEAM_NAME", event_id)
            if row["result_type"] not in SPECIAL_RESULT_TYPES:
                error("special", line, "RESULT_TYPE", row["result_type"])
            if row["played"] != "false":
                error("special", line, "PLAYED", row["played"])
            for field in ("win_counted", "loss_counted"):
                if row[field] not in SPECIAL_COUNT_VALUES:
                    error("special", line, "COUNTED", f"{field}={row[field]}")
            if row["source_id"] not in source_ids:
                error("special", line, "UNKNOWN_SOURCE", row["source_id"])


    # 歴史上の学校・野球部系列は、現役学校マスターから独立して管理する。
    try:
        history_columns, history_rows = read_rows(
            data_dir / "koshien_historical_schools.csv")
    except (OSError, UnicodeError, csv.Error) as exc:
        error("historical_schools", 0, "READ_ERROR", f"{type(exc).__name__}: {exc}")
        history_columns, history_rows = [], []
    historical_school_ids: set[str] = set()
    if tuple(history_columns) != HISTORICAL_SCHOOL_COLUMNS:
        error("historical_schools", 1, "SCHEMA", repr(history_columns))
    else:
        for line, row in enumerate(history_rows, 2):
            if None in row or any(v is None for v in row.values()):
                error("historical_schools", line, "ROW_COLUMNS", "列数不足または余剰")
                continue
            historical_school_id = row["historical_school_id"]
            if not historical_school_id or historical_school_id in historical_school_ids:
                error("historical_schools", line, "DUPLICATE_OR_EMPTY_ID", historical_school_id)
            historical_school_ids.add(historical_school_id)
            if not row["historical_name"]:
                error("historical_schools", line, "EMPTY_NAME", historical_school_id)
            if row["source_id"] not in source_ids:
                error("historical_schools", line, "UNKNOWN_SOURCE", row["source_id"])

    # 当時の大会出場チームと、現在の学校の継承通算を独立して保持する。
    # ヘッダーのみから段階導入し、旧koshien_appearancesやaggregateは変更しない。
    try:
        historical_columns, historical_rows = read_rows(
            data_dir / "koshien_historical_teams.csv")
    except (OSError, UnicodeError, csv.Error) as exc:
        error("historical_teams", 0, "READ_ERROR", f"{type(exc).__name__}: {exc}")
        historical_columns, historical_rows = [], []
    historical_index: dict[str, dict[str, str]] = {}
    if tuple(historical_columns) != HISTORICAL_TEAM_COLUMNS:
        error("historical_teams", 1, "SCHEMA", repr(historical_columns))
    else:
        for line, row in enumerate(historical_rows, 2):
            if None in row or any(v is None for v in row.values()):
                error("historical_teams", line, "ROW_COLUMNS", "列数不足または余剰")
                continue
            appearance_id = row["appearance_id"]
            if not appearance_id or appearance_id in historical_index:
                error("historical_teams", line, "DUPLICATE_OR_EMPTY_ID", appearance_id)
            else:
                historical_index[appearance_id] = row
            historical_school_id = row["historical_school_id"]
            if historical_school_id not in historical_school_ids:
                error("historical_teams", line, "UNKNOWN_HISTORICAL_SCHOOL", historical_school_id)
            kind = row["kind"]
            if kind not in KINDS:
                error("historical_teams", line, "KIND", kind)
            year = row["year"]
            if not re.fullmatch(r"\d{4}", year) or (
                kind in KINDS and not 1915 <= int(year) <= AS_OF_YEAR[kind]
            ):
                error("historical_teams", line, "YEAR", year)
            edition = row["edition"]
            if not re.fullmatch(r"\d+", edition) or (
                kind in KINDS and not 1 <= int(edition) <= AS_OF_EDITION[kind]
            ):
                error("historical_teams", line, "EDITION", edition)
            if not row["team_name"]:
                error("historical_teams", line, "EMPTY_TEAM_NAME", appearance_id)
            # 地域名は植民地・旧行政区の当時表記も想定し、都道府県コードを強制しない。
            if not row["representative_region"]:
                error("historical_teams", line, "EMPTY_REGION", appearance_id)
            if row["source_id"] not in source_ids:
                error("historical_teams", line, "UNKNOWN_SOURCE", row["source_id"])

    try:
        link_columns, link_rows = read_rows(
            data_dir / "koshien_team_attributions.csv")
    except (OSError, UnicodeError, csv.Error) as exc:
        error("team_attributions", 0, "READ_ERROR", f"{type(exc).__name__}: {exc}")
        link_columns, link_rows = [], []
    if tuple(link_columns) != HISTORICAL_ATTRIBUTION_COLUMNS:
        error("team_attributions", 1, "SCHEMA", repr(link_columns))
    else:
        link_keys: set[tuple[str, str]] = set()
        for line, row in enumerate(link_rows, 2):
            if None in row or any(v is None for v in row.values()):
                error("team_attributions", line, "ROW_COLUMNS", "列数不足または余剰")
                continue
            appearance_id, school_id = row["appearance_id"], row["school_id"]
            if not appearance_id or appearance_id not in historical_index:
                error("team_attributions", line, "UNKNOWN_APPEARANCE", appearance_id)
            if not school_id or school_id not in school_ids:
                error("team_attributions", line, "UNKNOWN_SCHOOL", school_id)
            if row["counts_in_school_total"] not in ATTRIBUTION_COUNT_VALUES:
                error("team_attributions", line, "COUNTED", row["counts_in_school_total"])
            if row["source_id"] not in source_ids:
                error("team_attributions", line, "UNKNOWN_SOURCE", row["source_id"])
            key = (appearance_id, school_id)
            if key in link_keys:
                error("team_attributions", line, "DUPLICATE_LINK", "/".join(key))
            link_keys.add(key)

    columns, appearances = read_rows(data_dir / "koshien_appearances.csv")
    if tuple(columns) != APPEARANCE_COLUMNS:
        error("appearances", 1, "SCHEMA", repr(columns))
        return issues
    seen = set()
    for line, row in enumerate(appearances, 2):
        if row["kind"] not in KINDS:
            error("appearances", line, "KIND", row["kind"])
            continue
        if not re.fullmatch(r"\d{4}", row["year"]) or not (
            1915 <= int(row["year"]) <= AS_OF_YEAR[row["kind"]]
        ):
            error("appearances", line, "YEAR", row["year"])
        if row["school_id"] not in school_ids:
            error("appearances", line, "UNKNOWN_SCHOOL", row["school_id"])
        if row["source_id"] not in source_ids:
            error("appearances", line, "UNKNOWN_SOURCE", row["source_id"])
        if not row["team_name"]:
            error("appearances", line, "EMPTY_NAME", "当時の校名")
        if not re.fullmatch(r"[WLD]*", row["results"]):
            error("appearances", line, "RESULTS", row["results"])
        if row["results"] and row["result"] not in RESULTS:
            error("appearances", line, "RESULT", row["result"])
        if not row["results"] and row["result"]:
            error("appearances", line, "RESULT_WITHOUT_GAMES", row["result"])
        if row["result"] == "優勝" and "L" in row["results"]:
            error("appearances", line, "CHAMPION_LOST", row["results"])
        key = (row["kind"], row["year"], row["school_id"])
        if key in seen:
            error("appearances", line, "DUPLICATE", "/".join(key))
        seen.add(key)

    columns, records = read_rows(data_dir / "koshien_records.csv")
    if tuple(columns) != RECORD_COLUMNS:
        error("records", 1, "SCHEMA", repr(columns))
        return issues
    totals = aggregate([
        row for row in appearances if row["kind"] in KINDS
        and re.fullmatch(r"\d{4}", row["year"])
    ])
    keys = set()
    for line, row in enumerate(records, 2):
        key = (row["school_id"], row["kind"])
        if key in keys:
            error("records", line, "DUPLICATE", "/".join(key))
        keys.add(key)
        if row["kind"] not in KINDS:
            error("records", line, "KIND", row["kind"])
            continue
        if row["school_id"] not in school_ids:
            error("records", line, "UNKNOWN_SCHOOL", row["school_id"])
        if row["source_id"] not in source_ids:
            error("records", line, "UNKNOWN_SOURCE", row["source_id"])
        if row["as_of_edition"] != str(AS_OF_EDITION[row["kind"]]):
            error("records", line, "AS_OF", row["as_of_edition"])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["verified_at"]):
            error("records", line, "VERIFIED_AT", row["verified_at"])
        numbers = ("appearances", "wins", "losses", "draws", "championships",
                   "last_appearance_year")
        if not all(re.fullmatch(r"\d+", row[name]) for name in numbers) or not re.fullmatch(
            r"\d*", row["runner_ups"]
        ):
            error("records", line, "NUMBER", "数の列")
            continue
        if int(row["appearances"]) < 1:
            error("records", line, "APPEARANCES", row["appearances"])
        if row["best_result"] and row["best_result"] not in RECORD_ONLY_RESULTS:
            error("records", line, "BEST_RESULT", row["best_result"])
        years = row["appearance_years"]
        if years:
            listed = [int(y) for y in years.split(";")]
            if len(listed) != int(row["appearances"]):
                error("records", line, "YEARS_COUNT", years)
            if listed != sorted(set(listed)) or max(listed) != int(row["last_appearance_year"]):
                error("records", line, "YEARS_ORDER", years)
        total = totals.get(key)
        if total is None:
            # 出場ごとの記録がない学校は通算だけを持つ（出典の値をそのまま使う）
            continue
        expected = {
            "appearances": str(len(total["years"])),
            "wins": str(total["wins"]),
            "losses": str(total["losses"]),
            "draws": str(total["draws"]),
            "championships": str(total["championships"]),
            "runner_ups": str(total["runner_ups"]),
            "best_result": total["best_result"],
            "last_appearance_year": str(max(total["years"])),
            "appearance_years": ";".join(str(y) for y in total["years"]),
        }
        for name, value in expected.items():
            if name == "appearance_years" and not row[name]:
                continue
            if row[name] != value:
                error("records", line, "MISMATCH", f"{'/'.join(key)} {name}: {row[name]} != {value}")
    for key in sorted(set(totals) - keys):
        error("records", 0, "MISSING_RECORD", "/".join(key))
    return issues


def main() -> int:
    issues = validate()
    for issue in issues:
        print(issue)
    print("OK" if not issues else f"INVALID: {len(issues)} issue(s)")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
