from __future__ import annotations

import csv
import json
from collections import Counter
import tempfile
import unittest
from pathlib import Path

from game_core.tournament_bridge import AbilityMainMatchResolver
from phase2_engine import (
    AnnualCompetitionInput,
    DataRepository,
    TournamentEngine,
    save_competition_run,
)
from phase2_engine.result_view import build_competition_result_view

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class Stage13C3TournamentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)

        selected = None
        for competition_id, competition in sorted(
            cls.repo.competitions.items()
        ):
            stages = cls.repo.stages(competition_id)
            if [stage["stage_code"] for stage in stages] != ["MAIN"]:
                continue
            prefecture_code = competition.get("prefecture_code", "")
            if not prefecture_code:
                continue
            schools = sorted(
                school_id
                for school_id, row in cls.repo.schools.items()
                if (
                    row.get("prefecture_code") == prefecture_code
                    and school_id in cls.repo.school_to_program
                )
            )
            if len(schools) >= 8:
                selected = (competition_id, schools[:8])
                break

        if selected is None:
            raise AssertionError(
                "no direct-MAIN competition with at least eight schools"
            )

        cls.competition_id, cls.school_ids = selected
        cls.seed = 2026100701
        cls.year = 2026
        cls.resolver = AbilityMainMatchResolver(
            cls.repo,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
            # DHなしの従来の全イベント付き直接実行・CSV出力を検証する。
            dh_enabled=False,
        )
        cls.engine = TournamentEngine(
            cls.repo,
            main_match_resolver=cls.resolver,
        )

    def _annual(self) -> AnnualCompetitionInput:
        return AnnualCompetitionInput(
            competition_id=self.competition_id,
            year=self.year,
            entrant_school_ids=list(self.school_ids),
            rng_seed=self.seed,
        )

    def test_main_bracket_uses_ability_model_for_every_non_bye_match(self):
        run = self.engine.run(self._annual())
        main = run.stage_executions[-1]
        non_bye = [match for match in main.matches if not match.is_bye]

        self.assertEqual(7, len(non_bye))
        self.assertEqual(
            {match.match_id for match in non_bye},
            set(run.match_simulation_results),
        )
        for match in non_bye:
            self.assertEqual(
                "ability_model_v1",
                match.metadata.get("score_source"),
            )
            self.assertIsInstance(match.metadata.get("team1_score"), int)
            self.assertIsInstance(match.metadata.get("team2_score"), int)
            self.assertNotEqual(
                match.metadata["team1_score"],
                match.metadata["team2_score"],
            )

    def test_champion_is_final_ability_match_winner(self):
        run = self.engine.run(self._annual())
        main = run.stage_executions[-1]
        final_match = max(
            (match for match in main.matches if not match.is_bye),
            key=lambda match: (match.round_no, match.match_id),
        )
        self.assertEqual(
            final_match.winner,
            run.outcome.champion_school_id,
        )
        self.assertEqual(
            final_match.winner,
            run.match_simulation_results[
                final_match.match_id
            ]["winner_id"],
        )

    def test_result_view_automatically_uses_embedded_ability_scores(self):
        run = self.engine.run(self._annual())
        rows = build_competition_result_view(run, self.repo)
        non_bye = [row for row in rows if not row.is_bye]

        self.assertEqual(7, len(non_bye))
        self.assertTrue(
            all(row.score_source == "ability_model_v1" for row in non_bye)
        )
        for row in non_bye:
            detail = run.match_simulation_results[row.match_id]
            self.assertEqual(detail["team1_score"], row.team1_score)
            self.assertEqual(detail["team2_score"], row.team2_score)

    def test_embedded_result_conflict_is_rejected_by_result_view(self):
        run = self.engine.run(self._annual())
        target_id = next(iter(run.match_simulation_results))
        detail = run.match_simulation_results[target_id]
        conflicting = {
            target_id: [
                detail["team2_score"],
                detail["team1_score"],
            ]
        }
        with self.assertRaises(ValueError):
            build_competition_result_view(
                run,
                self.repo,
                ability_scores=conflicting,
            )

    def test_competition_run_contains_complete_game_stats(self):
        run = self.engine.run(self._annual())
        self.assertEqual(7, len(run.match_simulation_results))

        for match_id, detail in run.match_simulation_results.items():
            with self.subTest(match_id=match_id):
                self.assertEqual(match_id, detail["match_id"])
                self.assertTrue(detail["events"])
                batter_keys = [
                    (row["school_id"], row["player_id"])
                    for row in detail["batter_stats"]
                ]
                self.assertEqual(len(batter_keys), len(set(batter_keys)))
                # この大会は開始前の先発変更なし。先発9人に加え、継投で
                # 出場した選手も、打席が回らなかった場合を含めて記録する。
                starter_keys = {
                    (school_id, player_id)
                    for school_id in (detail["team1_school_id"], detail["team2_school_id"])
                    for player_id in self.resolver.team_input(
                        school_id=school_id,
                        reference_year=self.year,
                        generation_seed=self.seed,
                        competition_id=self.competition_id,
                    ).team_strength.starting_lineup.starter_ids
                }
                pitcher_keys = {
                    (row["school_id"], row["player_id"])
                    for row in detail["pitcher_stats"]
                }
                self.assertEqual(starter_keys | pitcher_keys, set(batter_keys))
                appearances = Counter(
                    (event["offense_school_id"], event["batter_id"])
                    for event in detail["events"]
                )
                self.assertTrue(set(appearances) <= set(batter_keys))
                for row in detail["batter_stats"]:
                    self.assertEqual(
                        appearances[row["school_id"], row["player_id"]],
                        row["plate_appearances"],
                    )
                self.assertEqual(2, len(detail["team_stats"]))
                self.assertTrue(detail["pitcher_stats"])
                self.assertEqual(
                    detail["team1_score"] + detail["team2_score"],
                    sum(
                        event["runs_scored"]
                        for event in detail["events"]
                    ),
                )

    def test_team_generation_is_cached_across_tournament(self):
        self.resolver.clear_cache()
        self.engine.run(self._annual())
        self.assertEqual(8, self.resolver.cache_size)

    def test_same_seed_reproduces_full_ability_tournament(self):
        self.resolver.clear_cache()
        first = self.engine.run(self._annual()).to_dict()
        self.resolver.clear_cache()
        second = self.engine.run(self._annual()).to_dict()
        self.assertEqual(first, second)

    def test_save_competition_run_writes_game_stats_and_events(self):
        run = self.engine.run(self._annual())
        expected_match_count = len(run.match_simulation_results)
        expected_event_count = sum(
            len(detail["events"])
            for detail in run.match_simulation_results.values()
        )
        expected_batters = [
            {"match_id": match_id, **row}
            for match_id, detail in run.match_simulation_results.items()
            for row in detail["batter_stats"]
        ]

        def batter_key(row):
            return row["match_id"], row["school_id"], row["player_id"]

        expected_keys = Counter(batter_key(row) for row in expected_batters)
        self.assertTrue(all(count == 1 for count in expected_keys.values()))
        self.assertTrue(any(row["plate_appearances"] == 0 for row in expected_batters))

        with tempfile.TemporaryDirectory() as td:
            paths = save_competition_run(run, td)
            required = {
                "summary_json",
                "matches_csv",
                "placements_csv",
                "ability_matches_csv",
                "batter_game_stats_csv",
                "pitcher_game_stats_csv",
                "team_game_stats_csv",
                "match_events_csv",
            }
            self.assertEqual(required, set(paths))

            with Path(paths["ability_matches_csv"]).open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                match_rows = list(csv.DictReader(f))
            self.assertEqual(expected_match_count, len(match_rows))
            self.assertTrue(
                all(
                    row["score_source"] == "ability_model_v1"
                    for row in match_rows
                )
            )

            with Path(paths["batter_game_stats_csv"]).open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                batter_rows = list(csv.DictReader(f))
            self.assertEqual(len(expected_batters), len(batter_rows))
            saved_keys = Counter(batter_key(row) for row in batter_rows)
            self.assertEqual(expected_keys, saved_keys)
            # 全成績値も照合し、0打席の行を誤って除外していないことを確認する。
            self.assertEqual(
                {batter_key(row): {key: str(value) for key, value in row.items()}
                 for row in expected_batters},
                {batter_key(row): row for row in batter_rows},
            )
            relieved_teams = 0
            for match_id, detail in run.match_simulation_results.items():
                for school_id in (detail["team1_school_id"], detail["team2_school_id"]):
                    pitchers = [row["player_id"] for row in detail["pitcher_stats"]
                                if row["school_id"] == school_id and row["batters_faced"] > 0]
                    if len(pitchers) > 1:
                        relieved_teams += 1
                        # 交代前・交代後の投手が両方CSVに一度ずつ保存される。
                        for player_id in pitchers:
                            self.assertEqual(1, saved_keys[match_id, school_id, player_id])
            self.assertGreater(relieved_teams, 0)

            with Path(paths["team_game_stats_csv"]).open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                team_rows = list(csv.DictReader(f))
            self.assertEqual(expected_match_count * 2, len(team_rows))

            with Path(paths["match_events_csv"]).open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                event_rows = list(csv.DictReader(f))
            self.assertEqual(expected_event_count, len(event_rows))

            payload = json.loads(
                Path(paths["summary_json"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                expected_match_count,
                len(payload["match_simulation_results"]),
            )

    def test_annual_winner_override_has_priority_over_ability_resolver(self):
        baseline = self.engine.run(self._annual())
        target = next(
            match
            for match in baseline.stage_executions[-1].matches
            if not match.is_bye and match.round_no == 1
        )
        forced = (
            target.team2
            if target.winner == target.team1
            else target.team1
        )

        annual = self._annual()
        annual.main_match_winner_overrides = {
            target.match_id: forced,
        }
        self.resolver.clear_cache()
        run = self.engine.run(annual)
        updated = next(
            match
            for match in run.stage_executions[-1].matches
            if match.match_id == target.match_id
        )

        self.assertEqual(forced, updated.winner)
        self.assertEqual(
            "annual_override",
            updated.metadata.get("winner_source"),
        )
        self.assertNotIn(
            target.match_id,
            run.match_simulation_results,
        )

    def test_without_main_match_resolver_existing_engine_behavior_remains(self):
        legacy = TournamentEngine(self.repo)
        run = legacy.run(self._annual())
        self.assertEqual({}, run.match_simulation_results)
        main = run.stage_executions[-1]
        self.assertTrue(
            all(
                match.metadata.get("winner_source") == "resolver"
                for match in main.matches
                if not match.is_bye
            )
        )


if __name__ == "__main__":
    unittest.main()
