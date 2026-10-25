"""学校の編集による能力の補正（docs/design/school_edits.md）。

補正は学校ごと・項目（打撃・投手・守備・走力）ごとの段階（±``step_range``）。
選手の能力に足し、学校の強さはその選手から計算する（ADR-001・006）。
能力は選手と学校から毎回計算するので、今の部員にも今後の新入生にも同じように効く。
1段階の大きさは ``config/school_edits/school_edits_v1.json``。
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Mapping

from .abilities import PitchAbility


CONFIG_PATH = Path("school_edits") / "school_edits_v1.json"
CATEGORIES = ("batting", "pitching", "defense", "running")


def _clamp(value: float, low: int, high: int) -> int:
    return min(high, max(low, int(round(value))))


class SchoolAdjustmentModel:
    def __init__(self, config_root: str | Path):
        path = Path(config_root) / CONFIG_PATH
        self.params = json.loads(path.read_text(encoding="utf-8"))
        if self.params.get("config_id") != "school_edits_v1":
            raise ValueError("school edits config_id mismatch")
        self.step_range = int(self.params["step_range"])
        self.categories = self.params["categories"]

    def normalize(self, steps: Mapping[str, object]) -> dict[str, int]:
        """画面から来た段階を、決まった項目と範囲の整数にする（0 は省く）。"""
        out = {}
        for category in CATEGORIES:
            value = int(steps.get(category, 0) or 0)
            if abs(value) > self.step_range:
                raise ValueError(
                    f"補正は ±{self.step_range} 段階までです"
                )
            if value:
                out[category] = value
        return out

    def apply(self, snapshot, steps: Mapping[str, int]):
        """選手の能力（frozen な dataclass）に補正を足した新しい能力を返す。"""
        if not steps:
            return snapshot
        changes: dict[str, object] = {}
        for category, step in steps.items():
            rule = self.categories[category]
            delta = float(rule["points"]) * step
            for name in rule["fields"]:
                value = getattr(snapshot, name)
                if value is not None:
                    changes[name] = _clamp(value + delta, 1, 100)
            if category == "pitching" and snapshot.velocity_kmh is not None:
                changes["velocity_kmh"] = _clamp(
                    snapshot.velocity_kmh + float(rule["velocity_kmh_points"]) * step,
                    100, 165,
                )
                pitch_delta = float(rule["pitch_points"]) * step
                changes["pitch_repertoire"] = tuple(
                    PitchAbility(
                        pitch_type=pitch.pitch_type,
                        quality=_clamp(pitch.quality + pitch_delta, 1, 100),
                        command=_clamp(pitch.command + pitch_delta, 1, 100),
                        usage=pitch.usage,
                    )
                    for pitch in snapshot.pitch_repertoire
                )
        return replace(snapshot, **changes)
