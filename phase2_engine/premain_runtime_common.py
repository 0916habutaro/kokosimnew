from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from .brackets import _resolve_match, random_winner_resolver
from .models import MatchResolution
from .tournament_runtime import MATCH_BYE, MATCH_COMPLETED, MATCH_WAITING


@dataclass
class RuntimePreMainMatch:
    match_id: str
    competition_id: str
    stage_id: str
    stage_code: str
    phase_code: str
    round_no: int
    group_id: str = ""
    group_name: str = ""
    team1: str = ""
    team2: str = ""
    winner: str = ""
    loser: str = ""
    status: str = MATCH_WAITING
    is_bye: bool = False
    match_seq: int = 0
    source1: str = ""
    source2: str = ""
    structural_bye: bool = False
    metadata: dict = field(default_factory=dict)

    def public_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "competition_id": self.competition_id,
            "stage_id": self.stage_id,
            "stage_code": self.stage_code,
            "phase_code": self.phase_code,
            "round_no": self.round_no,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "team1": self.team1,
            "team2": self.team2,
            "winner": self.winner,
            "loser": self.loser,
            "status": self.status,
            "is_bye": self.is_bye,
            "metadata": dict(self.metadata),
        }


def resolve_runtime_match(
    match: RuntimePreMainMatch,
    *,
    competition_id: str,
    reference_year: int,
    generation_seed: int,
    namespace: str,
    match_resolver,
    resolved_match_sink: Dict[str, dict],
) -> MatchResolution:
    resolution = _resolve_match(
        match_id=match.match_id,
        competition_id=competition_id,
        reference_year=reference_year,
        generation_seed=generation_seed,
        team1=match.team1,
        team2=match.team2,
        namespace=namespace,
        winner_resolver=random_winner_resolver(generation_seed),
        match_resolver=match_resolver,
        resolved_match_sink=resolved_match_sink,
    )
    match.winner = resolution.winner_id
    match.loser = resolution.loser_id
    match.status = MATCH_COMPLETED
    if resolution.score_source:
        match.metadata["winner_source"] = resolution.score_source
    if resolution.team1_score is not None:
        match.metadata["score_source"] = resolution.score_source
        match.metadata["team1_score"] = resolution.team1_score
        match.metadata["team2_score"] = resolution.team2_score
    return resolution


def team_source(school_id: str) -> str:
    return f"team:{school_id}"


def winner_source(match_id: str) -> str:
    return f"match:{match_id}"


def source_value(source: str, matches: Dict[str, RuntimePreMainMatch]) -> str:
    if not source:
        return ""
    if source.startswith("team:"):
        return source[5:]
    if source.startswith("match:"):
        match = matches[source[6:]]
        if match.status in {MATCH_COMPLETED, MATCH_BYE}:
            return match.winner
        return ""
    raise ValueError(f"unknown participant source: {source}")
