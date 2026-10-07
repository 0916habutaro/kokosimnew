from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .models import AnnualCompetitionInput, CompetitionRun, MatchResolution, StageExecution
from .premain_runtime_forest import BlockForestRuntimeState
from .premain_runtime_fmt006 import Fmt006QualifierGroupRuntime
from .premain_runtime_composite import (
    COMPOSITE_QUALIFIER_MODELS,
    CompositeQualifierGroupRuntime,
    Fmt005GlobalQualifierRuntime,
)
from .repository import DataRepository
from .tournament_runtime import MainTournamentRuntimeState


@dataclass
class Fmt001QualifierGroupRuntime:
    group: dict
    eligible_school_ids: List[str]
    output_slots: int
    forest: BlockForestRuntimeState

    @property
    def format_model_id(self) -> str:
        return "FMT001"

    @property
    def is_complete(self) -> bool:
        return self.forest.is_complete

    def contains_match(self, match_id: str) -> bool:
        return any(
            match_id in runtime.matches
            for runtime in self.forest.block_runtimes
        )

    def ready_matches(self) -> list[dict]:
        return self.forest.ready_matches()

    def resolve_match(self, match_id: str) -> MatchResolution:
        return self.forest.resolve_match(match_id)

    def resolve_ready_round(self) -> list[MatchResolution]:
        return self.forest.resolve_ready_round()

    def resolve_all(self) -> list[str]:
        return self.forest.resolve_all()

    def output_school_ids(self) -> list[str]:
        return self.forest.winners()

    def to_matches(self):
        return self.forest.to_matches()

    def metadata(self) -> dict:
        return {
            "entrant_count": len(self.eligible_school_ids),
            "output_slots": self.output_slots,
            "representative_block_count": len(self.forest.blocks),
            "block_sizes": [len(block) for block in self.forest.blocks],
            "protected_seed_count": 0,
            "protected_seed_blocks": [],
        }


