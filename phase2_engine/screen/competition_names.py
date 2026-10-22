"""大会の短い名前（一覧で使う。game_definition.md §9）。

- 「第108回全国高等学校野球選手権静岡大会」→「夏・静岡大会」
- 「第108回全国高等学校野球選手権大会」→「夏の甲子園」
- 「第99回選抜高等学校野球大会」→「選抜大会」
- 「…明治神宮野球大会 高校の部」→「明治神宮大会」
- 「令和8年度春季埼玉県高等学校野球大会」→「春季埼玉県大会」
  （地区大会は「地区」を除く：「秋季近畿大会」）
- 「東京都秋季高等学校野球大会」→「秋季東京都大会」

規則に合わない大会は ``config/screen/competition_short_names_v1.json`` で
大会ID（年度によらず同じ）ごとに直す。
"""
from __future__ import annotations

import json
from pathlib import Path
import re


OVERRIDES_PATH = Path("screen") / "competition_short_names_v1.json"

_RULES = (
    (re.compile(r"全国高等学校野球選手権(.+)大会$"), r"夏・\1大会"),
    (re.compile(r"全国高等学校野球選手権大会$"), "夏の甲子園"),
    (re.compile(r"選抜高等学校野球大会$"), "選抜大会"),
    (re.compile(r"明治神宮野球大会"), "明治神宮大会"),
    (re.compile(r"(春季|秋季)(.+?)(地区)?高等学校野球大会$"), r"\1\2大会"),
    (re.compile(r"^(.+)(春季|秋季)高等学校野球大会$"), r"\2\1大会"),
)


def short_competition_name(name: str) -> str:
    for pattern, replacement in _RULES:
        match = pattern.search(name)
        if match:
            return match.expand(replacement)
    return name


class CompetitionNames:
    def __init__(self, config_root: str | Path):
        path = Path(config_root) / OVERRIDES_PATH
        self._overrides = json.loads(path.read_text(encoding="utf-8"))[
            "overrides"
        ]

    def __call__(self, competition_id: str, name: str) -> str:
        return self._overrides.get(competition_id) or short_competition_name(name)
