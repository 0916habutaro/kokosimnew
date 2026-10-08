from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .brackets import balanced_partition
from .models import (
    AnnualCompetitionInput,
    Match,
    MatchResolution,
    SeedAssignment,
    StageExecution,
)
from .premain_runtime_common import RuntimePreMainMatch, resolve_runtime_match
from .premain_runtime_forest import BlockForestRuntimeState
from .premain_runtime_round_robin import RoundRobinRuntimeState
from .premain_runtime_single_elim import SingleEliminationRuntimeState
from .randomness import shuffled
from .repository import DataRepository
from .tournament_runtime import MATCH_COMPLETED, MATCH_READY


SEED_EVENT_MODELS = {
    "FMT001",
    "FMT009",
    "FMT018",
    "FMT019",
    "FMT020",
    "FMT021",
    "FMT022",
    "FMT023",
    "FMT024",
}


@dataclass
class HeadToHeadRuntimeState:
    competition_id: str
    reference_year: int
    generation_seed: int
    stage_id: str
    stage_code: str
    phase_code: str
    group_id: str
    group_name: str
    match_no: int
    match: RuntimePreMainMatch
    match_resolver: object | None = field(default=None, repr=False)
    match_simulation_results: Dict[str, dict] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        team1: str,
        team2: str,
        *,
        competition_id: str,
        reference_year: int,
        stage_id: str,
        stage_code: str,
        phase_code: str,
        group_id: str,
        group_name: str,
        match_no: int,
        generation_seed: int,
        match_resolver=None,
        resolved_match_sink: Dict[str, dict] | None = None,
    ) -> "HeadToHeadRuntimeState":
        match_id = (
            f"{stage_id}-{group_id or 'GLOBAL'}-"
            f"{phase_code}-M{match_no:03d}"
        )
        sink = resolved_match_sink if resolved_match_sink is not None else {}
        return cls(
            competition_id=competition_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            stage_id=stage_id,
            stage_code=stage_code,
            phase_code=phase_code,
            group_id=group_id,
            group_name=group_name,
            match_no=match_no,
            match=RuntimePreMainMatch(
                match_id=match_id,
                competition_id=competition_id,
                stage_id=stage_id,
                stage_code=stage_code,
                phase_code=phase_code,
                round_no=1,
                group_id=group_id,
                group_name=group_name,
                team1=team1,
                team2=team2,
                status=MATCH_READY,
                match_seq=match_no,
            ),
            match_resolver=match_resolver,
            match_simulation_results=sink,
        )

    @property
    def is_complete(self) -> bool:
        return self.match.status == MATCH_COMPLETED

    def contains_match(self, match_id: str) -> bool:
        return match_id == self.match.match_id

    def ready_matches(self) -> list[dict]:
        if self.match.status != MATCH_READY:
            return []
        return [self.match.public_dict()]

    def resolve_match(self, match_id: str) -> MatchResolution:
        if match_id != self.match.match_id:
            raise KeyError(f"unknown match_id: {match_id}")
        if self.match.status != MATCH_READY:
            raise ValueError(f"{match_id}: match is not ready")
        return resolve_runtime_match(
            self.match,
            competition_id=self.competition_id,
            reference_year=self.reference_year,
            generation_seed=self.generation_seed,
            namespace=(
                f"{self.competition_id}:{self.stage_id}:"
                f"{self.group_id}:{self.phase_code}:"
                f"M{self.match_no}:{self.match.team1}:{self.match.team2}"
            ),
            match_resolver=self.match_resolver,
            resolved_match_sink=self.match_simulation_results,
        )

    def resolve_all(self) -> list[str]:
        if not self.is_complete:
            self.resolve_match(self.match.match_id)
        return self.ranking()

    def ranking(self) -> list[str]:
        if not self.is_complete:
            raise ValueError("head-to-head ranking unavailable before completion")
        return [self.match.winner, self.match.loser]

    def to_matches(self) -> list[Match]:
        m = self.match
        return [
            Match(
                match_id=m.match_id,
                competition_id=m.competition_id,
                stage_id=m.stage_id,
                stage_code=m.stage_code,
                phase_code=m.phase_code,
                round_no=1,
                group_id=m.group_id,
                group_name=m.group_name,
                team1=m.team1,
                team2=m.team2,
                winner=m.winner,
                loser=m.loser,
                metadata=dict(m.metadata),
            )
        ]


