"""架空監督の初期生成と保存用データ。選手・試合の乱数や能力には触れない。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from pathlib import Path

from phase2_engine.randomness import rng_for
from phase2_engine.school_year import school_year_of
from .ability_config import load_config
from .player_names import name_generator


@dataclass(frozen=True)
class Coach:
    coach_id: str
    display_name: str
    birth_year: int
    school_id: str
    appointment_year: int
    reputation: int
    development: int
    # 大きいほど早めの継投／若手の起用を好む。6-1では保存のみ。
    pitching_change: int
    player_selection: int

    def view(self, today: date) -> dict:
        year = school_year_of(today)
        return {**asdict(self), "age": year - self.birth_year,
                "tenure_years": year - self.appointment_year + 1}


class CoachBook:
    """人物IDを主キーにする。所属は学校IDで保持し、表示名から結び付けない。"""

    def __init__(self, coaches):
        self.coaches = {}
        schools = set()
        for coach in coaches:
            if coach.coach_id in self.coaches or coach.school_id in schools:
                raise ValueError("duplicate coach ID or school assignment")
            self.coaches[coach.coach_id] = coach
            schools.add(coach.school_id)

    def for_school(self, school_id: str) -> Coach | None:
        return next((c for c in self.coaches.values() if c.school_id == school_id), None)

    @classmethod
    def generate(cls, root: str | Path, teams, seed: int, first_year: int = 2026):
        root = Path(root).resolve()
        config = load_config(root / "config/coaches/coach_generation_v1.json",
                             expected_config_id="coach_generation_v1").payload
        for field in ("age", "tenure", "reputation", "development",
                      "pitching_change", "player_selection"):
            spec = config[field]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in spec.values()):
                raise ValueError(f"coach {field}: finite numbers required")
            if not spec["min"] <= spec.get("mode", spec.get("mean")) <= spec["max"]:
                raise ValueError(f"coach {field}: invalid range")
            if "stddev" in spec and spec["stddev"] <= 0:
                raise ValueError(f"coach {field}: positive stddev required")
        if not 0 < config["minimum_appointment_age"] <= config["age"]["min"]:
            raise ValueError("coach minimum appointment age exceeds minimum age")
        if config["tenure"]["min"] != 1:
            raise ValueError("coach minimum tenure must be one year")
        names = name_generator(str(root))
        coaches = []
        # 人物IDは学校IDを含まない専用乱数。氏名・能力の抽選とも分離する。
        ids = rng_for(seed, "coaches:initial:ids")
        for team in sorted(teams, key=lambda t: t.school_id):
            rng = rng_for(seed, f"coaches:initial:{team.school_id}")
            def triangular(field):
                s = config[field]
                return round(rng.triangular(s["min"], s["max"], s["mode"]))

            def ability(field):
                s = config[field]
                return round(max(s["min"], min(s["max"], rng.gauss(s["mean"], s["stddev"]))))

            age = triangular("age")
            tenure = min(triangular("tenure"), age - config["minimum_appointment_age"] + 1)
            # 既存の苗字頻度・名前の重みだけ再利用。選手の出身・評判は参照しない。
            name = (names.surnames[team.prefecture_code].choose(rng)
                    + names.config["display_separator"] + names.given_names.choose(rng))
            coaches.append(Coach(
                coach_id=f"COACH-{ids.getrandbits(128):032x}", display_name=name,
                birth_year=first_year - age, school_id=team.school_id,
                appointment_year=first_year - tenure + 1,
                reputation=ability("reputation"), development=ability("development"),
                pitching_change=ability("pitching_change"), player_selection=ability("player_selection"),
            ))
        return cls(coaches)
