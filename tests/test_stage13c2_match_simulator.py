from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from game_core.match_contract import (
    MatchSimulationInput,
    TeamMatchInput,
    validate_match_simulation_result,
)
from game_core.match_simulator import (
    MatchSimulator,
    synchronize_tournament_match,
)
from game_core.players import PlayerRosterGenerator
from game_core.school_intake import SchoolAwarePlayerAbilityGenerator
from game_core.team_strength import TeamStrengthGenerator
from phase2_engine.models import Match
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
ABILITY_CONFIG = ROOT / "config" / "abilities"
MATCH_CONFIG = ROOT / "config" / "match"


class Stage13C2MatchSimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.school_ids = sorted(cls.repo.school_to_program)[:4]
        cls.seed = 2026100701
        cls.year = 2026
        roster_generator = PlayerRosterGenerator()
        ability_generator = SchoolAwarePlayerAbilityGenerator(
            ABILITY_CONFIG
        )
        team_generator = TeamStrengthGenerator(ABILITY_CONFIG)
        cls.teams: dict[str, TeamMatchInput] = {}

        for school_id in cls.school_ids:
            roster = roster_generator.generate_for_school_id(
                cls.repo,
                school_id,
                cls.year,
                cls.seed,
            )
            abilities = tuple(
                ability_generator.iter_roster(
                    roster.players,
                    cls.year,
                    cls.seed,
                )
            )
            cls.teams[school_id] = TeamMatchInput(
                school_id=school_id,
                team_strength=team_generator.generate(abilities),
                player_abilities=abilities,
            )

        cls.simulator = MatchSimulator(MATCH_CONFIG)

    def _input(
        self,
        match_id: str = "SIM-001",
        team1_index: int = 0,
        team2_index: int = 1,
    ) -> MatchSimulationInput:
        return MatchSimulationInput(
            match_id=match_id,
            competition_id="CMP13C2",
            reference_year=self.year,
            generation_seed=self.seed,
            team1=self.teams[self.school_ids[team1_index]],
            team2=self.teams[self.school_ids[team2_index]],
        )

    def test_full_game_is_deterministic(self):
        match_input = self._input()
        first = self.simulator.simulate(match_input)
        second = self.simulator.simulate(match_input)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_completed_game_has_winner_and_no_tie(self):
        result = self.simulator.simulate(self._input())
        self.assertNotEqual(result.team1_score, result.team2_score)
        self.assertIn(
            result.winner_id,
            {result.team1_school_id, result.team2_school_id},
        )
        self.assertGreaterEqual(result.last_inning, 9)

    def test_result_passes_stage13c1_reconciliation(self):
        match_input = self._input()
        result = self.simulator.simulate(match_input)
        validate_match_simulation_result(
            result,
            match_input,
            config_dir=MATCH_CONFIG,
        )

    def test_events_and_plate_appearances_are_contiguous(self):
        result = self.simulator.simulate(self._input())
        self.assertEqual(
            list(range(1, len(result.events) + 1)),
            [event.event_no for event in result.events],
        )
        self.assertEqual(
            list(range(1, len(result.events) + 1)),
            [event.plate_appearance_no for event in result.events],
        )

    def test_lineup_cycles_beyond_first_nine_batters(self):
        result = self.simulator.simulate(self._input())
        by_team = {}
        for event in result.events:
            by_team.setdefault(event.offense_school_id, []).append(
                event.batter_id
            )
        for school_id, batter_ids in by_team.items():
            self.assertGreater(len(batter_ids), 9)
            lineup = tuple(
                entry.player_id
                for entry in sorted(
                    self.teams[school_id]
                    .team_strength.starting_lineup.entries,
                    key=lambda entry: entry.batting_order,
                )
            )
            self.assertEqual(lineup, tuple(batter_ids[:9]))

    def test_event_types_are_from_catalog(self):
        result = self.simulator.simulate(self._input())
        catalog = set(self.simulator.event_catalog)
        self.assertTrue(result.events)
        self.assertTrue(
            all(event.event_type in catalog for event in result.events)
        )

    def test_score_equals_event_runs(self):
        result = self.simulator.simulate(self._input())
        totals = {
            result.team1_school_id: 0,
            result.team2_school_id: 0,
        }
        for event in result.events:
            totals[event.offense_school_id] += event.runs_scored
        self.assertEqual(
            result.team1_score,
            totals[result.team1_school_id],
        )
        self.assertEqual(
            result.team2_score,
            totals[result.team2_school_id],
        )

    def test_team_hits_equal_batter_and_pitcher_totals(self):
        result = self.simulator.simulate(self._input())
        team_stats = {
            row.school_id: row for row in result.team_stats
        }
        for school_id, opponent_id in (
            (result.team1_school_id, result.team2_school_id),
            (result.team2_school_id, result.team1_school_id),
        ):
            batter_hits = sum(
                row.hits
                for row in result.batter_stats
                if row.school_id == school_id
            )
            pitcher_hits = sum(
                row.hits_allowed
                for row in result.pitcher_stats
                if row.school_id == opponent_id
            )
            self.assertEqual(team_stats[school_id].hits, batter_hits)
            self.assertEqual(team_stats[school_id].hits, pitcher_hits)

    def test_pitcher_batters_faced_equals_opponent_pa(self):
        result = self.simulator.simulate(self._input())
        for school_id, opponent_id in (
            (result.team1_school_id, result.team2_school_id),
            (result.team2_school_id, result.team1_school_id),
        ):
            pa = sum(
                row.plate_appearances
                for row in result.batter_stats
                if row.school_id == school_id
            )
            bf = sum(
                row.batters_faced
                for row in result.pitcher_stats
                if row.school_id == opponent_id
            )
            self.assertEqual(pa, bf)

    def test_different_match_namespace_changes_event_sequence(self):
        first = self.simulator.simulate(self._input("SIM-A"))
        second = self.simulator.simulate(self._input("SIM-B"))
        first_types = [event.event_type for event in first.events]
        second_types = [event.event_type for event in second.events]
        self.assertNotEqual(first_types, second_types)

    def test_short_regulation_game_supported_for_engine_tests(self):
        result = self.simulator.simulate(
            self._input("SIM-SHORT"),
            regulation_innings=3,
        )
        self.assertGreaterEqual(result.last_inning, 3)
        self.assertNotEqual(result.team1_score, result.team2_score)

    def test_probability_model_responds_to_batter_pitcher_abilities(self):
        match_input = self._input()
        batter = match_input.team1.player_abilities[0]
        pitcher = next(
            p
            for p in match_input.team2.player_abilities
            if p.primary_position == "P"
        )
        strong_batter = replace(
            batter,
            contact=95,
            power=95,
            plate_discipline=90,
            strikeout_resistance=90,
        )
        weak_batter = replace(
            batter,
            contact=20,
            power=20,
            plate_discipline=20,
            strikeout_resistance=20,
        )
        defense = match_input.team2.team_strength.defense_strength
        strong = self.simulator._event_weights(
            strong_batter,
            pitcher,
            defense,
        )
        weak = self.simulator._event_weights(
            weak_batter,
            pitcher,
            defense,
        )
        self.assertGreater(
            strong["single"] + strong["double"] + strong["home_run"],
            weak["single"] + weak["double"] + weak["home_run"],
        )
        self.assertLess(strong["strikeout"], weak["strikeout"])

    def test_stronger_pitcher_increases_strikeout_weight(self):
        match_input = self._input()
        batter = match_input.team1.player_abilities[0]
        pitcher = next(
            p
            for p in match_input.team2.player_abilities
            if p.primary_position == "P"
        )
        strong = replace(
            pitcher,
            stuff=95,
            strikeout=95,
            control=90,
        )
        weak = replace(
            pitcher,
            stuff=20,
            strikeout=20,
            control=20,
        )
        defense = match_input.team2.team_strength.defense_strength
        strong_weights = self.simulator._event_weights(
            batter,
            strong,
            defense,
        )
        weak_weights = self.simulator._event_weights(
            batter,
            weak,
            defense,
        )
        self.assertGreater(
            strong_weights["strikeout"],
            weak_weights["strikeout"],
        )

    def test_pitching_staff_can_be_used_beyond_ace(self):
        result = self.simulator.simulate(self._input("SIM-PITCHERS"))
        used = {
            row.player_id
            for row in result.pitcher_stats
            if row.batters_faced > 0
        }
        self.assertGreaterEqual(len(used), 2)

    def test_tournament_match_can_be_synchronized(self):
        match_input = self._input("SIM-SYNC")
        result = self.simulator.simulate(match_input)
        match = Match(
            match_id=result.match_id,
            competition_id=result.competition_id,
            stage_id="STG",
            stage_code="MAIN",
            phase_code="R1",
            round_no=1,
            team1=result.team1_school_id,
            team2=result.team2_school_id,
        )
        synchronize_tournament_match(match, result)
        self.assertEqual(result.winner_id, match.winner)
        self.assertEqual(result.loser_id, match.loser)
        self.assertEqual(
            result.team1_score,
            match.metadata["team1_score"],
        )
        self.assertEqual(
            "ability_model_v1",
            match.metadata["score_source"],
        )

    def test_match_config_is_revision_2_and_not_claimed_tuned(self):
        self.assertEqual(2, self.simulator.config.revision)
        self.assertEqual(
            "design_default_not_tuned",
            self.simulator.config.payload["status"],
        )


if __name__ == "__main__":
    unittest.main()
