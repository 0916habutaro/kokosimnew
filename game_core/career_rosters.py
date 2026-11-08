"""年度の切り替え（4月1日）の名簿：3年生の卒業・退部・進級と新入部員。

進級した選手は前の年度の名簿をそのまま引き継ぐ（前の年度の名簿を渡す。翌年度の乱数の種から
作り直さない）。新入部員の人数・守備位置・退部は ``roster_size.py``。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from phase2_engine.models import Team
from phase2_engine.randomness import rng_for

from .players import (
    GRADES, Player, PlayerRosterGenerator, SchoolRoster, draw_hands,
    _position_group, draw_identity, validate_school_roster,
)
from .roster_size import SizeContext, free_numbers, roster_size_model, standalone_floor_players


@dataclass(frozen=True)
class CareerRosterTransition:
    previous_year: int
    new_year: int
    school_id: str
    graduated: tuple[Player, ...]
    returning: tuple[Player, ...]
    newcomers: tuple[Player, ...]
    roster: SchoolRoster
    withdrawn: tuple[Player, ...] = ()

    def summary(self) -> dict:
        return {
            "previous_year": self.previous_year,
            "new_year": self.new_year,
            "school_id": self.school_id,
            "graduated_player_ids": [p.player_id for p in self.graduated],
            "returning_player_ids": [p.player_id for p in self.returning],
            "withdrawn_player_ids": [p.player_id for p in self.withdrawn],
            "newcomer_player_ids": [p.player_id for p in self.newcomers],
            "cohort_counts": {
                grade: sum(p.academic_year == grade for p in self.roster.players)
                for grade in GRADES
            },
            "floor_hit": self.roster.floor_hit,
            "roster_count": len(self.roster.players),
        }


def _newcomer_id(seed: int, year: int, school_id: str, slot: int) -> str:
    payload = (
        f"{seed}:player_career_newcomer_v1:{year}:{school_id}:{slot}"
    ).encode("utf-8")
    return "PLY" + hashlib.sha256(payload).hexdigest()[:20].upper()


def advance_school_roster(
    previous: SchoolRoster,
    team: Team,
    *,
    next_year: int,
    career_seed: int,
    generator: PlayerRosterGenerator | None = None,
    size: SizeContext | None = None,
) -> CareerRosterTransition:
    """3年生は卒業、1・2年生は退部を引いてから進級し、新入部員を入れる。

    進級する選手の選手ID・名前・出身・守備位置・投打・部員番号は変えない。新入部員の人数は
    卒業した人数と関係なく ``roster_size.py`` で決め、空いている部員番号を小さい順に使う。
    """
    validate_school_roster(previous)
    if next_year != previous.reference_year + 1:
        raise ValueError("roster transition requires an adjacent year")
    if not isinstance(career_seed, int) or isinstance(career_seed, bool):
        raise ValueError("career_seed must be integer")
    if previous.rng_seed != career_seed:
        raise ValueError("career seed differs from existing roster")
    if team.school_id != previous.school_id or team.program_id != previous.program_id:
        raise ValueError("roster transition team identity mismatch")
    if team.display_name != previous.school_name:
        raise ValueError("roster transition school name mismatch")

    generator = generator or PlayerRosterGenerator()
    model = roster_size_model()
    size = size or SizeContext(prefecture_code=team.prefecture_code,
                               floor_players=standalone_floor_players())
    if size.appeal is None:
        first = model.initial_appeal_state(
            career_seed, team.school_id, next_year, ownership=size.ownership,
            reputation_z=size.reputation_z(next_year)).value
        size = replace(size, appeal=lambda _year: first)
    graduates = tuple(
        p for p in previous.players if p.academic_year == 3
    )
    reputation_z = size.reputation_z(next_year)
    withdrawn = tuple(
        p for p in previous.players
        if p.academic_year in (1, 2) and model.withdraws(
            career_seed, team.school_id, next_year, p.entry_year, p.roster_no, reputation_z)
    )
    gone = {p.player_id for p in withdrawn}
    continued = tuple(
        replace(p, academic_year=p.academic_year + 1)
        for p in previous.players
        if p.academic_year in (1, 2) and p.player_id not in gone
    )
    second = [p.primary_position for p in continued if p.academic_year == 2]
    plan = model.plan_freshmen(career_seed, team.school_id, next_year, size,
                               second_years=second)
    numbers = free_numbers((p.roster_no for p in continued), plan.count)
    positions = model.positions(career_seed, team.school_id, next_year, numbers,
                                second_years=second)
    newcomers: list[Player] = []
    # 同じ学校の中で同姓同名にならないように（残る部員と新入生どうし）
    taken = {p.display_name for p in continued}
    for slot, pos in zip(numbers, positions):
        rng = rng_for(
            career_seed,
            f"career_roster_v1:{next_year}:{team.school_id}:slot:{slot}",
        )
        identity = draw_identity(
            generator.name_provider, team, career_seed,
            rng_for(
                career_seed,
                f"player_names_v1:career:{next_year}:{team.school_id}:slot:{slot}",
            ),
            taken,
        )
        taken.add(identity.display_name)
        throws, bats = draw_hands(pos, rng)
        newcomers.append(Player(
            player_id=_newcomer_id(
                career_seed, next_year, team.school_id, slot
            ),
            school_id=team.school_id,
            program_id=team.program_id,
            display_name=identity.display_name,
            name_source=identity.name_source,
            hometown_prefecture_code=identity.hometown_prefecture_code,
            academic_year=1,
            entry_year=next_year,
            roster_no=slot,
            primary_position=pos,
            position_group=_position_group(pos),
            bats=bats,
            throws=throws,
            roster_status="active_core",
            generation_seed=career_seed,
        ))

    sorted_players = sorted(
        [*continued, *newcomers], key=lambda p: p.roster_no
    )
    old_ids = {p.player_id for p in previous.players}
    fresh_ids = {p.player_id for p in newcomers}
    if fresh_ids & old_ids or len(fresh_ids) != len(newcomers):
        raise ValueError("career player identity collision")
    next_roster = SchoolRoster(
        reference_year=next_year,
        school_id=previous.school_id,
        program_id=previous.program_id,
        school_name=previous.school_name,
        rng_seed=career_seed,
        players=sorted_players,
        cohort_policy="career_v1",
        floor_hit=plan.floor_hit,
    )
    validate_school_roster(next_roster)
    return CareerRosterTransition(
        previous_year=previous.reference_year,
        new_year=next_year,
        school_id=team.school_id,
        graduated=graduates,
        returning=continued,
        newcomers=tuple(newcomers),
        roster=next_roster,
        withdrawn=withdrawn,
    )


def advance_rosters(
    previous_rosters,
    repo,
    *,
    next_year: int,
    career_seed: int,
    generator: PlayerRosterGenerator | None = None,
):
    """Stream school transitions without loading all 3,000+ rosters at once."""
    for roster in previous_rosters:
        team = repo.team(roster.school_id)
        yield advance_school_roster(
            roster, team, next_year=next_year,
            career_seed=career_seed, generator=generator,
            size=SizeContext(
                ownership=getattr(repo, "ownership_type", lambda _sid: "")(roster.school_id),
                prefecture_code=team.prefecture_code,
                floor_players=standalone_floor_players()),
        )
