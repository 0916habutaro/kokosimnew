from __future__ import annotations

from pathlib import Path

from phase2_engine.models import MatchResolution
from phase2_engine.repository import DataRepository

from .match_contract import MatchSimulationInput, TeamMatchInput
from .match_simulator import MatchSimulator
from .players import PlayerRosterGenerator
from .school_intake import SchoolAwarePlayerAbilityGenerator
from .team_strength import TeamStrengthGenerator


class AbilityMatchResolver:
    """Bridge Phase 2 tournament matches to the Stage 13 ability model.

    Phase 2 remains responsible for tournament structure and progression. This resolver
    owns each non-bye game's score/winner by constructing the two Stage 13 team inputs
    and delegating the game itself to MatchSimulator.
    """

    def __init__(
        self,
        repo: DataRepository,
        *,
        ability_config_dir: str | Path = "config/abilities",
        match_config_dir: str | Path = "config/match",
    ):
        self.repo = repo
        self.roster_generator = PlayerRosterGenerator()
        self.ability_generator = SchoolAwarePlayerAbilityGenerator(
            ability_config_dir
        )
        self.team_generator = TeamStrengthGenerator(ability_config_dir)
        self.simulator = MatchSimulator(match_config_dir)
        self._team_cache: dict[
            tuple[int, int, str],
            TeamMatchInput,
        ] = {}

    def clear_cache(self) -> None:
        self._team_cache.clear()

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
        key = (reference_year, generation_seed, school_id)
        cached = self._team_cache.get(key)
        if cached is not None:
            return cached

        roster = self.roster_generator.generate_for_school_id(
            self.repo,
            school_id,
            reference_year,
            generation_seed,
        )
        abilities = tuple(
            self.ability_generator.iter_roster(
                roster.players,
                reference_year,
                generation_seed,
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
                "ability match resolver requires two non-bye teams"
            )
        if team1 == team2:
            raise ValueError(
                "ability match resolver requires two distinct teams"
            )

        match_input = MatchSimulationInput(
            match_id=match_id,
            competition_id=competition_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            team1=self.team_input(
                school_id=team1,
                reference_year=reference_year,
                generation_seed=generation_seed,
            ),
            team2=self.team_input(
                school_id=team2,
                reference_year=reference_year,
                generation_seed=generation_seed,
            ),
        )
        result = self.simulator.simulate(match_input)
        return MatchResolution(
            winner_id=result.winner_id,
            loser_id=result.loser_id,
            team1_score=result.team1_score,
            team2_score=result.team2_score,
            score_source=result.score_source,
            detail=result.to_dict(),
        )


# Backward-compatible Stage 13C-3 name.
AbilityMainMatchResolver = AbilityMatchResolver
