from __future__ import annotations

import unittest
from pathlib import Path

from phase2_engine import (
    AnnualCompetitionInput,
    DataRepository,
    MatchResolution,
    TournamentEngine,
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
            team1_score=6,
            team2_score=2,
            score_source="stage13e3b3_stub",
            detail={
                "match_id": match_id,
                "competition_id": competition_id,
                "reference_year": reference_year,
                "generation_seed": generation_seed,
                "team1_school_id": team1,
                "team2_school_id": team2,
                "team1_score": 6,
                "team2_score": 2,
                "winner_id": team1,
                "loser_id": team2,
                "score_source": "stage13e3b3_stub",
            },
        )


class Stage13E3B3SeedEventRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.year = 2026
        cls.seed = 2026100813

    def _prefecture_schools(self, competition_id: str):
        pcode = self.repo.competition(
            competition_id
        ).get("prefecture_code")
        return sorted(
            school_id
            for school_id, row in self.repo.schools.items()
            if row.get("prefecture_code") == pcode
        )

    def _input_for(
        self,
        competition_id: str,
        seed: int | None = None,
    ):
        stages = self.repo.stages(competition_id)
        assigned_stages = [
            stage
            for stage in stages
            if stage["stage_id"]
            in self.repo.assignments_by_stage
        ]
        groups = []
        entrants = set()
        for stage in assigned_stages:
            for group in self.repo.groups_by_stage.get(
                stage["stage_id"],
                [],
            ):
                groups.append(group)
                entrants |= self.repo.group_school_ids(
                    group,
                    self.year,
                )

        group_override = {}
        if not entrants:
            candidates = self._prefecture_schools(
                competition_id
            )
            entrants = set(candidates)
            for index, school_id in enumerate(candidates):
                gid = groups[index % len(groups)][
                    "stage_group_id"
                ]
                group_override.setdefault(gid, []).append(
                    school_id
                )

        for group in groups:
            if (
                group.get("stage_code")
                == "PRELIMINARY_QUALIFIER"
                and not self.repo.group_school_ids(
                    group,
                    self.year,
                )
                and group["stage_group_id"]
                not in group_override
            ):
                group_override[
                    group["stage_group_id"]
                ] = sorted(entrants)

        direct_count = sum(
            int(rule.get("observed_2026_count") or 0)
            for rule in self.repo.access_rules(
                competition_id
            )
            if rule.get("grants_main_entry") == "yes"
        )
        direct = sorted(entrants)[:direct_count]

        annual = AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=sorted(entrants),
            direct_main_entry_school_ids=direct,
            rng_seed=self.seed if seed is None else seed,
            group_entrant_school_ids=group_override,
        )

        if competition_id == "CMP000110":
            seed_stage = self.repo.stage_by_code(
                competition_id,
                "SEED_EVENT",
            )
            target_counts = [20, 10, 18, 10]
            chosen = []
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
                chosen.extend(ids)
                overrides[
                    group["stage_group_id"]
                ] = ids
            annual.entrant_school_ids = chosen
            annual.group_entrant_school_ids = overrides
            annual.direct_main_entry_school_ids = []

        return annual

    def test_all_seed_graph_competitions_match_legacy_exactly(self):
        competition_ids = [
            "CMP000072",
            "CMP000073",
            "CMP000110",
            "CMP000116",
            "CMP000140",
            "CMP000144",
            "CMP000158",
            "CMP000160",
            "CMP000162",
        ]
        graph_types = set()
        for index, competition_id in enumerate(
            competition_ids
        ):
            with self.subTest(
                competition_id=competition_id
            ):
                annual = self._input_for(
                    competition_id,
                    seed=self.seed + index,
                )
                legacy = TournamentEngine(
                    self.repo
                ).run(annual)
                runtime = TournamentEngine(
                    self.repo
                ).prepare_seeded_competition_runtime(
                    annual
                )
                graph_types.add(runtime.graph_type)
                lazy = runtime.resolve_all()
                self.assertEqual(
                    legacy.seed_assignments,
                    lazy.seed_assignments,
                    f"{competition_id}: seed assignments differ",
                )
                self.assertEqual(
                    legacy.main_entrant_school_ids,
                    lazy.main_entrant_school_ids,
                    f"{competition_id}: MAIN entrants differ",
                )
                self.assertEqual(
                    legacy.stage_executions,
                    lazy.stage_executions,
                    f"{competition_id}: stage executions differ",
                )
                self.assertEqual(
                    legacy.to_dict(),
                    lazy.to_dict(),
                )

        self.assertEqual(
            {
                "seed_main",
                "seed_gate_main",
                "seed_qualifier_main",
            },
            graph_types,
        )

    def test_prepare_seed_graph_resolves_nothing(self):
        for competition_id in [
            "CMP000072",
            "CMP000110",
            "CMP000144",
        ]:
            with self.subTest(
                competition_id=competition_id
            ):
                resolver = StubDetailedResolver()
                runtime = TournamentEngine(
                    self.repo,
                    pre_main_match_resolver=resolver,
                    main_match_resolver=resolver,
                ).prepare_seeded_competition_runtime(
                    self._input_for(competition_id)
                )
                self.assertEqual([], resolver.calls)
                snapshot = runtime.public_snapshot()
                self.assertFalse(
                    snapshot["gate_activated"]
                )
                self.assertFalse(
                    snapshot["qualifier_activated"]
                )
                self.assertFalse(
                    snapshot["main_activated"]
                )
                self.assertTrue(
                    snapshot["ready_match_ids"]
                )

    def test_fmt018_repechage_activates_after_primary_seed_ko(self):
        runtime = TournamentEngine(
            self.repo
        ).prepare_seeded_competition_runtime(
            self._input_for(
                "CMP000072",
                seed=2026100815,
            )
        )
        group = next(
            item
            for item in runtime.seed_runtime.group_runtimes
            if item.format_model_id == "FMT018"
        )
        self.assertIsNone(group.secondary)
        self.assertEqual(
            {"PRIMARY_SEED_KO"},
            {
                row["phase_code"]
                for row in group.ready_matches()
            },
        )

        group.primary.resolve_all()
        self.assertIsNone(group.secondary)
        ready = group.ready_matches()
        self.assertIsNotNone(group.secondary)
        self.assertEqual(
            {"SEED_REPECHAGE"},
            {
                row["phase_code"]
                for row in ready
            },
        )
        self.assertFalse(runtime.seed_complete)

    def test_gifu_gate_and_main_activate_in_order(self):
        resolver = StubDetailedResolver()
        runtime = TournamentEngine(
            self.repo,
            pre_main_match_resolver=resolver,
            main_match_resolver=resolver,
        ).prepare_seeded_competition_runtime(
            self._input_for(
                "CMP000110",
                seed=2026100816,
            )
        )
        self.assertIsNone(runtime.gate_runtime)
        self.assertIsNone(runtime.main_runtime)

        runtime.seed_runtime.resolve_all()
        self.assertIsNone(runtime.gate_runtime)
        runtime.ready_matches()
        self.assertIsNotNone(runtime.gate_runtime)
        self.assertIsNone(runtime.main_runtime)
        self.assertEqual(
            {"GATE_ROUND"},
            {
                row["phase_code"]
                for row in runtime.ready_matches()
            },
        )

        runtime.gate_runtime.resolve_all()
        self.assertIsNone(runtime.main_runtime)
        runtime.ready_matches()
        self.assertIsNotNone(runtime.main_runtime)

    def test_ehime_qualifier_is_created_after_seed_event(self):
        runtime = TournamentEngine(
            self.repo
        ).prepare_seeded_competition_runtime(
            self._input_for(
                "CMP000144",
                seed=2026100817,
            )
        )
        self.assertIsNone(runtime.qualifier_runtime)

        runtime.seed_runtime.resolve_all()
        self.assertIsNone(runtime.qualifier_runtime)
        runtime.ready_matches()
        self.assertIsNotNone(runtime.qualifier_runtime)
        self.assertIsNone(
            runtime.qualifier_runtime.main_runtime
        )

        protected = runtime._seed_assignments()
        self.assertEqual(12, len(protected))
        qualifier = runtime.qualifier_runtime
        self.assertEqual(
            12,
            sum(
                group.protected_seed_count
                for group in qualifier.qualifier_groups
            ),
        )

        qualifier.resolve_all()
        execution = qualifier.qualifier_stage_execution()
        self.assertEqual(
            12,
            execution.metadata["protected_seed_count"],
        )
        self.assertEqual(
            12,
            len(
                execution.metadata[
                    "protected_seed_blocks"
                ]
            ),
        )

    def test_detailed_resolver_sequence_matches_legacy_gifu(self):
        annual = self._input_for(
            "CMP000110",
            seed=2026100818,
        )
        legacy_resolver = StubDetailedResolver()
        lazy_resolver = StubDetailedResolver()

        legacy = TournamentEngine(
            self.repo,
            pre_main_match_resolver=legacy_resolver,
            main_match_resolver=legacy_resolver,
        ).run(annual)
        lazy = TournamentEngine(
            self.repo,
            pre_main_match_resolver=lazy_resolver,
            main_match_resolver=lazy_resolver,
        ).prepare_seeded_competition_runtime(
            annual
        ).resolve_all()

        self.assertEqual(
            legacy.seed_assignments,
            lazy.seed_assignments,
            "Gifu detailed: seed assignments differ",
        )
        self.assertEqual(
            legacy.main_entrant_school_ids,
            lazy.main_entrant_school_ids,
            "Gifu detailed: MAIN entrants differ",
        )
        self.assertEqual(
            legacy_resolver.calls,
            lazy_resolver.calls,
            "Gifu detailed: resolver call order differs",
        )
        self.assertEqual(
            legacy.to_dict(),
            lazy.to_dict(),
        )
        self.assertEqual(
            set(lazy.match_simulation_results),
            set(lazy_resolver.calls),
        )

    def test_fmt022_stops_when_top_four_seed_pool_is_known(self):
        for competition_id in ("CMP000140", "CMP000162"):
            with self.subTest(competition_id=competition_id):
                annual = self._input_for(competition_id)
                legacy = TournamentEngine(self.repo).run(annual)
                lazy = TournamentEngine(
                    self.repo
                ).prepare_seeded_competition_runtime(
                    annual
                ).resolve_all()

                for run in (legacy, lazy):
                    seed_stage = next(
                        execution
                        for execution in run.stage_executions
                        if execution.stage_code == "SEED_EVENT"
                    )
                    self.assertEqual(
                        4,
                        len(seed_stage.output_school_ids),
                    )
                    self.assertEqual(
                        len(seed_stage.entrant_school_ids) - 4,
                        len([
                            match
                            for match in seed_stage.matches
                            if not match.is_bye
                        ]),
                    )

    def test_unified_dispatcher_selects_seed_runtime(self):
        runtime = TournamentEngine(
            self.repo
        ).prepare_competition_runtime(
            self._input_for("CMP000162")
        )
        self.assertEqual(
            "seed_main",
            runtime.graph_type,
        )


if __name__ == "__main__":
    unittest.main()
