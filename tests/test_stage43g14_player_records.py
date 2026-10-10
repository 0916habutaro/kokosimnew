"""Stage43G-14: real archive/roster-backed player records and leaderboard."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_history_scale_audit import synthetic_ability_record
from phase2_engine.career_player_records import (
    BATTER, PITCHER, CareerHistoryViewConflict, CareerPlayerRecordView,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701


class Stage43G14PlayerRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        work = Path(self.temp.name)
        self.history = HistoricalMatchArchive(work / "matches.sqlite3")
        self.rosters = CareerRosterArchive(work / "rosters.sqlite3")
        repo = DataRepository(ROOT / "data")
        schools = sorted(repo.school_to_program)
        self.a, self.b = schools[0], schools[1]
        generator = PlayerRosterGenerator()
        for school in (self.a, self.b):
            self.rosters.save_initial_roster(
                generator.generate_for_school_id(repo, school, 2026, SEED)
            )
            self.rosters.advance_and_save(
                repo.team(school), next_year=2027, career_seed=SEED,
            )
        p = self.rosters.roster(2026, self.a)
        self.hitter = next(x.player_id for x in p.players if x.academic_year == 1)
        self.pitcher = next(x.player_id for x in p.players
                            if x.primary_position == "P" and x.academic_year < 3)
        for year in (2026, 2027):
            if year == 2027:
                self.history.register_next_year(
                    year=year, rng_seed=SEED,
                    resolver_contract="synthetic_test_v1",
                    plan_fingerprint=f"stage43g14-year-{year}",
                )
            row = synthetic_ability_record(
                year, "CMP000086", f"ARCHIVE-{year}", self.a, self.b, 2,
            )
            for school in (self.a, self.b):
                members = self.rosters.roster(year, school).players
                selected = [p.player_id for p in members][:9]
                if school == self.a:
                    selected[0] = self.hitter
                    selected = list(dict.fromkeys(selected))
                    while len(selected) < 9:
                        selected.append(next(
                            p.player_id for p in members if p.player_id not in selected
                        ))
                source = [
                    rec for rec in row["ability_detail"]["batter_stats"]
                    if rec["school_id"] == school
                ]
                for item, pid in zip(source, selected):
                    item["player_id"] = pid
                    # The G13 synthetic-size fixture intentionally stores
                    # only 2 batting fields. Fill the actual v1 simulator
                    # field contract for this player-record integrity test.
                    for key in BATTER:
                        item.setdefault(key, 0)
                    item["plate_appearances"] = 4
                arm = next(p.player_id for p in members
                           if p.primary_position == "P")
                if school == self.a:
                    arm = self.pitcher
                for item in row["ability_detail"]["pitcher_stats"]:
                    if item["school_id"] == school:
                        item["player_id"] = arm
                        for key in PITCHER:
                            item.setdefault(key, 0)
                        item["outs_recorded"] = 27
            self.history.sync(
                year=year, rng_seed=SEED,
                resolver_contract="synthetic_test_v1",
                plan_fingerprint=f"stage43g14-year-{year}",
                completed=[row],
            )
            if year == 2026:
                self.history.seal_year(year, expected_match_count=1)
        self.view = CareerPlayerRecordView(self.history, self.rosters)

    def tearDown(self):
        self.temp.cleanup()

    def test_annual_and_career_stats_and_defined_ratios(self):
        result = self.view.player_seasons(
            self.hitter, start_year=2026, end_year=2027,
        )
        self.assertEqual(2, len(result["seasons"]))
        self.assertEqual([2026, 2027],
                         [x["year"] for x in result["seasons"]])
        b = result["totals"]["batting"]
        self.assertEqual(2, b["games"])
        self.assertEqual(8, b["at_bats"])
        self.assertEqual(2, b["hits"])
        self.assertEqual(.250, b["batting_average"])
        self.assertEqual(.250, b["on_base_percentage"])
        self.assertEqual(.250, b["slugging_percentage"])
        self.assertEqual(.500, b["on_base_plus_slugging"])
        self.assertEqual(0, result["games_without_box_scores"])

    def test_pitcher_outs_and_rates_only_from_box_scores(self):
        result = self.view.player_seasons(
            self.pitcher, start_year=2026, end_year=2027,
        )
        pitch = result["totals"]["pitching"]
        self.assertEqual(2, pitch["games"])
        self.assertEqual(54, pitch["outs_recorded"])
        self.assertEqual(54, pitch["innings_pitched_outs"])
        self.assertEqual(6, pitch["earned_runs"])
        self.assertEqual(3.00, pitch["earned_run_average"])
        self.assertEqual(0.00, pitch["walks_hits_per_inning"])
        self.assertFalse(result["pitcher_wins_losses_inferred"])

    def test_school_leaders_and_strict_id_ties(self):
        leaders = self.view.school_leaders(
            self.a, start_year=2026, end_year=2027,
            category="batting_hits", limit=2,
        )
        self.assertEqual(2, len(leaders["rows"]))
        self.assertEqual(2, leaders["rows"][0]["stat_value"])
        self.assertGreaterEqual(leaders["candidate_count"], 9)
        self.assertEqual(
            sorted(x["player_id"] for x in leaders["rows"]),
            [x["player_id"] for x in leaders["rows"]],
        )
        self.assertEqual(
            "pitching_strikeouts",
            self.view.school_leaders(
                self.a, start_year=2026, end_year=2027,
                category="pitching_strikeouts",
            )["category"],
        )

    def test_missing_boxscore_is_not_invented_zero_stats(self):
        missing = {
            "competition_id": "CMP000092", "match_id": "NO-A-2027",
            "competition_name": "ゲーム用スコアのみ", "match_date": "2027-05-09",
            "completed_on": "2027-05-09", "date_source": "game_projection_v1",
            "status": "completed", "stage_code": "MAIN",
            "phase_code": "MAIN_BRACKET", "round_no": 1,
            "team1_id": self.a, "team2_id": self.b, "team1_score": 2,
            "team2_score": 1, "winner_id": self.a, "loser_id": self.b,
            "score_source": "generated_v1",
        }
        self.history.sync(
            year=2027, rng_seed=SEED,
            resolver_contract="synthetic_test_v1",
            plan_fingerprint="stage43g14-year-2027",
            completed=[missing],
        )
        result = self.view.player_seasons(
            self.hitter, start_year=2026, end_year=2027,
        )
        self.assertEqual(1, result["games_without_box_scores"])
        self.assertEqual(2, result["totals"]["batting"]["games"])
        self.assertEqual(1, self.view.school_leaders(
            self.a, start_year=2026, end_year=2027, category="batting_hits",
        )["missing_box_score_games"])

    def test_all_years_verified_even_for_single_year_query(self):
        target = self.history.db_path
        with sqlite3.connect(target) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='WRONG' "
                "WHERE year=2026",
            )
        with self.assertRaises(CareerHistoryViewConflict):
            self.view.player_seasons(
                self.hitter, start_year=2026, end_year=2027,
            )
        with self.assertRaises(CareerHistoryViewConflict):
            self.view.school_leaders(
                self.a, start_year=2026, end_year=2027,
                category="batting_hits",
            )

    def test_invalid_metric_and_year_range_rejected(self):
        with self.assertRaises(ValueError):
            self.view.school_leaders(
                self.a, start_year=2026, end_year=2027,
                category="earned_run_average",
            )
        with self.assertRaises(ValueError):
            self.view.player_seasons(
                self.hitter, start_year=2027, end_year=2026,
            )

if __name__ == "__main__":
    unittest.main()
