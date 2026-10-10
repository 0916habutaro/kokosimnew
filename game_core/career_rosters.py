"""Year-to-year continuity for the 20-player structural school roster.

This intentionally leaves the existing initial-season generator unchanged.
A later live-year scheduler must supply the previous saved roster rather
than rebuilding it from next year's random seed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from phase2_engine.models import Team
from phase2_engine.randomness import rng_for

from .players import (
    CORE_ROSTER_SIZE, Player, PlayerRosterGenerator, SchoolRoster,
    _position_group, validate_school_roster,
)


@dataclass(frozen=True)
class CareerRosterTransition:
    previous_year: int
    new_year: int
    school_id: str
    graduated: tuple[Player, ...]
    returning: tuple[Player, ...]
    newcomers: tuple[Player, ...]
    roster: SchoolRoster

    def summary(self) -> dict:
        return {
            "previous_year": self.previous_year,
            "new_year": self.new_year,
            "school_id": self.school_id,
            "graduated_player_ids": [p.player_id for p in self.graduated],
            "returning_player_ids": [p.player_id for p in self.returning],
            "newcomer_player_ids": [p.player_id for p in self.newcomers],
            "cohort_counts": {
                grade: sum(p.academic_year == grade for p in self.roster.players)
                for grade in (1, 2, 3)
            },
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
) -> CareerRosterTransition:
    """Promote all survivors and recruit one freshman per graduation.

    A returning player's player_id, school, entry_year, identity, position,
    handedness and jersey slot remain untouched. Newcomers fill precisely
    the graduated position slots; 20-player positional quotas remain stable.

    The initial 2026 grade quotas are (5,7,8), so the actual next-year
    (freshmen, sophomores, juniors) counts are (8,5,7), *not* (5,7,8).
    Silently replacing returnees to force initial quotas is forbidden.
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
    graduates = tuple(
        p for p in previous.players if p.academic_year == 3
    )
    continued = tuple(
        replace(p, academic_year=p.academic_year + 1)
        for p in previous.players if p.academic_year in (1, 2)
    )
    newcomers: list[Player] = []
    for former in graduates:
        slot = former.roster_no
        pos = former.primary_position
        rng = rng_for(
            career_seed,
            f"career_roster_v1:{next_year}:{team.school_id}:slot:{slot}",
        )
        name, source = generator.name_provider(
            team, next_year, slot, rng
        )
        if not isinstance(name, str) or not name or not source:
            raise ValueError("newcomer name provider returned empty identity")
        throws_left = 0.20 if pos == "P" else 0.10
        throws = "L" if rng.random() < throws_left else "R"
        roll = rng.random()
        bats = "S" if roll < 0.04 else ("L" if roll < 0.29 else "R")
        newcomers.append(Player(
            player_id=_newcomer_id(
                career_seed, next_year, team.school_id, slot
            ),
            school_id=team.school_id,
            program_id=team.program_id,
            display_name=name,
            name_source=source,
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
    if len(sorted_players) != CORE_ROSTER_SIZE:
        raise ValueError("career roster size changed")
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
    )
    validate_school_roster(next_roster)
    # An extra lineage check ensures not even a subtle survivor mutation
    # is hidden behind a valid 20-person/position-count snapshot.
    after_by_id = {p.player_id: p for p in next_roster.players}
    for p in previous.players:
        if p.academic_year in (1, 2):
            if after_by_id.get(p.player_id) != replace(
                p, academic_year=p.academic_year + 1
            ):
                raise ValueError("returning player's identity was modified")
        elif p.player_id in after_by_id:
            raise ValueError("graduated player unexpectedly returned")
    return CareerRosterTransition(
        previous_year=previous.reference_year,
        new_year=next_year,
        school_id=team.school_id,
        graduated=graduates,
        returning=continued,
        newcomers=tuple(newcomers),
        roster=next_roster,
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
        yield advance_school_roster(
            roster, repo.team(roster.school_id), next_year=next_year,
            career_seed=career_seed, generator=generator,
        )