@dataclass
class SeedGroupRuntimeState:
    repo: DataRepository
    group: dict
    eligible_school_ids: List[str]
    output_slots: int
    format_model_id: str
    competition_id: str
    reference_year: int
    stage_id: str
    stage_code: str
    generation_seed: int
    match_resolver: object | None = field(default=None, repr=False)
    match_simulation_results: Dict[str, dict] = field(default_factory=dict)
    ranking_override: List[str] = field(default_factory=list)
    primary: object | None = None
    secondary: object | None = None
    class_runtimes: List[object | None] = field(default_factory=list)
    class_static_rankings: List[List[str]] = field(default_factory=list)
    subpool_area_ids: List[str] = field(default_factory=list)
    subpools: List[List[str]] = field(default_factory=list)
    final_ranking: List[str] = field(default_factory=list)
    final_metadata: dict = field(default_factory=dict)
    activated_secondary: bool = False

    @classmethod
    def create(
        cls,
        *,
        repo: DataRepository,
        group: dict,
        eligible_school_ids: Sequence[str],
        output_slots: int,
        format_model_id: str,
        competition_id: str,
        reference_year: int,
        stage_id: str,
        stage_code: str,
        generation_seed: int,
        supplied_ranking: Sequence[str] | None = None,
        match_resolver=None,
        resolved_match_sink: Dict[str, dict] | None = None,
    ) -> "SeedGroupRuntimeState":
        if format_model_id not in SEED_EVENT_MODELS:
            raise NotImplementedError(format_model_id)
        eligible = list(eligible_school_ids)
        if output_slots <= 0 or len(eligible) < output_slots:
            raise ValueError(
                f"{group['group_name']}: entrants={len(eligible)} "
                f"< seed slots={output_slots}"
            )
        sink = resolved_match_sink if resolved_match_sink is not None else {}
        runtime = cls(
            repo=repo,
            group=dict(group),
            eligible_school_ids=eligible,
            output_slots=output_slots,
            format_model_id=format_model_id,
            competition_id=competition_id,
            reference_year=reference_year,
            stage_id=stage_id,
            stage_code=stage_code,
            generation_seed=generation_seed,
            match_resolver=match_resolver,
            match_simulation_results=sink,
        )

        if supplied_ranking:
            supplied = list(supplied_ranking)
            if len(supplied) < output_slots:
                raise ValueError(
                    f"{group['stage_group_id']}: "
                    "supplied ranking shorter than output slots"
                )
            unknown = set(supplied) - set(eligible)
            if unknown:
                raise ValueError(
                    f"{group['stage_group_id']}: "
                    f"ranking contains ineligible teams {sorted(unknown)}"
                )
            runtime.ranking_override = supplied
            runtime.final_ranking = supplied
            runtime.final_metadata = {"ranking_source": "annual_override"}
            return runtime

        runtime._prepare_primary()
        return runtime

    @property
    def gid(self) -> str:
        return self.group["stage_group_id"]

    def _prepare_primary(self) -> None:
        model = self.format_model_id
        if model == "FMT001":
            self.primary = BlockForestRuntimeState.create(
                self.eligible_school_ids,
                block_count=self.output_slots,
                competition_id=self.competition_id,
                reference_year=self.reference_year,
                stage_id=self.stage_id,
                stage_code=self.stage_code,
                phase_code="SEED_BLOCK_KO",
                group_id=self.gid,
                group_name=self.group["group_name"],
                generation_seed=self.generation_seed,
                match_resolver=self.match_resolver,
                resolved_match_sink=self.match_simulation_results,
            )
            return

        if model in {"FMT009", "FMT022", "FMT023", "FMT024"}:
            phase_code = {
                "FMT009": "SEED_KO",
                "FMT022": "CENTRAL_KO",
                "FMT023": "DISTRICT_KO",
                "FMT024": "SEED_KO",
            }[model]
            self.primary = SingleEliminationRuntimeState.create(
                self.eligible_school_ids,
                competition_id=self.competition_id,
                reference_year=self.reference_year,
                stage_id=self.stage_id,
                stage_code=self.stage_code,
                phase_code=phase_code,
                group_id=self.gid,
                group_name=self.group["group_name"],
                generation_seed=self.generation_seed,
                match_resolver=self.match_resolver,
                resolved_match_sink=self.match_simulation_results,
            )
            return

        if model in {"FMT018", "FMT020"}:
            self.primary = SingleEliminationRuntimeState.create(
                self.eligible_school_ids,
                competition_id=self.competition_id,
                reference_year=self.reference_year,
                stage_id=self.stage_id,
                stage_code=self.stage_code,
                phase_code="PRIMARY_SEED_KO",
                group_id=self.gid,
                group_name=self.group["group_name"],
                generation_seed=self.generation_seed,
                match_resolver=self.match_resolver,
                resolved_match_sink=self.match_simulation_results,
            )
            return

        if model in {"FMT019", "FMT021"}:
            area_map = self.repo.area_school_ids_for_group(
                self.group,
                self.reference_year,
            )
            subpools = []
            area_ids = []
            for area_id, ids in area_map.items():
                pool = sorted(set(self.eligible_school_ids) & ids)
                if pool:
                    area_ids.append(area_id)
                    subpools.append(pool)
            if len(subpools) < 2:
                subpools = balanced_partition(
                    self.eligible_school_ids,
                    2,
                    base_seed=self.generation_seed,
                    namespace=(
                        f"{self.competition_id}:{self.stage_id}:"
                        f"{self.gid}:{model}:fallback_subpools"
                    ),
                )
                area_ids = [
                    f"AUTO{i}"
                    for i in range(1, len(subpools) + 1)
                ]
            self.subpool_area_ids = area_ids
            self.subpools = [list(pool) for pool in subpools]
            phase_code = (
                "PRIMARY_LEAGUES"
                if model == "FMT019"
                else "DISTRICT_RR"
            )
            self.primary = [
                RoundRobinRuntimeState.create(
                    pool,
                    competition_id=self.competition_id,
                    reference_year=self.reference_year,
                    stage_id=self.stage_id,
                    stage_code=self.stage_code,
                    phase_code=phase_code,
                    group_id=self.gid,
                    group_name=self.group["group_name"],
                    pool_no=pool_no,
                    generation_seed=self.generation_seed,
                    match_resolver=self.match_resolver,
                    resolved_match_sink=self.match_simulation_results,
                )
                for pool_no, pool in enumerate(
                    self.subpools,
                    start=1,
                )
            ]
            return

        raise NotImplementedError(model)

    @property
    def primary_complete(self) -> bool:
        if isinstance(self.primary, list):
            return all(runtime.is_complete for runtime in self.primary)
        return self.primary is None or self.primary.is_complete

    def _activate_dependent_phase(self) -> None:
        if (
            self.ranking_override
            or self.final_ranking
            or not self.primary_complete
            or self.activated_secondary
        ):
            return

        model = self.format_model_id
        if model == "FMT001":
            winners = self.primary.winners()
            leftovers = [
                team
                for team in self.eligible_school_ids
                if team not in set(winners)
            ]
            self.final_ranking = winners + shuffled(
                leftovers,
                self.generation_seed,
                (
                    f"{self.competition_id}:{self.stage_id}:"
                    f"{self.gid}:FMT001:leftovers"
                ),
            )
            self.final_metadata = {
                "ranking_source": "simulated_fmt001_block_winners",
                "representative_block_count": len(self.primary.blocks),
                "block_sizes": [
                    len(block) for block in self.primary.blocks
                ],
            }
            self.activated_secondary = True
            return

        if model in {"FMT009", "FMT022", "FMT023", "FMT024"}:
            self.final_ranking = self.primary.ranking()
            if model == "FMT009":
                self.final_metadata = {
                    "ranking_source": "simulated_fmt009",
                }
            else:
                self.final_metadata = {
                    "ranking_source": f"simulated_{model.lower()}",
                    "seed_cut_count": self.output_slots,
                }
            self.activated_secondary = True
            return

        if model in {"FMT018", "FMT020"}:
            primary_ranking = self.primary.ranking()
            top2 = primary_ranking[:2]
            remaining = [
                team
                for team in self.eligible_school_ids
                if team not in set(top2)
            ]
            remaining_slots = max(0, self.output_slots - len(top2))
            self.final_metadata = {
                "ranking_source": f"simulated_{model.lower()}",
                "primary_top2": top2,
                "secondary_block_sizes": [],
            }
            if remaining_slots:
                phase_code = (
                    "SEED_REPECHAGE"
                    if model == "FMT018"
                    else "THIRD_SEED"
                )
                self.secondary = BlockForestRuntimeState.create(
                    remaining,
                    block_count=remaining_slots,
                    competition_id=self.competition_id,
                    reference_year=self.reference_year,
                    stage_id=self.stage_id,
                    stage_code=self.stage_code,
                    phase_code=phase_code,
                    group_id=self.gid,
                    group_name=self.group["group_name"],
                    generation_seed=self.generation_seed,
                    match_resolver=self.match_resolver,
                    resolved_match_sink=self.match_simulation_results,
                )
                self.final_metadata["secondary_block_sizes"] = [
                    len(block) for block in self.secondary.blocks
                ]
            else:
                self._finish_primary_secondary_seed([])
            self.activated_secondary = True
            return

        if model in {"FMT019", "FMT021"}:
            primary_rankings = [
                runtime.ranking()
                for runtime in self.primary
            ]
            first_class = [
                ranking[0]
                for ranking in primary_rankings
                if ranking
            ]
            second_class = [
                ranking[1]
                for ranking in primary_rankings
                if len(ranking) > 1
            ]
            phase_code = (
                "RANKING"
                if model == "FMT019"
                else "CROSS_DECIDERS"
            )
            self.class_runtimes = []
            self.class_static_rankings = []
            for class_no, candidates in enumerate(
                [first_class, second_class],
                start=1,
            ):
                if not candidates:
                    self.class_runtimes.append(None)
                    self.class_static_rankings.append([])
                elif len(candidates) == 1:
                    self.class_runtimes.append(None)
                    self.class_static_rankings.append(
                        list(candidates)
                    )
                elif len(candidates) == 2:
                    self.class_runtimes.append(
                        HeadToHeadRuntimeState.create(
                            candidates[0],
                            candidates[1],
                            competition_id=self.competition_id,
                            reference_year=self.reference_year,
                            stage_id=self.stage_id,
                            stage_code=self.stage_code,
                            phase_code=phase_code,
                            group_id=self.gid,
                            group_name=self.group["group_name"],
                            match_no=class_no,
                            generation_seed=self.generation_seed,
                            match_resolver=self.match_resolver,
                            resolved_match_sink=self.match_simulation_results,
                        )
                    )
                    self.class_static_rankings.append([])
                else:
                    self.class_runtimes.append(
                        RoundRobinRuntimeState.create(
                            candidates,
                            competition_id=self.competition_id,
                            reference_year=self.reference_year,
                            stage_id=self.stage_id,
                            stage_code=self.stage_code,
                            phase_code=phase_code,
                            group_id=self.gid,
                            group_name=self.group["group_name"],
                            pool_no=100 + class_no,
                            generation_seed=self.generation_seed,
                            match_resolver=self.match_resolver,
                            resolved_match_sink=self.match_simulation_results,
                        )
                    )
                    self.class_static_rankings.append([])
            self.final_metadata = {
                "ranking_source": f"simulated_{model.lower()}",
                "subpool_count": len(self.subpools),
                "subpool_sizes": [
                    len(pool) for pool in self.subpools
                ],
                "standings": {
                    area_id: runtime.standings()
                    for area_id, runtime in zip(
                        self.subpool_area_ids,
                        self.primary,
                    )
                },
            }
            self.activated_secondary = True
            self._finalize_class_ranking_if_ready()
            return

        raise NotImplementedError(model)

    def _finish_primary_secondary_seed(
        self,
        extra: Sequence[str],
    ) -> None:
        primary_ranking = self.primary.ranking()
        top2 = primary_ranking[:2]
        extra_list = list(extra)
        self.final_ranking = (
            top2
            + extra_list
            + [
                team
                for team in primary_ranking
                if team not in set(top2 + extra_list)
            ]
        )

    def _class_runtime_complete(
        self,
        runtime: object | None,
    ) -> bool:
        return runtime is None or runtime.is_complete

    def _finalize_class_ranking_if_ready(self) -> None:
        if self.format_model_id not in {"FMT019", "FMT021"}:
            return
        if not self.class_runtimes:
            return
        if not all(
            self._class_runtime_complete(runtime)
            for runtime in self.class_runtimes
        ):
            return
        ranked: list[str] = []
        for runtime, static in zip(
            self.class_runtimes,
            self.class_static_rankings,
        ):
            if runtime is None:
                ranked.extend(static)
            else:
                ranked.extend(runtime.ranking())
        leftovers = [
            team
            for team in self.eligible_school_ids
            if team not in set(ranked)
        ]
        self.final_ranking = ranked + shuffled(
            leftovers,
            self.generation_seed,
            (
                f"{self.competition_id}:{self.stage_id}:"
                f"{self.gid}:{self.format_model_id}:leftover_order"
            ),
        )

    @property
    def is_complete(self) -> bool:
        if self.ranking_override or self.final_ranking:
            return True
        if not self.primary_complete:
            return False
        self._activate_dependent_phase()

        if self.format_model_id in {"FMT018", "FMT020"}:
            if self.secondary is None:
                return bool(self.final_ranking)
            if self.secondary.is_complete:
                self._finish_primary_secondary_seed(
                    self.secondary.winners()
                )
                return True
            return False

        if self.format_model_id in {"FMT019", "FMT021"}:
            self._finalize_class_ranking_if_ready()
            return bool(self.final_ranking)

        return bool(self.final_ranking)

    def _primary_runtimes(self) -> list[object]:
        if self.primary is None:
            return []
        return (
            list(self.primary)
            if isinstance(self.primary, list)
            else [self.primary]
        )

    def contains_match(self, match_id: str) -> bool:
        for runtime in self._primary_runtimes():
            if isinstance(runtime, BlockForestRuntimeState):
                if any(
                    match_id in block_runtime.matches
                    for block_runtime in runtime.block_runtimes
                ):
                    return True
            elif isinstance(runtime, HeadToHeadRuntimeState):
                if runtime.contains_match(match_id):
                    return True
            elif match_id in runtime.matches:
                return True

        self._activate_dependent_phase()
        if self.secondary is not None:
            if any(
                match_id in block_runtime.matches
                for block_runtime in self.secondary.block_runtimes
            ):
                return True
        for runtime in self.class_runtimes:
            if runtime is None:
                continue
            if isinstance(runtime, HeadToHeadRuntimeState):
                if runtime.contains_match(match_id):
                    return True
            elif match_id in runtime.matches:
                return True
        return False

    def ready_matches(self) -> list[dict]:
        if self.ranking_override or self.final_ranking:
            return []
        if not self.primary_complete:
            return [
                row
                for runtime in self._primary_runtimes()
                for row in runtime.ready_matches()
            ]

        self._activate_dependent_phase()
        if self.secondary is not None and not self.secondary.is_complete:
            return self.secondary.ready_matches()
        if self.class_runtimes:
            return [
                row
                for runtime in self.class_runtimes
                if runtime is not None
                for row in runtime.ready_matches()
            ]
        return []

    def resolve_match(self, match_id: str) -> MatchResolution:
        for runtime in self._primary_runtimes():
            if isinstance(runtime, BlockForestRuntimeState):
                if any(
                    match_id in block_runtime.matches
                    for block_runtime in runtime.block_runtimes
                ):
                    result = runtime.resolve_match(match_id)
                    self._activate_dependent_phase()
                    return result
            elif isinstance(runtime, HeadToHeadRuntimeState):
                if runtime.contains_match(match_id):
                    return runtime.resolve_match(match_id)
            elif match_id in runtime.matches:
                result = runtime.resolve_match(match_id)
                self._activate_dependent_phase()
                return result

        self._activate_dependent_phase()
        if self.secondary is not None:
            if any(
                match_id in block_runtime.matches
                for block_runtime in self.secondary.block_runtimes
            ):
                result = self.secondary.resolve_match(match_id)
                self.is_complete
                return result

        for runtime in self.class_runtimes:
            if runtime is None:
                continue
            if isinstance(runtime, HeadToHeadRuntimeState):
                if runtime.contains_match(match_id):
                    result = runtime.resolve_match(match_id)
                    self._finalize_class_ranking_if_ready()
                    return result
            elif match_id in runtime.matches:
                result = runtime.resolve_match(match_id)
                self._finalize_class_ranking_if_ready()
                return result
        raise KeyError(f"unknown match_id: {match_id}")

    def resolve_ready_round(self) -> list[MatchResolution]:
        if self.is_complete:
            return []
        if not self.primary_complete:
            results: list[MatchResolution] = []
            for runtime in self._primary_runtimes():
                if isinstance(runtime, RoundRobinRuntimeState):
                    for row in list(runtime.ready_matches()):
                        results.append(
                            runtime.resolve_match(row["match_id"])
                        )
                else:
                    results.extend(runtime.resolve_ready_round())
            self._activate_dependent_phase()
            return results

        self._activate_dependent_phase()
        if self.secondary is not None and not self.secondary.is_complete:
            results = self.secondary.resolve_ready_round()
            self.is_complete
            return results

        results = []
        for runtime in self.class_runtimes:
            if runtime is None or runtime.is_complete:
                continue
            if isinstance(runtime, HeadToHeadRuntimeState):
                results.append(
                    runtime.resolve_match(runtime.match.match_id)
                )
            elif isinstance(runtime, RoundRobinRuntimeState):
                for row in list(runtime.ready_matches()):
                    results.append(
                        runtime.resolve_match(row["match_id"])
                    )
            else:
                results.extend(runtime.resolve_ready_round())
        self._finalize_class_ranking_if_ready()
        return results

    def resolve_all(self) -> list[str]:
        if self.ranking_override:
            return self.ranking()
        for runtime in self._primary_runtimes():
            runtime.resolve_all()
        self._activate_dependent_phase()
        if self.secondary is not None:
            self.secondary.resolve_all()
        for runtime in self.class_runtimes:
            if runtime is not None:
                runtime.resolve_all()
        self.is_complete
        return self.ranking()

    def ranking(self) -> list[str]:
        if not self.is_complete:
            raise ValueError("seed ranking unavailable before completion")
        return list(self.final_ranking)

    def output_school_ids(self) -> list[str]:
        return self.ranking()[: self.output_slots]

    def metadata(self) -> dict:
        if not self.is_complete:
            raise ValueError("seed metadata unavailable before completion")
        return dict(self.final_metadata)

    def to_matches(self) -> list[Match]:
        matches: list[Match] = []
        for runtime in self._primary_runtimes():
            matches.extend(runtime.to_matches())
        if self.secondary is not None:
            matches.extend(self.secondary.to_matches())
        for runtime in self.class_runtimes:
            if runtime is not None:
                matches.extend(runtime.to_matches())
        return matches


