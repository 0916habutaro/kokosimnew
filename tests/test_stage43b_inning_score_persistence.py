from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from game_core.match_contract import (
    MatchSimulationInput, TeamMatchInput,
    validate_match_simulation_result,
)
from game_core.match_simulator import MatchSimulator
from game_core.players import PlayerRosterGenerator
from game_core.school_intake import SchoolAwarePlayerAbilityGenerator
from game_core.team_strength import TeamStrengthGenerator
from phase2_engine.browse_repository import BrowseRepository, SCHEMA_VERSION
from phase2_engine.browse_views import SeasonBrowseViews
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701


class Stage43BInningScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo = DataRepository(ROOT / "data")
        ids = sorted(repo.school_to_program)[:2]
        rosters = PlayerRosterGenerator()
        abilities = SchoolAwarePlayerAbilityGenerator(ROOT / "config" / "abilities")
        strength = TeamStrengthGenerator(ROOT / "config" / "abilities")
        teams = []
        for school_id in ids:
            roster = rosters.generate_for_school_id(repo, school_id, 2026, SEED)
            snapshots = tuple(abilities.iter_roster(roster.players, 2026, SEED))
            teams.append(TeamMatchInput(
                school_id=school_id,
                team_strength=strength.generate(snapshots),
                player_abilities=snapshots,
            ))
        cls.match_input = MatchSimulationInput(
            match_id="STAGE43B-001", competition_id="CMP-STAGE43B",
            reference_year=2026, generation_seed=SEED,
            team1=teams[0], team2=teams[1],
        )
        cls.simulator = MatchSimulator(ROOT / "config" / "match")
        cls.result = cls.simulator.simulate(cls.match_input)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "history.sqlite3"
        self.repository = BrowseRepository(self.db)
        self.repository.replace_season_views(2026, SEED, SeasonBrowseViews())

    def tearDown(self):
        self.tmp.cleanup()

    def _season(self, detail):
        return SimpleNamespace(
            year=2026,
            competition_runs={
                self.match_input.competition_id: SimpleNamespace(
                    match_simulation_results={self.match_input.match_id: detail},
                )
            },
        )

    def test_all_half_innings_have_explicit_played_or_skipped_state(self):
        result = self.result
        rows = result.inning_scores
        self.assertIsNotNone(rows)
        self.assertEqual(result.last_inning * 2, len(rows))
        self.assertEqual(
            [(i, half) for i in range(1, result.last_inning + 1)
             for half in ("top", "bottom")],
            [(row.inning, row.half) for row in rows],
        )
        self.assertEqual(
            result.team1_score,
            sum(row.runs for row in rows if row.half == "top" and row.was_played),
        )
        self.assertEqual(
            result.team2_score,
            sum(row.runs for row in rows if row.half == "bottom" and row.was_played),
        )
        self.assertTrue(all(row.runs is None for row in rows if not row.was_played))
        validate_match_simulation_result(
            result, self.match_input, config_dir=ROOT / "config" / "match"
        )

    def test_skipped_final_bottom_is_not_zero_run_half(self):
        # Change match RNG namespace only; roster and abilities stay fixed.
        found = None
        for i in range(1, 25):
            candidate = self.simulator.simulate(
                replace(self.match_input, match_id=f"STAGE43B-TOP-{i}")
            )
            if candidate.ending_half == "top":
                found = candidate
                break
        self.assertIsNotNone(found, "expected a game with unplayed final bottom")
        last = found.inning_scores[-1]
        self.assertEqual((found.last_inning, "bottom"), (last.inning, last.half))
        self.assertFalse(last.was_played)
        self.assertIsNone(last.runs)
        self.assertTrue(found.inning_scores[-2].was_played)

    def test_game_stats_and_line_score_survive_without_event_rows(self):
        detail = self.result.to_dict()
        # Option A deliberately does not require saving all plate appearances.
        detail["events"] = []
        summary = self.repository.replace_season_match_results(self._season(detail))
        self.assertEqual(len(detail["inning_scores"]), summary["inning_score_count"])
        self.assertEqual(0, summary["match_event_count"])
        innings = self.repository.inning_scores_for_match(
            2026, self.match_input.competition_id, self.match_input.match_id
        )
        self.assertEqual(len(detail["inning_scores"]), len(innings))
        self.assertEqual(
            [(row["inning"], row["half"], row["was_played"], row["runs"]) for row in innings],
            [(row["inning"], row["half"], int(row["was_played"]), row["runs"]) for row in detail["inning_scores"]],
        )
        self.assertTrue(self.repository.player_batter_game_stats(
            2026, self.result.batter_stats[0].player_id
        ))
        self.assertTrue(self.repository.player_pitcher_game_stats(
            2026, self.result.pitcher_stats[0].player_id
        ))
        self.assertEqual(
            [], self.repository.events_for_match(
                2026, self.match_input.competition_id, self.match_input.match_id
            ),
        )
        self.assertEqual(
            SCHEMA_VERSION,
            sqlite3.connect(self.db).execute("PRAGMA user_version").fetchone()[0],
        )

    def test_legacy_results_do_not_fabricate_inning_score(self):
        legacy = replace(self.result, inning_scores=None).to_dict()
        summary = self.repository.replace_season_match_results(self._season(legacy))
        self.assertEqual(0, summary["inning_score_count"])
        self.assertEqual(
            [], self.repository.inning_scores_for_match(
                2026, self.match_input.competition_id, self.match_input.match_id
            ),
        )

    def test_mismatched_total_is_rejected_without_corrupting_saved_record(self):
        valid = self.result.to_dict()
        self.repository.replace_season_match_results(self._season(valid))
        before = self.repository.inning_scores_for_match(
            2026, self.match_input.competition_id, self.match_input.match_id
        )
        bad = self.result.to_dict()
        bad["inning_scores"][0]["runs"] += 1
        with self.assertRaisesRegex(ValueError, "inning totals"):
            self.repository.replace_season_match_results(self._season(bad))
        self.assertEqual(
            before,
            self.repository.inning_scores_for_match(
                2026, self.match_input.competition_id, self.match_input.match_id
            ),
        )

    def test_bad_half_inning_structure_is_rejected(self):
        bad = self.result.to_dict()
        bad["inning_scores"][0]["half"] = "bottom"
        with self.assertRaisesRegex(ValueError, "order mismatch"):
            self.repository.replace_season_match_results(self._season(bad))

    def test_match_result_validation_rejects_wrong_batting_team(self):
        line = list(self.result.inning_scores)
        line[0] = replace(line[0], batting_team_id=self.result.team2_school_id)
        with self.assertRaisesRegex(ValueError, "batting team"):
            validate_match_simulation_result(
                replace(self.result, inning_scores=tuple(line)),
                self.match_input, config_dir=ROOT / "config" / "match",
            )

    def test_year_migration_adds_new_table_without_deleting_old_rows(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA user_version = 3")
            conn.execute("DROP TABLE match_inning_scores")
        self.repository.initialize_schema()
        with sqlite3.connect(self.db) as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            saved_year = conn.execute(
                "SELECT year FROM browse_seasons"
            ).fetchone()[0]
        self.assertIn("match_inning_scores", tables)
        self.assertEqual(2026, saved_year)


if __name__ == "__main__":
    unittest.main()
