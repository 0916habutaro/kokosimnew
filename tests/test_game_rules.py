"""試合の規定：タイブレークと得点差コールド（game_definition.md §11）。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from game_core.match_contract import (
    MatchSimulationInput,
    TeamMatchInput,
    validate_match_simulation_result,
)
from game_core.match_simulator import GameRules, MatchSimulator
from game_core.players import PlayerRosterGenerator
from game_core.school_intake import SchoolAwarePlayerAbilityGenerator
from game_core.team_strength import TeamStrengthGenerator
from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
ABILITY_CONFIG = ROOT / "config" / "abilities"
MATCH_CONFIG = ROOT / "config" / "match"
RULES = GameRules(tiebreak_start_inning=10, mercy=((5, 10), (7, 7)))


class GameRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        # 強い学校と弱い学校（大差の試合も出るように）
        ranked = sorted(cls.repo.school_to_program)
        cls.school_ids = [ranked[0], ranked[1], ranked[-1]]
        cls.seed, cls.year = 2026102601, 2026
        rosters = PlayerRosterGenerator()
        abilities = SchoolAwarePlayerAbilityGenerator(ABILITY_CONFIG)
        strength = TeamStrengthGenerator(ABILITY_CONFIG)
        cls.teams = {}
        for school_id in cls.school_ids:
            roster = rosters.generate_for_school_id(cls.repo, school_id, cls.year, cls.seed)
            players = tuple(abilities.iter_roster(roster.players, cls.year, cls.seed))
            cls.teams[school_id] = TeamMatchInput(
                school_id=school_id,
                team_strength=strength.generate(players),
                player_abilities=players,
            )
        cls.simulator = MatchSimulator(MATCH_CONFIG)

    def _input(self, number: int, team1: int = 0, team2: int = 1) -> MatchSimulationInput:
        return MatchSimulationInput(
            match_id=f"RULES-{number:04d}",
            competition_id="CMPRULES",
            reference_year=self.year,
            generation_seed=self.seed,
            team1=self.teams[self.school_ids[team1]],
            team2=self.teams[self.school_ids[team2]],
        )

    def test_tiebreak_starts_with_runners_on_first_and_second(self):
        checked = 0
        for number in range(400):
            match_input = self._input(number)
            result = self.simulator.simulate(match_input, rules=RULES)
            validate_match_simulation_result(result, match_input, config_dir=MATCH_CONFIG)
            if result.last_inning < 10:
                continue
            for half in ("top", "bottom"):
                first = next(
                    (e for e in result.events if e.inning == 10 and e.half == half), None,
                )
                if first is None:
                    continue
                bases = dict(first.metadata)["bases_before"].split("|")
                # 一塁は先頭打者の1人前、二塁は2人前（打順は続ける）
                self.assertTrue(bases[0] and bases[1] and not bases[2], bases)
                self.assertNotIn(first.batter_id, bases)
                checked += 1
            if checked >= 4:
                break
        self.assertGreaterEqual(checked, 2)

    def test_mercy_rule_ends_lopsided_games_early(self):
        called = 0
        for number in range(150):
            match_input = self._input(number, 0, 2)
            result = self.simulator.simulate(match_input, rules=RULES)
            validate_match_simulation_result(result, match_input, config_dir=MATCH_CONFIG)
            margin = abs(result.team1_score - result.team2_score)
            if result.last_inning < 9:
                called += 1
                self.assertGreaterEqual(result.last_inning, 5)
                self.assertGreaterEqual(margin, 10 if result.last_inning < 7 else 7)
            # 規定がなければ9回まで
            plain = self.simulator.simulate(match_input)
            self.assertGreaterEqual(plain.last_inning, 9)
        self.assertGreater(called, 0)


class RulesForMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.resolver = AbilityMatchResolver(
            cls.repo, ability_config_dir=ABILITY_CONFIG, match_config_dir=MATCH_CONFIG,
        )

    def _competition(self, **where):
        return next(
            cid for cid, row in self.repo.competitions.items()
            if all(row.get(key) == value for key, value in where.items())
        )

    def test_mercy_only_before_the_final_of_local_and_regional(self):
        national = self._competition(competition_type="national_championship")
        local = self._competition(competition_type="summer_local_qualifier", prefecture_code="13")
        kanagawa = self._competition(competition_type="summer_local_qualifier", prefecture_code="14")
        regional = self._competition(competition_level="regional", season_segment="autumn")
        main = SimpleNamespace(total_rounds=7)
        self.resolver.season_state = SimpleNamespace(competitions={
            cid: SimpleNamespace(runtime=main) for cid in (local, kanagawa, regional)
        })
        rules = self.resolver.rules_for
        self.assertEqual(10, rules(national, "X-MAIN-R01-M001").tiebreak_start_inning)
        self.assertEqual((), rules(national, "X-MAIN-R01-M001").mercy)
        self.assertEqual(((5, 10), (7, 7)), rules(local, "X-MAIN-R06-M001").mercy)
        self.assertEqual((), rules(local, "X-MAIN-R07-M001").mercy)  # 決勝
        self.assertEqual((), rules(kanagawa, "X-MAIN-R06-M001").mercy)  # 神奈川は準決勝から
        self.assertEqual(((5, 10), (7, 7)), rules(kanagawa, "X-MAIN-R05-M001").mercy)
        self.assertEqual((), rules(regional, "X-MAIN-R07-M001").mercy)
        # 本大会の前の予選はコールドあり
        self.assertEqual(((5, 10), (7, 7)), rules(local, "X-SGR1-POOL-M001").mercy)


if __name__ == "__main__":
    unittest.main()
