from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from game_core.match_config import load_and_validate_match_configs
from game_core.match_contract import (
    SCORE_SOURCE_ABILITY_MODEL_V1,
    BatterGameStats,
    MatchEvent,
    MatchSimulationInput,
    MatchSimulationResult,
    PitcherGameStats,
    TeamGameStats,
    TeamMatchInput,
    match_contract_provenance,
    result_score_pair,
    validate_batter_game_stats,
    validate_match_event,
    validate_match_simulation_input,
    validate_match_simulation_result,
    validate_pitcher_game_stats,
)
from game_core.players import PlayerRosterGenerator
from game_core.school_intake import SchoolAwarePlayerAbilityGenerator
from game_core.team_strength import TeamStrengthGenerator
from phase2_engine.models import CompetitionRun, Match, StageExecution
from phase2_engine.repository import DataRepository
from phase2_engine.result_view import build_competition_result_view

ROOT = Path(__file__).resolve().parents[1]
ABILITY_CONFIG_DIR = ROOT / "config" / "abilities"
MATCH_CONFIG_DIR = ROOT / "config" / "match"


class Stage13C1MatchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.seed = 2026100701
        cls.year = 2026
        cls.school_ids = sorted(cls.repo.school_to_program)[:2]

        roster_generator = PlayerRosterGenerator()
        ability_generator = SchoolAwarePlayerAbilityGenerator(
            ABILITY_CONFIG_DIR
        )
        team_generator = TeamStrengthGenerator(ABILITY_CONFIG_DIR)

        cls.teams: list[TeamMatchInput] = []
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
            strength = team_generator.generate(abilities)
            cls.teams.append(
                TeamMatchInput(
                    school_id=school_id,
                    team_strength=strength,
                    player_abilities=abilities,
                )
            )

        cls.match_input = MatchSimulationInput(
            match_id="MATCH13C1",
            competition_id="CMP13C1",
            reference_year=cls.year,
            generation_seed=cls.seed,
            team1=cls.teams[0],
            team2=cls.teams[1],
        )

        cls.team1_pitcher = (
            cls.teams[0].team_strength.pitching_staff.ace_player_id
        )
        cls.team2_pitcher = (
            cls.teams[1].team_strength.pitching_staff.ace_player_id
        )
        cls.team1_batter = next(
            player_id
            for player_id in cls.teams[0].team_strength.starting_lineup.starter_ids
            if player_id != cls.team1_pitcher
        )
        cls.team2_batter = next(
            player_id
            for player_id in cls.teams[1].team_strength.starting_lineup.starter_ids
            if player_id != cls.team2_pitcher
        )

    def _valid_result(self) -> MatchSimulationResult:
        provenance = match_contract_provenance(MATCH_CONFIG_DIR)
        events = (
            MatchEvent(
                event_no=1,
                plate_appearance_no=1,
                inning=1,
                half="top",
                offense_school_id=self.school_ids[0],
                defense_school_id=self.school_ids[1],
                batter_id=self.team1_batter,
                pitcher_id=self.team2_pitcher,
                event_type="home_run",
                runs_scored=1,
                outs_on_play=0,
                rbi=1,
            ),
            MatchEvent(
                event_no=2,
                plate_appearance_no=2,
                inning=1,
                half="bottom",
                offense_school_id=self.school_ids[1],
                defense_school_id=self.school_ids[0],
                batter_id=self.team2_batter,
                pitcher_id=self.team1_pitcher,
                event_type="strikeout",
                runs_scored=0,
                outs_on_play=1,
                rbi=0,
            ),
        )
        batters = (
            BatterGameStats(
                player_id=self.team1_batter,
                school_id=self.school_ids[0],
                plate_appearances=1,
                at_bats=1,
                runs=1,
                hits=1,
                home_runs=1,
                rbi=1,
            ),
            BatterGameStats(
                player_id=self.team2_batter,
                school_id=self.school_ids[1],
                plate_appearances=1,
                at_bats=1,
                strikeouts=1,
            ),
        )
        pitchers = (
            PitcherGameStats(
                player_id=self.team1_pitcher,
                school_id=self.school_ids[0],
                outs_recorded=1,
                batters_faced=1,
                strikeouts=1,
            ),
            PitcherGameStats(
                player_id=self.team2_pitcher,
                school_id=self.school_ids[1],
                outs_recorded=0,
                batters_faced=1,
                runs_allowed=1,
                earned_runs=1,
                hits_allowed=1,
                home_runs_allowed=1,
            ),
        )
        return MatchSimulationResult(
            match_id=self.match_input.match_id,
            competition_id=self.match_input.competition_id,
            reference_year=self.year,
            generation_seed=self.seed,
            team1_school_id=self.school_ids[0],
            team2_school_id=self.school_ids[1],
            team1_score=1,
            team2_score=0,
            winner_id=self.school_ids[0],
            loser_id=self.school_ids[1],
            last_inning=1,
            ending_half="bottom",
            score_source=provenance.score_source,
            match_config_id=provenance.match_config_id,
            match_config_revision=provenance.match_config_revision,
            match_config_sha256=provenance.match_config_sha256,
            event_catalog_id=provenance.event_catalog_id,
            event_catalog_revision=provenance.event_catalog_revision,
            event_catalog_sha256=provenance.event_catalog_sha256,
            stats_config_id=provenance.stats_config_id,
            stats_config_revision=provenance.stats_config_revision,
            stats_config_sha256=provenance.stats_config_sha256,
            team_stats=(
                TeamGameStats(
                    school_id=self.school_ids[0],
                    runs=1,
                    hits=1,
                    errors=0,
                ),
                TeamGameStats(
                    school_id=self.school_ids[1],
                    runs=0,
                    hits=0,
                    errors=0,
                ),
            ),
            events=events,
            batter_stats=batters,
            pitcher_stats=pitchers,
        )

    def _competition_run(self) -> CompetitionRun:
        match = Match(
            match_id=self.match_input.match_id,
            competition_id=self.match_input.competition_id,
            stage_id="STG13C1",
            stage_code="MAIN",
            phase_code="FINAL",
            round_no=1,
            team1=self.school_ids[0],
            team2=self.school_ids[1],
            winner=self.school_ids[0],
            loser=self.school_ids[1],
            metadata={"round_name": "決勝"},
        )
        stage = StageExecution(
            stage_id="STG13C1",
            stage_code="MAIN",
            format_model_id="",
            entrant_school_ids=list(self.school_ids),
            output_school_ids=[self.school_ids[0]],
            matches=[match],
        )
        return CompetitionRun(
            competition_id=self.match_input.competition_id,
            year=self.year,
            rng_seed=self.seed,
            entrant_school_ids=list(self.school_ids),
            seed_assignments=[],
            stage_executions=[stage],
            main_entrant_school_ids=list(self.school_ids),
        )

    def test_all_three_match_configs_load(self):
        configs = load_and_validate_match_configs(MATCH_CONFIG_DIR)
        self.assertEqual(
            {
                "match_simulation_v1",
                "event_catalog_v1",
                "game_stats_contract_v1",
            },
            set(configs),
        )

    def test_match_contract_provenance_is_complete(self):
        provenance = match_contract_provenance(MATCH_CONFIG_DIR)
        self.assertEqual(
            SCORE_SOURCE_ABILITY_MODEL_V1,
            provenance.score_source,
        )
        self.assertEqual(64, len(provenance.match_config_sha256))
        self.assertEqual(64, len(provenance.event_catalog_sha256))
        self.assertEqual(64, len(provenance.stats_config_sha256))

    def test_real_generated_team_inputs_validate(self):
        validate_match_simulation_input(self.match_input)

    def test_same_school_match_is_rejected(self):
        invalid = replace(
            self.match_input,
            team2=self.match_input.team1,
        )
        with self.assertRaises(ValueError):
            validate_match_simulation_input(invalid)

    def test_match_event_validates_team_order_and_players(self):
        event = self._valid_result().events[0]
        validate_match_event(
            event,
            self.match_input,
            config_dir=MATCH_CONFIG_DIR,
        )

    def test_match_event_wrong_half_team_order_is_rejected(self):
        event = replace(
            self._valid_result().events[0],
            half="bottom",
        )
        with self.assertRaises(ValueError):
            validate_match_event(
                event,
                self.match_input,
                config_dir=MATCH_CONFIG_DIR,
            )

    def test_unknown_event_type_is_rejected(self):
        event = replace(
            self._valid_result().events[0],
            event_type="unknown_event",
        )
        with self.assertRaises(ValueError):
            validate_match_event(
                event,
                self.match_input,
                config_dir=MATCH_CONFIG_DIR,
            )

    def test_batter_pa_formula_is_enforced(self):
        valid = BatterGameStats(
            player_id="P",
            school_id="S",
            plate_appearances=2,
            at_bats=1,
            walks=1,
        )
        validate_batter_game_stats(valid)
        invalid = replace(valid, plate_appearances=3)
        with self.assertRaises(ValueError):
            validate_batter_game_stats(invalid)

    def test_extra_base_hits_cannot_exceed_hits(self):
        invalid = BatterGameStats(
            player_id="P",
            school_id="S",
            plate_appearances=1,
            at_bats=1,
            hits=1,
            doubles=1,
            home_runs=1,
        )
        with self.assertRaises(ValueError):
            validate_batter_game_stats(invalid)

    def test_pitcher_stat_invariants_are_enforced(self):
        valid = PitcherGameStats(
            player_id="P",
            school_id="S",
            outs_recorded=3,
            batters_faced=4,
            runs_allowed=1,
            earned_runs=1,
            hits_allowed=1,
            walks=1,
            strikeouts=1,
        )
        validate_pitcher_game_stats(valid)
        with self.assertRaises(ValueError):
            validate_pitcher_game_stats(
                replace(valid, earned_runs=2)
            )

    def test_complete_result_reconciles(self):
        result = self._valid_result()
        validate_match_simulation_result(
            result,
            self.match_input,
            config_dir=MATCH_CONFIG_DIR,
        )
        self.assertEqual((1, 0), result_score_pair(result))

    def test_tied_completed_result_is_rejected(self):
        result = replace(
            self._valid_result(),
            team2_score=1,
        )
        with self.assertRaises(ValueError):
            validate_match_simulation_result(
                result,
                self.match_input,
                config_dir=MATCH_CONFIG_DIR,
            )

    def test_event_run_total_must_equal_score(self):
        result = self._valid_result()
        events = (
            replace(result.events[0], runs_scored=0, rbi=0),
            result.events[1],
        )
        with self.assertRaises(ValueError):
            validate_match_simulation_result(
                replace(result, events=events),
                self.match_input,
                config_dir=MATCH_CONFIG_DIR,
            )

    def test_config_provenance_mismatch_is_rejected(self):
        result = replace(
            self._valid_result(),
            match_config_sha256="0" * 64,
        )
        with self.assertRaises(ValueError):
            validate_match_simulation_result(
                result,
                self.match_input,
                config_dir=MATCH_CONFIG_DIR,
            )

    def test_result_view_accepts_ability_model_score(self):
        rows = build_competition_result_view(
            self._competition_run(),
            self.repo,
            ability_scores={self.match_input.match_id: [3, 1]},
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("ability_model_v1", rows[0].score_source)
        self.assertEqual((3, 1), (
            rows[0].team1_score,
            rows[0].team2_score,
        ))

    def test_result_view_override_has_priority_over_ability_score(self):
        rows = build_competition_result_view(
            self._competition_run(),
            self.repo,
            score_overrides={self.match_input.match_id: [5, 2]},
            ability_scores={self.match_input.match_id: [3, 1]},
        )
        self.assertEqual("override", rows[0].score_source)
        self.assertEqual((5, 2), (
            rows[0].team1_score,
            rows[0].team2_score,
        ))

    def test_result_view_rejects_ability_score_that_conflicts_with_winner(self):
        with self.assertRaises(ValueError):
            build_competition_result_view(
                self._competition_run(),
                self.repo,
                ability_scores={self.match_input.match_id: [1, 3]},
            )

    def test_rate_stats_are_not_stored_in_contract(self):
        fields = BatterGameStats.__dataclass_fields__
        self.assertNotIn("batting_average", fields)
        self.assertNotIn("on_base_percentage", fields)
        self.assertNotIn("ops", fields)

    def test_design_documents_exist(self):
        required = [
            ROOT / "docs" / "design" / "match_simulation_contract.md",
            ROOT / "docs" / "design" / "game_event_stats_contract.md",
            ROOT / "docs" / "adr" / "ADR-007-match-simulator-owns-winner.md",
            ROOT / "docs" / "adr" / "ADR-008-event-stats-reconciliation.md",
        ]
        self.assertTrue(all(path.exists() for path in required))


if __name__ == "__main__":
    unittest.main()
