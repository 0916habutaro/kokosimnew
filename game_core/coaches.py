"""架空監督の初期生成・年度人事・人物と所属履歴・入学時の評判補正。"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass, replace
from datetime import date
import math
from pathlib import Path

from phase2_engine.randomness import rng_for
from phase2_engine.school_year import school_year_of
from .ability_config import load_config
from .player_names import ROOT, name_generator


@dataclass(frozen=True)
class Coach:
    coach_id: str
    display_name: str
    birth_year: int
    school_id: str
    appointment_year: int
    reputation: int
    development: int
    # 大きいほど早めの継投／若手の起用を好む。6-2では効果を接続しない。
    pitching_change: int
    player_selection: int
    retired_on: str | None = None

    def view(self, today: date) -> dict:
        year = school_year_of(today)
        return {**asdict(self), "age": year - self.birth_year,
                "tenure_years": year - self.appointment_year + 1}


@dataclass(frozen=True)
class CoachEvent:
    date: str
    kind: str
    coach_id: str
    from_school_id: str | None
    to_school_id: str | None
    previous_appointment_date: str | None = None

    @property
    def completed_tenure_years(self) -> int | None:
        if self.previous_appointment_date is None:
            return None
        return int(self.date[:4]) - int(self.previous_appointment_date[:4])


@dataclass(frozen=True)
class CoachIntakeRating:
    first_entry_year: int
    reputation: int
    quality_z: float


@dataclass(frozen=True)
class CoachTactics:
    """試合用の小さな判断補正。人物データや選手の能力は含めない。"""
    bf_multiplier: float = 1.0
    quick_hook_reduction: int = 0
    selection_grade_bias: float = 0.0


def _draw_coach(team, year, rng, coach_id, names, config, *, initial):
    def triangular(spec):
        return round(rng.triangular(spec["min"], spec["max"], spec["mode"]))

    def ability(field):
        s = config[field]
        return round(max(s["min"], min(s["max"], rng.gauss(s["mean"], s["stddev"]))))

    age = triangular(config["age"])
    tenure = (min(triangular(config["tenure"]), age - config["minimum_appointment_age"] + 1)
              if initial else 1)
    name = (names.surnames[team.prefecture_code].choose(rng)
            + names.config["display_separator"] + names.given_names.choose(rng))
    return Coach(coach_id, name, year - age, team.school_id, year - tenure + 1,
                 ability("reputation"), ability("development"),
                 ability("pitching_change"), ability("player_selection"))


def _band_probability(bands, value):
    return next((prob for minimum, prob in reversed(bands) if value >= minimum), 0.0)


class CoachBook:
    """人物IDを主キーにする。所属は学校IDで保持し、表示名から結び付けない。"""

    def __init__(self, coaches, *, seed=0, first_year=2026, root=ROOT):
        self.coaches = {}
        schools = set()
        for coach in coaches:
            if coach.coach_id in self.coaches or coach.school_id in schools:
                raise ValueError("duplicate coach ID or school assignment")
            self.coaches[coach.coach_id] = coach
            schools.add(coach.school_id)
        self.seed = seed
        self.first_year = self.updated_year = first_year
        self.bind(root)
        self.config = load_config(self._root / "config/coaches/coach_personnel_v1.json",
                                  expected_config_id="coach_personnel_v1").payload
        self._validate_config()
        self.intake_config = load_config(self._root / "config/coaches/coach_intake_v1.json",
                                        expected_config_id="coach_intake_v1").payload
        effect = self.intake_config
        if (effect["first_entry_year"] < 2027 or effect["neutral_reputation"] != 50
                or not math.isfinite(effect["z_per_reputation_point"])
                or effect["z_per_reputation_point"] < 0
                or not math.isfinite(effect["max_abs_z"]) or effect["max_abs_z"] < 0):
            raise ValueError("invalid coach intake configuration")
        self.intake_year = first_year
        # 同じ人物・同じ評判の年度は複製しない。所属は既存イベントで参照する。
        self.intake_ratings: dict[str, list[CoachIntakeRating]] = {}
        self.growth_config = load_config(self._root / "config/coaches/coach_growth_v1.json",
                                        expected_config_id="coach_growth_v1").payload
        growth = self.growth_config
        first_month = date.fromisoformat(growth["first_practice_month"])
        if (first_month.day != 1 or first_month < date(2027, 4, 1)
                or growth["coach_reference"] != "month_start"
                or growth["neutral_development"] != 50
                or not math.isfinite(growth["multiplier_per_point"])
                or growth["multiplier_per_point"] < 0
                or not math.isfinite(growth["max_abs_delta"])
                or not 0 <= growth["max_abs_delta"] < 1):
            raise ValueError("invalid coach practice growth configuration")
        self.events = [CoachEvent(f"{c.appointment_year}-04-01", "initial", c.coach_id,
                                  None, c.school_id) for c in self.coaches.values()]
        self.tactics_config = load_config(self._root / "config/coaches/coach_tactics_v1.json",
                                         expected_config_id="coach_tactics_v1").payload
        tactics = self.tactics_config
        if (date.fromisoformat(tactics["first_match_date"]) < date(2027, 4, 1)
                or tactics["neutral_ability"] != 50
                or any(not math.isfinite(tactics[k]) or tactics[k] < 0 for k in (
                    "bf_reduction_per_point", "max_abs_bf_reduction",
                    "quick_hook_reduction_per_point", "max_abs_quick_hook_reduction",
                    "selection_bias_per_point", "max_abs_selection_bias"))
                or tactics["max_abs_bf_reduction"] >= 1):
            raise ValueError("invalid coach tactics configuration")
        self._rebuild_indexes()

    def bind(self, root):
        self._root = Path(root).resolve()

    def __getstate__(self):
        return {k: v for k, v in self.__dict__.items()
                if k not in ("_root", "active_by_school", "_school_history")}

    def __setstate__(self, data):
        self.__dict__.update(data)
        self.bind(ROOT)
        self._rebuild_indexes()

    def _validate_config(self):
        retirement = self.config["retirement"]
        if not 0 <= retirement["minimum_age"] < retirement["maximum_age"]:
            raise ValueError("coach retirement age range is invalid")
        bands = [retirement["age_probabilities"], *self.config["transfer"].values()]
        for rows in bands:
            if not rows or [r[0] for r in rows] != sorted(set(r[0] for r in rows)):
                raise ValueError("coach probability bands must increase")
            if any(not math.isfinite(p) or not 0 <= p <= 1 for _, p in rows):
                raise ValueError("coach probability must be between zero and one")
        for group in ("public", "private"):
            s = retirement[group]
            if not (s["tenure_threshold"] >= 1 and 0 <= s["per_year"] <= 1
                    and 0 <= s["maximum_bonus"] <= 1):
                raise ValueError("coach retirement tenure bonus is invalid")
        age = self.config["successor_age"]
        if not (0 < age["min"] <= age["mode"] <= age["max"] < retirement["maximum_age"]):
            raise ValueError("coach successor age range is invalid")

    def _rebuild_indexes(self):
        self.active_by_school = {c.school_id: c.coach_id for c in self.coaches.values()
                                 if c.retired_on is None}
        # 同日の全退任・異動元を先に空席にし、その後の就任を優先する。
        changes = {}
        for event in self.events:
            if event.from_school_id:
                changes.setdefault(event.from_school_id, {}).setdefault(event.date, None)
            if event.to_school_id:
                changes.setdefault(event.to_school_id, {})[event.date] = event.coach_id
        self._school_history = {sid: sorted(rows.items()) for sid, rows in changes.items()}

    def for_school(self, school_id: str, on: date | None = None) -> Coach | None:
        if on is None:
            return self.coaches.get(self.active_by_school.get(school_id))
        rows = self._school_history.get(school_id, [])
        index = bisect_right(rows, on.isoformat(), key=lambda row: row[0]) - 1
        if index < 0 or rows[index][1] is None:
            return None
        start, cid = rows[index]
        return replace(self.coaches[cid], school_id=school_id,
                       appointment_year=int(start[:4]), retired_on=None)

    def validate_coverage(self, school_ids):
        active = [c for c in self.coaches.values() if c.retired_on is None]
        if (len(active) != len(self.active_by_school)
                or set(self.active_by_school) != set(school_ids)
                or any(self.active_by_school.get(c.school_id) != c.coach_id for c in active)):
            raise ValueError("coach assignments must cover every school exactly once")

    def tactics_for(self, school_id: str, on: date) -> CoachTactics:
        """大会年度ではなく試合当日の所属を使う。参照だけで乱数は消費しない。"""
        config = self.tactics_config
        if on < date.fromisoformat(config["first_match_date"]):
            return CoachTactics()
        if school_year_of(on) > self.updated_year:
            raise ValueError("coach personnel not finalized for match date")
        coach = self.for_school(school_id, on=on)
        if coach is None:
            return CoachTactics()
        if not (1 <= coach.pitching_change <= 100 and 1 <= coach.player_selection <= 100):
            raise ValueError("coach tactics abilities must be between 1 and 100")
        def delta(ability, slope, cap):
            return max(-config[cap], min(config[cap],
                       (ability - config["neutral_ability"]) * config[slope]))
        return CoachTactics(
            round(1 - delta(coach.pitching_change, "bf_reduction_per_point",
                            "max_abs_bf_reduction"), 6),
            round(delta(coach.pitching_change, "quick_hook_reduction_per_point",
                        "max_abs_quick_hook_reduction")),
            round(delta(coach.player_selection, "selection_bias_per_point",
                        "max_abs_selection_bias"), 6),
        )

    def practice_for(self, school_id: str, month: date) -> tuple[str | None, int | None, float]:
        """対象月1日の在任者と育成力・練習倍率。育成力は人物の固定能力。

        翌月の成長処理日や現在の所属は使わない。将来、月途中の異動が
        加わっても当月は月初の人物を使い、翌月から交代を反映する。
        """
        first = month.replace(day=1)
        if school_year_of(first) > self.updated_year:
            raise ValueError("coach personnel for practice month is not finalized")
        effect = self.growth_config
        active = first >= date.fromisoformat(effect["first_practice_month"])
        coach = self.for_school(school_id, on=first)
        if coach is None:
            if active:
                raise ValueError("practice month must have an assigned coach")
            return None, None, 1.0
        if not 1 <= coach.development <= 100:
            raise ValueError("coach development must be between one and one hundred")
        delta = ((coach.development - effect["neutral_development"])
                 * effect["multiplier_per_point"]) if active else 0.0
        delta = max(-effect["max_abs_delta"], min(effect["max_abs_delta"], delta))
        return coach.coach_id, coach.development, round(1.0 + delta, 6)

    def retirement_probability(self, coach, year, group):
        s = self.config["retirement"]
        age = year - coach.birth_year
        if age >= s["maximum_age"]:
            return 1.0
        if age < s["minimum_age"]:
            return 0.0
        bonus = s[group]
        tenure = year - coach.appointment_year
        return min(1.0, _band_probability(s["age_probabilities"], age)
                   + min(bonus["maximum_bonus"],
                         max(0, tenure - bonus["tenure_threshold"]) * bonus["per_year"]))

    def finalize_intake(self, year: int) -> bool:
        """4月1日の人事後、新入生生成前に評判と実際の補正値を確定する。"""
        if year <= self.intake_year:
            return False
        if year != self.intake_year + 1 or year != self.updated_year:
            raise ValueError("coach intake must follow annual personnel consecutively")
        effect = self.intake_config
        if year >= effect["first_entry_year"]:
            for cid in sorted(self.active_by_school.values()):
                reputation = self.coaches[cid].reputation
                if not 1 <= reputation <= 100:
                    raise ValueError("coach reputation must be between one and one hundred")
            for cid in sorted(self.active_by_school.values()):
                reputation = self.coaches[cid].reputation
                z = (reputation - effect["neutral_reputation"]) * effect["z_per_reputation_point"]
                z = round(max(-effect["max_abs_z"], min(effect["max_abs_z"], z)), 6)
                previous = self.intake_ratings.get(cid, [])
                if not previous or (previous[-1].reputation, previous[-1].quality_z) != (reputation, z):
                    self.intake_ratings[cid] = [*previous, CoachIntakeRating(year, reputation, z)]
        self.intake_year = year
        return True

    def intake_for(self, school_id: str, entry_year: int) -> tuple[str | None, int | None, float]:
        """入学年4月1日の人物と、その年度に確定した評判・補正。現在値は使わない。"""
        if entry_year < self.intake_config["first_entry_year"]:
            return None, None, 0.0
        if entry_year > self.intake_year:
            raise ValueError(f"coach intake for {entry_year} is not finalized")
        coach = self.for_school(school_id, on=date(entry_year, 4, 1))
        if coach is None:
            return None, None, 0.0
        rows = self.intake_ratings.get(coach.coach_id, [])
        index = bisect_right(rows, entry_year, key=lambda row: row.first_entry_year) - 1
        if index < 0:
            raise ValueError("missing coach intake rating")
        rating = rows[index]
        return coach.coach_id, rating.reputation, rating.quality_z

    def update(self, today: date, repo) -> bool:
        year = today.year
        if (today.month, today.day) != (4, 1) or year <= self.updated_year:
            return False
        if year != self.updated_year + 1:
            raise ValueError("coach personnel years must be processed consecutively")
        self.validate_coverage(repo.schools)
        day = today.isoformat()
        retired, movers = set(), {}
        groups = {}
        for sid, cid in sorted(self.active_by_school.items()):
            coach = self.coaches[cid]
            ownership = repo.ownership_type(sid)
            group = "public" if ownership in self.config["public_ownership_types"] else "private"
            region = (repo.team(sid).prefecture_code, ownership)
            groups[sid] = region
            rng = rng_for(self.seed, f"coaches:personnel:{year}:{cid}")
            if rng.random() < self.retirement_probability(coach, year, group):
                retired.add(cid)
            elif ownership in (*self.config["public_ownership_types"], "private"):
                completed = year - coach.appointment_year
                if rng.random() < _band_probability(self.config["transfer"][group], completed):
                    movers.setdefault(region, []).append(cid)

        # 全異動候補と空席を確定。各県・設置者の二部マッチングで本人の学校を除外する。
        # 並びを正規化してから専用乱数で並べるため、マスターや辞書の処理順に依存しない。
        transfers = {}
        for region, candidates in sorted(movers.items()):
            candidates = sorted(candidates)
            leaving = retired | set(candidates)
            vacancies = sorted(sid for sid, cid in self.active_by_school.items()
                               if cid in leaving and groups[sid] == region)
            rng = rng_for(self.seed, f"coaches:placements:{year}:{region}")
            rng.shuffle(candidates)
            rng.shuffle(vacancies)
            assigned = {}

            def place(cid, seen):
                for sid in vacancies:
                    if sid in seen or sid == self.coaches[cid].school_id:
                        continue
                    seen.add(sid)
                    if sid not in assigned or place(assigned[sid], seen):
                        assigned[sid] = cid
                        return True
                return False

            for cid in candidates:
                place(cid, set())
            transfers.update({cid: sid for sid, cid in assigned.items()})

        updated = dict(self.coaches)
        events = []
        for cid in sorted(retired | set(transfers)):
            coach = self.coaches[cid]
            destination = transfers.get(cid)
            kind = "retirement" if cid in retired else "transfer"
            events.append(CoachEvent(day, kind, cid, coach.school_id, destination,
                                     f"{coach.appointment_year}-04-01"))
            updated[cid] = replace(coach, school_id=destination or "",
                                   appointment_year=year if destination else coach.appointment_year,
                                   retired_on=day if cid in retired else None)
        occupied = {c.school_id for c in updated.values() if c.retired_on is None}
        generation = load_config(self._root / "config/coaches/coach_generation_v1.json",
                                 expected_config_id="coach_generation_v1").payload
        generation = {**generation, "age": self.config["successor_age"]}
        names = name_generator(str(self._root))
        ids = rng_for(self.seed, f"coaches:successor:ids:{year}")
        for sid in sorted(set(repo.schools) - occupied):
            cid = f"COACH-{ids.getrandbits(128):032x}"
            while cid in updated:
                cid = f"COACH-{ids.getrandbits(128):032x}"
            rng = rng_for(self.seed, f"coaches:successor:{year}:{sid}")
            updated[cid] = _draw_coach(repo.team(sid), year, rng, cid, names, generation, initial=False)
            events.append(CoachEvent(day, "appointment", cid, None, sid))
        # 検証してから一括反映する。途中失敗時には人物・履歴・処理済み年度を変更しない。
        active = [c.school_id for c in updated.values() if c.retired_on is None]
        if len(active) != len(set(active)) or set(active) != set(repo.schools):
            raise ValueError("invalid coach personnel placement")
        self.coaches = updated
        self.events.extend(events)
        self.updated_year = year
        self._rebuild_indexes()
        return True

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
            coaches.append(_draw_coach(team, first_year, rng, f"COACH-{ids.getrandbits(128):032x}",
                                       names, config, initial=True))
        return cls(coaches, seed=seed, first_year=first_year, root=root)
