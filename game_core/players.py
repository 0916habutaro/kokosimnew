from __future__ import annotations

import csv
import hashlib
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

from phase2_engine.models import Team
from phase2_engine.randomness import rng_for
from phase2_engine.repository import DataRepository


CORE_ROSTER_SIZE = 20
GRADE_COUNTS = {1: 5, 2: 7, 3: 8}
POSITION_SLOTS = (
    "P", "P", "P", "P", "P",
    "C", "C",
    "1B",
    "2B", "2B",
    "3B", "3B",
    "SS", "SS",
    "LF", "LF",
    "CF", "CF",
    "RF", "RF",
)


@dataclass(frozen=True)
class Player:
    player_id: str
    school_id: str
    program_id: str
    display_name: str
    name_source: str
    academic_year: int
    entry_year: int
    roster_no: int
    primary_position: str
    position_group: str
    bats: str
    throws: str
    roster_status: str
    generation_seed: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SchoolRoster:
    reference_year: int
    school_id: str
    program_id: str
    school_name: str
    rng_seed: int
    players: list[Player] = field(default_factory=list)
    # Initial fixed grade quotas only apply to the 2026 bootstrap cohort.
    # Returning players keep their identity in later years.
    cohort_policy: str = "initial_v1"

    def to_dict(self) -> dict:
        return {
            "reference_year": self.reference_year,
            "school_id": self.school_id,
            "program_id": self.program_id,
            "school_name": self.school_name,
            "rng_seed": self.rng_seed,
            "player_count": len(self.players),
            "players": [player.to_dict() for player in self.players],
            **({"cohort_policy": self.cohort_policy}
               if self.cohort_policy != "initial_v1" else {}),
        }


NameProvider = Callable[[Team, int, int, random.Random], tuple[str, str]]


def _position_group(position: str) -> str:
    if position == "P":
        return "pitcher"
    if position == "C":
        return "catcher"
    if position in {"1B", "2B", "3B", "SS"}:
        return "infielder"
    if position in {"LF", "CF", "RF"}:
        return "outfielder"
    raise ValueError(f"unknown position: {position}")


def _placeholder_name(
    team: Team,
    reference_year: int,
    roster_no: int,
    rng: random.Random,
) -> tuple[str, str]:
    del team, reference_year, rng
    return f"仮選手{roster_no:02d}", "placeholder_v1"


def _player_id(
    base_seed: int,
    reference_year: int,
    school_id: str,
    roster_no: int,
) -> str:
    payload = (
        f"{base_seed}:player_v1:{reference_year}:"
        f"{school_id}:{roster_no}"
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:20].upper()
    return f"PLY{digest}"


class PlayerRosterGenerator:
    """Generate a deterministic 20-player structural roster per school.

    Stage 13A intentionally models identity/affiliation only.  Player ability,
    batting order, pitching usage and statistics are later-stage concerns.
    """

    def __init__(
        self,
        *,
        name_provider: NameProvider | None = None,
    ):
        self.name_provider = name_provider or _placeholder_name
        self._validate_contract()

    @staticmethod
    def _validate_contract() -> None:
        if sum(GRADE_COUNTS.values()) != CORE_ROSTER_SIZE:
            raise ValueError("grade counts must sum to CORE_ROSTER_SIZE")
        if len(POSITION_SLOTS) != CORE_ROSTER_SIZE:
            raise ValueError("position slots must match CORE_ROSTER_SIZE")
        if set(GRADE_COUNTS) != {1, 2, 3}:
            raise ValueError("grade counts must contain years 1, 2 and 3")

    def generate_school(
        self,
        team: Team,
        reference_year: int,
        base_seed: int,
    ) -> SchoolRoster:
        if reference_year <= 0:
            raise ValueError("reference_year must be positive")
        if not team.school_id:
            raise ValueError("team.school_id is required")

        grade_slots = [
            grade
            for grade, count in sorted(GRADE_COUNTS.items())
            for _ in range(count)
        ]
        grade_rng = rng_for(
            base_seed,
            f"player_roster_v1:{reference_year}:{team.school_id}:grades",
        )
        grade_rng.shuffle(grade_slots)

        positions = list(POSITION_SLOTS)
        position_rng = rng_for(
            base_seed,
            f"player_roster_v1:{reference_year}:{team.school_id}:positions",
        )
        position_rng.shuffle(positions)

        players: list[Player] = []
        for index in range(CORE_ROSTER_SIZE):
            roster_no = index + 1
            academic_year = grade_slots[index]
            position = positions[index]
            player_rng = rng_for(
                base_seed,
                (
                    f"player_roster_v1:{reference_year}:"
                    f"{team.school_id}:player:{roster_no}"
                ),
            )

            display_name, name_source = self.name_provider(
                team,
                reference_year,
                roster_no,
                player_rng,
            )
            if not display_name:
                raise ValueError(
                    f"{team.school_id}/{roster_no}: display_name is required"
                )
            if not name_source:
                raise ValueError(
                    f"{team.school_id}/{roster_no}: name_source is required"
                )

            throws_left_probability = 0.20 if position == "P" else 0.10
            throws = (
                "L"
                if player_rng.random() < throws_left_probability
                else "R"
            )
            bat_roll = player_rng.random()
            bats = "S" if bat_roll < 0.04 else ("L" if bat_roll < 0.29 else "R")

            players.append(
                Player(
                    player_id=_player_id(
                        base_seed,
                        reference_year,
                        team.school_id,
                        roster_no,
                    ),
                    school_id=team.school_id,
                    program_id=team.program_id,
                    display_name=display_name,
                    name_source=name_source,
                    academic_year=academic_year,
                    entry_year=reference_year - academic_year + 1,
                    roster_no=roster_no,
                    primary_position=position,
                    position_group=_position_group(position),
                    bats=bats,
                    throws=throws,
                    roster_status="active_core",
                    generation_seed=base_seed,
                )
            )

        roster = SchoolRoster(
            reference_year=reference_year,
            school_id=team.school_id,
            program_id=team.program_id,
            school_name=team.display_name,
            rng_seed=base_seed,
            players=players,
        )
        validate_school_roster(roster)
        return roster

    def generate_for_school_id(
        self,
        repo: DataRepository,
        school_id: str,
        reference_year: int,
        base_seed: int,
    ) -> SchoolRoster:
        return self.generate_school(
            repo.team(school_id),
            reference_year,
            base_seed,
        )

    def iter_all_rosters(
        self,
        repo: DataRepository,
        reference_year: int,
        base_seed: int,
    ) -> Iterator[SchoolRoster]:
        for school_id in sorted(repo.schools):
            if school_id not in repo.school_to_program:
                continue
            yield self.generate_for_school_id(
                repo,
                school_id,
                reference_year,
                base_seed,
            )


