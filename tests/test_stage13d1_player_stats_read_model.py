from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from phase2_engine.browse_gui_model import BrowseGuiModel
from phase2_engine.browse_repository import BrowseRepository
from phase2_engine.player_stats_read_model import PlayerStatsReadModel

ROOT = Path(__file__).resolve().parents[1]
STATS_CONFIG = ROOT / "config" / "stats" / "player_rankings_v1.json"


class Stage13D1PlayerStatsReadModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "stats.sqlite3"
        self.repo = BrowseRepository(self.db)
        self.repo.initialize_schema()
        self._insert_fixture()
        self.model = PlayerStatsReadModel(
            self.repo,
            config_path=STATS_CONFIG,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _insert_fixture(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                INSERT INTO browse_seasons (
                    year, rng_seed, schema_version,
                    match_count, competition_count, school_count
                ) VALUES (2026, 7, 2, 2, 2, 2)
                """
            )
            for school_id, school_name in (
                ("S1", "第一高校"),
                ("S2", "第二高校"),
            ):
                conn.execute(
                    """
                    INSERT INTO school_records (
                        year, school_id, school_name, prefecture_code,
                        competition_count, competition_ids,
                        games, wins, losses, win_pct,
                        runs_for, runs_against, run_differential,
                        titles, runner_up_finishes, last_game_date
                    ) VALUES (
                        2026, ?, ?, '01',
                        2, 'CMP-A;CMP-B',
                        2, 1, 1, 0.5,
                        5, 5, 0,
                        0, 0, '2026-07-02'
                    )
                    """,
                    (school_id, school_name),
                )

            self._insert_match(conn, "CMP-A", "M1", 5, 2)
            self._insert_match(conn, "CMP-B", "M2", 3, 4)

            for competition_id, match_id in (
                ("CMP-A", "M1"),
                ("CMP-B", "M2"),
            ):
                for school_id in ("S1", "S2"):
                    conn.execute(
                        """
                        INSERT INTO team_game_stats (
                            year, competition_id, match_id,
                            school_id, runs, hits, errors
                        ) VALUES (2026, ?, ?, ?, 0, 0, 0)
                        """,
                        (competition_id, match_id, school_id),
                    )

            # B1: season AB=8, H=4, BB=1, TB=11.
            self._insert_batter(
                conn,
                "CMP-A",
                "M1",
                "B1",
                "S1",
                pa=5,
                ab=4,
                runs=2,
                hits=2,
                singles=1,
                doubles=1,
                triples=0,
                hr=0,
                rbi=2,
                walks=1,
                so=1,
                hbp=0,
                sf=0,
                sh=0,
            )
            self._insert_batter(
                conn,
                "CMP-B",
                "M2",
                "B1",
                "S1",
                pa=4,
                ab=4,
                runs=2,
                hits=2,
                singles=0,
                doubles=0,
                triples=0,
                hr=2,
                rbi=4,
                walks=0,
                so=1,
                hbp=0,
                sf=0,
                sh=0,
            )

            # B2 is intentionally below the season rate qualification.
            self._insert_batter(
                conn,
                "CMP-A",
                "M1",
                "B2",
                "S1",
                pa=1,
                ab=1,
                runs=1,
                hits=1,
                singles=0,
                doubles=0,
                triples=0,
                hr=1,
                rbi=1,
                walks=0,
                so=0,
                hbp=0,
                sf=0,
                sh=0,
            )
            self._insert_batter(
                conn,
                "CMP-B",
                "M2",
                "B2",
                "S1",
                pa=1,
                ab=1,
                runs=0,
                hits=1,
                singles=1,
                doubles=0,
                triples=0,
                hr=0,
                rbi=0,
                walks=0,
                so=0,
                hbp=0,
                sf=0,
                sh=0,
            )

            # B3 creates a count-stat tie on home runs with B1.
            self._insert_batter(
                conn,
                "CMP-A",
                "M1",
                "B3",
                "S2",
                pa=4,
                ab=4,
                runs=2,
                hits=3,
                singles=1,
                doubles=0,
                triples=0,
                hr=2,
                rbi=3,
                walks=0,
                so=1,
                hbp=0,
                sf=0,
                sh=0,
            )

            # P1 season: 15 outs = 5 IP, ER=3, H=5, BB=2, K=7, BF=22.
            self._insert_pitcher(
                conn,
                "CMP-A",
                "M1",
                "P1",
                "S1",
                outs=9,
                bf=12,
                runs=1,
                er=1,
                hits=2,
                hr=0,
                walks=1,
                so=4,
                hbp=0,
            )
            self._insert_pitcher(
                conn,
                "CMP-B",
                "M2",
                "P1",
                "S1",
                outs=6,
                bf=10,
                runs=2,
                er=2,
                hits=3,
                hr=1,
                walks=1,
                so=3,
                hbp=0,
            )

            # P2 has excellent one-game rates but is below season qualification.
            self._insert_pitcher(
                conn,
                "CMP-A",
                "M1",
                "P2",
                "S1",
                outs=3,
                bf=4,
                runs=0,
                er=0,
                hits=0,
                hr=0,
                walks=0,
                so=4,
                hbp=0,
            )
            conn.commit()

    @staticmethod
    def _insert_match(conn, competition_id, match_id, score1, score2):
        winner = "S1" if score1 > score2 else "S2"
        loser = "S2" if winner == "S1" else "S1"
        conn.execute(
            """
            INSERT INTO ability_matches (
                year, competition_id, match_id, generation_seed,
                team1_school_id, team2_school_id,
                team1_score, team2_score, winner_id, loser_id,
                last_inning, ending_half, score_source,
                match_config_id, match_config_revision, match_config_sha256,
                event_catalog_id, event_catalog_revision, event_catalog_sha256,
                stats_config_id, stats_config_revision, stats_config_sha256
            ) VALUES (
                2026, ?, ?, 7,
                'S1', 'S2',
                ?, ?, ?, ?,
                9, 'bottom', 'ability_model_v1',
                'match_simulation_v1', 2, ?,
                'event_catalog_v1', 1, ?,
                'game_stats_contract_v1', 1, ?
            )
            """,
            (
                competition_id,
                match_id,
                score1,
                score2,
                winner,
                loser,
                "a" * 64,
                "b" * 64,
                "c" * 64,
            ),
        )

    @staticmethod
    def _insert_batter(
        conn,
        competition_id,
        match_id,
        player_id,
        school_id,
        *,
        pa,
        ab,
        runs,
        hits,
        singles,
        doubles,
        triples,
        hr,
        rbi,
        walks,
        so,
        hbp,
        sf,
        sh,
    ):
        conn.execute(
            """
            INSERT INTO batter_game_stats (
                year, competition_id, match_id, player_id, school_id,
                plate_appearances, at_bats, runs, hits,
                doubles, triples, home_runs, rbi, walks, strikeouts,
                hit_by_pitch, sacrifice_flies, sacrifice_bunts,
                stolen_bases, caught_stealing, singles
            ) VALUES (
                2026, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                0, 0, ?
            )
            """,
            (
                competition_id,
                match_id,
                player_id,
                school_id,
                pa,
                ab,
                runs,
                hits,
                doubles,
                triples,
                hr,
                rbi,
                walks,
                so,
                hbp,
                sf,
                sh,
                singles,
            ),
        )

    @staticmethod
    def _insert_pitcher(
        conn,
        competition_id,
        match_id,
        player_id,
        school_id,
        *,
        outs,
        bf,
        runs,
        er,
        hits,
        hr,
        walks,
        so,
        hbp,
    ):
        conn.execute(
            """
            INSERT INTO pitcher_game_stats (
                year, competition_id, match_id, player_id, school_id,
                outs_recorded, batters_faced, runs_allowed, earned_runs,
                hits_allowed, home_runs_allowed, walks, strikeouts, hit_batters
            ) VALUES (
                2026, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                competition_id,
                match_id,
                player_id,
                school_id,
                outs,
                bf,
                runs,
                er,
                hits,
                hr,
                walks,
                so,
                hbp,
            ),
        )

    def test_batter_season_rates_are_derived_from_counts(self):
        row = self.model.batter_aggregates(
            2026,
            player_id="B1",
        )[0]
        self.assertEqual(2, row.games)
        self.assertEqual(2, row.team_games)
        self.assertEqual(9, row.plate_appearances)
        self.assertEqual(8, row.at_bats)
        self.assertEqual(4, row.hits)
        self.assertEqual(11, row.total_bases)
        self.assertEqual(0.5, row.batting_average)
        self.assertEqual(0.556, row.on_base_percentage)
        self.assertEqual(1.375, row.slugging_percentage)
        self.assertEqual(1.931, row.ops)
        self.assertEqual(0.875, row.isolated_power)
        self.assertTrue(row.qualified_for_rate_rankings)

    def test_pitcher_season_rates_use_outs_not_decimal_innings(self):
        row = self.model.pitcher_aggregates(
            2026,
            player_id="P1",
        )[0]
        self.assertEqual(15, row.outs_recorded)
        self.assertEqual("5", row.innings_pitched_display)
        self.assertEqual(5.4, row.earned_run_average)
        self.assertEqual(1.4, row.whip)
        self.assertEqual(12.6, row.strikeouts_per_9)
        self.assertEqual(3.6, row.walks_per_9)
        self.assertEqual(3.5, row.strikeout_walk_ratio)
        self.assertEqual(0.227, row.k_minus_bb_pct)
        self.assertTrue(row.qualified_for_rate_rankings)

    def test_fractional_innings_are_displayed_as_fraction_not_decimal(self):
        self.assertEqual("6 2/3", self.model.innings_display(20))
        self.assertEqual("6 1/3", self.model.innings_display(19))

    def test_rate_rankings_exclude_unqualified_batters(self):
        rows = self.model.batter_rankings(
            2026,
            "batting_average",
        )
        self.assertEqual(["B3", "B1"], [row.player_id for row in rows])
        self.assertNotIn("B2", {row.player_id for row in rows})

    def test_count_rankings_include_unqualified_batters_and_share_rank(self):
        rows = self.model.batter_rankings(
            2026,
            "home_runs",
        )
        leaders = [row for row in rows if row.value == 2]
        self.assertEqual({"B1", "B3"}, {row.player_id for row in leaders})
        self.assertEqual({1}, {row.rank for row in leaders})

    def test_pitching_rate_rankings_exclude_unqualified_pitcher(self):
        era = self.model.pitcher_rankings(2026, "earned_run_average")
        self.assertEqual(["P1"], [row.player_id for row in era])
        strikeouts = self.model.pitcher_rankings(2026, "strikeouts")
        self.assertEqual("P1", strikeouts[0].player_id)
        self.assertIn("P2", {row.player_id for row in strikeouts})

    def test_competition_filter_recalculates_counts_and_qualification(self):
        row = self.model.batter_aggregates(
            2026,
            competition_id="CMP-A",
            player_id="B1",
        )[0]
        self.assertEqual(1, row.team_games)
        self.assertEqual(5, row.plate_appearances)
        self.assertEqual(0.5, row.batting_average)
        self.assertTrue(row.qualified_for_rate_rankings)

        pitcher = self.model.pitcher_aggregates(
            2026,
            competition_id="CMP-B",
            player_id="P1",
        )[0]
        self.assertEqual(1, pitcher.team_games)
        self.assertEqual(6, pitcher.outs_recorded)
        self.assertTrue(pitcher.qualified_for_rate_rankings)

    def test_school_filter_limits_rankings(self):
        rows = self.model.batter_rankings(
            2026,
            "home_runs",
            school_id="S2",
        )
        self.assertEqual(["B3"], [row.player_id for row in rows])
        self.assertEqual("第二高校", rows[0].school_name)

    def test_player_summary_contains_batter_and_pitcher_sides(self):
        summary = self.model.player_summary(2026, "P1")
        self.assertIsNone(summary["batter"])
        self.assertIsNotNone(summary["pitcher"])

        summary = self.model.player_summary(2026, "B1")
        self.assertIsNotNone(summary["batter"])
        self.assertIsNone(summary["pitcher"])

    def test_invalid_ranking_metric_and_limit_are_rejected(self):
        with self.assertRaises(ValueError):
            self.model.batter_rankings(2026, "unknown")
        with self.assertRaises(ValueError):
            self.model.pitcher_rankings(2026, "unknown")
        with self.assertRaises(ValueError):
            self.model.batter_rankings(2026, "hits", limit=0)

    def test_gui_model_exposes_player_stats_and_leaderboards(self):
        gui = BrowseGuiModel(
            self.db,
            data_dir=ROOT / "data",
        )
        summary = gui.player_stats_summary(2026, "B1")
        self.assertEqual(4, summary["batter"]["hits"])

        leaders = gui.batting_leaderboard(
            2026,
            "home_runs",
            limit=2,
        )
        self.assertEqual(2, len(leaders))
        self.assertEqual(1, leaders[0]["rank"])

        pitchers = gui.pitching_leaderboard(
            2026,
            "earned_run_average",
        )
        self.assertEqual(["P1"], [row["player_id"] for row in pitchers])

    def test_config_explicitly_marks_qualification_as_game_design(self):
        self.assertEqual(
            "design_default_not_tuned",
            self.model.config["status"],
        )
        self.assertTrue(
            self.model.config["rules"][
                "ranking_qualification_is_game_design_not_official_rule"
            ]
        )


if __name__ == "__main__":
    unittest.main()
