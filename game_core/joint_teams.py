"""連合チーム：部員の足りない学校どうしが大会ごとに組むチーム（game_definition.md §3.8）。

値と規則は ``config/players/joint_teams_v1.json``。

- その大会の開始日の出場できる部員が ``eligible_max_players`` 人以下の学校が組める（実在の規則）
- 相手は同じ大会の出場校（同じ都道府県・同じ代表区分）から、同じ支部・地区、同じ市町村の順に選ぶ
- 合わせて ``team_min_players`` 人に届けば1チーム。届かなければ、その大会に出ない
- 連合は代表校の枠で組み合わせ・日程・勝敗を持つ（``apply_to_annual`` がほかの学校を出場校から外す）

ここは純粋な計算だけを持つ。名簿・大会への組み込みは ``live_members.UnionPlanner``。
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from functools import lru_cache
import json
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from phase2_engine.randomness import rng_for


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "players" / "joint_teams_v1.json"


@lru_cache(maxsize=1)
def joint_team_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class JointTeam:
    """連合チーム。``schools`` は代表校が先頭。"""

    lead: str
    schools: tuple[str, ...]

    @property
    def partners(self) -> tuple[str, ...]:
        return self.schools[1:]


@dataclass(frozen=True)
class UnionPlan:
    """1つの大会の連合チームと、出ない学校。"""

    teams: tuple[JointTeam, ...] = ()
    absent: tuple[str, ...] = ()

    def removed(self) -> set[str]:
        """出場校の並びから外す学校（連合の代表校以外と、出ない学校）。"""
        return {s for team in self.teams for s in team.partners} | set(self.absent)

    def team_of(self, lead: str) -> JointTeam | None:
        return next((team for team in self.teams if team.lead == lead), None)

    def to_dict(self) -> dict:
        return {"teams": [list(team.schools) for team in self.teams], "absent": list(self.absent)}


def form_unions(
    competition_id: str,
    entrants: Sequence[str],
    players: Mapping[str, int],
    *,
    seed: int,
    branch_of: Callable[[str], str] = lambda _sid: "",
    municipality_of: Callable[[str], str] = lambda _sid: "",
    preferred: Iterable[str] = (),
    config: dict | None = None,
) -> UnionPlan:
    """``entrants`` の中で連合チームを組む。``players`` は学校 → その大会に出られる部員の数。

    ``preferred``（シード・予選免除のある学校）は連合の代表校にする。乱数はこの大会と学校
    ごとに分けて引く（同じ距離の相手が何校もあるときの順番だけに使う）。"""
    rule = config or joint_team_config()
    limit = int(rule["eligible_max_players"])
    need = int(rule["team_min_players"])
    target = max(need, int(rule.get("target_players", need)))
    most = int(rule["max_schools"])
    preferred = set(preferred)
    absent = [s for s in entrants if players.get(s, 0) <= 0]
    pool = sorted(
        (s for s in entrants if 0 < players.get(s, 0) <= limit),
        key=lambda s: (players[s], s),
    )

    def order(school):
        return rng_for(seed, rule["rng_namespace"].format(
            competition_id=competition_id, school_id=school)).random()

    def closeness(base, other):
        branch = branch_of(base)
        town = municipality_of(base)
        return (
            bool(branch) and branch_of(other) == branch,
            bool(town) and municipality_of(other) == town,
            players[other],
            -order(other),
        )

    groups: list[list[str]] = []
    leftover: list[str] = []
    while pool:
        first = pool.pop(0)
        group = [first]
        total = players[first]
        # 試合に出られる人数（need）だけでなく、交代のできる人数（target）まで集める
        while total < target and len(group) < most and pool:
            partner = max(pool, key=lambda other: closeness(first, other))
            pool.remove(partner)
            group.append(partner)
            total += players[partner]
        if total < need:
            leftover.extend(group)
        else:
            groups.append(group)
    # 9人に届かなかった学校は、まだ入れる近い連合に加わる。入れなければ出ない
    for school in sorted(leftover, key=lambda s: (-players[s], s)):
        room = [group for group in groups if len(group) < most]
        if not room:
            absent.append(school)
            continue
        max(room, key=lambda group: closeness(school, group[0])).append(school)
    teams = []
    for group in groups:
        lead = min(group, key=lambda s: (s not in preferred, -players[s], s))
        others = sorted((s for s in group if s != lead), key=lambda s: (-players[s], s))
        teams.append(JointTeam(lead, (lead, *others)))
    return UnionPlan(tuple(sorted(teams, key=lambda team: team.lead)), tuple(sorted(absent)))


def apply_to_annual(annual, plan: UnionPlan):
    """大会の入力（``AnnualCompetitionInput``）から、連合の代表校以外と出ない学校を外す。
    代表校は元の学校の枠（組・シード・予選免除）のまま出る。"""
    removed = plan.removed()
    if not removed:
        return annual
    changes = {}
    for item in fields(annual):
        value = getattr(annual, item.name)
        if item.name == "main_bracket_slots":
            changes[item.name] = ["" if s in removed else s for s in value]
        elif item.name == "main_match_winner_overrides":
            changes[item.name] = {k: v for k, v in value.items() if v not in removed}
        elif isinstance(value, list) and all(isinstance(s, str) for s in value):
            changes[item.name] = [s for s in value if s not in removed]
        elif isinstance(value, dict) and value and all(isinstance(v, list) for v in value.values()):
            changes[item.name] = {
                key: ([[s for s in pool if s not in removed] for pool in group]
                      if group and isinstance(group[0], list)
                      else [s for s in group if s not in removed])
                for key, group in value.items()
            }
    return replace(annual, **changes)


def team_name(team: JointTeam, name_of: Callable[[str], str]) -> str:
    """「代表校・ほかの学校」。"""
    return "・".join(name_of(s) for s in team.schools)


def union_teams(season, competition_id: str) -> tuple[JointTeam, ...]:
    """その大会に出た連合チーム（連合を組んだ大会と、そこから進んだ同じつながりの大会）。
    ``season`` は進行中・閉じた年度の状態（``union_plans`` と ``repo`` を持つ）。"""
    plans = getattr(season, "union_plans", None) or {}
    if competition_id in plans:
        return plans[competition_id].teams
    chains = joint_team_config()["chains"]
    competitions = season.repo.competitions

    def type_of(cid):
        return competitions.get(cid, {}).get("competition_type", "")

    chain = chains.get(type_of(competition_id))
    if chain is None:
        return ()
    return tuple(team for cid, plan in plans.items() if chains.get(type_of(cid)) == chain
                 for team in plan.teams)
