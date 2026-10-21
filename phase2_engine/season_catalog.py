"""年度ごとの大会表を2026年の大会からつくる。

大会の制度（出場枠・方式・シード・進出ルール）は2026年と同じとし
（game_definition.md §8）、2026年のデータをひな形にして各年度の大会表を
つくる。

- 年度 ``year`` の大会は、ひな形の大会のうち所属年度を ``year`` に
  ずらしたもの。3月の選抜は前の年度に属するので、2026年度には
  2027年3月の選抜（第99回）が入る
- 大会の回数・令和の年は、ずらした年数だけ進める
- 日程は曜日が2026年と同じになるよう、7日単位でずらす。ずらす日数は
  年度全体で1つ（大会どうしの前後関係を崩さない）。ただし年度の最後を
  越える大会（3月の選抜）だけは1週早める
- ルール・所属などのデータは2026年のものを使う（``rules_year``）
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re
from typing import Iterable, Mapping

from .school_year import competition_school_year, school_year_end


TEMPLATE_YEAR = 2026


def rules_year(year: int) -> int:
    """``year`` 年度の大会に使う制度データの年。2027年以降も2026年と同じ。"""
    return TEMPLATE_YEAR if year >= TEMPLATE_YEAR else year


def calendar_shift_days(year_offset: int) -> int:
    """``year_offset`` 年後の同じ曜日に移すための日数（7の倍数、ずれは±3日以内）。"""
    days = (
        date(TEMPLATE_YEAR + year_offset, 1, 1)
        - date(TEMPLATE_YEAR, 1, 1)
    ).days
    return 7 * round(days / 7)


def shift_date_list(value: str, days: int) -> str:
    if not value:
        return ""
    return ";".join(
        (date.fromisoformat(item.strip()) + timedelta(days=days)).isoformat()
        for item in value.split(";")
        if item.strip()
    )


_EDITION = re.compile(r"第(\d+)回")
_REIWA = re.compile(r"令和(\d+)年度")
_COMMEMORATION = re.compile(r"^\S*記念\s+")


def competition_display_name(name: str, year_offset: int) -> str:
    """回数と令和の年を ``year_offset`` 年分進めた大会名。"""
    if not year_offset:
        return name
    # 記念大会の冠はその年だけのものなので外す。
    name = _COMMEMORATION.sub("", name)
    name = _EDITION.sub(
        lambda m: f"第{int(m.group(1)) + year_offset}回", name
    )
    return _REIWA.sub(
        lambda m: f"令和{int(m.group(1)) + year_offset}年度", name
    )


@dataclass(frozen=True)
class SeasonCompetition:
    competition_id: str
    year_offset: int
    shift_days: int
    display_name: str


def season_competitions(
    competitions: Iterable[Mapping[str, str]],
    calendar_by_competition: Mapping[str, Mapping[str, str]],
    year: int,
) -> dict[str, SeasonCompetition]:
    """``year`` 年度に開かれる大会（ひな形の大会ID → ずらし方）。"""
    out: dict[str, SeasonCompetition] = {}
    for row in competitions:
        if row.get("reference_year") != str(TEMPLATE_YEAR):
            continue
        offset = year - competition_school_year(row)
        if offset < 0:
            continue
        shift = calendar_shift_days(offset)
        calendar = calendar_by_competition.get(row["competition_id"], {})
        last = max(
            [
                value
                for value in (
                    calendar.get("end_date", ""),
                    *(calendar.get("game_date_list") or "").split(";"),
                )
                if value
            ],
            default="",
        )
        if last and (
            date.fromisoformat(last) + timedelta(days=shift)
            > school_year_end(year)
        ):
            shift -= 7
        out[row["competition_id"]] = SeasonCompetition(
            competition_id=row["competition_id"],
            year_offset=offset,
            shift_days=shift,
            display_name=competition_display_name(
                row["competition_name"], offset
            ),
        )
    return out


def shift_calendar_row(
    row: Mapping[str, str],
    days: int,
) -> dict:
    shifted = dict(row)
    for key in ("start_date", "end_date", "draw_date", "game_date_list"):
        shifted[key] = shift_date_list(row.get(key, ""), days)
    return shifted


def shift_stage_calendar_row(
    row: Mapping[str, str],
    days: int,
) -> dict:
    shifted = dict(row)
    shifted["date_list"] = shift_date_list(row.get("date_list", ""), days)
    return shifted


def is_previous_school_year_source(
    competitions: Mapping[str, Mapping[str, str]],
    source_id: str,
    destination_id: str,
) -> bool:
    """進出元の大会が進出先より前の年度の大会か（例：3月の選抜→春季大会）。"""
    source = competitions.get(source_id)
    destination = competitions.get(destination_id)
    if source is None or destination is None:
        return False
    return (
        competition_school_year(source)
        < competition_school_year(destination)
    )
