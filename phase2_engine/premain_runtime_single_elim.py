from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from .models import Match, MatchResolution
from .premain_runtime_common import (
    RuntimePreMainMatch,
    resolve_runtime_match,
    source_value,
    team_source,
    winner_source,
)
from .randomness import shuffled
from .tournament_runtime import (
    MATCH_BYE,
    MATCH_COMPLETED,
    MATCH_READY,
    MATCH_WAITING,
)


@dataclass
class SingleEliminationRuntimeState:
    competition_id: str
    reference_year: int
    generation_seed: int
    stage_id: str
    stage_code: str
    phase_code: str
    group_id: str
    group_name: str
    entrant_school_ids: List[str]
    matches: Dict[str, RuntimePreMainMatch]
    match_order: List[str]
    match_ids_by_round: Dict[int, List[str]]
    match_resolver: object | None = field(default=None, repr=False)
    match_simulation_results: Dict[str, dict] = field(default_factory=dict)
    eliminated_by_round: Dict[int, List[str]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @classmethod
    def create(
        cls,
        teams: Iterable[str],
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
    ) -> "SingleEliminationRuntimeState":
        active = shuffled(
            teams,
            generation_seed,
            f"{competition_id}:{stage_id}:{group_id}:draw",
        )
        if not active:
            raise ValueError("single elimination runtime requires entrants")

        matches = {}
        order = []
        by_round = {}
        sources = [team_source(team) for team in active]
        round_no = 1
        match_seq = 1
        while len(sources) > 1:
            next_sources = []
            round_ids = []
            for i in range(0, len(sources), 2):
                source1 = sources[i]
                source2 = sources[i + 1] if i + 1 < len(sources) else ""
                match_id = (
                    f"{stage_id}-{group_id or 'GLOBAL'}-"
                    f"{phase_code}-{match_seq:03d}"
                )
                matches[match_id] = RuntimePreMainMatch(
                    match_id=match_id,
                    competition_id=competition_id,
                    stage_id=stage_id,
                    stage_code=stage_code,
                    phase_code=phase_code,
                    round_no=round_no,
                    group_id=group_id,
                    group_name=group_name,
                    match_seq=match_seq,
                    source1=source1,
                    source2=source2,
                    structural_bye=not bool(source2),
                )
                order.append(match_id)
                round_ids.append(match_id)
                next_sources.append(winner_source(match_id))
                match_seq += 1
            by_round[round_no] = round_ids
            sources = next_sources
            round_no += 1

        sink = resolved_match_sink if resolved_match_sink is not None else {}
        state = cls(
            competition_id=competition_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            stage_id=stage_id,
            stage_code=stage_code,
            phase_code=phase_code,
            group_id=group_id,
            group_name=group_name,
            entrant_school_ids=list(active),
            matches=matches,
            match_order=order,
            match_ids_by_round=by_round,
            match_resolver=match_resolver,
            match_simulation_results=sink,
        )
        state._refresh_statuses()
        state._validate()
        return state

    def _refresh_statuses(self) -> None:
        changed = True
        while changed:
            changed = False
            for match_id in self.match_order:
                match = self.matches[match_id]
                if match.status in {MATCH_COMPLETED, MATCH_BYE}:
                    continue
                team1 = source_value(match.source1, self.matches)
                team2 = source_value(match.source2, self.matches)
                if match.team1 != team1:
                    match.team1 = team1
                    changed = True
                if match.team2 != team2:
                    match.team2 = team2
                    changed = True

                if match.structural_bye:
                    if match.team1:
                        match.winner = match.team1
                        match.is_bye = True
                        match.status = MATCH_BYE
                        changed = True
                    else:
                        match.status = MATCH_WAITING
                    continue
                match.status = (
                    MATCH_READY
                    if match.team1 and match.team2
                    else MATCH_WAITING
                )

    @property
    def is_complete(self) -> bool:
        if not self.matches:
            return True
        return all(
            match.status in {MATCH_COMPLETED, MATCH_BYE}
            for match in self.matches.values()
        )

    def ready_matches(self) -> list[dict]:
        return [
            self.matches[mid].public_dict()
            for mid in self.match_order
            if self.matches[mid].status == MATCH_READY
        ]

    def resolve_match(self, match_id: str) -> MatchResolution:
        if match_id not in self.matches:
            raise KeyError(f"unknown match_id: {match_id}")
        match = self.matches[match_id]
        if match.status != MATCH_READY:
            raise ValueError(
                f"{match_id}: match is not ready (status={match.status})"
            )
        resolution = resolve_runtime_match(
            match,
            competition_id=self.competition_id,
            reference_year=self.reference_year,
            generation_seed=self.generation_seed,
            namespace=(
                f"{self.competition_id}:{self.stage_id}:{self.group_id}:"
                f"R{match.round_no}:M{match.match_seq}:"
                f"{match.team1}:{match.team2}"
            ),
            match_resolver=self.match_resolver,
            resolved_match_sink=self.match_simulation_results,
        )
        self.eliminated_by_round[match.round_no].append(match.loser)
        self._refresh_statuses()
        self._validate()
        return resolution

    def resolve_ready_round(self) -> list[MatchResolution]:
        ready = self.ready_matches()
        if not ready:
            return []
        round_no = min(row["round_no"] for row in ready)
        return [
            self.resolve_match(row["match_id"])
            for row in ready
            if row["round_no"] == round_no
        ]

    def resolve_all(self) -> list[str]:
        while not self.is_complete:
            if not self.resolve_ready_round():
                raise RuntimeError("single elimination runtime stalled")
        return self.ranking()

    def champion(self) -> str:
        if len(self.entrant_school_ids) == 1:
            return self.entrant_school_ids[0]
        if not self.is_complete:
            return ""
        return self.matches[self.match_order[-1]].winner

    def ranking(self) -> list[str]:
        if not self.is_complete:
            raise ValueError("ranking unavailable before completion")
        ranking = [self.champion()]
        for round_no in sorted(self.eliminated_by_round, reverse=True):
            ranking.extend(
                shuffled(
                    self.eliminated_by_round[round_no],
                    self.generation_seed,
                    f"{self.competition_id}:{self.stage_id}:"
                    f"{self.group_id}:rank_tiebreak:{round_no}",
                )
            )
        return ranking

    def to_matches(self) -> list[Match]:
        return [
            Match(
                match_id=m.match_id,
                competition_id=m.competition_id,
                stage_id=m.stage_id,
                stage_code=m.stage_code,
                phase_code=m.phase_code,
                round_no=m.round_no,
                group_id=m.group_id,
                group_name=m.group_name,
                team1=m.team1,
                team2=m.team2,
                winner=m.winner,
                loser=m.loser,
                is_bye=m.is_bye,
                metadata=dict(m.metadata),
            )
            for m in (self.matches[mid] for mid in self.match_order)
        ]

    def _validate(self) -> None:
        for match_id in self.match_order:
            match = self.matches[match_id]
            if match.status == MATCH_READY and (
                not match.team1 or not match.team2
            ):
                raise ValueError(f"{match_id}: ready match lacks participants")
            if match.status == MATCH_COMPLETED and (
                not match.winner or not match.loser
            ):
                raise ValueError(f"{match_id}: completed match lacks result")
            if match.status == MATCH_BYE and (
                not match.winner or match.loser
            ):
                raise ValueError(f"{match_id}: invalid bye")
