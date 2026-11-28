"""記念大会（game_definition.md §8、ADR-046）。

大会の制度は2026年と同じとするが、回数の決まった年の記念大会だけは例外として出場校を
増やす。どの年が記念大会かは大会の回数（ひな形の回数＋ずらした年数）で決め、値は
``config/selection/commemorative_v1.json`` に置く。

- 選抜：回数が ``edition_divisor`` で割り切れる年は、一般選考の枠を ``extra_general_quota``
  増やす（32校→36校）
- 選手権：回数が ``edition_divisor`` で割り切れる年は、``split_prefectures`` の府県の夏の地方大会を
  2つの区分の大会に分ける（甲子園は56校）。区分の大会は、もとの府県の大会の行（日程・ステージ・
  組み合わせ・シード・代表と秋の不戦勝の決まり）を区分ごとに写してつくる（``expand_rows``）。
  データの行は増やさず、学校の割り振り（``data/areas/commemorative_summer_split_2018.csv``）だけを持つ。
  写した大会は大会表で記念大会の年だけ使い、その年はもとの大会を使わない（``season_catalog``）
"""
from __future__ import annotations

import csv
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Iterable, Mapping

CONFIG_PATH = Path("selection") / "commemorative_v1.json"
_EDITION = re.compile(r"第(\d+)回")


def load_config(config_root: str | Path) -> dict:
    path = Path(config_root) / CONFIG_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("config_id") != "commemorative_v1":
        raise ValueError("commemorative config_id mismatch")
    return data


def config_for_data(data_dir: str | Path) -> dict:
    """``data/`` の隣の ``config/`` から読む（リポジトリの根を data として渡す古い入口では、その下の ``config/``）。"""
    root = Path(data_dir).resolve()
    for config_root in (root.parent / "config", root / "config"):
        if (config_root / CONFIG_PATH).is_file():
            return load_config(config_root)
    return load_config(root.parent / "config")


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


# ---- 選手権：7府県の夏の地方大会を2つに分ける ----

SUMMER_LOCAL = "summer_local_qualifier"
# 区分の大会のID・行のID（もとのIDの後ろに付ける。区分の名前の並びの順）
SUFFIXES = "AB"
# 写した大会の行に付ける印（もとの大会ID・区分の名前）
PARENT_KEY = "commemorative_parent_id"
DISTRICT_KEY = "commemorative_district"

# ファイル → (写す行の大会IDの列, 行のIDの列)
_CLONED = {
    "competitions.csv": ("competition_id", "competition_id"),
    "competition_stages.csv": ("competition_id", "stage_id"),
    "competition_seed_rules.csv": ("destination_competition_id", "seed_rule_id"),
    "bracket_generation_policies.csv": ("competition_id", "bracket_policy_id"),
    "qualification_rules.csv": ("source_competition_id", "rule_id"),
    "season_calendar.csv": ("competition_id", "calendar_id"),
}
MEMBERSHIPS = "school_area_memberships.csv"
EXPANDED = frozenset((*_CLONED, MEMBERSHIPS))


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=8)
def _split_plan(data_dir: str) -> tuple:
    """(もとの大会ID → 区分の大会, 区分の学校の所属の行)。記念大会の決まりがなければ空。"""
    from .paths import resolve_data_file

    root = Path(data_dir)
    config = config_for_data(root)
    rule = rule_for(config, "national_championship") or {}
    split = rule.get("split_prefectures") or {}
    if not split:
        return {}, ()
    competitions = _read_csv(resolve_data_file(root, "competitions.csv"))
    plan: dict[str, dict] = {}
    for row in competitions:
        prefecture = row.get("prefecture_code", "")
        if row.get("competition_type") != SUMMER_LOCAL or prefecture not in split:
            continue
        districts = split[prefecture]
        plan[row["competition_id"]] = {
            "prefecture": prefecture,
            "area": row.get("qualifying_area_id", ""),
            "children": [
                {"competition_id": row["competition_id"] + suffix, "suffix": suffix,
                 "district": district, "area": row.get("qualifying_area_id", "") + suffix}
                for suffix, district in zip(SUFFIXES, districts)
            ],
        }
    # 学校の所属：割り振りの表の区分 → 区分の大会の地域
    programs = {
        r["school_id"]: r["program_id"]
        for r in _read_csv(resolve_data_file(root, "baseball_programs.csv"))
        if r.get("discipline") == "hardball"
    }
    schemes = {
        r["area_id"]: r["scheme_id"]
        for r in _read_csv(resolve_data_file(root, MEMBERSHIPS))
        if r.get("reference_year") == "2026"
    }
    area_of = {
        (entry["prefecture"], child["district"]): (child["area"], schemes.get(entry["area"], ""))
        for entry in plan.values() for child in entry["children"]
    }
    memberships = []
    for number, row in enumerate(_read_csv(resolve_data_file(root, rule["split_data"])), start=1):
        area, scheme = area_of[(row["prefecture_code"], row["district_2018"])]
        memberships.append({
            "membership_id": f"SAMC{number:06d}", "program_id": programs[row["school_id"]],
            "scheme_id": scheme + "C", "area_id": area, "reference_year": "2026",
            "primary_source_id": row.get("source_id", ""), "verified_at": "2026-11-28",
            "notes": f"記念大会の2代表区分（{row['district_2018']}）。{row.get('basis', '')}",
        })
    return plan, tuple(memberships)


