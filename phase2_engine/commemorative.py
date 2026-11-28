"""記念大会（game_definition.md §8、ADR-046）。

大会の制度は2026年と同じとするが、回数の決まった年の記念大会だけは例外として出場校を
増やす。どの年が記念大会かは大会の回数（ひな形の回数＋ずらした年数）で決め、値は
``config/selection/commemorative_v1.json`` に置く。

- 選抜：回数が ``edition_divisor`` で割り切れる年は、一般選考の枠を ``extra_general_quota``
  増やす（32校→36校）
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Mapping

CONFIG_PATH = Path("selection") / "commemorative_v1.json"
_EDITION = re.compile(r"第(\d+)回")


def load_config(config_root: str | Path) -> dict:
    path = Path(config_root) / CONFIG_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("config_id") != "commemorative_v1":
        raise ValueError("commemorative config_id mismatch")
    return data


def config_for_data(data_dir: str | Path) -> dict:
    """``data/`` の隣の ``config/`` から読む。"""
    return load_config(Path(data_dir).resolve().parent / "config")


def edition(name: str, year_offset: int) -> int | None:
    """ひな形の大会名の回数を ``year_offset`` 年進めた回数（名前に回数がなければ None）。"""
    found = _EDITION.search(name or "")
    return int(found.group(1)) + year_offset if found else None


def rule_for(config: Mapping | None, competition_type: str) -> dict | None:
    """その種類の大会の記念大会の決まり（なければ None）。"""
    for rule in (config or {}).values():
        if isinstance(rule, dict) and rule.get("competition_type") == competition_type:
            return rule
    return None


def is_commemorative(config: Mapping | None, competition_type: str, number: int | None) -> bool:
    rule = rule_for(config, competition_type)
    return bool(rule and number and number % int(rule["edition_divisor"]) == 0)


def display_name(config: Mapping | None, competition_type: str, number: int | None) -> str | None:
    """記念大会の年の大会名。記念大会でなければ None。"""
    if not is_commemorative(config, competition_type, number):
        return None
    return rule_for(config, competition_type)["name_format"].format(edition=number)


def invitational_extra(config: Mapping | None, competition: Mapping, year_offset: int) -> dict | None:
    """その年の選抜が記念大会なら増枠の決まり（``extra_general_quota`` など）、でなければ None。"""
    ctype = competition.get("competition_type", "")
    if not is_commemorative(config, ctype, edition(competition.get("competition_name", ""), year_offset)):
        return None
    return rule_for(config, ctype)
