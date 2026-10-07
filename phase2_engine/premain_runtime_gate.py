from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from .models import Match, MatchResolution
from .premain_runtime_common import RuntimePreMainMatch, resolve_runtime_match
from .randomness import shuffled
from .tournament_runtime import MATCH_BYE, MATCH_COMPLETED, MATCH_READY


@dataclass
class SingleRoundGateRuntimeState:
    competition_id: str
    reference_year: int
    generation_seed: int
    stage_id: str
    stage_code: str
    phase_code: str
    entrant_school_ids: List[str]
    matches: Dict[str, RuntimePreMainMatch]
    match_order: List[str]
    match_resolver: object | None = field(default=None, repr=False)
    match_simulation_results: Dict[str, dict] = field(default_factory=dict)

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
        generation_seed: int,
        match_resolver=None,
        resolved_match_sink: Dict[str, dict] | None = None,
    ) -> "SingleRoundGateRuntimeState":
        entrants = shuffled(
            teams,
            generation_seed,
            f"{competition_id}:{stage_id}:gate_draw",
        )
        matches = {}
        order = []
        seq = 1
        i = 0
        while i < len(entrants):
            team1 = entrants[i]
            match_id = f"{stage_id}-GLOBAL-{seq:03d}"
            if i + 1 >= len(entrants):
                matches[match_id] = RuntimePreMainMatch(
                    match_id=match_id,
                    competition_id=competition_id,
                    stage_id=stage_id,
                    stage_code=stage_code,
                    phase_code=phase_code,
                    round_no=1,
                    team1=team1,
                    winner=team1,
                    status=MATCH_BYE,
                    is_bye=True,
                    match_seq=seq,
                    metadata={"reason": "odd_entrant_count"},
                )
                order.append(match_id)
                break
            team2 = entrants[i + 1]
            matches[match_id] = RuntimePreMainMatch(
                match_id=match_id,
                competition_id=competition_id,
                stage_id=stage_id,
                stage_code=stage_code,
                phase_code=phase_code,
                round_no=1,
                team1=team1,
                team2=team2,
                status=MATCH_READY,
                match_seq=seq,
            )
            order.append(match_id)
            seq += 1
            i += 2

        return cls(
            competition_id=competition_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            stage_id=stage_id,
            stage_code=stage_code,
            phase_code=phase_code,
            entrant_school_ids=entrants,
            matches=matches,
            match_order=order,
            match_resolver=match_resolver,
            match_simulation_results=(
                resolved_match_sink if resolved_match_sink is not None else {}
            ),
        )

    @property
    def is_complete(self) -> bool:
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
            raise ValueError(f"{match_id}: match is not ready")
        return resolve_runtime_match(
            match,
            competition_id=self.competition_id,
            reference_year=self.reference_year,
            generation_seed=self.generation_seed,
            namespace=(
                f"{self.competition_id}:{self.stage_id}:GATE:"
                f"M{match.match_seq}:{match.team1}:{match.team2}"
            ),
            match_resolver=self.match_resolver,
            resolved_match_sink=self.match_simulation_results,
        )

    def resolve_all(self) -> list[str]:
        for row in list(self.ready_matches()):
            self.resolve_match(row["match_id"])
        return self.winners()

    def winners(self) -> list[str]:
        if not self.is_complete:
            raise ValueError("gate winners unavailable before completion")
        return [self.matches[mid].winner for mid in self.match_order]

    def to_matches(self) -> list[Match]:
        return [
            Match(
                match_id=m.match_id,
                competition_id=m.competition_id,
                stage_id=m.stage_id,
                stage_code=m.stage_code,
                phase_code=m.phase_code,
                round_no=1,
                team1=m.team1,
                team2=m.team2,
                winner=m.winner,
                loser=m.loser,
                is_bye=m.is_bye,
                metadata=dict(m.metadata),
            )
            for m in (self.matches[mid] for mid in self.match_order)
        ]
