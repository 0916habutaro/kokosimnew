"""試合の規定：タイブレークと得点差コールド（game_definition.md §11）。"""
from __future__ import annotations

from datetime import date
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


class _TeamsFixture(unittest.TestCase):
    """強い学校2つと弱い学校1つの試合の入力。"""

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


class GameRulesTests(_TeamsFixture):
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
        autumn = self._competition(competition_type="autumn_prefectural")
        main = SimpleNamespace(total_rounds=7)
        self.resolver.season_state = SimpleNamespace(competitions={
            cid: SimpleNamespace(runtime=main) for cid in (local, kanagawa, regional, autumn)
        })
        rules = self.resolver.rules_for
        self.assertEqual(10, rules(national, "X-MAIN-R01-M001").tiebreak_start_inning)
        self.assertEqual((), rules(national, "X-MAIN-R01-M001").mercy)
        self.assertEqual(((5, 10), (7, 7)), rules(local, "X-MAIN-R06-M001").mercy)
        self.assertEqual((), rules(local, "X-MAIN-R07-M001").mercy)  # 決勝
        self.assertEqual((), rules(kanagawa, "X-MAIN-R06-M001").mercy)  # 神奈川は準決勝から
        self.assertEqual(((5, 10), (7, 7)), rules(kanagawa, "X-MAIN-R05-M001").mercy)
        self.assertEqual((), rules(regional, "X-MAIN-R07-M001").mercy)
        # 春・秋の都道府県大会も
        self.assertEqual(((5, 10), (7, 7)), rules(autumn, "X-MAIN-R06-M001").mercy)
        self.assertEqual((), rules(autumn, "X-MAIN-R07-M001").mercy)
        # 本大会の前の予選はコールドあり
        self.assertEqual(((5, 10), (7, 7)), rules(local, "X-SGR1-POOL-M001").mercy)


class PitchLimitTests(_TeamsFixture):
    """球数制限（1週間500球）と1打席の球数。"""

    def _staff(self, index: int = 0) -> tuple[str, ...]:
        team = self.teams[self.school_ids[index]]
        return tuple(entry.player_id for entry in team.team_strength.pitching_staff.entries)

    def test_pitches_are_counted(self):
        totals = []
        for number in range(40):
            result = self.simulator.simulate(self._input(number), rules=RULES)
            for stat in result.pitcher_stats:
                self.assertGreaterEqual(stat.pitches, stat.batters_faced)
            for school_id in (result.team1_school_id, result.team2_school_id):
                rows = [s for s in result.pitcher_stats if s.school_id == school_id]
                totals.append(
                    sum(s.pitches for s in rows) / sum(s.batters_faced for s in rows)
                )
        # 1打者あたり3〜4.5球くらい
        self.assertTrue(3.0 < sum(totals) / len(totals) < 4.5, sum(totals) / len(totals))

    def test_pitcher_without_allowance_does_not_pitch(self):
        staff = self._staff()
        self.assertGreater(len(staff), 1)
        ace = staff[0]
        for number in range(20):
            # 投げられない：出ない
            result = self.simulator.simulate(
                self._input(number), rules=RULES, pitch_allowances={ace: 0},
            )
            self.assertNotIn(ace, {s.player_id for s in result.pitcher_stats})
            # 残りが少ない：先発しない
            result = self.simulator.simulate(
                self._input(number), rules=RULES, pitch_allowances={ace: 60},
            )
            first = next(
                e.pitcher_id for e in result.events
                if e.defense_school_id == self.school_ids[0]
            )
            self.assertNotEqual(ace, first)

    def test_pitcher_leaves_after_the_batter_who_reaches_the_limit(self):
        by_event = self.simulator.params["pitch_count"]["by_event"]
        most = max(low + extra for low, extra in by_event.values())
        team = self.teams[self.school_ids[0]]
        # 投手陣はみな30球まで。足りなければ野手が投げる
        allowances = {pid: 30 for pid in self._staff()}
        fielders = 0
        for number in range(20):
            result = self.simulator.simulate(
                self._input(number), rules=RULES, pitch_allowances=allowances,
            )
            for stat in result.pitcher_stats:
                if stat.school_id != team.school_id:
                    continue
                if stat.player_id in allowances:
                    # 30球に届いた打者の打撃が終わるまでは投げる
                    self.assertLessEqual(stat.pitches, 29 + most)
                else:
                    fielders += 1
        self.assertGreater(fielders, 0)


class WeeklyPitchLogTests(unittest.TestCase):
    """試合の日を含む7日間で数え、投げた球数を日ごとに残す。"""

    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.school_ids = sorted(cls.repo.school_to_program)[:2]
        cls.competition = next(
            cid for cid, row in cls.repo.competitions.items()
            if row.get("competition_type") == "national_championship"
        )

    def _resolver(self, day: date, log: dict):
        resolver = AbilityMatchResolver(
            self.repo, ability_config_dir=ABILITY_CONFIG,
            match_config_dir=MATCH_CONFIG, team_generation_seed=2026102701,
        )
        resolver.season_state = SimpleNamespace(
            current_date=day, pitch_log=log, competitions={},
        )
        return resolver

    def _play(self, resolver, number: int):
        return resolver(
            match_id=f"X-MAIN-R01-M{number:03d}", competition_id=self.competition,
            reference_year=2026, generation_seed=2026102701,
            team1=self.school_ids[0], team2=self.school_ids[1],
        )

    def test_pitches_are_logged_and_limit_the_week(self):
        log: dict = {}
        resolver = self._resolver(date(2026, 8, 10), log)
        self._play(resolver, 1)
        self.assertTrue(log)
        self.assertTrue(all(set(days) == {"2026-08-10"} for days in log.values()))
        team = resolver.team_input(
            school_id=self.school_ids[0], reference_year=2026, generation_seed=2026102701,
        )
        ace = team.team_strength.pitching_staff.entries[0].player_id
        teams = (team,)
        # 6日前の球数は数え、7日前は数えない
        log[ace] = {"2026-08-04": 450, "2026-08-03": 50}
        self.assertEqual(50, resolver._pitch_allowances(teams, date(2026, 8, 10))[ace])
        self.assertEqual(500, resolver._pitch_allowances(teams, date(2026, 8, 11))[ace])
        # 古い日の記録は消える
        log[ace] = {"2026-08-01": 120}
        later = self._resolver(date(2026, 8, 12), log)
        self._play(later, 2)
        self.assertTrue(all(
            day >= "2026-08-06" for days in log.values() for day in days
        ))


if __name__ == "__main__":
    unittest.main()
