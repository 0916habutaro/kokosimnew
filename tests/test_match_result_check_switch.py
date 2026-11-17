"""終わった試合の結果の検査の切り替え。テストでは検査し、遊ぶときの入口だけ省く。"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_core import match_simulator
from game_core.match_contract import MatchSimulationInput, TeamMatchInput
from game_core.match_simulator import MatchSimulator
from game_core.players import PlayerRosterGenerator
from game_core.school_intake import SchoolAwarePlayerAbilityGenerator
from game_core.team_strength import TeamStrengthGenerator
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
ABILITY_CONFIG = ROOT / "config" / "abilities"
MATCH_CONFIG = ROOT / "config" / "match"
SEED = 2026111701


class MatchResultCheckSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo = DataRepository(ROOT / "data")
        abilities = SchoolAwarePlayerAbilityGenerator(ABILITY_CONFIG)
        teams = TeamStrengthGenerator(ABILITY_CONFIG)
        inputs = []
        for school_id in sorted(repo.school_to_program)[:2]:
            roster = PlayerRosterGenerator().generate_for_school_id(repo, school_id, 2026, SEED)
            players = tuple(abilities.iter_roster(roster.players, 2026, SEED))
            inputs.append(TeamMatchInput(school_id=school_id, team_strength=teams.generate(players),
                                         player_abilities=players))
        cls.match_input = MatchSimulationInput(
            match_id="CHECK-001", competition_id="CMPCHECK", reference_year=2026,
            generation_seed=SEED, team1=inputs[0], team2=inputs[1])

    def _simulate_counting_checks(self, simulator):
        calls = []
        original = match_simulator.validate_match_simulation_result

        def counted(*args, **kwargs):
            calls.append(args[0])
            return original(*args, **kwargs)

        with patch.object(match_simulator, "validate_match_simulation_result", counted):
            result = simulator.simulate(self.match_input)
        return result, calls

    def test_results_are_checked_by_default(self):
        self.assertTrue(MatchSimulator.check_results)
        result, calls = self._simulate_counting_checks(MatchSimulator(MATCH_CONFIG))
        self.assertEqual([result], calls)

    def test_check_can_be_skipped_without_changing_the_result(self):
        checked, _ = self._simulate_counting_checks(MatchSimulator(MATCH_CONFIG))
        simulator = MatchSimulator(MATCH_CONFIG)
        simulator.check_results = False
        skipped, calls = self._simulate_counting_checks(simulator)
        self.assertEqual([], calls)
        self.assertEqual(checked, skipped)

    def test_game_cli_skips_checks(self):
        from phase2_engine.live_game_cli import main

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(MatchSimulator, "check_results", True), \
                contextlib.redirect_stdout(io.StringIO()):
            main(["--save-root", tmp, "list"])
            self.assertFalse(MatchSimulator.check_results)
        self.assertTrue(MatchSimulator.check_results)


if __name__ == "__main__":
    unittest.main()
