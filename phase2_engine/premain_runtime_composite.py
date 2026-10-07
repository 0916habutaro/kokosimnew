from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .brackets import balanced_partition
from .models import Match, MatchResolution, StageExecution
from .premain_runtime_forest import BlockForestRuntimeState
from .premain_runtime_round_robin import RoundRobinRuntimeState
from .premain_runtime_single_elim import SingleEliminationRuntimeState
from .repository import DataRepository


COMPOSITE_QUALIFIER_MODELS = {
    "FMT002",
    "FMT003",
    "FMT004",
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
}


@dataclass
class _PhaseRecord:
    key: str
    kind: str
    runtimes: List[object]
    partitions: List[List[str]] = field(default_factory=list)
    suffixes: List[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return all(runtime.is_complete for runtime in self.runtimes)

    def contains_match(self, match_id: str) -> bool:
        return any(match_id in runtime.matches for runtime in self.runtimes)

    def ready_matches(self) -> list[dict]:
        return [
            row
            for runtime in self.runtimes
            for row in runtime.ready_matches()
        ]

    def resolve_match(self, match_id: str) -> MatchResolution:
        for runtime in self.runtimes:
            if match_id in runtime.matches:
                return runtime.resolve_match(match_id)
        raise KeyError(f"unknown match_id: {match_id}")

    def resolve_ready_round(self) -> list[MatchResolution]:
        results: list[MatchResolution] = []
        for runtime in self.runtimes:
            if isinstance(runtime, RoundRobinRuntimeState):
                for row in list(runtime.ready_matches()):
                    results.append(runtime.resolve_match(row["match_id"]))
            else:
                results.extend(runtime.resolve_ready_round())
        return results

    def resolve_all(self) -> None:
        # Keep legacy resolver-call order: phase order, then block/pool order.
        for runtime in self.runtimes:
            runtime.resolve_all()

    def to_matches(self, *, base_group_id: str, group_name: str) -> list[Match]:
        matches: list[Match] = []
        for idx, runtime in enumerate(self.runtimes):
            rows = runtime.to_matches()
            suffix = self.suffixes[idx] if idx < len(self.suffixes) else ""
            if suffix:
                for match in rows:
                    match.group_id = base_group_id
                    match.group_name = group_name
                    match.metadata["subgroup"] = suffix.lstrip("-")
            matches.extend(rows)
        return matches


@dataclass
class CompositeQualifierGroupRuntime:
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
    phases: List[_PhaseRecord] = field(default_factory=list)
    step: str = "init"
    finished: bool = False
    outputs: List[str] = field(default_factory=list)
    final_metadata: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)

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
        match_resolver=None,
        resolved_match_sink: Dict[str, dict] | None = None,
    ) -> "CompositeQualifierGroupRuntime":
        if format_model_id not in COMPOSITE_QUALIFIER_MODELS:
            raise NotImplementedError(format_model_id)
        eligible = list(eligible_school_ids)
        if output_slots <= 0 or output_slots > len(eligible):
            raise ValueError(
                f"{group['group_name']}: {format_model_id} "
                f"output_slots={output_slots} entrants={len(eligible)}"
            )
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
            match_simulation_results=(
                resolved_match_sink if resolved_match_sink is not None else {}
            ),
        )
        runtime._advance_until_waiting()
        return runtime

    @property
    def gid(self) -> str:
        return self.group["stage_group_id"]

    def _param(self, name: str, default=None):
        return self.repo.param(self.stage_id, name, self.gid, default)

    def _add_forest(
        self,
        key: str,
        teams: Sequence[str],
        slots: int,
        phase_code: str,
    ) -> _PhaseRecord:
        items = list(teams)
        if slots < 0 or slots > len(items):
            raise ValueError(
                f"{self.group['group_name']}: phase {phase_code} "
                f"slots={slots} entrants={len(items)}"
            )
        if slots == 0:
            record = _PhaseRecord(key=key, kind="forest", runtimes=[], partitions=[])
        else:
            forest = BlockForestRuntimeState.create(
                items,
                block_count=slots,
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
            record = _PhaseRecord(
                key=key,
                kind="forest",
                runtimes=[forest],
                partitions=[list(block) for block in forest.blocks],
            )
        self.phases.append(record)
        return record

    def _add_rank(
        self,
        key: str,
        teams: Sequence[str],
        phase_code: str,
        *,
        suffix: str = "",
    ) -> _PhaseRecord:
        runtime = SingleEliminationRuntimeState.create(
            list(teams),
            competition_id=self.competition_id,
            reference_year=self.reference_year,
            stage_id=self.stage_id,
            stage_code=self.stage_code,
            phase_code=phase_code,
            group_id=self.gid + suffix,
            group_name=self.group["group_name"],
            generation_seed=self.generation_seed,
            match_resolver=self.match_resolver,
            resolved_match_sink=self.match_simulation_results,
        )
        record = _PhaseRecord(
            key=key,
            kind="rank",
            runtimes=[runtime],
            partitions=[list(teams)],
            suffixes=[suffix],
        )
        self.phases.append(record)
        return record

    def _add_multi_rank(
        self,
        key: str,
        blocks: Sequence[Sequence[str]],
        phase_code: str,
    ) -> _PhaseRecord:
        runtimes = []
        suffixes = []
        for idx, block in enumerate(blocks, start=1):
            suffix = f"-PB{idx:02d}"
            runtimes.append(
                SingleEliminationRuntimeState.create(
                    list(block),
                    competition_id=self.competition_id,
                    reference_year=self.reference_year,
                    stage_id=self.stage_id,
                    stage_code=self.stage_code,
                    phase_code=phase_code,
                    group_id=self.gid + suffix,
                    group_name=self.group["group_name"],
                    generation_seed=self.generation_seed,
                    match_resolver=self.match_resolver,
                    resolved_match_sink=self.match_simulation_results,
                )
            )
            suffixes.append(suffix)
        record = _PhaseRecord(
            key=key,
            kind="multi_rank",
            runtimes=runtimes,
            partitions=[list(block) for block in blocks],
            suffixes=suffixes,
        )
        self.phases.append(record)
        return record

    def _add_round_robin(
        self,
        key: str,
        teams: Sequence[str],
        pool_count: int,
        phase_code: str,
    ) -> _PhaseRecord:
        items = list(teams)
        if pool_count <= 0 or pool_count > len(items):
            raise ValueError(
                f"{self.group['group_name']}: invalid pool_count={pool_count}"
            )
        pools = balanced_partition(
            items,
            pool_count,
            base_seed=self.generation_seed,
            namespace=(
                f"{self.competition_id}:{self.stage_id}:{self.gid}:"
                f"{phase_code}:pool_partition"
            ),
        )
        runtimes = [
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
            for pool_no, pool in enumerate(pools, start=1)
        ]
        record = _PhaseRecord(
            key=key,
            kind="round_robin",
            runtimes=runtimes,
            partitions=[list(pool) for pool in pools],
        )
        self.phases.append(record)
        return record

    def _phase(self, key: str) -> _PhaseRecord:
        for phase in self.phases:
            if phase.key == key:
                return phase
        raise KeyError(key)

    def _active_phase(self) -> _PhaseRecord | None:
        if not self.phases:
            return None
        phase = self.phases[-1]
        return None if self.finished else phase

    @staticmethod
    def _forest_winners(phase: _PhaseRecord) -> list[str]:
        if not phase.runtimes:
            return []
        return phase.runtimes[0].winners()

    @staticmethod
    def _rank(phase: _PhaseRecord) -> list[str]:
        return phase.runtimes[0].ranking()

    @staticmethod
    def _rankings(phase: _PhaseRecord) -> list[list[str]]:
        return [runtime.ranking() for runtime in phase.runtimes]

    @staticmethod
    def _standings(phase: _PhaseRecord) -> dict:
        return {
            str(index): runtime.standings()
            for index, runtime in enumerate(phase.runtimes, start=1)
        }

    @staticmethod
    def _dedup(items: Sequence[str]) -> list[str]:
        return list(dict.fromkeys(items))

    def _finish(self, outputs: Sequence[str], metadata: dict) -> None:
        self.outputs = list(outputs)
        self.final_metadata = {
            "entrant_count": len(self.eligible_school_ids),
            "output_slots": self.output_slots,
            "model_id": self.format_model_id,
            **metadata,
        }
        self.finished = True
        self.step = "done"

    def _advance_until_waiting(self) -> None:
        while not self.finished:
            active = self._active_phase()
            if active is not None and not active.is_complete:
                return
            previous = self.step
            self._advance_once()
            if self.finished:
                return
            active = self._active_phase()
            if active is not None and not active.is_complete:
                return
            if self.step == previous and active is None:
                raise RuntimeError(
                    f"{self.format_model_id} runtime failed to advance from {self.step}"
                )

    def _advance_once(self) -> None:
        model = self.format_model_id
        if model in {"FMT002", "FMT003", "FMT016", "FMT025"}:
            self._advance_primary_secondary()
        elif model == "FMT004":
            self._advance_fmt004()
        elif model == "FMT007":
            self._advance_fmt007()
        elif model == "FMT008":
            self._advance_fmt008()
        elif model == "FMT010":
            self._advance_fmt010()
        elif model in {"FMT011", "FMT013"}:
            self._advance_fmt011_013()
        elif model == "FMT012":
            self._advance_fmt012()
        elif model in {"FMT014", "FMT015"}:
            self._advance_fmt014_015()
        elif model == "FMT017":
            self._advance_fmt017()
        else:
            raise NotImplementedError(model)

    def _advance_primary_secondary(self) -> None:
        if self.step == "init":
            if self.format_model_id in {"FMT003", "FMT016"}:
                primary_slots = (
                    self.output_slots
                    if self.output_slots == 1
                    else self.output_slots - 1
                )
            else:
                primary_slots = max(1, (self.output_slots + 1) // 2)
            self.state["primary_slots_requested"] = primary_slots
            self._add_forest(
                "primary",
                self.eligible_school_ids,
                primary_slots,
                "PRIMARY",
            )
            self.step = "primary"
            return

        if self.step == "primary":
            primary_phase = self._phase("primary")
            primary = self._forest_winners(primary_phase)
            self.state["primary"] = primary
            remaining = [
                team
                for team in self.eligible_school_ids
                if team not in set(primary)
            ]
            secondary_slots = self.output_slots - len(primary)
            self.state["secondary_slots_requested"] = secondary_slots
            if secondary_slots:
                phase_code = (
                    "SECONDARY"
                    if self.format_model_id in {"FMT003", "FMT016"}
                    else "REPECHAGE"
                )
                self._add_forest(
                    "secondary",
                    remaining,
                    secondary_slots,
                    phase_code,
                )
                self.step = "secondary"
                return
            self.state["secondary"] = []
            self._after_primary_secondary()
            return

        if self.step == "secondary":
            self.state["secondary"] = self._forest_winners(
                self._phase("secondary")
            )
            self._after_primary_secondary()
            return

        if self.step == "ranking":
            ranking = self._rank(self._phase("ranking"))
            self._finish(
                ranking[: self.output_slots],
                self._primary_secondary_metadata(),
            )

    def _primary_secondary_metadata(self) -> dict:
        primary_phase = self._phase("primary")
        secondary_phase = next(
            (phase for phase in self.phases if phase.key == "secondary"),
            None,
        )
        return {
            "primary_slots": len(self.state.get("primary", [])),
            "secondary_or_repechage_slots": len(
                self.state.get("secondary", [])
            ),
            "primary_block_sizes": [
                len(block) for block in primary_phase.partitions
            ],
            "secondary_block_sizes": (
                [len(block) for block in secondary_phase.partitions]
                if secondary_phase is not None
                else []
            ),
            "annual_phase_split_policy": (
                "deterministic_simulation_from_total_quota"
            ),
        }

    def _after_primary_secondary(self) -> None:
        out = list(self.state["primary"]) + list(self.state["secondary"])
        if self.format_model_id == "FMT025" and len(out) > 1:
            self._add_rank(
                "ranking",
                out,
                "RANKING",
                suffix="-RANK",
            )
            self.step = "ranking"
            return
        self._finish(out, self._primary_secondary_metadata())

    def _advance_fmt004(self) -> None:
        if self.step == "init":
            self.state["protected_slots"] = self._param(
                "protected_primary_slots", 4
            )
            self.state["secondary_slots"] = self._param(
                "secondary_output_slots",
                self.output_slots - self.state["protected_slots"],
            )
            self._add_rank(
                "primary_rank",
                self.eligible_school_ids,
                "PRIMARY_TOP4",
            )
            self.step = "primary_rank"
            return

        if self.step == "primary_rank":
            ranking = self._rank(self._phase("primary_rank"))
            protected = ranking[: self.state["protected_slots"]]
            remaining = [
                team
                for team in self.eligible_school_ids
                if team not in set(protected)
            ]
            self.state["protected"] = protected
            self._add_forest(
                "secondary",
                remaining,
                self.state["secondary_slots"],
                "SECONDARY",
            )
            self.step = "secondary"
            return

        if self.step == "secondary":
            secondary = self._forest_winners(self._phase("secondary"))
            protected = self.state["protected"]
            self._finish(
                protected + secondary,
                {
                    "protected_count": len(protected),
                    "protected_ranking": protected,
                    "secondary_count": len(secondary),
                    "secondary_block_sizes": [
                        len(block)
                        for block in self._phase("secondary").partitions
                    ],
                },
            )

    def _advance_fmt007(self) -> None:
        if self.step == "init":
            self._add_rank(
                "main_ko",
                self.eligible_school_ids,
                "MAIN_KO",
            )
            self.step = "main_ko"
            return
        ranking = self._rank(self._phase("main_ko"))
        out = ranking[: self.output_slots]
        self._finish(
            out,
            {
                "qualified_ranking": out,
                "ranking_phase_simulated": True,
            },
        )

    def _advance_fmt008(self) -> None:
        if self.step == "init":
            self.state["guaranteed"] = self._param(
                "guaranteed_qf_winner_slots", 4
            )
            self.state["rep_slots"] = self._param(
                "representative_decider_slots",
                self.output_slots - self.state["guaranteed"],
            )
            self._add_rank(
                "main_ko",
                self.eligible_school_ids,
                "MAIN_KO",
            )
            self.step = "main_ko"
            return

        if self.step == "main_ko":
            ranking = self._rank(self._phase("main_ko"))
            direct = ranking[: self.state["guaranteed"]]
            rep_slots = self.state["rep_slots"]
            candidates = ranking[
                self.state["guaranteed"]:
                self.state["guaranteed"] + max(2 * rep_slots, rep_slots)
            ]
            if len(candidates) < rep_slots:
                candidates = [
                    team
                    for team in self.eligible_school_ids
                    if team not in set(direct)
                ]
            self.state["direct"] = direct
            self.state["candidates"] = candidates
            self._add_forest(
                "rep_deciders",
                candidates,
                rep_slots,
                "REP_DECIDERS",
            )
            self.step = "rep_deciders"
            return

        extra = self._forest_winners(self._phase("rep_deciders"))
        direct = self.state["direct"]
        self._finish(
            direct + extra,
            {
                "guaranteed_slots": len(direct),
                "representative_decider_slots": len(extra),
                "representative_candidate_count": len(
                    self.state["candidates"]
                ),
                "representative_block_sizes": [
                    len(block)
                    for block in self._phase("rep_deciders").partitions
                ],
                "top4_ranking": direct,
            },
        )

    def _advance_fmt010(self) -> None:
        if self.step == "init":
            min_blocks = (self.output_slots + 1) // 2
            block_count = min(
                len(self.eligible_school_ids) // 2,
                min_blocks + 1,
            )
            block_count = max(min_blocks, block_count)
            blocks = balanced_partition(
                self.eligible_school_ids,
                block_count,
                base_seed=self.generation_seed,
                namespace=(
                    f"{self.competition_id}:{self.stage_id}:"
                    f"{self.gid}:PRIMARY_BLOCKS"
                ),
            )
            self.state["block_count"] = block_count
            self._add_multi_rank(
                "primary_blocks",
                blocks,
                "PRIMARY_BLOCKS",
            )
            self.step = "primary_blocks"
            return

        if self.step == "primary_blocks":
            rankings = self._rankings(self._phase("primary_blocks"))
            survivors = [
                team
                for ranking in rankings
                for team in ranking[: min(2, len(ranking))]
            ]
            if len(survivors) < self.output_slots:
                raise AssertionError(
                    f"{self.group['group_name']}: "
                    "primary rank1/2 cohort smaller than quota"
                )
            self.state["survivors"] = survivors
            self._add_forest(
                "secondary",
                survivors,
                self.output_slots,
                "SECONDARY",
            )
            self.step = "secondary"
            return

        out = self._forest_winners(self._phase("secondary"))
        primary_phase = self._phase("primary_blocks")
        self._finish(
            out,
            {
                "primary_block_count": self.state["block_count"],
                "primary_block_sizes": [
                    len(block) for block in primary_phase.partitions
                ],
                "primary_rank1_rank2_count": len(
                    self.state["survivors"]
                ),
                "secondary_block_sizes": [
                    len(block)
                    for block in self._phase("secondary").partitions
                ],
            },
        )

    def _advance_fmt011_013(self) -> None:
        if self.step == "init":
            if self.format_model_id == "FMT013":
                pool_count = self._param("primary_pool_count", 4)
                advance_per_pool = self._param("advance_per_pool", 2)
            else:
                pool_count = min(
                    max(1, (self.output_slots + 1) // 2 + 1),
                    max(1, len(self.eligible_school_ids) // 2),
                )
                advance_per_pool = 2
            self.state["pool_count"] = pool_count
            self.state["advance_per_pool"] = advance_per_pool
            self._add_round_robin(
                "primary_league",
                self.eligible_school_ids,
                pool_count,
                "PRIMARY_LEAGUE",
            )
            self.step = "primary_league"
            return

        if self.step == "primary_league":
            phase = self._phase("primary_league")
            rankings = self._rankings(phase)
            advance = self.state["advance_per_pool"]
            survivors = []
            for ranking in rankings:
                survivors.extend(
                    ranking[: min(advance, len(ranking))]
                )
            if len(survivors) < self.output_slots:
                leftovers = [
                    team
                    for ranking in rankings
                    for team in ranking[advance:]
                ]
                survivors.extend(
                    leftovers[: self.output_slots - len(survivors)]
                )
            self.state["survivors"] = survivors
            self.state["standings"] = self._standings(phase)
            self._add_forest(
                "secondary",
                survivors,
                self.output_slots,
                "SECONDARY",
            )
            self.step = "secondary"
            return

        out = self._forest_winners(self._phase("secondary"))
        league = self._phase("primary_league")
        self._finish(
            out,
            {
                "primary_pool_count": self.state["pool_count"],
                "pool_sizes": [
                    len(pool) for pool in league.partitions
                ],
                "advance_per_pool": self.state["advance_per_pool"],
                "secondary_entrant_count": len(
                    self.state["survivors"]
                ),
                "secondary_block_sizes": [
                    len(block)
                    for block in self._phase("secondary").partitions
                ],
                "standings": self.state["standings"],
            },
        )

    def _advance_fmt012(self) -> None:
        if self.step == "init":
            zone_count = min(
                len(self.eligible_school_ids),
                self.output_slots + max(2, self.output_slots // 3),
            )
            self.state["zone_count"] = zone_count
            self._add_forest(
                "primary_zones",
                self.eligible_school_ids,
                zone_count,
                "PRIMARY_ZONES",
            )
            self.step = "primary_zones"
            return

        if self.step == "primary_zones":
            winners = self._forest_winners(
                self._phase("primary_zones")
            )
            self.state["zone_winners"] = winners
            self._add_forest(
                "secondary",
                winners,
                self.output_slots,
                "SECONDARY",
            )
            self.step = "secondary"
            return

        out = self._forest_winners(self._phase("secondary"))
        self._finish(
            out,
            {
                "zone_count": self.state["zone_count"],
                "zone_sizes": [
                    len(block)
                    for block in self._phase("primary_zones").partitions
                ],
                "secondary_entrant_count": len(
                    self.state["zone_winners"]
                ),
                "secondary_block_sizes": [
                    len(block)
                    for block in self._phase("secondary").partitions
                ],
            },
        )

    def _advance_fmt014_015(self) -> None:
        if self.step == "init":
            if self.format_model_id == "FMT014":
                primary_slots = min(
                    len(self.eligible_school_ids),
                    self.output_slots + max(2, self.output_slots // 2),
                )
            else:
                primary_slots = max(
                    1,
                    self.output_slots - max(2, self.output_slots // 3),
                )
            self.state["primary_slots"] = primary_slots
            self._add_forest(
                "primary",
                self.eligible_school_ids,
                primary_slots,
                "PRIMARY",
            )
            self.step = "primary"
            return

        if self.step == "primary":
            primary = self._forest_winners(self._phase("primary"))
            self.state["primary"] = primary
            if self.format_model_id == "FMT014":
                self.state["repechage"] = []
                self.state["secondary_entrants"] = list(primary)
                self._add_forest(
                    "secondary",
                    primary,
                    self.output_slots,
                    "SECONDARY",
                )
                self.step = "secondary"
                return

            remaining = [
                team
                for team in self.eligible_school_ids
                if team not in set(primary)
            ]
            desired_rep = min(
                len(remaining),
                self.output_slots - len(primary)
                + max(2, self.output_slots // 4),
            )
            self.state["desired_rep"] = desired_rep
            self._add_forest(
                "primary_repechage",
                remaining,
                desired_rep,
                "PRIMARY_REPECHAGE",
            )
            self.step = "primary_repechage"
            return

        if self.step == "primary_repechage":
            repechage = self._forest_winners(
                self._phase("primary_repechage")
            )
            self.state["repechage"] = repechage
            entrants = self.state["primary"] + repechage
            if len(entrants) < self.output_slots:
                raise AssertionError(
                    f"{self.group['group_name']}: "
                    "secondary cohort smaller than quota"
                )
            self.state["secondary_entrants"] = entrants
            self._add_forest(
                "secondary",
                entrants,
                self.output_slots,
                "SECONDARY",
            )
            self.step = "secondary"
            return

        out = self._forest_winners(self._phase("secondary"))
        rep_phase = next(
            (
                phase
                for phase in self.phases
                if phase.key == "primary_repechage"
            ),
            None,
        )
        self._finish(
            out,
            {
                "primary_survivor_count": len(self.state["primary"]),
                "primary_block_sizes": [
                    len(block)
                    for block in self._phase("primary").partitions
                ],
                "repechage_survivor_count": len(
                    self.state.get("repechage", [])
                ),
                "repechage_block_sizes": (
                    [len(block) for block in rep_phase.partitions]
                    if rep_phase is not None
                    else []
                ),
                "secondary_entrant_count": len(
                    self.state["secondary_entrants"]
                ),
                "secondary_block_sizes": [
                    len(block)
                    for block in self._phase("secondary").partitions
                ],
            },
        )

    def _advance_fmt017(self) -> None:
        if self.step == "init":
            zone_count = self._param("zone_count")
            first_slots = self._param(
                "first_place_representative_slots"
            )
            second_slots = self._param(
                "second_place_representative_slots"
            )
            first_playoff = self._param(
                "first_place_playoff_enabled", False
            )
            self.state.update(
                {
                    "zone_count": zone_count,
                    "first_slots": first_slots,
                    "second_slots": second_slots,
                    "first_playoff": first_playoff,
                }
            )
            self._add_round_robin(
                "zone_rr",
                self.eligible_school_ids,
                zone_count,
                "ZONE_RR",
            )
            self.step = "zone_rr"
            return

        if self.step == "zone_rr":
            zone_phase = self._phase("zone_rr")
            rankings = self._rankings(zone_phase)
            zone_winners = [
                ranking[0] for ranking in rankings if ranking
            ]
            zone_runners = [
                ranking[1]
                for ranking in rankings
                if len(ranking) > 1
            ]
            self.state["zone_winners"] = zone_winners
            self.state["zone_runners"] = zone_runners
            self.state["standings"] = self._standings(zone_phase)

            if (
                self.state["first_playoff"]
                or self.state["first_slots"] < len(zone_winners)
            ):
                self._add_forest(
                    "first_place_playoff",
                    zone_winners,
                    self.state["first_slots"],
                    "FIRST_PLACE_PLAYOFF",
                )
                self.step = "first_place_playoff"
                return

            first_reps = zone_winners[: self.state["first_slots"]]
            first_losers = zone_winners[self.state["first_slots"]:]
            self.state["first_reps"] = first_reps
            self.state["first_losers"] = first_losers
            self._activate_fmt017_second()
            return

        if self.step == "first_place_playoff":
            first_reps = self._forest_winners(
                self._phase("first_place_playoff")
            )
            self.state["first_reps"] = first_reps
            self.state["first_losers"] = [
                team
                for team in self.state["zone_winners"]
                if team not in set(first_reps)
            ]
            self._activate_fmt017_second()
            return

        second_reps = self._forest_winners(
            self._phase("second_place_playoff")
        )
        first_reps = self.state["first_reps"]
        out = first_reps + second_reps
        if len(out) != self.output_slots:
            raise AssertionError(
                f"{self.group['group_name']}: "
                f"FMT017 outputs={len(out)} != {self.output_slots}"
            )
        first_phase = next(
            (
                phase
                for phase in self.phases
                if phase.key == "first_place_playoff"
            ),
            None,
        )
        self._finish(
            out,
            {
                "zone_count": self.state["zone_count"],
                "zone_sizes": [
                    len(pool)
                    for pool in self._phase("zone_rr").partitions
                ],
                "first_place_slots": len(first_reps),
                "first_place_playoff": bool(
                    self.state["first_playoff"]
                ),
                "first_place_playoff_block_sizes": (
                    [len(block) for block in first_phase.partitions]
                    if first_phase is not None
                    else []
                ),
                "second_place_candidate_count": len(
                    self.state["second_candidates"]
                ),
                "second_place_slots": len(second_reps),
                "second_place_block_sizes": [
                    len(block)
                    for block in self._phase(
                        "second_place_playoff"
                    ).partitions
                ],
                "standings": self.state["standings"],
            },
        )

    def _activate_fmt017_second(self) -> None:
        candidates = self._dedup(
            self.state["zone_runners"] + self.state["first_losers"]
        )
        self.state["second_candidates"] = candidates
        self._add_forest(
            "second_place_playoff",
            candidates,
            self.state["second_slots"],
            "SECOND_PLACE_PLAYOFF",
        )
        self.step = "second_place_playoff"

    @property
    def is_complete(self) -> bool:
        self._advance_until_waiting()
        return self.finished

    def contains_match(self, match_id: str) -> bool:
        return any(
            phase.contains_match(match_id)
            for phase in self.phases
        )

    def ready_matches(self) -> list[dict]:
        self._advance_until_waiting()
        if self.finished:
            return []
        active = self._active_phase()
        return active.ready_matches() if active is not None else []

    def resolve_match(self, match_id: str) -> MatchResolution:
        self._advance_until_waiting()
        if self.finished:
            raise ValueError("qualifier group is already complete")
        active = self._active_phase()
        if active is None or not active.contains_match(match_id):
            raise KeyError(f"match is not active: {match_id}")
        result = active.resolve_match(match_id)
        self._advance_until_waiting()
        return result

    def resolve_ready_round(self) -> list[MatchResolution]:
        self._advance_until_waiting()
        if self.finished:
            return []
        active = self._active_phase()
        if active is None:
            return []
        results = active.resolve_ready_round()
        self._advance_until_waiting()
        return results

    def resolve_all(self) -> list[str]:
        while not self.is_complete:
            active = self._active_phase()
            if active is None:
                raise RuntimeError(
                    f"{self.format_model_id} runtime stalled"
                )
            active.resolve_all()
            self._advance_until_waiting()
        return self.output_school_ids()

    def output_school_ids(self) -> list[str]:
        if not self.is_complete:
            raise ValueError("qualifier output unavailable before completion")
        return list(self.outputs)

    def metadata(self) -> dict:
        if not self.is_complete:
            raise ValueError("qualifier metadata unavailable before completion")
        return dict(self.final_metadata)

    def to_matches(self) -> list[Match]:
        matches: list[Match] = []
        for phase in self.phases:
            matches.extend(
                phase.to_matches(
                    base_group_id=self.gid,
                    group_name=self.group["group_name"],
                )
            )
        return matches


@dataclass
class Fmt005GlobalQualifierRuntime:
    repo: DataRepository
    entrant_school_ids: List[str]
    output_slots: int
    primary_slots: int
    repechage_slots: int
    competition_id: str
    reference_year: int
    stage: dict
    generation_seed: int
    match_resolver: object | None = field(default=None, repr=False)
    match_simulation_results: Dict[str, dict] = field(default_factory=dict)
    primary: BlockForestRuntimeState | None = None
    repechage: BlockForestRuntimeState | None = None

    @classmethod
    def create(
        cls,
        *,
        repo: DataRepository,
        entrant_school_ids: Sequence[str],
        competition_id: str,
        reference_year: int,
        stage: dict,
        generation_seed: int,
        match_resolver=None,
        resolved_match_sink: Dict[str, dict] | None = None,
    ) -> "Fmt005GlobalQualifierRuntime":
        primary_slots = repo.param(
            stage["stage_id"], "primary_qualifier_slots"
        )
        repechage_slots = repo.param(
            stage["stage_id"], "repechage_qualifier_slots"
        )
        if not primary_slots or not repechage_slots:
            raise ValueError(
                "FMT005 requires primary_qualifier_slots "
                "and repechage_qualifier_slots"
            )
        sink = (
            resolved_match_sink
            if resolved_match_sink is not None
            else {}
        )
        runtime = cls(
            repo=repo,
            entrant_school_ids=list(entrant_school_ids),
            output_slots=primary_slots + repechage_slots,
            primary_slots=primary_slots,
            repechage_slots=repechage_slots,
            competition_id=competition_id,
            reference_year=reference_year,
            stage=dict(stage),
            generation_seed=generation_seed,
            match_resolver=match_resolver,
            match_simulation_results=sink,
        )
        runtime.primary = BlockForestRuntimeState.create(
            runtime.entrant_school_ids,
            block_count=primary_slots,
            competition_id=competition_id,
            reference_year=reference_year,
            stage_id=stage["stage_id"],
            stage_code=stage["stage_code"],
            phase_code="PRIMARY_GLOBAL",
            group_id="",
            group_name="全県",
            generation_seed=generation_seed,
            match_resolver=match_resolver,
            resolved_match_sink=sink,
        )
        return runtime

    @property
    def format_model_id(self) -> str:
        return "FMT005"

    @property
    def is_complete(self) -> bool:
        if not self.primary.is_complete:
            return False
        self._activate_repechage()
        return self.repechage.is_complete

    def _activate_repechage(self) -> None:
        if self.repechage is not None or not self.primary.is_complete:
            return
        primary = self.primary.winners()
        nonqualifiers = [
            team
            for team in self.entrant_school_ids
            if team not in set(primary)
        ]
        self.repechage = BlockForestRuntimeState.create(
            nonqualifiers,
            block_count=self.repechage_slots,
            competition_id=self.competition_id,
            reference_year=self.reference_year,
            stage_id=self.stage["stage_id"],
            stage_code=self.stage["stage_code"],
            phase_code="REPECHAGE_GLOBAL",
            group_id="",
            group_name="全県",
            generation_seed=self.generation_seed,
            match_resolver=self.match_resolver,
            resolved_match_sink=self.match_simulation_results,
        )

    def contains_match(self, match_id: str) -> bool:
        if any(
            match_id in runtime.matches
            for runtime in self.primary.block_runtimes
        ):
            return True
        self._activate_repechage()
        return bool(
            self.repechage
            and any(
                match_id in runtime.matches
                for runtime in self.repechage.block_runtimes
            )
        )

    def ready_matches(self) -> list[dict]:
        if not self.primary.is_complete:
            return self.primary.ready_matches()
        self._activate_repechage()
        return self.repechage.ready_matches()

    def resolve_match(self, match_id: str) -> MatchResolution:
        if not self.primary.is_complete:
            result = self.primary.resolve_match(match_id)
            self._activate_repechage()
            return result
        self._activate_repechage()
        return self.repechage.resolve_match(match_id)

    def resolve_ready_round(self) -> list[MatchResolution]:
        if not self.primary.is_complete:
            results = self.primary.resolve_ready_round()
            self._activate_repechage()
            return results
        self._activate_repechage()
        return self.repechage.resolve_ready_round()

    def resolve_all(self) -> list[str]:
        self.primary.resolve_all()
        self._activate_repechage()
        self.repechage.resolve_all()
        return self.output_school_ids()

    def output_school_ids(self) -> list[str]:
        if not self.is_complete:
            raise ValueError("FMT005 output unavailable before completion")
        return self.primary.winners() + self.repechage.winners()

    def to_matches(self) -> list[Match]:
        matches = self.primary.to_matches()
        if self.primary.is_complete:
            self._activate_repechage()
        if self.repechage is not None:
            matches.extend(self.repechage.to_matches())
        return matches

    def stage_execution(self) -> StageExecution:
        if not self.is_complete:
            raise ValueError("FMT005 StageExecution unavailable before completion")
        primary = self.primary.winners()
        repechage = self.repechage.winners()
        outputs = primary + repechage
        output_set = set(outputs)
        accounting = {}
        for group in self.repo.groups_by_stage.get(
            self.stage["stage_id"], []
        ):
            accounting[group["stage_group_id"]] = len(
                output_set
                & self.repo.group_school_ids(
                    group,
                    self.reference_year,
                )
            )
        return StageExecution(
            stage_id=self.stage["stage_id"],
            stage_code=self.stage["stage_code"],
            format_model_id="FMT005",
            entrant_school_ids=list(self.entrant_school_ids),
            output_school_ids=outputs,
            matches=self.to_matches(),
            metadata={
                "primary_qualifier_count": len(primary),
                "primary_nonqualifier_count": (
                    len(self.entrant_school_ids) - len(primary)
                ),
                "repechage_qualifier_count": len(repechage),
                "primary_block_sizes": [
                    len(block) for block in self.primary.blocks
                ],
                "repechage_block_sizes": [
                    len(block) for block in self.repechage.blocks
                ],
                "accounting_group_output_counts": accounting,
            },
        )
