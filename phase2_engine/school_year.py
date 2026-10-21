"""ゲームの年度：4月1日から翌年3月31日まで。

年度 ``year`` は ``year`` 年4月1日に始まり、``year + 1`` 年3月31日に終わる。
"""
from __future__ import annotations

from datetime import date


def school_year_start(year: int) -> date:
    return date(year, 4, 1)


def school_year_end(year: int) -> date:
    return date(year + 1, 3, 31)


def in_school_year(year: int, value: date) -> bool:
    return school_year_start(year) <= value <= school_year_end(year)
