"""学校の短い表示名（game_definition.md §9「校名の表示」）。

学校マスターの表示名は書き方がばらばら（「滋賀県立大津高等学校」「沼南」
「横須賀高校」など）なので、画面では次の規則で短くした名前を使う。

1. 表示名（なければ正式名）から、空白と「キャンパス」を除く
2. 「高等専門学校」は「高専」、「中等教育学校」は「中等」にし、「高等学校」は除く。
   末尾の「高校」「高」も除く（残りが1文字になるときは除かない。「日高」など）
3. 都道府県立の学校は、頭の「〇〇県立」「〇〇県」「都立」などを除く
4. 市立の学校は、頭の「〇〇市立」を除く。残りがその市の名前だけのときと、同じ
   都道府県のほかの学校と同じ名前になるときは「市」を付ける
   （和歌山市立和歌山→市和歌山、高知市立高知商業→高知商、岐阜市立岐阜商業→市岐阜商）
5. 新聞の略し方に近づける（2026-10-25）
   - 頭の「私立」を除く
   - 「日本大学」は「日大」、「工業大学」は「工大」、「〇〇大学第」は「〇〇大」（日大三）
   - 「大学附属」「大学付属」「大附属」は末尾なら「大付」（盛岡大付）、後ろに名前が
     続けば「大」（東海大学付属相模→東海大相模、近大附属新宮→近大新宮、東海大付浦安→東海大浦安）
   - 残りの「大学」は「大」
   - 末尾の「商業」「工業」「農業」「実業」は「商」「工」「農」「実」

規則に合わない学校は ``config/screen/school_short_names_v1.json`` で個別に直す。
"""
from __future__ import annotations

from collections import Counter
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
    match = re.match(r"^(?:.+?市立|市立)(.+)$", name)
    if match:
        city = (school.get("municipality") or "").removesuffix("市")
        name = ("市" if match.group(1) == city else "") + match.group(1)
    return _newspaper_style(name)


def _newspaper_style(name: str) -> str:
    name = name.removeprefix("私立")
    name = re.sub(r"大学第(?=.)", "大", name)
    name = re.sub(r"大学?[附付]属$", "大付", name)
    name = re.sub(r"大学?[附付]属(?=.)", "大", name)
    name = re.sub(r"大付(?=.)", "大", name)
    name = name.replace("大学", "大")
    name = name.replace("日本大", "日大").replace("工業大", "工大")
    for long, short in (("商業", "商"), ("工業", "工"), ("農業", "農"), ("実業", "実")):
        if name.endswith(long) and len(name) > len(long):
            name = name[:-len(long)] + short
            break
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
        # 市立の学校が同じ都道府県のほかの学校と同じ名前になれば「市」を付ける
        taken = Counter(
            (row.get("prefecture_code"), self._names[school_id])
            for school_id, row in repo.schools.items()
        )
        for school_id, row in repo.schools.items():
            name = self._names[school_id]
            if (
                school_id not in overrides
                and row.get("ownership_type") == "municipal"
                and taken[(row.get("prefecture_code"), name)] > 1
            ):
                self._names[school_id] = "市" + name

    def __call__(self, school_id: str) -> str:
        return self._names.get(school_id, school_id)

    def all(self) -> dict[str, str]:
        return dict(self._names)


class EditedNames:
    """学校の編集で変えた短い名前を優先する（日を渡すと、その日の名前）。"""

    def __init__(self, base: SchoolNames, edits):
        self._base = base
        self.edits = edits

    def __call__(self, school_id: str, day: str = "") -> str:
        name = self.edits.info_on(school_id, day).get("short_name") if school_id else ""
        return name or self._base(school_id)
