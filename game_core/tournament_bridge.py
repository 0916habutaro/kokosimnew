from __future__ import annotations

from pathlib import Path
from typing import Callable

from phase2_engine.models import MatchResolution
from phase2_engine.repository import DataRepository

from .match_contract import MatchSimulationInput, TeamMatchInput
from .match_simulator import MatchSimulator
from .players import PlayerRosterGenerator, SchoolRoster, validate_school_roster
from .school_intake import SchoolAwarePlayerAbilityGenerator
from .team_strength import TeamStrengthGenerator


class AbilityMatchResolver:
    """Bridge Phase 2 tournament matches to the Stage 13 ability model.

    Phase 2 remains responsible for tournament structure and progression. This resolver
    owns each non-bye game's score/winner by constructing Stage 13 team inputs and
    delegating the game itself to MatchSimulator.
    """

    def __init__(
        self,
        repo: DataRepository,
        *,
        ability_config_dir: str | Path = "config/abilities",
        match_config_dir: str | Path = "config/match",
        team_generation_seed: int | None = None,
        roster_provider: Callable[[int, str], SchoolRoster | None] | None = None,
    ):
        self.repo = repo
        self.roster_generator = PlayerRosterGenerator()
        # Explicit opt-in. Prevent future-year seasons from silently
        # creating entirely new identities for existing school members.
        self.roster_provider = roster_provider
        self.ability_generator = SchoolAwarePlayerAbilityGenerator(
            ability_config_dir
        )
        self.team_generator = TeamStrengthGenerator(ability_config_dir)
        self.simulator = MatchSimulator(match_config_dir)
        self._fixed_team_generation_seed = team_generation_seed
        self._season_reference_year: int | None = None
        self._season_team_generation_seed: int | None = None
        self._team_cache: dict[
            tuple[int, int, str],
            TeamMatchInput,
        ] = {}
        self._roster_cache: dict[
            tuple[int, int, str],
            SchoolRoster,
        ] = {}

    def clear_cache(self) -> None:
        self._team_cache.clear()
        self._roster_cache.clear()

    def begin_season(
        self,
        reference_year: int,
        season_generation_seed: int,
    ) -> None:
        if reference_year < 1:
            raise ValueError("reference_year must be positive")
        if (
            not isinstance(season_generation_seed, int)
            or isinstance(season_generation_seed, bool)
        ):
            raise ValueError("season_generation_seed must be integer")
        self.clear_cache()
        self._season_reference_year = reference_year
        self._season_team_generation_seed = season_generation_seed

    def _effective_team_generation_seed(
        self,
        *,
        reference_year: int,
        match_generation_seed: int,
    ) -> int:
        if self._fixed_team_generation_seed is not None:
            return self._fixed_team_generation_seed
        if (
            self._season_reference_year == reference_year
            and self._season_team_generation_seed is not None
        ):
            return self._season_team_generation_seed
        return match_generation_seed

    def player_master_records(self) -> dict[str, dict]:
        records: dict[str, dict] = {}
        for (reference_year, generation_seed, school_id), roster in sorted(
            self._roster_cache.items()
        ):
            for player in roster.players:
                row = {
                    "reference_year": reference_year,
                    **player.to_dict(),
                    "school_name": roster.school_name,
                }
                existing = records.get(player.player_id)
                if existing is not None and existing != row:
                    raise ValueError(
                        f"{player.player_id}: conflicting player master rows"
                    )
                records[player.player_id] = row
        return records

    @property
    def cache_size(self) -> int:
        return len(self._team_cache)

    def team_input(
        self,
        *,
        school_id: str,
        reference_year: int,
        generation_seed: int,
    ) -> TeamMatchInput:
        team_seed = self._effective_team_generation_seed(
            reference_year=reference_year,
            match_generation_seed=generation_seed,
        )
        key = (reference_year, team_seed, school_id)
        cached = self._team_cache.get(key)
        if cached is not None:
            return cached

        if self.roster_provider is None:
            roster = self.roster_generator.generate_for_school_id(
                self.repo, school_id, reference_year, team_seed,
            )
        else:
            roster = self.roster_provider(reference_year, school_id)
            if roster is None:
                raise ValueError(
                    f"missing historical roster: {school_id}/{reference_year}"
                )
            validate_school_roster(roster)
            if (roster.school_id != school_id
                    or roster.reference_year != reference_year):
                raise ValueError("historical roster year/school mismatch")
        self._roster_cache[key] = roster
        abilities = tuple(
            self.ability_generator.iter_roster(
                roster.players,
                reference_year,
                team_seed,
            )
        )
        team = TeamMatchInput(
            school_id=school_id,
            team_strength=self.team_generator.generate(abilities),
            player_abilities=abilities,
        )
        self._team_cache[key] = team
        return team

    def __call__(
        self,
        *,
        match_id: str,
        competition_id: str,
        reference_year: int,
        generation_seed: int,
        team1: str,
        team2: str,
    ) -> MatchResolution:
        if not team1 or not team2:
            raise ValueError(
                "ability MAIN resolver requires two non-bye teams"
            )
        if team1 == team2:
            raise ValueError(
                "ability MAIN resolver requires two distinct teams"
            )

        team1_input = self.team_input(
            school_id=team1,
            reference_year=reference_year,
            generation_seed=generation_seed,
        )
        team2_input = self.team_input(
            school_id=team2,
            reference_year=reference_year,
            generation_seed=generation_seed,
        )
        team_generation_seed = team1_input.team_strength.generation_seed
        if (
            team2_input.team_strength.generation_seed
            != team_generation_seed
        ):
            raise ValueError(
                "ability resolver team generation seed mismatch"
            )
        match_input = MatchSimulationInput(
            match_id=match_id,
            competition_id=competition_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            team1=team1_input,
            team2=team2_input,
            team_generation_seed=team_generation_seed,
        )
        result = self.simulator.simulate(match_input)
        detail = result.to_dict()
        detail["team_generation_seed"] = team_generation_seed
        return MatchResolution(
            winner_id=result.winner_id,
            loser_id=result.loser_id,
            team1_score=result.team1_score,
            team2_score=result.team2_score,
            score_source=result.score_source,
            detail=detail,
        )


# Backward-compatible Stage 13C-3 name.
AbilityMainMatchResolver = AbilityMatchResolver
