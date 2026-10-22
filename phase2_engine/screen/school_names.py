"""学校の短い表示名（game_definition.md §9「校名の表示」）。

学校マスターの表示名は書き方がばらばら（「滋賀県立大津高等学校」「沼南」
「横須賀高校」など）なので、画面では次の規則で短くした名前を使う。

1. 表示名（なければ正式名）から、空白と「キャンパス」を除く
2. 「高等専門学校」は「高専」、「中等教育学校」は「中等」にし、「高等学校」は除く。
   末尾の「高校」「高」も除く（残りが1文字になるときは除かない。「日高」など）
3. 都道府県立の学校は、頭の「〇〇県立」「〇〇県」「都立」などを除く
4. 市立の学校は、頭の「〇〇市立」を「市立」にする

規則に合わない学校は ``config/screen/school_short_names_v1.json`` で個別に直す。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import re

from ..paths import resolve_data_file


OVERRIDES_PATH = Path("screen") / "school_short_names_v1.json"
_PUBLIC_PREFIXES = ("都立", "道立", "府立", "県立")


def prefecture_names(data_dir) -> dict[str, str]:
    path = resolve_data_file(data_dir, "prefectures.csv")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            row["prefecture_code"]: row["prefecture_name"]
            for row in csv.DictReader(handle)
        }


def short_name(school: dict, prefecture_name: str) -> str:
    name = school.get("display_name") or school.get("official_name") or ""
    name = re.sub(r"\s+", "", name).replace("キャンパス", "")
    name = name.replace("高等専門学校", "高専")
    name = name.replace("中等教育学校", "中等")
    name = name.replace("高等学校", "")
    for suffix in ("高校", "高"):
        if name.endswith(suffix) and len(name) - len(suffix) >= 2:
            name = name[:-len(suffix)]
            break
    if school.get("ownership_type") == "prefectural":
        prefixes = (prefecture_name + "立", prefecture_name) + _PUBLIC_PREFIXES
        for prefix in prefixes:
            rest = name[len(prefix):]
            if name.startswith(prefix) and rest and not rest.startswith(
                ("大学", "第")
            ):
                name = rest
                break
    match = re.match(r"^.+?市立(.+)$", name)
    if match:
        name = "市立" + match.group(1)
    return name


class SchoolNames:
    """学校ID → 短い表示名。"""

    def __init__(self, repo, config_root: str | Path):
        path = Path(config_root) / OVERRIDES_PATH
        overrides = json.loads(path.read_text(encoding="utf-8"))["overrides"]
        prefectures = prefecture_names(repo.data_dir)
        self._names = {
            school_id: overrides.get(school_id)
            or short_name(row, prefectures.get(row.get("prefecture_code"), ""))
            for school_id, row in repo.schools.items()
        }

    def __call__(self, school_id: str) -> str:
        return self._names.get(school_id, school_id)

    def all(self) -> dict[str, str]:
        return dict(self._names)
