from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path

from phase2_engine import (
    AnnualCompetitionInput,
    DataRepository,
    LiveSeasonRuntimeState,
    MatchResolution,
    TournamentEngine,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class CountingResolver:
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
            team1_score=3,
            team2_score=1,
            score_source="stage13e3c_counting",
            detail={
                "match_id": match_id,
                "competition_id": competition_id,
                "reference_year": reference_year,
                "generation_seed": generation_seed,
                "team1_school_id": team1,
                "team2_school_id": team2,
                "team1_score": 3,
                "team2_score": 1,
                "winner_id": team1,
                "loser_id": team2,
                "score_source": "stage13e3c_counting",
            },
        )


class Stage13E3CLiveSeasonScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.year = 2026
        cls.seed = 2026100819

        selected = None
        for competition_id, competition in sorted(
            cls.repo.competitions.items()
        ):
            stages = cls.repo.stages(competition_id)
            if [row["stage_code"] for row in stages] != ["MAIN"]:
                continue
            pcode = competition.get("prefecture_code", "")
            if not pcode:
                continue
            schools = sorted(
                school_id
                for school_id, row in cls.repo.schools.items()
                if (
                    row.get("prefecture_code") == pcode
                    and school_id in cls.repo.school_to_program
                )
            )
            if len(schools) >= 8:
                selected = (competition_id, schools[:8])
                break
        if selected is None:
            raise AssertionError(
                "no direct MAIN fixture competition"
            )
        cls.direct_competition_id, cls.direct_school_ids = selected

    def _calendar(self, competition_id, dates):
        return {
            "competition_id": competition_id,
            "game_date_list": ";".join(dates),
            "calendar_status": "test_schedule",
        }

    def _direct_annual(self):
        return AnnualCompetitionInput(
            competition_id=self.direct_competition_id,
            year=self.year,
            entrant_school_ids=list(self.direct_school_ids),
            rng_seed=self.seed,
        )

    def _hokkaido_spring_annual(self):
        competition_id = "CMP000004"
        qualifier = self.repo.stage_by_code(
            competition_id,
            "BRANCH_QUALIFIER",
        )
        entrants = set()
        for group in self.repo.groups_by_stage[
            qualifier["stage_id"]
        ]:
            entrants |= self.repo.group_school_ids(
                group,
                self.year,
            )
        direct_count = sum(
            int(rule.get("observed_2026_count") or 0)
            for rule in self.repo.access_rules(
                competition_id
            )
            if rule.get("grants_main_entry") == "yes"
        )
        ordered = sorted(entrants)
        return AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=ordered,
            direct_main_entry_school_ids=ordered[:direct_count],
            rng_seed=self.seed + 1,
        )

    def _gifu_annual(self):
        competition_id = "CMP000110"
        seed_stage = self.repo.stage_by_code(
            competition_id,
            "SEED_EVENT",
        )
        target_counts = [20, 10, 18, 10]
        entrants = []
        overrides = {}
        for group, count in zip(
            self.repo.groups_by_stage[
                seed_stage["stage_id"]
            ],
            target_counts,
        ):
            ids = sorted(
                self.repo.group_school_ids(
                    group,
                    self.year,
                )
            )[:count]
            self.assertEqual(count, len(ids))
            entrants.extend(ids)
            overrides[group["stage_group_id"]] = ids
        return AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=entrants,
            rng_seed=self.seed + 2,
            group_entrant_school_ids=overrides,
        )

    def test_direct_main_resolves_one_wave_per_date(self):
        resolver = CountingResolver()
        engine = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
        )
        dates = [
            "2026-04-01",
            "2026-04-02",
            "2026-04-03",
        ]
        scheduled = engine.prepare_scheduled_competition_runtime(
            self._direct_annual(),
            self._calendar(
                self.direct_competition_id,
                dates,
            ),
        )

        self.assertEqual([], resolver.calls)
        day1 = scheduled.matches_for_date(dates[0])
        self.assertEqual(4, len(day1))
        self.assertTrue(
            all(row["winner_id"] == "" for row in day1)
        )
        self.assertEqual([], scheduled.matches_for_date(dates[1]))

        first = scheduled.play_date(dates[0])
        self.assertEqual(4, len(first))
        self.assertEqual(4, len(resolver.calls))
        self.assertEqual(
            2,
            len(scheduled.matches_for_date(dates[1])),
        )
        self.assertEqual([], scheduled.matches_for_date(dates[2]))

        second = scheduled.play_date(dates[1])
        self.assertEqual(2, len(second))
        self.assertEqual(
            1,
            len(scheduled.matches_for_date(dates[2])),
        )
        self.assertFalse(scheduled.is_complete)

        scheduled.play_date(dates[2])
        self.assertTrue(scheduled.is_complete)
        self.assertEqual(7, len(resolver.calls))

    def test_direct_main_date_run_matches_legacy_exactly(self):
        annual = self._direct_annual()
        legacy = TournamentEngine(self.repo).run(annual)
        dates = [
            "2026-04-01",
            "2026-04-02",
            "2026-04-03",
        ]
        scheduled = TournamentEngine(
            self.repo
        ).prepare_scheduled_competition_runtime(
            self._direct_annual(),
            self._calendar(
                self.direct_competition_id,
                dates,
            ),
        )
        result = scheduled.advance_through(
            dates[-1]
        )
        self.assertTrue(result["is_complete"])
        self.assertEqual(
            legacy.to_dict(),
            scheduled.to_competition_run().to_dict(),
        )

    def test_hokkaido_qualifier_then_main_uses_stage_dates(self):
        annual = self._hokkaido_spring_annual()
        legacy = TournamentEngine(self.repo).run(annual)
        main_dates = [
            "2026-05-25",
            "2026-05-26",
            "2026-05-27",
            "2026-05-28",
            "2026-05-30",
            "2026-05-31",
        ]
        qualifier_dates = [
            "2026-05-01",
            "2026-05-02",
            "2026-05-03",
            "2026-05-04",
            "2026-05-05",
        ]
        scheduled = TournamentEngine(
            self.repo
        ).prepare_scheduled_competition_runtime(
            self._hokkaido_spring_annual(),
            self._calendar("CMP000004", main_dates),
            stage_date_lists={
                "BRANCH_QUALIFIER": qualifier_dates,
            },
        )

        self.assertEqual(
            {"BRANCH_QUALIFIER"},
            {
                row["stage_code"]
                for row in scheduled.matches_for_date(
                    qualifier_dates[0]
                )
            },
        )
        scheduled.advance_through(
            main_dates[-1]
        )
        self.assertTrue(scheduled.is_complete)
        self.assertEqual(
            legacy.to_dict(),
            scheduled.to_competition_run().to_dict(),
        )

        completed = list(
            scheduled.completed_results().values()
        )
        qdates = [
            row["match_date"]
            for row in completed
            if row["stage_code"] == "BRANCH_QUALIFIER"
        ]
        mdates = [
            row["match_date"]
            for row in completed
            if row["stage_code"] == "MAIN"
        ]
        self.assertTrue(qdates)
        self.assertTrue(mdates)
        self.assertLess(max(qdates), min(mdates))

    def test_gifu_seed_gate_main_activates_by_stage_date(self):
        annual = self._gifu_annual()
        legacy = TournamentEngine(self.repo).run(annual)
        main_dates = [
            "2026-08-29",
            "2026-08-30",
            "2026-09-05",
            "2026-09-06",
            "2026-09-12",
            "2026-09-13",
        ]
        seed_dates = [
            "2026-08-01",
            "2026-08-02",
            "2026-08-03",
            "2026-08-04",
            "2026-08-05",
        ]
        gate_dates = ["2026-08-20"]
        scheduled = TournamentEngine(
            self.repo
        ).prepare_scheduled_competition_runtime(
            self._gifu_annual(),
            self._calendar("CMP000110", main_dates),
            stage_date_lists={
                "SEED_EVENT": seed_dates,
                "FIRST_TOURNAMENT": gate_dates,
            },
        )

        self.assertEqual(
            {"SEED_EVENT"},
            {
                row["stage_code"]
                for row in scheduled.matches_for_date(
                    seed_dates[0]
                )
            },
        )
        scheduled.advance_through(
            gate_dates[0]
        )
        self.assertFalse(scheduled.is_complete)
        self.assertTrue(
            scheduled.matches_for_date(
                main_dates[0]
            )
        )
        self.assertEqual(
            {"MAIN"},
            {
                row["stage_code"]
                for row in scheduled.matches_for_date(
                    main_dates[0]
                )
            },
        )
        scheduled.advance_through(
            main_dates[-1]
        )
        self.assertTrue(scheduled.is_complete)
        lazy = scheduled.to_competition_run()
        self.assertEqual(
            legacy.seed_assignments,
            lazy.seed_assignments,
            "Gifu schedule: seed assignments differ",
        )
        self.assertEqual(
            legacy.main_entrant_school_ids,
            lazy.main_entrant_school_ids,
            "Gifu schedule: MAIN entrants differ",
        )
        self.assertEqual(
            legacy.stage_executions,
            lazy.stage_executions,
            "Gifu schedule: stage executions differ",
        )
        self.assertEqual(
            legacy.outcome,
            lazy.outcome,
            "Gifu schedule: outcome differs",
        )
        self.assertEqual(
            legacy.to_dict(),
            lazy.to_dict(),
        )

        completed = list(
            scheduled.completed_results().values()
        )
        stages = [
            row["stage_code"]
            for row in completed
        ]
        self.assertIn("SEED_EVENT", stages)
        self.assertIn("FIRST_TOURNAMENT", stages)
        self.assertIn("MAIN", stages)

    def test_calendar_exhaustion_stops_without_inventing_date(self):
        scheduled = TournamentEngine(
            self.repo
        ).prepare_scheduled_competition_runtime(
            self._direct_annual(),
            self._calendar(
                self.direct_competition_id,
                ["2026-04-01"],
            ),
        )
        scheduled.play_date("2026-04-01")

        self.assertFalse(scheduled.is_complete)
        gap = scheduled.calendar_gap_matches()
        self.assertEqual(2, len(gap))
        self.assertTrue(
            all(
                row["date_source"] == "calendar_gap"
                and row["match_date"] == ""
                and row["winner"] == ""
                for row in gap
            )
        )
        self.assertEqual(
            2,
            scheduled.summary()["calendar_gap_count"],
        )

    def test_live_season_clock_calls_resolver_only_on_current_date(self):
        resolver = CountingResolver()
        engine = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
        )
        dates = [
            "2026-04-01",
            "2026-04-02",
            "2026-04-03",
        ]
        state = LiveSeasonRuntimeState.from_annual_inputs(
            engine=engine,
            repo=self.repo,
            annual_inputs=[self._direct_annual()],
            calendar_rows=[
                self._calendar(
                    self.direct_competition_id,
                    dates,
                )
            ],
            rng_seed=self.seed,
            start_date="2026-04-01",
        )

        self.assertEqual([], resolver.calls)
        today = state.today_matches()
        self.assertEqual(4, len(today))
        self.assertTrue(
            all(row["winner_id"] == "" for row in today)
        )
        self.assertEqual([], state.school_records())

        first = state.play_today()
        self.assertEqual(4, len(first))
        self.assertEqual(4, len(resolver.calls))
        self.assertEqual(
            "",
            state.competition_state(
                self.direct_competition_id
            )["champion_school_id"],
        )
        self.assertEqual(
            8,
            sum(
                row["games"]
                for row in state.school_records()
            ),
        )

        state.next_day()
        self.assertEqual(
            date(2026, 4, 2),
            state.current_date,
        )
        self.assertEqual(4, len(resolver.calls))
        self.assertEqual(2, len(state.today_matches()))

        state.advance_through("2026-04-03")
        self.assertEqual(7, len(resolver.calls))
        competition = state.competition_state(
            self.direct_competition_id
        )
        self.assertTrue(competition["is_complete"])
        self.assertTrue(
            competition["champion_school_id"]
        )

    def test_live_season_midseason_start_resolves_only_past_dates(self):
        resolver = CountingResolver()
        state = LiveSeasonRuntimeState.from_annual_inputs(
            engine=TournamentEngine(
                self.repo,
                main_match_resolver=resolver,
            ),
            repo=self.repo,
            annual_inputs=[self._direct_annual()],
            calendar_rows=[
                self._calendar(
                    self.direct_competition_id,
                    [
                        "2026-04-01",
                        "2026-04-02",
                        "2026-04-03",
                    ],
                )
            ],
            rng_seed=self.seed,
            start_date="2026-04-02",
        )

        self.assertEqual(4, len(resolver.calls))
        self.assertEqual(
            4,
            state.summary()["completed_match_count"],
        )
        self.assertEqual(2, len(state.today_matches()))
        self.assertTrue(
            all(
                row["winner_id"] == ""
                for row in state.today_matches()
            )
        )

    def test_public_snapshot_contains_no_unplayed_winner(self):
        state = LiveSeasonRuntimeState.from_annual_inputs(
            engine=TournamentEngine(self.repo),
            repo=self.repo,
            annual_inputs=[self._direct_annual()],
            calendar_rows=[
                self._calendar(
                    self.direct_competition_id,
                    [
                        "2026-04-01",
                        "2026-04-02",
                        "2026-04-03",
                    ],
                )
            ],
            rng_seed=self.seed,
            start_date="2026-04-01",
        )
        snapshot = state.public_snapshot()
        rows = snapshot["competitions"][
            self.direct_competition_id
        ]["matches"]
        self.assertTrue(rows)
        self.assertTrue(
            all(
                row["winner_id"] == ""
                for row in rows
                if row["status"] == "pending"
            )
        )
        self.assertNotIn(
            "ability_detail",
            repr(snapshot),
        )


if __name__ == "__main__":
    unittest.main()
