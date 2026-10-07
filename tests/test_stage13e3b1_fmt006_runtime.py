from __future__ import annotations

import unittest
from pathlib import Path

from phase2_engine import AnnualCompetitionInput, DataRepository, MatchResolution, TournamentEngine
from phase2_engine.cli import _kanagawa_demo


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
            team1_score=4,
            team2_score=2,
            score_source="stage13e3b1_stub",
            detail={
                "match_id": match_id,
                "competition_id": competition_id,
                "reference_year": reference_year,
                "generation_seed": generation_seed,
                "team1_school_id": team1,
                "team2_school_id": team2,
                "team1_score": 4,
                "team2_score": 2,
                "winner_id": team1,
                "loser_id": team2,
                "score_source": "stage13e3b1_stub",
            },
        )


class Stage13E3B1Fmt006RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.year = 2026
        cls.seed = 2026100804

    def _annual(self, competition_id="CMP000095", seed=None):
        entrants, direct = _kanagawa_demo(
            self.repo,
            competition_id,
            self.year,
        )
        return AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=entrants,
            direct_main_entry_school_ids=direct,
            rng_seed=self.seed if seed is None else seed,
        )

    def test_fmt006_lazy_run_exactly_matches_legacy_random_run(self):
        legacy = TournamentEngine(self.repo).run(self._annual())
        runtime = TournamentEngine(
            self.repo
        ).prepare_qualifier_main_runtime(self._annual())

        self.assertFalse(runtime.qualifier_complete)
        self.assertIsNone(runtime.main_runtime)
        self.assertEqual([], runtime.main_entrant_school_ids)

        lazy = runtime.resolve_all()
        self.assertEqual(legacy.to_dict(), lazy.to_dict())

    def test_pool_phase_precedes_cross_playoff_and_main_activation(self):
        resolver = StubDetailedResolver()
        runtime = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
            pre_main_match_resolver=resolver,
        ).prepare_qualifier_main_runtime(self._annual())

        first_ready = runtime.ready_matches()
        self.assertTrue(first_ready)
        self.assertEqual({"POOL_RR"}, {row["phase_code"] for row in first_ready})
        self.assertEqual([], resolver.calls)
        self.assertIsNone(runtime.main_runtime)

        pool_results = runtime.resolve_ready_round()
        self.assertTrue(pool_results)
        self.assertIsNone(runtime.main_runtime)
        cross_ready = runtime.ready_matches()
        self.assertTrue(cross_ready)
        self.assertEqual(
            {"CROSS_PLAYOFF"},
            {row["phase_code"] for row in cross_ready},
        )

        runtime.resolve_ready_round()
        self.assertTrue(runtime.qualifier_complete)
        self.assertIsNotNone(runtime.main_runtime)
        calls_after_qualifier = len(resolver.calls)
        self.assertGreater(calls_after_qualifier, 0)

        main_ready = runtime.ready_matches()
        self.assertTrue(main_ready)
        self.assertEqual(
            calls_after_qualifier,
            len(resolver.calls),
        )
        self.assertTrue(
            all(row["stage_code"] == "MAIN" for row in main_ready)
        )

    def test_fmt006_detailed_legacy_run_matches_lazy_run(self):
        legacy_resolver = StubDetailedResolver()
        lazy_resolver = StubDetailedResolver()
        legacy = TournamentEngine(
            self.repo,
            main_match_resolver=legacy_resolver,
            pre_main_match_resolver=legacy_resolver,
        ).run(self._annual(seed=2026100805))

        runtime = TournamentEngine(
            self.repo,
            main_match_resolver=lazy_resolver,
            pre_main_match_resolver=lazy_resolver,
        ).prepare_qualifier_main_runtime(
            self._annual(seed=2026100805)
        )
        lazy = runtime.resolve_all()

        self.assertEqual(legacy.to_dict(), lazy.to_dict())
        self.assertEqual(legacy_resolver.calls, lazy_resolver.calls)
        self.assertEqual(
            set(lazy.match_simulation_results),
            set(lazy_resolver.calls),
        )

    def test_cross_playoff_results_do_not_exist_before_pool_completion(self):
        resolver = StubDetailedResolver()
        runtime = TournamentEngine(
            self.repo,
            pre_main_match_resolver=resolver,
            main_match_resolver=resolver,
        ).prepare_qualifier_main_runtime(self._annual())

        self.assertEqual({}, runtime.pre_main_match_simulation_results)
        self.assertFalse(any(
            group.cross_activated
            for group in runtime.qualifier_groups
        ))

        target = runtime.ready_matches()[0]["match_id"]
        runtime.resolve_match(target)
        self.assertIn(
            target,
            runtime.pre_main_match_simulation_results,
        )
        self.assertFalse(any(
            group.cross_activated
            for group in runtime.qualifier_groups
        ))
        self.assertIsNone(runtime.main_runtime)

    def test_fmt006_pool_override_preserves_legacy_contract(self):
        annual = self._annual(seed=2026100806)
        stage = self.repo.stage_by_code(
            annual.competition_id,
            "BRANCH_QUALIFIER",
        )
        for group in self.repo.groups_by_stage[stage["stage_id"]]:
            gid = group["stage_group_id"]
            eligible = sorted(
                (
                    set(annual.entrant_school_ids)
                    - set(annual.direct_main_entry_school_ids)
                )
                & self.repo.group_school_ids(group, self.year)
            )
            slots = self.repo.param(
                stage["stage_id"],
                "output_slots",
                gid,
            )
            four, three = TournamentEngine._solve_3_or_4_pool_plan(
                len(eligible),
                slots,
            )
            sizes = [4] * four + [3] * three
            pools = []
            pos = 0
            for size in sizes:
                pools.append(eligible[pos:pos + size])
                pos += size
            annual.group_pool_assignments[gid] = pools

        legacy = TournamentEngine(self.repo).run(annual)
        lazy = TournamentEngine(
            self.repo
        ).prepare_qualifier_main_runtime(
            annual
        ).resolve_all()
        self.assertEqual(legacy.to_dict(), lazy.to_dict())
        qualifier = lazy.stage_executions[0]
        self.assertTrue(all(
            metadata["draw_source"] == "annual_override"
            for metadata in qualifier.metadata["group_metadata"].values()
        ))


if __name__ == "__main__":
    unittest.main()
