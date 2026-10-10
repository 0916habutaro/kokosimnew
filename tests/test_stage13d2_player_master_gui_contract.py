from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine import (
    AnnualCompetitionInput,
    DataRepository,
    PlayerStatsReadModel,
    TournamentEngine,
)
from phase2_engine.browse_gui_model import BrowseGuiModel
from phase2_engine.browse_repository import BrowseRepository, SCHEMA_VERSION
from phase2_engine.season import SeasonExecution

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
ABILITY_CONFIG = ROOT / "config" / "abilities"
MATCH_CONFIG = ROOT / "config" / "match"
STATS_CONFIG = ROOT / "config" / "stats" / "player_rankings_v1.json"


class Stage13D2PlayerMasterGuiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.year = 2026
        cls.season_seed = 2026100701
        cls.school_ids = sorted(cls.repo.school_to_program)[:4]

    def _resolver(self) -> AbilityMatchResolver:
        resolver = AbilityMatchResolver(
            self.repo,
            ability_config_dir=ABILITY_CONFIG,
            match_config_dir=MATCH_CONFIG,
        )
        resolver.begin_season(self.year, self.season_seed)
        return resolver

    def test_season_identity_seed_is_stable_across_match_seeds(self):
        resolver = self._resolver()
        school_id = self.school_ids[0]

        first = resolver.team_input(
            school_id=school_id,
            reference_year=self.year,
            generation_seed=111,
        )
        second = resolver.team_input(
            school_id=school_id,
            reference_year=self.year,
            generation_seed=222,
        )

        self.assertIs(first, second)
        self.assertEqual(1, resolver.cache_size)
        self.assertEqual(
            self.season_seed,
            first.team_strength.generation_seed,
        )
        self.assertEqual(
            {self.season_seed},
            {p.generation_seed for p in first.player_abilities},
        )
        self.assertEqual(
            [p.player_id for p in first.player_abilities],
            [p.player_id for p in second.player_abilities],
        )

    def test_match_seed_and_team_generation_seed_are_independent(self):
        resolver = self._resolver()
        first = resolver(
            match_id="D2-M1",
            competition_id="CMP-D2-A",
            reference_year=self.year,
            generation_seed=111,
            team1=self.school_ids[0],
            team2=self.school_ids[1],
        )
        second = resolver(
            match_id="D2-M2",
            competition_id="CMP-D2-B",
            reference_year=self.year,
            generation_seed=222,
            team1=self.school_ids[0],
            team2=self.school_ids[1],
        )

        self.assertEqual(
            self.season_seed,
            first.detail["team_generation_seed"],
        )
        self.assertEqual(
            self.season_seed,
            second.detail["team_generation_seed"],
        )
        first_players = {
            row["player_id"] for row in first.detail["batter_stats"]
        }
        second_players = {
            row["player_id"] for row in second.detail["batter_stats"]
        }
        self.assertEqual(first_players, second_players)

    def test_player_master_snapshot_is_one_row_per_player(self):
        resolver = self._resolver()
        for school_id in self.school_ids[:2]:
            resolver.team_input(
                school_id=school_id,
                reference_year=self.year,
                generation_seed=999,
            )
        records = resolver.player_master_records()

        self.assertEqual(40, len(records))
        self.assertEqual(40, len(set(records)))
        for player_id, row in records.items():
            with self.subTest(player_id=player_id):
                self.assertEqual(player_id, row["player_id"])
                self.assertEqual(self.year, row["reference_year"])
                self.assertEqual(
                    self.season_seed,
                    row["generation_seed"],
                )
                self.assertTrue(row["display_name"])
                self.assertIn(row["academic_year"], {1, 2, 3})
                self.assertIn(
                    row["primary_position"],
                    {"P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"},
                )

    def _ability_run_and_master(self):
        selected = None
        for competition_id, competition in sorted(
            self.repo.competitions.items()
        ):
            stages = self.repo.stages(competition_id)
            if [stage["stage_code"] for stage in stages] != ["MAIN"]:
                continue
            prefecture_code = competition.get("prefecture_code", "")
            ids = sorted(
                school_id
                for school_id, row in self.repo.schools.items()
                if row.get("prefecture_code") == prefecture_code
                and school_id in self.repo.school_to_program
            )
            if len(ids) >= 4:
                selected = (competition_id, ids[:4])
                break
        if selected is None:
            raise AssertionError("no direct MAIN competition fixture")

        competition_id, school_ids = selected
        resolver = self._resolver()
        engine = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
            pre_main_match_resolver=resolver,
        )
        run = engine.run(
            AnnualCompetitionInput(
                competition_id=competition_id,
                year=self.year,
                entrant_school_ids=school_ids,
                rng_seed=123456,
            )
        )
        return run, school_ids, resolver.player_master_records()

    def _prepare_sqlite(self):
        run, school_ids, master = self._ability_run_and_master()
        season = SeasonExecution(
            year=self.year,
            rng_seed=self.season_seed,
            competition_runs={run.competition_id: run},
            player_master_records=master,
        )
        tmp = tempfile.TemporaryDirectory()
        db = Path(tmp.name) / "browse.sqlite3"
        repository = BrowseRepository(db)
        repository.initialize_schema()

        with repository._connect() as conn:
            repository._initialize_schema_conn(conn)
            with conn:
                conn.execute(
                    """
                    INSERT INTO browse_seasons (
                        year, rng_seed, schema_version,
                        match_count, competition_count, school_count
                    ) VALUES (?, ?, 3, 3, 1, 4)
                    """,
                    (self.year, self.season_seed),
                )
                for school_id in school_ids:
                    conn.execute(
                        """
                        INSERT INTO school_records (
                            year, school_id, school_name, prefecture_code,
                            competition_count, competition_ids,
                            games, wins, losses, win_pct,
                            runs_for, runs_against, run_differential,
                            titles, runner_up_finishes, last_game_date
                        ) VALUES (
                            ?, ?, ?, '',
                            1, ?, 0, 0, 0, 0.0,
                            0, 0, 0, 0, 0, ''
                        )
                        """,
                        (
                            self.year,
                            school_id,
                            self.repo.team(school_id).display_name,
                            run.competition_id,
                        ),
                    )
        repository.replace_season_player_master(season)
        repository.replace_season_match_results(season)
        return tmp, db, repository, run, school_ids

    def test_sqlite_schema_v3_persists_player_master(self):
        tmp, db, repository, run, school_ids = self._prepare_sqlite()
        self.addCleanup(tmp.cleanup)

        with sqlite3.connect(db) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            count = conn.execute(
                "SELECT COUNT(*) FROM player_master WHERE year = ?",
                (self.year,),
            ).fetchone()[0]
        self.assertEqual(SCHEMA_VERSION, version)
        self.assertEqual(80, count)

        roster = repository.school_roster(
            self.year,
            school_ids[0],
        )
        self.assertEqual(20, len(roster))
        self.assertEqual(
            list(range(1, 21)),
            [row["roster_no"] for row in roster],
        )
        self.assertTrue(all(row["display_name"] for row in roster))

    def test_player_stats_join_master_display_fields(self):
        tmp, db, repository, run, school_ids = self._prepare_sqlite()
        self.addCleanup(tmp.cleanup)
        stats = PlayerStatsReadModel(
            repository,
            config_path=STATS_CONFIG,
        )
        detail = next(iter(run.match_simulation_results.values()))
        player_id = detail["batter_stats"][0]["player_id"]

        summary = stats.player_summary(self.year, player_id)
        self.assertIsNotNone(summary["player"])
        self.assertEqual(
            summary["player"]["display_name"],
            summary["batter"]["player_name"],
        )
        self.assertGreater(summary["batter"]["academic_year"], 0)
        self.assertTrue(summary["batter"]["primary_position"])

        leaders = stats.batter_rankings(
            self.year,
            "hits",
            limit=10,
        )
        self.assertTrue(leaders)
        self.assertTrue(all(row.player_name for row in leaders))

    def test_school_roster_summary_contains_stats_and_bench_players(self):
        tmp, db, repository, run, school_ids = self._prepare_sqlite()
        self.addCleanup(tmp.cleanup)
        stats = PlayerStatsReadModel(
            repository,
            config_path=STATS_CONFIG,
        )
        rows = stats.school_roster_summary(
            self.year,
            school_ids[0],
        )

        self.assertEqual(20, len(rows))
        self.assertTrue(all(row["player"]["display_name"] for row in rows))
        self.assertTrue(any(row["batter"] is not None for row in rows))
        self.assertTrue(
            any(
                row["batter"] is None and row["pitcher"] is None
                for row in rows
            )
        )

    def test_gui_contract_exposes_roster_player_and_rankings(self):
        tmp, db, repository, run, school_ids = self._prepare_sqlite()
        self.addCleanup(tmp.cleanup)
        gui = BrowseGuiModel(db, data_dir=DATA_ROOT)

        roster = gui.school_roster_stats(
            self.year,
            school_ids[0],
        )
        self.assertEqual(20, len(roster))

        player_id = next(
            row["player"]["player_id"]
            for row in roster
            if row["batter"] is not None
        )
        detail = gui.player_detail(self.year, player_id)
        self.assertEqual(
            detail["player"]["display_name"],
            detail["batter"]["player_name"],
        )

        search = gui.search_players(
            self.year,
            text=detail["player"]["display_name"],
            school_id=school_ids[0],
        )
        self.assertTrue(
            any(row["player_id"] == player_id for row in search)
        )

        boards = gui.competition_leaderboards(
            self.year,
            run.competition_id,
            batting_metric="hits",
            pitching_metric="strikeouts",
            limit=10,
        )
        self.assertEqual(run.competition_id, boards["competition_id"])
        self.assertTrue(boards["batting"])
        self.assertTrue(boards["pitching"])
        self.assertTrue(boards["batting"][0]["player_name"])

    def test_season_summary_reports_player_master_count(self):
        season = SeasonExecution(
            year=self.year,
            rng_seed=self.season_seed,
            player_master_records={
                "P1": {
                    "player_id": "P1",
                },
                "P2": {
                    "player_id": "P2",
                },
            },
        )
        self.assertEqual(2, season.summary()["player_master_count"])


if __name__ == "__main__":
    unittest.main()
