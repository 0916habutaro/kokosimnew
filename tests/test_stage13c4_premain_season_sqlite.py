from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine import AnnualCompetitionInput, DataRepository, TournamentEngine
from phase2_engine.brackets import (
    random_winner_resolver,
    run_block_winner_forest,
    run_head_to_head,
    run_round_robin,
    run_single_elimination_ranking,
    run_single_round_gate,
)
from phase2_engine.browse_repository import BrowseRepository
from phase2_engine.models import MatchResolution
from phase2_engine.season import SeasonExecution, SeasonOrchestrator

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class StubDetailedResolver:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        *,
        match_id,
        competition_id,
        reference_year,
        generation_seed,
        team1,
        team2,
    ):
        self.calls.append(match_id)
        return MatchResolution(
            winner_id=team1,
            loser_id=team2,
            team1_score=2,
            team2_score=1,
            score_source="ability_model_v1",
            detail={
                "match_id": match_id,
                "competition_id": competition_id,
                "reference_year": reference_year,
                "generation_seed": generation_seed,
                "team1_school_id": team1,
                "team2_school_id": team2,
                "team1_score": 2,
                "team2_score": 1,
                "winner_id": team1,
                "loser_id": team2,
                "score_source": "ability_model_v1",
            },
        )


class Stage13C4PreMainSeasonSQLiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.seed = 2026100701
        cls.year = 2026

    def test_single_elimination_accepts_detailed_resolver(self):
        resolver = StubDetailedResolver()
        sink = {}
        ranking, matches = run_single_elimination_ranking(
            ["S1", "S2", "S3", "S4"],
            competition_id="C",
            stage_id="STG",
            stage_code="QUAL",
            phase_code="KO",
            group_id="G",
            group_name="Group",
            base_seed=1,
            winner_resolver=random_winner_resolver(1),
            match_resolver=resolver,
            resolved_match_sink=sink,
            reference_year=2026,
        )
        played = [m for m in matches if not m.is_bye]
        self.assertEqual(3, len(played))
        self.assertEqual(3, len(sink))
        self.assertEqual(3, len(resolver.calls))
        self.assertEqual("ability_model_v1", played[0].metadata["score_source"])
        self.assertEqual(2, played[0].metadata["team1_score"])
        self.assertEqual(ranking[0], played[-1].winner)

    def test_gate_accepts_detailed_resolver(self):
        resolver = StubDetailedResolver()
        sink = {}
        winners, matches = run_single_round_gate(
            ["S1", "S2", "S3", "S4"],
            competition_id="C",
            stage_id="STG",
            stage_code="GATE",
            phase_code="GATE",
            base_seed=2,
            winner_resolver=random_winner_resolver(2),
            match_resolver=resolver,
            resolved_match_sink=sink,
            reference_year=2026,
        )
        self.assertEqual(2, len(winners))
        self.assertEqual(2, len(sink))
        self.assertTrue(all(m.metadata["score_source"] == "ability_model_v1" for m in matches))

    def test_round_robin_accepts_detailed_resolver(self):
        resolver = StubDetailedResolver()
        sink = {}
        ranking, matches, standings = run_round_robin(
            ["S1", "S2", "S3"],
            competition_id="C",
            stage_id="STG",
            stage_code="QUAL",
            phase_code="RR",
            group_id="G",
            group_name="Group",
            pool_no=1,
            base_seed=3,
            winner_resolver=random_winner_resolver(3),
            match_resolver=resolver,
            resolved_match_sink=sink,
            reference_year=2026,
        )
        self.assertEqual(3, len(matches))
        self.assertEqual(3, len(sink))
        self.assertEqual(3, sum(v["wins"] for v in standings.values()))
        self.assertEqual(3, len(ranking))

    def test_head_to_head_accepts_detailed_resolver(self):
        resolver = StubDetailedResolver()
        sink = {}
        match = run_head_to_head(
            "S1",
            "S2",
            competition_id="C",
            stage_id="STG",
            stage_code="QUAL",
            phase_code="PLAYOFF",
            group_id="G",
            group_name="Group",
            match_no=1,
            base_seed=4,
            winner_resolver=random_winner_resolver(4),
            match_resolver=resolver,
            resolved_match_sink=sink,
            reference_year=2026,
        )
        self.assertEqual("S1", match.winner)
        self.assertEqual(1, len(sink))
        self.assertEqual("ability_model_v1", match.metadata["score_source"])

    def test_block_forest_propagates_detailed_resolver(self):
        resolver = StubDetailedResolver()
        sink = {}
        winners, matches, blocks = run_block_winner_forest(
            ["S1", "S2", "S3", "S4", "S5", "S6"],
            block_count=2,
            competition_id="C",
            stage_id="STG",
            stage_code="QUAL",
            phase_code="FOREST",
            group_id="G",
            group_name="Group",
            base_seed=5,
            winner_resolver=random_winner_resolver(5),
            match_resolver=resolver,
            resolved_match_sink=sink,
            reference_year=2026,
        )
        self.assertEqual(2, len(winners))
        self.assertEqual(2, len(blocks))
        self.assertEqual(len([m for m in matches if not m.is_bye]), len(sink))

    def test_season_orchestrator_wires_same_resolver_to_main_and_pre_main(self):
        resolver = StubDetailedResolver()
        orchestrator = SeasonOrchestrator(
            self.repo,
            DATA_ROOT,
            match_resolver=resolver,
        )
        self.assertIs(resolver, orchestrator.match_resolver)
        self.assertIs(resolver, orchestrator.engine.main_match_resolver)
        self.assertIs(resolver, orchestrator.engine.pre_main_match_resolver)

    def _ability_run(self):
        selected = None
        for competition_id, competition in sorted(self.repo.competitions.items()):
            stages = self.repo.stages(competition_id)
            if [stage["stage_code"] for stage in stages] != ["MAIN"]:
                continue
            pcode = competition.get("prefecture_code", "")
            if not pcode:
                continue
            ids = sorted(
                sid
                for sid, row in self.repo.schools.items()
                if row.get("prefecture_code") == pcode
                and sid in self.repo.school_to_program
            )
            if len(ids) >= 4:
                selected = (competition_id, ids[:4])
                break
        if selected is None:
            raise AssertionError("no four-school direct MAIN fixture")

        competition_id, school_ids = selected
        resolver = AbilityMatchResolver(
            self.repo,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        engine = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
            pre_main_match_resolver=resolver,
        )
        run = engine.run(AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=school_ids,
            rng_seed=self.seed,
        ))
        return run

    def test_real_gifu_premain_and_main_use_one_ability_result_path(self):
        competition_id = "CMP000110"
        seed_stage = self.repo.stage_by_code(
            competition_id,
            "SEED_EVENT",
        )
        target_counts = [20, 10, 18, 10]
        entrants = []
        overrides = {}
        for group, count in zip(
            self.repo.groups_by_stage[seed_stage["stage_id"]],
            target_counts,
        ):
            ids = sorted(
                self.repo.group_school_ids(group, self.year)
            )[:count]
            self.assertEqual(count, len(ids))
            entrants.extend(ids)
            overrides[group["stage_group_id"]] = ids

        resolver = AbilityMatchResolver(
            self.repo,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        engine = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
            pre_main_match_resolver=resolver,
        )
        run = engine.run(AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=entrants,
            rng_seed=self.seed,
            group_entrant_school_ids=overrides,
        ))

        self.assertEqual(
            ["SEED_EVENT", "FIRST_TOURNAMENT", "MAIN"],
            [stage.stage_code for stage in run.stage_executions],
        )
        played = [
            match
            for stage in run.stage_executions
            for match in stage.matches
            if not match.is_bye
        ]
        self.assertTrue(played)
        self.assertEqual(
            {match.match_id for match in played},
            set(run.match_simulation_results),
        )
        self.assertTrue(all(
            match.metadata.get("score_source")
            == "ability_model_v1"
            for match in played
        ))
        self.assertIn(
            run.outcome.champion_school_id,
            run.main_entrant_school_ids,
        )
        self.assertEqual(len(set(entrants)), resolver.cache_size)

    def test_sqlite_schema_v2_contains_game_detail_tables(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "game.sqlite3"
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
            self.assertEqual(2, version)
            self.assertTrue({
                "ability_matches",
                "batter_game_stats",
                "pitcher_game_stats",
                "team_game_stats",
                "match_events",
            }.issubset(tables))

    def test_ability_game_results_round_trip_through_sqlite(self):
        run = self._ability_run()
        season = SeasonExecution(
            year=self.year,
            rng_seed=self.seed,
            competition_runs={run.competition_id: run},
        )
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "game.sqlite3"
            repository = BrowseRepository(db)
            repository.initialize_schema()
            # Detailed results require an owning browse_seasons row.
            with repository._connect() as conn:
                repository._initialize_schema_conn(conn)
                with conn:
                    conn.execute(
                        """
                        INSERT INTO browse_seasons (
                            year, rng_seed, schema_version,
                            match_count, competition_count, school_count
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (self.year, self.seed, 2, 3, 1, 4),
                    )
            summary = repository.replace_season_match_results(season)
            self.assertEqual(3, summary["ability_match_count"])
            self.assertEqual(54, summary["batter_game_stat_count"])
            self.assertEqual(6, summary["team_game_stat_count"])
            self.assertGreater(summary["pitcher_game_stat_count"], 0)
            self.assertGreater(summary["match_event_count"], 0)

            match_id = sorted(run.match_simulation_results)[0]
            stored = repository.ability_match(
                self.year,
                run.competition_id,
                match_id,
            )
            original = run.match_simulation_results[match_id]
            self.assertEqual(original["winner_id"], stored["winner_id"])
            self.assertEqual(original["team1_score"], stored["team1_score"])

            player_id = original["batter_stats"][0]["player_id"]
            batter_rows = repository.player_batter_game_stats(
                self.year,
                player_id,
            )
            self.assertTrue(batter_rows)

            events = repository.events_for_match(
                self.year,
                run.competition_id,
                match_id,
            )
            self.assertEqual(len(original["events"]), len(events))


if __name__ == "__main__":
    unittest.main()
