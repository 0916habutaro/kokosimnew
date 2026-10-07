from __future__ import annotations

import unittest
from pathlib import Path

from phase2_engine import (
    AnnualCompetitionInput,
    BlockForestRuntimeState,
    DataRepository,
    MatchResolution,
    RoundRobinRuntimeState,
    SingleEliminationRuntimeState,
    SingleRoundGateRuntimeState,
    TournamentEngine,
)
from phase2_engine.brackets import (
    random_winner_resolver,
    run_block_winner_forest,
    run_round_robin,
    run_single_elimination_ranking,
    run_single_round_gate,
)


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
            team1_score=3,
            team2_score=1,
            score_source="stage13e3a_stub",
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
                "score_source": "stage13e3a_stub",
            },
        )


class Stage13E3APreMainRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.year = 2026
        cls.seed = 2026100803

    def test_single_elimination_runtime_matches_legacy_primitive(self):
        teams = ["S1", "S2", "S3", "S4", "S5"]
        legacy_resolver = StubDetailedResolver()
        lazy_resolver = StubDetailedResolver()
        legacy_sink = {}
        lazy_sink = {}

        ranking, matches = run_single_elimination_ranking(
            teams,
            competition_id="C",
            stage_id="STG",
            stage_code="QUAL",
            phase_code="KO",
            group_id="G",
            group_name="Group",
            base_seed=11,
            winner_resolver=random_winner_resolver(11),
            match_resolver=legacy_resolver,
            resolved_match_sink=legacy_sink,
            reference_year=2026,
        )
        runtime = SingleEliminationRuntimeState.create(
            teams,
            competition_id="C",
            reference_year=2026,
            stage_id="STG",
            stage_code="QUAL",
            phase_code="KO",
            group_id="G",
            group_name="Group",
            generation_seed=11,
            match_resolver=lazy_resolver,
            resolved_match_sink=lazy_sink,
        )

        self.assertEqual([], lazy_resolver.calls)
        self.assertEqual(ranking, runtime.resolve_all())
        self.assertEqual(matches, runtime.to_matches())
        self.assertEqual(legacy_sink, lazy_sink)
        self.assertEqual(legacy_resolver.calls, lazy_resolver.calls)

    def test_gate_runtime_matches_legacy_primitive(self):
        teams = ["S1", "S2", "S3", "S4", "S5"]
        legacy_resolver = StubDetailedResolver()
        lazy_resolver = StubDetailedResolver()
        legacy_sink = {}
        lazy_sink = {}

        winners, matches = run_single_round_gate(
            teams,
            competition_id="C",
            stage_id="STG",
            stage_code="GATE",
            phase_code="GATE_ROUND",
            base_seed=12,
            winner_resolver=random_winner_resolver(12),
            match_resolver=legacy_resolver,
            resolved_match_sink=legacy_sink,
            reference_year=2026,
        )
        runtime = SingleRoundGateRuntimeState.create(
            teams,
            competition_id="C",
            reference_year=2026,
            stage_id="STG",
            stage_code="GATE",
            phase_code="GATE_ROUND",
            generation_seed=12,
            match_resolver=lazy_resolver,
            resolved_match_sink=lazy_sink,
        )

        self.assertEqual(winners, runtime.resolve_all())
        self.assertEqual(matches, runtime.to_matches())
        self.assertEqual(legacy_sink, lazy_sink)

    def test_round_robin_runtime_matches_legacy_primitive(self):
        teams = ["S1", "S2", "S3", "S4"]
        legacy_resolver = StubDetailedResolver()
        lazy_resolver = StubDetailedResolver()
        legacy_sink = {}
        lazy_sink = {}

        ranking, matches, table = run_round_robin(
            teams,
            competition_id="C",
            stage_id="STG",
            stage_code="QUAL",
            phase_code="POOL_RR",
            group_id="G",
            group_name="Group",
            pool_no=1,
            base_seed=13,
            winner_resolver=random_winner_resolver(13),
            match_resolver=legacy_resolver,
            resolved_match_sink=legacy_sink,
            reference_year=2026,
        )
        runtime = RoundRobinRuntimeState.create(
            teams,
            competition_id="C",
            reference_year=2026,
            stage_id="STG",
            stage_code="QUAL",
            phase_code="POOL_RR",
            group_id="G",
            group_name="Group",
            pool_no=1,
            generation_seed=13,
            match_resolver=lazy_resolver,
            resolved_match_sink=lazy_sink,
        )

        self.assertEqual(ranking, runtime.resolve_all())
        self.assertEqual(matches, runtime.to_matches())
        self.assertEqual(table, runtime.standings())
        self.assertEqual(legacy_sink, lazy_sink)

    def test_block_forest_runtime_matches_legacy_primitive(self):
        teams = [f"S{i}" for i in range(1, 10)]
        legacy_resolver = StubDetailedResolver()
        lazy_resolver = StubDetailedResolver()
        legacy_sink = {}
        lazy_sink = {}

        winners, matches, blocks = run_block_winner_forest(
            teams,
            block_count=3,
            competition_id="C",
            stage_id="STG",
            stage_code="QUAL",
            phase_code="BLOCK_KO",
            group_id="G",
            group_name="Group",
            base_seed=14,
            winner_resolver=random_winner_resolver(14),
            match_resolver=legacy_resolver,
            resolved_match_sink=legacy_sink,
            reference_year=2026,
        )
        runtime = BlockForestRuntimeState.create(
            teams,
            block_count=3,
            competition_id="C",
            reference_year=2026,
            stage_id="STG",
            stage_code="QUAL",
            phase_code="BLOCK_KO",
            group_id="G",
            group_name="Group",
            generation_seed=14,
            match_resolver=lazy_resolver,
            resolved_match_sink=lazy_sink,
        )

        self.assertEqual(blocks, runtime.blocks)
        self.assertEqual(winners, runtime.resolve_all())
        self.assertEqual(matches, runtime.to_matches())
        self.assertEqual(legacy_sink, lazy_sink)

    def _hokkaido_spring_annual(self):
        competition_id = "CMP000004"
        qualifier = self.repo.stage_by_code(
            competition_id,
            "BRANCH_QUALIFIER",
        )
        entrants = set()
        for group in self.repo.groups_by_stage[qualifier["stage_id"]]:
            entrants |= self.repo.group_school_ids(group, self.year)

        direct_count = sum(
            int(rule.get("observed_2026_count") or 0)
            for rule in self.repo.access_rules(competition_id)
            if rule.get("grants_main_entry") == "yes"
        )
        ordered = sorted(entrants)
        return AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=ordered,
            direct_main_entry_school_ids=ordered[:direct_count],
            rng_seed=self.seed,
        )

    def test_fmt001_qualifier_main_lazy_run_exactly_matches_legacy(self):
        annual = self._hokkaido_spring_annual()
        legacy = TournamentEngine(self.repo).run(annual)

        runtime = TournamentEngine(
            self.repo
        ).prepare_qualifier_main_runtime(
            self._hokkaido_spring_annual()
        )
        self.assertFalse(runtime.qualifier_complete)
        self.assertIsNone(runtime.main_runtime)
        self.assertEqual([], runtime.main_entrant_school_ids)

        lazy = runtime.resolve_all()
        self.assertEqual(legacy.to_dict(), lazy.to_dict())

    def test_main_is_not_created_until_all_qualifier_groups_complete(self):
        resolver = StubDetailedResolver()
        engine = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
            pre_main_match_resolver=resolver,
        )
        runtime = engine.prepare_qualifier_main_runtime(
            self._hokkaido_spring_annual()
        )

        self.assertEqual([], resolver.calls)
        self.assertIsNone(runtime.main_runtime)
        self.assertTrue(runtime.ready_matches())

        while not runtime.qualifier_complete:
            before = len(resolver.calls)
            resolved = runtime.resolve_ready_round()
            self.assertTrue(resolved)
            self.assertGreater(len(resolver.calls), before)
            if not runtime.qualifier_complete:
                self.assertIsNone(runtime.main_runtime)

        self.assertIsNotNone(runtime.main_runtime)
        pre_main_call_count = len(resolver.calls)
        self.assertGreater(pre_main_call_count, 0)
        self.assertTrue(runtime.main_runtime.ready_matches())
        self.assertEqual(
            pre_main_call_count,
            len(resolver.calls),
        )

        runtime.main_runtime.resolve_ready_round()
        self.assertGreater(
            len(resolver.calls),
            pre_main_call_count,
        )

    def test_detailed_resolver_results_exist_only_after_match_resolution(self):
        resolver = StubDetailedResolver()
        runtime = TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
            pre_main_match_resolver=resolver,
        ).prepare_qualifier_main_runtime(
            self._hokkaido_spring_annual()
        )

        self.assertEqual(
            {},
            runtime.pre_main_match_simulation_results,
        )
        target = runtime.ready_matches()[0]["match_id"]
        runtime.resolve_match(target)
        self.assertIn(
            target,
            runtime.pre_main_match_simulation_results,
        )
        snapshot = runtime.public_snapshot()
        self.assertFalse(snapshot["main_activated"])
        self.assertEqual([], snapshot["main_entrant_school_ids"])

    def test_fmt006_graph_remains_explicitly_out_of_stage13e3a_scope(self):
        competition_id = "CMP000095"
        pcode = self.repo.competition(competition_id)["prefecture_code"]
        entrants = sorted(
            school_id
            for school_id, row in self.repo.schools.items()
            if row.get("prefecture_code") == pcode
        )
        annual = AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=entrants,
            rng_seed=self.seed,
        )
        with self.assertRaises(NotImplementedError):
            TournamentEngine(
                self.repo
            ).prepare_qualifier_main_runtime(annual)


if __name__ == "__main__":
    unittest.main()
