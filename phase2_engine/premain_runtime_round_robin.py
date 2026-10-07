from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Sequence

from .models import Match, MatchResolution
from .premain_runtime_common import RuntimePreMainMatch, resolve_runtime_match
from .randomness import shuffled
from .tournament_runtime import MATCH_COMPLETED, MATCH_READY


@dataclass
class RoundRobinRuntimeState:
    competition_id: str
    reference_year: int
    generation_seed: int
    stage_id: str
    stage_code: str
    phase_code: str
    group_id: str
    group_name: str
    pool_no: int
    entrant_school_ids: List[str]
    matches: Dict[str, RuntimePreMainMatch]
    match_order: List[str]
    match_resolver: object | None = field(default=None, repr=False)
    match_simulation_results: Dict[str, dict] = field(default_factory=dict)
    wins: Dict[str, int] = field(default_factory=dict)
    losses: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        teams: Sequence[str],
        *,
        competition_id: str,
        reference_year: int,
        stage_id: str,
        stage_code: str,
        phase_code: str,
        group_id: str,
        group_name: str,
        pool_no: int,
        generation_seed: int,
        match_resolver=None,
        resolved_match_sink: Dict[str, dict] | None = None,
    ) -> "RoundRobinRuntimeState":
        items = list(teams)
        matches = {}
        order = []
        seq = 1
        for team1, team2 in combinations(items, 2):
            match_id = (
                f"{stage_id}-{group_id or 'GLOBAL'}-{phase_code}-"
                f"P{pool_no:02d}-M{seq:03d}"
            )
            matches[match_id] = RuntimePreMainMatch(
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
                match_seq=seq,
                metadata={"pool_no": pool_no},
            )
            order.append(match_id)
            seq += 1
        return cls(
            competition_id=competition_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            stage_id=stage_id,
            stage_code=stage_code,
            phase_code=phase_code,
            group_id=group_id,
            group_name=group_name,
            pool_no=pool_no,
            entrant_school_ids=items,
            matches=matches,
            match_order=order,
            match_resolver=match_resolver,
            match_simulation_results=(
                resolved_match_sink if resolved_match_sink is not None else {}
            ),
            wins={team: 0 for team in items},
            losses={team: 0 for team in items},
        )

    @property
    def is_complete(self) -> bool:
        return all(
            match.status == MATCH_COMPLETED
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
            raise ValueError(f"{match_id}: match is not ready")
        resolution = resolve_runtime_match(
            match,
            competition_id=self.competition_id,
            reference_year=self.reference_year,
            generation_seed=self.generation_seed,
            namespace=(
                f"{self.competition_id}:{self.stage_id}:{self.group_id}:"
                f"{self.phase_code}:P{self.pool_no}:M{match.match_seq}:"
                f"{match.team1}:{match.team2}"
            ),
            match_resolver=self.match_resolver,
            resolved_match_sink=self.match_simulation_results,
        )
        self.wins[match.winner] += 1
        self.losses[match.loser] += 1
        match.metadata["pool_no"] = self.pool_no
        return resolution

    def resolve_all(self) -> list[str]:
        for row in list(self.ready_matches()):
            self.resolve_match(row["match_id"])
        return self.ranking()

    def ranking(self) -> list[str]:
        if not self.is_complete:
            raise ValueError("round robin ranking unavailable before completion")
        tie_order = shuffled(
            self.entrant_school_ids,
            self.generation_seed,
            f"{self.competition_id}:{self.stage_id}:{self.group_id}:"
            f"{self.phase_code}:P{self.pool_no}:tiebreak",
        )
        tie_idx = {team: i for i, team in enumerate(tie_order)}
        return sorted(
            self.entrant_school_ids,
            key=lambda team: (-self.wins[team], tie_idx[team]),
        )

    def standings(self) -> Dict[str, Dict[str, int]]:
        return {
            team: {"wins": self.wins[team], "losses": self.losses[team]}
            for team in self.entrant_school_ids
        }

    def to_matches(self) -> list[Match]:
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
            for m in (self.matches[mid] for mid in self.match_order)
        ]
