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
            team1_score=5,
            team2_score=3,
            score_source="stage13e3b2_stub",
            detail={
                "match_id": match_id,
                "competition_id": competition_id,
                "reference_year": reference_year,
                "generation_seed": generation_seed,
                "team1_school_id": team1,
                "team2_school_id": team2,
                "team1_score": 5,
                "team2_score": 3,
                "winner_id": team1,
                "loser_id": team2,
                "score_source": "stage13e3b2_stub",
            },
        )


class Stage13E3B2CompositeRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.year = 2026
        cls.seed = 2026100807

    def _input_for(self, competition_id: str, seed: int | None = None):
        stages = self.repo.stages(competition_id)
        event_groups = []
        entrants = set()
        for stage in stages:
            if stage["stage_id"] not in self.repo.assignments_by_stage:
                continue
            for group in self.repo.groups_by_stage.get(stage["stage_id"], []):
                event_groups.append(group)
                entrants |= self.repo.group_school_ids(group, self.year)

        group_override = {}
        if not entrants:
            prefecture_code = self.repo.competition(
                competition_id
            ).get("prefecture_code")
            candidates = sorted(
                school_id
                for school_id, row in self.repo.schools.items()
                if row.get("prefecture_code") == prefecture_code
            )
            entrants = set(candidates)
            self.assertTrue(event_groups)
            for idx, school_id in enumerate(candidates):
                gid = event_groups[idx % len(event_groups)]["stage_group_id"]
                group_override.setdefault(gid, []).append(school_id)

        for group in event_groups:
            if (
                group.get("stage_code") == "PRELIMINARY_QUALIFIER"
                and not self.repo.group_school_ids(group, self.year)
                and group["stage_group_id"] not in group_override
            ):
                group_override[group["stage_group_id"]] = sorted(entrants)

        return AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=sorted(entrants),
            rng_seed=self.seed if seed is None else seed,
            group_entrant_school_ids=group_override,
        )

    def test_all_b2_qualifier_competitions_match_legacy_exactly(self):
        competition_ids = [
            "CMP000074",
            "CMP000075",
            "CMP000076",
            "CMP000077",
            "CMP000082",
            "CMP000083",
            "CMP000085",
            "CMP000093",
            "CMP000107",
            "CMP000108",
            "CMP000109",
            "CMP000111",
            "CMP000112",
            "CMP000113",
            "CMP000114",
            "CMP000115",
            "CMP000124",
            "CMP000134",
            "CMP000135",
            "CMP000136",
        ]
        covered_models = set()
        for index, competition_id in enumerate(competition_ids):
            with self.subTest(competition_id=competition_id):
                annual = self._input_for(
                    competition_id,
                    seed=self.seed + index,
                )
                legacy = TournamentEngine(self.repo).run(annual)
                lazy = TournamentEngine(
                    self.repo
                ).prepare_qualifier_main_runtime(
                    annual
                ).resolve_all()
                self.assertEqual(legacy.to_dict(), lazy.to_dict())
                qualifier = lazy.stage_executions[0]
                covered_models.add(qualifier.format_model_id)
                covered_models.update(
                    qualifier.metadata.get("group_models", {}).values()
                )

        self.assertTrue(
            {
                "FMT002",
                "FMT003",
                "FMT004",
                "FMT005",
                "FMT007",
                "FMT008",
                "FMT010",
                "FMT011",
                "FMT012",
                "FMT013",
                "FMT014",
                "FMT015",
                "FMT016",
                "FMT017",
                "FMT025",
            }.issubset(covered_models)
        )

    def test_fmt025_skips_ranking_without_explicit_requirement(self):
        for competition_id in ("CMP000112", "CMP000136"):
            with self.subTest(competition_id=competition_id):
                annual = self._input_for(competition_id)
                legacy = TournamentEngine(self.repo).run(annual)
                lazy = TournamentEngine(
                    self.repo
                ).prepare_qualifier_main_runtime(
                    annual
                ).resolve_all()

                for run in (legacy, lazy):
                    qualifier = next(
                        execution
                        for execution in run.stage_executions
                        if execution.stage_code == "BRANCH_QUALIFIER"
                    )
                    self.assertNotIn(
                        "RANKING",
                        {
                            match.phase_code
                            for match in qualifier.matches
                        },
                    )

    def test_repechage_is_not_created_before_primary_completion(self):
        resolver = StubDetailedResolver()
        runtime = TournamentEngine(
            self.repo,
            pre_main_match_resolver=resolver,
            main_match_resolver=resolver,
        ).prepare_qualifier_main_runtime(
            self._input_for("CMP000074")
        )

        self.assertEqual([], resolver.calls)
        self.assertIsNone(runtime.main_runtime)
        self.assertTrue(runtime.qualifier_groups)
        self.assertEqual(
            {"PRIMARY"},
            {
                row["phase_code"]
                for row in runtime.ready_matches()
            },
        )

        group = runtime.qualifier_groups[0]
        self.assertEqual(["primary"], [phase.key for phase in group.phases])
        group.phases[0].resolve_all()
        self.assertEqual(["primary"], [phase.key for phase in group.phases])
        self.assertIsNone(runtime.main_runtime)

        ready = group.ready_matches()
        self.assertTrue(ready)
        self.assertEqual(
            {"REPECHAGE"},
            {row["phase_code"] for row in ready},
        )
        self.assertEqual(
            ["primary", "secondary"],
            [phase.key for phase in group.phases],
        )
        self.assertIsNone(runtime.main_runtime)

    def test_fmt005_global_repechage_activates_lazily(self):
        resolver = StubDetailedResolver()
        runtime = TournamentEngine(
            self.repo,
            pre_main_match_resolver=resolver,
            main_match_resolver=resolver,
        ).prepare_qualifier_main_runtime(
            self._input_for("CMP000093", seed=2026100810)
        )

        group = runtime.qualifier_groups[0]
        self.assertIsNone(group.repechage)
        self.assertEqual(
            {"PRIMARY_GLOBAL"},
            {
                row["phase_code"]
                for row in runtime.ready_matches()
            },
        )
        self.assertEqual([], resolver.calls)
        self.assertIsNone(runtime.main_runtime)

        group.primary.resolve_all()
        self.assertIsNone(group.repechage)
        ready = group.ready_matches()
        self.assertIsNotNone(group.repechage)
        self.assertTrue(ready)
        self.assertEqual(
            {"REPECHAGE_GLOBAL"},
            {row["phase_code"] for row in ready},
        )
        self.assertIsNone(runtime.main_runtime)

    def test_mixed_model_competition_preserves_phase_codes(self):
        annual = self._input_for("CMP000114", seed=2026100811)
        legacy = TournamentEngine(self.repo).run(annual)
        lazy = TournamentEngine(
            self.repo
        ).prepare_qualifier_main_runtime(annual).resolve_all()

        self.assertEqual(legacy.to_dict(), lazy.to_dict())
        phases = {
            match.phase_code
            for execution in lazy.stage_executions
            for match in execution.matches
        }
        self.assertTrue(
            {
                "PRIMARY_BLOCKS",
                "PRIMARY_LEAGUE",
                "PRIMARY_ZONES",
                "PRIMARY",
                "PRIMARY_REPECHAGE",
                "SECONDARY",
            }.issubset(phases)
        )

    def test_detailed_resolver_sequence_matches_legacy(self):
        annual = self._input_for("CMP000114", seed=2026100812)
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
        ).prepare_qualifier_main_runtime(
            annual
        ).resolve_all()

        self.assertEqual(legacy.to_dict(), lazy.to_dict())
        self.assertEqual(legacy_resolver.calls, lazy_resolver.calls)
        self.assertEqual(
            set(lazy.match_simulation_results),
            set(lazy_resolver.calls),
        )


if __name__ == "__main__":
    unittest.main()
