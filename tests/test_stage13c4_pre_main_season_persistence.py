from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine.browse_repository import BrowseRepository, SCHEMA_VERSION
from phase2_engine.browse_views import SeasonBrowseViews
from phase2_engine.repository import DataRepository
from phase2_engine.result_view import build_competition_result_view
from phase2_engine.season import (
    SeasonExecution,
    SeasonOrchestrator,
    StructuralAnnualInputFactory,
)
from phase2_engine.engine import TournamentEngine

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class Stage13C4PreMainSeasonPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.seed = 2026100701
        cls.year = 2026
        cls.factory = StructuralAnnualInputFactory(
            cls.repo,
            DATA,
            cls.seed,
        )

        candidates = []
        for competition_id in sorted(cls.repo.competitions):
            stages = cls.repo.stages(competition_id)
            codes = {stage["stage_code"] for stage in stages}
            if "MAIN" not in codes or codes == {"MAIN"}:
                continue
            if cls.repo.access_rules(competition_id):
                continue
            try:
                annual = cls.factory.build_prefectural(
                    competition_id,
                    cls.year,
                    rng_seed=cls.seed,
                )
            except (ValueError, KeyError, NotImplementedError):
                continue
            if len(annual.entrant_school_ids) < 2:
                continue
            candidates.append(
                (len(annual.entrant_school_ids), competition_id, annual)
            )

        if not candidates:
            raise AssertionError(
                "no pre-MAIN prefectural competition available for Stage 13C-4 test"
            )

        _, cls.competition_id, cls.annual = min(candidates)
        cls.resolver = AbilityMatchResolver(
            cls.repo,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        cls.engine = TournamentEngine(
            cls.repo,
            match_resolver=cls.resolver,
        )
        cls.competition_run = cls.engine.run(cls.annual)

    def test_selected_competition_really_has_pre_main_stage(self):
        stage_codes = [
            execution.stage_code
            for execution in self.competition_run.stage_executions
        ]
        self.assertIn("MAIN", stage_codes)
        self.assertTrue(any(code != "MAIN" for code in stage_codes))

    def test_every_non_bye_match_across_all_stages_uses_ability_model(self):
        matches = [
            match
            for execution in self.competition_run.stage_executions
            for match in execution.matches
            if not match.is_bye
        ]
        self.assertTrue(matches)
        self.assertEqual(
            {match.match_id for match in matches},
            set(self.competition_run.match_simulation_results),
        )
        for match in matches:
            with self.subTest(match_id=match.match_id):
                self.assertEqual(
                    "ability_model_v1",
                    match.metadata.get("score_source"),
                )
                detail = self.competition_run.match_simulation_results[match.match_id]
                self.assertEqual(match.winner, detail["winner_id"])
                self.assertEqual(match.loser, detail["loser_id"])
                self.assertEqual(
                    match.metadata["team1_score"],
                    detail["team1_score"],
                )
                self.assertEqual(
                    match.metadata["team2_score"],
                    detail["team2_score"],
                )

    def test_pre_main_ability_winners_feed_later_stages(self):
        executions = self.competition_run.stage_executions
        main = executions[-1]
        self.assertEqual("MAIN", main.stage_code)
        self.assertEqual(
            set(self.competition_run.main_entrant_school_ids),
            set(main.entrant_school_ids),
        )
        for execution in executions[:-1]:
            for school_id in execution.output_school_ids:
                self.assertIn(school_id, self.competition_run.entrant_school_ids)

    def test_result_view_needs_no_explicit_ability_score_mapping(self):
        rows = build_competition_result_view(self.competition_run, self.repo)
        played = [row for row in rows if not row.is_bye]
        self.assertEqual(
            len(self.competition_run.match_simulation_results),
            len(played),
        )
        self.assertTrue(
            all(row.score_source == "ability_model_v1" for row in played)
        )

    def test_season_orchestrator_accepts_same_general_resolver(self):
        orchestrator = SeasonOrchestrator(
            self.repo,
            DATA,
            match_resolver=self.resolver,
        )
        self.assertIs(orchestrator.match_resolver, self.resolver)
        self.assertIs(orchestrator.engine.match_resolver, self.resolver)
        self.assertIs(orchestrator.engine.main_match_resolver, self.resolver)

    def test_sqlite_schema_v2_contains_game_data_tables(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "season.sqlite3"
            repository = BrowseRepository(db)
            repository.initialize_schema()
            with sqlite3.connect(db) as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
        self.assertEqual(2, SCHEMA_VERSION)
        self.assertEqual(2, version)
        self.assertTrue({
            "ability_matches",
            "batter_game_stats",
            "pitcher_game_stats",
            "team_game_stats",
            "match_events",
        }.issubset(tables))

    def test_sqlite_persists_full_competition_game_data(self):
        season = SeasonExecution(
            year=self.year,
            rng_seed=self.seed,
            competition_runs={
                self.competition_id: self.competition_run,
            },
        )
        empty_views = SeasonBrowseViews(
            matches_by_date=[],
            competition_results=[],
            school_records=[],
        )
        expected_matches = len(self.competition_run.match_simulation_results)
        expected_batters = sum(
            len(detail["batter_stats"])
            for detail in self.competition_run.match_simulation_results.values()
        )
        expected_pitchers = sum(
            len(detail["pitcher_stats"])
            for detail in self.competition_run.match_simulation_results.values()
        )
        expected_teams = sum(
            len(detail["team_stats"])
            for detail in self.competition_run.match_simulation_results.values()
        )
        expected_events = sum(
            len(detail["events"])
            for detail in self.competition_run.match_simulation_results.values()
        )

        with tempfile.TemporaryDirectory() as td:
            repository = BrowseRepository(Path(td) / "season.sqlite3")
            repository.replace_season_views(
                self.year,
                self.seed,
                empty_views,
            )
            summary = repository.replace_season_game_data(season)

            self.assertEqual(
                expected_matches,
                summary["ability_match_count"],
            )
            self.assertEqual(
                expected_batters,
                summary["batter_game_stat_count"],
            )
            self.assertEqual(
                expected_pitchers,
                summary["pitcher_game_stat_count"],
            )
            self.assertEqual(
                expected_teams,
                summary["team_game_stat_count"],
            )
            self.assertEqual(
                expected_events,
                summary["match_event_count"],
            )

            matches = repository.ability_matches(
                self.year,
                competition_id=self.competition_id,
            )
            self.assertEqual(expected_matches, len(matches))

            detail = next(iter(self.competition_run.match_simulation_results.values()))
            batter = detail["batter_stats"][0]
            batter_games = repository.batter_games(
                self.year,
                batter["player_id"],
            )
            self.assertTrue(batter_games)
            self.assertEqual(
                batter["player_id"],
                batter_games[0]["player_id"],
            )

            pitcher = detail["pitcher_stats"][0]
            pitcher_games = repository.pitcher_games(
                self.year,
                pitcher["player_id"],
            )
            self.assertTrue(pitcher_games)

            events = repository.events_for_match(
                self.year,
                self.competition_id,
                detail["match_id"],
            )
            self.assertEqual(len(detail["events"]), len(events))
            self.assertEqual(
                list(range(1, len(events) + 1)),
                [row["event_no"] for row in events],
            )

    def test_replacing_same_year_game_data_is_idempotent(self):
        season = SeasonExecution(
            year=self.year,
            rng_seed=self.seed,
            competition_runs={self.competition_id: self.run},
        )
        with tempfile.TemporaryDirectory() as td:
            repository = BrowseRepository(Path(td) / "season.sqlite3")
            repository.replace_season_views(
                self.year,
                self.seed,
                SeasonBrowseViews([], [], []),
            )
            first = repository.replace_season_game_data(season)
            second = repository.replace_season_game_data(season)
            self.assertEqual(
                first["ability_match_count"],
                second["ability_match_count"],
            )
            self.assertEqual(
                first["ability_match_count"],
                len(repository.ability_matches(self.year)),
            )

    def test_cli_exposes_ability_match_model_switch(self):
        source = (
            ROOT / "phase2_engine" / "season_cli.py"
        ).read_text(encoding="utf-8")
        self.assertIn("--match-model", source)
        self.assertIn('choices=("legacy", "ability")', source)
        self.assertIn("AbilityMatchResolver", source)

    def test_main_only_backward_alias_is_preserved(self):
        from game_core.tournament_bridge import (
            AbilityMainMatchResolver,
        )

        self.assertIs(AbilityMainMatchResolver, AbilityMatchResolver)


if __name__ == "__main__":
    unittest.main()