def split_parents(data_dir: str | Path) -> dict[str, dict]:
    """もとの大会ID → {prefecture, area, children: [{competition_id, district, area, suffix}]}。"""
    return _split_plan(str(Path(data_dir).resolve()))[0]


def _clone(row: dict, column: str, id_column: str, parent: str, child: dict) -> dict:
    out = dict(row)
    out[column] = child["competition_id"]
    if id_column != column:
        out[id_column] = row[id_column] + child["suffix"]
    return out


def _child_competition(row: dict, child: dict) -> dict:
    out = dict(row)
    out["competition_id"] = child["competition_id"]
    out["competition_code"] = f"{row.get('competition_code', '')}_{child['suffix']}"
    out["competition_name"] = re.sub(
        r"選手権(.+)大会$", f"選手権{child['district']}大会", row.get("competition_name", ""))
    out["qualifying_area_id"] = child["area"]
    out[PARENT_KEY] = row["competition_id"]
    out[DISTRICT_KEY] = child["district"]
    out["notes"] = f"記念大会の年だけの2代表区分の大会（{row['competition_id']} を写した。ADR-046）。"
    return out


def expand_rows(name: str, rows: Iterable[dict], data_dir: str | Path) -> list[dict]:
    """データの表に、区分の大会の行を足す（もとの大会の行を区分ごとに写す）。

    すでに足してある表（区分の大会の行がある）はそのまま返す。"""
    rows = list(rows)
    if name not in EXPANDED:
        return rows
    plan, memberships = _split_plan(str(Path(data_dir).resolve()))
    if not plan:
        return rows
    if name == MEMBERSHIPS:
        have = {row.get("membership_id") for row in rows}
        return rows + [dict(row) for row in memberships if row["membership_id"] not in have]
    column, id_column = _CLONED[name]
    children = {child["competition_id"] for entry in plan.values() for child in entry["children"]}
    if any(row.get(column) in children for row in rows):
        return rows
    out = list(rows)
    for row in rows:
        entry = plan.get(row.get(column, ""))
        if entry is None:
            continue
        for child in entry["children"]:
            out.append(_child_competition(row, child) if name == "competitions.csv"
                       else _clone(row, column, id_column, row[column], child))
    return out


def is_split_year(config: Mapping | None, competition: Mapping, year_offset: int) -> bool:
    """その年の夏の地方大会（ひな形の行）が記念大会の年か（回数は地方大会の名前の回数）。"""
    return is_commemorative(config, "national_championship",
                            edition(competition.get("competition_name", ""), year_offset))


def in_season(config: Mapping | None, competition: Mapping, year_offset: int,
              parents: Mapping[str, dict]) -> bool:
    """その年度の大会表に入れるか。区分の大会は記念大会の年だけ、もとの大会は記念大会でない年だけ。"""
    if competition.get(PARENT_KEY):
        return is_split_year(config, competition, year_offset)
    if competition.get("competition_id") in parents:
        return not is_split_year(config, competition, year_offset)
    return True


def team_count(config: Mapping | None, competition: Mapping, year_offset: int) -> int | None:
    """記念大会の年の出場校の数（決まりに ``team_count`` があるとき）。でなければ None。"""
    ctype = competition.get("competition_type", "")
    if not is_commemorative(config, ctype, edition(competition.get("competition_name", ""), year_offset)):
        return None
    value = (rule_for(config, ctype) or {}).get("team_count")
    return int(value) if value else None


def local_display_name(config: Mapping | None, competition: Mapping, number: int | None) -> str | None:
    """区分の大会の記念大会の年の名前（「第110回全国高等学校野球選手権記念北大阪大会」）。"""
    rule = rule_for(config, "national_championship")
    if not rule or not competition.get(DISTRICT_KEY) or not number:
        return None
    return rule["local_name_format"].format(edition=number, district=competition[DISTRICT_KEY])


def alias_access_rules(rules: Iterable[dict], active: Iterable[str], data_dir: str | Path) -> list[dict]:
    """秋の不戦勝などの決まり（``competition_access_rules``）の元がもとの大会で、その年度に
    もとの大会が開かれず区分の大会が開かれるときは、区分の大会ごとの決まりに置き換える
    （行のIDは後ろに区分の印を付ける）。ほかの決まりはそのまま。"""
    active = set(active)
    parents = split_parents(data_dir)
    out = []
    for rule in rules:
        source = rule.get("source_competition_id_2026", "")
        children = [child for child in parents.get(source, {}).get("children", ())
                    if child["competition_id"] in active]
        if source in active or not children:
            out.append(rule)
            continue
        for child in children:
            out.append({**rule, "source_competition_id_2026": child["competition_id"],
                        "access_rule_id": rule["access_rule_id"] + child["suffix"]})
    return out


def unused_source(source_id: str, active: Iterable[str], competitions: Mapping[str, Mapping]) -> bool:
    """決まりの元の大会が、その年度に開かれない区分の大会かもとの大会か（その決まりは使わない）。

    記念大会の年はもとの大会を、ほかの年は区分の大会を開かないので、その大会を元にする
    決まり（甲子園の代表・秋の不戦勝）は、その年の大会の決まりで置き換わっている。"""
    if source_id in set(active):
        return False
    row = competitions.get(source_id) or {}
    return bool(row.get(PARENT_KEY)) or any(
        other.get(PARENT_KEY) == source_id for other in competitions.values()
    )