@dataclass
class QualifierMainRuntimeState:
    repo: DataRepository
    annual: AnnualCompetitionInput
    entrant_school_ids: List[str]
    direct_main_entry_school_ids: List[str]
    qualifier_stage: dict
    main_stage: dict
    qualifier_entrant_school_ids: List[str]
    qualifier_groups: List[object]
    warnings: List[str]
    pre_main_match_simulation_results: Dict[str, dict]
    main_runtime: MainTournamentRuntimeState | None = None
    main_entrant_school_ids: List[str] = field(default_factory=list)
    pre_main_match_resolver: object | None = field(default=None, repr=False)
    main_match_resolver: object | None = field(default=None, repr=False)

    @classmethod
    def create_fmt001(
        cls,
        *,
        repo: DataRepository,
        annual: AnnualCompetitionInput,
        entrants: Sequence[str],
        direct: Sequence[str],
        qualifier_entrants: Sequence[str],
        qualifier_stage: dict,
        main_stage: dict,
        warnings: Sequence[str],
        pre_main_match_resolver=None,
        main_match_resolver=None,
    ) -> "QualifierMainRuntimeState":
        assignment = repo.assignments_by_stage.get(qualifier_stage["stage_id"])
        if not assignment:
            raise KeyError(f"no format assignment for {qualifier_stage['stage_id']}")
        default_model = assignment["default_format_model_id"]
        if default_model != "FMT001":
            raise NotImplementedError(
                "Stage 13E-3A qualifier runtime supports FMT001 only"
            )

        entrant_set = set(qualifier_entrants)
        covered = set()
        sink: Dict[str, dict] = {}
        runtimes = []

        for group in repo.groups_by_stage.get(qualifier_stage["stage_id"], []):
            gid = group["stage_group_id"]
            override = repo.group_format.get(gid)
            model_id = (override or {}).get("format_model_id") or default_model
            if model_id != "FMT001":
                raise NotImplementedError(
                    f"{gid}: Stage 13E-3A does not yet support {model_id}"
                )

            supplied = annual.group_entrant_school_ids.get(gid)
            if supplied is not None:
                eligible = list(dict.fromkeys(supplied))
                outside = set(eligible) - entrant_set
                if outside:
                    raise ValueError(
                        f"{gid}: annual group entrants outside competition entrant set: "
                        f"{sorted(outside)}"
                    )
            else:
                eligible = sorted(
                    entrant_set & repo.group_school_ids(group, annual.year)
                )

            covered.update(eligible)
            if not eligible:
                continue

            slots = repo.param(
                qualifier_stage["stage_id"],
                "output_slots",
                gid,
                int(
                    group.get("advance_slots_to_next")
                    or group.get("qualifier_slots_generated")
                    or 0
                ),
            )
            if slots <= 0:
                raise ValueError(f"{group['group_name']}: FMT001 requires output_slots")

            forest = BlockForestRuntimeState.create(
                eligible,
                block_count=slots,
                competition_id=annual.competition_id,
                reference_year=annual.year,
                stage_id=qualifier_stage["stage_id"],
                stage_code=qualifier_stage["stage_code"],
                phase_code="BLOCK_KO",
                group_id=gid,
                group_name=group["group_name"],
                generation_seed=annual.rng_seed,
                match_resolver=pre_main_match_resolver,
                resolved_match_sink=sink,
            )
            runtimes.append(
                Fmt001QualifierGroupRuntime(
                    group=group,
                    eligible_school_ids=eligible,
                    output_slots=slots,
                    forest=forest,
                )
            )

        uncovered = sorted(entrant_set - covered)
        if uncovered:
            raise ValueError(
                f"qualifier entrants without a stage group: {uncovered[:10]}"
            )

        return cls(
            repo=repo,
            annual=annual,
            entrant_school_ids=list(entrants),
            direct_main_entry_school_ids=list(direct),
            qualifier_stage=dict(qualifier_stage),
            main_stage=dict(main_stage),
            qualifier_entrant_school_ids=list(qualifier_entrants),
            qualifier_groups=runtimes,
            warnings=list(warnings),
            pre_main_match_simulation_results=sink,
            pre_main_match_resolver=pre_main_match_resolver,
            main_match_resolver=main_match_resolver,
        )

    @classmethod
    def create_fmt006(
        cls,
        *,
        repo: DataRepository,
        annual: AnnualCompetitionInput,
        entrants: Sequence[str],
        direct: Sequence[str],
        qualifier_entrants: Sequence[str],
        qualifier_stage: dict,
        main_stage: dict,
        warnings: Sequence[str],
        pre_main_match_resolver=None,
        main_match_resolver=None,
    ) -> "QualifierMainRuntimeState":
        assignment = repo.assignments_by_stage.get(qualifier_stage["stage_id"])
        if not assignment:
            raise KeyError(f"no format assignment for {qualifier_stage['stage_id']}")
        default_model = assignment["default_format_model_id"]
        if default_model != "FMT006":
            raise NotImplementedError(
                "Stage 13E-3B-1 FMT006 runtime requires FMT006"
            )

        entrant_set = set(qualifier_entrants)
        covered = set()
        sink: Dict[str, dict] = {}
        runtimes = []

        for group in repo.groups_by_stage.get(qualifier_stage["stage_id"], []):
            gid = group["stage_group_id"]
            override = repo.group_format.get(gid)
            model_id = (override or {}).get("format_model_id") or default_model
            if model_id != "FMT006":
                raise NotImplementedError(
                    f"{gid}: Stage 13E-3B-1 does not yet support mixed {model_id}"
                )

            supplied = annual.group_entrant_school_ids.get(gid)
            if supplied is not None:
                eligible = list(dict.fromkeys(supplied))
                outside = set(eligible) - entrant_set
                if outside:
                    raise ValueError(
                        f"{gid}: annual group entrants outside competition entrant set: "
                        f"{sorted(outside)}"
                    )
            else:
                eligible = sorted(
                    entrant_set & repo.group_school_ids(group, annual.year)
                )

            covered.update(eligible)
            if not eligible:
                continue

            slots = repo.param(
                qualifier_stage["stage_id"],
                "output_slots",
                gid,
                int(
                    group.get("advance_slots_to_next")
                    or group.get("qualifier_slots_generated")
                    or 0
                ),
            )
            if slots is None or slots <= 0:
                raise ValueError(f"{group['group_name']}: FMT006 requires output_slots")

            supplied_pools = annual.group_pool_assignments.get(gid)
            runtime_group = dict(group)
            runtime_group["_runtime_supplied_pools"] = bool(supplied_pools)
            runtimes.append(
                Fmt006QualifierGroupRuntime.create(
                    group=runtime_group,
                    eligible_school_ids=eligible,
                    output_slots=slots,
                    competition_id=annual.competition_id,
                    reference_year=annual.year,
                    stage_id=qualifier_stage["stage_id"],
                    stage_code=qualifier_stage["stage_code"],
                    generation_seed=annual.rng_seed,
                    supplied_pools=supplied_pools,
                    match_resolver=pre_main_match_resolver,
                    resolved_match_sink=sink,
                )
            )

        uncovered = sorted(entrant_set - covered)
        if uncovered:
            raise ValueError(
                f"qualifier entrants without a stage group: {uncovered[:10]}"
            )

        return cls(
            repo=repo,
            annual=annual,
            entrant_school_ids=list(entrants),
            direct_main_entry_school_ids=list(direct),
            qualifier_stage=dict(qualifier_stage),
            main_stage=dict(main_stage),
            qualifier_entrant_school_ids=list(qualifier_entrants),
            qualifier_groups=runtimes,
            warnings=list(warnings),
            pre_main_match_simulation_results=sink,
            pre_main_match_resolver=pre_main_match_resolver,
            main_match_resolver=main_match_resolver,
        )

    @classmethod
    def create_composite(
        cls,
        *,
        repo: DataRepository,
        annual: AnnualCompetitionInput,
        entrants: Sequence[str],
        direct: Sequence[str],
        qualifier_entrants: Sequence[str],
        qualifier_stage: dict,
        main_stage: dict,
        warnings: Sequence[str],
        pre_main_match_resolver=None,
        main_match_resolver=None,
    ) -> "QualifierMainRuntimeState":
        assignment = repo.assignments_by_stage.get(qualifier_stage["stage_id"])
        if not assignment:
            raise KeyError(f"no format assignment for {qualifier_stage['stage_id']}")
        default_model = assignment["default_format_model_id"]
        if default_model not in COMPOSITE_QUALIFIER_MODELS:
            raise NotImplementedError(
                f"Stage 13E-3B-2 composite runtime does not support {default_model}"
            )

        entrant_set = set(qualifier_entrants)
        covered = set()
        sink: Dict[str, dict] = {}
        runtimes = []

        for group in repo.groups_by_stage.get(qualifier_stage["stage_id"], []):
            gid = group["stage_group_id"]
            override = repo.group_format.get(gid)
            model_id = (override or {}).get("format_model_id") or default_model
            if model_id not in COMPOSITE_QUALIFIER_MODELS:
                raise NotImplementedError(
                    f"{gid}: Stage 13E-3B-2 composite runtime "
                    f"does not support mixed {model_id}"
                )

            supplied = annual.group_entrant_school_ids.get(gid)
            if supplied is not None:
                eligible = list(dict.fromkeys(supplied))
                outside = set(eligible) - entrant_set
                if outside:
                    raise ValueError(
                        f"{gid}: annual group entrants outside competition entrant set: "
                        f"{sorted(outside)}"
                    )
            else:
                eligible = sorted(
                    entrant_set & repo.group_school_ids(group, annual.year)
                )

            covered.update(eligible)
            if not eligible:
                continue

            slots = repo.param(
                qualifier_stage["stage_id"],
                "output_slots",
                gid,
                int(
                    group.get("advance_slots_to_next")
                    or group.get("qualifier_slots_generated")
                    or 0
                ),
            )
            if slots is None or slots <= 0:
                raise ValueError(
                    f"{group['group_name']}: {model_id} requires output_slots"
                )

            runtimes.append(
                CompositeQualifierGroupRuntime.create(
                    repo=repo,
                    group=group,
                    eligible_school_ids=eligible,
                    output_slots=slots,
                    format_model_id=model_id,
                    competition_id=annual.competition_id,
                    reference_year=annual.year,
                    stage_id=qualifier_stage["stage_id"],
                    stage_code=qualifier_stage["stage_code"],
                    generation_seed=annual.rng_seed,
                    match_resolver=pre_main_match_resolver,
                    resolved_match_sink=sink,
                )
            )

        uncovered = sorted(entrant_set - covered)
        if uncovered:
            raise ValueError(
                f"qualifier entrants without a stage group: {uncovered[:10]}"
            )

        return cls(
            repo=repo,
            annual=annual,
            entrant_school_ids=list(entrants),
            direct_main_entry_school_ids=list(direct),
            qualifier_stage=dict(qualifier_stage),
            main_stage=dict(main_stage),
            qualifier_entrant_school_ids=list(qualifier_entrants),
            qualifier_groups=runtimes,
            warnings=list(warnings),
            pre_main_match_simulation_results=sink,
            pre_main_match_resolver=pre_main_match_resolver,
            main_match_resolver=main_match_resolver,
        )

    @classmethod
    def create_fmt005(
        cls,
        *,
        repo: DataRepository,
        annual: AnnualCompetitionInput,
        entrants: Sequence[str],
        direct: Sequence[str],
        qualifier_entrants: Sequence[str],
        qualifier_stage: dict,
        main_stage: dict,
        warnings: Sequence[str],
        pre_main_match_resolver=None,
        main_match_resolver=None,
    ) -> "QualifierMainRuntimeState":
        sink: Dict[str, dict] = {}
        runtime = Fmt005GlobalQualifierRuntime.create(
            repo=repo,
            entrant_school_ids=qualifier_entrants,
            competition_id=annual.competition_id,
            reference_year=annual.year,
            stage=qualifier_stage,
            generation_seed=annual.rng_seed,
            match_resolver=pre_main_match_resolver,
            resolved_match_sink=sink,
        )
        return cls(
            repo=repo,
            annual=annual,
            entrant_school_ids=list(entrants),
            direct_main_entry_school_ids=list(direct),
            qualifier_stage=dict(qualifier_stage),
            main_stage=dict(main_stage),
            qualifier_entrant_school_ids=list(qualifier_entrants),
            qualifier_groups=[runtime],
            warnings=list(warnings),
            pre_main_match_simulation_results=sink,
            pre_main_match_resolver=pre_main_match_resolver,
            main_match_resolver=main_match_resolver,
        )

    @classmethod
    def create(
        cls,
        *,
        repo: DataRepository,
        annual: AnnualCompetitionInput,
        entrants: Sequence[str],
        direct: Sequence[str],
        qualifier_entrants: Sequence[str],
        qualifier_stage: dict,
        main_stage: dict,
        warnings: Sequence[str],
        pre_main_match_resolver=None,
        main_match_resolver=None,
    ) -> "QualifierMainRuntimeState":
        assignment = repo.assignments_by_stage.get(qualifier_stage["stage_id"])
        if not assignment:
            raise KeyError(f"no format assignment for {qualifier_stage['stage_id']}")
        model_id = assignment["default_format_model_id"]
        factory = {
            "FMT001": cls.create_fmt001,
            "FMT005": cls.create_fmt005,
            "FMT006": cls.create_fmt006,
        }.get(model_id)
        if factory is None and model_id in COMPOSITE_QUALIFIER_MODELS:
            factory = cls.create_composite
        if factory is None:
            raise NotImplementedError(
                f"Stage 13E-3B-2 qualifier runtime does not yet support {model_id}"
            )
        return factory(
            repo=repo,
            annual=annual,
            entrants=entrants,
            direct=direct,
            qualifier_entrants=qualifier_entrants,
            qualifier_stage=qualifier_stage,
            main_stage=main_stage,
            warnings=warnings,
            pre_main_match_resolver=pre_main_match_resolver,
            main_match_resolver=main_match_resolver,
        )

    @property
    def qualifier_complete(self) -> bool:
        return all(group.is_complete for group in self.qualifier_groups)

    @property
    def is_complete(self) -> bool:
        return self.main_runtime is not None and self.main_runtime.is_complete

    def ready_matches(self) -> list[dict]:
        if not self.qualifier_complete:
            return [
                row
                for group in self.qualifier_groups
                for row in group.ready_matches()
            ]
        self._activate_main()
        return self.main_runtime.ready_matches()

    def resolve_match(self, match_id: str) -> MatchResolution:
        if not self.qualifier_complete:
            for group in self.qualifier_groups:
                if group.contains_match(match_id):
                    result = group.resolve_match(match_id)
                    if self.qualifier_complete:
                        self._activate_main()
                    return result
            raise KeyError(f"unknown qualifier match_id: {match_id}")
        self._activate_main()
        return self.main_runtime.resolve_match(match_id)

    def resolve_ready_round(self) -> list[MatchResolution]:
        if not self.qualifier_complete:
            results = []
            for group in self.qualifier_groups:
                results.extend(group.resolve_ready_round())
            if self.qualifier_complete:
                self._activate_main()
            return results
        self._activate_main()
        return self.main_runtime.resolve_ready_round()

    def resolve_all(self) -> CompetitionRun:
        for group in self.qualifier_groups:
            group.resolve_all()
        self._activate_main()
        self.main_runtime.resolve_all()
        return self.to_competition_run()

    def qualifier_output_school_ids(self) -> list[str]:
        if not self.qualifier_complete:
            raise ValueError("qualifier output unavailable before completion")
        outputs = []
        for group in self.qualifier_groups:
            outputs.extend(group.output_school_ids())
        return list(dict.fromkeys(outputs))

    def _activate_main(self) -> None:
        if self.main_runtime is not None:
            return
        if not self.qualifier_complete:
            raise ValueError("MAIN cannot activate before qualifier completion")

        outputs = self.qualifier_output_school_ids()
        main_entrants = list(
            dict.fromkeys(outputs + self.direct_main_entry_school_ids)
        )
        if not set(main_entrants).issubset(set(self.entrant_school_ids)):
            raise AssertionError("MAIN contains a team outside annual entrant set")

        observed = self.repo.param(
            self.qualifier_stage["stage_id"], "observed_main_total"
        )
        if observed is not None and len(main_entrants) != observed:
            self.warnings.append(
                f"2026 observed MAIN total={observed}, current run={len(main_entrants)}"
            )

        observed_direct = self.repo.param(
            self.qualifier_stage["stage_id"], "observed_direct_access_slots"
        )
        if (
            observed_direct is not None
            and len(self.direct_main_entry_school_ids) != observed_direct
        ):
            self.warnings.append(
                f"2026 observed direct access={observed_direct}, "
                f"current input={len(self.direct_main_entry_school_ids)}"
            )

        expected = self.main_stage.get("team_count", "")
        if self.annual.year == 2026 and expected:
            try:
                expected_n = int(expected)
            except ValueError:
                expected_n = 0
            if expected_n and expected_n != len(main_entrants):
                self.warnings.append(
                    f"2026 MAIN team_count={expected_n}, "
                    f"current input/resolution={len(main_entrants)}"
                )

        self.main_entrant_school_ids = main_entrants
        self.main_runtime = MainTournamentRuntimeState.create(
            competition_id=self.annual.competition_id,
            reference_year=self.annual.year,
            generation_seed=self.annual.rng_seed,
            stage_id=self.main_stage["stage_id"],
            entrants=main_entrants,
            seed_assignments=(),
            annual_seed_order=self.annual.main_seed_school_ids,
            slot_override=(
                self.annual.main_bracket_slots
                if self.annual.main_bracket_slots
                else None
            ),
            winner_overrides=self.annual.main_match_winner_overrides,
            match_resolver=self.main_match_resolver,
        )

    def qualifier_stage_execution(self) -> StageExecution:
        if not self.qualifier_complete:
            raise ValueError(
                "qualifier StageExecution unavailable before completion"
            )
        default_model = self.repo.assignments_by_stage[
            self.qualifier_stage["stage_id"]
        ]["default_format_model_id"]
        if default_model == "FMT005":
            return self.qualifier_groups[0].stage_execution()
        outputs = []
        matches = []
        stage_groups = self.repo.groups_by_stage.get(
            self.qualifier_stage["stage_id"], []
        )
        group_outputs = {
            group["stage_group_id"]: []
            for group in stage_groups
        }
        group_models = {}
        for group in stage_groups:
            gid = group["stage_group_id"]
            override = self.repo.group_format.get(gid)
            group_models[gid] = (
                (override or {}).get("format_model_id")
                or default_model
            )
        group_metadata = {}

        for runtime in self.qualifier_groups:
            gid = runtime.group["stage_group_id"]
            group_output = runtime.output_school_ids()
            outputs.extend(group_output)
            group_outputs[gid] = group_output
            group_models[gid] = runtime.format_model_id
            group_metadata[gid] = runtime.metadata()
            matches.extend(runtime.to_matches())

        return StageExecution(
            stage_id=self.qualifier_stage["stage_id"],
            stage_code=self.qualifier_stage["stage_code"],
            format_model_id=self.repo.assignments_by_stage[
                self.qualifier_stage["stage_id"]
            ]["default_format_model_id"],
            entrant_school_ids=list(self.qualifier_entrant_school_ids),
            output_school_ids=list(dict.fromkeys(outputs)),
            matches=matches,
            metadata={
                "group_count": len(stage_groups),
                "group_outputs": group_outputs,
                "group_models": group_models,
                "group_metadata": group_metadata,
                "protected_seed_count": 0,
                "protected_seed_blocks": [],
            },
        )

    def to_competition_run(self) -> CompetitionRun:
        if not self.is_complete:
            raise ValueError("competition run unavailable before completion")
        results = dict(self.pre_main_match_simulation_results)
        results.update(self.main_runtime.match_simulation_results)
        return CompetitionRun(
            competition_id=self.annual.competition_id,
            year=self.annual.year,
            rng_seed=self.annual.rng_seed,
            entrant_school_ids=list(self.entrant_school_ids),
            seed_assignments=[],
            stage_executions=[
                self.qualifier_stage_execution(),
                self.main_runtime.stage_execution(),
            ],
            main_entrant_school_ids=list(self.main_entrant_school_ids),
            warnings=list(self.warnings),
            outcome=self.main_runtime._outcome(),
            match_simulation_results=results,
        )

    def public_snapshot(self) -> dict:
        return {
            "competition_id": self.annual.competition_id,
            "year": self.annual.year,
            "qualifier_complete": self.qualifier_complete,
            "main_activated": self.main_runtime is not None,
            "is_complete": self.is_complete,
            "main_entrant_school_ids": (
                list(self.main_entrant_school_ids)
                if self.main_runtime is not None
                else []
            ),
            "qualifier_ready_match_ids": [
                row["match_id"]
                for group in self.qualifier_groups
                for row in group.ready_matches()
            ],
            "main": (
                self.main_runtime.public_snapshot()
                if self.main_runtime is not None
                else None
            ),
        }
