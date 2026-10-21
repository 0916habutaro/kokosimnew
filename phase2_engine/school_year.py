"""ゲームの年度：4月1日から翌年3月31日まで。

年度 ``year`` は ``year`` 年4月1日に始まり、``year + 1`` 年3月31日に終わる。
"""
from __future__ import annotations

from datetime import date
from typing import Mapping


INVITATIONAL_TYPE = "national_invitational"


def school_year_start(year: int) -> date:
    return date(year, 4, 1)


def school_year_end(year: int) -> date:
    return date(year + 1, 3, 31)


def in_school_year(year: int, value: date) -> bool:
    return school_year_start(year) <= value <= school_year_end(year)


def competition_school_year(competition: Mapping[str, str]) -> int:
    """大会が属する年度。

    3月の選抜はその前の年度の秋の結果で選ばれるので、前の年度に属する
    （``reference_year`` が2026の選抜＝2025年度）。3月に始まる春季県大会は
    新しい年度の大会なので ``reference_year`` のまま。
    """
    year = int(competition["reference_year"])
    if competition.get("competition_type") == INVITATIONAL_TYPE:
        return year - 1
    return year