@dataclass
class SeedEventRuntimeState:
    repo: DataRepository
    annual: AnnualCompetitionInput
    entrant_school_ids: List[str]
    stage: dict
    default_format_model_id: str
    group_runtimes: List[SeedGroupRuntimeState]
    group_models: Dict[str, str]
    forced_seed_assignments: List[SeedAssignment]
    bypass_seed_school_ids: List[str]
    match_simulation_results: Dict[str, dict]
    match_resolver: object | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        *,
        repo: DataRepository,
        annual: AnnualCompetitionInput,
        entrants: Sequence[str],
        stage: dict,
        match_resolver=None,
        resolved_match_sink: Dict[str, dict] | None = None,
    ) -> "SeedEventRuntimeState":
        assignment = repo.assignments_by_stage.get(stage["stage_id"])
        if not assignment:
            raise KeyError(f"no format assignment for {stage['stage_id']}")
        default_model = assignment["default_format_model_id"]
        entrant_list = list(entrants)
        entrant_set = set(entrant_list)
        sink = resolved_match_sink if resolved_match_sink is not None else {}

        bypass_seed_ids = list(
            dict.fromkeys(annual.seed_event_bypass_school_ids)
        )
        outside_bypass = set(bypass_seed_ids) - entrant_set
        if outside_bypass:
            raise ValueError(
                "seed-event bypass teams must be competition entrants: "
                f"{sorted(outside_bypass)}"
            )
        linked_rules = [
            row
            for row in repo.seed_rules(annual.competition_id)
            if row.get("linked_access_rule_id")
        ]
        linked_capacity = sum(
            int(row.get("seed_count") or 0)
            for row in linked_rules
        )
        if bypass_seed_ids and not linked_rules:
            raise ValueError(
                "seed_event_bypass_school_ids supplied but competition "
                "has no linked seed rule"
            )
        if len(bypass_seed_ids) > linked_capacity:
            raise ValueError(
                f"seed-event bypass count={len(bypass_seed_ids)} "
                f"exceeds linked seed capacity={linked_capacity}"
            )

        forced: list[SeedAssignment] = []
        pos = 0
        for rule in sorted(
            linked_rules,
            key=lambda row: (
                -int(row.get("priority") or 0),
                row["seed_rule_id"],
            ),
        ):
            count = int(rule.get("seed_count") or 0)
            for local_rank, school_id in enumerate(
                bypass_seed_ids[pos:pos + count],
                start=1,
            ):
                forced.append(
                    SeedAssignment(
                        school_id=school_id,
                        group_id="",
                        group_name="special_access",
                        seed_tier=rule.get("seed_tier", ""),
                        source_rank=local_rank,
                        seed_rule_id=rule["seed_rule_id"],
                        destination_stage=rule.get(
                            "destination_entry_stage",
                            "",
                        ),
                    )
                )
            pos += count

        runtimes = []
        group_models = {}
        bypass_set = set(bypass_seed_ids)
        for group in repo.groups_by_stage.get(stage["stage_id"], []):
            gid = group["stage_group_id"]
            override = repo.group_format.get(gid)
            model_id = (
                (override or {}).get("format_model_id")
                or default_model
            )
            group_models[gid] = model_id
            if model_id not in SEED_EVENT_MODELS:
                raise NotImplementedError(
                    f"seed handler does not support {model_id}"
                )

            supplied_entrants = annual.group_entrant_school_ids.get(gid)
            if supplied_entrants is not None:
                eligible = list(dict.fromkeys(supplied_entrants))
                outside = set(eligible) - entrant_set
                if outside:
                    raise ValueError(
                        f"{gid}: annual group entrants outside competition "
                        f"entrant set: {sorted(outside)}"
                    )
            else:
                eligible = sorted(
                    entrant_set
                    & repo.group_school_ids(group, annual.year)
                )
            eligible = [
                school_id
                for school_id in eligible
                if school_id not in bypass_set
            ]

            output_slots = repo.param(
                stage["stage_id"],
                "output_slots",
                gid,
                int(group.get("seed_slots_generated") or 0),
            )
            runtimes.append(
                SeedGroupRuntimeState.create(
                    repo=repo,
                    group=group,
                    eligible_school_ids=eligible,
                    output_slots=output_slots,
                    format_model_id=model_id,
                    competition_id=annual.competition_id,
                    reference_year=annual.year,
                    stage_id=stage["stage_id"],
                    stage_code=stage["stage_code"],
                    generation_seed=annual.rng_seed,
                    supplied_ranking=annual.group_rankings.get(gid),
                    match_resolver=match_resolver,
                    resolved_match_sink=sink,
                )
            )

        return cls(
            repo=repo,
            annual=annual,
            entrant_school_ids=entrant_list,
            stage=dict(stage),
            default_format_model_id=default_model,
            group_runtimes=runtimes,
            group_models=group_models,
            forced_seed_assignments=forced,
            bypass_seed_school_ids=bypass_seed_ids,
            match_simulation_results=sink,
            match_resolver=match_resolver,
        )

    @property
    def is_complete(self) -> bool:
        return all(
            runtime.is_complete
            for runtime in self.group_runtimes
        )

    def ready_matches(self) -> list[dict]:
        return [
            row
            for runtime in self.group_runtimes
            for row in runtime.ready_matches()
        ]

    def resolve_match(self, match_id: str) -> MatchResolution:
        for runtime in self.group_runtimes:
            if runtime.contains_match(match_id):
                return runtime.resolve_match(match_id)
        raise KeyError(f"unknown seed-event match_id: {match_id}")

    def resolve_ready_round(self) -> list[MatchResolution]:
        results: list[MatchResolution] = []
        for runtime in self.group_runtimes:
            results.extend(runtime.resolve_ready_round())
        return results

    def resolve_all(self) -> list[SeedAssignment]:
        for runtime in self.group_runtimes:
            runtime.resolve_all()
        return self.seed_assignments()

    def _seed_assignments_from_rules(
        self,
        group: dict,
        ranked: Sequence[str],
    ) -> list[SeedAssignment]:
        area_ids = {
            item
            for item in group.get("source_area_ids", "").split(";")
            if item
        }
        rules = []
        for rule in self.repo.seed_rules_by_comp.get(
            self.annual.competition_id,
            [],
        ):
            rule_areas = {
                item
                for item in rule.get("source_area_ids", "").split(";")
                if item
            }
            if area_ids & rule_areas:
                rules.append(rule)

        output = []
        consumed = 0
        selector_order = {
            "rank_1": 1,
            "rank_2": 2,
            "rank_3_cohort": 3,
            "remaining_official_seed_qualifiers": 3,
        }
        rules.sort(
            key=lambda rule: (
                selector_order.get(
                    rule.get("source_result_selector", ""),
                    99,
                ),
                -int(rule.get("priority") or 0),
                rule["seed_rule_id"],
            )
        )
        for rule in rules:
            count = int(rule.get("seed_count") or 0)
            selector = rule.get("source_result_selector", "")
            if selector == "rank_1":
                start = 0
            elif selector == "rank_2":
                start = 1
            elif selector == "rank_3_cohort":
                start = 2
            else:
                start = consumed
            picks = list(ranked[start:start + count])
            for idx, school_id in enumerate(
                picks,
                start=start + 1,
            ):
                output.append(
                    SeedAssignment(
                        school_id=school_id,
                        group_id=group["stage_group_id"],
                        group_name=group["group_name"],
                        seed_tier=rule.get("seed_tier", ""),
                        source_rank=idx,
                        seed_rule_id=rule["seed_rule_id"],
                        destination_stage=rule.get(
                            "destination_entry_stage",
                            "",
                        ),
                    )
                )
            consumed = max(consumed, start + count)
        return output

    def seed_assignments(self) -> list[SeedAssignment]:
        if not self.is_complete:
            raise ValueError(
                "seed assignments unavailable before SEED_EVENT completion"
            )
        all_assignments = []
        for runtime in self.group_runtimes:
            all_assignments.extend(
                self._seed_assignments_from_rules(
                    runtime.group,
                    runtime.output_school_ids(),
                )
            )
        all_assignments.extend(self.forced_seed_assignments)

        dedup: Dict[str, SeedAssignment] = {}
        for assignment in sorted(
            all_assignments,
            key=lambda item: (
                item.source_rank,
                item.seed_rule_id,
            ),
        ):
            dedup.setdefault(
                assignment.school_id,
                assignment,
            )
        output = list(dedup.values())
        output.sort(
            key=lambda item: (
                item.group_name,
                item.source_rank,
                item.school_id,
            )
        )

        expected = (
            sum(
                int(runtime.group.get("seed_slots_generated") or 0)
                for runtime in self.group_runtimes
            )
            + len(self.forced_seed_assignments)
        )
        if len(output) != expected:
            raise AssertionError(
                f"seed output count {len(output)} "
                f"!= expected group slots {expected}"
            )
        return output

    def stage_execution(self) -> StageExecution:
        if not self.is_complete:
            raise ValueError(
                "SEED_EVENT StageExecution unavailable before completion"
            )
        assignments = self.seed_assignments()
        group_outputs = {
            runtime.gid: runtime.output_school_ids()
            for runtime in self.group_runtimes
        }
        group_metadata = {
            runtime.gid: runtime.metadata()
            for runtime in self.group_runtimes
        }
        matches = [
            match
            for runtime in self.group_runtimes
            for match in runtime.to_matches()
        ]
        return StageExecution(
            stage_id=self.stage["stage_id"],
            stage_code=self.stage["stage_code"],
            format_model_id=self.default_format_model_id,
            entrant_school_ids=list(self.entrant_school_ids),
            output_school_ids=[
                assignment.school_id
                for assignment in assignments
            ],
            matches=matches,
            metadata={
                "group_count": len(self.group_runtimes),
                "seed_count": len(assignments),
                "group_outputs": group_outputs,
                "group_models": dict(self.group_models),
                "group_metadata": group_metadata,
                "annual_ranking_override_groups": sorted(
                    self.annual.group_rankings
                ),
                "seed_event_bypass_school_ids": list(
                    self.bypass_seed_school_ids
                ),
                "forced_seed_count": len(
                    self.forced_seed_assignments
                ),
            },
        )
