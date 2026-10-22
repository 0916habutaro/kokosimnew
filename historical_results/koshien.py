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