def validate_school_roster(roster: SchoolRoster) -> None:
    if len(roster.players) != CORE_ROSTER_SIZE:
        raise ValueError(
            f"{roster.school_id}: expected {CORE_ROSTER_SIZE} players, "
            f"got {len(roster.players)}"
        )

    player_ids = [player.player_id for player in roster.players]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError(f"{roster.school_id}: duplicate player_id")

    roster_numbers = [player.roster_no for player in roster.players]
    if sorted(roster_numbers) != list(range(1, CORE_ROSTER_SIZE + 1)):
        raise ValueError(f"{roster.school_id}: roster_no must be 1..20")

    for player in roster.players:
        if player.school_id != roster.school_id:
            raise ValueError(f"{player.player_id}: school_id mismatch")
        if player.program_id != roster.program_id:
            raise ValueError(f"{player.player_id}: program_id mismatch")
        if player.entry_year != roster.reference_year - player.academic_year + 1:
            raise ValueError(f"{player.player_id}: entry_year mismatch")
        if player.position_group != _position_group(player.primary_position):
            raise ValueError(f"{player.player_id}: position_group mismatch")
        if player.bats not in {"R", "L", "S"}:
            raise ValueError(f"{player.player_id}: invalid bats")
        if player.throws not in {"R", "L"}:
            raise ValueError(f"{player.player_id}: invalid throws")

    actual_grades = {
        grade: sum(player.academic_year == grade for player in roster.players)
        for grade in (1, 2, 3)
    }
    if roster.cohort_policy == "initial_v1":
        if actual_grades != GRADE_COUNTS:
            raise ValueError(
                f"{roster.school_id}: grade distribution mismatch {actual_grades}"
            )
    elif roster.cohort_policy == "career_v1":
        if (sum(actual_grades.values()) != CORE_ROSTER_SIZE
                or any(count <= 0 for count in actual_grades.values())):
            raise ValueError(
                f"{roster.school_id}: career cohort must retain all grades"
            )
    else:
        raise ValueError(f"{roster.school_id}: unknown cohort policy")

    actual_positions = sorted(
        player.primary_position for player in roster.players
    )
    if actual_positions != sorted(POSITION_SLOTS):
        raise ValueError(
            f"{roster.school_id}: position slots do not match contract"
        )


def write_players_csv(
    rosters: Iterable[SchoolRoster],
    path: str | Path,
) -> dict:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "reference_year",
        *Player.__dataclass_fields__.keys(),
    ]
    roster_count = 0
    player_count = 0

    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for roster in rosters:
            validate_school_roster(roster)
            roster_count += 1
            for player in roster.players:
                row = player.to_dict()
                row = {
                    "reference_year": roster.reference_year,
                    **row,
                }
                writer.writerow(row)
                player_count += 1

    return {
        "roster_count": roster_count,
        "player_count": player_count,
        "output": str(output),
    }
