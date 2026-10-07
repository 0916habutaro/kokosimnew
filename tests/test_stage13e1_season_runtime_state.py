from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine import (
    AnnualCompetitionInput,
    DataRepository,
    TournamentEngine,
)
from phase2_engine.season import SeasonExecution
from phase2_engine.season_runtime import (
    MATCH_COMPLETED,
    MATCH_PENDING,
    MATCH_UNSCHEDULED,
    SeasonRuntimeState,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
ABILITY_CONFIG = ROOT / "config" / "abilities"
MATCH_CONFIG = ROOT / "config" / "match"


class Stage13E1SeasonRuntimeStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.year = 2026
        cls.season_seed = 2026100801

        selected = None
        for competition_id, competition in sorted(
            cls.repo.competitions.items()
        ):
            stages = cls.repo.stages(competition_id)
            if [stage["stage_code"] for stage in stages] != ["MAIN"]:
                continue
            prefecture_code = competition.get("prefecture_code", "")
            school_ids = sorted(
                school_id
                for school_id, row in cls.repo.schools.items()
                if row.get("prefecture_code") == prefecture_code
                and school_id in cls.repo.school_to_program
            )
            if len(school_ids) >= 4:
                selected = (competition_id, school_ids[:4])
                break
        if selected is None:
            raise AssertionError("no direct MAIN four-school fixture")

        cls.competition_id, cls.school_ids = selected
        resolver = AbilityMatchResolver(
            cls.repo,
            ability_config_dir=ABILITY_CONFIG,
            match_config_dir=MATCH_CONFIG,
        )
        resolver.begin_season(cls.year, cls.season_seed)
        engine = TournamentEngine(
            cls.repo,
            main_match_resolver=resolver,
            pre_main_match_resolver=resolver,
        )
        cls.run = engine.run(
            AnnualCompetitionInput(
                competition_id=cls.competition_id,
                year=cls.year,
                entrant_school_ids=cls.school_ids,
                rng_seed=777,
            )
        )
        cls.season = SeasonExecution(
            year=cls.year,
            rng_seed=cls.season_seed,
            competition_runs={
                cls.competition_id: cls.run,
            },
            player_master_records=resolver.player_master_records(),
        )
        cls.calendar = [{
            "calendar_id": "TEST-E1",
            "competition_id": cls.competition_id,
            "start_date": "2026-04-01",
            "end_date": "2026-04-02",
            "draw_date": "",
            "venue_summary": "",
            "game_date_list": "2026-04-01;2026-04-02",
            "calendar_status": "official_schedule",
            "primary_source_id": "TEST",
            "verified_at": "2026-10-08",
            "notes": "",
        }]

    def runtime(self, *, start_date="2026-04-01", calendar=None):
        return SeasonRuntimeState.from_prepared_season(
            self.season,
            self.repo,
            DATA_ROOT,
            start_date=start_date,
            calendar_rows=(
                self.calendar
                if calendar is None
                else calendar
            ),
        )

    def test_initial_state_hides_all_future_results(self):
        state = self.runtime()
        summary = state.summary()

        self.assertEqual("2026-04-01", summary["current_date"])
        self.assertEqual(3, summary["pending_match_count"])
        self.assertEqual(0, summary["completed_match_count"])
        self.assertEqual(2, summary["today_match_count"])
        self.assertEqual(0, summary["completed_ability_match_count"])

        for row in state.today_matches():
            self.assertEqual(MATCH_PENDING, row["status"])
            self.assertIsNone(row["team1_score"])
            self.assertIsNone(row["team2_score"])
            self.assertEqual("", row["winner_id"])
            self.assertEqual("", row["score_source"])

        snapshot = state.public_snapshot()
        future = [
            row
            for row in snapshot["matches"]
            if row["status"] == MATCH_PENDING
        ]
        self.assertTrue(future)
        self.assertTrue(all(row["winner_id"] == "" for row in future))
        self.assertTrue(
            all(row["team1_score"] is None for row in future)
        )

    def test_play_today_applies_only_first_day_results(self):
        state = self.runtime()
        results = state.play_today()

        self.assertEqual(2, len(results))
        self.assertTrue(
            all(result.ability_detail is not None for result in results)
        )
        summary = state.summary()
        self.assertEqual(2, summary["completed_match_count"])
        self.assertEqual(1, summary["pending_match_count"])
        self.assertEqual(2, summary["completed_ability_match_count"])

        completed = state.completed_results()
        ability = state.completed_ability_results()
        self.assertEqual(2, len(completed))
        self.assertEqual(2, len(ability))

        day_two = state.matches_for_date("2026-04-02")
        self.assertEqual(1, len(day_two))
        self.assertEqual(MATCH_PENDING, day_two[0]["status"])
        self.assertEqual("", day_two[0]["winner_id"])
        self.assertIsNone(day_two[0]["team1_score"])

    def test_play_today_is_idempotent(self):
        state = self.runtime()
        first = state.play_today()
        second = state.play_today()

        self.assertEqual(2, len(first))
        self.assertEqual([], second)
        self.assertEqual(2, len(state.completed_results()))

    def test_next_day_processes_current_day_then_moves_date(self):
        state = self.runtime()
        result = state.next_day()

        self.assertEqual("2026-04-01", result["from_date"])
        self.assertEqual("2026-04-02", result["to_date"])
        self.assertEqual(2, result["played_match_count"])
        self.assertEqual(date(2026, 4, 2), state.current_date)

        today = state.today_matches()
        self.assertEqual(1, len(today))
        self.assertEqual(MATCH_PENDING, today[0]["status"])

    def test_advance_through_completes_final_and_reveals_champion(self):
        state = self.runtime()
        result = state.advance_through("2026-04-02")

        self.assertEqual(3, result["played_match_count"])
        self.assertEqual(3, len(state.completed_results()))
        competition = state.competition_state(self.competition_id)
        self.assertTrue(competition["is_complete"])
        self.assertEqual(
            self.run.outcome.champion_school_id,
            competition["champion_school_id"],
        )
        self.assertEqual(0, competition["pending_match_count"])

    def test_school_records_only_include_completed_games(self):
        state = self.runtime()
        self.assertEqual([], state.school_records())

        state.play_today()
        records = state.school_records()
        self.assertEqual(4, len(records))
        self.assertEqual(4, sum(row["games"] for row in records))
        self.assertEqual(2, sum(row["wins"] for row in records))
        self.assertEqual(2, sum(row["losses"] for row in records))

        state.advance_through("2026-04-02")
        records = state.school_records()
        self.assertEqual(6, sum(row["games"] for row in records))
        self.assertEqual(3, sum(row["wins"] for row in records))
        self.assertEqual(3, sum(row["losses"] for row in records))

    def test_starting_midseason_applies_only_prior_dates(self):
        state = self.runtime(start_date="2026-04-02")
        summary = state.summary()

        self.assertEqual(2, summary["completed_match_count"])
        self.assertEqual(1, summary["pending_match_count"])
        self.assertEqual(1, summary["today_match_count"])
        self.assertEqual(2, len(state.completed_ability_results()))

        final = state.today_matches()[0]
        self.assertEqual(MATCH_PENDING, final["status"])
        self.assertEqual("", final["winner_id"])

    def test_advance_to_does_not_process_target_date(self):
        state = self.runtime()
        result = state.advance_to("2026-04-02")

        self.assertEqual(1, result["advanced_days"])
        self.assertEqual(2, result["played_match_count"])
        self.assertEqual("2026-04-02", result["current_date"])
        self.assertEqual(1, state.summary()["pending_match_count"])

    def test_runtime_cannot_move_backward(self):
        state = self.runtime(start_date="2026-04-02")
        with self.assertRaises(ValueError):
            state.advance_to("2026-04-01")

    def test_undated_matches_remain_unscheduled_and_hidden(self):
        calendar = [dict(
            self.calendar[0],
            game_date_list="",
            start_date="2026-04-01",
            end_date="2026-04-02",
        )]
        state = self.runtime(calendar=calendar)

        summary = state.summary()
        self.assertEqual(0, summary["pending_match_count"])
        self.assertEqual(3, summary["unscheduled_match_count"])
        self.assertEqual([], state.today_matches())
        self.assertEqual(3, len(state.unscheduled_matches()))
        self.assertTrue(all(
            row["status"] == MATCH_UNSCHEDULED
            and row["winner_id"] == ""
            and row["team1_score"] is None
            for row in state.unscheduled_matches()
        ))

    def test_three_team_bye_is_structurally_completed(self):
        resolver = AbilityMatchResolver(
            self.repo,
            ability_config_dir=ABILITY_CONFIG,
            match_config_dir=MATCH_CONFIG,
        )
        resolver.begin_season(self.year, self.season_seed)
        engine = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
            pre_main_match_resolver=resolver,
        )
        run = engine.run(
            AnnualCompetitionInput(
                competition_id=self.competition_id,
                year=self.year,
                entrant_school_ids=self.school_ids[:3],
                rng_seed=778,
            )
        )
        season = SeasonExecution(
            year=self.year,
            rng_seed=self.season_seed,
            competition_runs={
                self.competition_id: run,
            },
        )
        state = SeasonRuntimeState.from_prepared_season(
            season,
            self.repo,
            DATA_ROOT,
            start_date="2026-04-01",
            calendar_rows=self.calendar,
        )

        bye_rows = [
            match
            for match in state.matches.values()
            if match.is_bye
        ]
        self.assertTrue(bye_rows)
        self.assertTrue(all(
            match.status == MATCH_COMPLETED
            for match in bye_rows
        ))
        self.assertTrue(all(
            match.result is not None
            for match in bye_rows
        ))
        self.assertEqual(
            len(run.match_simulation_results),
            state.summary()["pending_match_count"],
        )

    def test_public_snapshot_never_contains_prepared_result_field(self):
        state = self.runtime()
        snapshot = state.public_snapshot()
        serialized = repr(snapshot)
        self.assertNotIn("_prepared_result", serialized)
        self.assertNotIn("ability_detail", serialized)


if __name__ == "__main__":
    unittest.main()
