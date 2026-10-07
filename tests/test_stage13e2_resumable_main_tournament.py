from __future__ import annotations

import unittest
from pathlib import Path

from game_core.tournament_bridge import AbilityMainMatchResolver
from phase2_engine import (
    AnnualCompetitionInput,
    DataRepository,
    MatchResolution,
    TournamentEngine,
)
from phase2_engine.tournament_runtime import (
    MATCH_BYE,
    MATCH_COMPLETED,
    MATCH_READY,
    MATCH_WAITING,
    ScheduledMainTournamentRuntime,
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
        self.calls.append({
            "match_id": match_id,
            "competition_id": competition_id,
            "reference_year": reference_year,
            "generation_seed": generation_seed,
            "team1": team1,
            "team2": team2,
        })
        return MatchResolution(
            winner_id=team1,
            loser_id=team2,
            team1_score=1,
            team2_score=0,
            score_source="counting_test",
            detail={
                "match_id": match_id,
                "winner_id": team1,
                "loser_id": team2,
                "team1_score": 1,
                "team2_score": 0,
                "score_source": "counting_test",
            },
        )


class Stage13E2ResumableMainTournamentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.year = 2026
        cls.seed = 2026100802

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

    def annual(self, count=8):
        return AnnualCompetitionInput(
            competition_id=self.competition_id,
            year=self.year,
            entrant_school_ids=list(self.school_ids[:count]),
            rng_seed=self.seed,
        )

    def test_prepare_does_not_resolve_any_real_match(self):
        resolver = CountingResolver()
        engine = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
        )
        state = engine.prepare_main_runtime(self.annual())

        self.assertEqual([], resolver.calls)
        self.assertFalse(state.is_complete)
        self.assertEqual(4, len(state.ready_matches()))
        self.assertEqual(3, len(state.waiting_matches()))
        self.assertEqual(0, len(state.completed_matches()))
        self.assertTrue(all(
            row["winner"] == ""
            for row in state.ready_matches()
            + state.waiting_matches()
        ))

    def test_resolving_one_match_only_propagates_its_winner(self):
        resolver = CountingResolver()
        state = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
        ).prepare_main_runtime(self.annual())

        first = state.ready_matches()[0]
        next_id = first["next_match_id"]
        state.resolve_match(first["match_id"])

        self.assertEqual(1, len(resolver.calls))
        resolved = state.matches[first["match_id"]]
        self.assertEqual(MATCH_COMPLETED, resolved.status)
        self.assertTrue(resolved.winner)
        self.assertEqual(
            resolved.winner,
            state.matches[next_id].team1,
        )
        self.assertEqual(
            MATCH_WAITING,
            state.matches[next_id].status,
        )
        self.assertEqual("", state.matches[next_id].winner)

    def test_resolve_ready_round_advances_bracket_incrementally(self):
        resolver = CountingResolver()
        state = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
        ).prepare_main_runtime(self.annual())

        first_round = state.resolve_ready_round()
        self.assertEqual(4, len(first_round))
        self.assertEqual(4, len(resolver.calls))
        self.assertEqual(2, len(state.ready_matches()))
        self.assertEqual(1, len(state.waiting_matches()))

        second_round = state.resolve_ready_round()
        self.assertEqual(2, len(second_round))
        self.assertEqual(6, len(resolver.calls))
        self.assertEqual(1, len(state.ready_matches()))
        self.assertEqual(0, len(state.waiting_matches()))
        self.assertFalse(state.is_complete)

        final = state.resolve_ready_round()
        self.assertEqual(1, len(final))
        self.assertEqual(7, len(resolver.calls))
        self.assertTrue(state.is_complete)
        self.assertTrue(state.champion_school_id)

    def test_lazy_random_resolution_matches_legacy_run_exactly(self):
        annual = self.annual()
        legacy = TournamentEngine(self.repo).run(annual)

        lazy_engine = TournamentEngine(self.repo)
        state = lazy_engine.prepare_main_runtime(self.annual())
        lazy = state.resolve_all()

        self.assertEqual(legacy.to_dict(), lazy.to_dict())

    def test_lazy_ability_resolution_matches_legacy_run_exactly(self):
        resolver1 = AbilityMainMatchResolver(
            self.repo,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        resolver2 = AbilityMainMatchResolver(
            self.repo,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        legacy = TournamentEngine(
            self.repo,
            main_match_resolver=resolver1,
        ).run(self.annual())

        state = TournamentEngine(
            self.repo,
            main_match_resolver=resolver2,
        ).prepare_main_runtime(self.annual())
        self.assertEqual({}, state.match_simulation_results)
        lazy = state.resolve_all()

        self.assertEqual(legacy.to_dict(), lazy.to_dict())
        self.assertEqual(7, len(lazy.match_simulation_results))

    def test_winner_override_is_applied_without_calling_resolver(self):
        baseline = TournamentEngine(self.repo).run(self.annual())
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
        annual = self.annual()
        annual.main_match_winner_overrides = {
            target.match_id: forced,
        }
        resolver = CountingResolver()
        state = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
        ).prepare_main_runtime(annual)

        state.resolve_match(target.match_id)
        self.assertEqual(forced, state.matches[target.match_id].winner)
        self.assertEqual(
            "annual_override",
            state.matches[target.match_id].metadata["winner_source"],
        )
        self.assertEqual([], resolver.calls)
        self.assertNotIn(
            target.match_id,
            state.match_simulation_results,
        )

    def test_byes_auto_propagate_without_resolver_calls(self):
        resolver = CountingResolver()
        state = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
        ).prepare_main_runtime(self.annual(count=5))

        byes = [
            match
            for match in state.matches.values()
            if match.status == MATCH_BYE
        ]
        self.assertEqual(3, len(byes))
        self.assertEqual([], resolver.calls)
        self.assertTrue(all(match.winner for match in byes))

        lazy = state.resolve_all()
        self.assertEqual(4, len(resolver.calls))
        self.assertEqual(4, lazy.outcome.match_count)
        self.assertEqual(3, lazy.outcome.bye_count)

    def test_incomplete_state_cannot_materialize_competition_run(self):
        state = TournamentEngine(
            self.repo
        ).prepare_main_runtime(self.annual())
        with self.assertRaises(ValueError):
            state.to_competition_run()

    def test_scheduled_runtime_calls_resolver_only_on_play_date(self):
        resolver = CountingResolver()
        state = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
        ).prepare_main_runtime(self.annual())
        scheduled = ScheduledMainTournamentRuntime.from_calendar_row(
            state,
            {
                "competition_id": self.competition_id,
                "game_date_list": (
                    "2026-04-01;2026-04-02;2026-04-03"
                ),
            },
        )

        self.assertEqual([], resolver.calls)
        first_day = scheduled.matches_for_date("2026-04-01")
        self.assertEqual(2, len(first_day))
        self.assertTrue(all(row["winner"] == "" for row in first_day))

        result = scheduled.play_date("2026-04-01")
        self.assertEqual(2, len(result))
        self.assertEqual(2, len(resolver.calls))
        self.assertFalse(state.is_complete)

        future = scheduled.matches_for_date("2026-04-02")
        self.assertTrue(future)
        self.assertTrue(any(
            row["status"] in {MATCH_READY, MATCH_WAITING}
            for row in future
        ))
        self.assertTrue(all(
            row["winner"] == ""
            for row in future
            if row["status"] != MATCH_BYE
        ))

    def test_scheduled_advance_through_finishes_tournament(self):
        resolver = CountingResolver()
        state = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
        ).prepare_main_runtime(self.annual())
        scheduled = ScheduledMainTournamentRuntime.from_calendar_row(
            state,
            {
                "competition_id": self.competition_id,
                "game_date_list": (
                    "2026-04-01;2026-04-02;2026-04-03"
                ),
            },
        )

        first = scheduled.advance_through("2026-04-01")
        self.assertEqual(2, first["played_match_count"])
        self.assertFalse(first["is_complete"])

        final = scheduled.advance_through("2026-04-03")
        self.assertEqual(5, final["played_match_count"])
        self.assertTrue(final["is_complete"])
        self.assertEqual(7, len(resolver.calls))
        self.assertTrue(state.champion_school_id)

    def test_public_snapshot_has_no_future_winner(self):
        state = TournamentEngine(
            self.repo
        ).prepare_main_runtime(self.annual())
        snapshot = state.public_snapshot()

        self.assertFalse(snapshot["is_complete"])
        self.assertEqual("", snapshot["champion_school_id"])
        for row in snapshot["matches"]:
            if row["status"] in {MATCH_READY, MATCH_WAITING}:
                self.assertEqual("", row["winner"])
                self.assertEqual("", row["loser"])

    def test_resolving_waiting_match_is_rejected(self):
        state = TournamentEngine(
            self.repo
        ).prepare_main_runtime(self.annual())
        waiting = state.waiting_matches()[0]
        with self.assertRaises(ValueError):
            state.resolve_match(waiting["match_id"])


if __name__ == "__main__":
    unittest.main()
