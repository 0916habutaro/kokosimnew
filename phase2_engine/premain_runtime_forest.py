from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence

from .brackets import balanced_partition
from .models import Match, MatchResolution
from .premain_runtime_single_elim import SingleEliminationRuntimeState


@dataclass
class BlockForestRuntimeState:
    competition_id: str
    reference_year: int
    generation_seed: int
    stage_id: str
    stage_code: str
    phase_code: str
    group_id: str
    group_name: str
    entrant_school_ids: List[str]
    blocks: List[List[str]]
    block_runtimes: List[SingleEliminationRuntimeState]
    match_simulation_results: Dict[str, dict] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        teams: Iterable[str],
        *,
        block_count: int,
        competition_id: str,
        reference_year: int,
        stage_id: str,
        stage_code: str,
        phase_code: str,
        group_id: str,
        group_name: str,
        generation_seed: int,
        match_resolver=None,
        resolved_match_sink: Dict[str, dict] | None = None,
    ) -> "BlockForestRuntimeState":
        items = list(teams)
        blocks = balanced_partition(
            items,
            block_count,
            base_seed=generation_seed,
            namespace=(
                f"{competition_id}:{stage_id}:{group_id}:"
                f"{phase_code}:forest_partition"
            ),
        )
        sink = resolved_match_sink if resolved_match_sink is not None else {}
        runtimes = [
            SingleEliminationRuntimeState.create(
                block,
                competition_id=competition_id,
                reference_year=reference_year,
                stage_id=stage_id,
                stage_code=stage_code,
                phase_code=phase_code,
                group_id=f"{group_id or 'GLOBAL'}-B{index:02d}",
                group_name=group_name,
                generation_seed=generation_seed,
                match_resolver=match_resolver,
                resolved_match_sink=sink,
            )
            for index, block in enumerate(blocks, start=1)
        ]
        return cls(
            competition_id=competition_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            stage_id=stage_id,
            stage_code=stage_code,
            phase_code=phase_code,
            group_id=group_id,
            group_name=group_name,
            entrant_school_ids=items,
            blocks=blocks,
            block_runtimes=runtimes,
            match_simulation_results=sink,
        )

    @classmethod
    def create_from_blocks(
        cls,
        blocks: Sequence[Sequence[str]],
        *,
        competition_id: str,
        reference_year: int,
        stage_id: str,
        stage_code: str,
        phase_code: str,
        group_id: str,
        group_name: str,
        generation_seed: int,
        match_resolver=None,
        resolved_match_sink: Dict[str, dict] | None = None,
    ) -> "BlockForestRuntimeState":
        normalized = [list(block) for block in blocks]
        if not normalized or any(not block for block in normalized):
            raise ValueError("block forest requires non-empty blocks")
        items = [team for block in normalized for team in block]
        if len(items) != len(set(items)):
            raise ValueError("block forest blocks contain duplicate entrants")
        sink = resolved_match_sink if resolved_match_sink is not None else {}
        runtimes = [
            SingleEliminationRuntimeState.create(
                block,
                competition_id=competition_id,
                reference_year=reference_year,
                stage_id=stage_id,
                stage_code=stage_code,
                phase_code=phase_code,
                group_id=f"{group_id or 'GLOBAL'}-B{index:02d}",
                group_name=group_name,
                generation_seed=generation_seed,
                match_resolver=match_resolver,
                resolved_match_sink=sink,
            )
            for index, block in enumerate(normalized, start=1)
        ]
        return cls(
            competition_id=competition_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            stage_id=stage_id,
            stage_code=stage_code,
            phase_code=phase_code,
            group_id=group_id,
            group_name=group_name,
            entrant_school_ids=items,
            blocks=normalized,
            block_runtimes=runtimes,
            match_simulation_results=sink,
        )

    @property
    def is_complete(self) -> bool:
        return all(runtime.is_complete for runtime in self.block_runtimes)

    def ready_matches(self) -> list[dict]:
        return [
            row
            for runtime in self.block_runtimes
            for row in runtime.ready_matches()
        ]

    def resolve_match(self, match_id: str) -> MatchResolution:
        for runtime in self.block_runtimes:
            if match_id in runtime.matches:
                return runtime.resolve_match(match_id)
        raise KeyError(f"unknown match_id: {match_id}")

    def resolve_ready_round(self) -> list[MatchResolution]:
        results = []
        for runtime in self.block_runtimes:
            results.extend(runtime.resolve_ready_round())
        return results

    def resolve_all(self) -> list[str]:
        for runtime in self.block_runtimes:
            runtime.resolve_all()
        return self.winners()

    def winners(self) -> list[str]:
        if not self.is_complete:
            raise ValueError("forest winners unavailable before completion")
        return [runtime.champion() for runtime in self.block_runtimes]

    def to_matches(self) -> list[Match]:
        matches = []
        for block_no, runtime in enumerate(self.block_runtimes, start=1):
            for match in runtime.to_matches():
                match.group_id = self.group_id
                match.group_name = self.group_name
                match.metadata["block_no"] = block_no
                matches.append(match)
        return matches
