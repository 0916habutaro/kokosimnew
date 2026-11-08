"""部員の人数：新入部員の人数・退部・最低人数・守備位置・ベンチ入り。

値は ``config/players/roster_size_v1.json``（game_definition.md §3.7）。

- 新入部員の期待人数 = scale × exp(学校ごとの集まりやすさ) × 監督 × 都道府県
- 集まりやすさ（対数）= 目安 ＋ 学校ごとのずれ。目安は評判の全国の順位（上位ほど大きく）と
  私立・公立で決まる人数の対数で、新規開始の評判から始め、毎年の評判の変化に少しずつついていく。
  ずれは強豪・私立ほど小さい（``AppealState``。``RosterBook.appeal`` に入れてセーブする）
- 実際の人数は期待人数から負の二項（ガンマ・ポアソン）で引き、強豪・私立ほど期待人数に寄せる
  （推薦・寮で安定して集める）
- 乱数は学校・年度（・部員番号）ごとに分けて引く。名簿をつくる順番で結果が変わらない
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from functools import lru_cache
import json
import math
from pathlib import Path
import random
from statistics import NormalDist
from typing import Callable, Iterable, Sequence

from phase2_engine.randomness import rng_for


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "players" / "roster_size_v1.json"
POSITIONS = ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
MAX_ROSTER_NO = 255


def _zero(_year: int) -> float:
    return 0.0


@dataclass(frozen=True)
class SizeContext:
    """学校の部員の集まり方を決める材料（年度 → 値の関数は入学年度で呼ぶ）。

    ``reputation_z`` は入部品質の学校成分（評判の全国の順位を正規分布の z にしたもの）。
    ``appeal`` を省くと、新規開始の集まりやすさ（乱数の種・学校・評判から）を使う。"""

    ownership: str = ""
    prefecture_code: str = ""
    reputation_z: Callable[[int], float] = _zero
    coach_z: Callable[[int], float] = _zero
    appeal: Callable[[int], float] | None = None


@dataclass(frozen=True)
class AppealState:
    """学校の部員の集まりやすさ（対数）：評判から決まる目安と、学校ごとのずれ。"""

    year: int
    anchor: float
    deviation: float

    @property
    def value(self) -> float:
        return self.anchor + self.deviation


def interpolate(points: Sequence[Sequence[float]], x: float) -> float:
    """[(x, y), ...]（x の小さい順）を直線でつないだ値。両端の外は端の値。"""
    xs = [float(px) for px, _ in points]
    if x <= xs[0]:
        return float(points[0][1])
    if x >= xs[-1]:
        return float(points[-1][1])
    i = bisect_right(xs, x)
    (x0, y0), (x1, y1) = points[i - 1], points[i]
    return float(y0) + (float(y1) - float(y0)) * (x - float(x0)) / (float(x1) - float(x0))


def ownership_group(ownership: str) -> str:
    """私立とそれ以外（県立・市立・国立などは公立として扱う）。"""
    return "private" if ownership == "private" else "public"


@dataclass
class IntakePlan:
    """1つの学校・年度の新入部員の人数と、最低人数に当たったか。"""

    count: int
    drawn: int
    floor_hit: bool = False
    expected: float = 0.0
    positions: list[str] = field(default_factory=list)


def poisson(rng: random.Random, mean: float) -> int:
    """平均 ``mean`` の Poisson 乱数（大きい平均でも下にあふれないように分けて引く）。"""
    count = 0
    while mean > 30.0:
        count += _poisson_small(rng, 30.0)
        mean -= 30.0
    return count + _poisson_small(rng, mean)


def _poisson_small(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    limit = math.exp(-mean)
    count, product = 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


class RosterSizeModel:
    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else json.loads(
            CONFIG_PATH.read_text(encoding="utf-8"))
        shares = self.config["positions"]
        total = sum(float(shares[p]) for p in POSITIONS)
        if abs(total - 1.0) > 1e-9:
            raise ValueError("roster_size_v1: position shares must sum to 1")
        self.namespaces = self.config["rng_namespaces"]
        # かさ上げするなら試合に要る9人以上（0 はかさ上げしない。連合チームで補う）
        players = int(self.config["minimum"]["players"])
        if players and players < 9:
            raise ValueError("roster_size_v1: minimum players must be 0 or at least 9")

    # ---- 学校ごとの集まりやすさ・都道府県 ----

    def share(self, reputation_z: float) -> float:
        """評判の全国の順位（下から。0〜1）。z は順位を正規分布に直したもの。"""
        return NormalDist().cdf(reputation_z)

    def _by_share(self, table: dict, ownership: str, share: float) -> float:
        return interpolate(table[ownership_group(ownership)], share)

    def target_appeal(self, ownership: str, reputation_z: float) -> float:
        """評判の順位と私立・公立から決まる集まりやすさの目安（新入部員の人数の対数）。"""
        rule = self.config["freshmen"]
        return math.log(self._by_share(rule["by_share"], ownership, self.share(reputation_z)))

    def _deviation_stddev(self, ownership: str, reputation_z: float) -> float:
        return self._by_share(self.config["school_appeal"]["deviation_stddev"], ownership,
                              self.share(reputation_z))

    def initial_appeal_state(self, seed: int, school_id: str, year: int, *,
                             ownership: str, reputation_z: float) -> AppealState:
        """新規開始：目安は新規開始の評判から、ずれは学校ごとの乱数（強豪・私立ほど小さい）。"""
        rng = rng_for(seed, self.namespaces["appeal"].format(year=year, school_id=school_id))
        deviation = rng.gauss(0.0, self._deviation_stddev(ownership, reputation_z))
        return AppealState(year, round(self.target_appeal(ownership, reputation_z), 6),
                           self._clip_appeal(deviation))

    def next_appeal_state(self, seed: int, school_id: str, year: int, previous: AppealState, *,
                          ownership: str, reputation_z: float) -> AppealState:
        """``year`` の集まりやすさ。目安はその年の評判の目安へ ``follow`` の割合だけ近づき、
        ずれは ``carry`` を掛けて小さな乱数を足す（広がりはその学校のずれの大きさを保つ）。"""
        rule = self.config["school_appeal"]
        follow, carry = float(rule["follow"]), float(rule["carry"])
        target = self.target_appeal(ownership, reputation_z)
        anchor = previous.anchor + (target - previous.anchor) * follow
        rng = rng_for(seed, self.namespaces["appeal"].format(year=year, school_id=school_id))
        step = rng.gauss(0.0, self._deviation_stddev(ownership, reputation_z)
                         * math.sqrt(max(0.0, 1.0 - carry * carry)))
        return AppealState(year, round(anchor, 6), self._clip_appeal(previous.deviation * carry + step))

    def _clip_appeal(self, value: float) -> float:
        clip = float(self.config["school_appeal"]["clip"])
        return round(max(-clip, min(clip, value)), 6)

    def prefecture_log(self, seed: int, prefecture_code: str) -> float:
        if not prefecture_code:
            return 0.0
        return _prefecture_log(seed, prefecture_code, float(self.config["prefecture"]["stddev"]),
                               self.namespaces["prefecture"])

    # ---- 新入部員の人数 ----

    def expected_freshmen(
        self, *, appeal: float, coach_z: float = 0.0, prefecture_log: float = 0.0,
    ) -> float:
        rule = self.config["freshmen"]
        return (
            float(rule["scale"])
            * math.exp(appeal)
            * math.exp(float(rule["coach_per_z"]) * coach_z)
            * math.exp(prefecture_log)
        )

    def stability(self, ownership: str, reputation_z: float) -> float:
        """期待人数に寄せる割合（0〜1。強豪・私立ほど大きい）。"""
        return self._by_share(self.config["freshmen"]["stability"], ownership,
                              self.share(reputation_z))

    def max_freshmen(self, ownership: str) -> int:
        return int(self.config["freshmen"]["max_freshmen"][ownership_group(ownership)])

    def draw_freshmen(self, rng: random.Random, mean: float, *, stability: float = 0.0,
                      maximum: int | None = None) -> int:
        """負の二項（ガンマで平均を揺らしてから Poisson）を、``stability`` の割合だけ期待人数に
        寄せる（ばらつきが 1 − stability 倍になる）。``maximum`` まで。"""
        rule = self.config["freshmen"]
        shape = float(rule["dispersion"])
        rate = rng.gammavariate(shape, mean / shape) if mean > 0 else 0.0
        drawn = poisson(rng, rate)
        count = int(round(stability * mean + (1.0 - stability) * drawn))
        limit = maximum if maximum is not None else max(rule["max_freshmen"].values())
        return max(0, min(int(limit), count))

    def plan_freshmen(
        self, seed: int, school_id: str, year: int, context: SizeContext, *,
        second_years: Sequence[str] = (), enforce_minimum: bool = True,
    ) -> IntakePlan:
        """``year`` の4月の新入部員の人数と守備位置。

        ``second_years`` は新2年生の守備位置（4月の新チームの残り）。``enforce_minimum``
        なら、新チーム（新1年生＋新2年生）が最低人数・投手・捕手にそろうまで増やす。"""
        reputation_z = context.reputation_z(year)
        appeal = (context.appeal(year) if context.appeal is not None
                  else self.initial_appeal_state(seed, school_id, year, ownership=context.ownership,
                                                 reputation_z=reputation_z).value)
        mean = self.expected_freshmen(
            appeal=appeal, coach_z=context.coach_z(year),
            prefecture_log=self.prefecture_log(seed, context.prefecture_code),
        )
        rng = rng_for(seed, self.namespaces["count"].format(year=year, school_id=school_id))
        drawn = self.draw_freshmen(rng, mean, stability=self.stability(context.ownership, reputation_z),
                                   maximum=self.max_freshmen(context.ownership))
        count = drawn
        if enforce_minimum:
            minimum = self.config["minimum"]
            need_p = max(0, int(minimum["pitchers"]) - sum(p == "P" for p in second_years))
            need_c = max(0, int(minimum["catchers"]) - sum(p == "C" for p in second_years))
            players = int(minimum["players"])
            if players:
                count = max(count, players - len(second_years), need_p + need_c)
        return IntakePlan(count=count, drawn=drawn, floor_hit=count > drawn, expected=mean)

    def positions(
        self, seed: int, school_id: str, year: int, roster_nos: Sequence[int], *,
        second_years: Sequence[str] = (), enforce_minimum: bool = True,
    ) -> list[str]:
        """新入部員の守備位置（部員番号ごとの乱数）。新チームに投手・捕手が足りなければ、
        番号の大きい新入部員から投手・捕手に替える。"""
        shares = self.config["positions"]
        out = []
        for roster_no in roster_nos:
            roll = rng_for(seed, self.namespaces["position"].format(
                year=year, school_id=school_id, roster_no=roster_no)).random()
            chosen = POSITIONS[-1]
            for position in POSITIONS:
                share = float(shares[position])
                if roll < share:
                    chosen = position
                    break
                roll -= share
            out.append(chosen)
        if enforce_minimum:
            minimum = self.config["minimum"]
            floors = {"P": int(minimum["pitchers"]), "C": int(minimum["catchers"])}

            def count(position):
                return sum(p == position for p in (*second_years, *out))

            for position in ("P", "C"):
                short = floors[position] - count(position)
                for index in reversed(range(len(out))):
                    if short <= 0:
                        break
                    current = out[index]
                    # 投手・捕手は最低人数を超えている分だけ振り替えてよい
                    if current == position or (current in floors
                                                and count(current) <= floors[current]):
                        continue
                    out[index] = position
                    short -= 1
        return out

    # ---- 退部 ----

    def withdrawal_chance(self, reputation_z: float) -> float:
        rule = self.config["withdrawal"]
        return min(float(rule["max"]),
                   float(rule["base"]) * math.exp(-float(rule["per_z"]) * reputation_z))

    def withdraws(self, seed: int, school_id: str, year: int, entry_year: int,
                  roster_no: int, reputation_z: float) -> bool:
        """``year`` の4月1日に進級する選手がやめるか。"""
        rng = rng_for(seed, self.namespaces["withdrawal"].format(
            year=year, school_id=school_id, entry_year=entry_year, roster_no=roster_no))
        return rng.random() < self.withdrawal_chance(reputation_z)


def free_numbers(taken: Iterable[int], count: int) -> list[int]:
    """使われていない部員番号を小さい順に ``count`` 個。"""
    used = set(taken)
    out = []
    number = 1
    while len(out) < count:
        if number > MAX_ROSTER_NO:
            raise ValueError("roster number overflow")
        if number not in used:
            out.append(number)
        number += 1
    return out


@lru_cache(maxsize=None)
def _prefecture_log(seed: int, prefecture_code: str, stddev: float, namespace: str) -> float:
    return rng_for(seed, namespace.format(prefecture_code=prefecture_code)).gauss(0.0, stddev)


@lru_cache(maxsize=1)
def roster_size_model() -> RosterSizeModel:
    return RosterSizeModel()


# ---- ベンチ入り ----

def bench_score(snapshot, config: dict | None = None) -> float:
    """ベンチ入りの評価（投手は投手の能力、野手は打撃・守備の能力の重み付き平均）。"""
    rule = (config or roster_size_model().config)["bench"]
    if snapshot.primary_position == "P":
        scale = rule["velocity_scale"]
        total = 0.0
        for name, weight in rule["pitcher"].items():
            value = getattr(snapshot, name, None) or 0
            if name == "velocity_kmh":
                value = (value - float(scale["low"])) * float(scale["per_kmh"]) if value else 0.0
            total += float(weight) * float(value)
    else:
        total = sum(float(weight) * float(getattr(snapshot, name, None) or 0)
                    for name, weight in rule["fielder"].items())
    return total + float(rule["grade_bonus"]) * snapshot.academic_year


def select_bench(players: Sequence, score_of: Callable[[object], float],
                 config: dict | None = None) -> tuple:
    """大会のベンチ入り（``size`` 人まで。名簿の順番を保つ）。

    投手・捕手を先に最低人数まで入れ、残りを評価の高い順に入れる。同じ評価は選手IDの順。"""
    rule = (config or roster_size_model().config)["bench"]
    size = int(rule["size"])
    if len(players) <= size:
        return tuple(players)
    scores = {p.player_id: score_of(p) for p in players}

    def ranked(pool):
        return sorted(pool, key=lambda p: (-scores[p.player_id], p.player_id))

    chosen: list = []
    for position, key in (("P", "min_pitchers"), ("C", "min_catchers")):
        chosen.extend(ranked([p for p in players if p.primary_position == position])[:int(rule[key])])
    picked = {p.player_id for p in chosen}
    rest = ranked([p for p in players if p.player_id not in picked])
    chosen.extend(rest[:max(0, size - len(chosen))])
    keep = {p.player_id for p in chosen[:size]}
    return tuple(p for p in players if p.player_id in keep)
