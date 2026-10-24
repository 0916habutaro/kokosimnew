"""学校の編集（docs/design/school_edits.md）。セーブ（スロット）ごとに保存する。

``data/master`` は書き換えない。編集はスロットのフォルダの ``school_edits.json``
に置き、読み込むときにゲームへ反映する。

- 学校の情報（表示名・短い名前・設置者）：変更した日（ゲームの日付）と一緒に
  残す。その日より前の試合は、当時の名前で表示する
- 能力の補正：学校ごと・項目ごとの段階。選手の能力に足す（``game_core.school_edits``）
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path


FILE_NAME = "school_edits.json"
SCHEMA = 1
INFO_FIELDS = ("display_name", "short_name", "ownership_type")


@dataclass
class SchoolEdits:
    # 学校ID → {"info": [{"date", 変えた項目…}], "ability": {項目: 段階},
    #            "ability_history": [{"date", "steps"}]}
    schools: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, slot_dir: str | Path) -> "SchoolEdits":
        path = Path(slot_dir) / FILE_NAME
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise ValueError("school edits schema mismatch")
        return cls(schools=data.get("schools", {}))

    def save(self, slot_dir: str | Path) -> None:
        path = Path(slot_dir) / FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps({"schema": SCHEMA, "schools": self.schools},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        os.replace(temp, path)

    # ---- 学校の情報 ----

    def info_on(self, school_id: str, day: str = "") -> dict:
        """その日に有効な情報（変えた項目だけ）。日を省くと今の情報。"""
        out: dict = {}
        for entry in self.schools.get(school_id, {}).get("info", []):
            if day and entry["date"] > day:
                break
            out.update({key: entry[key] for key in INFO_FIELDS if key in entry})
        return out

    def set_info(self, school_id: str, day: str, changes: dict) -> bool:
        """今の情報と違う項目だけを、その日の変更として残す。変わらなければ False。"""
        current = self.info_on(school_id)
        diff = {
            key: value for key, value in changes.items()
            if key in INFO_FIELDS and current.get(key) != value
        }
        if not diff:
            return False
        entries = self.schools.setdefault(school_id, {}).setdefault("info", [])
        if entries and entries[-1]["date"] == day:
            entries[-1].update(diff)
        else:
            entries.append({"date": day, **diff})
        return True

    def ownership_overrides(self) -> dict[str, str]:
        return {
            school_id: info["ownership_type"]
            for school_id in self.schools
            if "ownership_type" in (info := self.info_on(school_id))
        }

    def info_history(self, school_id: str) -> list[dict]:
        return list(self.schools.get(school_id, {}).get("info", []))

    # ---- 能力の補正 ----

    def ability(self, school_id: str) -> dict[str, int]:
        return dict(self.schools.get(school_id, {}).get("ability", {}))

    def set_ability(self, school_id: str, day: str, steps: dict[str, int]) -> bool:
        if steps == self.ability(school_id):
            return False
        entry = self.schools.setdefault(school_id, {})
        entry["ability"] = dict(steps)
        history = entry.setdefault("ability_history", [])
        if history and history[-1]["date"] == day:
            history[-1]["steps"] = dict(steps)
        else:
            history.append({"date": day, "steps": dict(steps)})
        return True

    def adjustments(self) -> dict[str, dict[str, int]]:
        return {
            school_id: dict(entry["ability"])
            for school_id, entry in self.schools.items()
            if entry.get("ability")
        }
