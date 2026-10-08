from __future__ import annotations

from collections import Counter
from typing import Dict, List, Sequence, Tuple

from .brackets import (
    balanced_partition,
    random_winner_resolver,
    run_block_winner_forest,
    run_head_to_head,
    run_round_robin,
    run_single_elimination_ranking,
    run_single_round_gate,
)
from .models import AnnualCompetitionInput, CompetitionRun, Match, SeedAssignment, StageExecution
from .main_tournament import run_main_single_elimination
from .randomness import shuffled
from .repository import DataRepository


class TournamentEngine:
    """CSV-driven Phase 2 tournament engine.

    Stage 12C-4 dispatches all Stage 12B pre-MAIN format models and then executes the
    prefectural MAIN as a fixed power-of-two single-elimination bracket. Competition-
    specific facts remain in CSV/annual input; exact annual draw slots and winners can
    be supplied as overrides without hardcoding school names in the engine.
    """

    SUPPORTED_FORMAT_MODELS = {f"FMT{i:03d}" for i in range(1, 27)}

    def __init__(
        self,
        repo: DataRepository,
        *,
        main_match_resolver=None,
        pre_main_match_resolver=None,
    ):
        self.repo = repo
        self.main_match_resolver = main_match_resolver
        self.pre_main_match_resolver = pre_main_match_resolver
        self._active_pre_main_results: dict[str, dict] = {}

    def prepare_main_runtime(
        self,
        annual: AnnualCompetitionInput,
    ):
        """Prepare a resumable MAIN bracket without resolving any real match.

        Stage 13E-2 currently supports competitions whose execution graph begins
        directly at MAIN. Pre-MAIN resumable execution is a later extension.
        """
        from .tournament_runtime import MainTournamentRuntimeState

        return MainTournamentRuntimeState.from_direct_main(
            self.repo,
            annual,
            match_resolver=self.main_match_resolver,
        )

    def prepare_qualifier_main_runtime(
        self,
        annual: AnnualCompetitionInput,
    ):
        """Prepare an incremental qualifier -> MAIN competition.

        Stage 13E-3B-2 supports FMT001/FMT005/FMT006 and the composite
        qualifier models FMT002-004, FMT007-008, FMT010-017 and FMT025.
        Seed-event graphs use prepare_seeded_competition_runtime().
        """
        from .premain_competition_runtime import QualifierMainRuntimeState
        from .premain_runtime_composite import COMPOSITE_QUALIFIER_MODELS

        entrants = self._validate_entrants(annual)
        direct = self._validate_direct_entries(annual, entrants)
        stage_by_code = {
            row["stage_code"]: row
            for row in self.repo.stages(annual.competition_id)
        }
        qualifier_codes = [
            code
            for code in (
                "BRANCH_QUALIFIER",
                "PRELIMINARY_QUALIFIER",
            )
            if code in stage_by_code
        ]
        if len(qualifier_codes) != 1 or set(stage_by_code) != {
            qualifier_codes[0],
            "MAIN",
        }:
            raise ValueError(
                "prepare_qualifier_main_runtime requires exactly "
                "one qualifier stage followed by MAIN"
            )

        qualifier_stage = stage_by_code[qualifier_codes[0]]
        assignment = self.repo.assignments_by_stage.get(
            qualifier_stage["stage_id"]
        )
        supported_models = {
            "FMT001",
            "FMT005",
            "FMT006",
        } | COMPOSITE_QUALIFIER_MODELS
        if (
            not assignment
            or assignment["default_format_model_id"] not in supported_models
        ):
            model_id = (
                assignment["default_format_model_id"]
                if assignment
                else "missing"
            )
            raise NotImplementedError(
                f"Stage 13E-3B-2 competition runtime does not yet support {model_id}"
            )

        qualifier_entrants, warnings = (
            self._qualifier_entrants_after_access_rules(
                annual,
                entrants,
                direct,
            )
        )
        return QualifierMainRuntimeState.create(
            repo=self.repo,
            annual=annual,
            entrants=entrants,
            direct=direct,
            qualifier_entrants=qualifier_entrants,
            qualifier_stage=qualifier_stage,
            main_stage=stage_by_code["MAIN"],
            warnings=warnings,
            pre_main_match_resolver=self.pre_main_match_resolver,
            main_match_resolver=self.main_match_resolver,
        )

    def prepare_seeded_competition_runtime(
        self,
        annual: AnnualCompetitionInput,
    ):
        """Prepare SEED_EVENT based competition graphs lazily.

        Stage 13E-3B-3 covers:
        - SEED_EVENT -> MAIN
        - SEED_EVENT -> FIRST_TOURNAMENT(FMT026) -> MAIN
        - SEED_EVENT -> qualifier -> MAIN
        """
        from .premain_graph_runtime import (
            SeededCompetitionRuntimeState,
        )

        entrants = self._validate_entrants(annual)
        direct = self._validate_direct_entries(
            annual,
            entrants,
        )
        stage_by_code = {
            row["stage_code"]: row
            for row in self.repo.stages(
                annual.competition_id
            )
        }
        if (
            "SEED_EVENT" not in stage_by_code
            or "MAIN" not in stage_by_code
        ):
            raise ValueError(
                "prepare_seeded_competition_runtime requires "
                "SEED_EVENT and MAIN"
            )

        allowed = {
            "SEED_EVENT",
            "MAIN",
            "FIRST_TOURNAMENT",
            "BRANCH_QUALIFIER",
            "PRELIMINARY_QUALIFIER",
        }
        unexpected = set(stage_by_code) - allowed
        if unexpected:
            raise ValueError(
                "unsupported seeded runtime stages: "
                f"{sorted(unexpected)}"
            )
        qualifier_codes = [
            code
            for code in (
                "BRANCH_QUALIFIER",
                "PRELIMINARY_QUALIFIER",
            )
            if code in stage_by_code
        ]
        if len(qualifier_codes) > 1:
            raise ValueError(
                "seeded runtime supports at most one qualifier stage"
            )
        if (
            "FIRST_TOURNAMENT" in stage_by_code
            and qualifier_codes
        ):
            raise ValueError(
                "seeded runtime cannot combine FIRST_TOURNAMENT "
                "and qualifier stage"
            )

        qualifier_entrants = []
        qualifier_warnings = []
        if qualifier_codes:
            qualifier_entrants, qualifier_warnings = (
                self._qualifier_entrants_after_access_rules(
                    annual,
                    entrants,
                    direct,
                )
            )

        return SeededCompetitionRuntimeState.create(
            repo=self.repo,
            annual=annual,
            entrants=entrants,
            direct=direct,
            stage_by_code=stage_by_code,
            qualifier_entrants=qualifier_entrants,
            qualifier_warnings=qualifier_warnings,
            pre_main_match_resolver=(
                self.pre_main_match_resolver
            ),
            main_match_resolver=self.main_match_resolver,
        )

    def prepare_competition_runtime(
        self,
        annual: AnnualCompetitionInput,
    ):
        """Dispatch the resumable runtime for the competition graph."""
        stage_codes = {
            row["stage_code"]
            for row in self.repo.stages(
                annual.competition_id
            )
        }
        if stage_codes == {"MAIN"}:
            return self.prepare_main_runtime(annual)
        if "SEED_EVENT" in stage_codes:
            return self.prepare_seeded_competition_runtime(
                annual
            )
        if "MAIN" in stage_codes and (
            "BRANCH_QUALIFIER" in stage_codes
            or "PRELIMINARY_QUALIFIER" in stage_codes
        ):
            return self.prepare_qualifier_main_runtime(
                annual
            )
        raise NotImplementedError(
            "Stage 13E runtime does not support "
            f"competition graph {sorted(stage_codes)}"
        )

    def _pre_main_resolution_kwargs(self, annual: AnnualCompetitionInput) -> dict:
        if self.pre_main_match_resolver is None:
            return {}
        return {
            "match_resolver": self.pre_main_match_resolver,
            "resolved_match_sink": self._active_pre_main_results,
            "reference_year": annual.year,
        }

    def run(self, annual: AnnualCompetitionInput) -> CompetitionRun:
        self._active_pre_main_results = {}
        entrants = self._validate_entrants(annual)
        direct = self._validate_direct_entries(annual, entrants)
        stage_by_code = {r["stage_code"]: r for r in self.repo.stages(annual.competition_id)}
        winner_resolver = random_winner_resolver(annual.rng_seed)
        warnings: List[str] = []

        # Gifu-style seed event -> one-round gate -> MAIN.
        if {"SEED_EVENT", "FIRST_TOURNAMENT", "MAIN"}.issubset(stage_by_code):
            base = self._run_seed_gate_main(annual, entrants, direct, stage_by_code, winner_resolver)
            return self._complete_main(annual, base, stage_by_code["MAIN"], winner_resolver)

        # Seed event -> non-geographic/geographic qualifier -> MAIN.
        # The seed event determines protected positions for the qualifier draw; only
        # qualifier survivors advance to MAIN.  Seed metadata whose destination is the
        # qualifier is intentionally not carried into the MAIN bracket.
        seed_qualifier_code = next(
            (code for code in ("BRANCH_QUALIFIER", "PRELIMINARY_QUALIFIER") if code in stage_by_code),
            None,
        )
        if "SEED_EVENT" in stage_by_code and seed_qualifier_code and "MAIN" in stage_by_code:
            seed_assignments, seed_execution = self._run_seed_event(
                annual=annual,
                entrants=entrants,
                stage=stage_by_code["SEED_EVENT"],
                winner_resolver=winner_resolver,
            )
            stage = stage_by_code[seed_qualifier_code]
            stage_entrants, bypass_warnings = self._qualifier_entrants_after_access_rules(
                annual, entrants, direct
            )
            warnings.extend(bypass_warnings)
            qualifier_execution = self._run_qualifier_stage(
                annual=annual,
                entrants=stage_entrants,
                stage=stage,
                winner_resolver=winner_resolver,
                protected_school_ids=[a.school_id for a in seed_assignments],
            )
            qualifier_execution.metadata["seed_context_school_ids"] = [
                a.school_id for a in seed_assignments
            ]
            qualifier_execution.metadata["seed_context_count"] = len(seed_assignments)
            main_entrants = self._dedup(qualifier_execution.output_school_ids + direct)
            if not set(main_entrants).issubset(set(entrants)):
                raise AssertionError("MAIN contains a team outside annual entrant set")
            warnings.extend(self._observed_main_count_warnings(stage, main_entrants, direct))
            base = CompetitionRun(
                competition_id=annual.competition_id,
                year=annual.year,
                rng_seed=annual.rng_seed,
                entrant_school_ids=list(entrants),
                seed_assignments=seed_assignments,
                stage_executions=[seed_execution, qualifier_execution],
                main_entrant_school_ids=main_entrants,
                warnings=warnings,
                match_simulation_results=dict(self._active_pre_main_results),
            )
            return self._complete_main(annual, base, stage_by_code["MAIN"], winner_resolver)

        # Seed-only event. Every registered tournament entrant continues to MAIN; the
        # event only overlays seed metadata (Aomori autumn and similar models).
        if {"SEED_EVENT", "MAIN"}.issubset(stage_by_code):
            seed_assignments, seed_execution = self._run_seed_event(
                annual=annual,
                entrants=entrants,
                stage=stage_by_code["SEED_EVENT"],
                winner_resolver=winner_resolver,
            )
            base = CompetitionRun(
                competition_id=annual.competition_id,
                year=annual.year,
                rng_seed=annual.rng_seed,
                entrant_school_ids=list(entrants),
                seed_assignments=seed_assignments,
                stage_executions=[seed_execution],
                main_entrant_school_ids=list(entrants),
                warnings=warnings,
                match_simulation_results=dict(self._active_pre_main_results),
            )
            return self._complete_main(annual, base, stage_by_code["MAIN"], winner_resolver)

        # Qualifier -> MAIN.  BRANCH_QUALIFIER covers geographic district/branch
        # systems; PRELIMINARY_QUALIFIER covers non-geographic annual block draws such
        # as Tokyo autumn.  Both share the same quota-group execution contract.
        qualifier_code = next((code for code in ("BRANCH_QUALIFIER", "PRELIMINARY_QUALIFIER") if code in stage_by_code), None)
        if qualifier_code and "MAIN" in stage_by_code:
            stage = stage_by_code[qualifier_code]
            stage_entrants, bypass_warnings = self._qualifier_entrants_after_access_rules(
                annual, entrants, direct
            )
            warnings.extend(bypass_warnings)
            qualifier_execution = self._run_qualifier_stage(
                annual=annual,
                entrants=stage_entrants,
                stage=stage,
                winner_resolver=winner_resolver,
            )
            main_entrants = self._dedup(qualifier_execution.output_school_ids + direct)
            if not set(main_entrants).issubset(set(entrants)):
                raise AssertionError("MAIN contains a team outside annual entrant set")
            warnings.extend(self._observed_main_count_warnings(stage, main_entrants, direct))
            base = CompetitionRun(
                competition_id=annual.competition_id,
                year=annual.year,
                rng_seed=annual.rng_seed,
                entrant_school_ids=list(entrants),
                seed_assignments=[],
                stage_executions=[qualifier_execution],
                main_entrant_school_ids=main_entrants,
                warnings=warnings,
                match_simulation_results=dict(self._active_pre_main_results),
            )
            return self._complete_main(annual, base, stage_by_code["MAIN"], winner_resolver)

        # Prefectures whose spring/autumn tournament begins directly at MAIN. The annual
        # entrant list is authoritative; federation membership alone never implies entry.
        if "MAIN" in stage_by_code:
            if direct:
                warnings.append("direct_main_entry_school_ids has no bypass effect because this competition begins at MAIN")
            base = CompetitionRun(
                competition_id=annual.competition_id,
                year=annual.year,
                rng_seed=annual.rng_seed,
                entrant_school_ids=list(entrants),
                seed_assignments=[],
                stage_executions=[],
                main_entrant_school_ids=list(entrants),
                warnings=warnings,
                match_simulation_results=dict(self._active_pre_main_results),
            )
            return self._complete_main(annual, base, stage_by_code["MAIN"], winner_resolver)

        raise NotImplementedError(
            f"Stage 12C-4 has no execution graph for {annual.competition_id}: {sorted(stage_by_code)}"
        )

    def _complete_main(self, annual, base_run, main_stage, winner_resolver) -> CompetitionRun:
        if self._active_pre_main_results:
            base_run.match_simulation_results.update(self._active_pre_main_results)
        if main_stage.get("format_type") not in {"", "single_elimination"}:
            raise NotImplementedError(
                f"MAIN format {main_stage.get('format_type')} is not implemented for {annual.competition_id}"
            )
        main_entrants = list(base_run.main_entrant_school_ids)
        annual_seeds = self._dedup(annual.main_seed_school_ids)
        outside = set(annual_seeds) - set(main_entrants)
        if outside:
            raise ValueError(f"MAIN seeds outside MAIN entrant set: {sorted(outside)}")

        exact_slots = list(annual.main_bracket_slots) if annual.main_bracket_slots else None
        execution, outcome = run_main_single_elimination(
            main_entrants,
            competition_id=annual.competition_id,
            stage_id=main_stage["stage_id"],
            base_seed=annual.rng_seed,
            winner_resolver=winner_resolver,
            seed_assignments=[
                a for a in base_run.seed_assignments
                if a.destination_stage in {"", "MAIN", "prefectural_main_draw", "second_tournament"}
            ],
            annual_seed_order=annual_seeds,
            slot_override=exact_slots,
            winner_overrides=annual.main_match_winner_overrides,
            match_resolver=self.main_match_resolver,
            resolved_match_sink=base_run.match_simulation_results,
            reference_year=annual.year,
        )
        base_run.stage_executions.append(execution)
        base_run.outcome = outcome

        expected = main_stage.get("team_count", "")
        if annual.year == 2026 and expected:
            try:
                expected_n = int(expected)
            except ValueError:
                expected_n = 0
            if expected_n and expected_n != len(main_entrants):
                base_run.warnings.append(
                    f"2026 MAIN team_count={expected_n}, current input/resolution={len(main_entrants)}"
                )
        return base_run

    # ------------------------------------------------------------------
    # Validation and access-rule boundary
    # ------------------------------------------------------------------
    def _validate_entrants(self, annual: AnnualCompetitionInput) -> List[str]:
        if not annual.entrant_school_ids:
            raise ValueError("entrant_school_ids is required; membership does not imply tournament participation")
        entrants: List[str] = []
        seen = set()
        comp = self.repo.competition(annual.competition_id)
        for school_id in annual.entrant_school_ids:
            if school_id in seen:
                continue
            if school_id not in self.repo.schools:
                raise ValueError(f"unknown school_id: {school_id}")
            if comp.get("prefecture_code") and self.repo.schools[school_id].get("prefecture_code") != comp["prefecture_code"]:
                raise ValueError(f"entrant {school_id} is outside destination prefecture")
            seen.add(school_id)
            entrants.append(school_id)
        return entrants

    def _validate_direct_entries(self, annual: AnnualCompetitionInput, entrants: Sequence[str]) -> List[str]:
        entrant_set = set(entrants)
        direct = self._dedup(annual.direct_main_entry_school_ids)
        unknown = set(direct) - entrant_set
        if unknown:
            raise ValueError(f"direct MAIN entries must also be in entrant_school_ids: {sorted(unknown)}")
        return direct

    def _eligible_group_entrants(self, annual: AnnualCompetitionInput, group: dict, entrant_set: set[str]) -> List[str]:
        gid = group["stage_group_id"]
        supplied = annual.group_entrant_school_ids.get(gid)
        if supplied is not None:
            ordered = self._dedup(supplied)
            outside = set(ordered) - entrant_set
            if outside:
                raise ValueError(f"{gid}: annual group entrants outside competition entrant set: {sorted(outside)}")
            return ordered
        return sorted(entrant_set & self.repo.group_school_ids(group, annual.year))

    def _qualifier_entrants_after_access_rules(
        self, annual: AnnualCompetitionInput, entrants: Sequence[str], direct: Sequence[str]
    ) -> Tuple[List[str], List[str]]:
        direct_set = set(direct)
        rules = self.repo.access_rules(annual.competition_id)
        warnings: List[str] = []
        if direct and not rules:
            raise ValueError("direct_main_entry_school_ids supplied but competition has no access rule")

        excluded = set()
        allowed_without_effect = False
        for rule in rules:
            policy = rule.get("bypassed_stage_participation_policy", "")
            if policy == "excluded_from_bypassed_stage":
                excluded |= direct_set
            elif policy == "allowed_without_qualification_effect" and direct:
                # Exact official participation can be replayed later with annual draw/result
                # data. For simulation, do not let a pre-qualified team consume a quota.
                excluded |= direct_set
                allowed_without_effect = True
        if allowed_without_effect:
            warnings.append(
                "direct-entry team is officially allowed to play the bypassed qualifier; "
                "Stage 12C-3 simulation excludes it from quota competition so it cannot consume a qualifier slot"
            )

        expected = sum(int(r.get("observed_2026_count") or 0) for r in rules if r.get("observed_2026_count"))
        if annual.year == 2026 and rules and direct and expected and len(direct_set) != expected:
            warnings.append(f"2026 access-rule direct entries observed={expected}, current input={len(direct_set)}")
        return [x for x in entrants if x not in excluded], warnings

    # ------------------------------------------------------------------
    # Gifu path retained from Stage 12C-1
    # ------------------------------------------------------------------
    def _run_seed_gate_main(self, annual, entrants, direct, stage_by_code, winner_resolver) -> CompetitionRun:
        if direct:
            raise NotImplementedError("seed+gate graph with direct MAIN access is not yet required by current data")
        seed_stage = stage_by_code["SEED_EVENT"]
        gate_stage = stage_by_code["FIRST_TOURNAMENT"]
        seed_assignments, seed_execution = self._run_seed_event(
            annual=annual, entrants=entrants, stage=seed_stage, winner_resolver=winner_resolver
        )
        seeded_ids = {x.school_id for x in seed_assignments}
        nonseed = [x for x in entrants if x not in seeded_ids]
        gate_assignment = self.repo.assignments_by_stage.get(gate_stage["stage_id"])
        if not gate_assignment or gate_assignment["default_format_model_id"] != "FMT026":
            raise NotImplementedError("gate handler requires FMT026")
        gate_winners, gate_matches = run_single_round_gate(
            nonseed,
            competition_id=annual.competition_id,
            stage_id=gate_stage["stage_id"],
            stage_code=gate_stage["stage_code"],
            phase_code="GATE_ROUND",
            base_seed=annual.rng_seed,
            winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
        )
        gate_execution = StageExecution(
            stage_id=gate_stage["stage_id"],
            stage_code=gate_stage["stage_code"],
            format_model_id="FMT026",
            entrant_school_ids=list(nonseed),
            output_school_ids=list(gate_winners),
            matches=gate_matches,
            metadata={
                "seed_bypass_count": len(seeded_ids),
                "nonseed_count": len(nonseed),
                "gate_winner_count": len(gate_winners),
                "bye_count": sum(1 for m in gate_matches if m.is_bye),
            },
        )
        main_entrants = [x.school_id for x in seed_assignments] + list(gate_winners)
        if len(main_entrants) != len(set(main_entrants)):
            raise AssertionError("duplicate team entered MAIN")
        warnings: List[str] = []
        expected = {
            "nonseed": self.repo.param(gate_stage["stage_id"], "observed_nonseed_gate_teams"),
            "winners": self.repo.param(gate_stage["stage_id"], "observed_gate_winner_slots"),
            "seed": self.repo.param(gate_stage["stage_id"], "seed_bypass_slots"),
            "main": self.repo.param(gate_stage["stage_id"], "observed_second_stage_total"),
        }
        observed = {
            "nonseed": len(nonseed), "winners": len(gate_winners),
            "seed": len(seeded_ids), "main": len(main_entrants),
        }
        for key, exp in expected.items():
            if exp is not None and observed[key] != exp:
                warnings.append(f"2026 observed {key}={exp}, current run={observed[key]}")
        return CompetitionRun(
            competition_id=annual.competition_id,
            year=annual.year,
            rng_seed=annual.rng_seed,
            entrant_school_ids=list(entrants),
            seed_assignments=seed_assignments,
            stage_executions=[seed_execution, gate_execution],
            main_entrant_school_ids=main_entrants,
            warnings=warnings,
            match_simulation_results=dict(self._active_pre_main_results),
        )

    # ------------------------------------------------------------------
    # Qualifier stage dispatch (FMT001 / FMT005 / FMT006)
    # ------------------------------------------------------------------
    def _run_qualifier_stage(
        self, annual, entrants, stage, winner_resolver, protected_school_ids: Sequence[str] = ()
    ) -> StageExecution:
        assignment = self.repo.assignments_by_stage.get(stage["stage_id"])
        if not assignment:
            raise KeyError(f"no format assignment for {stage['stage_id']}")
        default_model = assignment["default_format_model_id"]
        if default_model not in self.SUPPORTED_FORMAT_MODELS:
            raise NotImplementedError(default_model)

        if default_model == "FMT005":
            return self._run_fmt005_global_repechage(annual, entrants, stage, winner_resolver)

        groups = self.repo.groups_by_stage.get(stage["stage_id"], [])
        entrant_set = set(entrants)
        outputs: List[str] = []
        matches: List[Match] = []
        group_outputs: Dict[str, List[str]] = {}
        group_models: Dict[str, str] = {}
        group_metadata: Dict[str, dict] = {}
        covered = set()
        for group in groups:
            group_id = group["stage_group_id"]
            override = self.repo.group_format.get(group_id)
            model_id = (override or {}).get("format_model_id") or default_model
            group_models[group_id] = model_id
            eligible = self._eligible_group_entrants(annual, group, entrant_set)
            covered.update(eligible)
            if not eligible:
                group_outputs[group_id] = []
                continue
            if model_id == "FMT001":
                out, ms, meta = self._run_fmt001_group(
                    annual, stage, group, eligible, winner_resolver,
                    protected_school_ids=protected_school_ids,
                )
            elif model_id == "FMT006":
                out, ms, meta = self._run_fmt006_group(annual, stage, group, eligible, winner_resolver)
            elif model_id in {
                "FMT002", "FMT003", "FMT004", "FMT007", "FMT008",
                "FMT010", "FMT011", "FMT012", "FMT013", "FMT014",
                "FMT015", "FMT016", "FMT017", "FMT025",
            }:
                out, ms, meta = self._run_generic_qualifier_group(
                    model_id, annual, stage, group, eligible, winner_resolver
                )
            else:
                raise NotImplementedError(f"qualifier handler does not support {model_id}")
            group_outputs[group_id] = out
            group_metadata[group_id] = meta
            outputs.extend(out)
            matches.extend(ms)
        uncovered = sorted(entrant_set - covered)
        if uncovered:
            raise ValueError(f"qualifier entrants without a stage group: {uncovered[:10]}")
        outputs = self._dedup(outputs)
        return StageExecution(
            stage_id=stage["stage_id"],
            stage_code=stage["stage_code"],
            format_model_id=default_model,
            entrant_school_ids=list(entrants),
            output_school_ids=outputs,
            matches=matches,
            metadata={
                "group_count": len(groups),
                "group_outputs": group_outputs,
                "group_models": group_models,
                "group_metadata": group_metadata,
                "protected_seed_count": sum(
                    int(meta.get("protected_seed_count") or 0)
                    for meta in group_metadata.values()
                ),
                "protected_seed_blocks": sorted({
                    block
                    for meta in group_metadata.values()
                    for block in meta.get("protected_seed_blocks", [])
                }),
            },
        )

    def _run_fmt001_group(
        self, annual, stage, group, eligible, winner_resolver,
        protected_school_ids: Sequence[str] = (),
    ):
        slots = self.repo.param(
            stage["stage_id"], "output_slots", group["stage_group_id"],
            int(group.get("advance_slots_to_next") or group.get("qualifier_slots_generated") or 0),
        )
        if slots <= 0:
            raise ValueError(f"{group['group_name']}: FMT001 requires output_slots")

        eligible_set = set(eligible)
        protected = [
            sid for sid in self._dedup(protected_school_ids)
            if sid in eligible_set
        ]
        if len(protected) > slots:
            raise ValueError(
                f"{group['group_name']}: protected seeds={len(protected)} exceed output blocks={slots}"
            )

        # Most FMT001 qualifiers use the legacy deterministic forest unchanged.  When
        # a seed event explicitly targets this qualifier (Ehime autumn), spread the
        # protected teams one per representative block before filling the remaining
        # positions.  This preserves the seed event's real purpose without carrying
        # those seeds into the subsequent MAIN tournament.
        if not protected:
            winners, matches, blocks = run_block_winner_forest(
                eligible,
                block_count=slots,
                competition_id=annual.competition_id,
                stage_id=stage["stage_id"],
                stage_code=stage["stage_code"],
                phase_code="BLOCK_KO",
                group_id=group["stage_group_id"],
                group_name=group["group_name"],
                base_seed=annual.rng_seed,
                winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
            )
            return winners, matches, {
                "entrant_count": len(eligible), "output_slots": slots,
                "representative_block_count": len(blocks),
                "block_sizes": [len(x) for x in blocks],
                "protected_seed_count": 0,
                "protected_seed_blocks": [],
            }

        q, r = divmod(len(eligible), slots)
        sizes = [q + (1 if i < r else 0) for i in range(slots)]
        blocks: List[List[str]] = [[] for _ in range(slots)]
        block_order = shuffled(
            range(slots), annual.rng_seed,
            f"{annual.competition_id}:{stage['stage_id']}:{group['stage_group_id']}:seed_block_order",
        )
        seed_order = shuffled(
            protected, annual.rng_seed,
            f"{annual.competition_id}:{stage['stage_id']}:{group['stage_group_id']}:seed_order",
        )
        protected_blocks: List[int] = []
        for block_index, school_id in zip(block_order, seed_order):
            blocks[block_index].append(school_id)
            protected_blocks.append(block_index + 1)

        nonseeds = shuffled(
            [sid for sid in eligible if sid not in set(protected)],
            annual.rng_seed,
            f"{annual.competition_id}:{stage['stage_id']}:{group['stage_group_id']}:nonseed_fill",
        )
        pos = 0
        for block_index, size in enumerate(sizes):
            need = size - len(blocks[block_index])
            blocks[block_index].extend(nonseeds[pos:pos + need])
            pos += need
        if pos != len(nonseeds) or any(len(block) != size for block, size in zip(blocks, sizes)):
            raise AssertionError("seeded FMT001 block partition mismatch")

        winners: List[str] = []
        matches: List[Match] = []
        for block_no, block in enumerate(blocks, start=1):
            ranking, block_matches = run_single_elimination_ranking(
                block,
                competition_id=annual.competition_id,
                stage_id=stage["stage_id"],
                stage_code=stage["stage_code"],
                phase_code="BLOCK_KO",
                group_id=f"{group['stage_group_id']}-B{block_no:02d}",
                group_name=group["group_name"],
                base_seed=annual.rng_seed,
                winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
            )
            winners.append(ranking[0])
            for match in block_matches:
                match.group_id = group["stage_group_id"]
                match.group_name = group["group_name"]
                match.metadata["block_no"] = block_no
            matches.extend(block_matches)

        return winners, matches, {
            "entrant_count": len(eligible), "output_slots": slots,
            "representative_block_count": len(blocks),
            "block_sizes": [len(x) for x in blocks],
            "protected_seed_count": len(protected),
            "protected_seed_blocks": sorted(protected_blocks),
        }

    def _run_fmt006_group(self, annual, stage, group, eligible, winner_resolver):
        gid = group["stage_group_id"]
        slots = self.repo.param(stage["stage_id"], "output_slots", gid)
        if slots is None:
            raise ValueError(f"{group['group_name']}: FMT006 requires output_slots")
        supplied = annual.group_pool_assignments.get(gid)
        if supplied:
            pools = [list(x) for x in supplied]
            flat = [x for p in pools for x in p]
            if len(flat) != len(set(flat)) or set(flat) != set(eligible):
                raise ValueError(f"{gid}: supplied pools must contain each eligible team exactly once")
            if any(len(p) not in {3, 4} for p in pools):
                raise ValueError(f"{gid}: FMT006 pools must have 3 or 4 teams")
        else:
            four_count, three_count = self._solve_3_or_4_pool_plan(len(eligible), slots)
            sizes = [4] * four_count + [3] * three_count
            sizes = shuffled(sizes, annual.rng_seed, f"{annual.competition_id}:{stage['stage_id']}:{gid}:pool_sizes")
            drawn = shuffled(eligible, annual.rng_seed, f"{annual.competition_id}:{stage['stage_id']}:{gid}:pool_draw")
            pools = []
            pos = 0
            for size in sizes:
                pools.append(drawn[pos:pos + size])
                pos += size

        direct: List[str] = []
        runnerups_3: List[str] = []
        matches: List[Match] = []
        standings = {}
        for pno, pool in enumerate(pools, start=1):
            ranking, ms, table = run_round_robin(
                pool,
                competition_id=annual.competition_id,
                stage_id=stage["stage_id"], stage_code=stage["stage_code"],
                phase_code="POOL_RR", group_id=gid, group_name=group["group_name"],
                pool_no=pno, base_seed=annual.rng_seed, winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
            )
            matches.extend(ms)
            standings[str(pno)] = table
            if len(pool) == 4:
                direct.extend(ranking[:2])
            else:
                direct.append(ranking[0])
                runnerups_3.append(ranking[1])

        playoff_candidates = shuffled(
            runnerups_3, annual.rng_seed,
            f"{annual.competition_id}:{stage['stage_id']}:{gid}:cross_playoff_draw",
        )
        supplemental: List[str] = []
        match_no = 1
        i = 0
        while i < len(playoff_candidates):
            t1 = playoff_candidates[i]
            if i + 1 >= len(playoff_candidates):
                supplemental.append(t1)
                matches.append(Match(
                    match_id=f"{stage['stage_id']}-{gid}-CROSS_PLAYOFF-M{match_no:03d}",
                    competition_id=annual.competition_id, stage_id=stage["stage_id"],
                    stage_code=stage["stage_code"], phase_code="CROSS_PLAYOFF", round_no=1,
                    group_id=gid, group_name=group["group_name"], team1=t1, winner=t1,
                    is_bye=True, metadata={"reason": "unpaired_3team_pool_runnerup"},
                ))
                break
            m = run_head_to_head(
                t1, playoff_candidates[i + 1],
                competition_id=annual.competition_id, stage_id=stage["stage_id"],
                stage_code=stage["stage_code"], phase_code="CROSS_PLAYOFF",
                group_id=gid, group_name=group["group_name"], match_no=match_no,
                base_seed=annual.rng_seed, winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
            )
            matches.append(m)
            supplemental.append(m.winner)
            match_no += 1
            i += 2
        out = direct + supplemental
        if len(out) != slots:
            raise AssertionError(f"{group['group_name']}: qualifiers={len(out)} != output_slots={slots}")
        return out, matches, {
            "entrant_count": len(eligible), "output_slots": slots,
            "pool_sizes": [len(x) for x in pools],
            "four_team_pool_count": sum(1 for x in pools if len(x) == 4),
            "three_team_pool_count": sum(1 for x in pools if len(x) == 3),
            "direct_pool_qualifiers": len(direct),
            "cross_playoff_qualifiers": len(supplemental),
            "standings": standings,
            "draw_source": "annual_override" if supplied else "simulated_draw",
        }

    @staticmethod
    def _solve_3_or_4_pool_plan(entrant_count: int, output_slots: int) -> Tuple[int, int]:
        candidates = []
        for three in range(0, entrant_count // 3 + 1):
            rem = entrant_count - 3 * three
            if rem < 0 or rem % 4:
                continue
            four = rem // 4
            outputs = 2 * four + three + (three + 1) // 2
            if outputs == output_slots:
                candidates.append((four, three))
        if not candidates:
            raise ValueError(
                f"cannot partition entrants={entrant_count} into 3/4-team pools for output_slots={output_slots}"
            )
        # Prefer fewer 3-team pools: closest to the ordinary 4-team-pool form.
        return sorted(candidates, key=lambda x: (x[1], -x[0]))[0]

    def _quota_forest(
        self, annual, stage, group, teams, slots, phase_code, winner_resolver
    ):
        teams = list(teams)
        if slots < 0 or slots > len(teams):
            raise ValueError(
                f"{group['group_name']}: phase {phase_code} slots={slots} entrants={len(teams)}"
            )
        if slots == 0:
            return [], [], []
        return run_block_winner_forest(
            teams,
            block_count=slots,
            competition_id=annual.competition_id,
            stage_id=stage["stage_id"],
            stage_code=stage["stage_code"],
            phase_code=phase_code,
            group_id=group["stage_group_id"],
            group_name=group["group_name"],
            base_seed=annual.rng_seed,
            winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
        )

    def _rank_knockout(self, annual, stage, group, teams, phase_code, winner_resolver, suffix=""):
        gid = group["stage_group_id"] + suffix
        ranking, matches = run_single_elimination_ranking(
            teams,
            competition_id=annual.competition_id,
            stage_id=stage["stage_id"],
            stage_code=stage["stage_code"],
            phase_code=phase_code,
            group_id=gid,
            group_name=group["group_name"],
            base_seed=annual.rng_seed,
            winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
        )
        if suffix:
            for m in matches:
                m.group_id = group["stage_group_id"]
                m.group_name = group["group_name"]
                m.metadata["subgroup"] = suffix.lstrip("-")
        return ranking, matches

    def _round_robin_partition(
        self, annual, stage, group, teams, pool_count, phase_code, winner_resolver
    ):
        if pool_count <= 0 or pool_count > len(teams):
            raise ValueError(f"{group['group_name']}: invalid pool_count={pool_count}")
        pools = balanced_partition(
            teams,
            pool_count,
            base_seed=annual.rng_seed,
            namespace=(
                f"{annual.competition_id}:{stage['stage_id']}:{group['stage_group_id']}:"
                f"{phase_code}:pool_partition"
            ),
        )
        rankings, matches, tables = [], [], {}
        for pno, pool in enumerate(pools, start=1):
            ranking, ms, table = run_round_robin(
                pool,
                competition_id=annual.competition_id,
                stage_id=stage["stage_id"],
                stage_code=stage["stage_code"],
                phase_code=phase_code,
                group_id=group["stage_group_id"],
                group_name=group["group_name"],
                pool_no=pno,
                base_seed=annual.rng_seed,
                winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
            )
            rankings.append(ranking)
            matches.extend(ms)
            tables[str(pno)] = table
        return rankings, matches, pools, tables

    def _run_generic_qualifier_group(
        self, model_id, annual, stage, group, eligible, winner_resolver
    ):
        gid = group["stage_group_id"]
        slots = self.repo.param(
            stage["stage_id"], "output_slots", gid,
            int(group.get("advance_slots_to_next") or group.get("qualifier_slots_generated") or 0),
        )
        if slots <= 0 or slots > len(eligible):
            raise ValueError(
                f"{group['group_name']}: {model_id} output_slots={slots} entrants={len(eligible)}"
            )
        matches: List[Match] = []
        meta = {"entrant_count": len(eligible), "output_slots": slots, "model_id": model_id}

        # PRIMARY + REPECHAGE.  The source data defines the total group quota but not
        # each annual bracket split.  The engine therefore creates a deterministic
        # quota split while preserving both official phases; annual exact draws can
        # later replace this simulation boundary.
        if model_id in {"FMT002", "FMT003", "FMT016", "FMT025"}:
            if model_id in {"FMT003", "FMT016"}:
                primary_slots = slots if slots == 1 else slots - 1
            else:
                primary_slots = max(1, (slots + 1) // 2)
            primary, ms1, blocks1 = self._quota_forest(
                annual, stage, group, eligible, primary_slots, "PRIMARY", winner_resolver
            )
            matches.extend(ms1)
            primary_set = set(primary)
            remaining = [x for x in eligible if x not in primary_set]
            secondary_slots = slots - len(primary)
            secondary = []
            blocks2 = []
            if secondary_slots:
                phase = "SECONDARY" if model_id in {"FMT003", "FMT016"} else "REPECHAGE"
                secondary, ms2, blocks2 = self._quota_forest(
                    annual, stage, group, remaining, secondary_slots, phase, winner_resolver
                )
                matches.extend(ms2)
            out = primary + secondary
            if model_id == "FMT025" and len(out) > 1:
                ranking, rms = self._rank_knockout(
                    annual, stage, group, out, "RANKING", winner_resolver, suffix="-RANK"
                )
                matches.extend(rms)
                out = ranking[:slots]
            meta.update({
                "primary_slots": len(primary),
                "secondary_or_repechage_slots": len(secondary),
                "primary_block_sizes": [len(x) for x in blocks1],
                "secondary_block_sizes": [len(x) for x in blocks2],
                "annual_phase_split_policy": "deterministic_simulation_from_total_quota",
            })
            return out, matches, meta

        # Protect four teams, rank that cohort, then select remaining representatives.
        if model_id == "FMT004":
            protected_slots = self.repo.param(stage["stage_id"], "protected_primary_slots", gid, 4)
            secondary_slots = self.repo.param(
                stage["stage_id"], "secondary_output_slots", gid, slots - protected_slots
            )
            ranking, ms = self._rank_knockout(
                annual, stage, group, eligible, "PRIMARY_TOP4", winner_resolver
            )
            matches.extend(ms)
            protected = ranking[:protected_slots]
            remaining = [x for x in eligible if x not in set(protected)]
            secondary, ms2, blocks = self._quota_forest(
                annual, stage, group, remaining, secondary_slots, "SECONDARY", winner_resolver
            )
            matches.extend(ms2)
            out = protected + secondary
            meta.update({
                "protected_count": len(protected),
                "protected_ranking": protected,
                "secondary_count": len(secondary),
                "secondary_block_sizes": [len(x) for x in blocks],
            })
            return out, matches, meta

        # One knockout, stop qualification at top N; later games only determine order.
        if model_id == "FMT007":
            ranking, ms = self._rank_knockout(
                annual, stage, group, eligible, "MAIN_KO", winner_resolver
            )
            matches.extend(ms)
            out = ranking[:slots]
            meta.update({"qualified_ranking": out, "ranking_phase_simulated": True})
            return out, matches, meta

        # Four guaranteed quarterfinal winners plus two representative deciders.
        if model_id == "FMT008":
            guaranteed = self.repo.param(stage["stage_id"], "guaranteed_qf_winner_slots", gid, 4)
            rep_slots = self.repo.param(stage["stage_id"], "representative_decider_slots", gid, slots - guaranteed)
            ranking, ms = self._rank_knockout(
                annual, stage, group, eligible, "MAIN_KO", winner_resolver
            )
            matches.extend(ms)
            direct = ranking[:guaranteed]
            qf_loser_candidates = ranking[guaranteed:guaranteed + max(2 * rep_slots, rep_slots)]
            if len(qf_loser_candidates) < rep_slots:
                qf_loser_candidates = [x for x in eligible if x not in set(direct)]
            extra, ms2, blocks = self._quota_forest(
                annual, stage, group, qf_loser_candidates, rep_slots, "REP_DECIDERS", winner_resolver
            )
            matches.extend(ms2)
            out = direct + extra
            meta.update({
                "guaranteed_slots": len(direct),
                "representative_decider_slots": len(extra),
                "representative_candidate_count": len(qf_loser_candidates),
                "representative_block_sizes": [len(x) for x in blocks],
                "top4_ranking": direct,
            })
            return out, matches, meta

        # Multiple primary knockout blocks determine rank 1/2, then a secondary event.
        if model_id == "FMT010":
            min_blocks = (slots + 1) // 2
            block_count = min(len(eligible) // 2, min_blocks + 1)
            block_count = max(min_blocks, block_count)
            blocks = balanced_partition(
                eligible, block_count, base_seed=annual.rng_seed,
                namespace=f"{annual.competition_id}:{stage['stage_id']}:{gid}:PRIMARY_BLOCKS",
            )
            survivors = []
            primary_sizes = []
            for idx, block in enumerate(blocks, start=1):
                ranking, ms = self._rank_knockout(
                    annual, stage, group, block, "PRIMARY_BLOCKS", winner_resolver,
                    suffix=f"-PB{idx:02d}",
                )
                matches.extend(ms)
                survivors.extend(ranking[: min(2, len(ranking))])
                primary_sizes.append(len(block))
            if len(survivors) < slots:
                raise AssertionError(f"{group['group_name']}: primary rank1/2 cohort smaller than quota")
            out, ms2, secondary_blocks = self._quota_forest(
                annual, stage, group, survivors, slots, "SECONDARY", winner_resolver
            )
            matches.extend(ms2)
            meta.update({
                "primary_block_count": block_count,
                "primary_block_sizes": primary_sizes,
                "primary_rank1_rank2_count": len(survivors),
                "secondary_block_sizes": [len(x) for x in secondary_blocks],
            })
            return out, matches, meta

        # Round-robin pool qualifiers feed a secondary knockout.
        if model_id in {"FMT011", "FMT013"}:
            if model_id == "FMT013":
                pool_count = self.repo.param(stage["stage_id"], "primary_pool_count", gid, 4)
                advance_per_pool = self.repo.param(stage["stage_id"], "advance_per_pool", gid, 2)
            else:
                pool_count = min(max(1, (slots + 1) // 2 + 1), max(1, len(eligible) // 2))
                advance_per_pool = 2
            rankings, ms, pools, tables = self._round_robin_partition(
                annual, stage, group, eligible, pool_count, "PRIMARY_LEAGUE", winner_resolver
            )
            matches.extend(ms)
            survivors = []
            for ranking in rankings:
                survivors.extend(ranking[: min(advance_per_pool, len(ranking))])
            if len(survivors) < slots:
                # Preserve the league mechanism and fill the cohort from the best
                # remaining simulated positions if a small pool produced fewer slots.
                leftovers = [x for r in rankings for x in r[advance_per_pool:]]
                survivors.extend(leftovers[: slots - len(survivors)])
            out, ms2, secondary_blocks = self._quota_forest(
                annual, stage, group, survivors, slots, "SECONDARY", winner_resolver
            )
            matches.extend(ms2)
            meta.update({
                "primary_pool_count": pool_count,
                "pool_sizes": [len(x) for x in pools],
                "advance_per_pool": advance_per_pool,
                "secondary_entrant_count": len(survivors),
                "secondary_block_sizes": [len(x) for x in secondary_blocks],
                "standings": tables,
            })
            return out, matches, meta

        # Independent knockout zones feed final/placement brackets.
        if model_id == "FMT012":
            zone_count = min(len(eligible), slots + max(2, slots // 3))
            zone_winners, ms, zones = self._quota_forest(
                annual, stage, group, eligible, zone_count, "PRIMARY_ZONES", winner_resolver
            )
            matches.extend(ms)
            out, ms2, secondary_blocks = self._quota_forest(
                annual, stage, group, zone_winners, slots, "SECONDARY", winner_resolver
            )
            matches.extend(ms2)
            meta.update({
                "zone_count": zone_count,
                "zone_sizes": [len(x) for x in zones],
                "secondary_entrant_count": len(zone_winners),
                "secondary_block_sizes": [len(x) for x in secondary_blocks],
            })
            return out, matches, meta

        # Primary forest -> secondary forest.  FMT015 also restores a cohort through
        # a primary repechage before the secondary draw.
        if model_id in {"FMT014", "FMT015"}:
            if model_id == "FMT014":
                primary_survivor_slots = min(len(eligible), slots + max(2, slots // 2))
                primary, ms1, blocks1 = self._quota_forest(
                    annual, stage, group, eligible, primary_survivor_slots, "PRIMARY", winner_resolver
                )
                secondary_entrants = list(primary)
                repechage = []
                blocks_rep = []
                matches.extend(ms1)
            else:
                primary_survivor_slots = max(1, slots - max(2, slots // 3))
                primary, ms1, blocks1 = self._quota_forest(
                    annual, stage, group, eligible, primary_survivor_slots, "PRIMARY", winner_resolver
                )
                matches.extend(ms1)
                remaining = [x for x in eligible if x not in set(primary)]
                desired_rep = min(len(remaining), slots - len(primary) + max(2, slots // 4))
                repechage, msr, blocks_rep = self._quota_forest(
                    annual, stage, group, remaining, desired_rep, "PRIMARY_REPECHAGE", winner_resolver
                )
                matches.extend(msr)
                secondary_entrants = primary + repechage
            if len(secondary_entrants) < slots:
                raise AssertionError(f"{group['group_name']}: secondary cohort smaller than quota")
            out, ms2, blocks2 = self._quota_forest(
                annual, stage, group, secondary_entrants, slots, "SECONDARY", winner_resolver
            )
            matches.extend(ms2)
            meta.update({
                "primary_survivor_count": len(primary),
                "primary_block_sizes": [len(x) for x in blocks1],
                "repechage_survivor_count": len(repechage),
                "repechage_block_sizes": [len(x) for x in blocks_rep],
                "secondary_entrant_count": len(secondary_entrants),
                "secondary_block_sizes": [len(x) for x in blocks2],
            })
            return out, matches, meta

        # Zone round robins followed by first-place and second-place representative
        # decisions.  A loser from a configured first-place playoff remains eligible
        # for the second-place path, matching the Stage 12B contract.
        if model_id == "FMT017":
            zone_count = self.repo.param(stage["stage_id"], "zone_count", gid)
            first_slots = self.repo.param(stage["stage_id"], "first_place_representative_slots", gid)
            second_slots = self.repo.param(stage["stage_id"], "second_place_representative_slots", gid)
            first_playoff = self.repo.param(stage["stage_id"], "first_place_playoff_enabled", gid, False)
            rankings, ms, zones, tables = self._round_robin_partition(
                annual, stage, group, eligible, zone_count, "ZONE_RR", winner_resolver
            )
            matches.extend(ms)
            zone_winners = [r[0] for r in rankings if r]
            zone_runners = [r[1] for r in rankings if len(r) > 1]
            if first_playoff or first_slots < len(zone_winners):
                first_reps, ms1, first_blocks = self._quota_forest(
                    annual, stage, group, zone_winners, first_slots, "FIRST_PLACE_PLAYOFF", winner_resolver
                )
                matches.extend(ms1)
                first_losers = [x for x in zone_winners if x not in set(first_reps)]
            else:
                first_reps = zone_winners[:first_slots]
                first_losers = zone_winners[first_slots:]
                first_blocks = []
            second_candidates = self._dedup(zone_runners + first_losers)
            second_reps, ms2, second_blocks = self._quota_forest(
                annual, stage, group, second_candidates, second_slots, "SECOND_PLACE_PLAYOFF", winner_resolver
            )
            matches.extend(ms2)
            out = first_reps + second_reps
            if len(out) != slots:
                raise AssertionError(f"{group['group_name']}: FMT017 outputs={len(out)} != {slots}")
            meta.update({
                "zone_count": zone_count,
                "zone_sizes": [len(x) for x in zones],
                "first_place_slots": len(first_reps),
                "first_place_playoff": bool(first_playoff),
                "first_place_playoff_block_sizes": [len(x) for x in first_blocks],
                "second_place_candidate_count": len(second_candidates),
                "second_place_slots": len(second_reps),
                "second_place_block_sizes": [len(x) for x in second_blocks],
                "standings": tables,
            })
            return out, matches, meta

        raise NotImplementedError(f"generic qualifier model {model_id}")

    def _run_fmt005_global_repechage(self, annual, entrants, stage, winner_resolver) -> StageExecution:
        primary_slots = self.repo.param(stage["stage_id"], "primary_qualifier_slots")
        repechage_slots = self.repo.param(stage["stage_id"], "repechage_qualifier_slots")
        if not primary_slots or not repechage_slots:
            raise ValueError("FMT005 requires primary_qualifier_slots and repechage_qualifier_slots")
        primary, primary_matches, primary_blocks = run_block_winner_forest(
            entrants,
            block_count=primary_slots,
            competition_id=annual.competition_id, stage_id=stage["stage_id"],
            stage_code=stage["stage_code"], phase_code="PRIMARY_GLOBAL",
            group_id="", group_name="全県", base_seed=annual.rng_seed,
            winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
        )
        primary_set = set(primary)
        nonqualifiers = [x for x in entrants if x not in primary_set]
        repechage, rep_matches, rep_blocks = run_block_winner_forest(
            nonqualifiers,
            block_count=repechage_slots,
            competition_id=annual.competition_id, stage_id=stage["stage_id"],
            stage_code=stage["stage_code"], phase_code="REPECHAGE_GLOBAL",
            group_id="", group_name="全県", base_seed=annual.rng_seed,
            winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
        )
        outputs = primary + repechage
        accounting = self._account_by_stage_group(stage, outputs, annual.year)
        return StageExecution(
            stage_id=stage["stage_id"], stage_code=stage["stage_code"],
            format_model_id="FMT005", entrant_school_ids=list(entrants),
            output_school_ids=outputs, matches=primary_matches + rep_matches,
            metadata={
                "primary_qualifier_count": len(primary),
                "primary_nonqualifier_count": len(nonqualifiers),
                "repechage_qualifier_count": len(repechage),
                "primary_block_sizes": [len(x) for x in primary_blocks],
                "repechage_block_sizes": [len(x) for x in rep_blocks],
                "accounting_group_output_counts": accounting,
            },
        )

    def _account_by_stage_group(self, stage, school_ids, year):
        counts = {}
        ids = set(school_ids)
        for group in self.repo.groups_by_stage.get(stage["stage_id"], []):
            counts[group["stage_group_id"]] = len(ids & self.repo.group_school_ids(group, year))
        return counts

    # ------------------------------------------------------------------
    # Seed-event dispatch (FMT009 / FMT018..FMT021)
    # ------------------------------------------------------------------
    def _run_seed_event(self, annual, entrants, stage, winner_resolver):
        assignment = self.repo.assignments_by_stage.get(stage["stage_id"])
        if not assignment:
            raise KeyError(f"no format assignment for {stage['stage_id']}")
        default_model = assignment["default_format_model_id"]
        groups = self.repo.groups_by_stage.get(stage["stage_id"], [])
        all_assignments: List[SeedAssignment] = []
        all_matches: List[Match] = []
        group_outputs: Dict[str, List[str]] = {}
        group_models: Dict[str, str] = {}
        group_metadata: Dict[str, dict] = {}
        entrant_set = set(entrants)

        # Cross-competition access rules can grant a MAIN seed while bypassing the
        # district seed event.  Keep this annual/result-driven: no school name is
        # hardcoded here.  Linked seed rules (linked_access_rule_id) define the seed
        # tier and destination metadata.
        bypass_seed_ids = self._dedup(annual.seed_event_bypass_school_ids)
        outside_bypass = set(bypass_seed_ids) - entrant_set
        if outside_bypass:
            raise ValueError(
                f"seed-event bypass teams must be competition entrants: {sorted(outside_bypass)}"
            )
        linked_rules = [
            r for r in self.repo.seed_rules(annual.competition_id)
            if r.get("linked_access_rule_id")
        ]
        linked_capacity = sum(int(r.get("seed_count") or 0) for r in linked_rules)
        if bypass_seed_ids and not linked_rules:
            raise ValueError(
                "seed_event_bypass_school_ids supplied but competition has no linked seed rule"
            )
        if len(bypass_seed_ids) > linked_capacity:
            raise ValueError(
                f"seed-event bypass count={len(bypass_seed_ids)} exceeds linked seed capacity={linked_capacity}"
            )
        forced_seed_assignments: List[SeedAssignment] = []
        pos = 0
        for rule in sorted(linked_rules, key=lambda r: (-int(r.get("priority") or 0), r["seed_rule_id"])):
            count = int(rule.get("seed_count") or 0)
            for local_rank, school_id in enumerate(bypass_seed_ids[pos:pos + count], start=1):
                forced_seed_assignments.append(SeedAssignment(
                    school_id=school_id, group_id="", group_name="special_access",
                    seed_tier=rule.get("seed_tier", ""), source_rank=local_rank,
                    seed_rule_id=rule["seed_rule_id"],
                    destination_stage=rule.get("destination_entry_stage", ""),
                ))
            pos += count

        for group in groups:
            gid = group["stage_group_id"]
            override = self.repo.group_format.get(gid)
            model_id = (override or {}).get("format_model_id") or default_model
            group_models[gid] = model_id
            if model_id not in self.SUPPORTED_FORMAT_MODELS:
                raise NotImplementedError(f"seed handler does not support {model_id}")
            eligible = [
                sid for sid in self._eligible_group_entrants(annual, group, entrant_set)
                if sid not in set(bypass_seed_ids)
            ]
            output_slots = self.repo.param(
                stage["stage_id"], "output_slots", gid,
                int(group.get("seed_slots_generated") or 0),
            )
            if len(eligible) < output_slots:
                raise ValueError(f"{group['group_name']}: entrants={len(eligible)} < seed slots={output_slots}")

            supplied = annual.group_rankings.get(gid)
            if supplied:
                if len(supplied) < output_slots:
                    raise ValueError(f"{gid}: supplied ranking shorter than output slots")
                unknown = set(supplied) - set(eligible)
                if unknown:
                    raise ValueError(f"{gid}: ranking contains ineligible teams {sorted(unknown)}")
                ranking, matches, meta = list(supplied), [], {"ranking_source": "annual_override"}
            else:
                ranking, matches, meta = self._simulate_seed_group(
                    model_id, annual, stage, group, eligible, output_slots, winner_resolver
                )
            top = ranking[:output_slots]
            group_outputs[gid] = top
            group_metadata[gid] = meta
            all_matches.extend(matches)
            all_assignments.extend(self._seed_assignments_from_rules(annual.competition_id, group, top))

        all_assignments.extend(forced_seed_assignments)
        dedup: Dict[str, SeedAssignment] = {}
        for a in sorted(all_assignments, key=lambda x: (x.source_rank, x.seed_rule_id)):
            dedup.setdefault(a.school_id, a)
        out = list(dedup.values())
        out.sort(key=lambda x: (x.group_name, x.source_rank, x.school_id))
        expected = sum(int(g.get("seed_slots_generated") or 0) for g in groups) + len(forced_seed_assignments)
        if len(out) != expected:
            raise AssertionError(f"seed output count {len(out)} != expected group slots {expected}")
        execution = StageExecution(
            stage_id=stage["stage_id"], stage_code=stage["stage_code"],
            format_model_id=default_model, entrant_school_ids=list(entrants),
            output_school_ids=[x.school_id for x in out], matches=all_matches,
            metadata={
                "group_count": len(groups), "seed_count": len(out),
                "group_outputs": group_outputs, "group_models": group_models,
                "group_metadata": group_metadata,
                "annual_ranking_override_groups": sorted(annual.group_rankings),
                "seed_event_bypass_school_ids": list(bypass_seed_ids),
                "forced_seed_count": len(forced_seed_assignments),
            },
        )
        return out, execution

    def _simulate_seed_group(self, model_id, annual, stage, group, eligible, output_slots, winner_resolver):
        gid, gname = group["stage_group_id"], group["group_name"]

        if model_id == "FMT001":
            winners, matches, blocks = run_block_winner_forest(
                eligible,
                block_count=output_slots,
                competition_id=annual.competition_id, stage_id=stage["stage_id"],
                stage_code=stage["stage_code"], phase_code="SEED_BLOCK_KO",
                group_id=gid, group_name=gname, base_seed=annual.rng_seed,
                winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
            )
            leftovers = [x for x in eligible if x not in set(winners)]
            ranking = winners + shuffled(
                leftovers, annual.rng_seed,
                f"{annual.competition_id}:{stage['stage_id']}:{gid}:FMT001:leftovers",
            )
            return ranking, matches, {
                "ranking_source": "simulated_fmt001_block_winners",
                "representative_block_count": len(blocks),
                "block_sizes": [len(x) for x in blocks],
            }

        if model_id in {"FMT022", "FMT023", "FMT024"}:
            phase = {
                "FMT022": "CENTRAL_KO",
                "FMT023": "DISTRICT_KO",
                "FMT024": "SEED_KO",
            }[model_id]
            ranking, matches = run_single_elimination_ranking(
                eligible,
                competition_id=annual.competition_id, stage_id=stage["stage_id"],
                stage_code=stage["stage_code"], phase_code=phase,
                group_id=gid, group_name=gname, base_seed=annual.rng_seed,
                winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
            )
            return ranking, matches, {
                "ranking_source": f"simulated_{model_id.lower()}",
                "seed_cut_count": output_slots,
            }

        if model_id == "FMT009":
            ranking, matches = run_single_elimination_ranking(
                eligible,
                competition_id=annual.competition_id, stage_id=stage["stage_id"],
                stage_code=stage["stage_code"], phase_code="SEED_KO",
                group_id=gid, group_name=gname, base_seed=annual.rng_seed,
                winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
            )
            return ranking, matches, {"ranking_source": "simulated_fmt009"}

        if model_id in {"FMT018", "FMT020"}:
            primary, matches = run_single_elimination_ranking(
                eligible,
                competition_id=annual.competition_id, stage_id=stage["stage_id"],
                stage_code=stage["stage_code"], phase_code="PRIMARY_SEED_KO",
                group_id=gid, group_name=gname, base_seed=annual.rng_seed,
                winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
            )
            top2 = primary[:2]
            remaining = [x for x in eligible if x not in set(top2)]
            remaining_slots = max(0, output_slots - len(top2))
            extra: List[str] = []
            second_matches: List[Match] = []
            blocks: List[List[str]] = []
            if remaining_slots:
                phase = "SEED_REPECHAGE" if model_id == "FMT018" else "THIRD_SEED"
                extra, second_matches, blocks = run_block_winner_forest(
                    remaining,
                    block_count=remaining_slots,
                    competition_id=annual.competition_id, stage_id=stage["stage_id"],
                    stage_code=stage["stage_code"], phase_code=phase,
                    group_id=gid, group_name=gname, base_seed=annual.rng_seed,
                    winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
                )
            ranking = top2 + extra + [x for x in primary if x not in set(top2 + extra)]
            return ranking, matches + second_matches, {
                "ranking_source": f"simulated_{model_id.lower()}",
                "primary_top2": top2, "secondary_block_sizes": [len(x) for x in blocks],
            }

        if model_id in {"FMT019", "FMT021"}:
            area_map = self.repo.area_school_ids_for_group(group, annual.year)
            subpools = []
            for area_id, ids in area_map.items():
                pool = sorted(set(eligible) & ids)
                if pool:
                    subpools.append((area_id, pool))
            if len(subpools) < 2:
                parts = balanced_partition(
                    eligible, 2, base_seed=annual.rng_seed,
                    namespace=f"{annual.competition_id}:{stage['stage_id']}:{gid}:{model_id}:fallback_subpools",
                )
                subpools = [(f"AUTO{i}", p) for i, p in enumerate(parts, start=1)]
            primary_phase = "PRIMARY_LEAGUES" if model_id == "FMT019" else "DISTRICT_RR"
            primary_rankings = []
            all_matches: List[Match] = []
            standing_meta = {}
            for pno, (area_id, pool) in enumerate(subpools, start=1):
                rank, ms, table = run_round_robin(
                    pool,
                    competition_id=annual.competition_id, stage_id=stage["stage_id"],
                    stage_code=stage["stage_code"], phase_code=primary_phase,
                    group_id=gid, group_name=gname, pool_no=pno,
                    base_seed=annual.rng_seed, winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
                )
                primary_rankings.append(rank)
                all_matches.extend(ms)
                standing_meta[area_id] = table
            first_class = [r[0] for r in primary_rankings if r]
            second_class = [r[1] for r in primary_rankings if len(r) > 1]
            phase = "RANKING" if model_id == "FMT019" else "CROSS_DECIDERS"
            ranked: List[str] = []
            for cls_no, candidates in enumerate([first_class, second_class], start=1):
                if not candidates:
                    continue
                if len(candidates) == 1:
                    class_ranking = list(candidates)
                elif len(candidates) == 2:
                    m = run_head_to_head(
                        candidates[0], candidates[1],
                        competition_id=annual.competition_id, stage_id=stage["stage_id"],
                        stage_code=stage["stage_code"], phase_code=phase,
                        group_id=gid, group_name=gname, match_no=cls_no,
                        base_seed=annual.rng_seed, winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
                    )
                    all_matches.append(m)
                    class_ranking = [m.winner, m.loser]
                else:
                    class_ranking, ms, _ = run_round_robin(
                        candidates,
                        competition_id=annual.competition_id, stage_id=stage["stage_id"],
                        stage_code=stage["stage_code"], phase_code=phase,
                        group_id=gid, group_name=gname, pool_no=100 + cls_no,
                        base_seed=annual.rng_seed, winner_resolver=winner_resolver,
            **self._pre_main_resolution_kwargs(annual),
                    )
                    all_matches.extend(ms)
                ranked.extend(class_ranking)
            leftovers = [x for x in eligible if x not in set(ranked)]
            ranking = ranked + shuffled(
                leftovers, annual.rng_seed,
                f"{annual.competition_id}:{stage['stage_id']}:{gid}:{model_id}:leftover_order",
            )
            return ranking, all_matches, {
                "ranking_source": f"simulated_{model_id.lower()}",
                "subpool_count": len(subpools), "subpool_sizes": [len(x[1]) for x in subpools],
                "standings": standing_meta,
            }

        raise NotImplementedError(f"seed model {model_id}")

    def _seed_assignments_from_rules(self, competition_id: str, group: dict, ranked: Sequence[str]) -> List[SeedAssignment]:
        area_ids = {x for x in group.get("source_area_ids", "").split(";") if x}
        rules = []
        for r in self.repo.seed_rules_by_comp.get(competition_id, []):
            rule_areas = {x for x in r.get("source_area_ids", "").split(";") if x}
            if area_ids & rule_areas:
                rules.append(r)
        output: List[SeedAssignment] = []
        consumed = 0
        selector_order = {
            "rank_1": 1, "rank_2": 2,
            "rank_3_cohort": 3, "remaining_official_seed_qualifiers": 3,
        }
        rules.sort(key=lambda r: (
            selector_order.get(r.get("source_result_selector", ""), 99),
            -int(r.get("priority") or 0), r["seed_rule_id"],
        ))
        for r in rules:
            count = int(r.get("seed_count") or 0)
            selector = r.get("source_result_selector", "")
            if selector == "rank_1":
                start = 0
            elif selector == "rank_2":
                start = 1
            elif selector == "rank_3_cohort":
                start = 2
            else:
                start = consumed
            picks = list(ranked[start:start + count])
            for idx, school_id in enumerate(picks, start=start + 1):
                output.append(SeedAssignment(
                    school_id=school_id, group_id=group["stage_group_id"],
                    group_name=group["group_name"], seed_tier=r.get("seed_tier", ""),
                    source_rank=idx, seed_rule_id=r["seed_rule_id"],
                    destination_stage=r.get("destination_entry_stage", ""),
                ))
            consumed = max(consumed, start + count)
        return output

    # ------------------------------------------------------------------
    # Audit helpers
    # ------------------------------------------------------------------
    def _observed_main_count_warnings(self, stage, main_entrants, direct):
        warnings = []
        observed = self.repo.param(stage["stage_id"], "observed_main_total")
        if observed is not None and len(main_entrants) != observed:
            warnings.append(f"2026 observed MAIN total={observed}, current run={len(main_entrants)}")
        observed_direct = self.repo.param(stage["stage_id"], "observed_direct_access_slots")
        if observed_direct is not None and len(direct) != observed_direct:
            warnings.append(f"2026 observed direct access={observed_direct}, current input={len(direct)}")
        return warnings

    @staticmethod
    def _dedup(items: Sequence[str]) -> List[str]:
        out, seen = [], set()
        for x in items:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
