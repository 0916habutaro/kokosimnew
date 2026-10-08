from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .models import (
    AnnualCompetitionInput,
    CompetitionRun,
    MatchResolution,
    SeedAssignment,
    StageExecution,
)
from .premain_competition_runtime import QualifierMainRuntimeState
from .premain_runtime_gate import SingleRoundGateRuntimeState
from .premain_runtime_seed_event import SeedEventRuntimeState
from .repository import DataRepository
from .tournament_runtime import MainTournamentRuntimeState


@dataclass
class SeededCompetitionRuntimeState:
    repo: DataRepository
    annual: AnnualCompetitionInput
    entrant_school_ids: List[str]
    direct_main_entry_school_ids: List[str]
    stage_by_code: Dict[str, dict]
    graph_type: str
    seed_runtime: SeedEventRuntimeState
    qualifier_entrant_school_ids: List[str] = field(default_factory=list)
    qualifier_warnings: List[str] = field(default_factory=list)
    gate_runtime: SingleRoundGateRuntimeState | None = None
    gate_entrant_school_ids: List[str] = field(default_factory=list)
    qualifier_runtime: QualifierMainRuntimeState | None = None
    main_runtime: MainTournamentRuntimeState | None = None
    warnings: List[str] = field(default_factory=list)
    pre_main_match_simulation_results: Dict[str, dict] = field(
        default_factory=dict
    )
    pre_main_match_resolver: object | None = field(default=None, repr=False)
    main_match_resolver: object | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        *,
        repo: DataRepository,
        annual: AnnualCompetitionInput,
        entrants: Sequence[str],
        direct: Sequence[str],
        stage_by_code: Dict[str, dict],
        qualifier_entrants: Sequence[str] = (),
        qualifier_warnings: Sequence[str] = (),
        pre_main_match_resolver=None,
        main_match_resolver=None,
    ) -> "SeededCompetitionRuntimeState":
        if "SEED_EVENT" not in stage_by_code or "MAIN" not in stage_by_code:
            raise ValueError(
                "seeded competition runtime requires SEED_EVENT and MAIN"
            )

        if "FIRST_TOURNAMENT" in stage_by_code:
            if any(
                code in stage_by_code
                for code in (
                    "BRANCH_QUALIFIER",
                    "PRELIMINARY_QUALIFIER",
                )
            ):
                raise ValueError(
                    "seed+gate graph cannot also contain qualifier stage"
                )
            graph_type = "seed_gate_main"
        elif any(
            code in stage_by_code
            for code in (
                "BRANCH_QUALIFIER",
                "PRELIMINARY_QUALIFIER",
            )
        ):
            graph_type = "seed_qualifier_main"
        else:
            graph_type = "seed_main"

        sink: Dict[str, dict] = {}
        seed_runtime = SeedEventRuntimeState.create(
            repo=repo,
            annual=annual,
            entrants=entrants,
            stage=stage_by_code["SEED_EVENT"],
            match_resolver=pre_main_match_resolver,
            resolved_match_sink=sink,
        )

        return cls(
            repo=repo,
            annual=annual,
            entrant_school_ids=list(entrants),
            direct_main_entry_school_ids=list(direct),
            stage_by_code={
                key: dict(value)
                for key, value in stage_by_code.items()
            },
            graph_type=graph_type,
            seed_runtime=seed_runtime,
            qualifier_entrant_school_ids=list(qualifier_entrants),
            qualifier_warnings=list(qualifier_warnings),
            pre_main_match_simulation_results=sink,
            pre_main_match_resolver=pre_main_match_resolver,
            main_match_resolver=main_match_resolver,
        )

    @property
    def seed_complete(self) -> bool:
        return self.seed_runtime.is_complete

    @property
    def is_complete(self) -> bool:
        if self.graph_type == "seed_qualifier_main":
            return (
                self.qualifier_runtime is not None
                and self.qualifier_runtime.is_complete
            )
        return (
            self.main_runtime is not None
            and self.main_runtime.is_complete
        )

    def _seed_assignments(self) -> list[SeedAssignment]:
        return self.seed_runtime.seed_assignments()

    def _main_seed_assignments(
        self,
        assignments: Sequence[SeedAssignment],
    ) -> list[SeedAssignment]:
        return [
            assignment
            for assignment in assignments
            if assignment.destination_stage
            in {
                "",
                "MAIN",
                "prefectural_main_draw",
                "second_tournament",
            }
        ]

    def _main_runtime_for(
        self,
        entrants: Sequence[str],
        assignments: Sequence[SeedAssignment],
    ) -> MainTournamentRuntimeState:
        annual_seeds = list(
            dict.fromkeys(self.annual.main_seed_school_ids)
        )
        outside = set(annual_seeds) - set(entrants)
        if outside:
            raise ValueError(
                f"MAIN seeds outside MAIN entrant set: {sorted(outside)}"
            )
        return MainTournamentRuntimeState.create(
            competition_id=self.annual.competition_id,
            reference_year=self.annual.year,
            generation_seed=self.annual.rng_seed,
            stage_id=self.stage_by_code["MAIN"]["stage_id"],
            entrants=list(entrants),
            seed_assignments=self._main_seed_assignments(assignments),
            annual_seed_order=annual_seeds,
            slot_override=(
                self.annual.main_bracket_slots
                if self.annual.main_bracket_slots
                else None
            ),
            winner_overrides=self.annual.main_match_winner_overrides,
            match_resolver=self.main_match_resolver,
        )

    def _activate_after_seed(self) -> None:
        if not self.seed_complete:
            return
        assignments = self._seed_assignments()

        if self.graph_type == "seed_gate_main":
            if self.gate_runtime is not None:
                return
            if self.direct_main_entry_school_ids:
                raise NotImplementedError(
                    "seed+gate graph with direct MAIN access is "
                    "not yet required by current data"
                )
            seeded_ids = {
                assignment.school_id
                for assignment in assignments
            }
            nonseed = [
                school_id
                for school_id in self.entrant_school_ids
                if school_id not in seeded_ids
            ]
            gate_stage = self.stage_by_code["FIRST_TOURNAMENT"]
            gate_assignment = self.repo.assignments_by_stage.get(
                gate_stage["stage_id"]
            )
            if (
                not gate_assignment
                or gate_assignment["default_format_model_id"]
                != "FMT026"
            ):
                raise NotImplementedError(
                    "gate handler requires FMT026"
                )
            self.gate_entrant_school_ids = list(nonseed)
            self.gate_runtime = SingleRoundGateRuntimeState.create(
                nonseed,
                competition_id=self.annual.competition_id,
                reference_year=self.annual.year,
                stage_id=gate_stage["stage_id"],
                stage_code=gate_stage["stage_code"],
                phase_code="GATE_ROUND",
                generation_seed=self.annual.rng_seed,
                match_resolver=self.pre_main_match_resolver,
                resolved_match_sink=(
                    self.pre_main_match_simulation_results
                ),
            )
            return

        if self.graph_type == "seed_qualifier_main":
            if self.qualifier_runtime is not None:
                return
            qualifier_code = next(
                code
                for code in (
                    "BRANCH_QUALIFIER",
                    "PRELIMINARY_QUALIFIER",
                )
                if code in self.stage_by_code
            )
            self.qualifier_runtime = QualifierMainRuntimeState.create(
                repo=self.repo,
                annual=self.annual,
                entrants=self.entrant_school_ids,
                direct=self.direct_main_entry_school_ids,
                qualifier_entrants=self.qualifier_entrant_school_ids,
                qualifier_stage=self.stage_by_code[qualifier_code],
                main_stage=self.stage_by_code["MAIN"],
                warnings=self.qualifier_warnings,
                pre_main_match_resolver=self.pre_main_match_resolver,
                main_match_resolver=self.main_match_resolver,
                protected_seed_school_ids=[
                    assignment.school_id
                    for assignment in assignments
                ],
            )
            return

        if self.main_runtime is None:
            self.main_runtime = self._main_runtime_for(
                self.entrant_school_ids,
                assignments,
            )
            self._append_main_count_warning(
                len(self.entrant_school_ids)
            )

    def _activate_main_after_gate(self) -> None:
        if (
            self.graph_type != "seed_gate_main"
            or self.gate_runtime is None
            or not self.gate_runtime.is_complete
            or self.main_runtime is not None
        ):
            return

        assignments = self._seed_assignments()
        main_entrants = [
            assignment.school_id
            for assignment in assignments
        ] + self.gate_runtime.winners()
        if len(main_entrants) != len(set(main_entrants)):
            raise AssertionError("duplicate team entered MAIN")

        gate_stage = self.stage_by_code["FIRST_TOURNAMENT"]
        expected = {
            "nonseed": self.repo.param(
                gate_stage["stage_id"],
                "observed_nonseed_gate_teams",
            ),
            "winners": self.repo.param(
                gate_stage["stage_id"],
                "observed_gate_winner_slots",
            ),
            "seed": self.repo.param(
                gate_stage["stage_id"],
                "seed_bypass_slots",
            ),
            "main": self.repo.param(
                gate_stage["stage_id"],
                "observed_second_stage_total",
            ),
        }
        observed = {
            "nonseed": len(self.gate_entrant_school_ids),
            "winners": len(self.gate_runtime.winners()),
            "seed": len(assignments),
            "main": len(main_entrants),
        }
        for key, expected_value in expected.items():
            if (
                expected_value is not None
                and observed[key] != expected_value
            ):
                self.warnings.append(
                    f"2026 observed {key}={expected_value}, "
                    f"current run={observed[key]}"
                )

        self.main_runtime = self._main_runtime_for(
            main_entrants,
            assignments,
        )
        self._append_main_count_warning(len(main_entrants))

    def _append_main_count_warning(self, entrant_count: int) -> None:
        expected = self.stage_by_code["MAIN"].get("team_count", "")
        if self.annual.year != 2026 or not expected:
            return
        try:
            expected_n = int(expected)
        except ValueError:
            expected_n = 0
        if expected_n and expected_n != entrant_count:
            self.warnings.append(
                f"2026 MAIN team_count={expected_n}, "
                f"current input/resolution={entrant_count}"
            )

    def ready_matches(self) -> list[dict]:
        if not self.seed_complete:
            return self.seed_runtime.ready_matches()

        self._activate_after_seed()

        if self.graph_type == "seed_gate_main":
            if not self.gate_runtime.is_complete:
                return self.gate_runtime.ready_matches()
            self._activate_main_after_gate()
            return self.main_runtime.ready_matches()

        if self.graph_type == "seed_qualifier_main":
            return self.qualifier_runtime.ready_matches()

        return self.main_runtime.ready_matches()

    def resolve_match(self, match_id: str) -> MatchResolution:
        if not self.seed_complete:
            result = self.seed_runtime.resolve_match(match_id)
            if self.seed_complete:
                self._activate_after_seed()
            return result

        self._activate_after_seed()

        if self.graph_type == "seed_gate_main":
            if not self.gate_runtime.is_complete:
                result = self.gate_runtime.resolve_match(match_id)
                if self.gate_runtime.is_complete:
                    self._activate_main_after_gate()
                return result
            self._activate_main_after_gate()
            return self.main_runtime.resolve_match(match_id)

        if self.graph_type == "seed_qualifier_main":
            return self.qualifier_runtime.resolve_match(match_id)

        return self.main_runtime.resolve_match(match_id)

    def resolve_ready_round(self) -> list[MatchResolution]:
        if not self.seed_complete:
            results = self.seed_runtime.resolve_ready_round()
            if self.seed_complete:
                self._activate_after_seed()
            return results

        self._activate_after_seed()

        if self.graph_type == "seed_gate_main":
            if not self.gate_runtime.is_complete:
                ready = list(self.gate_runtime.ready_matches())
                results = [
                    self.gate_runtime.resolve_match(row["match_id"])
                    for row in ready
                ]
                if self.gate_runtime.is_complete:
                    self._activate_main_after_gate()
                return results
            self._activate_main_after_gate()
            return self.main_runtime.resolve_ready_round()

        if self.graph_type == "seed_qualifier_main":
            return self.qualifier_runtime.resolve_ready_round()

        return self.main_runtime.resolve_ready_round()

    def resolve_all(self) -> CompetitionRun:
        self.seed_runtime.resolve_all()
        self._activate_after_seed()

        if self.graph_type == "seed_gate_main":
            self.gate_runtime.resolve_all()
            self._activate_main_after_gate()
            self.main_runtime.resolve_all()
        elif self.graph_type == "seed_qualifier_main":
            self.qualifier_runtime.resolve_all()
        else:
            self.main_runtime.resolve_all()

        return self.to_competition_run()

    def _gate_stage_execution(self) -> StageExecution:
        if self.gate_runtime is None or not self.gate_runtime.is_complete:
            raise ValueError(
                "FIRST_TOURNAMENT StageExecution unavailable before completion"
            )
        assignments = self._seed_assignments()
        winners = self.gate_runtime.winners()
        return StageExecution(
            stage_id=self.stage_by_code["FIRST_TOURNAMENT"]["stage_id"],
            stage_code="FIRST_TOURNAMENT",
            format_model_id="FMT026",
            entrant_school_ids=list(
                self.gate_entrant_school_ids
            ),
            output_school_ids=list(winners),
            matches=self.gate_runtime.to_matches(),
            metadata={
                "seed_bypass_count": len(assignments),
                "nonseed_count": len(
                    self.gate_entrant_school_ids
                ),
                "gate_winner_count": len(winners),
                "bye_count": sum(
                    1
                    for match in self.gate_runtime.to_matches()
                    if match.is_bye
                ),
            },
        )

    def to_competition_run(self) -> CompetitionRun:
        if not self.is_complete:
            raise ValueError(
                "competition run unavailable before completion"
            )

        assignments = self._seed_assignments()
        seed_execution = self.seed_runtime.stage_execution()

        if self.graph_type == "seed_qualifier_main":
            qualifier_execution = (
                self.qualifier_runtime.qualifier_stage_execution()
            )
            qualifier_execution.metadata[
                "seed_context_school_ids"
            ] = [
                assignment.school_id
                for assignment in assignments
            ]
            qualifier_execution.metadata[
                "seed_context_count"
            ] = len(assignments)

            results = dict(
                self.pre_main_match_simulation_results
            )
            results.update(
                self.qualifier_runtime
                .pre_main_match_simulation_results
            )
            results.update(
                self.qualifier_runtime
                .main_runtime
                .match_simulation_results
            )
            return CompetitionRun(
                competition_id=self.annual.competition_id,
                year=self.annual.year,
                rng_seed=self.annual.rng_seed,
                entrant_school_ids=list(
                    self.entrant_school_ids
                ),
                seed_assignments=list(assignments),
                stage_executions=[
                    seed_execution,
                    qualifier_execution,
                    self.qualifier_runtime
                    .main_runtime
                    .stage_execution(),
                ],
                main_entrant_school_ids=list(
                    self.qualifier_runtime
                    .main_entrant_school_ids
                ),
                warnings=list(
                    self.qualifier_runtime.warnings
                ),
                outcome=(
                    self.qualifier_runtime
                    .main_runtime
                    ._outcome()
                ),
                match_simulation_results=results,
            )

        results = dict(
            self.pre_main_match_simulation_results
        )
        results.update(
            self.main_runtime.match_simulation_results
        )
        stage_executions = [seed_execution]
        main_entrants = list(
            self.main_runtime.entrant_school_ids
        )
        if self.graph_type == "seed_gate_main":
            stage_executions.append(
                self._gate_stage_execution()
            )
        stage_executions.append(
            self.main_runtime.stage_execution()
        )
        return CompetitionRun(
            competition_id=self.annual.competition_id,
            year=self.annual.year,
            rng_seed=self.annual.rng_seed,
            entrant_school_ids=list(
                self.entrant_school_ids
            ),
            seed_assignments=list(assignments),
            stage_executions=stage_executions,
            main_entrant_school_ids=main_entrants,
            warnings=list(self.warnings),
            outcome=self.main_runtime._outcome(),
            match_simulation_results=results,
        )

    def public_snapshot(self) -> dict:
        main = None
        if self.graph_type == "seed_qualifier_main":
            if (
                self.qualifier_runtime is not None
                and self.qualifier_runtime.main_runtime is not None
            ):
                main = (
                    self.qualifier_runtime
                    .main_runtime
                    .public_snapshot()
                )
        elif self.main_runtime is not None:
            main = self.main_runtime.public_snapshot()

        return {
            "competition_id": self.annual.competition_id,
            "year": self.annual.year,
            "graph_type": self.graph_type,
            "seed_complete": self.seed_complete,
            "gate_activated": self.gate_runtime is not None,
            "qualifier_activated": (
                self.qualifier_runtime is not None
            ),
            "main_activated": main is not None,
            "is_complete": self.is_complete,
            "ready_match_ids": [
                row["match_id"]
                for row in self.ready_matches()
            ],
            "main": main,
        }
